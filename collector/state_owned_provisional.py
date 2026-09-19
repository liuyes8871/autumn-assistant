from __future__ import annotations

"""数量优先的国企公开岗位临时采集器。

The reviewed collector deliberately refuses to run ``TARGET`` sources.  That
is the right rule for the formal catalogue, but it also meant that a public
recruitment page with visible jobs contributed zero rows until a person had
completed the whole source review checklist.  This module is the bounded,
separate bridge for that gap:

* it only opens HTTPS pages already discovered from a company's public site;
* it does not execute JavaScript, use cookies, log in, or bypass a challenge;
* every row is labelled provisional and remains outside the VERIFIED source
  registry;
* the existing normalisation, deduplication and humanities/social/business
  audience decision are reused before a row is offered for publication.

The output is intentionally a standalone audit artifact.  A future UI can
import the ``eligibleJobs`` array behind a visible “公开入口临时采集 · 待核验”
label without changing the formal catalogue contract.
"""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx

from .adapters import (
    USER_AGENT,
    _ats_campus_item_allowed,
    _ats_raw_job,
    _dom_node_is_visible,
)
from .audience_policy import AudienceDecision, assess_job
from .feeds import JsonLdCampusAdapter, PublicFeedAdapter, StaticHtmlCampusAdapter, jsonld_job_parser
from .http_cache import response_content_hash, response_headers
from .normalize import normalize_job
from .quality import deduplicate
from .schema import NormalizedJob, RawJob, SourceConfig, model_json
from .state_owned_discovery import traffic_domain


PROVISIONAL_SCHEMA_VERSION = 1
DEFAULT_INTERVAL_SECONDS = 0.5
DEFAULT_WORKERS = 8
MAX_PAGE_BYTES = 4 * 1024 * 1024
SITEMAP_MARKERS = ("sitemap", "site-map")
FEED_MARKERS = ("/rss", "/atom", "/feed", ".rss", ".atom", ".xml")
JOB_TITLE_STOPWORDS = frozenset(
    {
        "招聘岗位",
        "职位名称",
        "岗位名称",
        "职位",
        "岗位",
        "招聘信息",
        "人才招聘",
        "加入我们",
        "更多",
        "详情",
        "查看详情",
        "申请职位",
        "立即申请",
    }
)
GENERIC_LINK_STOPWORDS = frozenset(
    {
        "首页",
        "关于我们",
        "新闻中心",
        "联系我们",
        "人才理念",
        "人才发展",
        "社会招聘",
        "校园招聘",
        "招聘",
        "人才",
        "加入我们",
        "了解更多",
        "查看",
        "详情",
        "下载",
        "登录",
        "注册",
    }
)


def _text(value: Any, limit: int = 12_000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())[:limit]


def _camel_key(key: str) -> str:
    parts = str(key).split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _camelize(value: Any) -> Any:
    """Translate the collector's internal snake_case JSON to the web contract."""

    if isinstance(value, Mapping):
        return {_camel_key(str(key)): _camelize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


def _web_locations(job: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Make an unknown Chinese-company location usable by the default filter.

    The source pages often omit a city altogether.  These candidates are all
    Chinese listed companies, so the safe UI representation is mainland China
    with an explicit "地点待确认" label rather than silently disappearing from
    the default mainland view.  We do not invent a province or city.
    """

    locations = job.get("locations")
    if not isinstance(locations, list) or not locations:
        return [{"scope": "MAINLAND_CHINA", "countryCode": "CN", "provinceCode": None, "cityCode": None, "districtCode": None, "displayName": "地点待确认", "raw": "未知"}]
    result: list[dict[str, Any]] = []
    city_markers = ("北京", "上海", "天津", "重庆", "广州", "深圳", "杭州", "南京", "武汉", "成都", "西安", "全国", "远程")
    requirement_markers = re.compile(r"学历|专业|经验|熟悉|负责|能够|具备|要求|流程|分析|优先")
    for value in locations:
        if not isinstance(value, Mapping):
            continue
        item = dict(value)
        scope = str(item.get("scope") or "UNKNOWN")
        if scope == "UNKNOWN":
            label = str(item.get("displayName") or item.get("raw") or "")
            # ``normalize_job`` may interpret a requirements column as a
            # location when a legacy table has no city column.  Those values
            # must not become dozens of fake cities in the filter UI.
            if not any(marker in label for marker in city_markers) or len(label) > 80 or requirement_markers.search(label):
                continue
            item["scope"] = "MAINLAND_CHINA"
            item["countryCode"] = item.get("countryCode") or "CN"
            item["displayName"] = label
            item["raw"] = item.get("raw") or label
        result.append(item)
    return result or [{"scope": "MAINLAND_CHINA", "countryCode": "CN", "provinceCode": None, "cityCode": None, "districtCode": None, "displayName": "地点待确认", "raw": "未知"}]


def build_web_catalog(report: Mapping[str, Any], *, include_review: bool = False) -> dict[str, Any]:
    """Build a separately labelled, browser-readable provisional job catalog.

    The formal catalog remains untouched.  By default only rows that pass the
    existing generalist audience gate are exposed; ``include_review`` is an
    explicit opt-in for operators who prefer maximum recall over noise.
    """

    field = "quantityFirstJobs" if include_review else "eligibleJobs"
    values = report.get(field) or []
    # Older provisional reports were written before the quantity-first array
    # was added.  Their sourceResults still contain the parsed public rows, so
    # rebuild the eligible + NEEDS_REVIEW lane locally instead of silently
    # falling back to the old eligible-only list.  This keeps a rerun from
    # needing to hit hundreds of public pages merely to republish a snapshot.
    if include_review and not values:
        values = _rebuild_quantity_first_jobs(report)
    elif not include_review and not values:
        values = report.get("jobs") or []
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            continue
        job = _camelize(value)
        job_id = str(job.get("id") or "")
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        job["provisional"] = True
        job["publicationLabel"] = "公开入口临时采集 · 待核验"
        job["sourceStatus"] = "TARGET"
        company_name = str(job.get("companyName") or "公开入口")
        job["sourceName"] = f"{company_name} · 公开入口临时采集"
        job["locations"] = _web_locations(job)
        city = str(job.get("city") or "").strip()
        if not city or city == "未知" or len(city) > 80 or re.search(r"学历|专业|经验|熟悉|负责|能够|具备|要求", city):
            job["city"] = "地点待确认"
        jobs.append(job)
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    job_company_count = len({str(job.get("companyId") or "") for job in jobs if job.get("companyId")})
    eligible_count = sum(1 for job in jobs if job.get("audienceDecision") == AudienceDecision.TARGET_GENERALIST.value)
    review_count = sum(1 for job in jobs if job.get("audienceDecision") == AudienceDecision.NEEDS_REVIEW.value)
    return {
        "schemaVersion": 1,
        "generatedAt": report.get("generatedAt"),
        "reportType": "state_owned_provisional_web_catalog",
        "provisional": True,
        "sourceStatus": "TARGET",
        "publicationLabel": "公开入口临时采集 · 待核验",
        "verificationMode": "RELAXED_PUBLIC_ENTRY",
        "quantityFirst": True,
        "includesNeedsReview": bool(include_review),
        "summary": {
            "jobCount": len(jobs),
            "companyCount": job_company_count or summary.get("companyCountWithEligibleJobs", 0),
            "eligibleJobCount": eligible_count or summary.get("eligibleJobCount", len(jobs)),
            "reviewJobCount": review_count or summary.get("reviewJobCount", 0),
            "sourcePageCount": summary.get("pageCount", 0),
        },
        "jobs": jobs,
    }


def _rebuild_quantity_first_jobs(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Recreate quantity-first rows from a legacy report's page snapshots.

    ``sourceResults`` are already the parser output captured by the previous
    run.  Reusing them is deterministic, does not make network requests, and
    applies the same normalisation, deduplication and audience policy as a
    fresh collection.  Technical/medical/legal/design rows remain excluded;
    only rows that pass or need an audience decision are returned.
    """

    pages = report.get("sourceResults") if isinstance(report, Mapping) else None
    if not isinstance(pages, list) or not pages:
        return []
    generated_at = report.get("generatedAt")
    try:
        value = str(generated_at or "")
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        now = datetime.fromisoformat(value) if value else datetime.now(UTC)
    except (TypeError, ValueError):
        now = datetime.now(UTC)
    all_normalized: list[NormalizedJob] = []
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        normalized, _, _ = _normalise_page_jobs(page, now=now)
        all_normalized.extend(normalized)
    unique_normalized = deduplicate(all_normalized)
    return [
        model_json(job)
        for job in unique_normalized
        if job.audience_decision in {
            AudienceDecision.TARGET_GENERALIST.value,
            AudienceDecision.NEEDS_REVIEW.value,
        }
    ]


def _safe_url(value: Any, *, base_url: str) -> str | None:
    raw = _text(value, 2_000)
    if not raw or raw.startswith(("javascript:", "data:", "mailto:", "tel:", "#")):
        return None
    absolute = urljoin(base_url, raw)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    # Fragments are navigation state, not a distinct job endpoint. Removing
    # them also prevents the same page from being fetched repeatedly.
    return urlunparse(parsed._replace(fragment=""))


def _host(value: str | None) -> str:
    return (urlparse(str(value or "")).hostname or "").lower().rstrip(".")


def _is_sitemap(value: str) -> bool:
    path = urlparse(value).path.lower()
    return any(marker in path for marker in SITEMAP_MARKERS)


def _is_feed(value: str) -> bool:
    parsed = urlparse(value)
    path = (parsed.path or "").lower()
    return any(marker in path for marker in FEED_MARKERS)


def _domain_allowed(host: str, source: SourceConfig) -> bool:
    allowed = [source.apply_domain, *source.apply_domains, *( [source.ats_host] if source.ats_host else [])]
    host = host.lower().rstrip(".")
    for value in allowed:
        domain = str(value or "").lower().strip().lstrip("*.").rstrip(".")
        if domain and (host == domain or host.endswith("." + domain)):
            return True
    return False


def _candidate_name(candidate: Mapping[str, Any]) -> str:
    return _text(
        candidate.get("shortName")
        or candidate.get("short_name")
        or candidate.get("legalName")
        or candidate.get("legal_name")
        or candidate.get("stockCode")
        or candidate.get("candidateId")
        or "国企候选公司",
        200,
    )


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    return _text(candidate.get("candidateId") or candidate.get("candidate_id") or "", 200)


def _company_id(candidate: Mapping[str, Any]) -> str:
    # Keep this namespace separate from the formal company registry.  A stock
    # code is stable when available, while the candidate id prevents a missing
    # or malformed code from merging unrelated companies.
    code = re.sub(r"\D", "", _text(candidate.get("stockCode") or candidate.get("stock_code")))
    return f"soe-provisional-{code.zfill(6)}" if code else f"soe-provisional-{_candidate_id(candidate)}"


def _source_id(candidate: Mapping[str, Any], landing_url: str) -> str:
    digest = hashlib.sha256(landing_url.encode("utf-8")).hexdigest()[:12]
    return f"{_company_id(candidate)}-{digest}"


def _entry_items(report: Mapping[str, Any], *, include_review: bool = True) -> list[dict[str, Any]]:
    """Return deduplicated public landing pages from a discovery report."""

    rows = report.get("results", []) if isinstance(report, Mapping) else []
    if not isinstance(rows, list):
        return []
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in rows:
        if not isinstance(candidate, Mapping):
            continue
        classification = str(candidate.get("classification") or "")
        if not include_review and classification != "CONNECTOR_CANDIDATE":
            continue
        candidate_id = _candidate_id(candidate)
        if not candidate_id:
            continue
        entries = candidate.get("entryCandidates") or []
        by_url: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            url = _safe_url(entry.get("landingUrl"), base_url=str(candidate.get("homepageUrl") or ""))
            if url:
                by_url[url] = entry
        links = candidate.get("recruitmentLinks") or []
        for value in links:
            url = _safe_url(value, base_url=str(candidate.get("homepageUrl") or ""))
            if url:
                by_url.setdefault(url, {})
        # A report may describe the homepage itself as a connector candidate.
        if not by_url:
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                url = _safe_url(entry.get("landingUrl"), base_url=str(candidate.get("homepageUrl") or ""))
                if url:
                    by_url[url] = entry
        for url, entry in by_url.items():
            if _is_sitemap(url):
                continue
            key = (candidate_id, url)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "candidate": dict(candidate),
                    "entry": dict(entry),
                    "landingUrl": url,
                    "discoveryClassification": classification,
                }
            )
    return items


def build_provisional_source(item: Mapping[str, Any]) -> SourceConfig | None:
    candidate = item.get("candidate") if isinstance(item.get("candidate"), Mapping) else {}
    landing = _safe_url(item.get("landingUrl"), base_url=str(candidate.get("homepageUrl") or ""))
    if not landing:
        return None
    landing_host = _host(landing)
    homepage_host = _host(str(candidate.get("homepageUrl") or ""))
    if not landing_host:
        return None
    entry = item.get("entry") if isinstance(item.get("entry"), Mapping) else {}
    detected = str(entry.get("detectedAts") or "").upper()
    if detected in {"JSONLD", "JOBPOSTING"} or int(entry.get("structuredJobCount") or 0) > 0:
        adapter = "jsonld"
        mode = "JSONLD"
    elif _is_feed(landing) or any(_is_feed(str(value)) for value in entry.get("feedLinks") or []):
        adapter = "rss"
        mode = "XML"
    else:
        # HTML is the safe broad fallback.  It parses visible rows and never
        # evaluates page scripts.
        adapter = "provisional_html"
        mode = "HTML"
    apply_domains = [landing_host]
    if homepage_host and homepage_host not in apply_domains:
        apply_domains.append(homepage_host)
    ats_host = landing_host if detected in {"BEISEN", "MOKA", "FEISHU", "GREENHOUSE", "LEVER", "ASHBY"} else None
    return SourceConfig(
        source_id=_source_id(candidate, landing),
        company_id=_company_id(candidate),
        company_name=_candidate_name(candidate),
        source_url=landing,
        apply_domain=landing_host,
        apply_domains=apply_domains,
        ats_host=ats_host,
        source_level="B",
        campus_only=False,
        adapter=adapter,
        access_mode=mode,
        endpoint=landing,
        status="TARGET",
        evidence_urls=[landing],
        detected_ats=detected or None,
        current_cohort_signal=(str(entry.get("currentCohortSignal") or "") or None),
        requires_manual_review=True,
        note="公开招聘入口临时采集；未完成正式来源核验。",
        request_interval_seconds=0,
    )


def _row_title(cells: list[Any], links: list[Any]) -> str:
    for link in links:
        label = _text(link.get_text(" ", strip=True), 240)
        if label and label not in JOB_TITLE_STOPWORDS and len(label) <= 160:
            return label
    for cell in cells:
        label = _text(cell.get_text(" ", strip=True), 240)
        if label and label not in JOB_TITLE_STOPWORDS and len(label) <= 160:
            return label
    return ""


def _looks_like_job_title(value: str) -> bool:
    text = _text(value, 200)
    if not text or text in JOB_TITLE_STOPWORDS or len(text) > 160:
        return False
    if text.casefold() in {value.casefold() for value in GENERIC_LINK_STOPWORDS}:
        return False
    # A row containing a Chinese/English role phrase is useful even when a
    # legacy government site has no explicit application link.  Reject obvious
    # page furniture and date-only announcements.
    if re.fullmatch(r"[\d\-/:. ]+", text):
        return False
    if any(marker in text for marker in ("版权所有", "ICP备", "Copyright", "隐私政策", "网站地图")):
        return False
    return len(text) >= 2


def _recruitment_page_context(page_url: str, page_text: str) -> bool:
    """Whether a page itself looks like a recruitment surface.

    Discovery intentionally over-collects links such as “投资者关系” because
    they sit beside “人才招聘” in older CMS navigation.  Link fallback is
    therefore enabled only for a recruitment-looking path or visible page
    text; table parsing remains available for an explicitly detected table.
    """

    value = f"{urlparse(page_url).path} {page_text}".casefold()
    return any(marker in value for marker in ("招聘", "招贤", "校招", "应届", "人才", "career", "recruit", "campus", "graduate", "jobs", "join"))


def _is_navigation_link(link: Any) -> bool:
    current = link
    while current is not None and getattr(current, "name", None):
        name = str(getattr(current, "name", "")).casefold()
        classes = " ".join(str(value).casefold() for value in (current.get("class") or []))
        ident = str(current.get("id") or "").casefold()
        if name in {"header", "nav", "footer"} or any(token in f"{classes} {ident}" for token in ("nav", "menu", "footer", "header", "topbar", "breadcrumb")):
            return True
        current = getattr(current, "parent", None)
    return False


def _row_job(source: SourceConfig, row: Any, index: int, page_url: str) -> RawJob | None:
    if not _dom_node_is_visible(row):
        return None
    cells = row.find_all(["td", "th"])
    if not cells:
        return None
    # A header-only row is page furniture, not a posting.  Requiring at least
    # one data cell still allows older templates that put the role name in a
    # ``th`` while keeping ordinary ``th`` column headings out.
    if not row.find_all("td"):
        return None
    links = row.find_all("a", href=True)
    title = _row_title(cells, links)
    if not _looks_like_job_title(title):
        return None
    values = [_text(cell.get_text(" ", strip=True), 2_000) for cell in cells]
    href = None
    for link in links:
        href = _safe_url(link.get("href"), base_url=page_url)
        if href:
            break
    apply_url = href or page_url
    # Row index is part of the id when a legacy page exposes no per-job href.
    row_digest = hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:12]
    source_job_id = href or f"row-{index}-{row_digest}"
    location = "未知"
    for value in values[1:]:
        if any(token in value for token in ("北京", "上海", "天津", "重庆", "广州", "深圳", "杭州", "南京", "武汉", "成都", "西安", "全国", "远程")):
            location = value[:240]
            break
    if location == "未知" and len(values) > 1:
        # Older company templates often put requirements in the second
        # column and omit a city entirely.  Do not surface a whole JD as the
        # location in the web list; keep the explicit unknown value instead.
        candidate_location = values[1][:240]
        if candidate_location and len(candidate_location) <= 80 and not re.search(r"学历|专业|经验|熟悉|负责|能够|具备|要求", candidate_location):
            location = candidate_location
    item = {
        "id": source_job_id,
        "title": title,
        "description": " ".join(value for value in values if value),
        "location": location,
        "url": apply_url,
        "requirements": " ".join(values[2:]),
        "isCampus": True,
    }
    if not _ats_campus_item_allowed(item, source):
        return None
    try:
        return _ats_raw_job(
            item,
            source,
            apply_value=apply_url,
            title_value=title,
            location_value=location,
            description_value=item["description"],
            requirement_value=item["requirements"],
            source_job_id=source_job_id,
        )
    except (TypeError, ValueError):
        return None


def _link_job(source: SourceConfig, link: Any, index: int, page_url: str) -> RawJob | None:
    if not _dom_node_is_visible(link):
        return None
    if _is_navigation_link(link):
        return None
    title = _text(link.get_text(" ", strip=True), 200)
    if not _looks_like_job_title(title):
        return None
    href = _safe_url(link.get("href"), base_url=page_url)
    if not href or not _domain_allowed(_host(href), source):
        return None
    parsed_path = urlparse(href).path.casefold()
    parent_text = _text(link.parent.get_text(" ", strip=True) if link.parent else title, 2_000)
    recruitment_link = any(marker in parsed_path for marker in ("job", "recruit", "career", "campus", "position", "vacancy", "zhaopin", "rczp", "xiaozhao"))
    recruitment_title = any(marker in title.casefold() for marker in ("招聘", "校招", "应届", "岗位", "职位", "graduate", "campus", "recruit"))
    date_signal = bool(re.search(r"20\d{2}[年./-]", parent_text))
    if not (recruitment_link or recruitment_title or date_signal):
        return None
    parent = link.parent
    description = parent_text
    item = {
        "id": href or f"link-{index}",
        "title": title,
        "description": description,
        "location": "未知",
        "url": href,
        "requirements": description,
        "isCampus": True,
    }
    if not _ats_campus_item_allowed(item, source):
        return None
    try:
        return _ats_raw_job(
            item,
            source,
            apply_value=href,
            title_value=title,
            location_value="未知",
            description_value=description,
            requirement_value=description,
            source_job_id=href or f"link-{index}",
        )
    except (TypeError, ValueError):
        return None


def parse_provisional_html(content: bytes, *, source: SourceConfig, page_url: str) -> list[RawJob]:
    """Parse JSON-LD, visible tables, and conservative recruitment links."""

    raw = content[:MAX_PAGE_BYTES]
    soup = BeautifulSoup(raw, "html.parser")
    jobs: list[RawJob] = []
    # JSON-LD is the highest-quality fallback and often coexists with a visual
    # table.  It is deduplicated below by the stable job id.
    try:
        from .ats_discovery import extract_jobposting_jsonld

        for index, item in enumerate(extract_jobposting_jsonld(raw, page_url=page_url)):
            if not _ats_campus_item_allowed(item, source):
                continue
            try:
                jobs.append(jsonld_job_parser(item, source))
            except (TypeError, ValueError):
                continue
    except (TypeError, ValueError, UnicodeError):
        pass
    rows = soup.select("table tbody tr") or soup.select("table tr")
    for index, row in enumerate(rows):
        job = _row_job(source, row, index, page_url)
        if job:
            jobs.append(job)
    # Some government templates render a list of recruitment notices without a
    # table.  Only use links when no table jobs were found, and cap the result
    # so a navigation-heavy page cannot flood the provisional report.
    if not jobs and _recruitment_page_context(page_url, _text(soup.get_text(" ", strip=True), 8_000)):
        for index, link in enumerate(soup.find_all("a", href=True)):
            job = _link_job(source, link, index, page_url)
            if job:
                jobs.append(job)
            if len(jobs) >= 200:
                break
    return deduplicate_raw(jobs)


def deduplicate_raw(jobs: Iterable[RawJob]) -> list[RawJob]:
    seen: dict[str, RawJob] = {}
    for job in jobs:
        key = f"{job.source_job_id or ''}|{job.title}|{job.apply_url}".casefold()
        seen.setdefault(key, job)
    return list(seen.values())


def fetch_provisional_page(item: Mapping[str, Any], *, timeout: float = 20.0) -> dict[str, Any]:
    source = build_provisional_source(item)
    candidate = item.get("candidate") if isinstance(item.get("candidate"), Mapping) else {}
    landing = str(item.get("landingUrl") or "")
    base: dict[str, Any] = {
        "candidateId": _candidate_id(candidate),
        "stockCode": candidate.get("stockCode") or candidate.get("stock_code"),
        "companyName": _candidate_name(candidate),
        "landingUrl": landing,
        "discoveryClassification": item.get("discoveryClassification"),
        "adapter": source.adapter if source else None,
        "status": "TARGET",
        "provisional": True,
        "fetchedAt": datetime.now(UTC).isoformat(),
        "statusCode": 0,
        "rawCount": 0,
        "jobs": [],
    }
    if source is None:
        base["error"] = "invalid_https_landing_url"
        return base
    try:
        headers = {"Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml,application/json", "User-Agent": USER_AGENT}
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.get(landing, headers=headers)
            base.update(
                {
                    "statusCode": int(response.status_code),
                    "finalUrl": str(getattr(response, "url", None) or landing),
                    "contentType": str(response.headers.get("content-type") or "").split(";", 1)[0],
                    "bytes": len(response.content),
                    "contentHash": response_content_hash(response),
                    "cacheValidators": {key: response.headers.get(key) for key in ("etag", "last-modified") if response.headers.get(key)},
                }
            )
            if response.status_code in {401, 403, 405, 429}:
                base["blocked"] = True
                base["error"] = "access_control"
                return base
            if response.status_code >= 400:
                base["error"] = f"http_status_{response.status_code}"
                return base
            final_url = str(getattr(response, "url", None) or landing)
            if source.adapter == "rss":
                result = PublicFeedAdapter(client=client).fetch(source)
                jobs = result.jobs
                if result.error:
                    base["error"] = result.error
            elif source.adapter == "jsonld":
                result = JsonLdCampusAdapter(client=client).fetch(source)
                jobs = result.jobs
                if result.error:
                    base["error"] = result.error
            else:
                jobs = parse_provisional_html(response.content, source=source, page_url=final_url)
            base["rawCount"] = len(jobs)
            base["jobs"] = [model_json(job) for job in jobs]
            if not jobs and "error" not in base:
                base["error"] = "no_parseable_public_jobs"
            return base
    except httpx.TimeoutException:
        base["error"] = "timeout"
    except httpx.RequestError as exc:
        base["error"] = f"request_error:{exc.__class__.__name__}"
    except (TypeError, ValueError, UnicodeError) as exc:
        base["error"] = f"parse_error:{exc.__class__.__name__}"
    return base


def _normalise_page_jobs(page: Mapping[str, Any], *, now: datetime) -> tuple[list[NormalizedJob], dict[str, int], list[dict[str, Any]]]:
    source_item = {
        "candidate": {
            "candidateId": page.get("candidateId"),
            "stockCode": page.get("stockCode"),
            "shortName": page.get("companyName"),
            "homepageUrl": page.get("landingUrl"),
        },
        "landingUrl": page.get("landingUrl"),
        "entry": {},
    }
    source = build_provisional_source(source_item)
    if source is None:
        return [], {"normalized": 0, "eligible": 0, "review": 0, "outOfScope": 0, "rejected": len(page.get("jobs") or [])}, []
    counts = {"normalized": 0, "eligible": 0, "review": 0, "outOfScope": 0, "rejected": 0}
    normalized: list[NormalizedJob] = []
    review: list[dict[str, Any]] = []
    for value in page.get("jobs") or []:
        try:
            raw = RawJob.model_validate(value)
            # Rebind to the freshly created source so source metadata and
            # namespace are deterministic even if a parser emitted aliases.
            raw = raw.model_copy(update={"source_id": source.source_id, "company_id": source.company_id, "company_name": source.company_name})
            job = normalize_job(raw, source, now)
            counts["normalized"] += 1
        except (TypeError, ValueError) as exc:
            counts["rejected"] += 1
            review.append({"title": value.get("title") if isinstance(value, Mapping) else "", "reason": str(exc)})
            continue
        assessment = assess_job(job)
        job = job.model_copy(update={"audience_decision": assessment.decision.value, "audience_reason_codes": list(assessment.reason_codes)})
        normalized.append(job)
        if assessment.decision == AudienceDecision.TARGET_GENERALIST:
            counts["eligible"] += 1
        elif assessment.decision == AudienceDecision.NEEDS_REVIEW:
            counts["review"] += 1
            review.append({"jobId": job.id, "title": job.title, "reasonCodes": list(assessment.reason_codes)})
        else:
            counts["outOfScope"] += 1
    return normalized, counts, review


def collect_provisional_jobs(
    discovery_path: Path,
    *,
    output: Path | None = None,
    include_review: bool = True,
    max_pages: int | None = None,
    max_workers: int = DEFAULT_WORKERS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    timeout: float = 20.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    payload = json.loads(discovery_path.read_text(encoding="utf-8"))
    items = _entry_items(payload, include_review=include_review)
    if max_pages is not None:
        items = items[: max(0, int(max_pages))]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        candidate = item.get("candidate") if isinstance(item.get("candidate"), Mapping) else {}
        domain = traffic_domain(_host(str(item.get("landingUrl") or "")) or "unknown")
        grouped[domain].append(item)

    def run_group(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in group:
            rows.append(fetch_provisional_page(item, timeout=timeout))
            if interval_seconds > 0:
                time.sleep(max(0.0, float(interval_seconds)))
        return rows

    page_results: list[dict[str, Any]] = []
    workers = max(1, min(int(max_workers or 1), DEFAULT_WORKERS))
    if grouped:
        with ThreadPoolExecutor(max_workers=min(workers, len(grouped))) as executor:
            futures = [executor.submit(run_group, group) for group in grouped.values()]
            for future in as_completed(futures):
                page_results.extend(future.result())
    page_results.sort(key=lambda value: (str(value.get("stockCode") or ""), str(value.get("landingUrl") or "")))

    all_normalized: list[NormalizedJob] = []
    all_review: list[dict[str, Any]] = []
    totals = {"raw": 0, "normalized": 0, "eligible": 0, "review": 0, "outOfScope": 0, "rejected": 0}
    for page in page_results:
        totals["raw"] += int(page.get("rawCount") or 0)
        normalized, counts, review = _normalise_page_jobs(page, now=now)
        all_normalized.extend(normalized)
        all_review.extend(
            [{"candidateId": page.get("candidateId"), "companyName": page.get("companyName"), "landingUrl": page.get("landingUrl"), **entry} for entry in review]
        )
        for key, value in counts.items():
            totals[key] += value
    unique_normalized = deduplicate(all_normalized)
    eligible_jobs = [job for job in unique_normalized if job.audience_decision == AudienceDecision.TARGET_GENERALIST.value]
    review_jobs = [job for job in unique_normalized if job.audience_decision == AudienceDecision.NEEDS_REVIEW.value]
    # Quantity-first remains a separate lane.  It deliberately excludes
    # out-of-scope technical/medical/legal/design roles, but keeps rows that
    # only lack enough structured requirements for an automatic decision.
    quantity_first_jobs = [*eligible_jobs, *review_jobs]
    quantity_first_companies = {job.company_id for job in quantity_first_jobs}
    adapter_counts: dict[str, int] = defaultdict(int)
    for page in page_results:
        adapter_counts[str(page.get("adapter") or "unknown")] += 1
    blocked = sum(1 for page in page_results if page.get("blocked") or page.get("error") == "access_control")
    errors = sum(1 for page in page_results if page.get("error") and not page.get("blocked"))
    companies_with_jobs = {job.company_id for job in eligible_jobs}
    report = {
        "schemaVersion": PROVISIONAL_SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "reportType": "state_owned_provisional_jobs",
        "provisional": True,
        "sourceStatus": "TARGET",
        "verificationMode": "RELAXED_PUBLIC_ENTRY",
        "publicationLabel": "公开入口临时采集 · 待核验",
        "privacyAndAccess": {
            "publicHttpsOnly": True,
            "loginOrCookies": False,
            "captchaOrAccessControlBypass": False,
            "javascriptExecution": False,
            "formalVerifiedRegistryChanged": False,
        },
        "input": {
            "discoveryReport": discovery_path.name,
            "discoveryReportSha256": hashlib.sha256(discovery_path.read_bytes()).hexdigest(),
            "includeReviewClassifications": bool(include_review),
            "selectedPageCount": len(items),
            "domainCount": len(grouped),
            "maxWorkers": workers,
            "intervalSeconds": max(0.0, float(interval_seconds)),
        },
        "summary": {
            "candidateCompanyCount": len({str(item.get("candidateId")) for item in page_results if item.get("candidateId")}),
            "pageCount": len(page_results),
            "pagesWithJobs": sum(1 for page in page_results if int(page.get("rawCount") or 0) > 0),
            "blockedPageCount": blocked,
            "errorPageCount": errors,
            "rawJobCount": totals["raw"],
            "normalizedJobCount": len(unique_normalized),
            "eligibleJobCount": len(eligible_jobs),
            "reviewJobCount": len(review_jobs),
            "quantityFirstJobCount": len(quantity_first_jobs),
            "outOfScopeJobCount": totals["outOfScope"],
            "rejectedJobCount": totals["rejected"],
            "companyCountWithEligibleJobs": len(companies_with_jobs),
            "companyCountWithQuantityFirstJobs": len(quantity_first_companies),
            "adapterDistribution": dict(sorted(adapter_counts.items())),
        },
        "jobs": [model_json(job) for job in eligible_jobs],
        "eligibleJobs": [model_json(job) for job in eligible_jobs],
        "quantityFirstJobs": [model_json(job) for job in quantity_first_jobs],
        "reviewJobs": all_review[:2000],
        "sourceResults": page_results,
        "quality": {
            "rawParsedBeforeAudienceGate": totals["raw"],
            "normalisedAfterSourceAndCampusChecks": len(unique_normalized),
            "deduplicatedEligible": len(eligible_jobs),
            "audiencePolicy": "humanities-social-business-v1",
        },
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect public state-owned-company jobs as a separately labelled provisional snapshot.")
    parser.add_argument("--discovery", type=Path, default=Path("artifacts/state-owned-source-discovery.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/state-owned-provisional-jobs.json"))
    parser.add_argument("--connectors-only", action="store_true", help="Only fetch CONNECTOR_CANDIDATE rows; default also includes NEEDS_MANUAL_REVIEW entries with public links.")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--web-output", type=Path, default=None, help="Optionally write a camelCase provisional catalog for the web app.")
    parser.add_argument("--include-review-jobs", action="store_true", help="Include NEEDS_REVIEW rows in --web-output for maximum recall.")
    args = parser.parse_args(argv)
    report = collect_provisional_jobs(
        args.discovery,
        output=args.output,
        include_review=not args.connectors_only,
        max_pages=args.max_pages,
        max_workers=args.max_workers,
        interval_seconds=args.interval,
        timeout=args.timeout,
    )
    if args.web_output:
        web_catalog = build_web_catalog(report, include_review=args.include_review_jobs)
        args.web_output.parent.mkdir(parents=True, exist_ok=True)
        args.web_output.write_text(json.dumps(web_catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
