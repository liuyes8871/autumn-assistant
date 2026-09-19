from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .authority_index import authority_candidate_rows, load_authority_index, load_candidate_company_configs, merge_authority_candidates
from .registry import (
    company_priority,
    focus_company_map,
    focused_company_priority,
    load_company_configs,
    load_focus_registry,
    load_sources,
    source_can_run,
)
from .schema import CompanyConfig, model_json
from .ats_discovery import (
    detect_ats_from_html,
    detect_security_challenge,
    discover_public_page,
    discover_target_sources as _discover_target_sources,
    extract_feed_links,
    extract_jobposting_jsonld,
    extract_sitemap_links,
)
from .sasac import parse_sasac_central_enterprises

# Public compatibility export for callers that keep all discovery helpers in
# this module.  ``build_coverage`` resolves it through ``globals`` because its
# boolean option intentionally has the same human-facing name.
def discover_target_sources(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return _discover_target_sources(*args, **kwargs)


def check_authority_sources(authorities_path: Path, *, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Check discovery pages without promoting or parsing them as companies.

    The pages in ``candidate-discovery-sources.json`` are discovery evidence,
    not job sources. We only record reachability and coarse access outcomes;
    bodies, cookies and response payloads are never written to public reports.
    A 401/403/429 is treated as blocked and is never retried or bypassed.
    """

    authorities = json.loads(authorities_path.read_text(encoding="utf-8"))
    checked_at = datetime.now(UTC).isoformat()
    results: list[dict[str, Any]] = []
    headers = {"User-Agent": "autumn-assistant-source-discovery/0.1 (+public-source-audit)"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for authority in authorities if isinstance(authorities, list) else []:
            authority_id = str(authority.get("id", "unknown"))
            url = str(authority.get("url", ""))
            result: dict[str, Any] = {"id": authority_id, "url": url, "checkedAt": checked_at}
            try:
                response = client.get(url)
                result.update({
                    "statusCode": response.status_code,
                    "reachable": 200 <= response.status_code < 400,
                    "blocked": response.status_code in {401, 403, 405, 429},
                    "contentType": response.headers.get("content-type", "").split(";", 1)[0],
                    "bytes": len(response.content),
                })
                if authority_id == "sasac-central-soes" and 200 <= response.status_code < 400:
                    parsed_rows = parse_sasac_central_enterprises(response.content, source_url=url)
                    expected = int(authority.get("expectedCount", 99) or 99)
                    result.update({
                        "candidateCount": len(parsed_rows),
                        "expectedCount": expected,
                        "complete": len(parsed_rows) == expected,
                    })
                    if len(parsed_rows) != expected:
                        result["errorType"] = "unexpected_candidate_count"
                if response.status_code in {401, 403, 405, 429}:
                    result["errorType"] = "access_blocked"
                elif detect_security_challenge(response.content):
                    result.update({"reachable": False, "blocked": True, "errorType": "access_blocked"})
                elif response.status_code >= 500:
                    result["errorType"] = "transient_server_error"
            except httpx.TimeoutException:
                result.update({"reachable": False, "blocked": False, "errorType": "timeout"})
            except httpx.RequestError:
                result.update({"reachable": False, "blocked": False, "errorType": "request_error"})
            results.append(result)
    return results


def check_candidate_sources(
    sources_path: Path,
    *,
    timeout: float = 15.0,
    interval_seconds: float = 0.35,
    focus_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Check target source landing pages without promoting or parsing them.

    This is deliberately a reachability probe, not a collector. It requests
    only the registered public landing URL, stores status metadata (never the
    response body), and treats authentication, rate limiting, CAPTCHA and
    security responses as blocked without retrying or bypassing them.
    """

    sources = load_sources(sources_path)
    focused_companies = focus_company_map(load_focus_registry(focus_path))
    sources.sort(key=lambda source: (
        0 if source.company_id in focused_companies else 1,
        int(focused_companies.get(source.company_id, {}).get("priority", 99)),
        source.source_id,
    ))
    checked_at = datetime.now(UTC).isoformat()
    results: list[dict[str, Any]] = []
    headers = {"User-Agent": "autumn-assistant-source-discovery/0.1 (+public-source-audit)"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for source in sources:
            if source.status != "TARGET":
                continue
            result: dict[str, Any] = {
                "sourceId": source.source_id,
                "companyId": source.company_id,
                "url": str(source.source_url),
                "checkedAt": checked_at,
                "sourceStatus": source.status,
            }
            try:
                response = client.get(str(source.source_url))
                result.update({
                    "statusCode": response.status_code,
                    "reachable": 200 <= response.status_code < 400,
                    "blocked": response.status_code in {401, 403, 405, 429},
                    "contentType": response.headers.get("content-type", "").split(";", 1)[0],
                    "bytes": len(response.content),
                })
                if response.status_code in {401, 403, 405, 429}:
                    result["errorType"] = "access_blocked"
                elif detect_security_challenge(response.content):
                    result.update({"reachable": False, "blocked": True, "errorType": "access_blocked"})
                elif response.status_code == 404:
                    result["errorType"] = "not_found"
                elif response.status_code >= 500:
                    result["errorType"] = "transient_server_error"
                elif response.status_code >= 400:
                    result["errorType"] = "unexpected_status"
            except httpx.TimeoutException:
                result.update({"reachable": False, "blocked": False, "errorType": "timeout"})
            except httpx.RequestError:
                result.update({"reachable": False, "blocked": False, "errorType": "request_error"})
            results.append(result)
            if interval_seconds > 0:
                time.sleep(interval_seconds)
    return results


def build_coverage(
    companies_path: Path,
    sources_path: Path,
    output: Path | None = None,
    *,
    authorities_path: Path = Path("registry/candidate-discovery-sources.json"),
    check_authorities: bool = False,
    check_target_sources: bool = False,
    authority_timeout: float = 15.0,
    focus_path: Path | None = None,
    authority_index_path: Path | None = None,
    hiring_radar_path: Path | None = None,
    discover_target_sources: bool = False,
    discovery_interval_seconds: float = 0.35,
) -> dict[str, Any]:
    """Build an auditable connection backlog; never auto-promote a source."""

    focus_payload = load_focus_registry(focus_path)
    focused_companies = focus_company_map(focus_payload)
    authority_path = authority_index_path or companies_path.with_name("internet-authority-top100.json")
    radar_path = hiring_radar_path or companies_path.with_name("hiring-radar-seed.json")
    companies = sorted(
        load_candidate_company_configs(
            companies_path,
            authority_path if authority_path.exists() else None,
            radar_path if radar_path.exists() else None,
        ),
        key=lambda company: focused_company_priority(company, focused_companies),
    )
    sources = load_sources(sources_path)
    by_company: dict[str, list[Any]] = {}
    for source in sources:
        by_company.setdefault(source.company_id, []).append(source)

    rows: list[dict[str, Any]] = []
    for rank, company in enumerate(companies, start=1):
        company_sources = by_company.get(company.id, [])
        runnable = [source for source in company_sources if source_can_run(source)[0]]
        reasons = sorted({source_can_run(source)[1] for source in company_sources if not source_can_run(source)[0]})
        priority = company_priority(company)[0]
        focus = focused_companies.get(company.id, {})
        company_payload = company.model_dump(mode="json", by_alias=True)
        rows.append({
            "rank": rank,
            "companyId": company.id,
            "companyName": company.name,
            "priorityBand": priority,
            "focusPriority": focus.get("priority"),
            "focusSegment": focus.get("segment"),
            "isFocusCompany": company.id in focused_companies,
            "priorityReason": _priority_reason(company),
            "listingStatus": company.listing_status,
            "stockCodes": company.stock_codes,
            "employeeCount": company.employee_count,
            "careerUrl": company_payload.get("careerUrl"),
            "discoverySource": company_payload.get("discoverySource"),
            "hiringRadar": company_payload.get("hiringRadar"),
            "sourceCount": len(company_sources),
            "runnableSourceCount": len(runnable),
            "sourceStatuses": sorted({source.status for source in company_sources}),
            "notReadyReasons": reasons,
            "nextAction": "COLLECT" if runnable else "REVIEW_SOURCE" if company_sources else "DISCOVER_OFFICIAL_SOURCE",
        })

    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "coverageStatus": "IN_PROGRESS",
        "coverageScope": "registry_candidates_and_reviewed_sources",
        "selectionPolicy": "china_internet_focus_then_listed_and_employee_count_gte_500",
        "companyCount": len(companies),
        "authorityIndex": None,
        "focus": {
            "id": focus_payload.get("focusId"),
            "mode": focus_payload.get("mode", "PRIORITIZE"),
            "target": focus_payload.get("target"),
            "companyCount": len(focused_companies),
            "companiesWithSources": sum(1 for row in rows if row["isFocusCompany"] and row["sourceCount"]),
            "companiesWithRunnableSources": sum(1 for row in rows if row["isFocusCompany"] and row["runnableSourceCount"]),
            "candidatesWithoutOfficialSource": sum(1 for row in rows if row["isFocusCompany"] and row["nextAction"] == "DISCOVER_OFFICIAL_SOURCE"),
            "segmentCounts": {
                str(segment): sum(1 for row in rows if row["focusSegment"] == segment)
                for segment in sorted({row["focusSegment"] for row in rows if row["focusSegment"]})
            },
        },
        "listedLargeCompanyCount": sum(1 for company in companies if company.listing_status == "LISTED" and ((company.employee_count or 0) >= 500 or company.scale in {"500–999", "1000–9999", "10000+"})),
        "companiesWithSources": sum(1 for row in rows if row["sourceCount"]),
        "companiesWithRunnableSources": sum(1 for row in rows if row["runnableSourceCount"]),
        "verifiedCompanyCount": len({source.company_id for source in sources if source.status == "VERIFIED" and source_can_run(source)[0]}),
        "autoVerifiedSourceCount": sum(1 for source in sources if source.status == "AUTO_VERIFIED" and source_can_run(source)[0]),
        "autoVerifiedCompanyCount": len({source.company_id for source in sources if source.status == "AUTO_VERIFIED" and source_can_run(source)[0]}),
        "blockedCompanyCount": len({source.company_id for source in sources if source.status in {"BLOCKED", "QUARANTINED", "REPLACED", "STALE"}}),
        "accessibleSourceCoverageRate": round(sum(1 for source in sources if source.status in {"VERIFIED", "AUTO_VERIFIED"} and source_can_run(source)[0]) / len(sources), 4) if sources else None,
        "saturation": {
            "status": "IN_PROGRESS",
            "consecutiveNoNewCycles": 0,
            "definition": "连续两个周度发现周期无新增合格来源，且所有可访问来源均已接入或有明确阻断记录",
        },
        "rows": rows,
    }
    if authority_path.exists():
        authority_payload = load_authority_index(authority_path)
        _authority_rows, authority_merge = merge_authority_candidates(
            json.loads(companies_path.read_text(encoding="utf-8")),
            authority_candidate_rows(authority_payload),
        )
        report["authorityIndex"] = {
            **authority_merge,
            "id": authority_payload.get("authorityId"),
            "year": authority_payload.get("reportYear"),
            "sourceUrl": authority_payload.get("sourceUrl"),
            "pdfUrl": authority_payload.get("pdfUrl"),
        }
    if radar_path.exists():
        from .hiring_radar import load_hiring_radar_seed

        radar_payload = load_hiring_radar_seed(radar_path)
        report["hiringRadar"] = {
            "sourceRepository": radar_payload.get("sourceRepository"),
            "sourcePath": radar_payload.get("sourcePath"),
            "sourceCommit": radar_payload.get("sourceCommit"),
            "license": radar_payload.get("license"),
            "recordCount": len(radar_payload.get("records", [])),
            "companyCount": len({str(item.get("companyName")) for item in radar_payload.get("records", []) if isinstance(item, dict) and item.get("companyName")}),
            "entryUrlCount": sum(1 for item in radar_payload.get("records", []) if isinstance(item, dict) and item.get("entryUrl")),
            "discoveryOnly": True,
        }
    if check_authorities and authorities_path.exists():
        report["authorityChecks"] = check_authority_sources(authorities_path, timeout=authority_timeout)
    if check_target_sources and sources_path.exists():
        checks = check_candidate_sources(sources_path, timeout=authority_timeout, focus_path=focus_path)
        report["candidateSourceChecks"] = checks
        report["candidateSourceCheckSummary"] = {
            "checked": len(checks),
            "reachable": sum(1 for item in checks if item.get("reachable")),
            "blocked": sum(1 for item in checks if item.get("blocked")),
            "errors": sum(1 for item in checks if item.get("errorType")),
        }
    if discover_target_sources and sources_path.exists():
        # Convert the validated Pydantic source rows back to their public
        # camelCase shape before handing them to the discovery-only helper.
        target_rows = [source.model_dump(mode="json", by_alias=True) for source in sources if source.status == "TARGET"]
        discoveries = globals()["discover_target_sources"](
            target_rows,
            timeout=authority_timeout,
            interval_seconds=discovery_interval_seconds,
        )
        report["targetSourceDiscoveries"] = discoveries
        classification_counts = Counter(
            str(item.get("classification") or "MANUAL_IMPORT_ONLY")
            for item in discoveries
            if isinstance(item, dict)
        )
        report["targetSourceDiscoverySummary"] = {
            "checked": len(discoveries),
            "reachable": sum(1 for item in discoveries if item.get("reachable")),
            "atsDetected": sum(1 for item in discoveries if item.get("detectedAts")),
            "structuredPages": sum(1 for item in discoveries if item.get("structuredJobCount", 0) > 0),
            "blocked": sum(1 for item in discoveries if item.get("blocked")),
            "manualReview": sum(1 for item in discoveries if item.get("requiresManualReview", True)),
            # Keep the four operator actions explicit so a large TARGET pool
            # can be triaged without treating reachability as verification.
            "classificationCounts": {
                key: int(classification_counts.get(key, 0))
                for key in (
                    "CONNECTOR_CANDIDATE",
                    "NEEDS_MANUAL_REVIEW",
                    "MANUAL_IMPORT_ONLY",
                    "PUBLIC_ACCESS_UNAVAILABLE",
                )
            },
        }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _priority_reason(company: CompanyConfig) -> str:
    listed = company.listing_status == "LISTED"
    large = (company.employee_count is not None and company.employee_count >= 500) or company.scale in {"500–999", "1000–9999", "10000+"}
    if listed and large:
        return "上市且员工数不少于500"
    if large:
        return "员工数不少于500"
    if listed:
        return "已上市但员工规模尚未核验或不足500"
    return "上市与员工规模尚待核验"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a truthful company/source coverage backlog.")
    parser.add_argument("--companies", type=Path, default=Path("registry/companies.json"))
    parser.add_argument("--sources", type=Path, default=Path("registry/sources.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/source-coverage.json"))
    parser.add_argument("--authorities", type=Path, default=Path("registry/candidate-discovery-sources.json"))
    parser.add_argument("--check-authorities", action="store_true", help="perform one low-frequency reachability check; never promotes sources")
    parser.add_argument("--check-candidate-sources", action="store_true", help="check TARGET source landing pages; never promotes sources or stores response bodies")
    parser.add_argument("--discover-target-sources", action="store_true", help="inspect TARGET landing pages for ATS/feed/JSON-LD hints; never promotes sources")
    parser.add_argument("--discovery-interval", type=float, default=0.35, help="delay between discovery requests")
    parser.add_argument("--focus", type=Path, default=Path("registry/internet-focus.json"))
    parser.add_argument("--authority-index", type=Path, default=Path("registry/internet-authority-top100.json"))
    parser.add_argument("--hiring-radar", type=Path, default=Path("registry/hiring-radar-seed.json"))
    parser.add_argument("--authority-timeout", type=float, default=15.0)
    args = parser.parse_args(argv)
    report = build_coverage(args.companies, args.sources, args.output, authorities_path=args.authorities, check_authorities=args.check_authorities, check_target_sources=args.check_candidate_sources, authority_timeout=args.authority_timeout, focus_path=args.focus, authority_index_path=args.authority_index, hiring_radar_path=args.hiring_radar, discover_target_sources=args.discover_target_sources, discovery_interval_seconds=args.discovery_interval)
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
