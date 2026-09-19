from __future__ import annotations

import json
from pathlib import Path

from collector.authority_index import (
    authority_candidate_rows,
    build_authority_import_report,
    load_authority_index,
    load_candidate_company_configs,
)
from collector.hiring_radar import build_hiring_radar_report, load_hiring_radar_seed


ROOT = Path(__file__).resolve().parents[1]


def test_isc_top100_is_complete_and_ordered() -> None:
    payload = load_authority_index(ROOT / "registry" / "internet-authority-top100.json")
    assert payload["authorityId"] == "isc-internet-top100-2025"
    assert len(payload["companies"]) == 100
    assert [item["rank"] for item in payload["companies"]] == list(range(1, 101))
    assert len({item["name"] for item in payload["companies"]}) == 100
    assert len(authority_candidate_rows(payload)) == 100


def test_authority_import_is_discovery_only_and_deduplicates_registry(tmp_path: Path) -> None:
    report = build_authority_import_report(
        ROOT / "registry" / "companies.json",
        ROOT / "registry" / "internet-authority-top100.json",
        tmp_path / "authority-import.json",
    )
    assert report["authority"]["rowCount"] == 100
    assert report["discoveryOnly"] is True
    assert report["merge"]["authorityCompanyCount"] == 100
    assert all(row["requiresOfficialCareerReview"] is True for row in report["candidates"])
    assert all(row["doNotPublishAsConnected"] is True for row in report["candidates"])
    assert (tmp_path / "authority-import.json").exists()


def test_candidate_pool_includes_unmatched_authority_names_without_sources() -> None:
    configs = load_candidate_company_configs(
        ROOT / "registry" / "companies.json",
        ROOT / "registry" / "internet-authority-top100.json",
    )
    ids = [company.id for company in configs]
    assert len(ids) == len(set(ids))
    assert len(configs) >= 100
    assert all(company.source_status in {"TARGET", "VERIFIED", "QUARANTINED", "BLOCKED", "REPLACED", "STALE"} for company in configs)


def test_candidate_pool_can_merge_hiring_radar_without_promoting_sources() -> None:
    configs = load_candidate_company_configs(
        ROOT / "registry" / "companies.json",
        ROOT / "registry" / "internet-authority-top100.json",
        ROOT / "registry" / "hiring-radar-seed.json",
    )
    assert len(configs) > 165
    radar_candidates = [company for company in configs if company.model_dump(mode="json", by_alias=True).get("discoverySource") == "hiring-radar"]
    assert radar_candidates
    assert all(company.source_status == "TARGET" for company in radar_candidates)
    assert all(company.directory is None for company in radar_candidates)


def test_hiring_radar_seed_is_pinned_and_unverified() -> None:
    seed = load_hiring_radar_seed(ROOT / "registry" / "hiring-radar-seed.json")
    assert seed["sourceCommit"] == "3784ed9286e7e7c6f214e1d03e1196595b56b6a4"
    assert seed["license"] == "MIT"
    assert seed["recordCount"] == 157
    assert {row["ats"] for row in seed["records"]} == {"feishu", "moka", "beisen"}
    assert all(row["entryType"] == "ENTRY_LEAD" and row["entryUrlVerified"] is False for row in seed["records"])


def test_hiring_radar_import_never_promotes_seed(tmp_path: Path) -> None:
    report = build_hiring_radar_report(
        ROOT / "registry" / "companies.json",
        ROOT / "registry" / "hiring-radar-seed.json",
        tmp_path / "hiring-radar.json",
    )
    assert report["discoveryOnly"] is True
    assert report["summary"]["recordCount"] == 157
    assert all(row["sourceStatus"] == "TARGET" and row["runnable"] is False for row in report["records"])
