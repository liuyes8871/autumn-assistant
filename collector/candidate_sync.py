from __future__ import annotations

"""Build a truthful weekly company-candidate backlog.

This task deliberately does not promote a company or source to VERIFIED. The
authoritative exchange/SASAC pages are discovery inputs only; every candidate
still needs a first-party career URL, robots/terms review and at least three
job samples before the five-hour collector can request it.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def build_candidate_backlog(
    companies_path: Path,
    sources_path: Path,
    authorities_path: Path,
    output: Path | None = None,
    *,
    focus_path: Path | None = None,
    authority_index_path: Path | None = None,
    hiring_radar_path: Path | None = None,
) -> dict[str, Any]:
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
    sources_by_company: dict[str, list[Any]] = {}
    for source in sources:
        sources_by_company.setdefault(source.company_id, []).append(source)

    rows: list[dict[str, Any]] = []
    for rank, company in enumerate(companies, start=1):
        company_sources = sources_by_company.get(company.id, [])
        runnable = [source for source in company_sources if source_can_run(source)[0]]
        company_payload = company.model_dump(mode="json", by_alias=True)
        large_evidence = bool((company.employee_count is not None and company.employee_count >= 500) or company.scale in {"500–999", "1000–9999", "10000+"})
        rows.append({
            "rank": rank,
            "companyId": company.id,
            "companyName": company.name,
            "industry": company.industry,
            "priorityBand": company_priority(company)[0],
            "focusPriority": focused_companies.get(company.id, {}).get("priority"),
            "focusSegment": focused_companies.get(company.id, {}).get("segment"),
            "isFocusCompany": company.id in focused_companies,
            "listingStatus": company.listing_status,
            "employeeCount": company.employee_count,
            "largeCompanyEvidence": large_evidence,
            "sourceStatus": company.source_status,
            "careerUrl": company_payload.get("careerUrl"),
            "discoverySource": company_payload.get("discoverySource"),
            "hiringRadar": company_payload.get("hiringRadar"),
            "sourceCount": len(company_sources),
            "runnableSourceCount": len(runnable),
            "nextAction": "COLLECT" if runnable else "REVIEW_SOURCE" if company_sources else "DISCOVER_OFFICIAL_SOURCE",
            "doNotPublishAsConnected": not bool(runnable),
        })

    authorities = json.loads(authorities_path.read_text(encoding="utf-8"))
    authority_summary: dict[str, Any] | None = None
    if authority_path.exists():
        authority_payload = load_authority_index(authority_path)
        _authority_rows, authority_summary = merge_authority_candidates(
            json.loads(companies_path.read_text(encoding="utf-8")),
            authority_candidate_rows(authority_payload),
        )
        authority_summary = {
            **authority_summary,
            "id": authority_payload.get("authorityId"),
            "year": authority_payload.get("reportYear"),
            "sourceUrl": authority_payload.get("sourceUrl"),
            "pdfUrl": authority_payload.get("pdfUrl"),
        }
    radar_summary: dict[str, Any] | None = None
    if radar_path.exists():
        # Keep the pinned seed's own audit report in the backlog so operators
        # can distinguish radar rows from the authority index without treating
        # either as a connected source.
        from .hiring_radar import load_hiring_radar_seed

        radar_payload = load_hiring_radar_seed(radar_path)
        radar_summary = {
            "sourceRepository": radar_payload.get("sourceRepository"),
            "sourcePath": radar_payload.get("sourcePath"),
            "sourceCommit": radar_payload.get("sourceCommit"),
            "license": radar_payload.get("license"),
            "recordCount": len(radar_payload.get("records", [])),
            "companyCount": len({str(item.get("companyName")) for item in radar_payload.get("records", []) if isinstance(item, dict) and item.get("companyName")}),
            "entryUrlCount": sum(1 for item in radar_payload.get("records", []) if isinstance(item, dict) and item.get("entryUrl")),
            "discoveryOnly": True,
        }
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "cadence": "weekly",
        "coverageStatus": "IN_PROGRESS",
        "coverageDefinition": "覆盖所有能够从企业官网或官方 ATS 公开发现、无需登录且通过访问边界审核的活跃校招来源；不存在永久全网抓完日期。",
        "selectionPolicy": "china_internet_focus_then_listed_and_employee_count_gte_500",
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
        "discoveryOnly": True,
        "authoritativeDiscoverySources": authorities,
        "authorityIndex": authority_summary,
        "hiringRadar": radar_summary,
        "companyCount": len(rows),
        "candidateWithoutOfficialSource": sum(1 for row in rows if row["nextAction"] == "DISCOVER_OFFICIAL_SOURCE"),
        "companiesWithRunnableSources": sum(1 for row in rows if row["runnableSourceCount"]),
        "confirmed500PlusCompanies": sum(1 for row in rows if row["largeCompanyEvidence"]),
        "verifiedCompanySources": sum(1 for row in rows if row["sourceStatus"] in {"VERIFIED", "AUTO_VERIFIED"}),
        "manualVerifiedCompanySources": sum(1 for row in rows if row["sourceStatus"] == "VERIFIED"),
        "autoVerifiedCompanySources": sum(1 for row in rows if row["sourceStatus"] == "AUTO_VERIFIED"),
        "saturation": {
            "status": "IN_PROGRESS",
            "consecutiveNoNewCycles": 0,
            "definition": "连续两个周度发现周期没有新增合格来源，并且所有可访问来源均已接入或有明确阻断记录",
        },
        "rows": rows,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the weekly, discovery-only company coverage backlog.")
    parser.add_argument("--companies", type=Path, default=Path("registry/companies.json"))
    parser.add_argument("--sources", type=Path, default=Path("registry/sources.json"))
    parser.add_argument("--authorities", type=Path, default=Path("registry/candidate-discovery-sources.json"))
    parser.add_argument("--focus", type=Path, default=Path("registry/internet-focus.json"))
    parser.add_argument("--authority-index", type=Path, default=Path("registry/internet-authority-top100.json"))
    parser.add_argument("--hiring-radar", type=Path, default=Path("registry/hiring-radar-seed.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/company-candidate-backlog.json"))
    args = parser.parse_args(argv)
    report = build_candidate_backlog(args.companies, args.sources, args.authorities, args.output, focus_path=args.focus, authority_index_path=args.authority_index, hiring_radar_path=args.hiring_radar)
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
