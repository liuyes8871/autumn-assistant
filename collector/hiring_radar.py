from __future__ import annotations

"""Import Hiring Radar's company seed as discovery-only metadata.

Only the upstream seed table is reused.  The collector does not import its
scrapers, execute browser/session code or copy any Moka decryption logic.  A
seed record is a lead until the first-party URL and campus scope are reviewed
inside this project.
"""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .company_discovery import normalize_company_name


HIRING_RADAR_COMMIT = "3784ed9286e7e7c6f214e1d03e1196595b56b6a4"


def load_hiring_radar_seed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Hiring Radar seed must be an object")
    if payload.get("schemaVersion") != 1:
        raise ValueError("unsupported Hiring Radar seed schema")
    if payload.get("sourceCommit") != HIRING_RADAR_COMMIT:
        raise ValueError("Hiring Radar seed must pin the audited commit")
    if payload.get("license") != "MIT":
        raise ValueError("Hiring Radar seed must retain the MIT license")
    records = payload.get("records")
    if not isinstance(records, list) or int(payload.get("recordCount", -1)) != len(records):
        raise ValueError("Hiring Radar seed recordCount does not match records")
    keys: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Hiring Radar seed rows must be objects")
        key = str(row.get("key") or "").strip()
        ats = str(row.get("ats") or "").strip().lower()
        name = str(row.get("companyName") or "").strip()
        if not key or not name or ats not in {"feishu", "moka", "beisen"}:
            raise ValueError("Hiring Radar seed row is missing key, companyName or supported ATS")
        if key in keys:
            raise ValueError(f"duplicate Hiring Radar seed key: {key}")
        keys.add(key)
        if row.get("entryType") != "ENTRY_LEAD" or row.get("entryUrlVerified") is not False:
            raise ValueError("Hiring Radar rows must remain unverified entry leads")
    return payload


def build_hiring_radar_report(
    companies_path: Path,
    seed_path: Path,
    output: Path | None = None,
) -> dict[str, Any]:
    seed = load_hiring_radar_seed(seed_path)
    values = json.loads(companies_path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("company registry must be an array")
    by_key: dict[str, dict[str, Any]] = {}
    for company in values:
        if not isinstance(company, dict):
            continue
        for value in [company.get("id"), company.get("name"), *(company.get("aliases") or [])]:
            key = normalize_company_name(value)
            if key:
                by_key.setdefault(key, company)
    rows: list[dict[str, Any]] = []
    matched_keys: set[str] = set()
    for source_row in seed["records"]:
        keys = [normalize_company_name(source_row.get("companyName")), normalize_company_name(source_row.get("key"))]
        company = next((by_key.get(key) for key in keys if key and by_key.get(key)), None)
        if company:
            matched_keys.add(str(company.get("id")))
        rows.append({
            **source_row,
            "companyId": company.get("id") if company else None,
            "matchedCompanyName": company.get("name") if company else None,
            "sourceStatus": "TARGET",
            "runnable": False,
            "requiresOfficialCareerReview": True,
            "doNotPublishAsConnected": True,
        })
    unique_company_ids = {row["companyId"] for row in rows if row.get("companyId")}
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "importType": "hiring_radar_seed",
        "source": {
            "repository": seed.get("sourceRepository"),
            "path": seed.get("sourcePath"),
            "commit": seed.get("sourceCommit"),
            "commitDate": seed.get("sourceCommitDate"),
            "license": seed.get("license"),
            "licenseFile": seed.get("licenseFile"),
        },
        "summary": {
            "recordCount": len(rows),
            "uniqueCompanyCount": len(unique_company_ids),
            "matchedRegistryCompanyCount": len(matched_keys),
            "unmatchedRecordCount": sum(1 for row in rows if not row.get("companyId")),
            "byAts": {ats: sum(1 for row in rows if row.get("ats") == ats) for ats in ("feishu", "moka", "beisen")},
        },
        "discoveryOnly": True,
        "reuseBoundary": seed.get("reuseBoundary"),
        "promotionRule": "固定种子只用于发现公司和 ATS 入口线索；完成企业官网反向确认、robots/条款、校招识别和三条岗位抽查后，才可登记为可运行来源。",
        "records": rows,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the pinned Hiring Radar company seed without promoting sources.")
    parser.add_argument("--companies", type=Path, default=Path("registry/companies.json"))
    parser.add_argument("--seed", type=Path, default=Path("registry/hiring-radar-seed.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/hiring-radar-import.json"))
    args = parser.parse_args(argv)
    report = build_hiring_radar_report(args.companies, args.seed, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
