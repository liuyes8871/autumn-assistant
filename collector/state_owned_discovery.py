from __future__ import annotations

"""Bounded, discovery-only recruitment entry probes for the state-owned pool.

This module is intentionally an orchestrator, not a crawler.  It follows only
obvious recruitment links exposed by a public company homepage, uses the
existing ATS/JSON-LD/feed analyser, and stores metadata rather than response
bodies.  Every discovered endpoint remains ``TARGET`` and ``runnable=False``
until the normal source-review gate is completed by a human.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from .ats_discovery import (
    ATS_PATTERNS,
    detect_ats_from_html,
    detect_security_challenge,
    discover_public_page,
)
from .http_cache import response_content_hash, response_headers
from .state_owned import import_equity_nature_xlsx, enrich_state_owned_candidates


DISCOVERY_SCHEMA_VERSION = 1
MIN_INTERVAL_SECONDS = 0.5
MAX_LINKS_PER_HOMEPAGE = 8
RECRUITMENT_TEXT_MARKERS = (
    "招聘", "人才", "加入我们", "校园", "校招", "应届", "career", "careers", "jobs", "job", "campus", "join us", "graduate",
)
KNOWN_ATS_HOSTS = {signature.casefold() for _ats, signatures in ATS_PATTERNS for signature in signatures if "." in signature}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def traffic_domain(host: str) -> str:
    labels = [part for part in str(host or "").casefold().split(".") if part]
    if len(labels) >= 3 and ".".join(labels[-2:]) in {"com.cn", "net.cn", "org.cn", "co.uk"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else ".".join(labels)


def _safe_url(value: Any, *, base_url: str = "") -> str | None:
    raw = _text(value)
    if not raw or raw.startswith(("javascript:", "data:", "mailto:", "tel:")):
        return None
    absolute = urljoin(base_url, raw) if base_url else raw
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return absolute


def _is_known_ats_host(host: str) -> bool:
    value = str(host or "").casefold()
    return any(value == marker or value.endswith("." + marker) for marker in KNOWN_ATS_HOSTS)


def extract_recruitment_links(html: bytes | str, *, page_url: str, max_links: int = MAX_LINKS_PER_HOMEPAGE) -> list[str]:
    """Find visible, recruitment-looking links; never executes page scripts."""

    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else str(html or "")
    soup = BeautifulSoup(raw[:4 * 1024 * 1024], "html.parser")
    base_host = (urlparse(page_url).hostname or "").casefold()
    values: list[tuple[int, str]] = []
    for node in soup.find_all("a", href=True):
        url = _safe_url(node.get("href"), base_url=page_url)
        if not url:
            continue
        parsed = urlparse(url)
        text = _text(node.get_text(" ", strip=True)).casefold()
        path = f"{parsed.path} {parsed.query}".casefold()
        if not any(marker in text or marker in path for marker in RECRUITMENT_TEXT_MARKERS):
            continue
        host = (parsed.hostname or "").casefold()
        # A homepage may link to a reviewed vendor tenant; unrelated external
        # links (social media, ads, tracking URLs) are never followed.
        same_site = host == base_host or host.endswith("." + base_host) or base_host.endswith("." + host)
        if not same_site and not _is_known_ats_host(host):
            continue
        score = 0
        if any(marker in text for marker in ("校园", "校招", "应届", "graduate", "campus")):
            score += 4
        if any(marker in path for marker in ("career", "job", "campus", "recruit", "join", "xiaozhao")):
            score += 2
        values.append((score, url))
    ordered: list[str] = []
    for _score, url in sorted(values, key=lambda item: (-item[0], item[1])):
        if url not in ordered:
            ordered.append(url)
        if len(ordered) >= max(1, min(int(max_links), MAX_LINKS_PER_HOMEPAGE)):
            break
    return ordered


def _response_meta(response: Any) -> dict[str, Any]:
    headers = response_headers(response)
    content = getattr(response, "content", b"") or b""
    status = int(getattr(response, "status_code", 0) or 0)
    # A 304 response intentionally has no representation body.  Hashing the
    # empty byte string would overwrite the previous document hash with the
    # hash of "nothing", so leave it empty and let the caller reuse the old
    # validator/hash pair.
    content_hash = None if status == 304 else response_content_hash(response)
    return {
        "statusCode": status,
        "contentType": _text(headers.get("content-type", "")).split(";", 1)[0],
        "bytes": len(content),
        # Discovery reports persist validators and a body hash only.  Keeping
        # these lightweight values enables conditional re-checks without
        # turning the candidate backlog into a response cache.
        "etag": headers.get("etag"),
        "lastModified": headers.get("last-modified"),
        "contentHash": content_hash,
        "notModified": status == 304,
    }


def _candidate_domain(candidate: Mapping[str, Any]) -> str:
    values = candidate.get("homepageCandidates") or candidate.get("homepage_candidates") or []
    first = values[0] if isinstance(values, list) and values else candidate.get("homepageObserved") or candidate.get("homepage_observed")
    return traffic_domain(urlparse(str(first or "")).hostname or "unknown")


def _entry_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    keep = (
        "landingUrl", "classification", "detectedAts", "confidence", "tenant", "candidateEndpoint",
        "candidateEndpoints", "feedLinks", "sitemapLinks", "structuredJobCount", "visibleTableRowCount",
        "fieldCompleteness", "currentCohortSignal", "currentCohortSignals", "reviewReasons", "statusCode",
        "reachable", "blocked", "contentType", "etag", "lastModified", "contentHash", "notModified", "fetchedAt",
    )
    result = {key: row.get(key) for key in keep if key in row}
    result["sourceStatus"] = "TARGET"
    result["runnable"] = False
    return result


def probe_state_owned_company(
    candidate: Mapping[str, Any],
    *,
    client: httpx.Client,
    timeout: float = 15.0,
    max_links: int = MAX_LINKS_PER_HOMEPAGE,
    previous_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Probe one homepage and its public recruitment links in memory."""

    candidate_id = str(candidate.get("candidateId") or candidate.get("candidate_id") or "")
    observed = _text(candidate.get("homepageObserved") or candidate.get("homepage_observed")) or None
    values = candidate.get("homepageCandidates") or candidate.get("homepage_candidates") or []
    homepage = str(values[0]) if isinstance(values, list) and len(values) == 1 else None
    previous = dict(previous_result or {})
    result: dict[str, Any] = {
        "candidateId": candidate_id,
        "stockCode": candidate.get("stockCode") or candidate.get("stock_code"),
        "shortName": candidate.get("shortName") or candidate.get("short_name"),
        "legalName": candidate.get("legalName") or candidate.get("legal_name"),
        "listingState": candidate.get("listingState") or candidate.get("listing_state"),
        "homepageObserved": observed,
        "homepageUrl": homepage,
        "checkedAt": datetime.now(UTC).isoformat(),
        "reachable": False,
        "blocked": False,
        "classification": "MANUAL_IMPORT_ONLY",
        "reviewReasons": [],
        "recruitmentLinks": [],
        "entryCandidates": [],
        "detectedAts": [],
        "candidateEndpoints": [],
        "currentCohortSignals": [],
        "sourceStatus": "TARGET",
        "verified": False,
        "runnable": False,
        "notModified": False,
    }
    if not homepage:
        result["reviewReasons"] = ["homepage_missing_or_multiple_addresses"]
        result["classification"] = "NEEDS_MANUAL_REVIEW"
        return result
    parsed_homepage = urlparse(homepage)
    if parsed_homepage.scheme != "https" or not parsed_homepage.hostname:
        result["reviewReasons"] = ["homepage_requires_https_probe"]
        result["classification"] = "NEEDS_MANUAL_REVIEW"
        return result
    try:
        request_headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "autumn-assistant-state-owned-discovery/0.1",
        }
        # Reuse only server-provided validators from the previous discovery
        # row.  No cookies, authorization headers or response bodies are ever
        # carried into the next request.
        if previous.get("etag"):
            request_headers["If-None-Match"] = str(previous["etag"])[:256]
        if previous.get("lastModified"):
            request_headers["If-Modified-Since"] = str(previous["lastModified"])[:256]
        response = client.get(homepage, headers=request_headers)
        result.update(_response_meta(response))
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 304:
            if previous:
                preserved = dict(previous)
                preserved.update({
                    "candidateId": candidate_id,
                    "stockCode": candidate.get("stockCode") or candidate.get("stock_code"),
                    "shortName": candidate.get("shortName") or candidate.get("short_name"),
                    "legalName": candidate.get("legalName") or candidate.get("legal_name"),
                    "homepageObserved": observed,
                    "homepageUrl": homepage,
                    "checkedAt": result["checkedAt"],
                    "statusCode": 304,
                    "reachable": True,
                    "blocked": False,
                    "notModified": True,
                    "etag": result.get("etag") or previous.get("etag"),
                    "lastModified": result.get("lastModified") or previous.get("lastModified"),
                    "contentHash": result.get("contentHash") or previous.get("contentHash"),
                    "sourceStatus": "TARGET",
                    "verified": False,
                    "runnable": False,
                })
                return preserved
            result.update({
                "classification": "PUBLIC_ACCESS_UNAVAILABLE",
                "reviewReasons": ["not_modified_without_previous_snapshot"],
            })
            return result
        if status in {401, 403, 405, 429} or detect_security_challenge(getattr(response, "content", b"")):
            result.update({"blocked": True, "classification": "PUBLIC_ACCESS_UNAVAILABLE", "reviewReasons": ["access_blocked"]})
            return result
        if status >= 400:
            result.update({"classification": "PUBLIC_ACCESS_UNAVAILABLE", "reviewReasons": [f"http_status_{status}"]})
            return result
        result["reachable"] = True
        content = getattr(response, "content", b"") or b""
        final_url = str(getattr(response, "url", None) or homepage)
        analysis = detect_ats_from_html(content, page_url=final_url)
        links = extract_recruitment_links(content, page_url=final_url, max_links=max_links)
        # A homepage can itself be a hosted ATS board or a JSON-LD job page.
        if not links and (analysis.get("detectedAts") or analysis.get("structuredJobCount") or analysis.get("visibleTableRowCount")):
            links = [final_url]
        result["recruitmentLinks"] = links
        result["currentCohortSignals"] = list(analysis.get("currentCohortSignals") or [])
        for match in analysis.get("matches", []):
            ats = str(match.get("ats") or "")
            if ats and ats not in result["detectedAts"]:
                result["detectedAts"].append(ats)
        result["candidateEndpoints"] = list(analysis.get("candidateEndpoints") or [])[:20]
        for link in links:
            entry = discover_public_page(
                f"{candidate_id}-entry",
                candidate_id,
                str(candidate.get("shortName") or candidate_id),
                link,
                client=client,
                timeout=timeout,
            )
            result["entryCandidates"].append(_entry_summary(entry))
            ats = entry.get("detectedAts")
            if ats and ats not in result["detectedAts"]:
                result["detectedAts"].append(ats)
            for endpoint in entry.get("candidateEndpoints") or []:
                if endpoint not in result["candidateEndpoints"]:
                    result["candidateEndpoints"].append(endpoint)
            for signal in entry.get("currentCohortSignals") or []:
                if signal not in result["currentCohortSignals"]:
                    result["currentCohortSignals"].append(signal)
        if any(item.get("classification") == "CONNECTOR_CANDIDATE" for item in result["entryCandidates"]):
            result["classification"] = "CONNECTOR_CANDIDATE"
        elif result["entryCandidates"]:
            result["classification"] = "NEEDS_MANUAL_REVIEW"
        else:
            result["classification"] = "MANUAL_IMPORT_ONLY"
        if not result["currentCohortSignals"]:
            result["reviewReasons"].append("current_cohort_signal_not_found")
        if not result["entryCandidates"]:
            result["reviewReasons"].append("recruitment_link_not_found")
        result["reviewReasons"] = list(dict.fromkeys(result["reviewReasons"]))
        return result
    except httpx.TimeoutException:
        result.update({"classification": "PUBLIC_ACCESS_UNAVAILABLE", "reviewReasons": ["timeout"]})
    except httpx.RequestError:
        result.update({"classification": "PUBLIC_ACCESS_UNAVAILABLE", "reviewReasons": ["request_error"]})
    return result


def _select_batch(candidates: list[Mapping[str, Any]], *, batch_number: int, batch_size: int, max_domains: int = 100) -> list[Mapping[str, Any]]:
    ordered = sorted(candidates, key=lambda row: (
        0 if str(row.get("listingState") or row.get("listing_state") or "") == "正常上市" else 1,
        0 if row.get("homepageCandidates") or row.get("homepage_candidates") else 1,
        str(row.get("stockCode") or row.get("stock_code") or ""),
    ))
    start = max(0, (max(1, int(batch_number)) - 1) * max(1, int(batch_size)))
    selected: list[Mapping[str, Any]] = []
    domains: set[str] = set()
    for row in ordered[start:]:
        domain = _candidate_domain(row)
        if domain != "unknown" and domain not in domains and len(domains) >= max_domains:
            continue
        if domain != "unknown":
            domains.add(domain)
        selected.append(row)
        if len(selected) >= max(1, min(int(batch_size), 100)):
            break
    return selected


def _load_previous(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        return {str(row.get("candidateId")): dict(row) for row in rows if isinstance(row, dict) and row.get("candidateId")}
    except (OSError, ValueError, TypeError):
        return {}


def build_state_owned_discovery_report(
    workbook_path: Path,
    *,
    companies_path: Path | None = None,
    sasac_path: Path | None = None,
    output: Path | None = None,
    batch_number: int = 1,
    batch_size: int = 100,
    max_domain_workers: int = 8,
    interval_seconds: float = MIN_INTERVAL_SECONDS,
    timeout: float = 15.0,
    previous_path: Path | None = None,
) -> dict[str, Any]:
    imported = import_equity_nature_xlsx(workbook_path)
    companies: list[dict[str, Any]] = []
    if companies_path and companies_path.exists():
        payload = json.loads(companies_path.read_text(encoding="utf-8"))
        companies = [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    groups: list[dict[str, Any]] = []
    if sasac_path and sasac_path.exists():
        payload = json.loads(sasac_path.read_text(encoding="utf-8"))
        values = payload.get("companies", payload.get("rows", payload)) if isinstance(payload, dict) else payload
        groups = [dict(item) for item in values if isinstance(item, dict)] if isinstance(values, list) else []
    candidates = [row.model_dump(mode="json", by_alias=True) for row in enrich_state_owned_candidates(imported.state_owned_rows, companies, groups)]
    selected = _select_batch(candidates, batch_number=batch_number, batch_size=batch_size)
    min_interval = max(MIN_INTERVAL_SECONDS, float(interval_seconds or 0))
    groups_by_domain: dict[str, list[Mapping[str, Any]]] = {}
    for row in selected:
        groups_by_domain.setdefault(_candidate_domain(row), []).append(row)
    previous = _load_previous(previous_path or output)

    def run_group(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            for row in items:
                rows.append(
                    probe_state_owned_company(
                        row,
                        client=client,
                        timeout=timeout,
                        previous_result=previous.get(str(row.get("candidateId") or "")),
                    )
                )
                # This delay applies between candidates on the same domain;
                # cross-domain groups are limited by the worker pool.
                if min_interval > 0:
                    import time
                    time.sleep(min_interval)
        return rows

    completed: list[dict[str, Any]] = []
    workers = max(1, min(int(max_domain_workers or 1), 8))
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(groups_by_domain)))) as executor:
        futures = [executor.submit(run_group, items) for items in groups_by_domain.values()]
        for future in as_completed(futures):
            completed.extend(future.result())
    for row in completed:
        previous[str(row["candidateId"])] = row
    results = sorted(previous.values(), key=lambda row: str(row.get("stockCode") or row.get("candidateId") or ""))
    remaining_count = max(0, len(candidates) - len(previous))
    classification_counts = {
        key: sum(row.get("classification") == key for row in results)
        for key in ("CONNECTOR_CANDIDATE", "NEEDS_MANUAL_REVIEW", "MANUAL_IMPORT_ONLY", "PUBLIC_ACCESS_UNAVAILABLE")
    }
    ats_counts: dict[str, int] = {}
    for row in results:
        for ats in row.get("detectedAts") or []:
            ats_counts[str(ats)] = ats_counts.get(str(ats), 0) + 1
    processed_ids = set(previous)
    report = {
        "schemaVersion": DISCOVERY_SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "reportType": "state_owned_recruitment_source_discovery",
        "discoveryOnly": True,
        "source": {"fileName": workbook_path.name, "readOnly": True, "notCopiedToWebAssets": True},
        "batch": {
            "number": max(1, int(batch_number)),
            "requestedSize": max(1, min(int(batch_size), 100)),
            "selectedCount": len(selected),
            "domainCount": len(groups_by_domain),
            "maxDomains": 100,
            "maxDomainWorkers": workers,
            "intervalSeconds": min_interval,
            "serialWithinDomain": True,
        },
        "summary": {
            **imported.summary,
            "candidateCount": len(candidates),
            "processedCount": len(processed_ids),
            "remainingCount": remaining_count,
            "nextBatch": max(1, int(batch_number)) + 1 if selected and remaining_count else None,
            "recruitmentEntryDiscoveredCount": sum(bool(row.get("recruitmentLinks")) for row in results),
            "connectorCandidateCount": classification_counts["CONNECTOR_CANDIDATE"],
            "needsManualReviewCount": classification_counts["NEEDS_MANUAL_REVIEW"],
            "manualImportOnlyCount": classification_counts["MANUAL_IMPORT_ONLY"],
            "blockedCount": classification_counts["PUBLIC_ACCESS_UNAVAILABLE"],
            "verifiedSourceCount": 0,
            "rawJobCount": 0,
            "eligibleJobCount": 0,
            "atsDistribution": dict(sorted(ats_counts.items())),
            "classificationCounts": classification_counts,
        },
        "promotionRule": "所有发现结果均保持TARGET；只有企业官网反向确认、robots/条款、当前届信号、至少三条岗位抽查、投递域名和字段质量核验完成后才可登记VERIFIED来源。",
        "results": results,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# Alias for callers that use the shorter verb.
discover_state_owned_candidates = build_state_owned_discovery_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover public recruitment entries for state-owned listed companies without promoting sources.")
    parser.add_argument("--excel", "--input", dest="excel", type=Path, required=True)
    parser.add_argument("--companies", type=Path, default=None)
    parser.add_argument("--sasac", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("artifacts/state-owned-source-discovery.json"))
    parser.add_argument("--previous", type=Path, default=None)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-domain-workers", type=int, default=8)
    parser.add_argument("--interval", type=float, default=MIN_INTERVAL_SECONDS)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)
    report = build_state_owned_discovery_report(
        args.excel,
        companies_path=args.companies,
        sasac_path=args.sasac,
        output=args.output,
        previous_path=args.previous,
        batch_number=args.batch,
        batch_size=args.batch_size,
        max_domain_workers=args.max_domain_workers,
        interval_seconds=args.interval,
        timeout=args.timeout,
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
