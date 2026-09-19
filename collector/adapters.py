from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import hashlib
import json
import random
import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx

from .policy import retry_decision
from .schema import RawJob, SourceConfig
from .http_cache import CacheEntry, response_headers, response_content_hash, update_entry


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 AutumnAssistant/0.2"
CAMPUS_WORDS = ("校招", "校园", "应届", "毕业生", "graduate", "campus", "trainee", "管培")
SOCIAL_WORDS = ("社招", "社会招聘", "experienced", "社会人才")


class SourceBlockedError(RuntimeError):
    """Raised when a source asks for login, captcha, or blocks automation."""


@dataclass
class FetchResult:
    source_id: str
    jobs: list[RawJob]
    status_code: int
    attempts: int
    blocked: bool = False
    error: str | None = None
    complete: bool = True
    pages: int = 0
    not_modified: bool = False
    response_headers: dict[str, str] = field(default_factory=dict)
    content_hash: str | None = None
    fetched_at: datetime | None = None
    raw_count: int = 0
    detail_fetched_count: int = 0
    detail_failed_count: int = 0

    @property
    def detail_success_rate(self) -> float | None:
        total = self.detail_fetched_count + self.detail_failed_count
        if not total:
            return None
        return self.detail_fetched_count / total


def _sleep(source: SourceConfig) -> None:
    if source.request_interval_seconds:
        time.sleep(source.request_interval_seconds + random.uniform(0, 0.18))


def _response_json(response: Any) -> Any:
    """Decode UTF-8 explicitly because several Chinese ATS omit charset."""

    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return json.loads(content.decode("utf-8"))
    return response.json()


def _date_from_epoch(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=UTC).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _date_from_text(value: Any) -> date | None:
    """Parse an official ISO/date prefix without treating update timestamps as publish dates."""

    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    # Baidu currently returns ``YYYY-MM-DD``; accepting an ISO datetime keeps
    # the adapter tolerant of a harmless API representation change while still
    # requiring the source to provide the date explicitly.
    match = re.match(r"^(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _cohort(text: str) -> str:
    match = re.search(r"(?<!\d)(20\d{2})\s*届", text)
    if match:
        return match.group(1)
    match = re.search(r"(?<!\d)(2\d)\s*届", text)
    if match:
        return f"20{match.group(1)}"
    # Some official portals omit 届 and write 2027校招 / 2027秋招. Keep the
    # recruitment word mandatory so unrelated years in the JD are not treated
    # as the graduation cohort.
    match = re.search(r"(?<!\d)(20\d{2})\s*(?:年\s*)?(?:校园招聘|校招|秋招|春招)", text)
    return match.group(1) if match else "未知"


def _english_cohort(text: str) -> str:
    """Read explicit English early-career year signals from public ATS text.

    Greenhouse and similar global boards commonly describe a cohort as
    ``Summer 2027 internship`` or ``upcoming graduates (2027)`` rather than
    using the Chinese ``届`` marker.  The patterns stay deliberately narrow:
    a bare year is never treated as a cohort, and the surrounding phrase must
    identify an internship, graduate programme, or class.
    """

    value = str(text or "")
    marker = r"(?:intern(?:ship)?|co[- ]?op|upcoming\s+graduates?|graduate\s+(?:program|programme)|academy|class(?:es)?)"
    patterns = (
        # Year first: ``2027 ... Upcoming Graduates`` or ``2027 Academy``.
        rf"(?<!\d)(20\d{{2}})(?!\d)[^.!?\n]{{0,140}}{marker}",
        # Marker first: ``Summer 2027 internship`` or ``Accounting Intern ... 2027``.
        rf"{marker}[^.!?\n]{{0,140}}(?<!\d)(20\d{{2}})(?!\d)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if match:
            return match.group(1)
    return "未知"


def _cohort_from_context(text: str, source: SourceConfig | None = None) -> str:
    """Resolve Chinese/English cohort wording with an audited source hint."""

    cohort = _cohort(text)
    if cohort == "未知":
        cohort = _english_cohort(text)
    if cohort == "未知" and source and source.current_cohort_signal:
        # ``currentCohortSignal`` is populated only from the discovery report
        # after an operator has reviewed the official page.  Treat it as a
        # bounded fallback, never as a free-form year guess.
        match = re.search(r"(?<!\d)(20\d{2})(?!\d)", str(source.current_cohort_signal))
        if match:
            cohort = match.group(1)
    return cohort


def _batch(text: str) -> str:
    pairs = (
        ("提前批", "提前批"), ("秋招补录", "秋招补录"), ("春招补录", "春招补录"),
        ("秋季校园招聘", "秋招正式批"), ("秋招", "秋招正式批"),
        ("春季校园招聘", "春招"), ("春招", "春招"),
        ("实习转正", "实习转正"), ("管培", "管培生/专项计划"),
        ("专项计划", "管培生/专项计划"), ("日常校招", "日常校招"),
    )
    return next((value for marker, value in pairs if marker in text), "未知")


def _education(text: str) -> str:
    if "博士" in text:
        return "博士"
    if "硕士" in text or "研究生" in text:
        return "硕士"
    if "本科" in text or "学士" in text:
        return "本科"
    if "大专" in text or "专科" in text:
        return "大专"
    return "未知"


def _role_category(text: str) -> str:
    mapping = (
        (("算法", "机器学习", "大模型", "ai"), "算法/AI"),
        (("数据", "商业分析"), "数据"), (("芯片", "硬件", "射频", "电子", "fpga"), "硬件/芯片"),
        (("开发", "研发", "软件", "前端", "后端", "客户端", "测试工程"), "软件研发"),
        (("产品",), "产品"), (("运营",), "运营"), (("市场", "品牌", "营销"), "市场/品牌"),
        (("销售", "商务", "客户经理"), "销售/商务"),
        (("供应链", "采购", "物流", "仓储", "集配", "营业部", "场地", "采销"), "供应链/采购/物流"),
        (("财务", "会计", "审计"), "财务/审计"), (("投资", "投研", "证券"), "金融/投研"),
        (("人力", "招聘", "hr"), "人力资源"),
        (("法务", "合规"), "法务/合规"), (("设计", "美术"), "设计"),
        (("策划", "发行"), "游戏策划/发行"), (("生产", "制造", "质量", "工艺"), "生产制造/质量"),
        (("医药", "临床", "药物"), "医药/研发"), (("项目管理", "项目经理"), "项目管理"),
    )
    lower = text.lower()

    def matches(word: str) -> bool:
        # ``ai`` must be a standalone token. Substring matching would classify
        # unrelated English words such as ``maintain`` as algorithm roles.
        if word == "ai":
            return bool(re.search(r"(?<![a-z])ai(?![a-z])", lower))
        return word in lower

    return next((category for words, category in mapping if any(matches(word) for word in words)), "其他")


def _campus_flag(source: SourceConfig, *values: str) -> bool | None:
    text = " ".join(values).lower()
    if any(word in text for word in SOCIAL_WORDS):
        return False
    markers = tuple(word.lower() for word in source.campus_markers) or CAMPUS_WORDS
    if any(word in text for word in markers):
        return True
    path = (source.website_path or "").lower()
    if source.campus_only and any(word in path for word in ("campus", "school", "graduate", "campushire")):
        return True
    return None


class PublicJsonAdapter:
    """Conservative single-page adapter for reviewed public JSON endpoints."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        endpoint: str,
        parser: Callable[[dict[str, Any], SourceConfig], RawJob],
        max_attempts: int = 3,
        item_filter: Callable[[dict[str, Any]], bool] | None = None,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        attempts = 0
        previous_cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        while attempts < max_attempts:
            attempts += 1
            try:
                headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
                headers.update(previous_cache.request_headers())
                response = self.client.get(endpoint, headers=headers)
                fetched_at = datetime.now(UTC)
                response_meta = response_headers(response)
                if response.status_code == 304:
                    return FetchResult(
                        source.source_id,
                        [],
                        response.status_code,
                        attempts,
                        complete=True,
                        pages=1,
                        not_modified=True,
                        response_headers=response_meta,
                        content_hash=previous_cache.content_hash,
                        fetched_at=fetched_at,
                    )
                decision = retry_decision(response.status_code, attempts, max_attempts)
                if response.status_code in {401, 403, 405, 429}:
                    return FetchResult(source.source_id, [], response.status_code, attempts, blocked=True, error=decision.reason, response_headers=response_meta, fetched_at=fetched_at)
                if response.status_code >= 400:
                    if decision.retry:
                        time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                        continue
                    return FetchResult(source.source_id, [], response.status_code, attempts, error=decision.reason, response_headers=response_meta, fetched_at=fetched_at)
                payload = _response_json(response)
                items, found = _collection(payload)
                if not found:
                    return FetchResult(source.source_id, [], response.status_code, attempts, error="incomplete_payload", complete=False, response_headers=response_meta, content_hash=response_content_hash(response), fetched_at=fetched_at)
                jobs: list[RawJob] = []
                invalid_items = 0
                for item in items:
                    if not isinstance(item, dict):
                        invalid_items += 1
                        continue
                    try:
                        if item_filter is not None and not item_filter(item):
                            continue
                        jobs.append(RawJob.model_validate(parser(item, source)))
                    except (KeyError, TypeError, ValueError):
                        # A single malformed/withdrawn row must not discard a
                        # healthy source response.  The raw count and
                        # completeness metrics still expose that some rows
                        # could not be normalised for operator review.
                        invalid_items += 1
                if items and not jobs and invalid_items:
                    return FetchResult(
                        source.source_id,
                        [],
                        response.status_code,
                        attempts,
                        error="invalid_items",
                        complete=False,
                        pages=1,
                        response_headers=response_meta,
                        content_hash=response_content_hash(response),
                        fetched_at=fetched_at,
                        raw_count=len(items),
                    )
                return FetchResult(
                    source.source_id,
                    jobs,
                    response.status_code,
                    attempts,
                    pages=1,
                    response_headers=response_meta,
                    content_hash=response_content_hash(response),
                    fetched_at=fetched_at,
                    raw_count=len(items),
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                decision = retry_decision(None, attempts, max_attempts)
                if not decision.retry:
                    return FetchResult(source.source_id, [], 0, attempts, error=f"network_timeout:{exc.__class__.__name__}", fetched_at=datetime.now(UTC))
                time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
            except (ValueError, json.JSONDecodeError) as exc:
                return FetchResult(source.source_id, [], 0, attempts, error=f"invalid_json:{exc.__class__.__name__}", complete=False, fetched_at=datetime.now(UTC))
        return FetchResult(source.source_id, [], 0, attempts, error="retry_exhausted", fetched_at=datetime.now(UTC))


def _absolute_apply_url(value: Any, base_url: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return urljoin(base_url, text)


def _ats_context(item: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "title", "name", "job_title", "jobTitle", "description", "descriptionPlain",
        "descriptionHtml", "jobDescription", "locationsText", "location", "locations", "employmentType", "recruitmentType",
        "category", "department", "team", "bulletFields", "qualifications", "requirements",
        "categories", "publishedAt", "datePosted", "postedAt",
    ):
        value = item.get(key)
        if isinstance(value, list):
            values.extend(str(entry) for entry in value)
        elif isinstance(value, dict):
            values.extend(str(entry) for entry in value.values())
        elif value not in (None, ""):
            values.append(str(value))
    return " ".join(values)


def _allowlisted_ats_item(item: dict[str, Any], source: SourceConfig) -> bool:
    """Apply an explicit source-level allow-list before campus heuristics.

    Public Greenhouse boards often contain hundreds of experienced-hire roles
    alongside a small early-career programme.  A reviewed ID list or title
    marker is therefore required for mixed boards; an empty configuration
    keeps the existing behaviour for already-audited campus-only sources.
    """

    allowed_ids = {
        str(value).strip().casefold()
        for value in source.allowed_job_ids
        if str(value).strip()
    }
    allowed_markers = {
        str(value).strip().casefold()
        for value in source.allowed_title_markers
        if str(value).strip()
    }
    if not allowed_ids and not allowed_markers:
        return True

    id_values = (
        item.get("id"), item.get("job_id"), item.get("jobId"),
        item.get("jobPostingId"), item.get("requisitionId"), item.get("requisition_id"),
        item.get("gh_jid"),
    )
    observed_ids = {str(value).strip().casefold() for value in id_values if value not in (None, "")}
    if allowed_ids and observed_ids.intersection(allowed_ids):
        return True
    if allowed_markers:
        title = str(
            item.get("title") or item.get("name") or item.get("job_title") or item.get("jobTitle") or ""
        ).strip().casefold()
        if title and any(marker in title for marker in allowed_markers):
            return True
    return False


def _ats_campus_item_allowed(item: dict[str, Any], source: SourceConfig) -> bool:
    """Keep reviewed campus feeds conservative when an ATS mixes hiring types.

    A source-level campus audit is required before an adapter can run.  Within
    that feed, an explicit social/experienced-hire marker still wins and the
    row is dropped.  Missing campus wording is allowed because many official
    ATS rows inherit the campus context from the audited board rather than
    repeating it in each posting.
    """

    if not _allowlisted_ats_item(item, source):
        return False
    return _campus_flag(source, _ats_context(item)) is not False


def _ats_raw_job(item: dict[str, Any], source: SourceConfig, *, apply_value: Any, title_value: Any,
                 location_value: Any, description_value: Any, requirement_value: Any,
                 source_job_id: Any, publish_value: Any = None) -> RawJob:
    """Map standard ATS fields to ``RawJob`` without guessing missing facts."""

    title = str(title_value or "").strip()
    location = location_value
    if isinstance(location, dict):
        location = (
            location.get("name")
            or location.get("text")
            or location.get("displayName")
            or "、".join(
                str(location.get(key)).strip()
                for key in ("city", "state", "region", "country", "addressLocality", "addressRegion")
                if location.get(key) not in (None, "")
            )
        )
    if isinstance(location, list):
        location = "、".join(
            str(entry.get("name") or entry.get("text") or entry).strip()
            if isinstance(entry, dict) else str(entry).strip()
            for entry in location
            if str(entry).strip()
        )
    location_text = str(location or "未知").strip() or "未知"
    description = str(description_value or "").strip()
    requirement = requirement_value
    if isinstance(requirement, list):
        requirements = [str(value).strip() for value in requirement if str(value).strip()]
    else:
        requirements = [str(requirement).strip()] if str(requirement or "").strip() else []
    apply_url = _absolute_apply_url(apply_value, str(source.endpoint or source.source_url))
    if not apply_url:
        # The Pydantic model rejects an absent application URL; callers treat
        # this as an invalid row and preserve the previous snapshot.
        raise ValueError("missing_apply_url")
    context = _ats_context(item)
    published = _date_from_text(publish_value) or _date_from_epoch(publish_value)
    return RawJob.model_validate({
        "source_id": source.source_id,
        "source_job_id": str(source_job_id).strip() if source_job_id not in (None, "") else None,
        "company_id": source.company_id,
        "company_name": source.company_name,
        "title": title,
        "city": location_text,
        "role_category": _role_category(title),
        "cohort": _cohort_from_context(context, source),
        "batch": _batch(context),
        "education": _education(context),
        "description": description,
        "requirements": requirements,
        "publish_date": published,
        "publish_date_source": "OFFICIAL" if published else "UNKNOWN",
        "deadline": _date_from_text(item.get("deadline") or item.get("closingDate") or item.get("applicationDeadline")),
        "apply_url": apply_url,
        "source_url": str(source.source_url),
        "source_name": source.company_name + "官方校招来源",
        "source_level": source.source_level,
        "source_evidence": [str(source.source_url), *[str(value) for value in source.evidence_urls]],
        "is_campus": True,
        "campaign_id": f"{source.company_id}:{_cohort_from_context(context, source)}:{_batch(context)}",
        "campaign_name": f"{_cohort_from_context(context, source)}届{_batch(context)}" if _cohort_from_context(context, source) != "未知" else "校园招聘",
        "campaign_official_url": str(source.source_url),
    })


def _workday_job_id(item: dict[str, Any]) -> Any:
    bullet_fields = item.get("bulletFields")
    first_bullet = bullet_fields[0] if isinstance(bullet_fields, list) and bullet_fields else None
    return item.get("jobReqId") or item.get("id") or first_bullet


def greenhouse_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    """Map the public Greenhouse board shape (including absolute_url)."""

    return _ats_raw_job(
        item,
        source,
        apply_value=item.get("absolute_url") or item.get("url"),
        title_value=item.get("title") or item.get("name"),
        location_value=item.get("location"),
        description_value=item.get("content") or item.get("description"),
        requirement_value=item.get("requirements"),
        source_job_id=item.get("id") or item.get("job_id"),
        # Greenhouse exposes ``updated_at`` for edits, not the employer's
        # publication date.  Only explicit creation/publication fields are
        # eligible for the public ``publishDate`` contract; otherwise the UI
        # correctly shows that the official date is unknown.
        publish_value=item.get("published_at") or item.get("publishedAt") or item.get("created_at") or item.get("createdAt"),
    )


def lever_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    """Map Lever's public postings shape (hostedUrl/categories)."""

    categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
    location = categories.get("location") or item.get("workplaceType")
    description = item.get("descriptionPlain") or item.get("description")
    return _ats_raw_job(
        item,
        source,
        # ``hostedUrl`` is Lever's canonical field.  A few reviewed public
        # feeds expose the same posting under ``absolute_url`` (the Greenhouse
        # naming convention), so accept it as a conservative compatibility
        # fallback rather than dropping an otherwise valid public row.
        apply_value=item.get("hostedUrl") or item.get("applyUrl") or item.get("absolute_url") or item.get("url"),
        title_value=item.get("text") or item.get("title"),
        location_value=location,
        description_value=description,
        requirement_value=item.get("lists") or item.get("requirements"),
        source_job_id=item.get("id"),
        publish_value=item.get("createdAt") or item.get("updatedAt"),
    )


class WorkdayCampusAdapter:
    """Public Workday CXS campus endpoint (no login or browser state)."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 3,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        endpoint = str(source.endpoint)
        output: list[RawJob] = []
        total_attempts = 0
        pages = 0
        expected_total: int | None = None
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": str(source.source_url),
        }
        headers.update(cache.request_headers())
        last_headers: dict[str, str] = {}
        last_hash: str | None = None
        last_fetched_at: datetime | None = None
        raw_count = 0
        for page in range(source.max_pages):
            payload_body = {"appliedFacets": {}, "limit": source.page_size, "offset": page * source.page_size, "searchText": ""}
            response: Any = None
            for attempt in range(1, max_attempts + 1):
                total_attempts += 1
                try:
                    response = self.client.post(endpoint, headers=headers, json=payload_body)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    decision = retry_decision(None, attempt, max_attempts)
                    if decision.retry:
                        time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                        continue
                    return FetchResult(source.source_id, [], 0, total_attempts, error=f"network_timeout:{exc.__class__.__name__}", complete=False, pages=pages, fetched_at=datetime.now(UTC))
                response_meta = response_headers(response)
                response_hash = response_content_hash(response)
                fetched_at = datetime.now(UTC)
                if response.status_code == 304:
                    if page == 0:
                        return FetchResult(
                            source.source_id, [], response.status_code, total_attempts,
                            complete=True, pages=1, not_modified=True,
                            response_headers=response_meta, content_hash=cache.content_hash,
                            fetched_at=fetched_at,
                        )
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error="not_modified_after_first_page", complete=False, pages=pages, response_headers=response_meta, content_hash=response_hash, fetched_at=fetched_at, raw_count=raw_count)
                decision = retry_decision(response.status_code, attempt, max_attempts)
                if response.status_code in {401, 403, 405, 429}:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, blocked=True, error="access_control", complete=False, pages=pages, response_headers=response_meta, fetched_at=fetched_at)
                if response.status_code >= 400 and decision.retry:
                    time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                    continue
                if response.status_code >= 400:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error=decision.reason, complete=False, pages=pages, response_headers=response_meta, fetched_at=fetched_at)
                break
            if response is None:
                return FetchResult(source.source_id, [], 0, total_attempts, error="retry_exhausted", complete=False, pages=pages, fetched_at=datetime.now(UTC))
            try:
                payload = _response_json(response)
            except (ValueError, json.JSONDecodeError) as exc:
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error=f"invalid_json:{exc.__class__.__name__}", complete=False, pages=pages, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            if not isinstance(payload, dict) or not isinstance(payload.get("jobPostings"), list):
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error="incomplete_payload", complete=False, pages=pages, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            posts = payload["jobPostings"]
            raw_count += len(posts)
            last_headers = response_headers(response) or last_headers
            last_hash = response_content_hash(response) or last_hash
            last_fetched_at = datetime.now(UTC)
            for item in posts:
                if not isinstance(item, dict):
                    continue
                if not _ats_campus_item_allowed(item, source):
                    continue
                try:
                    output.append(_ats_raw_job(item, source,
                        apply_value=item.get("externalUrl") or item.get("externalPath") or item.get("applyUrl"),
                        title_value=item.get("title"), location_value=item.get("locationsText") or item.get("location"),
                        description_value=item.get("jobDescription") or item.get("description"),
                        requirement_value=item.get("qualifications") or item.get("requirements"),
                        source_job_id=_workday_job_id(item),
                        publish_value=item.get("postedOn") or item.get("updatedOn")))
                except (TypeError, ValueError):
                    continue
            pages += 1
            try:
                expected_total = int(payload.get("total")) if payload.get("total") is not None else expected_total
            except (TypeError, ValueError):
                pass
            if not posts or len(posts) < source.page_size or (expected_total is not None and (page + 1) * source.page_size >= expected_total):
                return FetchResult(source.source_id, output, response.status_code, total_attempts, pages=pages, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
            _sleep(source)
        return FetchResult(source.source_id, [], 200, total_attempts, error="truncated_feed", complete=False, pages=pages, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)


class GreenhouseCampusAdapter:
    """Greenhouse public board JSON; only explicitly campus sources are run."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 3,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        result = PublicJsonAdapter(self.client).fetch(
            source,
            str(source.endpoint),
            greenhouse_json_parser,
            max_attempts=max_attempts,
            item_filter=lambda item: _ats_campus_item_allowed(item, source),
            cache_entry=cache_entry,
        )
        if result.error or result.blocked:
            return result
        # PublicJsonAdapter already handles common ``jobs`` envelopes.  The
        # dedicated route is kept explicit so a future Greenhouse-specific
        # parser can be enabled per source without changing the gate.
        return result


class LeverCampusAdapter(GreenhouseCampusAdapter):
    """Lever's public postings JSON uses the same conservative mapping."""

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 3,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        return PublicJsonAdapter(self.client).fetch(
            source,
            str(source.endpoint),
            lever_json_parser,
            max_attempts=max_attempts,
            item_filter=lambda item: _ats_campus_item_allowed(item, source),
            cache_entry=cache_entry,
        )


def _dom_node_is_visible(node: Any) -> bool:
    """Reject obvious hidden DOM rows without executing page JavaScript."""

    current = node
    while current is not None and getattr(current, "name", None):
        if current.name in {"script", "style", "template", "noscript"}:
            return False
        if current.has_attr("hidden") or str(current.get("aria-hidden", "")).lower() == "true":
            return False
        style = str(current.get("style", "")).replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return False
        classes = {str(value).lower() for value in (current.get("class") or [])}
        if classes.intersection({"hidden", "is-hidden", "d-none", "sr-only"}):
            return False
        current = getattr(current, "parent", None)
    return True


class DomCampusAdapter:
    """Opt-in parser for ordinary, server-rendered campus HTML.

    The registry must provide a stable job selector and field selectors.  No
    scripts are executed, no hidden API is guessed, and a page without those
    selectors is considered incomplete.
    """

    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 1,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.dom_job_selector:
            return FetchResult(source.source_id, [], 0, 0, error="dom_selectors_not_configured", complete=False)
        try:
            cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
            headers = {"Accept": "text/html", "User-Agent": USER_AGENT, "Referer": str(source.source_url)}
            headers.update(cache.request_headers())
            response = self.client.get(str(source.endpoint or source.source_url), headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return FetchResult(source.source_id, [], 0, 1, error=f"network_timeout:{exc.__class__.__name__}", complete=False)
        if response.status_code == 304:
            return FetchResult(
                source.source_id,
                [],
                response.status_code,
                1,
                complete=True,
                pages=1,
                not_modified=True,
                response_headers=response_headers(response),
                content_hash=(cache_entry.content_hash if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry).content_hash),
                fetched_at=datetime.now(UTC),
            )
        if response.status_code in {401, 403, 405, 429}:
            return FetchResult(source.source_id, [], response.status_code, 1, blocked=True, error="access_control", complete=False, response_headers=response_headers(response), fetched_at=datetime.now(UTC))
        if response.status_code >= 400:
            return FetchResult(source.source_id, [], response.status_code, 1, error=f"http_status:{response.status_code}", complete=False, response_headers=response_headers(response), fetched_at=datetime.now(UTC))
        soup = BeautifulSoup(response.content[:4 * 1024 * 1024], "html.parser")
        selectors = source.dom_field_selectors
        jobs: list[RawJob] = []
        for node in soup.select(source.dom_job_selector):
            if not _dom_node_is_visible(node):
                continue

            def field(name: str, fallback: str = "") -> str:
                selector = selectors.get(name)
                selected = node.select_one(selector) if selector else None
                # Selectors for links should return the destination, not the
                # visible label (e.g. ``申请``).  The URL is still checked by
                # normalize_job against the source's reviewed allow-list.
                if selected is not None and name.lower() in {"applyurl", "url", "sourceurl"}:
                    href = selected.get("href")
                    if href:
                        return str(href).strip()
                return " ".join(selected.stripped_strings) if selected else fallback
            title = field("title")
            apply_url = field("applyUrl")
            if not title or not apply_url:
                continue
            item = {"title": title, "description": field("description"), "requirements": field("requirements"), "location": field("city"), "postedAt": field("publishDate")}
            context = _ats_context(item)
            if _campus_flag(source, context) is False:
                continue
            try:
                base_url = str(getattr(response, "url", source.source_url))
                jobs.append(_ats_raw_job(item, source, apply_value=_absolute_apply_url(apply_url, base_url), title_value=title, location_value=field("city", "未知"), description_value=field("description"), requirement_value=field("requirements"), source_job_id=field("id") or apply_url, publish_value=field("publishDate")))
            except (TypeError, ValueError):
                continue
        if not jobs:
            return FetchResult(source.source_id, [], response.status_code, 1, error="incomplete_payload", complete=False, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC))
        return FetchResult(source.source_id, jobs, response.status_code, 1, pages=1, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=len(jobs))


class BaiduCampusAdapter:
    """Baidu's public graduate-campus endpoint.

    The endpoint is a normal form-encoded public request used by the official
    campus page.  We deliberately keep the contract narrow: only the
    ``GRADUATE`` feed and records labelled ``校招`` are accepted, requests are
    paged serially, and no cookies, login state or hidden browser APIs are
    involved.
    """

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 3,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        host = (urlparse(str(source.endpoint)).hostname or "").lower()
        if host != "talent.baidu.com":
            return FetchResult(source.source_id, [], 0, 0, error="invalid_baidu_host", complete=False)
        endpoint = str(source.endpoint)
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": USER_AGENT,
            "Origin": "https://talent.baidu.com",
            "Referer": str(source.source_url),
        }
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers.update(cache.request_headers())
        output: list[RawJob] = []
        total_attempts = 0
        pages_fetched = 0
        expected_total: int | None = None
        last_headers: dict[str, str] = {}
        last_hash: str | None = None
        last_fetched_at: datetime | None = None
        raw_count = 0
        for page in range(1, source.max_pages + 1):
            body = {
                "recruitType": "GRADUATE",
                "workPlace": "",
                "postType": "",
                "projectType": "",
                "keyWord": "",
                "curPage": str(page),
                "pageSize": str(source.page_size),
            }
            response: Any = None
            for attempt in range(1, max_attempts + 1):
                total_attempts += 1
                try:
                    response = self.client.post(endpoint, headers=headers, data=body)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    decision = retry_decision(None, attempt, max_attempts)
                    if decision.retry:
                        time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                        continue
                    return FetchResult(source.source_id, [], 0, total_attempts, error=f"network_timeout:{exc.__class__.__name__}", complete=False, pages=pages_fetched, fetched_at=datetime.now(UTC))
                response_meta = response_headers(response)
                response_hash = response_content_hash(response)
                fetched_at = datetime.now(UTC)
                if response.status_code == 304:
                    if page == 1:
                        return FetchResult(
                            source.source_id, [], response.status_code, total_attempts,
                            complete=True, pages=1, not_modified=True,
                            response_headers=response_meta, content_hash=cache.content_hash,
                            fetched_at=fetched_at,
                        )
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error="not_modified_after_first_page", complete=False, pages=pages_fetched, response_headers=response_meta, content_hash=response_hash, fetched_at=fetched_at, raw_count=raw_count)
                decision = retry_decision(response.status_code, attempt, max_attempts)
                if response.status_code in {401, 403, 405, 429}:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, blocked=True, error="access_control", complete=False, pages=pages_fetched, response_headers=response_meta, fetched_at=fetched_at)
                if response.status_code >= 400 and decision.retry:
                    time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                    continue
                if response.status_code >= 400:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error=decision.reason, complete=False, pages=pages_fetched, response_headers=response_meta, fetched_at=fetched_at)
                break
            if response is None:
                return FetchResult(source.source_id, [], 0, total_attempts, error="retry_exhausted", complete=False, pages=pages_fetched, fetched_at=datetime.now(UTC))
            try:
                payload = _response_json(response)
            except (ValueError, json.JSONDecodeError) as exc:
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error=f"invalid_json:{exc.__class__.__name__}", complete=False, pages=pages_fetched, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                message = str(payload.get("message") or payload.get("msg") or "invalid_status") if isinstance(payload, dict) else "invalid_status"
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error=f"baidu_api:{message}", complete=False, pages=pages_fetched, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error="incomplete_payload", complete=False, pages=pages_fetched, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            if expected_total is None:
                try:
                    expected_total = int(data.get("total"))
                except (TypeError, ValueError):
                    expected_total = None
            items = data["list"]
            raw_count += len(items)
            last_headers = response_headers(response) or last_headers
            last_hash = response_content_hash(response) or last_hash
            last_fetched_at = datetime.now(UTC)
            for item in items:
                if isinstance(item, dict) and self._is_campus_item(item):
                    try:
                        output.append(self._map_item(item, source))
                    except (TypeError, ValueError):
                        continue
            pages_fetched += 1
            if not items or len(items) < source.page_size or (expected_total is not None and raw_count >= expected_total):
                return FetchResult(source.source_id, output, response.status_code, total_attempts, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
            _sleep(source)
        return FetchResult(source.source_id, [], 200, total_attempts, error="truncated_feed", complete=False, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)

    @staticmethod
    def _is_campus_item(item: dict[str, Any]) -> bool:
        recruit_type = str(item.get("recruitType") or "").strip().upper()
        project_type = str(item.get("projectType") or "").strip()
        project_code = str(item.get("projectTypeCode") or "").strip()
        text = " ".join(str(item.get(key) or "") for key in ("name", "workContent", "serviceCondition", "projectType")).lower()
        if any(word.lower() in text for word in SOCIAL_WORDS):
            return False
        if recruit_type and recruit_type != "GRADUATE":
            return False
        if project_type and "校招" not in project_type and project_code != "1":
            return False
        return True

    @staticmethod
    def _role_category(item: dict[str, Any]) -> str:
        title_text = " ".join(str(item.get(key) or "") for key in ("name", "postType"))
        category = _role_category(title_text)
        if category != "其他":
            return category
        # Only use the body as a fallback for titles that carry no usable
        # function label. This avoids a generic AI/cloud phrase in every JD
        # turning finance, HR or operations roles into algorithm roles.
        category = _role_category(str(item.get("workContent") or ""))
        if category != "其他":
            return category
        post_type = str(item.get("postType") or "")
        if "技术" in post_type:
            return "软件研发"
        if "产品" in post_type:
            return "产品"
        if "运营" in post_type:
            return "运营"
        if "职能" in post_type or "综合" in post_type:
            return "职能综合"
        return "其他"

    @classmethod
    def _map_item(cls, item: dict[str, Any], source: SourceConfig) -> RawJob:
        post_id = str(item.get("postId") or item.get("jobId") or "").strip()
        title = str(item.get("name") or "").strip()
        work_content = str(item.get("workContent") or "").strip()
        condition = str(item.get("serviceCondition") or "").strip()
        context = " ".join((title, work_content, condition, str(item.get("projectType") or ""), source.note or ""))
        cohort = _cohort_from_context(context, source)
        detail_url = f"https://talent.baidu.com/jobs/detail/GRADUATE/{post_id}"
        published = _date_from_text(item.get("publishDate"))
        requirements = [condition] if condition else []
        return RawJob.model_validate({
            "source_id": source.source_id,
            "source_job_id": post_id or None,
            "company_id": source.company_id,
            "company_name": source.company_name,
            "title": title,
            "city": str(item.get("workPlace") or "未知"),
            "role_category": cls._role_category(item),
            "cohort": cohort,
            "batch": "未知",
            "education": _education(" ".join((str(item.get("education") or ""), condition))),
            "description": work_content,
            "requirements": requirements,
            "publish_date": published,
            "publish_date_source": "OFFICIAL" if published else "UNKNOWN",
            "deadline": None,
            "apply_url": detail_url,
            "source_url": detail_url,
            "source_name": source.company_name + "官方校招来源",
            "source_level": source.source_level,
            "source_evidence": [str(source.source_url), *[str(value) for value in source.evidence_urls]],
            "is_campus": True,
            "campaign_id": f"{source.company_id}:{cohort}:未知",
            "campaign_name": f"{cohort}届校园招聘" if cohort != "未知" else "校园招聘",
            "campaign_official_url": str(source.source_url),
        })


class JdCampusAdapter:
    """JD's unauthenticated ``present`` campus feed.

    ``campus.jd.com`` exposes a separate public API for new graduates.  The
    adapter never touches the authenticated application/resume endpoints and
    treats an inconsistent page count as incomplete so a bad response cannot
    close a previously published job.
    """

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 3,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        endpoint = str(source.endpoint)
        host = (urlparse(endpoint).hostname or "").lower()
        if host != "campus.jd.com":
            return FetchResult(source.source_id, [], 0, 0, error="invalid_jd_host", complete=False)
        endpoint = _with_query(endpoint, type="present")
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Origin": "https://campus.jd.com",
            "Referer": str(source.source_url),
        }
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers.update(cache.request_headers())
        output: list[RawJob] = []
        total_attempts = 0
        pages_fetched = 0
        expected_total: int | None = None
        seen: set[str] = set()
        last_headers: dict[str, str] = {}
        last_hash: str | None = None
        last_fetched_at: datetime | None = None
        raw_count = 0
        # JD's public endpoint is zero-based: pageIndex=0 is the first page.
        # Starting at one silently omits the first twenty positions while the
        # API still reports the full totalNumber.
        for page in range(source.max_pages):
            body = {
                "pageSize": source.page_size,
                "pageIndex": page,
                "parameter": {
                    "positionName": "",
                    "planIdList": [],
                    "positionDeptList": [],
                    "jobDirectionCodeList": [],
                    "workCityCodeList": [],
                },
            }
            response: Any = None
            for attempt in range(1, max_attempts + 1):
                total_attempts += 1
                try:
                    response = self.client.post(endpoint, headers=headers, json=body)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    decision = retry_decision(None, attempt, max_attempts)
                    if decision.retry:
                        time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                        continue
                    return FetchResult(source.source_id, [], 0, total_attempts, error=f"network_timeout:{exc.__class__.__name__}", complete=False, pages=pages_fetched, fetched_at=datetime.now(UTC))
                response_meta = response_headers(response)
                response_hash = response_content_hash(response)
                fetched_at = datetime.now(UTC)
                if response.status_code == 304:
                    if page == 0:
                        return FetchResult(
                            source.source_id, [], response.status_code, total_attempts,
                            complete=True, pages=1, not_modified=True,
                            response_headers=response_meta, content_hash=cache.content_hash,
                            fetched_at=fetched_at,
                        )
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error="not_modified_after_first_page", complete=False, pages=pages_fetched, response_headers=response_meta, content_hash=response_hash, fetched_at=fetched_at, raw_count=raw_count)
                decision = retry_decision(response.status_code, attempt, max_attempts)
                if response.status_code in {401, 403, 405, 429}:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, blocked=True, error="access_control", complete=False, pages=pages_fetched, response_headers=response_meta, fetched_at=fetched_at)
                if response.status_code >= 400 and decision.retry:
                    time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                    continue
                if response.status_code >= 400:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error=decision.reason, complete=False, pages=pages_fetched, response_headers=response_meta, fetched_at=fetched_at)
                break
            if response is None:
                return FetchResult(source.source_id, [], 0, total_attempts, error="retry_exhausted", complete=False, pages=pages_fetched, fetched_at=datetime.now(UTC))
            try:
                payload = _response_json(response)
            except (ValueError, json.JSONDecodeError) as exc:
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error=f"invalid_json:{exc.__class__.__name__}", complete=False, pages=pages_fetched, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            if not isinstance(payload, dict) or payload.get("success") is not True:
                message = str(payload.get("errorMessage") or payload.get("message") or "invalid_status") if isinstance(payload, dict) else "invalid_status"
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error=f"jd_api:{message}", complete=False, pages=pages_fetched, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            data = payload.get("body")
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error="incomplete_payload", complete=False, pages=pages_fetched, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            if expected_total is None:
                try:
                    expected_total = int(data.get("totalNumber"))
                except (TypeError, ValueError):
                    expected_total = None
            items = data["items"]
            raw_count += len(items)
            last_headers = response_headers(response) or last_headers
            last_hash = response_content_hash(response) or last_hash
            last_fetched_at = datetime.now(UTC)
            for item in items:
                if not isinstance(item, dict) or not self._is_campus_item(item):
                    continue
                try:
                    job = self._map_item(item, source)
                except (TypeError, ValueError):
                    continue
                key = job.source_job_id or str(job.apply_url)
                if key not in seen:
                    seen.add(key)
                    output.append(job)
            pages_fetched += 1
            # JD's totalNumber describes raw endpoint rows. Compare it with
            # raw_count rather than the filtered output so mixed campus/social
            # responses do not trigger needless pagination or a false
            # incomplete result.
            if expected_total is not None and raw_count >= expected_total:
                return FetchResult(source.source_id, output, response.status_code, total_attempts, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
            if not items:
                if expected_total is not None and raw_count < expected_total:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error="incomplete_pagination", complete=False, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
                return FetchResult(source.source_id, output, response.status_code, total_attempts, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
            if len(items) < source.page_size:
                if expected_total is not None and raw_count < expected_total:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error="incomplete_pagination", complete=False, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
                return FetchResult(source.source_id, output, response.status_code, total_attempts, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
            _sleep(source)
        return FetchResult(source.source_id, [], 200, total_attempts, error="truncated_feed", complete=False, pages=pages_fetched, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)

    @staticmethod
    def _is_campus_item(item: dict[str, Any]) -> bool:
        text = " ".join(str(item.get(key) or "") for key in ("positionName", "jobDirection", "workContent", "qualification"))
        return not any(word.lower() in text.lower() for word in SOCIAL_WORDS)

    @staticmethod
    def _role_category(item: dict[str, Any]) -> str:
        title_category = _role_category(str(item.get("positionName") or ""))
        if title_category != "其他":
            return title_category
        direction = str(item.get("jobDirection") or "")
        direction_category = _role_category(direction)
        if direction_category != "其他":
            return direction_category
        if "采销" in direction or "物流" in direction or "供应链" in direction:
            return "供应链/采购/物流"
        if "管理培训" in direction:
            return "职能综合"
        return "其他"

    @classmethod
    def _map_item(cls, item: dict[str, Any], source: SourceConfig) -> RawJob:
        publish_id = str(item.get("publishId") or item.get("reqId") or "").strip()
        title = str(item.get("positionName") or "").strip()
        work_content = str(item.get("workContent") or "").strip()
        qualification = str(item.get("qualification") or "").strip()
        requirement_values = item.get("requirementVoList") if isinstance(item.get("requirementVoList"), list) else []
        cities: list[str] = []
        for requirement in requirement_values:
            if not isinstance(requirement, dict):
                continue
            city = str(requirement.get("workCity") or "").strip()
            if city:
                city = city.split("-")[-1].replace("市", "")
            if city and city not in cities:
                cities.append(city)
        if not cities:
            city = str(item.get("workCity") or item.get("workAddress") or "").strip()
            if city:
                city = city.split("-")[-1].replace("市", "")
                cities.append(city)
        context = " ".join((title, work_content, qualification, str(item.get("jobDirection") or ""), source.note or ""))
        cohort = _cohort_from_context(context, source)
        detail_url = f"https://campus.jd.com/#/newDetails?publishId={publish_id}"
        published = _date_from_epoch(item.get("publishTime"))
        return RawJob.model_validate({
            "source_id": source.source_id,
            "source_job_id": publish_id or None,
            "company_id": source.company_id,
            "company_name": source.company_name,
            "title": title,
            "city": "、".join(cities) or "未知",
            "role_category": cls._role_category(item),
            "cohort": cohort,
            "batch": "未知",
            "education": _education(qualification),
            "description": work_content,
            "requirements": [qualification] if qualification else [],
            "publish_date": published,
            "publish_date_source": "OFFICIAL" if published else "UNKNOWN",
            "deadline": None,
            "apply_url": detail_url,
            "source_url": detail_url,
            "source_name": source.company_name + "官方校招来源",
            "source_level": source.source_level,
            "source_evidence": [str(source.source_url), *[str(value) for value in source.evidence_urls]],
            "is_campus": True,
            "campaign_id": f"{source.company_id}:{cohort}:未知",
            "campaign_name": f"{cohort}届校园招聘" if cohort != "未知" else "校园招聘",
            "campaign_official_url": str(source.source_url),
        })


_COLLECTION_KEYS = (
    "jobs", "jobList", "jobPosts", "positions", "offers", "records", "results", "items", "list", "Posts", "content",
)
_COLLECTION_WRAPPERS = ("data", "Data", "d", "result", "payload", "response")


def _collection(payload: Any, *, _depth: int = 0) -> tuple[list[Any], bool]:
    """Find a known job collection in common public ATS envelopes.

    A bounded walk handles Beisen/iTalent's frequent ``data.list`` and SAP's
    ``d.results`` shapes while refusing arbitrary nested arrays.  The depth
    limit is deliberate: a source that introduces several undocumented
    wrappers should be reviewed rather than guessed into production.
    """

    if isinstance(payload, list):
        return payload, True
    if not isinstance(payload, dict):
        return [], False
    for key in _COLLECTION_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value, True
    if _depth >= 2:
        return [], False
    for wrapper_name in _COLLECTION_WRAPPERS:
        wrapper = payload.get(wrapper_name)
        if isinstance(wrapper, dict):
            values, found = _collection(wrapper, _depth=_depth + 1)
            if found:
                return values, True
    return [], False


def _with_query(url: str, **updates: Any) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in updates.items()})
    return urlunparse(parsed._replace(query=urlencode(query)))


class TencentCampusAdapter:
    """Tencent's public career feed, constrained to its campus recruitment attrId."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        parser: Callable[[dict[str, Any], SourceConfig], RawJob],
        max_attempts: int = 3,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        output: list[RawJob] = []
        total_attempts = 0
        seen: set[str] = set()
        pages_fetched = 0
        for attr_id in source.campus_attr_ids:
            for page in range(1, source.max_pages + 1):
                endpoint = _with_query(str(source.endpoint), attrId=attr_id, pageIndex=page, pageSize=source.page_size, language="zh-cn", area="cn")
                page_result = PublicJsonAdapter(self.client).fetch(
                    source,
                    endpoint,
                    parser,
                    max_attempts=max_attempts,
                    cache_entry=cache_entry if attr_id == source.campus_attr_ids[0] and page == 1 else None,
                )
                if page_result.not_modified:
                    return page_result
                total_attempts += page_result.attempts
                if page_result.error or page_result.blocked:
                    page_result.jobs = []
                    page_result.complete = False
                    page_result.pages = pages_fetched
                    page_result.attempts = total_attempts
                    return page_result
                for job in page_result.jobs:
                    key = job.source_job_id or str(job.apply_url)
                    if key not in seen:
                        seen.add(key)
                        output.append(job)
                pages_fetched += 1
                # Pagination is driven by the endpoint's raw page size. The
                # parsed list may be shorter after removing experienced-hire
                # rows, which must not make us stop before all campus pages
                # have been observed.
                if page_result.raw_count < source.page_size:
                    break
                _sleep(source)
            else:
                return FetchResult(source.source_id, [], 200, total_attempts, error="truncated_feed", complete=False, pages=pages_fetched)
        return FetchResult(source.source_id, output, 200, total_attempts, pages=pages_fetched)


class FeishuCampusAdapter:
    """Public Hire-campus portal adapter; no login, cookies or bypasses.

    Most reviewed tenants are hosted on ``*.jobs.feishu.cn``. ByteDance's
    campus portal exposes the same documented public Hire API contract from
    ``jobs.bytedance.com``; that single host is allowed explicitly in the
    registry and here rather than broadening this adapter to arbitrary hosts.
    """

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 3,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        host = (source.ats_host or urlparse(str(source.source_url)).hostname or "").lower()
        path = (source.website_path or "").strip("/")
        allowed_host = host.endswith(".jobs.feishu.cn") or host == "jobs.bytedance.com"
        if not allowed_host or not path or not re.fullmatch(r"[A-Za-z0-9_/-]{1,80}", path):
            return FetchResult(source.source_id, [], 0, 0, error="invalid_feishu_configuration", complete=False)
        endpoint = f"https://{host}/api/v1/search/job/posts"
        headers = {
            "Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT,
            "Origin": f"https://{host}", "Referer": str(source.source_url),
            "Portal-Channel": "office", "Portal-Platform": "pc", "website-path": path,
        }
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers.update(cache.request_headers())
        output: list[RawJob] = []
        total_attempts = 0
        raw_count = 0
        expected_total: int | None = None
        seen_ids: set[str] = set()
        last_headers: dict[str, str] = {}
        last_hash: str | None = None
        last_fetched_at: datetime | None = None
        for page in range(source.max_pages):
            body = {
                "keyword": "", "limit": source.page_size, "offset": page * source.page_size,
                "portal_type": 3, "portal_entrance": 1, "language": "zh",
                "recruitment_id_list": ["201"], "job_category_id_list": [], "location_code_list": [],
                "subject_id_list": [], "job_function_id_list": [],
            }
            response: Any = None
            for attempt in range(1, max_attempts + 1):
                total_attempts += 1
                try:
                    response = self.client.post(endpoint, headers=headers, json=body)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    decision = retry_decision(None, attempt, max_attempts)
                    if decision.retry:
                        time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                        continue
                    return FetchResult(source.source_id, [], 0, total_attempts, error=f"network_timeout:{exc.__class__.__name__}", complete=False, pages=page)
                decision = retry_decision(response.status_code, attempt, max_attempts)
                response_meta = response_headers(response)
                response_hash = response_content_hash(response)
                fetched_at = datetime.now(UTC)
                if response.status_code == 304 and page == 0:
                    return FetchResult(
                        source.source_id, [], response.status_code, total_attempts,
                        complete=True, pages=1, not_modified=True,
                        response_headers=response_meta, content_hash=cache.content_hash,
                        fetched_at=fetched_at,
                    )
                if response.status_code in {401, 403, 405, 429}:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, blocked=True, error="access_control", complete=False, pages=page, response_headers=response_meta, fetched_at=fetched_at)
                if response.status_code >= 400 and decision.retry:
                    time.sleep(decision.delay_seconds + random.uniform(0, 0.35))
                    continue
                if response.status_code >= 400:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error=decision.reason, complete=False, pages=page, response_headers=response_meta, fetched_at=fetched_at)
                break
            try:
                payload = _response_json(response)
            except (ValueError, json.JSONDecodeError) as exc:
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error=f"invalid_json:{exc.__class__.__name__}", complete=False, pages=page, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict) or not isinstance(data.get("job_post_list"), list):
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error="incomplete_payload", complete=False, pages=page, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=raw_count)
            posts = data["job_post_list"]
            raw_count += len(posts)
            last_headers = response_headers(response)
            last_hash = response_content_hash(response) or last_hash
            last_fetched_at = datetime.now(UTC)
            # Keep the API filter as the first line of defence, then inspect
            # the job-level metadata as a second line. Public ATS feeds can
            # occasionally ignore an empty filter or mix experienced roles
            # into the same response. We never let an explicit social-hire
            # marker enter the normalized campus catalog.
            for item in posts:
                if not isinstance(item, dict) or not self._is_campus_post(item, source):
                    continue
                try:
                    job = self._map_post(item, source, host, path)
                    key = job.source_job_id or str(job.apply_url)
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    output.append(job)
                except (TypeError, ValueError):
                    continue
            count = data.get("count")
            try:
                # Some Feishu tenants serialise count as a string. Keep the
                # raw response count separate from the filtered/deduplicated
                # public output so pagination remains correct for mixed feeds.
                if count is not None and not isinstance(count, bool):
                    expected_total = max(0, int(count))
            except (TypeError, ValueError):
                pass
            if not posts or len(posts) < source.page_size or (expected_total is not None and raw_count >= expected_total):
                return FetchResult(source.source_id, output, response.status_code, total_attempts, pages=page + 1, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)
            _sleep(source)
        return FetchResult(source.source_id, [], 200, total_attempts, error="truncated_feed", complete=False, pages=source.max_pages, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched_at, raw_count=raw_count)

    @staticmethod
    def _is_campus_post(item: dict[str, Any], source: SourceConfig) -> bool:
        """Reject an explicitly experienced-hire item from a mixed ATS feed."""

        title = str(item.get("title") or "")
        recruitment = item.get("recruit_type") if isinstance(item.get("recruit_type"), dict) else {}
        recruitment_id = str(recruitment.get("id") or "").strip()
        recruitment_name = str(recruitment.get("name") or recruitment.get("i18n_name") or "")
        parent = recruitment.get("parent") if isinstance(recruitment.get("parent"), dict) else {}
        parent_id = str(parent.get("id") or "").strip()

        marker_text = " ".join((title, recruitment_name)).lower()
        if any(word.lower() in marker_text for word in SOCIAL_WORDS):
            return False
        # 201 is Feishu's standard campus recruitment type. Some reviewed
        # portals expose only the parent campus type (2), while others omit
        # recruit_type entirely; the request itself still constrains those
        # responses to recruitment_id_list=["201"].
        if recruitment_id and recruitment_id not in {"201", "2"} and parent_id != "2":
            return False
        if parent_id and parent_id != "2" and recruitment_id not in {"201", "2"}:
            return False
        return _campus_flag(source, title, recruitment_name) is not False

    @staticmethod
    def _map_post(item: dict[str, Any], source: SourceConfig, host: str, path: str) -> RawJob:
        job_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "")
        requirement = str(item.get("requirement") or "")
        recruitment = item.get("recruit_type") if isinstance(item.get("recruit_type"), dict) else {}
        function = item.get("job_function") if isinstance(item.get("job_function"), dict) else {}
        cities = [str(city.get("name") or "").strip() for city in (item.get("city_list") or []) if isinstance(city, dict)]
        recruitment_name = str(recruitment.get("name") or "")
        context = " ".join((title, description, requirement, recruitment_name, source.note or ""))
        detail_url = f"https://{host}/{path}/position/{job_id}/detail"
        published = _date_from_epoch(item.get("publish_time"))
        cohort = _cohort_from_context(context, source)
        batch = _batch(context)
        return RawJob.model_validate({
            "source_id": source.source_id, "source_job_id": job_id or None,
            "company_id": source.company_id, "company_name": source.company_name,
            "title": title, "city": "、".join(filter(None, cities)) or "未知",
            "role_category": _role_category(f"{title} {function.get('name', '')}"),
            "cohort": cohort, "batch": batch, "education": _education(context),
            "description": description, "requirements": [requirement] if requirement else [],
            "publish_date": published, "publish_date_source": "OFFICIAL" if published else "UNKNOWN",
            "deadline": None, "apply_url": detail_url, "source_url": detail_url,
            "source_name": source.company_name + "官方校招来源", "source_level": source.source_level,
            "source_evidence": [str(source.source_url), *[str(value) for value in source.evidence_urls]],
            "is_campus": True,
            "campaign_id": f"{source.company_id}:{cohort}:{batch}",
            "campaign_name": f"{cohort}届{batch}" if cohort != "未知" else recruitment_name or "校园招聘",
            "campaign_official_url": str(source.source_url),
        })


def fetch_source(
    source: SourceConfig,
    parser: Callable[[dict[str, Any], SourceConfig], RawJob],
    client: httpx.Client | None = None,
    cache_entry: CacheEntry | dict[str, Any] | None = None,
) -> FetchResult:
    adapter = source.adapter.lower()
    if adapter == "baidu":
        return BaiduCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter == "jd":
        return JdCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter == "feishu":
        return FeishuCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter.startswith("tencent"):
        return TencentCampusAdapter(client=client).fetch(source, parser, cache_entry=cache_entry)
    if adapter in {"workday", "workday_campus"}:
        return WorkdayCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"greenhouse", "greenhouse_campus"}:
        return GreenhouseCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"lever", "lever_campus"}:
        return LeverCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"dom", "html", "dom_campus"}:
        return DomCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"ashby", "ashby_campus"}:
        from .feeds import AshbyCampusAdapter

        return AshbyCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"beisen", "beisen_campus", "italent", "wecruit"}:
        from .feeds import BeisenCampusAdapter

        return BeisenCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"beisen_modern", "beisen_bsglobal"}:
        from .feeds import BeisenModernCampusAdapter

        return BeisenModernCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"beisen_legacy", "beisen_campus_legacy"}:
        from .feeds import BeisenLegacyCampusAdapter

        return BeisenLegacyCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"teamtailor", "recruitee", "successfactors", "rss", "atom", "xml", "feed"}:
        from .feeds import PublicFeedAdapter

        return PublicFeedAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"smartrecruiters", "smartrecruiters_campus"}:
        from .feeds import SmartRecruitersCampusAdapter

        return SmartRecruitersCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"personio", "personio_campus"}:
        from .feeds import PersonioCampusAdapter

        return PersonioCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"bamboohr", "bamboohr_campus"}:
        from .feeds import BambooHRCampusAdapter

        return BambooHRCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"breezy", "breezy_campus"}:
        from .feeds import BreezyCampusAdapter

        return BreezyCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"oracle", "oracle_campus"}:
        from .feeds import OracleCampusAdapter

        return OracleCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"icims", "icims_campus"}:
        from .feeds import ICIMSCampusAdapter

        return ICIMSCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"workable", "workable_campus"}:
        from .feeds import WorkableCampusAdapter

        return WorkableCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"jsonld", "json_ld", "jobposting", "structured_html"}:
        from .feeds import JsonLdCampusAdapter

        return JsonLdCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if adapter in {"static_html", "html_table", "table", "static"}:
        from .feeds import StaticHtmlCampusAdapter

        return StaticHtmlCampusAdapter(client=client).fetch(source, cache_entry=cache_entry)
    if not source.endpoint:
        return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
    return PublicJsonAdapter(client=client).fetch(source, str(source.endpoint), parser, cache_entry=cache_entry)


def __getattr__(name: str) -> Any:
    """Lazy compatibility exports for the extended public-feed adapters."""

    if name in {
        "AshbyCampusAdapter",
        "BeisenCampusAdapter",
        "BeisenModernCampusAdapter",
        "BeisenLegacyCampusAdapter",
        "JsonLdCampusAdapter",
        "PublicFeedAdapter",
        "TeamtailorCampusAdapter",
        "RecruiteeCampusAdapter",
        "SuccessFactorsCampusAdapter",
        "SmartRecruitersCampusAdapter",
        "PersonioCampusAdapter",
        "BambooHRCampusAdapter",
        "BreezyCampusAdapter",
        "OracleCampusAdapter",
        "ICIMSCampusAdapter",
        "StaticHtmlCampusAdapter",
        "WorkableCampusAdapter",
    }:
        from . import feeds

        if name in {"TeamtailorCampusAdapter", "RecruiteeCampusAdapter", "SuccessFactorsCampusAdapter"}:
            return feeds.PublicFeedAdapter
        return getattr(feeds, name)
    raise AttributeError(name)
