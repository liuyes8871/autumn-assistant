from __future__ import annotations

"""Reviewed-source registry helpers used by the live collector.

The registry is intentionally data-only. A source is never considered live just
because it appears in the target list: it must be marked ``VERIFIED`` and have a
reviewed public endpoint/adapter before the scheduler is allowed to request it.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .normalize import host_matches
from .schema import CompanyConfig, RawJob, SourceConfig


def load_sources(path: Path) -> list[SourceConfig]:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("source registry must be a JSON array")
    aliases = {
        "sourceId": "source_id", "companyId": "company_id", "companyName": "company_name",
        "sourceUrl": "source_url", "applyDomain": "apply_domain", "sourceLevel": "source_level",
        "applyDomains": "apply_domains",
        "campusOnly": "campus_only", "verifiedAt": "verified_at", "evidenceUrls": "evidence_urls",
        "robotsReviewedAt": "robots_reviewed_at", "termsReviewedAt": "terms_reviewed_at",
        "accessMode": "access_mode",
        "atsHost": "ats_host", "websitePath": "website_path", "pageSize": "page_size",
        "maxPages": "max_pages", "requestIntervalSeconds": "request_interval_seconds",
        "campusMarkers": "campus_markers",
        "campusAttrIds": "campus_attr_ids",
        "allowedJobIds": "allowed_job_ids",
        "allowedTitleMarkers": "allowed_title_markers",
        "domJobSelector": "dom_job_selector",
        "domFieldSelectors": "dom_field_selectors",
        "feedType": "feed_type",
        "detectedAts": "detected_ats",
        "candidateEndpoint": "candidate_endpoint",
        "discoveryEvidenceUrls": "discovery_evidence_urls",
        "currentCohortSignal": "current_cohort_signal",
        "requiresManualReview": "requires_manual_review",
        "evidenceReport": "evidence_report",
        "autoVerifiedAt": "auto_verified_at",
        "locations": "locations",
    }
    normalized = [{aliases.get(key, key): value for key, value in item.items()} for item in values]
    return [SourceConfig.model_validate(value) for value in normalized]


def load_companies(path: Path) -> list[dict[str, Any]]:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("company registry must be a JSON array")
    return values


def load_company_configs(path: Path) -> list[CompanyConfig]:
    values = load_companies(path)
    return [CompanyConfig.model_validate(value) for value in values]


def load_focus_registry(path: Path | None) -> dict[str, Any]:
    """Load an optional, discovery-only company focus definition.

    Focus membership changes the order in which sources are discovered and
    reviewed. It never makes a source runnable and never bypasses the existing
    VERIFIED/robots/terms/endpoint gate.
    """

    if path is None or not path.exists():
        return {"schemaVersion": 1, "focusId": None, "companies": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("companies"), list):
        raise ValueError("focus registry must be an object with a companies array")
    if payload.get("mode", "PRIORITIZE") != "PRIORITIZE":
        raise ValueError("focus registry mode must be PRIORITIZE")
    company_ids = [str(item.get("companyId", "")) for item in payload["companies"] if isinstance(item, dict)]
    if not all(company_ids) or len(company_ids) != len(set(company_ids)):
        raise ValueError("focus registry company ids must be non-empty and unique")
    for item in payload["companies"]:
        if not isinstance(item, dict):
            raise ValueError("focus registry companies must be objects")
        priority = item.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int) or priority not in {0, 1, 2}:
            raise ValueError("focus registry priority must be 0, 1, or 2")
        if not str(item.get("segment", "")).strip():
            raise ValueError("focus registry segment cannot be empty")
    return payload


def focus_company_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["companyId"]): item
        for item in payload.get("companies", [])
        if isinstance(item, dict) and item.get("companyId")
    }


def source_can_run(source: SourceConfig) -> tuple[bool, str]:
    """Return a safe, explainable gate decision for one source."""

    if not source.enabled:
        return False, "disabled"
    if source.status not in {"VERIFIED", "AUTO_VERIFIED"}:
        return False, f"status_{source.status.lower()}"
    if source.status == "VERIFIED" and (not source.verified_at or not source.robots_reviewed_at or not source.terms_reviewed_at):
        return False, "source_review_dates_incomplete"
    adapter = source.adapter.lower()
    known_json_adapters = {
        # Existing reviewed first-party feeds and the public ATS adapters.
        # Keeping this list explicit lets a future source omit accessMode
        # safely while still preventing an arbitrary/manual adapter from
        # becoming runnable by accident.
        "baidu", "jd", "feishu", "tencent", "tencent_json",
        "ashby", "ashby_campus", "beisen", "beisen_campus", "beisen_modern", "beisen_bsglobal", "beisen_legacy", "beisen_campus_legacy", "italent", "wecruit",
        "workable", "workable_campus", "json", "json_api", "jsonld", "json_ld", "jobposting", "structured_html",
        "static_html", "html_table", "table", "static",
        "greenhouse", "greenhouse_campus",
        "lever", "lever_campus", "successfactors_json",
        "smartrecruiters", "smartrecruiters_campus", "personio", "personio_campus",
        "bamboohr", "bamboohr_campus", "breezy", "breezy_campus",
        "oracle", "oracle_campus", "icims", "icims_campus",
    }
    known_feed_adapters = {"teamtailor", "recruitee", "successfactors", "personio", "rss", "atom", "xml", "feed"}
    effective_mode = source.access_mode
    # Newly reviewed sources are often first written with an adapter and
    # endpoint before an operator fills in ``accessMode``.  Known public
    # adapters may use that explicit type safely; arbitrary/manual adapters
    # remain blocked until the registry is complete.
    if effective_mode == "UNKNOWN" and adapter in known_json_adapters:
        effective_mode = "JSON"
    elif effective_mode == "UNKNOWN" and adapter in known_feed_adapters:
        effective_mode = "XML"
    if effective_mode == "DOM":
        # HTML collection is deliberately opt-in.  A reviewed DOM source must
        # provide a stable job selector and use the dedicated parser; generic
        # TARGET/manual entries remain non-runnable.
        required_dom_fields = {"title", "applyUrl"}
        if (
            adapter not in {"dom", "html", "dom_campus"}
            or not source.dom_job_selector
            or not required_dom_fields.issubset(source.dom_field_selectors)
        ):
            return False, "adapter_requires_reviewed_dom_selectors"
    elif effective_mode == "HTML" and adapter not in {"dom", "html", "dom_campus", "static_html", "html_table", "table", "static", "icims", "icims_campus", "beisen_legacy", "beisen_campus_legacy"}:
        return False, "html_requires_reviewed_adapter"
    elif effective_mode in {"RSS", "XML"} and adapter not in known_feed_adapters:
        return False, "feed_requires_reviewed_adapter"
    elif effective_mode == "JSONLD" and adapter not in {"jsonld", "json_ld", "jobposting", "structured_html"}:
        return False, "jsonld_requires_reviewed_adapter"
    elif effective_mode == "SITEMAP" and adapter not in {"jsonld", "json_ld", "jobposting", "structured_html", "static_html", "html_table", "table", "static"}:
        return False, "sitemap_discovery_only"
    elif effective_mode not in {"JSON", "RSS", "XML", "HTML", "JSONLD", "SITEMAP"}:
        return False, "adapter_requires_reviewed_json_endpoint"
    source_scheme = urlparse(str(source.source_url)).scheme.lower()
    if source_scheme != "https":
        return False, "source_url_requires_https"
    if adapter == "feishu":
        endpoint_host = (source.ats_host or urlparse(str(source.source_url)).hostname or "").lower()
        # ByteDance's campus portal uses the same public Hire API contract but
        # is hosted on the company's own jobs.bytedance.com domain. Keep this
        # exception explicit rather than accepting arbitrary hosts.
        if not endpoint_host.endswith(".jobs.feishu.cn") and endpoint_host != "jobs.bytedance.com":
            return False, "invalid_feishu_host"
    elif source.endpoint:
        endpoint_host = (urlparse(str(source.endpoint)).hostname or "").lower()
    elif effective_mode == "DOM":
        endpoint_host = (urlparse(str(source.source_url)).hostname or "").lower()
    else:
        return False, "endpoint_not_configured"
    # A reviewed source may expose the public listing endpoint from a vendor
    # host while the application itself lives on a first-party host.  Honour
    # the explicit ``applyDomains`` allow-list when present, but never infer
    # additional domains from redirects or response content.
    # ``ats_host`` is an explicit, reviewed vendor host (for example
    # api.ashbyhq.com) and is allowed in addition to the first-party
    # application domains.  It is never inferred from redirects or response
    # content.
    allowed_domains = [source.apply_domain, *source.apply_domains, *([source.ats_host] if source.ats_host else [])]
    if source.endpoint and urlparse(str(source.endpoint)).scheme.lower() != "https":
        return False, "endpoint_requires_https"
    if not endpoint_host or not any(host_matches(endpoint_host, domain) for domain in allowed_domains):
        return False, "endpoint_domain_not_allowed"
    if source.status == "AUTO_VERIFIED":
        report = source.evidence_report
        if report is None:
            return False, "auto_evidence_report_missing"
        if report.conclusion != "AUTO_VERIFIED":
            return False, f"auto_evidence_{report.conclusion.lower()}"
        if adapter in {"moka", "boss", "boss_zhipin", "manual", "manual_or_ats", "provisional_html"}:
            return False, "auto_adapter_not_allowlisted"
        checks = (
            (report.official_reverse_link, "official_reverse_link_missing"),
            (report.public_access_no_auth, "public_access_requires_auth"),
            (report.robots_terms_allowed, "robots_terms_not_reviewed"),
            (report.current_cohort_evidence, "current_cohort_evidence_missing"),
            (report.campus_evidence, "campus_evidence_missing"),
            (report.company_identity_exact, "company_identity_not_exact"),
            (report.apply_domain_verified, "apply_domain_not_verified"),
        )
        for passed, reason in checks:
            if not passed:
                return False, reason
        if report.sampled_jobs < 3:
            return False, "auto_sample_count_insufficient"
        if report.required_field_completeness < 1.0:
            return False, "auto_required_fields_incomplete"
        if report.invalid_row_ratio > 0.05:
            return False, "auto_invalid_row_ratio_too_high"
        if report.duplicate_ratio > 0.05:
            return False, "auto_duplicate_ratio_too_high"
        if report.anomalous_drop:
            return False, "auto_anomalous_job_count_drop"
        if report.consecutive_healthy_runs < 2:
            return False, "auto_health_runs_insufficient"
    return True, "ready"


def company_priority(company: CompanyConfig) -> tuple[int, int, str]:
    """Sort listed employers with 500+ employees first, without guessing facts."""

    listed = company.listing_status == "LISTED"
    large = (company.employee_count is not None and company.employee_count >= 500) or company.scale in {"500–999", "1000–9999", "10000+"}
    priority_band = 0 if listed and large else 1 if large else 2 if listed else 3
    return (priority_band, -(company.employee_count or 0), company.name)


def focused_company_priority(
    company: CompanyConfig,
    focused_companies: dict[str, dict[str, Any]],
) -> tuple[int, int, int, int, str]:
    """Put the current product focus first, then retain the evidence ranking."""

    focus = focused_companies.get(company.id)
    if focus:
        focus_priority = int(focus.get("priority", 99))
        return (0, focus_priority, *company_priority(company))
    return (1, 99, *company_priority(company))


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _normalize_location_items(value: Any) -> list[dict[str, Any]]:
    """Accept the common snake_case/camelCase public ATS location shapes.

    The collector never invents a hierarchy here. It only renames fields so
    ``normalize_locations`` can apply the deterministic geography dictionary
    later; raw source text is preserved for auditability.
    """

    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    result: list[dict[str, Any]] = []
    for entry in values:
        if isinstance(entry, str):
            result.append({"display_name": entry, "raw": entry})
            continue
        if not isinstance(entry, dict):
            continue
        mapped = {
            "scope": entry.get("scope") or entry.get("locationScope"),
            "country_code": entry.get("country_code") or entry.get("countryCode"),
            "province_code": entry.get("province_code") or entry.get("provinceCode"),
            "city_code": entry.get("city_code") or entry.get("cityCode"),
            "district_code": entry.get("district_code") or entry.get("districtCode"),
            "display_name": entry.get("display_name") or entry.get("displayName") or entry.get("city") or entry.get("name"),
            "raw": entry.get("raw") or entry.get("display_name") or entry.get("displayName") or entry.get("city") or entry.get("name"),
        }
        if mapped["display_name"]:
            result.append({key: item for key, item in mapped.items() if item not in (None, "")})
    return result


def generic_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    """Map common public JSON field names without guessing missing facts."""

    apply_url = _first(item, "apply_url", "applyUrl", "applicationUrl", "url", "jobUrl")
    source_url = _first(item, "source_url", "sourceUrl") or str(source.source_url)
    source_job_id = _first(item, "source_job_id", "sourceJobId", "job_id", "jobId", "id")
    raw_locations = _first(item, "locations", "jobLocations")
    raw_city = _first(item, "city", "location", "workCity") or "未知"
    if isinstance(raw_city, (dict, list)):
        raw_locations = raw_locations or raw_city
        raw_city = "未知"
    payload: dict[str, Any] = {
        "source_id": source.source_id,
        "source_job_id": str(source_job_id) if source_job_id is not None else None,
        "company_id": source.company_id,
        "company_name": _first(item, "company_name", "companyName") or source.company_name,
        "title": _first(item, "title", "job_title", "jobTitle") or "",
        "city": raw_city,
        "locations": _normalize_location_items(raw_locations),
        "role_category": _first(item, "role_category", "roleCategory", "category") or "其他",
        "company_industry": _first(item, "company_industry", "companyIndustry") or "未知",
        "company_type": _first(item, "company_type", "companyType") or "未知",
        "company_scale": _first(item, "company_scale", "companyScale") or "未知",
        "cohort": _first(item, "cohort", "graduationYear", "graduateYear") or "未知",
        "batch": _first(item, "batch", "recruitmentBatch") or "未知",
        "education": _first(item, "education", "educationRequirement", "degree") or "未知",
        "major_tags": _first(item, "major_tags", "majorTags", "majors") or [],
        "skills": _first(item, "skills", "keywords", "tags") or [],
        "description": _first(item, "description", "jobDescription", "detail") or "",
        "requirements": _first(item, "requirements", "qualifications", "requirementsText") or [],
        "publish_date": _first(item, "publish_date", "publishDate", "postedAt"),
        "publish_date_source": _first(item, "publish_date_source", "publishDateSource") or "UNKNOWN",
        "deadline": _first(item, "deadline", "closingDate", "applicationDeadline"),
        "apply_url": apply_url,
        "source_url": source_url,
        "source_name": source.company_name + "官方校招来源",
        "source_level": source.source_level,
        "source_evidence": [str(source.source_url), *[str(value) for value in source.evidence_urls]],
        "is_campus": _first(item, "is_campus", "isCampus", "campus") if any(key in item for key in ("is_campus", "isCampus", "campus")) else None,
        "campaign_id": _first(item, "campaign_id", "campaignId"),
        "campaign_name": _first(item, "campaign_name", "campaignName"),
        "campaign_open_date": _first(item, "campaign_open_date", "campaignOpenDate", "openDate"),
        "campaign_deadline": _first(item, "campaign_deadline", "campaignDeadline"),
        "campaign_official_url": _first(item, "campaign_official_url", "campaignOfficialUrl") or source_url,
    }
    return RawJob.model_validate(payload)


def tencent_json_parser(item: dict[str, Any], source: SourceConfig) -> RawJob:
    """Normalize Tencent's documented public career JSON shape.

    ``LastUpdateTime`` is deliberately not treated as an official publication
    date; Tencent's endpoint exposes it as an update timestamp. The caller must
    still verify the campaign and campus scope before changing a source to
    ``VERIFIED``.
    """

    location = _first(item, "LocationName", "location", "city") or "未知"
    apply_url = _first(item, "PostURL", "url", "applyUrl")
    if isinstance(apply_url, str) and apply_url.startswith("http://careers.tencent.com/"):
        apply_url = "https://" + apply_url.removeprefix("http://")
    responsibility = _first(item, "Responsibility", "responsibility") or ""
    requirement = _first(item, "Requirement", "requirement") or ""
    text = "\n".join(value for value in (responsibility, requirement) if value)
    source_job_id = _first(item, "PostId", "postId", "id")
    return RawJob.model_validate({
        "source_id": source.source_id,
        "source_job_id": str(source_job_id) if source_job_id is not None else None,
        "company_id": source.company_id,
        "company_name": source.company_name,
        "title": _first(item, "RecruitPostName", "title") or "",
        "city": location,
        "role_category": _first(item, "CategoryName", "category", "BGName") or "其他",
        "description": text,
        "requirements": [],
        "publish_date": None,
        "publish_date_source": "UNKNOWN",
        "deadline": None,
        "apply_url": apply_url,
        "source_url": str(source.source_url),
        "source_name": source.company_name + "官方校招来源",
        "source_level": source.source_level,
        "source_evidence": [str(source.source_url), *[str(value) for value in source.evidence_urls]],
        "is_campus": True,
    })


def parser_for_source(source: SourceConfig):
    if (source.parser or source.adapter).lower().startswith("tencent"):
        return tencent_json_parser
    return generic_json_parser


def public_source_record(
    source: SourceConfig,
    *,
    health: str,
    reason: str | None = None,
    job_count: int = 0,
    fetched_job_count: int | None = None,
    eligible_job_count: int = 0,
    excluded_job_count: int = 0,
    review_job_count: int = 0,
    fetched_at: str | None = None,
    not_modified: bool = False,
    content_hash: str | None = None,
    raw_count: int | None = None,
    unique_count: int | None = None,
    duplicate_ratio: float | None = None,
    field_completeness: float | None = None,
    detail_success_rate: float | None = None,
    unknown_cohort_ratio: float | None = None,
    freshness_days: float | None = None,
) -> dict[str, Any]:
    """Strip internal request details before exposing source health in Pages."""

    record = {
        "sourceId": source.source_id,
        "companyId": source.company_id,
        "companyName": source.company_name,
        "sourceUrl": str(source.source_url),
        "sourceLevel": source.source_level.value,
        "status": source.status,
        "health": health,
        "adapter": source.adapter,
        "accessMode": source.access_mode,
        "verifiedAt": source.verified_at.isoformat() if source.verified_at else None,
        "robotsReviewedAt": source.robots_reviewed_at.isoformat() if source.robots_reviewed_at else None,
        "termsReviewedAt": source.terms_reviewed_at.isoformat() if source.terms_reviewed_at else None,
        "jobCount": job_count,
        "fetchedJobCount": fetched_job_count if fetched_job_count is not None else job_count,
        "eligibleJobCount": eligible_job_count,
        "excludedJobCount": excluded_job_count,
        "reviewJobCount": review_job_count,
        "fetchedAt": fetched_at,
        "notModified": bool(not_modified),
    }
    if source.evidence_report is not None:
        evidence = source.evidence_report
        record["autoVerification"] = {
            "conclusion": evidence.conclusion,
            "atsType": evidence.ats_type,
            "tenant": evidence.tenant,
            "sampledJobs": evidence.sampled_jobs,
            "requiredFieldCompleteness": evidence.required_field_completeness,
            "invalidRowRatio": evidence.invalid_row_ratio,
            "duplicateRatio": evidence.duplicate_ratio,
            "consecutiveHealthyRuns": evidence.consecutive_healthy_runs,
            "anomalousDrop": evidence.anomalous_drop,
            "failureReasons": list(evidence.failure_reasons),
            "checkedAt": evidence.checked_at.isoformat() if evidence.checked_at else None,
        }
    for key, value in (
        ("contentHash", content_hash),
        ("rawCount", raw_count),
        ("uniqueCount", unique_count),
        ("duplicateRatio", duplicate_ratio),
        ("fieldCompleteness", field_completeness),
        ("detailSuccessRate", detail_success_rate),
        ("unknownCohortRatio", unknown_cohort_ratio),
        ("freshnessDays", freshness_days),
    ):
        if value is not None:
            record[key] = value
    if reason:
        record["reason"] = reason
    return record
