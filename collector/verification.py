from __future__ import annotations

"""Automatic evidence checks for public, unauthenticated job sources.

The collector intentionally keeps this module deterministic and network-free.
Discovery/fetch jobs provide the observations; this module turns those
observations into a small evidence report and a safe status recommendation.
It never promotes a registry row by itself and it never treats an ATS tenant
list or a BOSS search result as official evidence.
"""

from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.parse import urlparse

from .schema import SourceConfig, SourceEvidenceReport


PUBLIC_CONNECTOR_ALLOWLIST: frozenset[str] = frozenset({
    "feishu", "tencent", "tencent_json", "baidu", "jd",
    "beisen", "beisen_campus", "beisen_modern", "beisen_bsglobal", "beisen_legacy", "beisen_campus_legacy", "italent", "wecruit",
    "workday", "workday_campus", "greenhouse", "greenhouse_campus", "lever", "lever_campus",
    "ashby", "ashby_campus", "workable", "workable_campus", "teamtailor", "recruitee",
    "successfactors", "successfactors_json", "smartrecruiters", "smartrecruiters_campus", "personio", "personio_campus",
    "bamboohr", "bamboohr_campus", "breezy", "breezy_campus", "oracle", "oracle_campus",
    "icims", "icims_campus", "rss", "atom", "xml", "feed", "json", "json_api",
    "jsonld", "json_ld", "jobposting", "structured_html", "static_html", "html_table", "table", "static",
})


def _ratio(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def evaluate_evidence(source: SourceConfig, report: SourceEvidenceReport) -> tuple[str, list[str]]:
    """Return ``(conclusion, reasons)`` without mutating ``source``.

    The checks mirror the source gate.  Keeping one pure implementation makes
    scheduled runs, CLI reports and unit tests agree about what
    ``AUTO_VERIFIED`` means.
    """

    reasons: list[str] = []
    adapter = source.adapter.casefold()
    if adapter not in PUBLIC_CONNECTOR_ALLOWLIST:
        reasons.append("adapter_not_allowlisted")
    if adapter in {"moka", "manual", "manual_or_ats", "boss", "boss_zhipin", "provisional_html"}:
        reasons.append("manual_or_blocked_connector")
    if urlparse(str(source.source_url)).scheme.casefold() != "https":
        reasons.append("source_url_requires_https")
    if source.endpoint and urlparse(str(source.endpoint)).scheme.casefold() != "https":
        reasons.append("endpoint_requires_https")
    checks = (
        (report.official_reverse_link, "official_reverse_link_missing"),
        (report.public_access_no_auth, "public_access_requires_auth"),
        (report.robots_terms_allowed, "robots_terms_not_reviewed"),
        (report.current_cohort_evidence, "current_cohort_evidence_missing"),
        (report.campus_evidence, "campus_evidence_missing"),
        (report.company_identity_exact, "company_identity_not_exact"),
        (report.apply_domain_verified, "apply_domain_not_verified"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    if report.sampled_jobs < 3:
        reasons.append("sample_count_insufficient")
    if report.required_field_completeness < 1.0:
        reasons.append("required_fields_incomplete")
    if report.invalid_row_ratio > 0.05:
        reasons.append("invalid_row_ratio_too_high")
    if report.duplicate_ratio > 0.05:
        reasons.append("duplicate_ratio_too_high")
    if report.anomalous_drop:
        reasons.append("anomalous_job_count_drop")
    if report.consecutive_healthy_runs < 2:
        reasons.append("healthy_runs_insufficient")
    if reasons:
        return ("BLOCKED" if any(reason in {"manual_or_blocked_connector", "source_url_requires_https", "endpoint_requires_https"} for reason in reasons) else "PROVISIONAL", sorted(set(reasons)))
    return "AUTO_VERIFIED", []


def build_evidence_report(
    source: SourceConfig,
    *,
    sampled_jobs: int,
    required_field_completeness: float,
    invalid_row_ratio: float,
    duplicate_ratio: float,
    consecutive_healthy_runs: int,
    anomalous_drop: bool = False,
    official_reverse_link: bool,
    public_access_no_auth: bool,
    robots_terms_allowed: bool,
    current_cohort_evidence: bool,
    campus_evidence: bool,
    company_identity_exact: bool,
    apply_domain_verified: bool,
    official_reverse_link_url: str | None = None,
    checked_at: datetime | None = None,
) -> SourceEvidenceReport:
    """Build and evaluate one report from already-collected observations."""

    report = SourceEvidenceReport.model_validate({
        "atsType": source.detected_ats or source.adapter,
        "tenant": source.ats_host,
        "endpoint": str(source.endpoint) if source.endpoint else None,
        "officialReverseLink": official_reverse_link,
        "officialReverseLinkUrl": official_reverse_link_url,
        "publicAccessNoAuth": public_access_no_auth,
        "robotsTermsAllowed": robots_terms_allowed,
        "currentCohortEvidence": current_cohort_evidence,
        "campusEvidence": campus_evidence,
        "companyIdentityExact": company_identity_exact,
        "applyDomainVerified": apply_domain_verified,
        "sampledJobs": max(0, int(sampled_jobs)),
        "requiredFieldCompleteness": _ratio(required_field_completeness, 0.0),
        "invalidRowRatio": _ratio(invalid_row_ratio, 1.0),
        "duplicateRatio": _ratio(duplicate_ratio, 1.0),
        "consecutiveHealthyRuns": max(0, int(consecutive_healthy_runs)),
        "anomalousDrop": bool(anomalous_drop),
        "checkedAt": (checked_at or datetime.now(UTC)).isoformat(),
    })
    conclusion, reasons = evaluate_evidence(source, report)
    return report.model_copy(update={"conclusion": conclusion, "failure_reasons": reasons})


def auto_verification_summary(sources: Iterable[SourceConfig]) -> dict[str, int]:
    """Return registry-level counts for operator reports."""

    values = list(sources)
    return {
        "sourceCount": len(values),
        "verifiedSourceCount": sum(1 for source in values if source.status == "VERIFIED"),
        "autoVerifiedSourceCount": sum(1 for source in values if source.status == "AUTO_VERIFIED"),
        "provisionalSourceCount": sum(1 for source in values if source.evidence_report and source.evidence_report.conclusion == "PROVISIONAL"),
        "quarantinedSourceCount": sum(1 for source in values if source.status == "QUARANTINED"),
        "blockedSourceCount": sum(1 for source in values if source.status == "BLOCKED"),
    }
