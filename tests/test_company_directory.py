from datetime import UTC, datetime
import json
from types import SimpleNamespace

from collector.company_directory import build_company_directory
from collector.directory_cli import refresh_directory


def _job(company_id: str, *, cohort: str = "2027", status: str = "ACTIVE") -> SimpleNamespace:
    return SimpleNamespace(company_id=company_id, cohort=cohort, status=status)


def test_directory_separates_verified_entries_from_unreviewed_leads() -> None:
    companies = [
        {"id": "verified", "name": "已核验公司", "careerUrl": "https://jobs.example.com/campus", "sourceStatus": "VERIFIED"},
        {"id": "lead", "name": "入口线索公司", "careerUrl": "https://careers.example.com/", "sourceStatus": "TARGET"},
        {"id": "missing", "name": "没有入口"},
    ]
    sources = [
        SimpleNamespace(company_id="verified", source_url="https://jobs.example.com/campus", status="VERIFIED", adapter="feishu", access_mode="JSON", verified_at="2026-09-01"),
        SimpleNamespace(company_id="lead", source_url="https://careers.example.com/", status="TARGET", adapter="manual", access_mode="UNKNOWN", verified_at=None),
    ]
    records, summary = build_company_directory(
        companies,
        sources,
        [_job("verified")],
        now=datetime(2026, 9, 8, tzinfo=UTC),
    )
    assert {record["id"] for record in records} == {"verified", "lead"}
    by_id = {record["id"]: record["directory"] for record in records}
    assert by_id["verified"]["directoryStatus"] == "ACTIVE_CONFIRMED"
    assert by_id["verified"]["entryType"] == "OFFICIAL_ATS"
    assert by_id["lead"]["directoryStatus"] == "ACTIVE_LEAD"
    assert by_id["lead"]["entryType"] == "ENTRY_LEAD"
    assert summary["officialEntryCount"] == 1
    assert summary["entryLeadCount"] == 1
    assert summary["companiesWithEligibleJobs"] == 1


def test_directory_keeps_focus_segment_as_non_verification_metadata() -> None:
    records, _summary = build_company_directory(
        [{"id": "focus", "name": "重点公司", "careerUrl": "https://careers.example.com/campus", "sourceStatus": "TARGET"}],
        [],
        [],
        now=datetime(2026, 9, 8, tzinfo=UTC),
        focus_segments={"focus": "内容社区与社交"},
    )
    assert records[0]["focusSegment"] == "内容社区与社交"
    assert records[0]["directory"]["directoryStatus"] == "ACTIVE_LEAD"


def test_directory_does_not_treat_non_current_jobs_as_current_signal() -> None:
    records, summary = build_company_directory(
        [{"id": "old", "name": "旧届公司", "careerUrl": "https://old.example.com/campus", "sourceStatus": "TARGET"}],
        [],
        [_job("old", cohort="2026")],
        now=datetime(2026, 9, 8, tzinfo=UTC),
    )
    assert records[0]["directory"]["directoryStatus"] == "ACTIVE_LEAD"
    assert summary["companiesWithEligibleJobs"] == 0


def test_community_cohort_lead_can_fill_missing_career_url_without_becoming_official() -> None:
    records, summary = build_company_directory(
        [{"id": "lead", "name": "入口线索公司", "sourceStatus": "TARGET"}],
        [],
        [],
        now=datetime(2026, 9, 8, tzinfo=UTC),
        community_leads=[{
            "companyId": "lead",
            "title": "入口线索公司 2027 届秋招",
            "officialUrl": "https://careers.example.com/campus",
            "officialUrlVerified": False,
            "verificationStatus": "NEEDS_REVIEW",
            "sourceUrl": "https://www.xiaohongshu.com/explore/abc",
        }],
    )
    assert len(records) == 1
    assert records[0]["directory"]["directoryStatus"] == "ACTIVE_LEAD"
    assert records[0]["directory"]["entryType"] == "ENTRY_LEAD"
    assert records[0]["directory"]["careerUrl"] == "https://careers.example.com/campus"
    assert summary["entryLeadCount"] == 1


def test_entry_observation_state_is_authoritative_for_public_visibility() -> None:
    companies = [
        {"id": "active", "name": "当前校招公司", "careerUrl": "https://careers.example.com/campus", "sourceStatus": "TARGET"},
        {"id": "stale", "name": "已失效公司", "careerUrl": "https://stale.example.com/campus", "sourceStatus": "VERIFIED"},
    ]
    records, summary = build_company_directory(
        companies,
        [],
        [],
        now=datetime(2026, 9, 8, tzinfo=UTC),
        entry_observations={
            "active": {
                "companyId": "active",
                "directoryStatus": "ACTIVE_CONFIRMED",
                "entryType": "OFFICIAL_CAMPAIGN_PAGE",
                "careerUrl": "https://careers.example.com/2027-campus",
                "evidenceUrl": "https://careers.example.com/news/2027-campus",
                "evidenceText": "官网检测到 2027 届校招信号。",
                "signals": ["2027_CAMPUS"],
                "checkedAt": "2026-09-08T00:00:00+00:00",
                "firstConfirmedAt": "2026-09-01T00:00:00+00:00",
            },
            "stale": {
                "companyId": "stale",
                "directoryStatus": "STALE",
                "careerUrl": "https://stale.example.com/campus",
            },
        },
    )
    assert [record["id"] for record in records] == ["active"]
    entry = records[0]["directory"]
    assert entry["directoryStatus"] == "ACTIVE_CONFIRMED"
    assert entry["entryType"] == "OFFICIAL_CAMPAIGN_PAGE"
    assert entry["careerUrl"].endswith("2027-campus")
    assert entry["evidenceUrl"].endswith("2027-campus")
    assert entry["detectedSignals"] == ["2027_CAMPUS"]
    assert entry["firstConfirmedAt"].startswith("2026-09-01")
    assert summary["activeRecruitingCompanyCount"] == 1


def test_company_directory_accepts_generator_input_after_lead_url_merge() -> None:
    records, _summary = build_company_directory(
        (item for item in [{"id": "lead", "name": "生成器公司", "sourceStatus": "TARGET"}]),
        [],
        [],
        now=datetime(2026, 9, 8, tzinfo=UTC),
        community_leads=[{
            "companyId": "lead",
            "title": "生成器公司 2027 届秋招",
            "officialUrl": "https://careers.example.com/campus",
            "officialUrlVerified": False,
            "verificationStatus": "NEEDS_REVIEW",
        }],
    )
    assert len(records) == 1


def test_directory_refresh_uses_daily_entry_state_to_hide_stale_companies(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "manifest.json").write_text(json.dumps({
        "generatedAt": "2026-09-08T00:00:00+00:00",
        "catalogVersion": "test",
        "isDemo": False,
    }), encoding="utf-8")
    (data_dir / "catalog.json").write_text(json.dumps({"jobs": []}), encoding="utf-8")
    companies_path = tmp_path / "companies.json"
    companies_path.write_text(json.dumps([
        {"id": "active", "name": "当前公司", "careerUrl": "https://active.example.com/campus", "sourceStatus": "TARGET"},
        {"id": "stale", "name": "过期公司", "careerUrl": "https://stale.example.com/campus", "sourceStatus": "TARGET"},
    ], ensure_ascii=False), encoding="utf-8")
    sources_path = tmp_path / "sources.json"
    sources_path.write_text("[]", encoding="utf-8")
    state_path = tmp_path / "entry-state.json"
    state_path.write_text(json.dumps({"entries": {
        "active": {"companyId": "active", "directoryStatus": "ACTIVE_CONFIRMED", "entryType": "OFFICIAL_CAREER_SITE", "careerUrl": "https://active.example.com/campus", "signals": ["2027_CAMPUS"], "checkedAt": "2026-09-08T00:00:00+00:00"},
        "stale": {"companyId": "stale", "directoryStatus": "STALE", "careerUrl": "https://stale.example.com/campus"},
    }}), encoding="utf-8")
    refresh_directory(companies_path=companies_path, sources_path=sources_path, data_dir=data_dir, entry_state=state_path)
    public = json.loads((data_dir / "companies.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in public["companies"]] == ["active"]
