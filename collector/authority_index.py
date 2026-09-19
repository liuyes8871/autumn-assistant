from __future__ import annotations

"""Import and audit the Internet Society of China top-100 index.

The authority index is a *candidate* source only.  It is intentionally kept
separate from ``registry/companies.json`` and ``registry/sources.json``:
appearing in an industry list never proves that a company has an active campus
campaign or that its jobs may be fetched.  This module gives the weekly
discovery task a deterministic, reviewable input and a small merge report.
"""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .company_discovery import candidate_id_for, normalize_company_name
from .schema import CompanyConfig


AUTHORITY_SCHEMA_VERSION = 1
AUTHORITY_ID = "isc-internet-top100-2025"


def _text(value: Any) -> str:
    return str(value or "").strip()


def load_authority_index(path: Path) -> dict[str, Any]:
    """Load and validate a fixed, reproducible authority index.

    Validation is intentionally strict.  A partial or re-ordered report must
    fail the weekly job rather than silently replacing one of the 100 source
    rows with a different company.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("authority index must be an object")
    if payload.get("schemaVersion") != AUTHORITY_SCHEMA_VERSION:
        raise ValueError("unsupported authority index schema")
    if not _text(payload.get("authorityId")):
        raise ValueError("authorityId is required")
    companies = payload.get("companies")
    if not isinstance(companies, list) or len(companies) != 100:
        raise ValueError("authority index must contain exactly 100 companies")
    ranks: list[int] = []
    names: set[str] = set()
    for row in companies:
        if not isinstance(row, dict):
            raise ValueError("authority company rows must be objects")
        rank = row.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise ValueError("authority company rank must be an integer")
        ranks.append(rank)
        name = _text(row.get("name"))
        key = normalize_company_name(name)
        if len(key) < 2:
            raise ValueError("authority company name cannot be empty")
        if key in names:
            raise ValueError(f"duplicate authority company: {name}")
        names.add(key)
        if not _text(row.get("province")):
            raise ValueError(f"authority company province is required: {name}")
        if not _text(row.get("segment")):
            raise ValueError(f"authority company segment is required: {name}")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not _text(value) for value in aliases):
            raise ValueError(f"authority company aliases must be strings: {name}")
    if ranks != list(range(1, 101)):
        raise ValueError("authority company ranks must be the sequence 1..100")
    return payload


def authority_candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert authority rows to discovery-only candidate records."""

    authority_id = _text(payload.get("authorityId"))
    source_url = _text(payload.get("pdfUrl") or payload.get("sourceUrl"))
    rows: list[dict[str, Any]] = []
    for item in payload["companies"]:
        name = _text(item["name"])
        aliases = [_text(value) for value in item.get("aliases", []) if _text(value)]
        rows.append({
            "candidateId": f"{authority_id}-{int(item['rank']):03d}",
            "rank": int(item["rank"]),
            "name": name,
            "normalizedName": normalize_company_name(name),
            "aliases": aliases,
            "authorityIds": [authority_id],
            "sourceUrls": [source_url] if source_url else [],
            "stockCodes": [str(value) for value in item.get("stockCodes", []) if _text(value)],
            "listingMarket": item.get("listingMarket"),
            "province": _text(item.get("province")),
            "segment": _text(item.get("segment")),
            "brands": [_text(value) for value in item.get("brands", []) if _text(value)],
            "canonicalCompanyId": _text(item.get("canonicalCompanyId")) or None,
            "discoveryStatus": "DISCOVERED",
            "requiresOfficialCareerReview": True,
            "authorityEvidenceText": _text(item.get("evidenceText")) or f"中国互联网协会 2025 年前百家企业，第 {int(item['rank'])} 名",
        })
    return rows


def _company_keys(company: dict[str, Any]) -> set[str]:
    values = [company.get("id"), company.get("name"), *(company.get("aliases") or [])]
    return {normalize_company_name(value) for value in values if normalize_company_name(value)}


def merge_authority_candidates(
    existing_companies: Iterable[dict[str, Any]],
    authority_rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge rows by explicit canonical id, name or alias without guessing.

    The output is a candidate backlog row, not a registry mutation.  If an
    authority name cannot be matched, a deterministic ``candidate-isc-XXX``
    id is retained so a human can resolve it later without losing the source
    rank or evidence.
    """

    existing_values = [company for company in existing_companies if isinstance(company, dict)]
    existing_by_key: dict[str, dict[str, Any]] = {}
    for company in existing_values:
        if not isinstance(company, dict):
            continue
        for key in _company_keys(company):
            existing_by_key.setdefault(key, company)

    merged: list[dict[str, Any]] = []
    matched = 0
    conflicts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in sorted(authority_rows, key=lambda item: int(item.get("rank", 0))):
        canonical_id = _text(row.get("canonicalCompanyId"))
        matched_company = None
        if canonical_id:
            matched_company = next((company for company in existing_values if company.get("id") == canonical_id), None)
        if matched_company is None:
            keys = [normalize_company_name(row.get("name")), *(normalize_company_name(value) for value in row.get("aliases", []))]
            matches = {id(company): company for key in keys if key and (company := existing_by_key.get(key))}
            if len(matches) == 1:
                matched_company = next(iter(matches.values()))
            elif len(matches) > 1:
                conflicts.append({"rank": row.get("rank"), "name": row.get("name"), "candidateCompanyIds": [company.get("id") for company in matches.values()]})
        if matched_company:
            candidate_id = str(matched_company.get("id"))
            matched += 1
            status = "MATCHED_REGISTRY"
        else:
            candidate_id = f"candidate-isc-{int(row.get('rank', 0)):03d}"
            status = "DISCOVERED"
        if candidate_id in seen_ids:
            conflicts.append({"rank": row.get("rank"), "name": row.get("name"), "reason": "duplicate_candidate_id", "candidateId": candidate_id})
            candidate_id = f"{candidate_id}-{int(row.get('rank', 0)):03d}"
        seen_ids.add(candidate_id)
        merged.append({
            "candidateId": candidate_id,
            "authorityRank": int(row["rank"]),
            "name": row["name"],
            "normalizedName": row["normalizedName"],
            "aliases": row.get("aliases", []),
            "matchedCompanyId": candidate_id if matched_company else None,
            "matchedCompanyName": matched_company.get("name") if matched_company else None,
            "segment": row.get("segment"),
            "province": row.get("province"),
            "brands": row.get("brands", []),
            "authorityIds": row.get("authorityIds", []),
            "sourceUrls": row.get("sourceUrls", []),
            "stockCodes": row.get("stockCodes", []),
            "listingMarket": row.get("listingMarket"),
            "discoveryStatus": status,
            "requiresOfficialCareerReview": True,
            "doNotPublishAsConnected": True,
        })
    summary = {
        "authorityCompanyCount": len(merged),
        "matchedRegistryCount": matched,
        "newCandidateCount": len(merged) - matched,
        "conflictCount": len(conflicts),
        "conflicts": conflicts,
        "deduplicated": True,
    }
    return merged, summary


def build_authority_import_report(
    companies_path: Path,
    authority_path: Path,
    output: Path | None = None,
) -> dict[str, Any]:
    payload = load_authority_index(authority_path)
    companies = json.loads(companies_path.read_text(encoding="utf-8"))
    if not isinstance(companies, list):
        raise ValueError("company registry must be an array")
    rows, merge_summary = merge_authority_candidates(companies, authority_candidate_rows(payload))
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "importType": "authority_company_index",
        "authority": {
            "id": payload.get("authorityId"),
            "name": payload.get("reportName"),
            "year": payload.get("reportYear"),
            "sourceUrl": payload.get("sourceUrl"),
            "pdfUrl": payload.get("pdfUrl"),
            "rowCount": len(payload["companies"]),
            "fixed": True,
        },
        "merge": merge_summary,
        "discoveryOnly": True,
        "promotionRule": "权威名录只创建候选记录；企业官网/官方 ATS、当前届信号、robots/条款和岗位抽查完成后，才允许登记来源或发布岗位。",
        "candidates": rows,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def load_candidate_company_configs(
    companies_path: Path,
    authority_path: Path | None = None,
    hiring_radar_path: Path | None = None,
) -> list[CompanyConfig]:
    """Return the registry plus discovery-only authority/ATS candidates.

    Unmatched rows are represented as ``TARGET``/``UNKNOWN`` company configs.
    Hiring Radar rows may carry a public ATS landing URL, but that URL remains
    an unverified entry lead: it never creates a ``SourceConfig`` and cannot
    pass ``source_can_run``.  Existing registry objects are returned unchanged
    so their evidence and aliases are preserved.

    ``authority_path`` and ``hiring_radar_path`` are optional so older/local
    callers keep the V1 registry-only behaviour.  In production callers pass
    both fixed discovery inputs, making the candidate pool deterministic and
    auditable without mutating ``registry/companies.json``.
    """

    values = json.loads(companies_path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("company registry must be an array")
    existing = [dict(item) for item in values if isinstance(item, dict)]
    merged = list(existing)
    by_id = {str(item.get("id")): item for item in merged if item.get("id")}
    by_key: dict[str, dict[str, Any]] = {}
    for item in merged:
        for value in [item.get("id"), item.get("name"), *(item.get("aliases") or [])]:
            key = normalize_company_name(value)
            if key:
                by_key.setdefault(key, item)

    if authority_path is not None and authority_path.exists():
        payload = load_authority_index(authority_path)
        candidates, _summary = merge_authority_candidates(existing, authority_candidate_rows(payload))
    else:
        candidates = []
    for row in candidates:
        if row.get("matchedCompanyId"):
            continue
        candidate_id = str(row["candidateId"])
        if candidate_id in by_id:
            continue
        merged.append({
            "id": candidate_id,
            "name": row["name"],
            "aliases": row.get("aliases", []),
            "industry": "互联网与数字服务",
            "type": "未知",
            "scale": "未知",
            "sourceStatus": "TARGET",
            "listingStatus": "UNKNOWN",
            "stockCodes": row.get("stockCodes", []),
            "authorityRank": row.get("authorityRank"),
            "authorityIds": row.get("authorityIds", []),
            "authorityEvidenceUrls": row.get("sourceUrls", []),
            "authoritySegment": row.get("segment"),
            "discoveryOnly": True,
            "discoverySource": "isc-internet-top100-2025",
        })

        by_id[candidate_id] = merged[-1]
        for value in [row.get("name"), *(row.get("aliases") or [])]:
            key = normalize_company_name(value)
            if key:
                by_key.setdefault(key, merged[-1])

    # Hiring Radar is imported as a pinned, MIT-licensed *seed* only.  It is
    # useful for expanding discovery coverage because many public ATS tenants
    # are not yet represented in our registry.  We deliberately do not copy
    # scraper code or mark any of these rows as a runnable source.
    if hiring_radar_path is not None and hiring_radar_path.exists():
        from .hiring_radar import load_hiring_radar_seed

        seed = load_hiring_radar_seed(hiring_radar_path)
        for source_row in seed["records"]:
            name = str(source_row.get("companyName") or "").strip()
            key = normalize_company_name(name)
            lookup_keys = [key, normalize_company_name(source_row.get("key"))]
            matched = next((by_key.get(value) for value in lookup_keys if value and by_key.get(value)), None)
            if matched:
                # Preserve a small provenance hint on the in-memory candidate
                # object.  This is metadata only; registry files remain read
                # only and no source status is changed.
                radar_sources = matched.setdefault("discoverySources", [])
                if "hiring-radar" not in radar_sources:
                    radar_sources.append("hiring-radar")
                continue
            if len(key) < 2:
                continue
            candidate_id = candidate_id_for(f"hiring-radar:{source_row.get('key') or name}")
            # A hash collision is extremely unlikely, but deterministic
            # suffixing keeps malformed seed updates from silently replacing a
            # prior candidate.
            if candidate_id in by_id:
                suffix = 2
                base_id = candidate_id
                while f"{base_id}-{suffix}" in by_id:
                    suffix += 1
                candidate_id = f"{base_id}-{suffix}"
            candidate = {
                "id": candidate_id,
                "name": name,
                "aliases": [str(source_row.get("key"))] if str(source_row.get("key") or "").strip() and str(source_row.get("key")) != name else [],
                "industry": "互联网与数字服务",
                "type": "未知",
                "scale": "未知",
                "sourceStatus": "TARGET",
                "listingStatus": "UNKNOWN",
                "careerUrl": source_row.get("entryUrl") or None,
                "discoveryOnly": True,
                "discoverySource": "hiring-radar",
                "hiringRadar": {
                    "key": source_row.get("key"),
                    "ats": source_row.get("ats"),
                    "entryType": source_row.get("entryType", "ENTRY_LEAD"),
                    "entryUrlVerified": bool(source_row.get("entryUrlVerified", False)),
                    "segment": source_row.get("segment"),
                    "sourceLine": source_row.get("sourceLine"),
                    "sourceCommit": seed.get("sourceCommit"),
                },
            }
            merged.append(candidate)
            by_id[candidate_id] = candidate
            for value in [name, *candidate["aliases"]]:
                value_key = normalize_company_name(value)
                if value_key:
                    by_key.setdefault(value_key, candidate)
    return [CompanyConfig.model_validate(item) for item in merged]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import and audit the fixed Internet Society of China top-100 index.")
    parser.add_argument("--companies", type=Path, default=Path("registry/companies.json"))
    parser.add_argument("--authority", type=Path, default=Path("registry/internet-authority-top100.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/internet-authority-import.json"))
    args = parser.parse_args(argv)
    report = build_authority_import_report(args.companies, args.authority, args.output)
    print(json.dumps({"authorityCompanyCount": report["merge"]["authorityCompanyCount"], "matchedRegistryCount": report["merge"]["matchedRegistryCount"], "newCandidateCount": report["merge"]["newCandidateCount"], "conflictCount": report["merge"]["conflictCount"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
