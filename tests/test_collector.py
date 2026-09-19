from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest

import collector.cli as collector_cli
from collector.cli import _traffic_domain, build, public_job
from collector.adapters import BaiduCampusAdapter, DomCampusAdapter, FeishuCampusAdapter, GreenhouseCampusAdapter, JdCampusAdapter, LeverCampusAdapter, PublicJsonAdapter, TencentCampusAdapter, WorkdayCampusAdapter, _cohort
from collector.audience_policy import AudienceDecision, assess_job
from collector.discovery import build_coverage
from collector.lifecycle import update_lifecycle
from collector.normalize import clean_text, host_matches, infer_campus, normalize_job, normalize_role_category
from collector.policy import retry_decision
from collector.quality import source_quality
from collector.registry import generic_json_parser, load_sources, source_can_run, tencent_json_parser
from collector.release_gate import validate_manifest
from collector.schema import RawJob, SourceConfig, model_json


def source() -> SourceConfig:
    return SourceConfig(
        source_id="fixture",
        company_id="demo",
        company_name="演示企业",
        source_url="https://jobs.example.com/campus",
        apply_domain="example.com",
        source_level="DEMO",
    )


def test_traffic_domain_serialises_shared_ats_tenants() -> None:
    assert _traffic_domain("nio.jobs.feishu.cn") == "feishu.cn"
    assert _traffic_domain("anker-in.jobs.feishu.cn") == "feishu.cn"
    assert _traffic_domain("tencent.wd1.myworkdayjobs.com") == "myworkdayjobs.com"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("【2027届秋招】用户运营", "2027"),
        ("屏幕显示工程师-2027校招", "2027"),
        ("【2027秋招】客户端开发工程师", "2027"),
        ("2027 年校园招聘管培生", "2027"),
        ("产品发布于2027年，面向社会人才", "未知"),
    ],
)
def test_cohort_accepts_official_campus_title_variants(text: str, expected: str) -> None:
    assert _cohort(text) == expected


def job(**overrides: object) -> RawJob:
    value = {
        "source_job_id": "1",
        "company_id": "demo",
        "company_name": "演示企业",
        "title": "校园运营",
        "city": "武汉市",
        "role_category": "运营",
        "company_industry": "互联网",
        "company_type": "民企",
        "company_scale": "500–999",
        "cohort": "2027",
        "batch": "秋招正式批",
        "education": "本科",
        "description": "<p>参与用户运营<script>alert(1)</script></p>",
        "requirements": ["数据分析", "数据分析"],
        "apply_url": "https://jobs.example.com/apply/1",
        "source_url": "https://jobs.example.com/campus",
        "source_name": "演示官网",
        "source_level": "DEMO",
        "is_campus": True,
    }
    value.update(overrides)
    return RawJob.model_validate(value)


def test_clean_text_removes_script_and_collapses_whitespace() -> None:
    assert clean_text("<p>hello</p><script>bad()</script>  world") == "hello world"


def test_normalize_city_and_stable_id() -> None:
    normalized = normalize_job(job(), source(), datetime(2026, 9, 2, tzinfo=UTC))
    assert normalized.city == "武汉"
    assert normalized.id == "demo:1"
    assert "alert" not in normalized.description
    assert normalized.requirements == ["数据分析"]


def test_role_category_aliases_use_stable_public_taxonomy() -> None:
    assert normalize_role_category("战略与投资") == "金融/投研"
    assert normalize_role_category("销售、服务与支持") == "销售/商务"
    assert normalize_role_category("未知的岗位族") == "其他"


@pytest.mark.parametrize(
    ("title", "role_category", "requirements", "expected"),
    [
        ("软件工程师", "其他", [], AudienceDecision.OUT_OF_SCOPE),
        ("软件工程师", "其他", ["不限专业"], AudienceDecision.OUT_OF_SCOPE),
        ("市场管培生", "市场/品牌", ["计算机、自动化等相关专业"], AudienceDecision.OUT_OF_SCOPE),
        ("市场管培生", "市场/品牌", ["计算机专业优先，同时接受市场营销、工商管理"], AudienceDecision.TARGET_GENERALIST),
        ("商业数据分析", "数据", ["不限专业，熟悉 SQL、Python 者优先"], AudienceDecision.TARGET_GENERALIST),
        ("法务专员", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("校园游戏策划", "游戏策划/发行", [], AudienceDecision.TARGET_GENERALIST),
        ("技术策划", "游戏策划/发行", [], AudienceDecision.OUT_OF_SCOPE),
        ("Game Backend Development Intern", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("Data Science Intern", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("Database Administrator Intern", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("IT Operations Intern", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("World Model Research Intern", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("Game Research & Development Intern, Engine Research", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("Game ML Researcher Intern", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("Computer Science Intern", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("Marketing Trainee (IT Marketing)", "市场/品牌", ["专业不限"], AudienceDecision.TARGET_GENERALIST),
        ("数据库管理员", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("系统运维专员", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("市场研究员", "市场/品牌", [], AudienceDecision.TARGET_GENERALIST),
        ("项目专员", "其他", [], AudienceDecision.TARGET_GENERALIST),
        ("AI Product Manager", "产品", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("视觉设计师", "设计", ["设计专业，需提供作品集"], AudienceDecision.OUT_OF_SCOPE),
        ("产品设计师", "产品", ["不限专业"], AudienceDecision.OUT_OF_SCOPE),
        ("内容运营", "运营", ["需提供作品集"], AudienceDecision.OUT_OF_SCOPE),
        ("内容运营", "运营", ["有作品集者优先"], AudienceDecision.TARGET_GENERALIST),
        ("投资顾问", "金融/投研", ["负责 client portfolio management"], AudienceDecision.TARGET_GENERALIST),
        ("市场专员", "市场/品牌", ["设计专业背景"], AudienceDecision.OUT_OF_SCOPE),
        ("供应链管理培训生", "供应链/采购/物流", ["工商管理、物流管理专业"], AudienceDecision.TARGET_GENERALIST),
        ("供应链工程师", "供应链/采购/物流", [], AudienceDecision.OUT_OF_SCOPE),
        ("数据科学家", "数据", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("研发专员", "其他", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("技术运营", "运营", ["专业不限"], AudienceDecision.OUT_OF_SCOPE),
        ("运营专员", "其他", [], AudienceDecision.TARGET_GENERALIST),
        ("校园岗位", "其他", [], AudienceDecision.NEEDS_REVIEW),
    ],
)
def test_audience_policy_classifies_target_and_specialized_roles(
    title: str, role_category: str, requirements: list[str], expected: AudienceDecision
) -> None:
    result = assess_job(job(title=title, role_category=role_category, requirements=requirements))
    assert result.decision == expected


def test_structured_major_tags_are_treated_as_requirements() -> None:
    assert assess_job(job(title="市场专员", role_category="市场/品牌", major_tags=["计算机"])).decision == AudienceDecision.OUT_OF_SCOPE
    assert assess_job(job(title="市场专员", role_category="市场/品牌", major_tags=["计算机专业优先", "市场营销"])).decision == AudienceDecision.TARGET_GENERALIST


def test_major_gate_does_not_treat_jd_domain_prose_as_a_major_requirement() -> None:
    # “计算机办公软件” describes a tool, not the applicant's major.
    assert assess_job(job(title="市场专员", role_category="市场/品牌", requirements=["岗位要求熟悉计算机办公软件"])).decision == AudienceDecision.TARGET_GENERALIST
    # Likewise an unclassified title cannot be admitted merely because its JD
    # mentions a business or marketing team.
    assert assess_job(job(title="专项岗位", role_category="其他", description="支持 business team 制定 marketing 计划", requirements=[])).decision == AudienceDecision.NEEDS_REVIEW


def test_explicit_major_sentence_without_requirement_prefix_is_still_blocked() -> None:
    assert assess_job(job(title="市场专员", role_category="市场/品牌", requirements=["计算机专业"])).decision == AudienceDecision.OUT_OF_SCOPE
    assert assess_job(job(title="市场专员", role_category="市场/品牌", requirements=["Computer Science"])).decision == AudienceDecision.OUT_OF_SCOPE
    assert assess_job(job(title="市场专员", role_category="市场/品牌", requirements=["计算机或市场营销相关专业"])).decision == AudienceDecision.TARGET_GENERALIST
    assert assess_job(job(title="市场专员", role_category="市场/品牌", requirements=["Computer Science preferred"])).decision == AudienceDecision.TARGET_GENERALIST
    assert assess_job(job(title="市场专员", role_category="市场/品牌", requirements=["Computer Science preferred; Engineering required"])).decision == AudienceDecision.OUT_OF_SCOPE


def test_social_job_is_rejected() -> None:
    social = job(title="高级工程师", description="社招岗位", is_campus=False)
    assert not infer_campus(social)
    with pytest.raises(ValueError, match="social_or_unverified_job"):
        normalize_job(social, source())


def test_source_name_cannot_turn_an_unmarked_social_result_into_campus_job() -> None:
    unmarked = job(
        title="招聘经理",
        description="负责招聘策略和人才甄选。",
        requirements=["一年以上工作经验"],
        batch="未知",
        cohort="未知",
        source_name="演示企业官方校招来源",
        is_campus=None,
    )
    assert not infer_campus(unmarked)
    with pytest.raises(ValueError, match="social_or_unverified_job"):
        normalize_job(unmarked, source())


def test_reviewed_campus_scope_allows_experience_word_in_requirements() -> None:
    campus = job(title="校园产品实习生", requirements=["有项目经验者优先"], is_campus=True)
    assert infer_campus(campus)


def test_explicit_social_title_is_rejected_even_when_feed_is_misconfigured() -> None:
    social = job(title="社会招聘高级工程师", is_campus=True)
    assert not infer_campus(social)


def test_domain_allow_list_does_not_accept_lookalikes() -> None:
    assert host_matches("careers.example.com", "example.com")
    assert host_matches("example.com", "example.com")
    assert not host_matches("example.com.evil.test", "example.com")
    assert not host_matches("notexample.com", "example.com")


def test_normalize_rejects_unreviewed_source_page_domain() -> None:
    untrusted = job(source_url="https://jobs.example.net/copied-list")
    with pytest.raises(ValueError, match="unverified_source_domain"):
        normalize_job(untrusted, source())


def test_quality_quarantines_large_count_drop() -> None:
    normalized = normalize_job(job(), source())
    report = source_quality([normalized], "fixture", previous_count=3)
    assert report.quarantined is True
    assert any("50_percent" in reason for reason in report.reasons)


def test_failed_fetch_does_not_quarantine() -> None:
    normalized = normalize_job(job(), source())
    report = source_quality([normalized], "fixture", previous_count=10, fetch_ok=False)
    assert report.quarantined is False
    assert "fetch_failed_preserve_previous_catalog" in report.reasons


def test_build_writes_catalog_and_excludes_social_fixture(tmp_path: Path) -> None:
    result = build(Path("collector/demo_raw.json"), tmp_path)
    assert result["accepted"] == 2
    assert (tmp_path / "catalog.json").exists()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "companies.json").exists()
    assert list((tmp_path / "jobs").glob("*.json"))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["audiencePolicy"]["version"] == "humanities-social-business-v1"
    assert manifest["audiencePolicy"]["eligibleJobCount"] == 2
    assert manifest["coverage"]["status"] == "IN_PROGRESS"
    assert manifest["coverage"]["scope"] == "registry_candidates_and_reviewed_sources"
    assert manifest["collectionFocus"]["id"] == "china-internet-v1"
    assert manifest["collectionFocus"]["focusCompanyCount"] == 0
    audience_report = next(item for item in manifest["reports"] if item.get("reportType") == "audience_filter")
    assert audience_report["current"]["targetGeneralist"] == 2
    assert audience_report["bySource"]
    assert audience_report["reasonCounts"]["ALLOWED_TARGET_MAJOR"] == 2
    assert all("description" not in item and "requirements" not in item for item in audience_report["reviewJobs"])
    details = [item for shard in (tmp_path / "jobs").glob("*.json") for item in json.loads(shard.read_text(encoding="utf-8"))["jobs"]]
    assert all(item["audienceDecision"] == "TARGET_GENERALIST" for item in details)


def test_v1_state_migration_removes_technical_history_without_count_drop_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_value = SourceConfig.model_validate({**source().model_dump(mode="json"),
        "source_level": "A",
        "status": "VERIFIED",
        "access_mode": "JSON",
        "verified_at": "2026-09-03",
        "robots_reviewed_at": "2026-09-03",
        "terms_reviewed_at": "2026-09-03",
    })
    source_registry = tmp_path / "sources.json"
    source_registry.write_text(json.dumps([source_value.model_dump(mode="json", by_alias=True)], ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    technical = normalize_job(job(source_id="fixture", source_job_id="tech", source_level="A", title="软件工程师", requirements=["不限专业"]), source_value, now)
    eligible = normalize_job(job(source_id="fixture", source_job_id="eligible", source_level="A", title="市场专员", role_category="市场/品牌"), source_value, now)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"schemaVersion": 1, "jobs": [model_json(technical), model_json(eligible)]}, ensure_ascii=False), encoding="utf-8")

    raw_current = job(source_id="fixture", source_job_id="eligible", source_level="A", title="市场专员", role_category="市场/品牌")
    monkeypatch.setattr(
        collector_cli,
        "_fetch_live_sources",
        lambda _sources, max_domain_workers=4: (
            [raw_current],
            [collector_cli.public_source_record(source_value, health="healthy", job_count=1)],
            {"fixture": True},
        ),
    )
    output = tmp_path / "data"
    result = build(None, output, sources_path=source_registry, state_path=state_path, now=now)
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["accepted"] == 1
    assert [item["title"] for item in catalog["jobs"]] == ["市场专员"]
    assert [item["title"] for item in state["jobs"]] == ["市场专员"]
    assert state["schemaVersion"] == 2
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["sourceHealth"]["quarantined"] == 0


def test_verified_source_gate_fails_before_overwriting_previous_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_value = source()
    source_registry = tmp_path / "sources.json"
    source_registry.write_text(json.dumps([source_value.model_dump(mode="json", by_alias=True)], ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "data"
    output.mkdir()
    sentinel = output / "manifest.json"
    sentinel.write_text('{"catalogVersion":"known-good"}', encoding="utf-8")
    catalog_sentinel = output / "catalog.json"
    catalog_sentinel.write_text('{"catalogVersion":"known-good"}', encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text('{"schemaVersion":1,"jobs":[]}', encoding="utf-8")
    monkeypatch.setattr(
        collector_cli,
        "_fetch_live_sources",
        lambda _sources, max_domain_workers=4: ([], [collector_cli.public_source_record(source_value, health="healthy", job_count=0)], {"fixture": True}),
    )
    with pytest.raises(RuntimeError, match="verified_source_gate_failed:0<1"):
        build(None, output, sources_path=source_registry, state_path=state_path, min_verified_sources=1)
    assert sentinel.read_text(encoding="utf-8") == '{"catalogVersion":"known-good"}'
    assert catalog_sentinel.read_text(encoding="utf-8") == '{"catalogVersion":"known-good"}'
    assert json.loads(state_path.read_text(encoding="utf-8"))["schemaVersion"] == 1


def test_not_modified_source_counts_toward_verified_gate_and_reuses_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_value = SourceConfig.model_validate({**source().model_dump(mode="json"),
        "source_level": "A",
        "status": "VERIFIED",
        "access_mode": "JSON",
        "endpoint": "https://jobs.example.com/api/jobs",
        "verified_at": "2026-09-03",
        "robots_reviewed_at": "2026-09-03",
        "terms_reviewed_at": "2026-09-03",
    })
    source_registry = tmp_path / "sources.json"
    source_registry.write_text(json.dumps([source_value.model_dump(mode="json", by_alias=True)], ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    previous_job = normalize_job(job(source_id="fixture", source_job_id="stable"), source_value, now)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "schemaVersion": 2,
        "sourceObservedCounts": {"fixture": 1},
        "sourceCountHistory": {"fixture": [1, 1, 1]},
        "jobs": [model_json(previous_job)],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        collector_cli,
        "_fetch_live_sources",
        lambda _sources, **_kwargs: (
            [],
            [collector_cli.public_source_record(
                source_value,
                health="not_modified",
                not_modified=True,
            )],
            {"fixture": True},
        ),
    )
    output = tmp_path / "data"
    result = build(None, output, sources_path=source_registry, state_path=state_path, now=now, min_verified_sources=1)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    sources = json.loads((output / "sources.json").read_text(encoding="utf-8"))["sources"]

    assert result["verifiedSourceCount"] == 1
    assert manifest["verifiedSourceCount"] == 1
    assert manifest["sourceHealth"]["notModified"] == 1
    assert [item["id"] for item in catalog["jobs"]] == [previous_job.id]
    assert sources[0]["jobCount"] == 1
    assert sources[0]["health"] == "not_modified"


def test_audience_filter_does_not_trigger_count_drop_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_value = SourceConfig.model_validate({**source().model_dump(mode="json"),
        "source_level": "A",
        "status": "VERIFIED",
        "access_mode": "JSON",
        "verified_at": "2026-09-03",
        "robots_reviewed_at": "2026-09-03",
        "terms_reviewed_at": "2026-09-03",
    })
    source_registry = tmp_path / "sources.json"
    source_registry.write_text(json.dumps([source_value.model_dump(mode="json", by_alias=True)], ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    technical = normalize_job(job(source_id="fixture", source_job_id="tech", source_level="A", title="软件工程师", requirements=["不限专业"]), source_value, now)
    eligible = normalize_job(job(source_id="fixture", source_job_id="eligible", source_level="A", title="市场专员", role_category="市场/品牌"), source_value, now)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "schemaVersion": 2,
        "audiencePolicyVersion": "humanities-social-business-v1",
        "sourceObservedCounts": {"fixture": 2},
        "jobs": [model_json(technical), model_json(eligible)],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        collector_cli,
        "_fetch_live_sources",
        lambda _sources, max_domain_workers=4: (
            [job(source_id="fixture", source_job_id="tech", source_level="A", title="软件工程师", requirements=["不限专业"]),
             job(source_id="fixture", source_job_id="eligible", source_level="A", title="市场专员", role_category="市场/品牌")],
            [collector_cli.public_source_record(source_value, health="healthy", job_count=2)],
            {"fixture": True},
        ),
    )
    output = tmp_path / "data"
    build(None, output, sources_path=source_registry, state_path=state_path, now=now)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    sources = json.loads((output / "sources.json").read_text(encoding="utf-8"))["sources"]
    assert manifest["sourceHealth"]["quarantined"] == 0
    assert manifest["audiencePolicy"]["eligibleJobCount"] == 1
    assert manifest["audiencePolicy"]["excludedJobCount"] == 1
    assert sources[0]["fetchedJobCount"] == 2
    assert sources[0]["eligibleJobCount"] == 1


def test_registry_has_fifty_target_companies() -> None:
    import json

    companies = json.loads(Path("registry/companies.json").read_text(encoding="utf-8"))
    assert len(companies) >= 50
    assert all(company["sourceStatus"] in {"TARGET", "VERIFIED", "QUARANTINED", "BLOCKED", "REPLACED", "STALE"} for company in companies)
    verified = [company for company in companies if company["sourceStatus"] == "VERIFIED"]
    assert verified
    # Listed, audited large employers are the priority rather than an absolute
    # exclusion rule: a small number of clearly labelled private employers can
    # be retained to cover sectors such as games. Unknown scale must never be
    # presented as an audited employee band.
    priority_verified = [company for company in verified if not company.get("coverageException")]
    listed_large = [company for company in priority_verified if company.get("listingStatus") == "LISTED" and company.get("scale") != "未知"]
    assert len(listed_large) / len(priority_verified) >= 0.8
    assert all(company.get("listingStatus") in {"LISTED", "UNLISTED", "UNKNOWN"} for company in verified)


def test_retry_policy_never_retries_access_controls() -> None:
    assert retry_decision(403, 1).retry is False
    assert retry_decision(429, 1).retry is False
    assert retry_decision(503, 1).retry is True
    assert retry_decision(None, 3).retry is False


def test_lifecycle_needs_two_successful_missing_snapshots() -> None:
    existing = normalize_job(job(), source())
    first = update_lifecycle([existing], [], fetch_ok=True)
    assert first[0].status == "ACTIVE"
    assert first[0].first_missing_successes == 1
    second = update_lifecycle(first, [], fetch_ok=True)
    assert second[0].status == "CLOSED"
    assert update_lifecycle([existing], [], fetch_ok=False)[0].status == "ACTIVE"


def test_registry_accepts_public_camel_case_source_contract() -> None:
    sources = load_sources(Path("registry/sources.json"))
    assert len(sources) >= 10
    tencent = next(item for item in sources if item.source_id == "tencent-campus")
    assert tencent.parser == "tencent_json"
    assert str(tencent.endpoint).startswith("https://careers.tencent.com/")


def test_registry_allows_explicit_bytedance_hire_host() -> None:
    source = next(item for item in load_sources(Path("registry/sources.json")) if item.source_id == "bytedance-campus")
    assert source_can_run(source) == (True, "ready")
    assert source.ats_host == "jobs.bytedance.com"


def test_tencent_fixture_maps_without_inventing_publish_date() -> None:
    payload = json.loads(Path("tests/fixtures/tencent-response.json").read_text(encoding="utf-8"))
    parsed = tencent_json_parser(payload["Data"]["Posts"][0], load_sources(Path("registry/sources.json"))[0])
    assert parsed.title == "校园运营策划（武汉）"
    assert parsed.publish_date is None
    assert parsed.publish_date_source == "UNKNOWN"
    assert parsed.is_campus is True


def test_verified_source_needs_complete_review_dates() -> None:
    reviewed = SourceConfig(
        source_id="reviewed", company_id="demo", company_name="演示企业",
        source_url="https://jobs.example.com/campus", apply_domain="example.com",
        endpoint="https://jobs.example.com/api", access_mode="JSON", status="VERIFIED",
        verified_at="2026-09-03", robots_reviewed_at="2026-09-03", terms_reviewed_at="2026-09-03",
    )
    assert source_can_run(reviewed) == (True, "ready")
    assert source_can_run(reviewed.model_copy(update={"terms_reviewed_at": None}))[1] == "source_review_dates_incomplete"


def test_feishu_adapter_maps_public_campus_fixture() -> None:
    payload = Path("tests/fixtures/feishu-response.json").read_bytes()

    class Response:
        status_code = 200
        content = payload

    class Client:
        requests: list[dict[str, object]] = []
        urls: list[str] = []

        def post(self, url: str, **kwargs: object) -> Response:
            self.urls.append(url)
            self.requests.append(kwargs)
            return Response()

    source_value = SourceConfig(
        source_id="feishu-campus", company_id="demo", company_name="演示企业",
        source_url="https://demo.jobs.feishu.cn/campus/", apply_domain="jobs.feishu.cn",
        adapter="feishu", access_mode="JSON", ats_host="demo.jobs.feishu.cn", website_path="campus",
        page_size=100, max_pages=2, request_interval_seconds=0,
    )
    client = Client()
    result = FeishuCampusAdapter(client=client).fetch(source_value)
    assert result.complete is True
    assert len(result.jobs) == 2
    assert result.jobs[0].title == "【2027届秋招】用户运营"
    assert result.jobs[0].cohort == "2027"
    assert result.jobs[0].batch == "秋招正式批"
    assert result.jobs[0].is_campus is True
    assert client.requests[0]["json"]["recruitment_id_list"] == ["201"]


def test_feishu_adapter_rejects_explicit_experienced_item() -> None:
    class Response:
        status_code = 200
        content = json.dumps({
            "code": 0,
            "data": {
                "count": 2,
                "job_post_list": [
                    {"id": "campus", "title": "2027届校招运营", "city_list": [{"name": "武汉"}], "recruit_type": {"id": "201", "name": "校园招聘"}},
                    {"id": "social", "title": "社会招聘高级工程师", "city_list": [{"name": "深圳"}], "recruit_type": {"id": "101", "name": "社会招聘"}},
                ],
            },
        }, ensure_ascii=False).encode("utf-8")

    class Client:
        def post(self, _url: str, **_kwargs: object) -> Response:
            return Response()

    source_value = SourceConfig(
        source_id="feishu-campus", company_id="demo", company_name="演示企业",
        source_url="https://demo.jobs.feishu.cn/campus/", apply_domain="jobs.feishu.cn",
        adapter="feishu", access_mode="JSON", ats_host="demo.jobs.feishu.cn", website_path="campus",
        page_size=100, max_pages=2, request_interval_seconds=0,
    )
    result = FeishuCampusAdapter(client=Client()).fetch(source_value)
    assert result.complete is True
    assert [item.source_job_id for item in result.jobs] == ["campus"]


def test_baidu_adapter_uses_form_pagination_and_rejects_social_items() -> None:
    first_page = json.loads(Path("tests/fixtures/baidu-response.json").read_text(encoding="utf-8"))
    second_item = {
        "education": "硕士", "name": "平台研发工程师", "orgName": "百度",
        "postId": "baidu-2027-002", "jobId": "baidu-2027-002", "postType": "技术",
        "publishDate": "2026-08-28", "serviceCondition": "硕士及以上，面向 2027 届毕业生。",
        "workContent": "参与云平台服务研发。", "workPlace": "上海市",
        "projectType": "校招", "projectTypeCode": "1", "recruitType": "GRADUATE",
    }

    class Response:
        status_code = 200

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def json(self) -> dict[str, object]:
            return self.payload

    class Client:
        requests: list[dict[str, object]] = []
        urls: list[str] = []

        def post(self, url: str, **kwargs: object) -> Response:
            self.urls.append(url)
            self.requests.append(kwargs)
            body = kwargs["data"]
            assert isinstance(body, dict)
            if body["curPage"] == "1":
                return Response(first_page)
            return Response({"status": "ok", "data": {"total": "3", "list": [second_item]}})

    source_value = SourceConfig(
        source_id="baidu-campus", company_id="baidu", company_name="百度",
        source_url="https://talent.baidu.com/jobs/list", apply_domain="talent.baidu.com",
        adapter="baidu", access_mode="JSON", endpoint="https://talent.baidu.com/httservice/getPostListNew",
        page_size=2, max_pages=3, request_interval_seconds=0,
        note="面向全球 2027 届毕业生的校园招聘公开接口。",
    )
    client = Client()
    result = BaiduCampusAdapter(client=client).fetch(source_value)
    assert result.complete is True
    assert result.pages == 2
    assert [item.source_job_id for item in result.jobs] == ["baidu-2027-001", "baidu-2027-002"]
    assert result.jobs[0].cohort == "2027"
    assert result.jobs[0].publish_date_source == "OFFICIAL"
    assert result.jobs[0].apply_url.host == "talent.baidu.com"
    assert all(request["headers"]["Content-Type"].startswith("application/x-www-form-urlencoded") for request in client.requests)
    assert client.requests[0]["data"]["recruitType"] == "GRADUATE"


def test_baidu_adapter_rejects_invalid_status_without_publishing() -> None:
    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"status": "fail", "message": "security challenge"}

    class Client:
        def post(self, _url: str, **_kwargs: object) -> Response:
            return Response()

    source_value = SourceConfig(
        source_id="baidu-campus", company_id="baidu", company_name="百度",
        source_url="https://talent.baidu.com/jobs/list", apply_domain="talent.baidu.com",
        adapter="baidu", access_mode="JSON", endpoint="https://talent.baidu.com/httservice/getPostListNew",
        request_interval_seconds=0,
    )
    result = BaiduCampusAdapter(client=Client()).fetch(source_value)
    assert result.complete is False
    assert result.jobs == []
    assert result.error == "baidu_api:security challenge"


def test_jd_adapter_maps_present_feed_and_detects_incomplete_pagination() -> None:
    first_page = json.loads(Path("tests/fixtures/jd-response.json").read_text(encoding="utf-8"))
    second_item = {
        "publishId": 9121, "positionName": "采销管培生", "jobDirection": "采销与物流方向",
        "publishTime": 1784871792000, "workContent": "参与供应链和采销业务。",
        "qualification": "本科及以上，面向2027届毕业生。",
        "requirementVoList": [{"workCity": "湖北省-武汉市", "positionBg": "京东零售"}],
    }

    class Response:
        status_code = 200

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def json(self) -> dict[str, object]:
            return self.payload

    class Client:
        requests: list[dict[str, object]] = []
        urls: list[str] = []

        def post(self, url: str, **kwargs: object) -> Response:
            self.urls.append(url)
            self.requests.append(kwargs)
            body = kwargs["json"]
            assert isinstance(body, dict)
            if body["pageIndex"] == 0:
                return Response(first_page)
            return Response({"success": True, "body": {"totalNumber": 3, "items": [second_item]}})

    source_value = SourceConfig(
        source_id="jd-campus", company_id="jd", company_name="京东",
        source_url="https://campus.jd.com/", apply_domain="campus.jd.com",
        adapter="jd", access_mode="JSON", endpoint="https://campus.jd.com/api/wx/position/page?type=present",
        page_size=2, max_pages=3, request_interval_seconds=0,
        note="京东官方校园招聘，面向 2027 届毕业生。",
    )
    client = Client()
    result = JdCampusAdapter(client=client).fetch(source_value)
    assert result.complete is True
    assert result.pages == 2
    assert [item.source_job_id for item in result.jobs] == ["9119", "9120", "9121"]
    assert result.jobs[0].cohort == "2027"
    assert result.jobs[0].city == "北京、深圳"
    assert result.jobs[0].role_category == "产品"
    assert result.jobs[0].apply_url.host == "campus.jd.com"
    assert client.requests[0]["json"]["pageIndex"] == 0
    assert "type=present" in client.urls[0]


def test_tencent_adapter_uses_only_live_campus_dictionary_codes() -> None:
    fixture = json.loads(Path("tests/fixtures/tencent-response.json").read_text(encoding="utf-8"))

    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return fixture

    class Client:
        urls: list[str] = []

        def get(self, url: str, **_kwargs: object) -> Response:
            self.urls.append(url)
            return Response()

    source_value = SourceConfig(
        source_id="tencent-campus", company_id="tencent", company_name="腾讯",
        source_url="https://join.qq.com/", apply_domain="careers.tencent.com",
        endpoint="https://careers.tencent.com/tencentcareer/api/post/Query",
        adapter="tencent_json", access_mode="JSON", campus_attr_ids=["2", "3", "5"],
        page_size=100, max_pages=1, request_interval_seconds=0,
    )
    client = Client()
    result = TencentCampusAdapter(client=client).fetch(source_value, tencent_json_parser)
    assert result.complete is True
    assert len(client.urls) == 3
    assert "attrId=1" not in " ".join(client.urls)
    assert {url.split("attrId=")[1].split("&")[0] for url in client.urls} == {"2", "3", "5"}


def test_company_coverage_prioritises_listed_large_employers(tmp_path: Path) -> None:
    report = build_coverage(Path("registry/companies.json"), Path("registry/sources.json"), tmp_path / "coverage.json")
    assert report["companyCount"] >= 50
    assert report["listedLargeCompanyCount"] >= 5
    assert report["rows"][0]["priorityBand"] == 0
    assert (tmp_path / "coverage.json").exists()


def test_generic_parser_keeps_missing_company_facts_unknown() -> None:
    source_value = source()
    parsed = generic_json_parser({"id": "x", "title": "校园产品", "applyUrl": "https://jobs.example.com/x"}, source_value)
    assert parsed.company_type == "未知"
    assert parsed.company_scale == "未知"


def test_public_json_adapter_rejects_unknown_response_envelope() -> None:
    class Response:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"message": "security challenge"}

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = PublicJsonAdapter(client=Client()).fetch(source(), "https://jobs.example.com/api", generic_json_parser)
    assert result.complete is False
    assert result.error == "incomplete_payload"


def test_release_gate_rejects_demo_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"isDemo": True, "sourceCount": 0, "verifiedSourceCount": 0}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="release_gate_demo_catalog"):
        validate_manifest(manifest, 0)


def test_release_gate_checks_catalog_completeness_and_https(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"isDemo": False, "sourceCount": 1, "verifiedSourceCount": 1}), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"jobs": [{"status": "ACTIVE", "title": "校园运营", "companyName": "企业", "city": "武汉", "roleCategory": "运营", "cohort": "2027", "batch": "秋招正式批", "education": "本科", "applyUrl": "https://jobs.example.com/apply", "sourceUrl": "https://jobs.example.com/campus"}]}), encoding="utf-8")
    result = validate_manifest(manifest, 1, catalog)
    assert result["completeness"] == 1


def test_release_gate_requires_complete_auto_verification_reports(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "isDemo": False,
        "sourceCount": 1,
        "verifiedSourceCount": 0,
        "autoVerifiedSourceCount": 1,
        "publishableSourceCount": 1,
        "autoVerificationReports": [{"sourceId": "auto-1", "conclusion": "AUTO_VERIFIED"}],
    }), encoding="utf-8")
    result = validate_manifest(manifest, 1)
    assert result["autoVerifiedSourceCount"] == 1

    invalid = json.loads(manifest.read_text(encoding="utf-8"))
    invalid["autoVerificationReports"][0]["conclusion"] = "PROVISIONAL"
    manifest.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(RuntimeError, match="release_gate_auto_verification_incomplete"):
        validate_manifest(manifest, 1)


def test_release_gate_revalidates_detail_shards_against_audience_policy(tmp_path: Path) -> None:
    normalized = normalize_job(job(), source())
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    detail = public_job({key: value for key, value in normalized.model_dump(mode="json").items()})
    detail["detailShard"] = "00"
    (jobs_dir / "00.json").write_text(json.dumps({"jobs": [detail]}, ensure_ascii=False), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"jobs": [
        {
            "id": normalized.id, "status": "ACTIVE", "title": normalized.title, "companyName": normalized.company_name,
            "city": normalized.city, "roleCategory": normalized.role_category, "cohort": normalized.cohort,
            "batch": normalized.batch, "education": normalized.education, "applyUrl": str(normalized.apply_url),
            "sourceUrl": str(normalized.source_url), "detailShard": "00",
        }
    ]}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"isDemo": False, "sourceCount": 1, "verifiedSourceCount": 1, "audiencePolicy": {"version": "humanities-social-business-v1"}}), encoding="utf-8")
    result = validate_manifest(manifest, 1, catalog, jobs_dir)
    assert result["audienceCheckedJobs"] == 1

    detail["title"] = "软件工程师"
    (jobs_dir / "00.json").write_text(json.dumps({"jobs": [detail]}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="release_gate_audience_policy"):
        validate_manifest(manifest, 1, catalog, jobs_dir)


def test_release_gate_revalidates_closed_public_records(tmp_path: Path) -> None:
    normalized = normalize_job(job(), source())
    active_normalized = normalize_job(job(source_job_id="2", title="运营专员"), source())
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    detail = public_job({key: value for key, value in normalized.model_dump(mode="json").items()})
    detail.update({"detailShard": "00", "status": "CLOSED", "title": "软件工程师"})
    active_detail = public_job({key: value for key, value in active_normalized.model_dump(mode="json").items()})
    active_detail["detailShard"] = "00"
    (jobs_dir / "00.json").write_text(json.dumps({"jobs": [detail, active_detail]}, ensure_ascii=False), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"jobs": [{
        "id": normalized.id, "status": "CLOSED", "title": "软件工程师", "companyName": normalized.company_name,
        "city": normalized.city, "roleCategory": normalized.role_category, "cohort": normalized.cohort,
        "batch": normalized.batch, "education": normalized.education, "applyUrl": str(normalized.apply_url),
        "sourceUrl": str(normalized.source_url), "detailShard": "00",
    }, {
        "id": active_normalized.id, "status": "ACTIVE", "title": active_normalized.title, "companyName": active_normalized.company_name,
        "city": active_normalized.city, "roleCategory": active_normalized.role_category, "cohort": active_normalized.cohort,
        "batch": active_normalized.batch, "education": active_normalized.education, "applyUrl": str(active_normalized.apply_url),
        "sourceUrl": str(active_normalized.source_url), "detailShard": "00",
    }]}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"isDemo": False, "sourceCount": 1, "verifiedSourceCount": 1,
                                    "audiencePolicy": {"version": "humanities-social-business-v1"}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="release_gate_audience_policy"):
        validate_manifest(manifest, 1, catalog, jobs_dir)


def test_release_gate_validates_separate_company_directory(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"isDemo": False, "sourceCount": 1, "verifiedSourceCount": 1}), encoding="utf-8")
    companies = tmp_path / "companies.json"
    companies.write_text(json.dumps({"companies": [{
        "id": "demo",
        "name": "演示企业",
        "sourceStatus": "TARGET",
        "directory": {
            "directoryStatus": "ACTIVE_LEAD",
            "entryType": "ENTRY_LEAD",
            "careerUrl": "https://careers.example.com/campus",
            "evidenceUrl": "https://careers.example.com/news",
        },
    }]}, ensure_ascii=False), encoding="utf-8")
    result = validate_manifest(manifest, 1, companies_path=companies)
    assert result["directoryCompanyCount"] == 1
    assert result["directoryEntryLeadCount"] == 1

    invalid = json.loads(companies.read_text(encoding="utf-8"))
    invalid["companies"][0]["directory"]["directoryStatus"] = "STALE"
    companies.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="release_gate_inactive_company_directory"):
        validate_manifest(manifest, 1, companies_path=companies)

    invalid["companies"][0]["directory"]["directoryStatus"] = "ACTIVE_LEAD"
    invalid["companies"][0]["directory"]["entryType"] = "ENTRY_LEAD"
    manifest.write_text(json.dumps({"isDemo": False, "sourceCount": 1, "verifiedSourceCount": 1, "companyDirectory": {"activeRecruitingCompanyCount": 2}}, ensure_ascii=False), encoding="utf-8")
    companies.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="release_gate_company_directory_summary"):
        validate_manifest(manifest, 1, companies_path=companies)


def test_workday_adapter_maps_public_campus_postings() -> None:
    class Response:
        status_code = 200
        content = json.dumps({"jobPostings": [{
            "title": "校园市场运营",
            "jobReqId": "wd-1",
            "externalPath": "/校园市场运营_WD-1",
            "locationsText": "上海市",
            "jobDescription": "参与校园市场活动与复盘。",
            "qualifications": "本科及以上，面向 2027 届毕业生。",
            "postedOn": "2026-09-08",
        }], "total": 1}).encode("utf-8")

    class Client:
        def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    source_value = SourceConfig(
        source_id="workday-campus", company_id="demo", company_name="演示企业",
        source_url="https://company.example.com/campus", apply_domain="example.com",
        endpoint="https://company.example.com/api", adapter="workday", access_mode="JSON",
        page_size=20, max_pages=2, request_interval_seconds=0,
    )
    result = WorkdayCampusAdapter(client=Client()).fetch(source_value)
    assert result.error is None
    assert result.jobs[0].title == "校园市场运营"
    assert result.jobs[0].apply_url.host == "company.example.com"
    assert result.jobs[0].publish_date_source == "OFFICIAL"


def test_greenhouse_and_lever_adapters_map_public_envelopes() -> None:
    class Response:
        status_code = 200
        content = json.dumps({"jobs": [{
            "id": "gh-1", "title": "校园内容运营", "absolute_url": "https://boards.example.com/jobs/gh-1",
            "location": {"name": "北京市"}, "content": "校园招聘，支持内容策划。", "updated_at": "2026-09-08T00:00:00Z",
        }, {
            "id": "social-1", "title": "社会招聘内容运营", "absolute_url": "https://boards.example.com/jobs/social-1",
            "location": {"name": "北京市"}, "content": "社会招聘岗位。",
        }]}).encode("utf-8")

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    greenhouse = SourceConfig(
        source_id="greenhouse-campus", company_id="demo", company_name="演示企业",
        source_url="https://boards.example.com/campus", apply_domain="example.com", apply_domains=["boards.example.com"],
        endpoint="https://boards.example.com/api", adapter="greenhouse", access_mode="JSON", request_interval_seconds=0,
    )
    lever = greenhouse.model_copy(update={"source_id": "lever-campus", "adapter": "lever"})
    greenhouse_result = GreenhouseCampusAdapter(client=Client()).fetch(greenhouse)
    assert greenhouse_result.jobs[0].title == "校园内容运营"
    assert len(greenhouse_result.jobs) == 1
    assert greenhouse_result.jobs[0].publish_date is None
    # Reuse the same fixture with Lever's permissive public shape to ensure
    # the adapter route is explicit and does not fall through to an unknown
    # parser.
    lever_result = LeverCampusAdapter(client=Client()).fetch(lever)
    assert lever_result.jobs[0].title == "校园内容运营"
    assert len(lever_result.jobs) == 1


def test_dom_adapter_requires_audited_selectors_and_maps_visible_rows() -> None:
    class Response:
        status_code = 200
        url = "https://company.example.com/campus"
        content = """
        <div class='job'><h2 class='title'>校园公关专员</h2><span class='city'>深圳市</span>
        <p class='desc'>参与校园传播与活动。</p><a class='apply' href='/apply/1'>申请</a></div>
        <div class='job' hidden><h2 class='title'>隐藏社会招聘岗位</h2><span class='city'>深圳市</span>
        <p class='desc'>社会招聘。</p><a class='apply' href='/apply/2'>申请</a></div>
        """.encode("utf-8")

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    source_value = SourceConfig(
        source_id="dom-campus", company_id="demo", company_name="演示企业",
        source_url="https://company.example.com/campus", apply_domain="example.com",
        adapter="dom", access_mode="DOM", dom_job_selector=".job",
        dom_field_selectors={"title": ".title", "city": ".city", "description": ".desc", "applyUrl": ".apply"},
        status="VERIFIED", verified_at=date(2026, 9, 8),
        robots_reviewed_at=date(2026, 9, 8), terms_reviewed_at=date(2026, 9, 8),
        request_interval_seconds=0,
    )
    result = DomCampusAdapter(client=Client()).fetch(source_value)
    assert result.error is None
    assert result.jobs[0].city == "深圳市"
    assert str(result.jobs[0].apply_url) == "https://company.example.com/apply/1"
    assert len(result.jobs) == 1
    assert source_can_run(source_value) == (True, "ready")
