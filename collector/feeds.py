from __future__ import annotations

"""Conservative public ATS/feed adapters.

These adapters only use unauthenticated GET/JSON endpoints that an operator
has already reviewed in ``registry/sources.json``.  They deliberately avoid
browser execution, proxy rotation and hidden endpoint discovery.  The
response body is parsed in memory and never written to a public artifact.
"""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
import re
from typing import Any, Callable
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from .adapters import (
    USER_AGENT,
    _absolute_apply_url,
    _ats_campus_item_allowed,
    _ats_raw_job,
    _date_from_text,
    _response_json,
    _collection,
    _sleep,
    PublicJsonAdapter,
    FetchResult,
)
from .ats_discovery import extract_jobposting_jsonld
from .http_cache import CacheEntry, response_content_hash, response_headers
from .schema import RawJob, SourceConfig


def _content(response: Any) -> bytes:
    value = getattr(response, "content", None)
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        return json.dumps(response.json(), ensure_ascii=False).encode("utf-8")
    except (AttributeError, TypeError, ValueError):
        return b""


def _normalise_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    parsed = _date_from_text(value)
    if parsed:
        return parsed.isoformat()
    try:
        date_value = parsedate_to_datetime(str(value))
        if date_value.tzinfo is None:
            date_value = date_value.replace(tzinfo=UTC)
        return date_value.astimezone(UTC).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def extract_bs_global_config(html: bytes | str) -> dict[str, Any]:
    """Extract a public ``BSGlobal`` bootstrap object without executing JS.

    Northstar pages have shipped both JSON literals and simple assignment
    forms.  We only accept a bounded object literal and return an empty
    mapping when the page uses a dynamic/encoded configuration.
    """

    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else str(html or "")
    match = re.search(r"(?:window\.)?BSGlobal\s*=\s*", raw, re.I)
    if not match:
        return {}
    start = match.end()
    while start < len(raw) and raw[start].isspace():
        start += 1
    if start >= len(raw) or raw[start] != "{":
        return {}
    # A non-greedy regex stops at the first nested closing brace.  Walk a
    # bounded object instead, while respecting quoted strings and escapes; this
    # stays JSON-only and never evaluates arbitrary portal JavaScript.
    depth = 0
    quote: str | None = None
    escaped = False
    end: int | None = None
    for index in range(start, min(len(raw), start + 200_000)):
        char = raw[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"\"", "'"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        return {}
    candidate = raw[start:end]
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        # A few pages use single quotes for a JSON-compatible object.  Avoid
        # eval; only quote the common scalar form and let malformed data fail.
        try:
            value = json.loads(candidate.replace("'", '"'))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return value if isinstance(value, dict) else {}


def _local_name(value: str) -> str:
    return str(value or "").rsplit("}", 1)[-1].split(":")[-1].casefold()


def _element_text(element: ET.Element) -> str:
    return " ".join(part.strip() for part in element.itertext() if part and part.strip())


def _child_text(element: ET.Element, names: tuple[str, ...]) -> str | None:
    wanted = {name.casefold() for name in names}
    for child in element.iter():
        if child is element:
            continue
        if _local_name(child.tag) in wanted:
            value = _element_text(child)
            if value:
                return value
    return None


def _child_url(element: ET.Element, names: tuple[str, ...], base_url: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for child in element.iter():
        if child is element or _local_name(child.tag) not in wanted:
            continue
        value = (child.get("href") or child.get("url") or _element_text(child)).strip()
        if value:
            return urljoin(base_url, value)
    return None


def parse_public_feed(content: bytes, *, base_url: str = "") -> list[dict[str, Any]]:
    """Parse common RSS, Atom, Recruitee and legacy XML job feeds."""

    root = ET.fromstring(content)
    record_names = {"item", "entry", "job", "position", "posting", "jobpost", "jobposting", "offer"}
    records = [node for node in root.iter() if _local_name(node.tag) in record_names]
    if _local_name(root.tag) in record_names:
        records.insert(0, root)
    if not records:
        # Some small vendor feeds use arbitrary row names.  A node is still a
        # safe record when it contains both a title and a URL.
        for node in list(root):
            if _child_text(node, ("title", "name")) and _child_url(node, ("link", "url", "applyUrl", "apply_url"), base_url):
                records.append(node)
    output: list[dict[str, Any]] = []
    for node in records:
        title = _child_text(node, ("title", "name", "jobTitle", "job_title"))
        apply_url = _child_url(node, ("applyUrl", "apply_url", "applicationUrl", "url", "link", "hostedUrl"), base_url)
        if not title or not apply_url:
            continue
        description = _child_text(node, ("description", "summary", "content", "jobDescription", "descriptionHtml")) or ""
        location = _child_text(node, ("location", "locations", "city", "workLocation", "jobLocation")) or "未知"
        requirements = _child_text(node, ("requirements", "qualifications", "qualification", "education", "experience")) or ""
        published = _normalise_date(_child_text(node, ("pubDate", "published", "datePosted", "postedAt", "createdAt", "created")))
        deadline = _normalise_date(_child_text(node, ("validThrough", "deadline", "closingDate", "applicationDeadline")))
        source_job_id = _child_text(node, ("id", "guid", "jobId", "job_id", "requisitionId", "shortcode")) or apply_url
        output.append({
            "id": source_job_id,
            "title": title,
            "description": description,
            "requirements": requirements,
            "location": location,
            "url": apply_url,
            "publishedAt": published,
            "deadline": deadline,
            "department": _child_text(node, ("department", "team", "category")) or "",
        })
    return output


def _feed_record_count(content: bytes) -> int:
    """Count bounded, known feed record nodes for completeness checks.

    ``parse_public_feed`` intentionally returns only rows with a title and
    application URL.  Counting the source nodes separately lets the adapter
    distinguish a genuinely empty feed from a schema change that caused every
    row to be dropped, without retaining or publishing the feed body.
    """

    root = ET.fromstring(content)
    record_names = {"item", "entry", "job", "position", "posting", "jobpost", "jobposting", "offer"}
    count = sum(1 for node in root.iter() if _local_name(node.tag) in record_names)
    if count:
        return count
    # Mirror the parser's conservative arbitrary-row fallback.  This catches
    # a schema change where every row still has a title/link but no longer uses
    # RSS's conventional ``item``/``entry`` tag; it must not be published as
    # a healthy empty feed.
    return sum(
        1
        for node in list(root)
        if _child_text(node, ("title", "name"))
        and _child_url(node, ("link", "url", "applyUrl", "apply_url"), "")
    )


def feed_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    return _ats_raw_job(
        item,
        source,
        apply_value=item.get("url") or item.get("applyUrl") or item.get("hostedUrl"),
        title_value=item.get("title") or item.get("name"),
        location_value=item.get("location") or item.get("locations"),
        description_value=item.get("description") or item.get("summary") or item.get("descriptionHtml"),
        requirement_value=item.get("requirements") or item.get("qualifications"),
        source_job_id=item.get("id") or item.get("guid"),
        publish_value=item.get("publishedAt") or item.get("datePosted") or item.get("createdAt"),
    )


class PublicFeedAdapter:
    """RSS/XML adapter for reviewed Teamtailor, Recruitee and SAP feeds."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(
        self,
        source: SourceConfig,
        max_attempts: int = 2,
        cache_entry: CacheEntry | dict[str, Any] | None = None,
    ) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml", "User-Agent": USER_AGENT, "Referer": str(source.source_url)}
        headers.update(cache.request_headers())
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.client.get(str(source.endpoint), headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == max_attempts:
                    return FetchResult(source.source_id, [], 0, attempt, error=f"network_timeout:{exc.__class__.__name__}", complete=False, fetched_at=datetime.now(UTC))
                continue
            meta = response_headers(response)
            fetched_at = datetime.now(UTC)
            if response.status_code == 304:
                return FetchResult(source.source_id, [], 304, attempt, complete=True, pages=1, not_modified=True, response_headers=meta, content_hash=cache.content_hash, fetched_at=fetched_at)
            if response.status_code in {401, 403, 405, 429}:
                return FetchResult(source.source_id, [], response.status_code, attempt, blocked=True, error="access_control", complete=False, response_headers=meta, fetched_at=fetched_at)
            if response.status_code >= 500 and attempt < max_attempts:
                continue
            if response.status_code >= 400:
                return FetchResult(source.source_id, [], response.status_code, attempt, error=f"http_status:{response.status_code}", complete=False, response_headers=meta, fetched_at=fetched_at)
            try:
                raw_content = _content(response)
                items = parse_public_feed(raw_content, base_url=str(response.url if getattr(response, "url", None) else source.endpoint))
                record_count = _feed_record_count(raw_content)
            except (ET.ParseError, ValueError, UnicodeError) as exc:
                return FetchResult(source.source_id, [], response.status_code, attempt, error=f"invalid_xml:{exc.__class__.__name__}", complete=False, response_headers=meta, content_hash=response_content_hash(response), fetched_at=fetched_at)
            jobs: list[RawJob] = []
            eligible_items = 0
            invalid_items = 0
            for item in items:
                if not _ats_campus_item_allowed(item, source):
                    # A reviewed feed can legitimately mix experienced-hire
                    # rows. They count towards the observed response but do
                    # not make an otherwise healthy empty campus snapshot
                    # incomplete.
                    continue
                eligible_items += 1
                try:
                    jobs.append(feed_json_parser(item, source))
                except (TypeError, ValueError):
                    invalid_items += 1
            if not jobs and ((eligible_items and invalid_items) or (record_count and not items)):
                # Never interpret a schema change or an all-malformed feed as
                # an empty source. The caller will preserve the last valid
                # snapshot and expose the failure in source health.
                return FetchResult(source.source_id, [], response.status_code, attempt, error="invalid_items", complete=False, pages=1, response_headers=meta, content_hash=response_content_hash(response), fetched_at=fetched_at, raw_count=max(len(items), record_count))
            return FetchResult(source.source_id, jobs, response.status_code, attempt, pages=1, response_headers=meta, content_hash=response_content_hash(response), fetched_at=fetched_at, raw_count=max(len(items), record_count))
        return FetchResult(source.source_id, [], 0, max_attempts, error="retry_exhausted", complete=False)


def ashby_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    return _ats_raw_job(
        item,
        source,
        apply_value=item.get("applyUrl") or item.get("jobUrl") or item.get("url"),
        title_value=item.get("title") or item.get("name"),
        location_value=item.get("location") or item.get("locations"),
        description_value=item.get("descriptionHtml") or item.get("description") or item.get("descriptionPlain"),
        requirement_value=item.get("requirements") or item.get("qualifications"),
        source_job_id=item.get("jobPostingId") or item.get("id") or item.get("slug"),
        publish_value=item.get("publishedAt") or item.get("datePosted"),
    )


class AshbyCampusAdapter:
    """Ashby's documented public Job Board API."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 3, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        return PublicJsonAdapter(self.client).fetch(
            source,
            str(source.endpoint),
            ashby_json_parser,
            max_attempts=max_attempts,
            item_filter=lambda item: item.get("isListed") is not False and _ats_campus_item_allowed(item, source),
            cache_entry=cache_entry,
        )


def workable_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    # Workable's public widget normally returns a canonical ``url``.  Older
    # responses may expose only a shortcode; resolve that shortcode against
    # the manually reviewed board URL rather than joining it to the API path
    # (which would create an invalid application destination).
    shortcode = item.get("shortcode")
    fallback_url = urljoin(str(source.source_url).rstrip("/") + "/", f"j/{shortcode}") if shortcode not in (None, "") else None
    return _ats_raw_job(
        item,
        source,
        apply_value=item.get("url") or item.get("application_url") or fallback_url,
        title_value=item.get("title") or item.get("job_title"),
        location_value=item.get("location") or item.get("city"),
        description_value=item.get("description") or item.get("descriptionPlain"),
        requirement_value=item.get("requirements") or item.get("education"),
        source_job_id=item.get("id") or item.get("shortcode"),
        publish_value=item.get("published") or item.get("created_at"),
    )


def smartrecruiters_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    """Map SmartRecruiters' public ``postings`` response."""

    location = item.get("location")
    if isinstance(location, dict):
        location = location.get("city") or location.get("region") or location.get("country") or location.get("name")
    return _ats_raw_job(
        item,
        source,
        apply_value=item.get("ref") or item.get("url") or item.get("jobAdUrl") or item.get("applyUrl"),
        title_value=item.get("name") or item.get("title") or item.get("jobTitle"),
        location_value=location or item.get("locations"),
        description_value=item.get("jobAd") or item.get("description") or item.get("jobDescription"),
        requirement_value=item.get("requirements") or item.get("qualifications"),
        source_job_id=item.get("id") or item.get("uuid") or item.get("refNumber"),
        publish_value=item.get("releasedDate") or item.get("publishedAt") or item.get("datePosted"),
    )


def public_ats_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    """Shared conservative mapping for public JSON ATS variants."""

    return _ats_raw_job(
        item,
        source,
        apply_value=(item.get("applyUrl") or item.get("applicationUrl") or item.get("url") or
                     item.get("jobUrl") or item.get("absolute_url") or item.get("hostedUrl") or
                     item.get("detailUrl") or item.get("externalUrl")),
        title_value=item.get("title") or item.get("name") or item.get("jobTitle") or item.get("jobName") or item.get("text"),
        location_value=item.get("location") or item.get("locations") or item.get("locationsText") or item.get("city"),
        description_value=item.get("description") or item.get("descriptionHtml") or item.get("descriptionPlain") or item.get("jobDescription") or item.get("content"),
        requirement_value=item.get("requirements") or item.get("qualifications") or item.get("education"),
        source_job_id=item.get("id") or item.get("uuid") or item.get("jobId") or item.get("job_id") or item.get("requisitionId") or item.get("slug"),
        publish_value=item.get("publishedAt") or item.get("datePosted") or item.get("postedAt") or item.get("createdAt") or item.get("releasedDate"),
    )


class PublicAtsJsonAdapter:
    """GET-only adapter for reviewed public ATS JSON endpoints.

    The endpoint must be explicitly registered and domain-allowlisted.  No
    tenant path, API token or browser session is inferred here.
    """

    def __init__(self, parser: Callable[[dict[str, Any], SourceConfig], RawJob] = public_ats_json_parser, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.parser = parser
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 3, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        from .adapters import PublicJsonAdapter

        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        return PublicJsonAdapter(self.client).fetch(
            source,
            str(source.endpoint),
            self.parser,
            max_attempts=max_attempts,
            item_filter=lambda item: _ats_campus_item_allowed(item, source),
            cache_entry=cache_entry,
        )


class SmartRecruitersCampusAdapter(PublicAtsJsonAdapter):
    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        super().__init__(parser=smartrecruiters_json_parser, client=client, timeout=timeout)


class PersonioCampusAdapter(PublicFeedAdapter):
    """Personio's public XML feed, parsed with the same safe feed contract."""


class BambooHRCampusAdapter(PublicAtsJsonAdapter):
    pass


class BreezyCampusAdapter(PublicAtsJsonAdapter):
    pass


class OracleCampusAdapter(PublicAtsJsonAdapter):
    pass


class ICIMSCampusAdapter(PublicAtsJsonAdapter):
    pass


class WorkableCampusAdapter:
    """Public Workable widget JSON; no hosted dataset or browser required."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 3, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        from .adapters import PublicJsonAdapter

        return PublicJsonAdapter(self.client).fetch(
            source,
            str(source.endpoint or source.source_url),
            workable_json_parser,
            max_attempts=max_attempts,
            item_filter=lambda item: _ats_campus_item_allowed(item, source),
            cache_entry=cache_entry,
        )


def beisen_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    return _ats_raw_job(
        item,
        source,
        apply_value=item.get("applyUrl") or item.get("url") or item.get("detailUrl"),
        title_value=item.get("jobName") or item.get("jobTitle") or item.get("title") or item.get("name"),
        location_value=item.get("cityName") or item.get("city") or item.get("location"),
        description_value=item.get("jobDescription") or item.get("description"),
        requirement_value=item.get("qualification") or item.get("requirements"),
        source_job_id=item.get("jobId") or item.get("id"),
        publish_value=item.get("publishTime") or item.get("publishDate") or item.get("createdAt"),
    )


class BeisenCampusAdapter:
    """Generic public Beisen/iTalent JSON envelope after manual review."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 3, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        from .adapters import PublicJsonAdapter

        return PublicJsonAdapter(self.client).fetch(
            source,
            str(source.endpoint or source.source_url),
            beisen_json_parser,
            max_attempts=max_attempts,
            item_filter=lambda item: _ats_campus_item_allowed(item, source),
            cache_entry=cache_entry,
        )


def _beisen_page_items(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    """Read modern/legacy Northstar envelopes without guessing deep paths."""

    items, found = _collection(payload)
    if not found:
        return [], None
    total: int | None = None
    if isinstance(payload, dict):
        for key in ("total", "totalCount", "totalNum", "count"):
            value = payload.get(key)
            if value is not None:
                try:
                    total = int(value)
                    break
                except (TypeError, ValueError):
                    pass
        data = payload.get("data")
        if isinstance(data, dict) and total is None:
            for key in ("total", "totalCount", "totalNum", "count"):
                try:
                    if data.get(key) is not None:
                        total = int(data[key])
                        break
                except (TypeError, ValueError):
                    pass
    return [item for item in items if isinstance(item, dict)], total


class BeisenModernCampusAdapter:
    """Public BSGlobal/Northstar campus endpoint.

    Modern portals expose a small public configuration request followed by a
    job list endpoint.  The endpoint and tenant still have to be registered by
    an operator; this adapter only sends the explicit campus category ``2``
    and never decrypts or executes portal scripts.
    """

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 3, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        endpoint = str(source.endpoint)
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT, "Referer": str(source.source_url)}
        headers.update(cache.request_headers())
        output: list[RawJob] = []
        seen: set[str] = set()
        total_attempts = 0
        total_observed = 0
        last_headers: dict[str, str] = {}
        last_hash: str | None = None
        last_fetched: datetime | None = None
        for page in range(source.max_pages):
            body = {
                "PageIndex": page + 1,
                "PageSize": source.page_size,
                "pageIndex": page + 1,
                "pageSize": source.page_size,
                "Category": ["2"],
                "category": ["2"],
                "Keyword": "",
            }
            response: Any = None
            for attempt in range(1, max_attempts + 1):
                total_attempts += 1
                try:
                    response = self.client.post(endpoint, headers=headers, json=body)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == max_attempts:
                        return FetchResult(source.source_id, [], 0, total_attempts, error=f"network_timeout:{exc.__class__.__name__}", complete=False, pages=page)
                    continue
                if response.status_code == 304 and page == 0:
                    return FetchResult(source.source_id, [], 304, total_attempts, complete=True, pages=1, not_modified=True, response_headers=response_headers(response), content_hash=cache.content_hash, fetched_at=datetime.now(UTC))
                if response.status_code in {401, 403, 405, 429}:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, blocked=True, error="access_control", complete=False, pages=page, response_headers=response_headers(response), fetched_at=datetime.now(UTC))
                if response.status_code >= 500 and attempt < max_attempts:
                    continue
                if response.status_code >= 400:
                    return FetchResult(source.source_id, [], response.status_code, total_attempts, error=f"http_status:{response.status_code}", complete=False, pages=page, response_headers=response_headers(response), fetched_at=datetime.now(UTC))
                break
            if response is None:
                return FetchResult(source.source_id, [], 0, total_attempts, error="retry_exhausted", complete=False, pages=page)
            try:
                payload = _response_json(response)
                items, expected_total = _beisen_page_items(payload)
            except (ValueError, TypeError, json.JSONDecodeError):
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error="invalid_json", complete=False, pages=page, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=total_observed)
            if not items and expected_total is None and page == 0:
                return FetchResult(source.source_id, [], response.status_code, total_attempts, error="incomplete_payload", complete=False, pages=page, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=total_observed)
            total_observed += len(items)
            last_headers = response_headers(response)
            last_hash = response_content_hash(response) or last_hash
            last_fetched = datetime.now(UTC)
            for item in items:
                if not _ats_campus_item_allowed(item, source):
                    continue
                try:
                    job = beisen_json_parser(item, source)
                except (TypeError, ValueError):
                    continue
                key = job.source_job_id or str(job.apply_url)
                if key not in seen:
                    seen.add(key)
                    output.append(job)
            if not items or len(items) < source.page_size or (expected_total is not None and total_observed >= expected_total):
                return FetchResult(source.source_id, output, response.status_code, total_attempts, pages=page + 1, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched, raw_count=total_observed)
            _sleep(source)
        return FetchResult(source.source_id, [], 200, total_attempts, error="truncated_feed", complete=False, pages=source.max_pages, response_headers=last_headers, content_hash=last_hash, fetched_at=last_fetched, raw_count=total_observed)


class BeisenLegacyCampusAdapter:
    """Server-rendered ``/Campus`` fallback for older Beisen portals."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 1, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        if not source.endpoint:
            return FetchResult(source.source_id, [], 0, 0, error="endpoint_not_configured", complete=False)
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers = {"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT, "Referer": str(source.source_url)}
        headers.update(cache.request_headers())
        try:
            response = self.client.get(str(source.endpoint), headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return FetchResult(source.source_id, [], 0, 1, error=f"network_timeout:{exc.__class__.__name__}", complete=False, fetched_at=datetime.now(UTC))
        if response.status_code == 304:
            return FetchResult(source.source_id, [], 304, 1, complete=True, pages=1, not_modified=True, response_headers=response_headers(response), content_hash=cache.content_hash, fetched_at=datetime.now(UTC))
        if response.status_code in {401, 403, 405, 429}:
            return FetchResult(source.source_id, [], response.status_code, 1, blocked=True, error="access_control", complete=False, response_headers=response_headers(response), fetched_at=datetime.now(UTC))
        if response.status_code >= 400:
            return FetchResult(source.source_id, [], response.status_code, 1, error=f"http_status:{response.status_code}", complete=False, response_headers=response_headers(response), fetched_at=datetime.now(UTC))
        soup = BeautifulSoup(_content(response)[:4 * 1024 * 1024], "html.parser")
        nodes = soup.select(".job-item, .job-list-item, li[class*=job], [data-job-id]")
        if not nodes:
            nodes = soup.select("table tr")
        jobs: list[RawJob] = []
        for index, node in enumerate(nodes):
            links = node.find_all("a", href=True)
            link = next((item for item in links if "campus" in " ".join(item.stripped_strings).casefold() or item.get("href")), None)
            if link is None:
                continue
            title = " ".join(link.stripped_strings).strip() or " ".join(node.stripped_strings).strip()
            href = urljoin(str(getattr(response, "url", None) or source.endpoint), str(link.get("href")))
            item = {"id": node.get("data-job-id") or href or index, "title": title, "url": href, "location": "未知", "description": " ".join(node.stripped_strings)}
            if not _ats_campus_item_allowed(item, source):
                continue
            try:
                jobs.append(beisen_json_parser(item, source))
            except (TypeError, ValueError):
                continue
        if not jobs:
            return FetchResult(source.source_id, [], response.status_code, 1, error="legacy_beisen_jobs_not_found", complete=False, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=len(nodes))
        return FetchResult(source.source_id, jobs, response.status_code, 1, pages=1, response_headers=response_headers(response), content_hash=response_content_hash(response), fetched_at=datetime.now(UTC), raw_count=len(nodes))


def _jsonld_location(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    output: list[str] = []
    for item in values:
        if isinstance(item, str):
            output.append(item)
            continue
        if not isinstance(item, dict):
            continue
        address = item.get("address") if isinstance(item.get("address"), dict) else item
        parts = [address.get(key) for key in ("streetAddress", "addressLocality", "addressRegion", "addressCountry") if address.get(key)]
        if parts:
            output.append(" · ".join(str(part) for part in parts))
    return "、".join(output) or "未知"


def jsonld_job_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    organization = item.get("hiringOrganization") if isinstance(item.get("hiringOrganization"), dict) else {}
    return _ats_raw_job(
        item,
        source,
        apply_value=item.get("url") or item.get("sameAs") or source.source_url,
        title_value=item.get("title") or item.get("name"),
        location_value=_jsonld_location(item.get("jobLocation")),
        description_value=item.get("description") or item.get("responsibilities"),
        requirement_value=item.get("qualifications") or item.get("educationRequirements") or item.get("experienceRequirements"),
        source_job_id=item.get("identifier") if not isinstance(item.get("identifier"), dict) else item["identifier"].get("value"),
        publish_value=item.get("datePosted"),
    )


class JsonLdCampusAdapter:
    """Low-maintenance fallback for official pages exposing JobPosting JSON-LD."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 2, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers = {"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT, "Referer": str(source.source_url)}
        headers.update(cache.request_headers())
        try:
            response = self.client.get(str(source.endpoint or source.source_url), headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return FetchResult(source.source_id, [], 0, 1, error=f"network_timeout:{exc.__class__.__name__}", complete=False, fetched_at=datetime.now(UTC))
        meta = response_headers(response)
        fetched_at = datetime.now(UTC)
        if response.status_code == 304:
            return FetchResult(source.source_id, [], 304, 1, complete=True, pages=1, not_modified=True, response_headers=meta, content_hash=cache.content_hash, fetched_at=fetched_at)
        if response.status_code in {401, 403, 405, 429}:
            return FetchResult(source.source_id, [], response.status_code, 1, blocked=True, error="access_control", complete=False, response_headers=meta, fetched_at=fetched_at)
        if response.status_code >= 400:
            return FetchResult(source.source_id, [], response.status_code, 1, error=f"http_status:{response.status_code}", complete=False, response_headers=meta, fetched_at=fetched_at)
        items = extract_jobposting_jsonld(_content(response), page_url=str(getattr(response, "url", None) or source.source_url))
        jobs: list[RawJob] = []
        for item in items:
            if not _ats_campus_item_allowed(item, source):
                continue
            try:
                jobs.append(jsonld_job_parser(item, source))
            except (TypeError, ValueError):
                continue
        if not jobs:
            return FetchResult(source.source_id, [], response.status_code, 1, error="structured_jobposting_not_found", complete=False, response_headers=meta, content_hash=response_content_hash(response), fetched_at=fetched_at, raw_count=len(items))
        return FetchResult(source.source_id, jobs, response.status_code, 1, pages=1, response_headers=meta, content_hash=response_content_hash(response), fetched_at=fetched_at, raw_count=len(items))


class StaticHtmlCampusAdapter:
    """Reviewed server-rendered table fallback.

    This parser is intentionally limited to visible HTML tables.  It does not
    execute scripts or infer arbitrary selectors, which keeps the fallback
    useful for small official campaign pages without turning it into a
    generic scraper.
    """

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source: SourceConfig, max_attempts: int = 1, cache_entry: CacheEntry | dict[str, Any] | None = None) -> FetchResult:
        cache = cache_entry if isinstance(cache_entry, CacheEntry) else CacheEntry.from_value(cache_entry)
        headers = {"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT, "Referer": str(source.source_url)}
        headers.update(cache.request_headers())
        try:
            response = self.client.get(str(source.endpoint or source.source_url), headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return FetchResult(source.source_id, [], 0, 1, error=f"network_timeout:{exc.__class__.__name__}", complete=False, fetched_at=datetime.now(UTC))
        meta = response_headers(response)
        fetched_at = datetime.now(UTC)
        if response.status_code == 304:
            return FetchResult(source.source_id, [], 304, 1, complete=True, pages=1, not_modified=True, response_headers=meta, content_hash=cache.content_hash, fetched_at=fetched_at)
        if response.status_code in {401, 403, 405, 429}:
            return FetchResult(source.source_id, [], response.status_code, 1, blocked=True, error="access_control", complete=False, response_headers=meta, fetched_at=fetched_at)
        if response.status_code >= 400:
            return FetchResult(source.source_id, [], response.status_code, 1, error=f"http_status:{response.status_code}", complete=False, response_headers=meta, fetched_at=fetched_at)
        soup = BeautifulSoup(_content(response)[:4 * 1024 * 1024], "html.parser")
        jobs: list[RawJob] = []
        rows = soup.select("table tbody tr") or soup.select("table tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            links = row.find_all("a", href=True)
            title = ""
            apply_url = ""
            for link in links:
                label = " ".join(link.stripped_strings).strip()
                if label and not title:
                    title = label
                if not apply_url:
                    apply_url = urljoin(str(getattr(response, "url", None) or source.source_url), str(link.get("href")))
            if not title:
                title = " ".join(cells[0].stripped_strings).strip()
            if not title or not apply_url:
                continue
            values = [" ".join(cell.stripped_strings).strip() for cell in cells]
            item = {"title": title, "location": "、".join(values[1:2]) or "未知", "description": " ".join(values), "url": apply_url, "publishedAt": next((value for value in values if _normalise_date(value)), None)}
            if not _ats_campus_item_allowed(item, source):
                continue
            try:
                jobs.append(feed_json_parser(item, source))
            except (TypeError, ValueError):
                continue
        if not jobs:
            return FetchResult(source.source_id, [], response.status_code, 1, error="static_table_not_found", complete=False, response_headers=meta, content_hash=response_content_hash(response), fetched_at=fetched_at, raw_count=len(rows))
        return FetchResult(source.source_id, jobs, response.status_code, 1, pages=1, response_headers=meta, content_hash=response_content_hash(response), fetched_at=fetched_at, raw_count=len(rows))


# Keep explicit connector names available to callers and operator notebooks
# while sharing the same reviewed, unauthenticated feed implementation.  The
# aliases also make the adapter matrix visible without adding near-identical
# classes for each vendor's RSS/XML transport.
TeamtailorCampusAdapter = PublicFeedAdapter
RecruiteeCampusAdapter = PublicFeedAdapter
SuccessFactorsCampusAdapter = PublicFeedAdapter
