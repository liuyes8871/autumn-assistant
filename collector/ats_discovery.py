from __future__ import annotations

"""Discovery-only ATS and structured-data inspection.

The functions in this module classify public career pages and suggest
candidate endpoints.  They never promote a registry source, execute page
scripts, or persist HTML.  Network helpers intentionally stop on authentication,
rate-limit and security responses.
"""

from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import time
from typing import Any, Iterable
from urllib.parse import parse_qs, urljoin, urlparse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import httpx


ATS_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FEISHU", ("jobs.feishu.cn", "jobs.bytedance.com", "/api/v1/search/job/posts")),
    ("MOKA", ("mokahr.com", "moka.hr", "mokacdn.com")),
    ("BEISEN", ("zhiye.com", "wecruit.com.cn", "italent")),
    ("GREENHOUSE", ("greenhouse.io", "boards.greenhouse.io", "boards-api.greenhouse.io")),
    ("LEVER", ("jobs.lever.co", "api.lever.co")),
    ("ASHBY", ("ashbyhq.com", "jobs.ashbyhq.com", "api.ashbyhq.com")),
    ("WORKDAY", ("myworkdayjobs.com", "workdayjobs.com", "workday.com")),
    ("SUCCESSFACTORS", ("successfactors.com", "jobs2web.com", "sapsf.com")),
    ("TEAMTAILOR", ("teamtailor.com", "teamtailor-cdn.com")),
    ("RECRUITEE", ("recruitee.com", "api.recruitee.com")),
    ("WORKABLE", ("apply.workable.com", "workable.com")),
    ("SMARTRECRUITERS", ("jobs.smartrecruiters.com", "api.smartrecruiters.com", "smartrecruiters.com")),
    ("PERSONIO", ("jobs.personio.com", "personio.com/xml", "personio.de/xml")),
    ("BAMBOOHR", ("bamboohr.com/careers", "boards.bamboohr.com")),
    ("BREEZY", ("breezy.hr", "api.breezy.hr")),
    ("ORACLE", ("oraclecloud.com", "hcmUI/CandidateExperience")),
    ("ICIMS", ("icims.com", "icims.com/jobs")),
    # BOSS is deliberately discovery-only.  There is no public connector in
    # this project and a match must never be treated as an official source.
    ("BOSS", ("zhipin.com", "boss直聘", "bosszhipin.com")),
)

FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml", "application/rdf+xml"}
MAX_HTML_BYTES = 4 * 1024 * 1024

# Discovery is deliberately more permissive than the source registry gate.
# These labels describe the next human action; they are never a replacement
# for ``VERIFIED`` and are therefore safe to expose in an operator backlog.
DISCOVERY_CLASSES = {
    "CONNECTOR_CANDIDATE",       # a known public parser or structured feed is visible
    "NEEDS_MANUAL_REVIEW",       # an ATS is visible but its endpoint/contract needs review
    "MANUAL_IMPORT_ONLY",        # no safe public connector was found
    "PUBLIC_ACCESS_UNAVAILABLE", # blocked, missing or otherwise unreachable
}

CONNECTOR_ATS = {
    "FEISHU", "GREENHOUSE", "LEVER", "ASHBY", "BEISEN", "TEAMTAILOR", "RECRUITEE",
    "SUCCESSFACTORS", "WORKABLE", "WORKDAY", "SMARTRECRUITERS", "PERSONIO",
    "BAMBOOHR", "BREEZY", "ORACLE", "ICIMS", "JSONLD", "STATIC_HTML",
}

SECURITY_CHALLENGE_MARKERS = (
    "captcha",
    "验证码",
    "人机验证",
    "安全验证",
    "访问验证",
    "请完成验证",
    "verify you are human",
    "checking your browser",
    "just a moment",
    "challenge-platform",
    "cf-chl-",
    "enable cookies to continue",
)


def _unique(values: Iterable[str]) -> list[str]:
    """Return non-empty URL hints in stable order without leaking duplicates."""

    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _content_type(value: Any) -> str:
    """Normalise a MIME type that may include parameters."""

    return str(value or "").split(";", 1)[0].strip().casefold()


def _traffic_domain(host: str) -> str:
    """Collapse public vendor tenants to one pacing domain."""

    labels = [part for part in str(host or "").lower().split(".") if part]
    if len(labels) < 2:
        return ".".join(labels)
    if len(labels) >= 3 and ".".join(labels[-2:]) in {"com.cn", "net.cn", "org.cn", "co.uk"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _source_value(source: Any, *keys: str) -> Any:
    """Read dict or Pydantic source rows without forcing one casing."""

    if isinstance(source, dict):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
        return None
    for key in keys:
        value = getattr(source, key, None)
        if value not in (None, ""):
            return value
    return None


def _clean_url(value: Any, base_url: str = "") -> str | None:
    text = str(value or "").strip()
    if not text or text.startswith(("javascript:", "data:", "mailto:")):
        return None
    absolute = urljoin(base_url, text) if base_url else text
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return absolute


def _board_slug(url: str, host_suffixes: tuple[str, ...]) -> str | None:
    parsed = urlparse(url)
    query_slug = parse_qs(parsed.query).get("for", [None])[0]
    if query_slug and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", query_slug):
        return query_slug
    parts = [part for part in parsed.path.split("/") if part]
    host = (parsed.hostname or "").lower()
    if not parts:
        return None
    for marker in host_suffixes:
        if marker in host:
            return parts[-1] if parts[-1] not in {"campus", "position", "jobs", "careers"} else (parts[-2] if len(parts) > 1 else None)
    return None


def _workday_candidate_endpoint(url: str) -> str | None:
    """Infer a Workday CXS jobs endpoint from a public board URL.

    Workday hosts expose a stable, documented path shape but tenant and site
    names vary by employer.  This helper only emits a hint when both pieces
    are visible in the URL; it never probes or promotes the result.
    """

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host.endswith(".myworkdayjobs.com"):
        return None
    labels = [part for part in host.split(".") if part]
    if len(labels) < 4:
        return None
    # Typical host: ``tenant.wd1.myworkdayjobs.com``.  Keep the explicit
    # tenant label and avoid treating the Workday region (wd1/wd5) as one.
    tenant = labels[0]
    if tenant.startswith("wd") and tenant[2:].isdigit():
        return None
    parts = [part for part in parsed.path.split("/") if part]
    locale = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$", re.I)
    meaningful = [part for part in parts if part.casefold() not in {"jobs", "job", "careers", "career"} and not locale.fullmatch(part)]
    if not meaningful:
        return None
    site = meaningful[0]
    if not re.fullmatch(r"[A-Za-z0-9._~-]{1,120}", site):
        return None
    return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"


def detect_security_challenge(content: bytes | str, *, max_bytes: int = MAX_HTML_BYTES) -> bool:
    """Return whether a public response is a likely CAPTCHA/security page.

    The body is inspected in memory only and reduced to visible text before
    matching.  This is intentionally conservative and is used to classify a
    probe as blocked; it never attempts to solve or bypass the challenge.
    """

    if isinstance(content, bytes):
        raw = content[:max_bytes].decode("utf-8", errors="replace")
    else:
        raw = str(content or "")[:max_bytes]
    if not raw:
        return False
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.find_all(["script", "style", "noscript", "template", "svg"]):
        node.decompose()
    visible = " ".join(soup.stripped_strings).casefold()
    return any(marker.casefold() in visible for marker in SECURITY_CHALLENGE_MARKERS)


def extract_feed_links(html: bytes | str, *, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for node in soup.find_all(["link", "a"]):
        href = node.get("href")
        value = _clean_url(href, page_url)
        if not value:
            continue
        kind = _content_type(node.get("type"))
        path = urlparse(value).path.lower()
        rel = " ".join(str(item).lower() for item in (node.get("rel") or []))
        if kind in FEED_TYPES or ("alternate" in rel and ("rss" in kind or "atom" in kind)) or any(token in path for token in ("/rss", "/feed", ".rss", ".xml", "atom")):
            if value not in links:
                links.append(value)
    return links[:20]


def _jsonld_values(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _jsonld_values(item)
    elif isinstance(value, dict):
        graph = value.get("@graph")
        if graph is not None:
            yield from _jsonld_values(graph)
        else:
            yield value


def extract_jobposting_jsonld(html: bytes | str, *, page_url: str = "") -> list[dict[str, Any]]:
    """Return only JSON-LD objects whose type includes ``JobPosting``."""

    soup = BeautifulSoup(html, "html.parser")
    output: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        text = script.string or script.get_text()
        if not text or len(text) > 2 * 1024 * 1024:
            continue
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for item in _jsonld_values(payload):
            type_value = item.get("@type")
            types = type_value if isinstance(type_value, list) else [type_value]
            if not any(str(value).casefold().rstrip("/").rsplit("/", 1)[-1] == "jobposting" for value in types):
                continue
            clean = dict(item)
            if clean.get("url"):
                clean["url"] = _clean_url(clean["url"], page_url) or clean["url"]
            output.append(clean)
    return output


def extract_sitemap_links(html: bytes | str, *, page_url: str) -> list[str]:
    """Extract sitemap URLs from HTML without crawling them."""

    soup = BeautifulSoup(html, "html.parser")
    values: list[str] = []
    for node in soup.find_all("a", href=True):
        href = _clean_url(node.get("href"), page_url)
        if href and "sitemap" in urlparse(href).path.lower() and href not in values:
            values.append(href)
    for node in soup.find_all("link", href=True):
        href = _clean_url(node.get("href"), page_url)
        if href and "sitemap" in urlparse(href).path.lower() and href not in values:
            values.append(href)
    parsed = urlparse(page_url)
    if parsed.scheme and parsed.hostname:
        root = f"{parsed.scheme}://{parsed.hostname}"
        for suffix in ("/sitemap.xml", "/sitemap_index.xml"):
            candidate = root + suffix
            if candidate not in values:
                values.append(candidate)
    return values[:10]


def parse_sitemap_urls(content: bytes | str, *, base_url: str = "") -> list[str]:
    """Parse a bounded sitemap/index into URL candidates without fetching them."""

    raw = content.encode("utf-8") if isinstance(content, str) else content
    if len(raw) > MAX_HTML_BYTES:
        raw = raw[:MAX_HTML_BYTES]
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, UnicodeError):
        return []
    values: list[str] = []
    for node in root.iter():
        if str(node.tag).rsplit("}", 1)[-1].casefold() != "loc":
            continue
        value = _clean_url("".join(node.itertext()).strip(), base_url)
        if value and value not in values:
            values.append(value)
    return values[:500]


def detect_ats_from_html(html: bytes | str, *, page_url: str) -> dict[str, Any]:
    """Classify an official career page and produce auditable endpoint hints."""

    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else str(html or "")
    bounded = raw[:MAX_HTML_BYTES]
    # A number of server-rendered pages escape slashes inside script blobs.
    # Normalising that harmless representation improves detection without
    # executing JavaScript or attempting to infer hidden requests.
    # Include metadata values in the in-memory signature scan.  Several ATS
    # integrations advertise their vendor only through ``meta`` tags while
    # keeping the visible HTML intentionally generic.  We do not persist the
    # values or execute any embedded script.
    metadata_context = " ".join(
        str(value).strip()
        for node in BeautifulSoup(bounded, "html.parser").find_all("meta")
        for value in (
            node.get("content"), node.get("name"), node.get("property"), node.get("itemprop"),
        )
        if value not in (None, "")
    )
    lower = (bounded.replace("\\/", "/") + " " + metadata_context).casefold()
    parsed = urlparse(page_url)
    host = (parsed.hostname or "").lower()
    soup = BeautifulSoup(bounded, "html.parser")
    linked_urls = _unique(
        value
        for node in soup.find_all(["a", "link", "script", "iframe"], href=True)
        if (value := _clean_url(node.get("href"), page_url))
    )
    linked_urls.extend(
        value
        for node in soup.find_all(["script", "iframe"], src=True)
        if (value := _clean_url(node.get("src"), page_url)) and value not in linked_urls
    )
    linked_context = " ".join(linked_urls).casefold()
    matches: list[dict[str, Any]] = []
    for ats, signatures in ATS_PATTERNS:
        found = [signature for signature in signatures if signature.casefold() in lower or signature.casefold() in host or signature.casefold() in parsed.path.casefold() or signature.casefold() in linked_context]
        if not found:
            continue
        ats_link = next((value for value in linked_urls if any(signature.casefold() in value.casefold() for signature in signatures)), None)
        context_url = ats_link or page_url
        context_parsed = urlparse(context_url)
        context_host = (context_parsed.hostname or host).lower()
        evidence = [page_url, *([ats_link] if ats_link else [])]
        endpoints: list[str] = []
        if ats == "GREENHOUSE":
            slug = _board_slug(context_url, ("greenhouse.io",)) or _first_match(ats_link or bounded, r"(?:for=|boards/)([A-Za-z0-9_-]+)")
            if slug:
                endpoints.append(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        elif ats == "LEVER":
            slug = _board_slug(context_url, ("lever.co",))
            if slug:
                endpoints.append(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        elif ats == "ASHBY":
            slug = _board_slug(context_url, ("ashbyhq.com",))
            if slug:
                endpoints.append(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        elif ats == "WORKDAY":
            endpoint = _workday_candidate_endpoint(context_url)
            if endpoint:
                endpoints.append(endpoint)
        elif ats == "TEAMTAILOR":
            # Teamtailor has used both ``jobs.rss`` and ``rss`` over time;
            # keep all public, harmless hints for human review.
            endpoints.extend([
                urljoin(context_url, "/jobs.rss"),
                urljoin(context_url, "/rss"),
                urljoin(context_url, "/feed"),
            ])
        elif ats == "RECRUITEE":
            # The tenant slug is public in the hosted URL.  The API remains a
            # candidate only until an operator verifies the tenant's terms and
            # response shape.
            tenant_slug = _board_slug(context_url, ("recruitee.com",))
            if tenant_slug:
                endpoints.append(f"https://{context_host}/api/offers")
        elif ats == "SUCCESSFACTORS":
            endpoints.extend(
                value for value in linked_urls
                if urlparse(value).path.casefold().endswith((".xml", ".rss", "/rss", "/feed"))
            )
        elif ats == "WORKABLE" and context_host == "apply.workable.com":
            account = _board_slug(context_url, ("workable.com",))
            endpoints.append(urljoin(context_url, f"/api/v3/accounts/{account}/jobs" if account else "/api/v3/accounts"))
        elif ats == "FEISHU":
            endpoints.append(f"https://{context_host}/api/v1/search/job/posts")
        elif ats == "BEISEN":
            # Northstar/BSGlobal portals expose this public bootstrap route;
            # it is only a candidate until the tenant config and campus
            # category are verified by an operator.
            endpoints.append(urljoin(context_url, "/portal/registerSystemInfo"))
            if "/campus" in context_parsed.path.casefold() or "/social" in context_parsed.path.casefold():
                endpoints.append(context_url)
        elif ats == "SMARTRECRUITERS":
            parts = [part for part in context_parsed.path.split("/") if part]
            tenant = next((part for part in reversed(parts) if re.fullmatch(r"[A-Za-z0-9_-]{2,120}", part)), None)
            if tenant:
                endpoints.append(f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings")
        elif ats == "PERSONIO":
            # Personio publishes an unauthenticated XML feed per tenant. Keep
            # the tenant path as a candidate; the registry gate still
            # requires explicit terms, company identity and field evidence.
            endpoints.append(urljoin(context_url, "/xml"))
        elif ats == "BAMBOOHR":
            endpoints.append(urljoin(context_url, "/careers/list"))
        elif ats == "BREEZY":
            tenant = _board_slug(context_url, ("breezy.hr",))
            if not tenant:
                labels = [part for part in (context_parsed.hostname or "").split(".") if part]
                if len(labels) >= 3 and labels[-2:] == ["breezy", "hr"]:
                    tenant = labels[0]
            if tenant:
                endpoints.append(f"https://api.breezy.hr/v3/company/{tenant}/positions")
        elif ats in {"ORACLE", "ICIMS"}:
            # These vendors expose several tenant-specific public contracts;
            # retain the reviewed landing page as a candidate instead of
            # guessing a hidden API path.
            endpoints.append(context_url)
        matches.append({
            "ats": ats,
            "confidence": "HIGH" if host and any(signature.casefold() in host for signature in signatures) else "MEDIUM",
            "signals": found,
            "evidenceUrls": evidence,
            "candidateEndpoints": _unique(endpoints),
            "candidateEndpoint": _unique(endpoints)[0] if _unique(endpoints) else None,
            "tenant": context_host or None,
        })
    structured = extract_jobposting_jsonld(bounded, page_url=page_url)
    feeds = extract_feed_links(bounded, page_url=page_url)
    sitemaps = extract_sitemap_links(bounded, page_url=page_url)
    table_rows = soup.select("table tbody tr") or soup.select("table tr")
    visible_table_rows = [row for row in table_rows if row.find(["a", "td", "th"])]
    if structured and not any(item.get("ats") == "JSONLD" for item in matches):
        matches.append({
            "ats": "JSONLD",
            "confidence": "MEDIUM",
            "signals": ["schema.org/JobPosting"],
            "evidenceUrls": [page_url],
            "candidateEndpoints": [page_url],
            "candidateEndpoint": page_url,
            "tenant": host or None,
        })
    if visible_table_rows and not matches:
        matches.append({
            "ats": "STATIC_HTML",
            "confidence": "MEDIUM",
            "signals": ["visible_html_table"],
            "evidenceUrls": [page_url],
            "candidateEndpoints": [page_url],
            "candidateEndpoint": page_url,
            "tenant": host or None,
        })
    structured_completeness = _jobposting_field_completeness(structured)
    table_completeness = _table_field_completeness(visible_table_rows)
    candidate_endpoints = _unique(
        endpoint
        for match in matches
        for endpoint in match.get("candidateEndpoints", [])
    )
    candidate_endpoints.extend(value for value in feeds if value not in candidate_endpoints)
    candidate_endpoints.extend(value for value in sitemaps if value not in candidate_endpoints)
    if structured and page_url not in candidate_endpoints:
        candidate_endpoints.append(page_url)
    return {
        "pageUrl": page_url,
        "matches": matches,
        "detectedAts": matches[0]["ats"] if matches else None,
        "confidence": matches[0]["confidence"] if matches else "NONE",
        "feedLinks": feeds,
        "sitemapLinks": sitemaps,
        "structuredJobCount": len(structured),
        "visibleTableRowCount": len(visible_table_rows),
        "fieldCompleteness": round(max(structured_completeness, table_completeness), 4),
        "candidateEndpoints": candidate_endpoints,
        "candidateEndpoint": candidate_endpoints[0] if candidate_endpoints else None,
        "currentCohortSignals": detect_current_cohort_signal(bounded),
    }


def detect_ats(html: bytes | str, page_url: str) -> dict[str, Any]:
    """Short alias used by discovery scripts and operator notebooks."""

    return detect_ats_from_html(html, page_url=page_url)


def resolve_candidate_endpoints(html: bytes | str, page_url: str) -> list[str]:
    """Return de-duplicated public endpoint hints without performing requests."""

    analysis = detect_ats_from_html(html, page_url=page_url)
    values: list[str] = []
    for match in analysis.get("matches", []):
        for endpoint in match.get("candidateEndpoints", []):
            if endpoint not in values:
                values.append(endpoint)
    values.extend(value for value in analysis.get("feedLinks", []) if value not in values)
    values.extend(value for value in analysis.get("sitemapLinks", []) if value not in values)
    if analysis.get("structuredJobCount") and page_url not in values:
        values.append(page_url)
    return values


def _first_match(value: str, pattern: str) -> str | None:
    match = re.search(pattern, value, re.I)
    return match.group(1) if match and match.groups() else None


def detect_current_cohort_signal(text: bytes | str, cohort: str = "2027") -> list[str]:
    value = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text or "")
    compact = re.sub(r"\s+", "", value).casefold()
    patterns = (
        (f"{cohort}届", f"{cohort}_CAMPUS"),
        (f"{cohort}校招", f"{cohort}_CAMPUS"),
        (f"{cohort}校园招聘", f"{cohort}_CAMPUS"),
        ("秋招", "AUTUMN_RECRUITMENT"),
        ("校园招聘开放", "CAMPUS_RECRUITMENT_OPEN"),
    )
    return list(dict.fromkeys(code for marker, code in patterns if marker.casefold() in compact))


def _jobposting_field_completeness(items: Iterable[dict[str, Any]]) -> float:
    """Score the fields needed to safely map a JSON-LD JobPosting."""

    values = list(items)
    if not values:
        return 0.0
    required = ("title", "url", "description", "jobLocation", "datePosted", "hiringOrganization")
    score = sum(1 for item in values for key in required if item.get(key) not in (None, "", [], {}))
    return score / (len(values) * len(required))


def _table_field_completeness(rows: Iterable[Any]) -> float:
    """Score a visible HTML table without persisting its contents."""

    values = list(rows)
    if not values:
        return 0.0
    complete = 0
    for row in values:
        cells = row.find_all(["td", "th"])
        has_text = bool(" ".join(row.stripped_strings).strip())
        has_link = bool(row.find("a", href=True))
        # A visible row with text and an application link is enough for the
        # static adapter to be useful; location/date remain optional fields.
        complete += int(has_text) + int(has_link)
    return complete / (len(values) * 2)


def classify_discovery(
    *,
    reachable: bool,
    blocked: bool,
    status_code: int | None,
    matches: Iterable[dict[str, Any]] = (),
    candidate_endpoints: Iterable[str] = (),
    feed_links: Iterable[str] = (),
    structured_job_count: int = 0,
    visible_table_row_count: int = 0,
) -> str:
    """Map one probe to the next safe operator action.

    This is an operational classification, not a trust decision.  A
    ``CONNECTOR_CANDIDATE`` still requires official reverse-link evidence,
    robots/terms review and job sampling before registry promotion.
    """

    if blocked or not reachable or (status_code is not None and status_code >= 400):
        return "PUBLIC_ACCESS_UNAVAILABLE"
    match_values = [str(item.get("ats") or "").upper() for item in matches if isinstance(item, dict)]
    if candidate_endpoints or feed_links or structured_job_count or visible_table_row_count:
        if any(value in CONNECTOR_ATS for value in match_values) or feed_links or structured_job_count or visible_table_row_count:
            return "CONNECTOR_CANDIDATE"
    if match_values:
        return "NEEDS_MANUAL_REVIEW"
    return "MANUAL_IMPORT_ONLY"


def _review_reasons(analysis: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    matches = [item for item in analysis.get("matches", []) if isinstance(item, dict)]
    # ``extract_sitemap_links`` always supplies two conventional fallback
    # paths for a valid host.  Those hints are useful to an operator but are
    # not evidence that the page actually exposed a sitemap, so they must not
    # suppress the manual/structured review reason on an otherwise plain page.
    if not matches and not analysis.get("feedLinks") and not analysis.get("structuredJobCount") and not analysis.get("visibleTableRowCount"):
        reasons.append("ats_not_detected_use_manual_or_structured_review")
    if matches and not analysis.get("candidateEndpoints"):
        reasons.append("endpoint_not_inferred_requires_manual_contract_review")
    if not analysis.get("currentCohortSignals"):
        reasons.append("current_cohort_signal_not_found")
    if analysis.get("structuredJobCount", 0) and analysis.get("fieldCompleteness", 0) < 0.5:
        reasons.append("structured_fields_incomplete")
    return reasons


def discover_public_page(
    source_id: str,
    company_id: str,
    company_name: str,
    landing_url: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Fetch one public landing page and return a privacy-safe candidate row."""

    checked_at = datetime.now(UTC).isoformat()
    result: dict[str, Any] = {
        "sourceId": source_id,
        "companyId": company_id,
        "companyName": company_name,
        "landingUrl": landing_url,
        "checkedAt": checked_at,
        "reachable": False,
        "blocked": False,
        "requiresManualReview": True,
        "reviewReasons": [],
        "classification": "PUBLIC_ACCESS_UNAVAILABLE",
        "fieldCompleteness": 0.0,
        "candidateEndpoints": [],
        "candidateEndpoint": None,
    }
    # Discovery is restricted to public HTTPS pages.  Refuse an unsafe URL
    # before opening a connection so a malformed candidate cannot turn the
    # discovery pass into an HTTP fetcher.
    parsed_landing = urlparse(str(landing_url))
    if parsed_landing.scheme.casefold() != "https" or not parsed_landing.hostname:
        result["reviewReasons"] = ["source_url_requires_https"]
        return result
    own_client = client is None
    http_client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = http_client.get(landing_url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "autumn-assistant-source-discovery/0.3 (+public-source-audit)"})
        response_headers = getattr(response, "headers", {}) or {}
        result.update({
            "statusCode": response.status_code,
            "reachable": 200 <= response.status_code < 400,
            "blocked": response.status_code in {401, 403, 405, 429},
            "contentType": _content_type(response_headers.get("content-type", "")),
            "bytes": len(getattr(response, "content", b"")),
        })
        if response.status_code in {401, 403, 405, 429}:
            result["reviewReasons"] = ["access_blocked"]
        elif detect_security_challenge(getattr(response, "content", b"")):
            # A challenge page often returns 200 and otherwise looks like a
            # normal HTML document.  It is still an access block and must not
            # be misclassified as a manual-import page with no ATS signal.
            result.update({
                "reachable": False,
                "blocked": True,
                "reviewReasons": ["access_blocked"],
                "classification": "PUBLIC_ACCESS_UNAVAILABLE",
            })
        elif response.status_code >= 400:
            result["reviewReasons"] = ["not_found" if response.status_code == 404 else "unexpected_status"]
        else:
            analysis = detect_ats_from_html(getattr(response, "content", b""), page_url=str(getattr(response, "url", None) or landing_url))
            result.update({
                "detectedAts": analysis.get("detectedAts"),
                "confidence": analysis.get("confidence", "NONE"),
                "matches": analysis.get("matches", []),
                # Keep the vendor tenant/board identifier at the row level as
                # well as inside ``matches``.  This makes the discovery report
                # directly actionable without requiring consumers to unpack
                # the first ATS match themselves.
                "tenant": next(
                    (
                        str(match.get("tenant"))
                        for match in analysis.get("matches", [])
                        if isinstance(match, dict) and match.get("tenant")
                    ),
                    None,
                ),
                "candidateEndpoints": analysis.get("candidateEndpoints", []),
                "candidateEndpoint": analysis.get("candidateEndpoint"),
                "feedLinks": analysis.get("feedLinks", []),
                "sitemapLinks": analysis.get("sitemapLinks", []),
                "structuredJobCount": analysis.get("structuredJobCount", 0),
                "visibleTableRowCount": analysis.get("visibleTableRowCount", 0),
                "fieldCompleteness": analysis.get("fieldCompleteness", 0.0),
                "currentCohortSignals": analysis.get("currentCohortSignals", []),
                "currentCohortSignal": (analysis.get("currentCohortSignals") or [None])[0],
            })
            result["reviewReasons"] = _review_reasons(analysis)
            result["classification"] = classify_discovery(
                reachable=True,
                blocked=False,
                status_code=response.status_code,
                matches=analysis.get("matches", []),
                candidate_endpoints=analysis.get("candidateEndpoints", []),
                feed_links=analysis.get("feedLinks", []),
                structured_job_count=int(analysis.get("structuredJobCount", 0) or 0),
                visible_table_row_count=int(analysis.get("visibleTableRowCount", 0) or 0),
            )
        if response.status_code in {401, 403, 405, 429} or response.status_code >= 400:
            result["classification"] = "PUBLIC_ACCESS_UNAVAILABLE"
    except httpx.TimeoutException:
        result["reviewReasons"] = ["timeout"]
        result["classification"] = "PUBLIC_ACCESS_UNAVAILABLE"
    except httpx.RequestError:
        result["reviewReasons"] = ["request_error"]
        result["classification"] = "PUBLIC_ACCESS_UNAVAILABLE"
    finally:
        if own_client:
            http_client.close()
    return result


def discover_target_sources(
    sources: Iterable[dict[str, Any]],
    *,
    timeout: float = 15.0,
    interval_seconds: float = 0.35,
    max_domain_workers: int = 4,
) -> list[dict[str, Any]]:
    """Inspect TARGET sources without changing registry status.

    Requests are serial within one registrable traffic domain and limited to
    ``max_domain_workers`` domains in parallel.  This keeps a large candidate
    backlog from taking an entire workflow window while avoiding a burst at a
    single ATS vendor.  The returned rows retain input order for deterministic
    reports.
    """

    selected: list[tuple[int, Any]] = []
    for index, source in enumerate(sources):
        status = _source_value(source, "status")
        status = getattr(status, "value", status)
        if status is not None and str(status) != "TARGET":
            continue
        selected.append((index, source))

    groups: dict[str, list[tuple[int, Any]]] = {}
    for index, source in selected:
        landing_url = str(_source_value(source, "sourceUrl", "source_url") or "")
        host = (urlparse(landing_url).hostname or "unknown")
        groups.setdefault(_traffic_domain(host), []).append((index, source))

    def run_group(items: list[tuple[int, Any]]) -> list[tuple[int, dict[str, Any]]]:
        rows: list[tuple[int, dict[str, Any]]] = []
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            for index, source in items:
                source_id = str(_source_value(source, "sourceId", "source_id") or "unknown")
                company_id = str(_source_value(source, "companyId", "company_id") or "unknown")
                company_name = str(_source_value(source, "companyName", "company_name") or "未知企业")
                landing_url = str(_source_value(source, "sourceUrl", "source_url") or "")
                try:
                    row = discover_public_page(
                        source_id,
                        company_id,
                        company_name,
                        landing_url,
                        client=client,
                        timeout=timeout,
                    )
                except Exception as exc:  # keep one broken target from hiding the rest
                    row = {
                        "sourceId": source_id,
                        "companyId": company_id,
                        "companyName": company_name,
                        "landingUrl": landing_url,
                        "checkedAt": datetime.now(UTC).isoformat(),
                        "reachable": False,
                        "blocked": False,
                        "requiresManualReview": True,
                        "classification": "PUBLIC_ACCESS_UNAVAILABLE",
                        "reviewReasons": [f"probe_error:{exc.__class__.__name__}"],
                        "candidateEndpoint": None,
                        "candidateEndpoints": [],
                    }
                rows.append((index, row))
                if interval_seconds > 0:
                    time.sleep(interval_seconds)
        return rows

    if not groups:
        return []
    max_workers = max(1, min(int(max_domain_workers or 1), 4))
    completed: list[tuple[int, dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(groups))) as executor:
        futures = [executor.submit(run_group, items) for items in groups.values()]
        for future in as_completed(futures):
            completed.extend(future.result())
    completed.sort(key=lambda item: item[0])
    return [row for _index, row in completed]
