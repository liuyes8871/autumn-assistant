from __future__ import annotations

from datetime import UTC, datetime
import json

from collector.adapters import FeishuCampusAdapter, PublicJsonAdapter, _allowlisted_ats_item, _cohort_from_context
from collector.ats_discovery import (
    classify_discovery,
    detect_security_challenge,
    detect_ats_from_html,
    discover_public_page,
    extract_jobposting_jsonld,
    parse_sitemap_urls,
)
from collector.feeds import (
    AshbyCampusAdapter,
    BeisenCampusAdapter,
    JsonLdCampusAdapter,
    PublicFeedAdapter,
    StaticHtmlCampusAdapter,
    TeamtailorCampusAdapter,
    WorkableCampusAdapter,
    parse_public_feed,
)
from collector.health import source_health_row
from collector.inbox import sanitize_inbox_entry
from collector.registry import generic_json_parser, source_can_run
from collector.schema import DiscoveryCandidate, SourceConfig
from collector.verification import build_evidence_report
from scripts.refresh_public_sources import refresh as refresh_public_sources


def _reviewed_source(**updates: object) -> SourceConfig:
    value: dict[str, object] = {
        "source_id": "ashby-demo",
        "company_id": "demo",
        "company_name": "演示企业",
        "source_url": "https://jobs.example.com/campus",
        "apply_domain": "example.com",
        "apply_domains": ["api.ashbyhq.com"],
        "endpoint": "https://api.ashbyhq.com/posting-api/job-board/demo",
        "adapter": "ashby",
        "access_mode": "JSON",
        "status": "VERIFIED",
        "verified_at": "2026-09-10",
        "robots_reviewed_at": "2026-09-10",
        "terms_reviewed_at": "2026-09-10",
        "request_interval_seconds": 0,
    }
    value.update(updates)
    return SourceConfig.model_validate(value)


def test_discovery_identifies_ashby_link_and_jsonld() -> None:
    html = """
    <a href="https://jobs.ashbyhq.com/demo">校园招聘</a>
    <script type="application/ld+json">{"@type":"JobPosting","title":"校园运营"}</script>
    """
    result = detect_ats_from_html(html, page_url="https://example.com/campus")
    assert result["detectedAts"] == "ASHBY"
    assert result["structuredJobCount"] == 1
    assert extract_jobposting_jsonld(html, page_url="https://example.com/campus")[0]["title"] == "校园运营"


def test_discovery_exposes_safe_classification_and_structured_completeness() -> None:
    html = """
    <link rel="alternate" type="application/rss+xml; charset=utf-8" href="/jobs.xml">
    <script type="application/ld+json">
      {"@type":"https://schema.org/JobPosting","title":"校园运营",
       "url":"/jobs/1","description":"岗位说明","jobLocation":"武汉",
       "datePosted":"2026-09-10","hiringOrganization":{"name":"演示企业"}}
    </script>
    """
    analysis = detect_ats_from_html(html, page_url="https://example.com/campus")
    assert analysis["fieldCompleteness"] == 1.0
    assert "https://example.com/jobs.xml" in analysis["candidateEndpoints"]
    assert classify_discovery(
        reachable=True,
        blocked=False,
        status_code=200,
        matches=analysis["matches"],
        candidate_endpoints=analysis["candidateEndpoints"],
        feed_links=analysis["feedLinks"],
        structured_job_count=analysis["structuredJobCount"],
    ) == "CONNECTOR_CANDIDATE"
    row = DiscoveryCandidate.model_validate({
        "sourceId": "demo", "companyId": "demo", "companyName": "演示企业",
        "landingUrl": "https://example.com/campus", "checkedAt": "2026-09-10T00:00:00Z",
        "classification": "CONNECTOR_CANDIDATE", "fieldCompleteness": analysis["fieldCompleteness"],
    })
    assert row.classification == "CONNECTOR_CANDIDATE"


def test_discovery_marks_beisen_as_connector_and_exposes_primary_endpoint() -> None:
    html = '<a href="https://demo.zhiye.com/campus">校园招聘</a>'
    analysis = detect_ats_from_html(html, page_url="https://example.com/campus")
    assert analysis["detectedAts"] == "BEISEN"
    assert analysis["candidateEndpoint"] == analysis["candidateEndpoints"][0]
    assert classify_discovery(
        reachable=True,
        blocked=False,
        status_code=200,
        matches=analysis["matches"],
        candidate_endpoints=analysis["candidateEndpoints"],
    ) == "CONNECTOR_CANDIDATE"


def test_discovery_infers_workday_cxs_endpoint_without_promoting_source() -> None:
    html = '<a href="https://acme.wd1.myworkdayjobs.com/en-US/Acme_Careers">校园招聘</a>'
    analysis = detect_ats_from_html(html, page_url="https://acme.example.com/campus")
    assert analysis["detectedAts"] == "WORKDAY"
    assert "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Acme_Careers/jobs" in analysis["candidateEndpoints"]


def test_discovery_marks_visible_security_challenge_as_blocked() -> None:
    assert detect_security_challenge("<html><title>Just a moment...</title><p>Verify you are human</p></html>") is True
    assert detect_security_challenge("<html><title>校园招聘</title><p>岗位列表</p></html>") is False


def test_discover_public_page_classifies_405_and_html_challenge_as_unavailable() -> None:
    class Response:
        def __init__(self, status_code: int, content: bytes) -> None:
            self.status_code = status_code
            self.content = content
            self.headers = {"content-type": "text/html"}
            self.url = "https://example.com/campus"

    class Client:
        def __init__(self, response: Response) -> None:
            self.response = response
            self.calls = 0

        def get(self, *_args: object, **_kwargs: object) -> Response:
            self.calls += 1
            return self.response

    blocked = discover_public_page(
        "blocked", "demo", "演示企业", "https://example.com/campus",
        client=Client(Response(405, b"method not allowed")),
    )
    assert blocked["classification"] == "PUBLIC_ACCESS_UNAVAILABLE"
    assert blocked["blocked"] is True
    assert blocked["reviewReasons"] == ["access_blocked"]

    challenge = discover_public_page(
        "challenge", "demo", "演示企业", "https://example.com/campus",
        client=Client(Response(200, b"<title>Just a moment...</title><p>Verify you are human</p>")),
    )
    assert challenge["classification"] == "PUBLIC_ACCESS_UNAVAILABLE"
    assert challenge["blocked"] is True
    assert challenge["reachable"] is False


def test_discover_public_page_rejects_non_https_without_request() -> None:
    class Client:
        def get(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("unsafe landing URL must not be requested")

    result = discover_public_page("http", "demo", "演示企业", "http://example.com/campus", client=Client())
    assert result["classification"] == "PUBLIC_ACCESS_UNAVAILABLE"
    assert result["reviewReasons"] == ["source_url_requires_https"]


def test_sitemap_parser_is_namespace_tolerant_and_bounded() -> None:
    urls = parse_sitemap_urls(
        b"<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        b"<sitemap><loc>/jobs.xml</loc></sitemap></sitemapindex>",
        base_url="https://example.com/",
    )
    assert urls == ["https://example.com/jobs.xml"]


def test_public_feed_parser_supports_rss_and_absolute_links() -> None:
    content = """
    <rss><channel><item><guid>job-1</guid><title>校园市场运营</title>
    <link>/jobs/1</link><description>面向2027届毕业生</description>
    <pubDate>Wed, 10 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>
    """.encode("utf-8")
    rows = parse_public_feed(content, base_url="https://example.com/feed.xml")
    assert rows[0]["id"] == "job-1"
    assert rows[0]["url"] == "https://example.com/jobs/1"
    assert rows[0]["publishedAt"] == "2026-09-10"


def test_ashby_adapter_filters_unlisted_and_maps_public_shape() -> None:
    source = _reviewed_source()

    class Response:
        status_code = 200
        content = json.dumps({"jobs": [
            {"jobPostingId": "a-1", "title": "校园市场运营", "location": "武汉", "jobUrl": "https://example.com/jobs/a-1", "descriptionHtml": "2027届校园招聘", "isListed": True},
            {"jobPostingId": "a-2", "title": "不展示", "jobUrl": "https://example.com/jobs/a-2", "isListed": False},
        ]}).encode("utf-8")
        headers: dict[str, str] = {}

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = AshbyCampusAdapter(client=Client()).fetch(source)
    assert result.complete is True
    assert [job.source_job_id for job in result.jobs] == ["a-1"]
    assert result.jobs[0].cohort == "2027"


def test_public_json_adapter_walks_bounded_nested_data_envelope() -> None:
    source = _reviewed_source()

    class Response:
        status_code = 200
        headers: dict[str, str] = {}
        content = json.dumps({"data": {"list": [{
            "jobPostingId": "nested-1", "title": "校园市场运营", "location": "武汉",
            "jobUrl": "https://example.com/jobs/nested-1", "descriptionHtml": "2027届校园招聘",
        }]}}).encode("utf-8")

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = AshbyCampusAdapter(client=Client()).fetch(source)
    assert result.complete is True
    assert [job.source_job_id for job in result.jobs] == ["nested-1"]


def test_beisen_adapter_maps_nested_public_envelope() -> None:
    source = _reviewed_source(
        source_id="beisen-demo",
        adapter="beisen",
        access_mode="JSON",
        endpoint="https://api.example.com/positions",
        apply_domains=["example.com", "api.example.com"],
    )

    class Response:
        status_code = 200
        headers: dict[str, str] = {}
        content = json.dumps({"data": {"list": [{
            "jobId": "b-1", "jobName": "校园品牌运营", "cityName": "武汉市",
            "detailUrl": "https://example.com/jobs/b-1", "jobDescription": "面向2027届毕业生",
        }]}}).encode("utf-8")

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = BeisenCampusAdapter(client=Client()).fetch(source)
    assert result.complete is True
    assert result.jobs[0].source_job_id == "b-1"
    assert result.jobs[0].cohort == "2027"


def test_workable_adapter_resolves_shortcode_against_reviewed_board() -> None:
    source = _reviewed_source(
        source_id="workable-demo",
        adapter="workable",
        access_mode="JSON",
        source_url="https://apply.workable.com/demo/",
        endpoint="https://apply.workable.com/api/v3/accounts/demo/jobs",
        apply_domain="apply.workable.com",
    )

    class Response:
        status_code = 200
        headers: dict[str, str] = {}
        content = json.dumps({"jobs": [{
            "id": "w-1", "shortcode": "WXYZ", "title": "校园市场运营",
            "location": "上海", "description": "2027届校园招聘",
        }]}).encode("utf-8")

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = WorkableCampusAdapter(client=Client()).fetch(source)
    assert result.complete is True
    assert str(result.jobs[0].apply_url) == "https://apply.workable.com/demo/j/WXYZ"


def test_mixed_ats_allow_list_rejects_unreviewed_postings() -> None:
    source = _reviewed_source(
        allowed_job_ids=["8572402002"],
        allowed_title_markers=["2027 academy"],
    )
    assert _allowlisted_ats_item({"id": 8572402002, "title": "Academy Analyst"}, source)
    assert _allowlisted_ats_item({"id": 999, "title": "2027 Academy Analyst"}, source)
    assert not _allowlisted_ats_item({"id": 999, "title": "Senior Analyst"}, source)


def test_english_early_career_year_is_normalized() -> None:
    source = _reviewed_source(current_cohort_signal="2027 early-career programme")
    assert _cohort_from_context("Point72 Academy Program for Upcoming Graduates (2027 - SG)", source) == "2027"
    assert _cohort_from_context("Market Research Strategy Intern; expected graduation Winter 2027", source) == "2027"


def test_jsonld_adapter_maps_jobposting_page() -> None:
    source = _reviewed_source(
        source_id="jsonld-demo",
        adapter="jsonld",
        access_mode="JSONLD",
        endpoint="https://example.com/campus",
    )

    class Response:
        status_code = 200
        headers: dict[str, str] = {}
        url = "https://example.com/campus"
        content = '''<script type="application/ld+json">{
          "@type":"JobPosting", "title":"校园内容运营",
          "url":"https://example.com/jobs/j-1", "description":"面向2027届毕业生",
          "jobLocation":{"address":{"addressLocality":"深圳"}},
          "datePosted":"2026-09-10", "hiringOrganization":{"name":"演示企业"}
        }</script>'''.encode("utf-8")

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = JsonLdCampusAdapter(client=Client()).fetch(source)
    assert result.complete is True
    assert result.jobs[0].title == "校园内容运营"
    assert result.jobs[0].cohort == "2027"


def test_feed_alias_exposes_vendor_specific_name_without_duplicate_implementation() -> None:
    assert TeamtailorCampusAdapter is PublicFeedAdapter


def test_public_json_adapter_sends_validators_and_handles_304() -> None:
    source = _reviewed_source()
    seen: list[dict[str, str]] = []

    class Response:
        status_code = 304
        headers = {"ETag": "\"next\""}
        content = b""

    class Client:
        def get(self, _url: str, *, headers: dict[str, str]) -> Response:
            seen.append(headers)
            return Response()

    result = PublicJsonAdapter(client=Client()).fetch(
        source,
        str(source.endpoint),
        generic_json_parser,
        cache_entry={"etag": "\"old\"", "lastModified": "Wed, 09 Sep 2026 12:00:00 GMT", "contentHash": "hash"},
    )
    assert result.not_modified is True
    assert seen[0]["If-None-Match"] == '"old"'
    assert seen[0]["If-Modified-Since"].startswith("Wed, 09 Sep")


def test_source_gate_accepts_reviewed_feed_and_health_reports_drop() -> None:
    feed = _reviewed_source(adapter="teamtailor", access_mode="RSS", endpoint="https://example.com/rss")
    assert source_can_run(feed) == (True, "ready")
    row = source_health_row({"sourceId": "x", "health": "healthy", "fetchedJobCount": 2}, history=[10, 11, 12])
    assert row["anomalousDrop"] is True


def test_inbox_discards_sensitive_fields_and_requires_https() -> None:
    clean = sanitize_inbox_entry({
        "title": "校园运营", "companyName": "企业", "applyUrl": "https://example.com/jobs/1",
        "sourceUrl": "https://example.com/campus", "cookie": "secret", "html": "<body>private</body>",
    }, imported_at=datetime(2026, 9, 10, tzinfo=UTC))
    assert clean is not None
    assert "cookie" not in clean and "html" not in clean
    assert sanitize_inbox_entry({"title": "岗位", "companyName": "企业", "applyUrl": "http://example.com/1"}) is None


def test_public_source_refresh_downgrades_stale_health_when_registry_status_changes(tmp_path) -> None:
    registry = tmp_path / "sources.json"
    public = tmp_path / "public-sources.json"
    manifest = tmp_path / "manifest.json"
    target = _reviewed_source(source_id="status-change", status="TARGET")
    registry.write_text(json.dumps([target.model_dump(mode="json", by_alias=True)]), encoding="utf-8")
    public.write_text(json.dumps({"sources": [{
        "sourceId": "status-change", "status": "VERIFIED", "health": "healthy",
        "jobCount": 3, "fetchedJobCount": 3,
    }]}), encoding="utf-8")
    manifest.write_text(json.dumps({"catalogVersion": "test", "generatedAt": "2026-09-10T00:00:00Z"}), encoding="utf-8")

    result = refresh_public_sources(registry, public, manifest)
    assert result["publicSources"] == 1
    row = json.loads(public.read_text(encoding="utf-8"))["sources"][0]
    assert row["status"] == "TARGET"
    assert row["health"] == "not_ready"
    assert row["reason"] == "status_target"


def test_public_source_refresh_clears_stale_auto_evidence_for_target(tmp_path) -> None:
    registry = tmp_path / "sources.json"
    public = tmp_path / "public-sources.json"
    manifest = tmp_path / "manifest.json"
    target = _reviewed_source(source_id="target-with-old-evidence", status="TARGET")
    registry.write_text(json.dumps([target.model_dump(mode="json", by_alias=True)]), encoding="utf-8")
    public.write_text(json.dumps({"sources": [{
        "sourceId": "target-with-old-evidence", "status": "TARGET", "health": "healthy",
        "jobCount": 3, "fetchedJobCount": 3, "autoVerification": {"conclusion": "AUTO_VERIFIED"},
    }]}), encoding="utf-8")
    manifest.write_text(json.dumps({"catalogVersion": "test", "generatedAt": "2026-09-10T00:00:00Z"}), encoding="utf-8")

    refresh_public_sources(registry, public, manifest)
    row = json.loads(public.read_text(encoding="utf-8"))["sources"][0]
    assert row["health"] == "not_ready"
    assert "autoVerification" not in row


def test_static_html_adapter_accepts_visible_table_rows() -> None:
    source = _reviewed_source(adapter="static_html", access_mode="HTML", endpoint="https://example.com/campus")

    class Response:
        status_code = 200
        url = "https://example.com/campus"
        headers: dict[str, str] = {}
        content = "<table><tbody><tr><td><a href='/jobs/1'>2027校园市场运营</a></td><td>武汉市</td></tr></tbody></table>".encode()

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = StaticHtmlCampusAdapter(client=Client()).fetch(source)
    assert result.complete is True
    assert result.jobs[0].title == "2027校园市场运营"


def test_feed_adapter_preserves_previous_snapshot_on_all_malformed_rows() -> None:
    source = _reviewed_source(adapter="teamtailor", access_mode="RSS", endpoint="https://example.com/jobs.rss")

    class Response:
        status_code = 200
        headers: dict[str, str] = {}
        content = b"<rss><channel><item><description>schema changed</description></item></channel></rss>"

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = PublicFeedAdapter(client=Client()).fetch(source)
    assert result.complete is False
    assert result.error == "invalid_items"
    assert result.raw_count == 1


def test_feishu_count_string_and_filtered_rows_do_not_break_pagination() -> None:
    source = SourceConfig(
        source_id="feishu-campus", company_id="demo", company_name="演示企业",
        source_url="https://demo.jobs.feishu.cn/campus/", apply_domain="jobs.feishu.cn",
        adapter="feishu", access_mode="JSON", ats_host="demo.jobs.feishu.cn", website_path="campus",
        page_size=2, max_pages=2, request_interval_seconds=0,
    )

    pages = [
        [{"id": "campus-1", "title": "2027届校招运营", "description": "校园招聘", "recruit_type": {"id": "201", "name": "校园招聘"}},
         {"id": "social-1", "title": "社会招聘工程师", "recruit_type": {"id": "101", "name": "社会招聘"}}],
        [{"id": "campus-2", "title": "2027届校招市场", "description": "校园招聘", "recruit_type": {"id": "201", "name": "校园招聘"}}],
    ]

    class Response:
        status_code = 200
        headers: dict[str, str] = {}

        def __init__(self, posts: list[dict[str, object]]) -> None:
            self.content = json.dumps({"data": {"count": "3", "job_post_list": posts}}, ensure_ascii=False).encode()

    class Client:
        calls: list[int] = []

        def post(self, _url: str, *, json: dict[str, object], **_kwargs: object) -> Response:
            offset = int(json["offset"])
            self.calls.append(offset)
            return Response(pages[offset // 2])

    client = Client()
    result = FeishuCampusAdapter(client=client).fetch(source)
    assert result.complete is True
    assert result.raw_count == 3
    assert [job.source_job_id for job in result.jobs] == ["campus-1", "campus-2"]
    assert client.calls == [0, 2]


def test_new_public_ats_discovery_keeps_tenant_endpoints_as_candidates() -> None:
    cases = {
        "SMARTRECRUITERS": "https://jobs.smartrecruiters.com/acme",
        "PERSONIO": "https://jobs.personio.com/acme",
        "BAMBOOHR": "https://acme.bamboohr.com/careers/list",
        "BREEZY": "https://acme.breezy.hr/",
        "ORACLE": "https://acme.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1",
        "ICIMS": "https://acme.icims.com/jobs/search",
    }
    for expected_ats, url in cases.items():
        analysis = detect_ats_from_html(f'<a href="{url}">校园招聘</a>', page_url="https://example.com/campus")
        assert analysis["detectedAts"] == expected_ats
        assert analysis["candidateEndpoints"]
        assert analysis["candidateEndpoint"] in analysis["candidateEndpoints"]


def test_beisen_bsglobal_is_read_without_executing_script() -> None:
    from collector.feeds import extract_bs_global_config

    payload = extract_bs_global_config(
        '<script>window.BSGlobal = {"tenant":"demo","config":{"api":"https://api.example.com"}};</script>'
    )
    assert payload == {"tenant": "demo", "config": {"api": "https://api.example.com"}}
    assert extract_bs_global_config("window.BSGlobal = decodeURIComponent('hidden');") == {}


def test_complete_auto_evidence_allows_a_public_source_to_run() -> None:
    source = _reviewed_source(
        source_id="smart-auto",
        adapter="smartrecruiters",
        source_url="https://acme.example.com/campus",
        endpoint="https://api.smartrecruiters.com/v1/companies/acme/postings",
        apply_domain="acme.example.com",
        apply_domains=["api.smartrecruiters.com"],
        detected_ats="SMARTRECRUITERS",
        ats_host="api.smartrecruiters.com",
        status="AUTO_VERIFIED",
    )
    report = build_evidence_report(
        source,
        sampled_jobs=3,
        required_field_completeness=1,
        invalid_row_ratio=0,
        duplicate_ratio=0,
        consecutive_healthy_runs=2,
        official_reverse_link=True,
        public_access_no_auth=True,
        robots_terms_allowed=True,
        current_cohort_evidence=True,
        campus_evidence=True,
        company_identity_exact=True,
        apply_domain_verified=True,
        official_reverse_link_url="https://acme.example.com/campus",
    )
    ready = source.model_copy(update={"evidence_report": report})
    assert report.conclusion == "AUTO_VERIFIED"
    assert source_can_run(ready) == (True, "ready")


def test_auto_evidence_rejects_short_samples_and_boss_sources() -> None:
    source = _reviewed_source(
        source_id="short-auto",
        adapter="smartrecruiters",
        source_url="https://acme.example.com/campus",
        endpoint="https://api.smartrecruiters.com/v1/companies/acme/postings",
        apply_domain="acme.example.com",
        apply_domains=["api.smartrecruiters.com"],
        detected_ats="SMARTRECRUITERS",
        ats_host="api.smartrecruiters.com",
        status="AUTO_VERIFIED",
    )
    short_report = build_evidence_report(
        source,
        sampled_jobs=2,
        required_field_completeness=1,
        invalid_row_ratio=0,
        duplicate_ratio=0,
        consecutive_healthy_runs=2,
        official_reverse_link=True,
        public_access_no_auth=True,
        robots_terms_allowed=True,
        current_cohort_evidence=True,
        campus_evidence=True,
        company_identity_exact=True,
        apply_domain_verified=True,
    )
    assert short_report.conclusion == "PROVISIONAL"
    assert "sample_count_insufficient" in short_report.failure_reasons
    assert source_can_run(source.model_copy(update={"evidence_report": short_report}))[0] is False

    boss = _reviewed_source(
        source_id="boss-discovery-only",
        adapter="boss",
        source_url="https://www.zhipin.com/campus",
        endpoint="https://www.zhipin.com/campus/api/jobs",
        apply_domain="zhipin.com",
        apply_domains=["www.zhipin.com"],
        access_mode="JSON",
        status="AUTO_VERIFIED",
    )
    boss_report = build_evidence_report(
        boss,
        sampled_jobs=3,
        required_field_completeness=1,
        invalid_row_ratio=0,
        duplicate_ratio=0,
        consecutive_healthy_runs=2,
        official_reverse_link=True,
        public_access_no_auth=True,
        robots_terms_allowed=True,
        current_cohort_evidence=True,
        campus_evidence=True,
        company_identity_exact=True,
        apply_domain_verified=True,
    )
    assert boss_report.conclusion == "BLOCKED"
    assert source_can_run(boss.model_copy(update={"evidence_report": boss_report}))[0] is False


def test_auto_evidence_rejects_anomalous_job_count_drop() -> None:
    source = _reviewed_source(
        source_id="drop-auto",
        adapter="smartrecruiters",
        source_url="https://acme.example.com/campus",
        endpoint="https://api.smartrecruiters.com/v1/companies/acme/postings",
        apply_domain="acme.example.com",
        apply_domains=["api.smartrecruiters.com"],
        status="AUTO_VERIFIED",
    )
    report = build_evidence_report(
        source,
        sampled_jobs=3,
        required_field_completeness=1,
        invalid_row_ratio=0,
        duplicate_ratio=0,
        consecutive_healthy_runs=2,
        anomalous_drop=True,
        official_reverse_link=True,
        public_access_no_auth=True,
        robots_terms_allowed=True,
        current_cohort_evidence=True,
        campus_evidence=True,
        company_identity_exact=True,
        apply_domain_verified=True,
    )
    assert report.conclusion == "PROVISIONAL"
    assert "anomalous_job_count_drop" in report.failure_reasons
    assert source_can_run(source.model_copy(update={"evidence_report": report}))[0] is False
