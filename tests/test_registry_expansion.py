from __future__ import annotations

import json
from pathlib import Path

from collector.candidate_sync import build_candidate_backlog
from collector.discovery import build_coverage, check_candidate_sources
from collector.registry import focused_company_priority, load_company_configs, load_focus_registry, focus_company_map

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str):
    return json.loads((ROOT / "registry" / name).read_text(encoding="utf-8"))


def test_company_and_source_registries_are_linked_without_duplicates():
    companies = _read("companies.json")
    sources = _read("sources.json")

    company_ids = [item["id"] for item in companies]
    source_ids = [item["sourceId"] for item in sources]

    assert len(company_ids) == len(set(company_ids))
    assert len(source_ids) == len(set(source_ids))
    assert {item["companyId"] for item in sources} <= set(company_ids)


def test_new_discovery_batch_is_auditable_but_not_published_as_verified():
    companies = {item["id"]: item for item in _read("companies.json")}
    sources = _read("sources.json")
    source_by_id = {item["sourceId"]: item for item in sources}

    expected_companies = {
        "pdd", "kuaishou", "ctrip", "didi", "midea", "byd", "catl",
        "haier", "hisense", "china-mobile", "loreal", "alibaba", "cmb",
        "ccb", "china-telecom", "pingan", "dji",
    }
    assert expected_companies <= companies.keys()

    expected_sources = {
        "pdd-campus", "kuaishou-campus", "ctrip-campus", "didi-campus",
        "midea-campus", "byd-campus", "catl-campus", "haier-campus",
        "hisense-campus", "chinamobile-campus", "loreal-campus",
        "alibaba-campus", "cmb-campus", "ccb-campus",
        "china-telecom-campus", "pingan-campus",
    }
    assert expected_sources <= source_by_id.keys()
    for source_id in expected_sources:
        source = source_by_id[source_id]
        assert source["status"] == "TARGET"
        assert source["evidenceUrls"]
        assert source["adapter"] == "manual_or_ats"


def test_batch10_internet_entries_are_traceable_and_remain_targets():
    companies = {item["id"]: item for item in _read("companies.json")}
    sources = {item["sourceId"]: item for item in _read("sources.json")}
    expected = {
        "perfect-world": "perfect-world-campus",
        "eastmoney": "eastmoney-campus",
        "fourth-paradigm": "fourth-paradigm-campus",
        "cloudwalk": "cloudwalk-careers",
        "qiniu": "qiniu-campus",
        "qingcloud": "qingcloud-careers",
        "smartmore": "smartmore-campus",
        "dolphindb": "dolphindb-campus",
        "beisen": "beisen-careers",
        "tuya": "tuya-careers",
        "pingcap": "pingcap-careers",
    }
    assert all(company_id in companies for company_id in expected)
    for company_id, source_id in expected.items():
        company = companies[company_id]
        source = sources[source_id]
        assert source["companyId"] == company_id
        assert source["status"] == "TARGET"
        assert source["evidenceUrls"]
        assert str(source["sourceUrl"]).startswith("https://")
        assert company.get("careerUrl") or source.get("sourceUrl")
    # The one URL corrected during the low-frequency probe must not regress to
    # the stale /careers path that returned 404.
    assert companies["cloudwalk"]["careerUrl"].endswith("/Join")


def test_target_source_probe_records_only_reachability_metadata(monkeypatch):
    class FakeResponse:
        status_code = 200
        content = b"private response body must not be persisted"
        headers = {"content-type": "text/html; charset=utf-8"}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _url):
            return FakeResponse()

    import collector.discovery as discovery

    monkeypatch.setattr(discovery.httpx, "Client", FakeClient)
    results = check_candidate_sources(
        ROOT / "registry" / "sources.json",
        interval_seconds=0,
        focus_path=ROOT / "registry" / "internet-focus.json",
    )

    target_count = sum(item.get("status") == "TARGET" for item in _read("sources.json"))
    assert len(results) == target_count
    assert all(item["reachable"] is True for item in results)
    assert all("responseBody" not in item and "content" not in item for item in results)
    focus_ids = {item["companyId"] for item in _read("internet-focus.json")["companies"]}
    assert results[0]["companyId"] in focus_ids


def test_internet_focus_registry_links_to_companies_and_keeps_targets_unverified():
    companies = {item["id"] for item in _read("companies.json")}
    focus = _read("internet-focus.json")
    focus_ids = [item["companyId"] for item in focus["companies"]]

    assert focus["focusId"] == "china-internet-v1"
    assert focus["mode"] == "PRIORITIZE"
    assert len(focus_ids) == len(set(focus_ids))
    assert set(focus_ids) <= companies

    source_by_company = {item["companyId"]: item for item in _read("sources.json")}
    for company_id in ("mihoyo", "xiaohongshu", "company-360", "ke"):
        assert source_by_company[company_id]["status"] == "TARGET"


def test_focus_priority_puts_internet_companies_before_non_focus_without_changing_source_gate():
    focus = focus_company_map(load_focus_registry(ROOT / "registry" / "internet-focus.json"))
    configs = load_company_configs(ROOT / "registry" / "companies.json")
    ordered = sorted(configs, key=lambda company: focused_company_priority(company, focus))

    first_non_focus = next(index for index, company in enumerate(ordered) if company.id not in focus)
    assert all(company.id in focus for company in ordered[:first_non_focus])
    assert ordered[0].id == "tencent"

    source_by_id = {item["sourceId"]: item for item in _read("sources.json")}
    assert source_by_id["xiaohongshu-campus"]["status"] == "TARGET"
    assert source_by_id["xiaohongshu-campus"].get("accessMode", "UNKNOWN") != "JSON"


def test_focus_metrics_are_exposed_separately_from_all_company_coverage(tmp_path):
    coverage = build_coverage(
        ROOT / "registry" / "companies.json",
        ROOT / "registry" / "sources.json",
        tmp_path / "coverage.json",
        focus_path=ROOT / "registry" / "internet-focus.json",
    )
    backlog = build_candidate_backlog(
        ROOT / "registry" / "companies.json",
        ROOT / "registry" / "sources.json",
        ROOT / "registry" / "candidate-discovery-sources.json",
        tmp_path / "backlog.json",
        focus_path=ROOT / "registry" / "internet-focus.json",
    )

    assert coverage["selectionPolicy"] == "china_internet_focus_then_listed_and_employee_count_gte_500"
    assert coverage["focus"]["companyCount"] >= 30
    assert backlog["focus"]["companyCount"] == coverage["focus"]["companyCount"]
    assert "segmentCounts" in coverage["focus"]
    assert coverage["verifiedCompanyCount"] == 20
