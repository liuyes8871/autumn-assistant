from __future__ import annotations

import json
from pathlib import Path

from collector.company_discovery import (
    build_discovery_report,
    build_entry_discovery_report,
    candidate_id_for,
    detect_campus_signals,
    merge_discovered_candidates,
    merge_entry_observations,
    normalize_company_name,
    parse_html_authority,
    parse_json_authority,
    sanitize_entry_observation,
    sanitize_entry_observation_map,
)


ROOT = Path(__file__).resolve().parents[1]


def test_company_name_key_and_candidate_id_are_stable() -> None:
    assert normalize_company_name("  腾讯（00700.HK） ") == "腾讯00700hk"
    assert candidate_id_for("腾讯") == candidate_id_for(" 腾讯 ")


def test_parse_json_authority_accepts_nested_envelopes_and_deduplicates() -> None:
    rows = parse_json_authority(
        {
            "data": {
                "items": [
                    {"证券简称": "腾讯", "证券代码": "00700", "上市市场": "港交所"},
                    {"companyName": "腾讯", "stockCode": "00700"},
                    {"name": "美团", "stockCode": "03690"},
                    {"total": 2},
                ]
            }
        },
        authority_id="hkex-listed",
        source_url="https://example.test/list",
    )
    assert [row["name"] for row in rows] == ["腾讯", "美团"]
    assert rows[0]["stockCodes"] == ["00700"]
    assert rows[0]["listingMarket"] == "港交所"
    assert all(row["requiresOfficialCareerReview"] for row in rows)


def test_parse_json_authority_accepts_odata_d_results_envelope() -> None:
    rows = parse_json_authority(
        {"d": {"results": [{"SEC_NAME_CN": "小红书", "COMPANY_CODE": "999999"}]}},
        authority_id="exchange-odata",
        source_url="https://example.test/odata",
    )
    assert [row["name"] for row in rows] == ["小红书"]
    assert rows[0]["stockCodes"] == ["999999"]


def test_parse_html_authority_reads_table_names_without_persisting_page_text() -> None:
    rows = parse_html_authority(
        """
        <table><tr><th>股票代码</th><th>证券简称</th></tr>
        <tr><td>000001</td><td>平安银行</td></tr>
        <tr><td>600000</td><td>浦发银行</td></tr></table>
        """,
        authority_id="sse-listed",
        source_url="https://example.test/sse",
    )
    assert [row["name"] for row in rows] == ["平安银行", "浦发银行"]
    assert rows[0]["stockCodes"] == ["000001"]
    assert rows[0]["name"] == "平安银行"
    assert "description" not in rows[0]


def test_merge_matches_registry_aliases_and_prioritises_focus() -> None:
    rows = merge_discovered_candidates(
        [
            {"id": "tencent", "name": "腾讯", "aliases": ["腾讯控股"]},
            {"id": "demo", "name": "演示企业", "aliases": []},
        ],
        [
            {"name": "腾讯控股", "normalizedName": normalize_company_name("腾讯控股"), "candidateId": "candidate-t", "authorityIds": ["hkex"], "sourceUrls": ["https://example.test"], "stockCodes": [], "listingMarket": None, "requiresOfficialCareerReview": True},
            {"name": "新公司", "normalizedName": normalize_company_name("新公司"), "candidateId": "candidate-n", "authorityIds": ["sse"], "sourceUrls": ["https://example.test"], "stockCodes": [], "listingMarket": None, "requiresOfficialCareerReview": True},
        ],
        focus_companies={"tencent": {"priority": 0, "segment": "综合平台与 AI"}},
    )
    assert rows[0]["matchedCompanyId"] == "tencent"
    assert rows[0]["focusPriority"] == 0
    assert rows[1]["discoveryStatus"] == "DISCOVERED"
    assert rows[1]["matchedCompanyId"] is None


def test_discovery_report_fixture_is_discovery_only(tmp_path: Path) -> None:
    fixture = tmp_path / "authority.json"
    fixture.write_text(json.dumps({"sse": {"companies": [{"name": "新公司"}]}}, ensure_ascii=False), encoding="utf-8")
    report = build_discovery_report(
        ROOT / "registry" / "companies.json",
        ROOT / "registry" / "candidate-discovery-sources.json",
        focus_path=ROOT / "registry" / "internet-focus.json",
        input_path=fixture,
    )
    assert report["discoveryOnly"] is True
    assert report["summary"]["newCandidateCount"] >= 1
    assert report["candidates"][0]["requiresOfficialCareerReview"] is True
    assert "VERIFIED" not in {row["discoveryStatus"] for row in report["candidates"]}


def test_current_cohort_signal_detection_is_deterministic() -> None:
    assert "2027_CAMPUS" in detect_campus_signals("2027届校园招聘正式启动")
    assert "AUTUMN_RECRUITMENT" in detect_campus_signals("秋季校园招聘")
    assert detect_campus_signals("社会招聘职位") == []


def test_entry_observation_merge_preserves_first_confirmation_and_stales_failures() -> None:
    previous = {
        "demo": {
            "companyId": "demo",
            "directoryStatus": "ACTIVE_CONFIRMED",
            "careerUrl": "https://careers.example.com/campus",
            "firstConfirmedAt": "2026-09-01T00:00:00+00:00",
            "consecutiveFailures": 0,
            "public": True,
        }
    }
    merged, counts = merge_entry_observations(previous, [{
        "companyId": "demo", "cohort": "2027", "directoryStatus": "STALE",
        "errorType": "timeout", "checkedAt": "2026-09-08T00:00:00+00:00",
    }], stale_after_failures=3)
    assert merged["demo"]["directoryStatus"] == "STALE"
    assert merged["demo"]["public"] is False
    assert merged["demo"]["firstConfirmedAt"] == "2026-09-01T00:00:00+00:00"
    assert counts["stale"] == 1


def test_entry_discovery_fixture_is_separate_from_job_sources(tmp_path: Path) -> None:
    fixture = tmp_path / "entries.json"
    fixture.write_text(json.dumps({"observations": [{
        "companyId": "demo", "cohort": "2027", "directoryStatus": "ACTIVE_CONFIRMED",
        "entryType": "OFFICIAL_CAMPAIGN_PAGE", "careerUrl": "https://careers.example.com/campus",
        "signals": ["2027_CAMPUS"], "checkedAt": "2026-09-08T00:00:00+00:00",
        "public": True,
    }]}), encoding="utf-8")
    companies = tmp_path / "companies.json"
    companies.write_text(json.dumps([{"id": "demo", "name": "演示企业", "careerUrl": "https://careers.example.com/campus"}], ensure_ascii=False), encoding="utf-8")
    report = build_entry_discovery_report(companies, input_path=fixture, output=tmp_path / "report.json")
    assert report["discoveryOnly"] is True
    assert report["summary"]["publicActiveCount"] == 1
    assert report["entries"]["demo"]["directoryStatus"] == "ACTIVE_CONFIRMED"


def test_entry_observation_allowlist_drops_response_and_session_fields() -> None:
    clean = sanitize_entry_observation({
        "companyId": "demo",
        "directoryStatus": "ACTIVE_CONFIRMED",
        "careerUrl": "https://careers.example.com/campus",
        "signals": ["2027_CAMPUS"],
        "responseBody": "full html must not be persisted",
        "html": "<html>secret</html>",
        "cookies": {"session": "secret"},
        "headers": {"authorization": "secret"},
        "stack": "internal traceback",
    })
    assert clean is not None
    assert clean["companyId"] == "demo"
    assert "responseBody" not in clean and "html" not in clean
    assert "cookies" not in clean and "headers" not in clean and "stack" not in clean


def test_entry_observation_map_uses_mapping_key_as_company_id() -> None:
    clean = sanitize_entry_observation_map({
        "demo": {
            "companyId": "another-company",
            "directoryStatus": "ACTIVE_LEAD",
            "careerUrl": "https://careers.example.com/",
        },
    })
    assert list(clean) == ["demo"]
    assert clean["demo"]["companyId"] == "demo"
