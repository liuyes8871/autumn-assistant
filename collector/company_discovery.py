from __future__ import annotations

"""Discovery-only helpers for expanding the employer candidate pool.

The weekly discovery job is intentionally separate from the live job
collector.  It may read a public exchange/SASAC/company-directory page and
produce a de-duplicated list of names for human review, but it must never
turn a discovered name into a runnable source.  A candidate still needs a
first-party campus URL, robots/terms review and a tested adapter before it can
be marked ``VERIFIED`` in ``registry/sources.json``.

The parsers below are deliberately conservative.  They accept common JSON
envelopes and HTML tables, retain only lightweight identity fields, and never
persist a response body or copy a directory's full contents into the public
catalog.
"""

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
import unicodedata
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import httpx

from .ats_discovery import detect_security_challenge
from .registry import focus_company_map, load_companies, load_focus_registry
from .sasac import parse_sasac_central_enterprises, SasacStructureError


DISCOVERY_SCHEMA_VERSION = 1
DISCOVERY_USER_AGENT = "autumn-assistant-company-discovery/0.1 (+public-source-audit)"
NON_RETRYABLE_STATUS = {401, 403, 405, 429}
MAX_AUTHORITY_BYTES = 4 * 1024 * 1024
MAX_CAREER_BYTES = 1 * 1024 * 1024
CURRENT_COHORT = "2027"

# Daily entry probes are intentionally a very small public contract.  The
# probe may receive an HTTP response object internally, but neither response
# bodies nor request/session metadata belong in a discovery report or state
# file.  Keep this allow-list close to the merge code so fixture inputs and
# future adapters share the same privacy boundary.
ENTRY_DIRECTORY_STATUSES = {"DISCOVERED", "ACTIVE_CONFIRMED", "ACTIVE_LEAD", "INACTIVE", "BLOCKED", "STALE"}
ENTRY_TYPES = {"OFFICIAL_CAREER_SITE", "OFFICIAL_ATS", "OFFICIAL_CAMPAIGN_PAGE", "ENTRY_LEAD"}
ENTRY_OBSERVATION_KEYS = {
    "companyId",
    "companyName",
    "cohort",
    "directoryStatus",
    "entryType",
    "careerUrl",
    "evidenceUrl",
    "evidenceText",
    "signals",
    "detectedSignals",
    "checkedAt",
    "lastCheckedAt",
    "firstConfirmedAt",
    "reachable",
    "blocked",
    "public",
    "statusCode",
    "contentType",
    "bytes",
    "errorType",
    "lastErrorType",
    "consecutiveFailures",
}

# These patterns are intentionally narrow.  A company is not promoted merely
# because its name or an unrelated social post contains a year; the page text
# must expose a current campus-recruiting signal.
CAMPUS_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("COHORT", re.compile(r"(?:2027\s*届|2027\s*级|2027校招|2027校园招聘)", re.I)),
    ("AUTUMN_RECRUITMENT", re.compile(r"(?:秋招|秋季校园招聘|秋季招聘|秋季校招)", re.I)),
    ("CAMPUS_RECRUITMENT_OPEN", re.compile(r"(?:校园招聘(?:已|现)?开放|校招(?:已|现)?启动|校园招聘正式启动|校园招聘开放)", re.I)),
)

NAME_KEYS = (
    "name",
    "companyName",
    "company_name",
    "fullName",
    "enterpriseName",
    "enterprise_name",
    "orgName",
    "org_name",
    "SEC_NAME_CN",
    "SEC_NAME_FULL",
    "FULL_NAME",
    "证券简称",
    "证券名称",
    "公司名称",
    "企业名称",
    "简称",
)
CODE_KEYS = (
    "stockCode",
    "stock_code",
    "code",
    "证券代码",
    "股票代码",
    "A_STOCK_CODE",
    "B_STOCK_CODE",
    "COMPANY_CODE",
)
MARKET_KEYS = ("market", "exchange", "listingMarket", "上市市场", "交易所")


def _bounded_text(value: Any, limit: int) -> str | None:
    """Return a compact scalar string, never an arbitrary nested payload."""

    if isinstance(value, bool) or value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    return text[:limit]


def _safe_url(value: Any) -> str | None:
    text = _bounded_text(value, 2048)
    if not text:
        return None
    parsed = urlparse(text)
    # Entry observations are evidence for a public link.  Reject credentials,
    # javascript/data URLs and other values that could become an unsafe link
    # when rendered by the web client.
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return text


def sanitize_entry_observation(value: Any) -> dict[str, Any] | None:
    """Strip untrusted fields from one daily entry observation.

    This function is deliberately deterministic and schema-shaped.  Unknown
    keys (including ``html``, ``responseBody``, ``cookies``, ``headers`` and
    internal exception objects) are discarded rather than recursively copied.
    """

    if not isinstance(value, dict):
        return None
    company_id = _bounded_text(value.get("companyId"), 160)
    if not company_id:
        return None
    result: dict[str, Any] = {"companyId": company_id}
    for key, limit in (("companyName", 200), ("cohort", 32), ("evidenceText", 320), ("checkedAt", 80), ("lastCheckedAt", 80), ("firstConfirmedAt", 80), ("errorType", 96), ("lastErrorType", 96), ("contentType", 96)):
        text = _bounded_text(value.get(key), limit)
        if text is not None:
            result[key] = text
    for key in ("careerUrl", "evidenceUrl"):
        url = _safe_url(value.get(key))
        if url is not None:
            result[key] = url
    status = _bounded_text(value.get("directoryStatus"), 32)
    if status in ENTRY_DIRECTORY_STATUSES:
        result["directoryStatus"] = status
    entry_type = _bounded_text(value.get("entryType"), 40)
    if entry_type in ENTRY_TYPES:
        result["entryType"] = entry_type
    signals_value = value.get("signals", value.get("detectedSignals"))
    if isinstance(signals_value, list):
        signals: list[str] = []
        for item in signals_value[:32]:
            text = _bounded_text(item, 120)
            if text and text not in signals:
                signals.append(text)
        result["signals"] = signals
        # Keep the alias used by the persisted directory schema, but never
        # duplicate arbitrary values under unknown keys.
        result["detectedSignals"] = list(signals)
    for key in ("reachable", "blocked", "public"):
        if isinstance(value.get(key), bool):
            result[key] = value[key]
    for key, lower, upper in (("statusCode", 100, 599), ("bytes", 0, 100_000_000), ("consecutiveFailures", 0, 100)):
        raw = value.get(key)
        if isinstance(raw, bool):
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if lower <= number <= upper:
            result[key] = number
    return result


def sanitize_entry_observation_map(value: Any) -> dict[str, dict[str, Any]]:
    """Sanitize a persisted ``companyId -> observation`` mapping."""

    if not isinstance(value, dict):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for company_id, observation in value.items():
        key = _bounded_text(company_id, 160)
        if not key or not isinstance(observation, dict):
            continue
        # The mapping key is authoritative; do not let a nested companyId
        # redirect an observation to another company.
        candidate = dict(observation)
        candidate["companyId"] = key
        clean = sanitize_entry_observation(candidate)
        if clean:
            output[key] = clean
    return output


def detect_campus_signals(text: str, *, cohort: str = CURRENT_COHORT) -> list[str]:
    """Return stable signal codes from a bounded, visible page-text sample."""

    value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).casefold()
    if not value:
        return []
    signals: list[str] = []
    cohort_pattern = re.compile(rf"{re.escape(cohort)}(?:届|级|校招|校园招聘)", re.I)
    if cohort_pattern.search(value):
        signals.append(f"{cohort}_CAMPUS")
    # The generic patterns are useful when an official page omits the year,
    # but only in combination with a current-page observation.  Keep their
    # codes stable so reports can be diffed between daily runs.
    if re.search(r"(?:秋招|秋季校园招聘|秋季招聘|秋季校招)", value, re.I):
        signals.append("AUTUMN_RECRUITMENT")
    if re.search(r"(?:校园招聘(?:已|现)?开放|校招(?:已|现)?启动|校园招聘正式启动)", value, re.I):
        signals.append("CAMPUS_RECRUITMENT_OPEN")
    return list(dict.fromkeys(signals))


def entry_type_for_url(url: str) -> str:
    value = str(url or "").lower()
    if any(token in value for token in ("jobs.feishu.cn", "zhiye.com", "mokahr.com", "myworkdayjobs.com", "greenhouse.io", "lever.co", "successfactors")):
        return "OFFICIAL_ATS"
    if any(token in value for token in ("/campus", "xiaozhao", "school", "campus-recruit", "校园")):
        return "OFFICIAL_CAMPAIGN_PAGE"
    return "OFFICIAL_CAREER_SITE"


def normalize_company_name(value: Any) -> str:
    """Return a stable comparison key without changing the display name."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    # Keep Chinese characters and letters/digits, dropping legal suffix
    # punctuation and whitespace.  Suffixes are retained: “腾讯” and “腾讯音乐”
    # must not be merged merely because both are internet companies.
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


def candidate_id_for(name: str) -> str:
    digest = hashlib.sha256(normalize_company_name(name).encode("utf-8")).hexdigest()[:12]
    return f"candidate-{digest}"


def _first(record: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    output: list[str] = []
    for item in values:
        if isinstance(item, dict):
            item = _first(item, ("code", "value", "name"))
        text = str(item or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _iter_json_records(payload: Any) -> Iterable[dict[str, Any]]:
    """Yield likely company records from common public directory envelopes."""

    if isinstance(payload, list):
        for value in payload:
            if isinstance(value, dict):
                yield value
        return
    if not isinstance(payload, dict):
        return
    # Prefer explicit collection keys so an envelope's metadata is never
    # mistaken for a company.  Nested ``data``/``result`` envelopes are
    # traversed recursively with a small depth bound by the call structure.
    for key in ("companies", "companyList", "items", "results", "list", "rows", "records", "data", "result", "Data", "d", "pageHelp"):
        value = payload.get(key)
        if isinstance(value, list):
            yield from _iter_json_records(value)
        elif isinstance(value, dict):
            yield from _iter_json_records(value)


def parse_json_authority(payload: Any, *, authority_id: str, source_url: str) -> list[dict[str, Any]]:
    """Extract lightweight candidates from a JSON authority response."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in _iter_json_records(payload):
        name_value = _first(record, NAME_KEYS)
        name = str(name_value or "").strip()
        key = normalize_company_name(name)
        # A company row must have a plausible name.  This avoids turning
        # pagination metadata and empty records into candidate companies.
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        rows.append(_candidate_row(
            name=name,
            authority_id=authority_id,
            source_url=source_url,
            stock_codes=_string_list(_first(record, CODE_KEYS)),
            market=str(_first(record, MARKET_KEYS) or "").strip() or None,
            raw_fields={
                "employeeCount": _first(record, ("employeeCount", "employee_count", "员工人数", "员工数")),
                "industry": _first(record, ("industry", "行业", "所属行业")),
            },
        ))
    return rows


def parse_html_authority(html: str, *, authority_id: str, source_url: str) -> list[dict[str, Any]]:
    """Extract names from HTML tables without retaining arbitrary page text."""

    if authority_id == "sasac-central-soes":
        # Keep the public helper correct for callers that parse a fixture
        # directly rather than going through ``fetch_authority_candidates``.
        rows: list[dict[str, Any]] = []
        for item in parse_sasac_central_enterprises(html, source_url=source_url):
            row = _candidate_row(
                name=str(item.get("name") or "").strip(),
                authority_id=authority_id,
                source_url=source_url,
                stock_codes=[],
                market=None,
                raw_fields={},
            )
            row.update({
                "authorityRank": item.get("rank"),
                "groupId": item.get("groupId"),
                "homepageObserved": item.get("homepageObserved"),
                "homepage": item.get("homepage"),
                "ownershipClass": "CENTRAL_GROUP",
                "homepageReviewRequired": bool(item.get("homepageReviewRequired")),
            })
            rows.append(row)
        return rows
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [" ".join(cell.stripped_strings) for cell in tr.find_all(["th", "td"])]
            if not cells:
                continue
            joined = " ".join(cells)
            # Skip header rows; only accept rows carrying a recognizable
            # Chinese/Latin company-like token and avoid navigation labels.
            if any(marker in joined for marker in ("公司名称", "证券简称", "股票代码", "Company Name")) and len(cells) <= 3:
                continue
            name = _pick_html_name(cells)
            key = normalize_company_name(name)
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            code_match = re.search(r"(?<!\d)(\d{5,6})(?!\d)", joined)
            rows.append(_candidate_row(
                name=name,
                authority_id=authority_id,
                source_url=source_url,
                stock_codes=[code_match.group(1)] if code_match else [],
                market=None,
                raw_fields={},
            ))
    return rows


def _pick_html_name(cells: list[str]) -> str:
    # Prefer the first non-code cell.  Exchange tables generally place code
    # first and the short name second; ordinary directories place name first.
    for cell in cells:
        value = cell.strip()
        if not value or re.fullmatch(r"\d{5,6}", value):
            continue
        if re.search(r"公司|集团|银行|证券|股份|有限|科技|网络|互联网|控股|能源|物流|零售|汽车|电商|信息", value) or re.search(r"[\u3400-\u9fff]", value):
            return value[:120]
    return cells[0].strip()[:120]


def _candidate_row(
    *,
    name: str,
    authority_id: str,
    source_url: str,
    stock_codes: list[str],
    market: str | None,
    raw_fields: dict[str, Any],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "candidateId": candidate_id_for(name),
        "name": name,
        "normalizedName": normalize_company_name(name),
        "aliases": [],
        "authorityIds": [authority_id],
        "sourceUrls": [source_url],
        "stockCodes": stock_codes,
        "listingMarket": market,
        "discoveryStatus": "DISCOVERED",
        "requiresOfficialCareerReview": True,
    }
    if raw_fields.get("employeeCount") not in (None, ""):
        row["employeeCountObserved"] = raw_fields["employeeCount"]
    if raw_fields.get("industry") not in (None, ""):
        row["industryObserved"] = raw_fields["industry"]
    return row


def merge_discovered_candidates(
    existing_companies: Iterable[dict[str, Any]],
    discovered_rows: Iterable[dict[str, Any]],
    *,
    focus_companies: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge duplicate authority rows and match known registry companies."""

    existing_by_name: dict[str, dict[str, Any]] = {}
    for company in existing_companies:
        if not isinstance(company, dict):
            continue
        names = [company.get("name"), *(company.get("aliases") or [])]
        for value in names:
            key = normalize_company_name(value)
            if key:
                existing_by_name[key] = company

    merged: dict[str, dict[str, Any]] = {}
    for row in discovered_rows:
        name = str(row.get("name") or "").strip()
        key = normalize_company_name(row.get("normalizedName") or name)
        if len(key) < 2:
            continue
        existing = existing_by_name.get(key)
        candidate = merged.setdefault(key, {
            "candidateId": row.get("candidateId") or candidate_id_for(name),
            "name": name,
            "normalizedName": key,
            "aliases": [],
            "authorityIds": [],
            "sourceUrls": [],
            "stockCodes": [],
            "listingMarket": None,
            "discoveryStatus": "MATCHED_REGISTRY" if existing else "DISCOVERED",
            "matchedCompanyId": existing.get("id") if existing else None,
            "matchedCompanyName": existing.get("name") if existing else None,
            "requiresOfficialCareerReview": True,
        })
        for field in ("authorityIds", "sourceUrls", "stockCodes"):
            for value in row.get(field) or []:
                if value not in candidate[field]:
                    candidate[field].append(value)
        if row.get("listingMarket") and not candidate.get("listingMarket"):
            candidate["listingMarket"] = row["listingMarket"]
        for field in ("employeeCountObserved", "industryObserved"):
            if row.get(field) not in (None, "") and field not in candidate:
                candidate[field] = row[field]
        if focus_companies and existing and existing.get("id") in focus_companies:
            candidate["focusPriority"] = focus_companies[existing["id"]].get("priority")
            candidate["focusSegment"] = focus_companies[existing["id"]].get("segment")

    return sorted(merged.values(), key=lambda row: (
        0 if row.get("focusPriority") is not None else 1,
        int(row.get("focusPriority", 99)),
        str(row.get("name", "")),
    ))


def _authority_rows_from_response(response: httpx.Response, *, authority_id: str, source_url: str) -> list[dict[str, Any]]:
    content = response.content[:MAX_AUTHORITY_BYTES]
    # The SASAC page is a fixed two-column table: each HTML row contains two
    # independent enterprises. The generic table parser intentionally handles
    # one name per row, so use the dedicated parser here to avoid silently
    # dropping enterprises 51--99.
    if authority_id == "sasac-central-soes":
        try:
            sasac_rows = parse_sasac_central_enterprises(content, source_url=source_url, strict=False)
        except (SasacStructureError, ValueError, TypeError):
            return []
        output: list[dict[str, Any]] = []
        for item in sasac_rows:
            row = _candidate_row(
                name=str(item.get("name") or "").strip(),
                authority_id=authority_id,
                source_url=source_url,
                stock_codes=[],
                market=None,
                raw_fields={},
            )
            row.update({
                "authorityRank": item.get("rank"),
                "groupId": item.get("groupId"),
                "homepageObserved": item.get("homepageObserved"),
                "homepage": item.get("homepage"),
                "ownershipClass": "CENTRAL_GROUP",
                "homepageReviewRequired": bool(item.get("homepageReviewRequired")),
            })
            output.append(row)
        return output
    content_type = response.headers.get("content-type", "").lower()
    # A few public endpoints omit ``Content-Type`` or return
    # ``text/plain`` for JSON.  Sniff only the first non-whitespace byte as a
    # compatibility fallback; the body is still parsed only as a bounded,
    # discovery-only response.
    looks_like_json = content.lstrip()[:1] in {b"{", b"["}
    if "json" in content_type or looks_like_json:
        try:
            return parse_json_authority(json.loads(content.decode("utf-8")), authority_id=authority_id, source_url=source_url)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
    try:
        return parse_html_authority(content.decode("utf-8", errors="replace"), authority_id=authority_id, source_url=source_url)
    except Exception:
        # A malformed authority page should be visible as an empty result;
        # callers record the error metadata and never promote candidates.
        return []


def _authority_payload(response: httpx.Response) -> Any:
    """Decode a JSON authority response for pagination metadata only."""

    content = response.content[:MAX_AUTHORITY_BYTES]
    content_type = response.headers.get("content-type", "").lower()
    looks_like_json = content.lstrip()[:1] in {b"{", b"["}
    if "json" not in content_type and not looks_like_json:
        return None
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _page_meta(payload: Any) -> tuple[int | None, int | None]:
    """Return (total, page_size) from common exchange pagination envelopes."""

    if not isinstance(payload, dict):
        return None, None
    candidates = [payload]
    for key in ("pageHelp", "pagination", "meta", "data", "result", "Data", "d"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    total: int | None = None
    page_size: int | None = None
    for item in candidates:
        for key in ("total", "totalCount", "count", "recordsTotal"):
            try:
                if item.get(key) not in (None, ""):
                    total = int(item[key])
                    break
            except (TypeError, ValueError):
                pass
        for key in ("pageSize", "size", "limit"):
            try:
                if item.get(key) not in (None, ""):
                    page_size = int(item[key])
                    break
            except (TypeError, ValueError):
                pass
        if total is not None and page_size is not None:
            break
    return total, page_size


def fetch_authority_candidates(authorities_path: Path, *, timeout: float = 15.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch authority pages once, returning rows plus safe status metadata."""

    authorities = json.loads(authorities_path.read_text(encoding="utf-8"))
    checked_at = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": DISCOVERY_USER_AGENT}) as client:
        for authority in authorities if isinstance(authorities, list) else []:
            if not isinstance(authority, dict):
                continue
            authority_id = str(authority.get("id") or "unknown")
            url = str(authority.get("url") or "")
            result: dict[str, Any] = {
                "id": authority_id,
                "url": url,
                "checkedAt": checked_at,
                "candidateCount": 0,
                "pagesFetched": 0,
                "complete": False,
            }
            if authority_id == "sasac-central-soes":
                result["expectedCount"] = int(authority.get("expectedCount", 99) or 99)
            if not url:
                result.update({"reachable": False, "errorType": "missing_url"})
                checks.append(result)
                continue
            try:
                # Some official exchange pages render an empty table and
                # load the same public data from a documented JSON endpoint.
                # An authority may opt into that endpoint explicitly; the
                # default remains a single GET of the registered page.  No
                # cookies, auth headers or browser-only requests are used.
                api_url = str(authority.get("apiUrl") or authority.get("endpoint") or url)
                method = str(authority.get("method") or "GET").upper()
                base_params = authority.get("params") if isinstance(authority.get("params"), dict) else {}
                request_headers = {
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": DISCOVERY_USER_AGENT,
                    "Referer": url,
                }
                if method not in {"GET", "POST"}:
                    result.update({"reachable": False, "blocked": False, "errorType": "unsupported_method"})
                    checks.append(result)
                    continue
                max_pages = max(1, min(int(authority.get("maxPages", 1) or 1), 50))
                pagination_param_names = {
                    "pageHelp.pageNo", "pageHelp.beginPage", "pageNo", "page", "pageIndex",
                }
                has_declared_pagination = bool(pagination_param_names.intersection(base_params))
                total_candidates = 0
                pages_fetched = 0
                total_expected: int | None = None
                page_size: int | None = None
                pagination_complete = False
                for page in range(1, max_pages + 1):
                    params = {str(key): str(value) for key, value in base_params.items()}
                    # Keep the authority's naming convention; do not invent
                    # pagination parameters for a page that did not declare
                    # them.  This prevents accidental requests to unrelated
                    # endpoints when a directory changes shape.
                    for page_key in ("pageHelp.pageNo", "pageHelp.beginPage", "pageNo", "page", "pageIndex"):
                        if page_key in params:
                            params[page_key] = str(page)
                    if method == "POST":
                        response = client.post(api_url, headers=request_headers, data=params)
                    else:
                        response = client.get(api_url, headers=request_headers, params=params)
                    if page == 1:
                        result.update({
                            "statusCode": response.status_code,
                            "reachable": 200 <= response.status_code < 400,
                            "blocked": response.status_code in NON_RETRYABLE_STATUS,
                            "contentType": response.headers.get("content-type", "").split(";", 1)[0],
                            "bytes": len(response.content),
                            "requestUrl": api_url,
                        })
                    if response.status_code in NON_RETRYABLE_STATUS:
                        result["errorType"] = "access_blocked"
                        break
                    if response.status_code >= 400:
                        result["errorType"] = "unexpected_status"
                        break
                    payload = _authority_payload(response)
                    parsed = _authority_rows_from_response(response, authority_id=authority_id, source_url=url)
                    rows.extend(parsed)
                    total_candidates += len(parsed)
                    pages_fetched += 1
                    total_expected, page_size = _page_meta(payload)
                    # A source that does not declare a page parameter is a
                    # single-page authority, even when it has unrelated query
                    # parameters. Repeating the same request would create
                    # needless traffic and could make a static directory look
                    # paginated when it is not.
                    if not has_declared_pagination:
                        pagination_complete = True
                        break
                    if not parsed or (total_expected is not None and page * (page_size or len(parsed)) >= total_expected) or (page_size is not None and len(parsed) < page_size):
                        pagination_complete = True
                        break
                if result.get("reachable"):
                    result["candidateCount"] = total_candidates
                    result["pagesFetched"] = pages_fetched
                    result["complete"] = pagination_complete
                    if total_expected is not None:
                        result["expectedCount"] = total_expected
                    if authority_id == "sasac-central-soes":
                        expected = int(result.get("expectedCount", 99) or 99)
                        if total_candidates != expected:
                            result["complete"] = False
                            result["errorType"] = "unexpected_candidate_count"
            except httpx.TimeoutException:
                result.update({"reachable": False, "blocked": False, "errorType": "timeout"})
            except httpx.RequestError:
                result.update({"reachable": False, "blocked": False, "errorType": "request_error"})
            checks.append(result)
    return rows, checks


def _visible_page_text(content: bytes) -> str:
    """Extract a bounded visible-text sample for signal detection only."""

    html = content[:MAX_CAREER_BYTES].decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(["script", "style", "noscript", "template", "svg"]):
        node.decompose()
    parts: list[str] = []
    if soup.title:
        parts.extend(soup.title.stripped_strings)
    for meta in soup.find_all("meta"):
        if str(meta.get("name", "")).lower() in {"description", "keywords"}:
            content_value = str(meta.get("content", "")).strip()
            if content_value:
                parts.append(content_value)
    parts.extend(soup.get_text(" ", strip=True).split())
    # Signal detection needs no full response retention.  The returned string
    # is immediately discarded by the probe and never written to a report.
    return " ".join(parts)[:200_000]


def probe_career_entries(
    companies: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    cohort: str = CURRENT_COHORT,
    timeout: float = 15.0,
    interval_seconds: float = 0.35,
) -> list[dict[str, Any]]:
    """Probe registered first-party career URLs for current-campus signals.

    Requests are unauthenticated, serial and low-frequency.  The output is
    lightweight metadata: status, signal codes and URL evidence only.  It does
    not include response HTML, cookies, redirect chains or page text.
    """

    checked_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    results: list[dict[str, Any]] = []
    headers = {"User-Agent": DISCOVERY_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for company in companies:
            if not isinstance(company, dict) or not company.get("id"):
                continue
            company_id = str(company["id"])
            career_url = str(company.get("careerUrl") or "").strip()
            if not career_url:
                evidence_urls = company.get("discoveryEvidenceUrls")
                if isinstance(evidence_urls, list):
                    career_url = next((str(value).strip() for value in evidence_urls if str(value).strip().startswith("https://")), "")
            result: dict[str, Any] = {
                "companyId": company_id,
                "companyName": str(company.get("name") or company_id),
                "careerUrl": career_url or None,
                "cohort": cohort,
                "checkedAt": checked_at,
                "directoryStatus": "STALE",
                "entryType": entry_type_for_url(career_url),
                "signals": [],
                "reachable": False,
                "blocked": False,
                "public": False,
            }
            if not career_url:
                result.update({"directoryStatus": "INACTIVE", "errorType": "missing_career_url"})
                results.append(result)
                continue
            parsed = urlparse(career_url)
            if parsed.scheme != "https" or not parsed.hostname:
                result.update({"directoryStatus": "BLOCKED", "blocked": True, "errorType": "non_https_url"})
                results.append(result)
                continue
            try:
                response = client.get(career_url)
                result.update({
                    "statusCode": response.status_code,
                    "reachable": 200 <= response.status_code < 400,
                    "blocked": response.status_code in NON_RETRYABLE_STATUS,
                    "contentType": response.headers.get("content-type", "").split(";", 1)[0],
                    "bytes": len(response.content),
                })
                if response.status_code in NON_RETRYABLE_STATUS:
                    result.update({"directoryStatus": "BLOCKED", "errorType": "access_blocked"})
                elif detect_security_challenge(response.content):
                    # A 200 challenge page is not a public career entry.  Do
                    # not persist or expose its HTML; keep only the reason so
                    # the operator can review it without a bypass attempt.
                    result.update({"directoryStatus": "BLOCKED", "blocked": True, "reachable": False, "errorType": "access_blocked"})
                elif response.status_code == 404:
                    result.update({"directoryStatus": "INACTIVE", "errorType": "not_found"})
                elif response.status_code >= 500:
                    result.update({"directoryStatus": "STALE", "errorType": "transient_server_error"})
                elif response.status_code >= 400:
                    result.update({"directoryStatus": "STALE", "errorType": "unexpected_status"})
                else:
                    signals = detect_campus_signals(_visible_page_text(response.content), cohort=cohort)
                    result["signals"] = signals
                    if signals:
                        result.update({"directoryStatus": "ACTIVE_CONFIRMED", "public": True, "evidenceText": "官网页面检测到当前届校园招聘信号；具体岗位以企业官网为准。"})
                    else:
                        result.update({"directoryStatus": "INACTIVE", "errorType": "current_cohort_signal_not_found"})
            except httpx.TimeoutException:
                result.update({"directoryStatus": "STALE", "errorType": "timeout"})
            except httpx.RequestError:
                result.update({"directoryStatus": "STALE", "errorType": "request_error"})
            results.append(result)
            if interval_seconds > 0:
                time.sleep(interval_seconds)
    return results


def merge_entry_observations(
    previous: dict[str, dict[str, Any]] | None,
    observations: Iterable[dict[str, Any]],
    *,
    stale_after_failures: int = 3,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Merge daily probes while preserving the last confirmed entry metadata."""

    # Sanitize both sides of the merge.  Callers other than
    # ``build_entry_discovery_report`` (for example a scheduled worker or a
    # fixture harness) may pass an older/raw state mapping directly.
    merged = sanitize_entry_observation_map(previous or {})
    counts = {"activeConfirmed": 0, "activeLead": 0, "stale": 0, "blocked": 0, "inactive": 0}
    for raw_observation in observations:
        observation = sanitize_entry_observation(raw_observation)
        if observation is None:
            continue
        company_id = str(observation.get("companyId") or "")
        if not company_id:
            continue
        old = merged.get(company_id, {})
        status = str(observation.get("directoryStatus") or "STALE")
        if status == "ACTIVE_CONFIRMED":
            entry = {
                **old,
                "companyId": company_id,
                "cohort": observation.get("cohort", CURRENT_COHORT),
                "directoryStatus": "ACTIVE_CONFIRMED",
                "entryType": observation.get("entryType", "OFFICIAL_CAREER_SITE"),
                "careerUrl": observation.get("careerUrl") or old.get("careerUrl"),
                "evidenceUrl": observation.get("careerUrl") or old.get("evidenceUrl"),
                "evidenceText": observation.get("evidenceText") or "官网页面检测到当前届校园招聘信号；具体岗位以企业官网为准。",
                "detectedSignals": list(observation.get("signals") or []),
                "lastCheckedAt": observation.get("checkedAt") or datetime.now(UTC).isoformat(),
                "firstConfirmedAt": old.get("firstConfirmedAt") or observation.get("checkedAt"),
                "consecutiveFailures": 0,
                "public": True,
            }
            merged[company_id] = entry
            continue
        failures = int(old.get("consecutiveFailures", 0) or 0) + 1
        if status in {"BLOCKED", "STALE"} and old:
            # Keep a stale record for audit, but never claim the unavailable
            # entry is currently active in the public directory.
            next_status = "STALE" if failures < stale_after_failures else "INACTIVE"
            merged[company_id] = {
                **old,
                "directoryStatus": next_status,
                "lastCheckedAt": observation.get("checkedAt") or old.get("lastCheckedAt"),
                "consecutiveFailures": failures,
                "lastErrorType": observation.get("errorType"),
                "public": False,
            }
        else:
            merged[company_id] = {
                **old,
                "companyId": company_id,
                "cohort": observation.get("cohort", CURRENT_COHORT),
                "directoryStatus": status,
                "careerUrl": observation.get("careerUrl") or old.get("careerUrl"),
                "lastCheckedAt": observation.get("checkedAt") or datetime.now(UTC).isoformat(),
                "consecutiveFailures": failures,
                "lastErrorType": observation.get("errorType"),
                "public": False,
            }
    for entry in merged.values():
        status = str(entry.get("directoryStatus") or "STALE")
        key = {"ACTIVE_CONFIRMED": "activeConfirmed", "ACTIVE_LEAD": "activeLead", "STALE": "stale", "BLOCKED": "blocked", "INACTIVE": "inactive"}.get(status)
        if key:
            counts[key] += 1
    return merged, counts


def build_entry_discovery_report(
    companies_path: Path,
    *,
    output: Path | None = None,
    state_path: Path | None = None,
    input_path: Path | None = None,
    cohort: str = CURRENT_COHORT,
    timeout: float = 15.0,
    authority_index_path: Path | None = None,
    hiring_radar_path: Path | None = None,
) -> dict[str, Any]:
    """Run or fixture-test the daily company-entry signal discovery task."""

    # Probe the same merged discovery pool used by the weekly backlog.  The
    # local import avoids a module cycle (authority_index itself reuses the
    # name-normalisation helpers from this module).  Temporary fixture
    # directories normally do not contain either seed, so old callers retain
    # the registry-only behaviour automatically.
    authority_path = authority_index_path or companies_path.with_name("internet-authority-top100.json")
    radar_path = hiring_radar_path or companies_path.with_name("hiring-radar-seed.json")
    if authority_path.exists() or radar_path.exists():
        from .authority_index import load_candidate_company_configs

        candidate_configs = load_candidate_company_configs(
            companies_path,
            authority_path if authority_path.exists() else None,
            radar_path if radar_path.exists() else None,
        )
        companies = [config.model_dump(mode="json", by_alias=True) for config in candidate_configs]
    else:
        companies = load_companies(companies_path)
    if input_path:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        raw_observations = payload.get("observations", payload) if isinstance(payload, dict) else payload
        observations = [clean for item in raw_observations if (clean := sanitize_entry_observation(item))] if isinstance(raw_observations, list) else []
    else:
        observations = probe_career_entries(companies, cohort=cohort, timeout=timeout)
    # Apply the same allow-list to live probe output as to fixtures.  This is
    # cheap, keeps the report contract stable, and protects the publication
    # boundary if a future probe implementation returns extra diagnostics.
    observations = [clean for item in observations if (clean := sanitize_entry_observation(item))]
    previous: dict[str, dict[str, Any]] = {}
    if state_path and state_path.exists():
        try:
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            previous = sanitize_entry_observation_map(state_payload.get("entries", state_payload) if isinstance(state_payload, dict) else {})
        except (OSError, ValueError, TypeError):
            previous = {}
    entries, counts = merge_entry_observations(previous, observations)
    checked_at = datetime.now(UTC).isoformat()
    report = {
        "schemaVersion": 1,
        "generatedAt": checked_at,
        "cadence": "daily",
        "cohort": cohort,
        "discoveryOnly": True,
        "summary": {
            "companyCount": len(companies),
            "observationCount": len(observations),
            **counts,
            "publicActiveCount": sum(1 for entry in entries.values() if entry.get("public")),
        },
        # ``observations`` is intentionally the same sanitized, lightweight
        # shape that is fed into the state merge.  Never persist the fixture's
        # raw object, which could contain HTML, response bodies or cookies.
        "observations": observations,
        "entries": entries,
        "promotionRule": "入口层只在官网或官方 ATS 检测到当前届校招信号时公开；岗位采集仍需独立完成来源审核、适配器测试和文社商受众门禁。",
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if state_path:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"schemaVersion": 1, "generatedAt": checked_at, "entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_discovery_report(
    companies_path: Path,
    authorities_path: Path,
    *,
    focus_path: Path | None = None,
    input_path: Path | None = None,
    timeout: float = 15.0,
    authority_index_path: Path | None = None,
    hiring_radar_path: Path | None = None,
) -> dict[str, Any]:
    """Build a discovery-only report from local fixtures or authority URLs."""

    if input_path:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        rows: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        entries = payload.items() if isinstance(payload, dict) else [("fixture", payload)]
        for authority_id, value in entries:
            url = str(value.get("sourceUrl") or "https://example.invalid/discovery") if isinstance(value, dict) else "https://example.invalid/discovery"
            rows.extend(parse_json_authority(value, authority_id=str(authority_id), source_url=url))
        checks = [{"id": "fixture", "reachable": True, "candidateCount": len(rows)}]
    else:
        rows, checks = fetch_authority_candidates(authorities_path, timeout=timeout)

    authority_path = authority_index_path or companies_path.with_name("internet-authority-top100.json")
    radar_path = hiring_radar_path or companies_path.with_name("hiring-radar-seed.json")
    if authority_path.exists() or radar_path.exists():
        from .authority_index import load_candidate_company_configs

        candidate_configs = load_candidate_company_configs(
            companies_path,
            authority_path if authority_path.exists() else None,
            radar_path if radar_path.exists() else None,
        )
        companies = [config.model_dump(mode="json", by_alias=True) for config in candidate_configs]
    else:
        companies = load_companies(companies_path)
    focus_payload = load_focus_registry(focus_path)
    merged = merge_discovered_candidates(companies, rows, focus_companies=focus_company_map(focus_payload))
    matched = sum(1 for row in merged if row.get("matchedCompanyId"))
    focus_matches = sum(1 for row in merged if row.get("focusPriority") is not None)
    report = {
        "schemaVersion": DISCOVERY_SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "cadence": "daily_authority_probe_with_weekly_review",
        "discoveryOnly": True,
        "focus": {
            "id": focus_payload.get("focusId"),
            "target": focus_payload.get("target"),
            "focusCompanyCount": len(focus_payload.get("companies", [])),
            "matchedFocusCandidates": focus_matches,
        },
        "summary": {
            "authorityCount": len(checks),
            "reachableAuthorityCount": sum(1 for item in checks if item.get("reachable")),
            "rawCandidateRowCount": len(rows),
            "uniqueCandidateCount": len(merged),
            "matchedRegistryCount": matched,
            "newCandidateCount": len(merged) - matched,
            "requiresOfficialCareerReviewCount": sum(1 for row in merged if row.get("requiresOfficialCareerReview")),
        },
        "authorities": checks,
        "candidates": merged,
        "promotionRule": "仅人工补齐企业官网或官方 ATS、robots/条款、校招识别、三条岗位抽查和适配器测试后，才允许更新 registry/sources.json 为 VERIFIED；发现结果不会自动发布岗位。",
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a discovery-only company candidate report.")
    parser.add_argument("--companies", type=Path, default=Path("registry/companies.json"))
    parser.add_argument("--authorities", type=Path, default=Path("registry/candidate-discovery-sources.json"))
    parser.add_argument("--focus", type=Path, default=Path("registry/internet-focus.json"))
    parser.add_argument("--input", type=Path, help="Local JSON fixture; skips network requests.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/company-discovery.json"))
    parser.add_argument("--probe-career-entries", action="store_true", help="probe registered career URLs for current-cohort campus signals")
    parser.add_argument("--entry-state", type=Path, default=Path("collector/company-directory-state.json"))
    parser.add_argument("--authority-index", type=Path, default=Path("registry/internet-authority-top100.json"))
    parser.add_argument("--hiring-radar", type=Path, default=Path("registry/hiring-radar-seed.json"))
    parser.add_argument("--cohort", default=CURRENT_COHORT)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)
    if args.probe_career_entries:
        report = build_entry_discovery_report(args.companies, output=args.output, state_path=args.entry_state, input_path=args.input, cohort=args.cohort, timeout=args.timeout, authority_index_path=args.authority_index, hiring_radar_path=args.hiring_radar)
    else:
        report = build_discovery_report(args.companies, args.authorities, focus_path=args.focus, input_path=args.input, timeout=args.timeout, authority_index_path=args.authority_index, hiring_radar_path=args.hiring_radar)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.probe_career_entries:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
