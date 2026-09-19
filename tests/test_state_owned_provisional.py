from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from collector.state_owned_provisional import (
    _entry_items,
    build_web_catalog,
    build_provisional_source,
    collect_provisional_jobs,
    parse_provisional_html,
)


def _candidate() -> dict[str, object]:
    return {
        "candidateId": "soes-demo",
        "stockCode": "000001",
        "shortName": "示例国企",
        "legalName": "示例国企股份有限公司",
        "homepageUrl": "https://example.com",
    }


def test_entry_items_deduplicate_fragments_and_skip_sitemaps() -> None:
    report = {
        "results": [
            {
                **_candidate(),
                "classification": "CONNECTOR_CANDIDATE",
                "recruitmentLinks": [
                    "https://example.com/campus#jobs",
                    "https://example.com/campus",
                    "https://example.com/sitemap.xml",
                ],
                "entryCandidates": [
                    {"landingUrl": "https://example.com/campus#jobs", "visibleTableRowCount": 1}
                ],
            }
        ]
    }
    items = _entry_items(report)
    assert [item["landingUrl"] for item in items] == ["https://example.com/campus"]


def test_provisional_source_is_target_and_uses_public_page_domains() -> None:
    source = build_provisional_source({"candidate": _candidate(), "landingUrl": "https://example.com/campus", "entry": {}})
    assert source is not None
    assert source.status == "TARGET"
    assert source.requires_manual_review is True
    assert source.adapter == "provisional_html"
    assert source.apply_domain == "example.com"


def test_html_parser_keeps_visible_job_rows_without_links_and_skips_navigation() -> None:
    source = build_provisional_source({"candidate": _candidate(), "landingUrl": "https://example.com/campus", "entry": {}})
    assert source is not None
    html = """
    <html><body>
      <nav><a href='/about'>关于我们</a><a href='/campus'>校园招聘</a></nav>
      <table><tr><th>岗位名称</th><th>地点</th><th>要求</th></tr>
        <tr><td>市场运营专员</td><td>武汉</td><td>专业不限，应届毕业生</td></tr>
        <tr><td>算法工程师</td><td>深圳</td><td>计算机相关专业</td></tr>
      </table>
    </body></html>
    """
    jobs = parse_provisional_html(html.encode("utf-8"), source=source, page_url="https://example.com/campus")
    assert [job.title for job in jobs] == ["市场运营专员", "算法工程师"]
    assert all(str(job.apply_url) == "https://example.com/campus" for job in jobs)


def test_collect_provisional_jobs_reports_eligible_rows_separately(tmp_path: Path, monkeypatch) -> None:
    discovery = tmp_path / "discovery.json"
    discovery.write_text(
        json.dumps(
            {
                "results": [
                    {
                        **_candidate(),
                        "classification": "CONNECTOR_CANDIDATE",
                        "recruitmentLinks": ["https://example.com/campus"],
                        "entryCandidates": [{"landingUrl": "https://example.com/campus", "visibleTableRowCount": 2}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class Response:
        status_code = 200
        url = "https://example.com/campus"
        headers = {"content-type": "text/html; charset=utf-8"}
        content = "<table><tr><th>岗位</th></tr><tr><td>市场运营专员</td></tr></table>".encode("utf-8")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *_args, **_kwargs):
            return Response()

    import collector.state_owned_provisional as provisional

    monkeypatch.setattr(provisional.httpx, "Client", Client)
    report = collect_provisional_jobs(discovery, output=tmp_path / "out.json", interval_seconds=0, now=datetime(2026, 9, 16, tzinfo=UTC))
    assert report["provisional"] is True
    assert report["sourceStatus"] == "TARGET"
    assert report["summary"]["rawJobCount"] == 1
    assert report["summary"]["eligibleJobCount"] == 1
    assert len(report["eligibleJobs"]) == 1
    assert (tmp_path / "out.json").exists()


def test_web_catalog_is_camel_case_and_discloses_provisional_status() -> None:
    report = {
        "generatedAt": "2026-09-16T00:00:00Z",
        "summary": {"companyCountWithEligibleJobs": 1, "eligibleJobCount": 1},
        "eligibleJobs": [
            {
                "id": "soe-provisional-000001:1",
                "company_id": "soe-provisional-000001",
                "company_name": "示例国企",
                "title": "市场运营岗",
                "city": "未知",
                "locations": [{"scope": "UNKNOWN", "display_name": "未知", "raw": "未知"}],
                "role_category": "运营",
                "company_industry": "未知",
                "company_type": "未知",
                "company_scale": "未知",
                "cohort": "未知",
                "batch": "未知",
                "education": "本科",
                "major_tags": [],
                "skills": [],
                "description": "公开页面岗位信息",
                "requirements": [],
                "apply_url": "https://example.com/job/1",
                "source_url": "https://example.com/campus",
                "source_name": "示例国企官方校招来源",
                "source_level": "B",
                "first_seen_at": "2026-09-16T00:00:00Z",
                "last_verified_at": "2026-09-16T00:00:00Z",
                "content_hash": "hash",
                "status": "ACTIVE",
                "detail_shard": "00",
            }
        ],
    }
    catalog = build_web_catalog(report)
    assert catalog["jobs"][0]["companyId"] == "soe-provisional-000001"
    assert catalog["jobs"][0]["provisional"] is True
    assert catalog["jobs"][0]["publicationLabel"] == "公开入口临时采集 · 待核验"
    assert catalog["jobs"][0]["locations"][0]["scope"] == "MAINLAND_CHINA"
    assert catalog["jobs"][0]["city"] == "地点待确认"


def test_web_catalog_rebuilds_quantity_first_rows_from_legacy_page_snapshots() -> None:
    """A pre-quantity-first report must not silently republish only 497 rows."""

    raw_job = {
        "source_job_id": "legacy-1",
        "company_id": "soe-provisional-000001",
        "company_name": "示例国企",
        "title": "校园岗位",
        "city": "未知",
        "role_category": "其他",
        "description": "公开页面岗位信息",
        "requirements": [],
        "apply_url": "https://example.com/job/1",
        "source_url": "https://example.com/campus",
        "source_name": "示例国企官方校招来源",
        "source_level": "B",
        "is_campus": True,
    }
    report = {
        "generatedAt": "2026-09-16T00:00:00Z",
        "summary": {"companyCountWithEligibleJobs": 1, "eligibleJobCount": 0, "reviewJobCount": 1, "pageCount": 1},
        # This is the shape emitted by older reports before quantityFirstJobs
        # became a persisted array.
        "sourceResults": [
            {
                "candidateId": "soes-demo",
                "stockCode": "000001",
                "companyName": "示例国企",
                "landingUrl": "https://example.com/campus",
                "jobs": [raw_job],
            }
        ],
    }
    catalog = build_web_catalog(report, include_review=True)
    assert len(catalog["jobs"]) == 1
    assert catalog["jobs"][0]["audienceDecision"] == "NEEDS_REVIEW"
    assert catalog["includesNeedsReview"] is True
