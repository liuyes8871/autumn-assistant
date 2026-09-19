from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class SourceLevel(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    DEMO = "DEMO"


class JobStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    QUARANTINED = "QUARANTINED"


class LocationScope(StrEnum):
    MAINLAND_CHINA = "MAINLAND_CHINA"
    HONG_KONG_MACAU_TAIWAN = "HONG_KONG_MACAU_TAIWAN"
    OVERSEAS = "OVERSEAS"
    REMOTE = "REMOTE"
    UNKNOWN = "UNKNOWN"


class JobLocation(BaseModel):
    scope: LocationScope = LocationScope.UNKNOWN
    country_code: str | None = None
    province_code: str | None = None
    city_code: str | None = None
    district_code: str | None = None
    display_name: str
    raw: str


class SourceEvidenceReport(BaseModel):
    """Machine-readable evidence used by the automatic source gate.

    This is intentionally an internal contract.  It records *why* a public
    connector is safe to run, but it never contains cookies, tokens, response
    bodies or other session data.  A registry row can only become
    ``AUTO_VERIFIED`` when the report says that every required check passed.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    upstream_project: str | None = Field(default=None, alias="upstreamProject")
    upstream_commit: str | None = Field(default=None, alias="upstreamCommit")
    license: str | None = None
    ats_type: str | None = Field(default=None, alias="atsType")
    tenant: str | None = None
    endpoint: HttpUrl | None = None
    official_reverse_link: bool = Field(default=False, alias="officialReverseLink")
    official_reverse_link_url: HttpUrl | None = Field(default=None, alias="officialReverseLinkUrl")
    public_access_no_auth: bool = Field(default=False, alias="publicAccessNoAuth")
    robots_terms_allowed: bool = Field(default=False, alias="robotsTermsAllowed")
    current_cohort_evidence: bool = Field(default=False, alias="currentCohortEvidence")
    campus_evidence: bool = Field(default=False, alias="campusEvidence")
    company_identity_exact: bool = Field(default=False, alias="companyIdentityExact")
    apply_domain_verified: bool = Field(default=False, alias="applyDomainVerified")
    sampled_jobs: int = Field(default=0, ge=0, alias="sampledJobs")
    required_field_completeness: float = Field(default=0.0, ge=0.0, le=1.0, alias="requiredFieldCompleteness")
    invalid_row_ratio: float = Field(default=1.0, ge=0.0, le=1.0, alias="invalidRowRatio")
    duplicate_ratio: float = Field(default=1.0, ge=0.0, le=1.0, alias="duplicateRatio")
    consecutive_healthy_runs: int = Field(default=0, ge=0, alias="consecutiveHealthyRuns")
    anomalous_drop: bool = Field(default=False, alias="anomalousDrop")
    conclusion: Literal["AUTO_VERIFIED", "PROVISIONAL", "QUARANTINED", "BLOCKED"] = "PROVISIONAL"
    failure_reasons: list[str] = Field(default_factory=list, alias="failureReasons")
    checked_at: datetime | None = Field(default=None, alias="checkedAt")


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source_id: str
    company_id: str
    company_name: str
    source_url: HttpUrl
    apply_domain: str
    apply_domains: list[str] = Field(default_factory=list)
    source_level: SourceLevel = SourceLevel.A
    campus_only: bool = True
    adapter: str = "manual"
    enabled: bool = True
    verified_at: date | None = None
    note: str | None = None
    status: Literal["TARGET", "AUTO_VERIFIED", "VERIFIED", "QUARANTINED", "BLOCKED", "REPLACED", "STALE"] = "TARGET"
    evidence_urls: list[HttpUrl] = Field(default_factory=list)
    robots_reviewed_at: date | None = None
    terms_reviewed_at: date | None = None
    # Public, unauthenticated source transports.  RSS/XML/HTML are kept
    # separate from JSON so a discovery result can explain exactly which
    # parser is expected to run; MANUAL/UNKNOWN remain non-runnable until a
    # human completes the source review.
    access_mode: Literal["JSON", "DOM", "RSS", "XML", "HTML", "JSONLD", "SITEMAP", "MANUAL", "UNKNOWN"] = "UNKNOWN"
    endpoint: HttpUrl | None = None
    parser: str | None = None
    ats_host: str | None = None
    website_path: str | None = None
    feed_type: Literal["RSS", "ATOM", "XML", "JSON", "HTML", "JSONLD"] | None = None
    # Discovery metadata is intentionally optional and never makes a source
    # runnable.  It is populated by the candidate report only after a public
    # landing page has been inspected; registry promotion still requires the
    # existing VERIFIED/robots/terms gate.
    detected_ats: str | None = None
    candidate_endpoint: HttpUrl | None = None
    discovery_evidence_urls: list[HttpUrl] = Field(default_factory=list)
    current_cohort_signal: str | None = None
    requires_manual_review: bool = True
    evidence_report: SourceEvidenceReport | None = Field(default=None, alias="evidenceReport")
    auto_verified_at: date | None = Field(default=None, alias="autoVerifiedAt")
    page_size: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=8, ge=1, le=30)
    request_interval_seconds: float = Field(default=0.35, ge=0.0, le=5.0)
    campus_markers: list[str] = Field(default_factory=list)
    campus_attr_ids: list[str] = Field(default_factory=lambda: ["2", "3", "5"])
    # Some public ATS boards combine campus and experienced-hire postings. An
    # explicitly reviewed allow-list lets a source expose only the audited
    # cohort/roles without guessing from a title or importing the whole board.
    # These fields are source configuration, not part of the public job
    # contract, and remain optional for existing sources.
    allowed_job_ids: list[str] = Field(default_factory=list)
    allowed_title_markers: list[str] = Field(default_factory=list)
    # DOM adapters remain opt-in and require an audited selector map.  Keeping
    # these fields in the source contract lets a future official page be
    # enabled without scraping arbitrary HTML or executing page scripts.
    dom_job_selector: str | None = None
    dom_field_selectors: dict[str, str] = Field(default_factory=dict)


class CompanyDirectoryStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    ACTIVE_CONFIRMED = "ACTIVE_CONFIRMED"
    ACTIVE_LEAD = "ACTIVE_LEAD"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"
    STALE = "STALE"


class CareerEntryType(StrEnum):
    OFFICIAL_CAREER_SITE = "OFFICIAL_CAREER_SITE"
    OFFICIAL_ATS = "OFFICIAL_ATS"
    OFFICIAL_CAMPAIGN_PAGE = "OFFICIAL_CAMPAIGN_PAGE"
    ENTRY_LEAD = "ENTRY_LEAD"


class CampusRecruitmentEntry(BaseModel):
    """Current-cohort company entry, separate from runnable job sources."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    company_id: str = Field(alias="companyId")
    cohort: str
    directory_status: CompanyDirectoryStatus = Field(alias="directoryStatus")
    entry_type: CareerEntryType = Field(alias="entryType")
    career_url: HttpUrl = Field(alias="careerUrl")
    evidence_url: HttpUrl = Field(alias="evidenceUrl")
    evidence_text: str = Field(alias="evidenceText")
    detected_signals: list[str] = Field(default_factory=list, alias="detectedSignals")
    directory_source: str = Field(alias="directorySource")
    directory_rank: int | None = Field(default=None, alias="directoryRank")
    first_confirmed_at: datetime | None = Field(default=None, alias="firstConfirmedAt")
    last_checked_at: datetime = Field(alias="lastCheckedAt")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")


class CompanyConfig(BaseModel):
    """Audited company facts used for prioritisation and catalog enrichment."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str
    industry: str = "未知"
    type: str = "未知"
    scale: str = "未知"
    source_status: Literal["TARGET", "AUTO_VERIFIED", "VERIFIED", "QUARANTINED", "BLOCKED", "REPLACED", "STALE"] = Field(default="TARGET", alias="sourceStatus")
    listing_status: Literal["LISTED", "UNLISTED", "UNKNOWN"] = Field(default="UNKNOWN", alias="listingStatus")
    stock_codes: list[str] = Field(default_factory=list, alias="stockCodes")
    employee_count: int | None = Field(default=None, ge=0, alias="employeeCount")
    listing_evidence_urls: list[HttpUrl] = Field(default_factory=list, alias="listingEvidenceUrls")
    employee_evidence_urls: list[HttpUrl] = Field(default_factory=list, alias="employeeEvidenceUrls")
    career_url: HttpUrl | None = Field(default=None, alias="careerUrl")
    verified_at: date | None = Field(default=None, alias="verifiedAt")
    aliases: list[str] = Field(default_factory=list)
    directory: CampusRecruitmentEntry | None = None


class RawJob(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_id: str | None = None
    source_job_id: str | None = None
    company_id: str
    company_name: str
    title: str
    city: str = "未知"
    locations: list[JobLocation] = Field(default_factory=list)
    role_category: str = "其他"
    company_industry: str = "未知"
    company_type: str = "未知"
    company_scale: str = "未知"
    cohort: str = "未知"
    batch: str = "未知"
    education: str = "未知"
    major_tags: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    publish_date: date | None = None
    publish_date_source: Literal["OFFICIAL", "UNKNOWN", "DEMO"] = "UNKNOWN"
    deadline: date | None = None
    apply_url: HttpUrl
    source_url: HttpUrl
    source_name: str
    source_level: SourceLevel = SourceLevel.A
    source_evidence: list[str] = Field(default_factory=list)
    is_campus: bool | None = None
    campaign_id: str | None = None
    campaign_name: str | None = None
    campaign_open_date: date | None = None
    campaign_deadline: date | None = None
    campaign_official_url: HttpUrl | None = None

    @field_validator("title", "company_name")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title/company_name cannot be empty")
        return value


class NormalizedJob(RawJob):
    model_config = ConfigDict(extra="ignore")

    id: str
    first_seen_at: datetime
    last_verified_at: datetime
    content_hash: str
    status: JobStatus = JobStatus.ACTIVE
    detail_shard: str = "00"
    first_missing_successes: int = 0
    changed_at: datetime | None = None
    # Persist the deterministic audience decision alongside the snapshot so a
    # later audit can explain why a job was published without reusing mutable
    # presentation text. The public catalog keeps these fields in the detail
    # shard rather than the lightweight list summary.
    audience_decision: str | None = None
    audience_reason_codes: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    accepted: int = 0
    rejected: int = 0
    quarantined: bool = False
    reasons: list[str] = Field(default_factory=list)
    source_id: str | None = None
    fetched_at: datetime | None = None
    fetch_complete: bool = True
    raw_count: int = 0
    unique_count: int = 0
    duplicate_count: int = 0
    duplicate_ratio: float = 0.0
    field_completeness: float = 0.0
    unknown_cohort_ratio: float = 0.0
    baseline_count: int | None = None
    baseline_source: str | None = None
    freshness_days: float | None = None


class DiscoveryCandidate(BaseModel):
    """A discovery-only ATS/feed candidate.

    This contract deliberately lives beside, rather than inside, the public
    job schema.  A candidate is evidence for an operator and cannot be
    published until the source registry is independently reviewed.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source_id: str = Field(alias="sourceId")
    company_id: str = Field(alias="companyId")
    company_name: str = Field(alias="companyName")
    landing_url: HttpUrl = Field(alias="landingUrl")
    detected_ats: str | None = Field(default=None, alias="detectedAts")
    confidence: Literal["HIGH", "MEDIUM", "LOW", "NONE"] = "NONE"
    tenant: str | None = None
    candidate_endpoint: HttpUrl | None = Field(default=None, alias="candidateEndpoint")
    candidate_endpoints: list[HttpUrl] = Field(default_factory=list, alias="candidateEndpoints")
    evidence_urls: list[HttpUrl] = Field(default_factory=list, alias="evidenceUrls")
    current_cohort_signal: str | None = Field(default=None, alias="currentCohortSignal")
    structured_job_count: int = Field(default=0, alias="structuredJobCount")
    visible_table_row_count: int = Field(default=0, alias="visibleTableRowCount")
    field_completeness: float = Field(default=0.0, alias="fieldCompleteness", ge=0.0, le=1.0)
    feed_links: list[HttpUrl] = Field(default_factory=list, alias="feedLinks")
    sitemap_links: list[HttpUrl] = Field(default_factory=list, alias="sitemapLinks")
    classification: Literal[
        "CONNECTOR_CANDIDATE",
        "NEEDS_MANUAL_REVIEW",
        "MANUAL_IMPORT_ONLY",
        "PUBLIC_ACCESS_UNAVAILABLE",
    ] = "MANUAL_IMPORT_ONLY"
    classification_reason: str | None = Field(default=None, alias="classificationReason")
    status_code: int | None = Field(default=None, alias="statusCode")
    content_type: str | None = Field(default=None, alias="contentType")
    reachable: bool = False
    blocked: bool = False
    requires_manual_review: bool = Field(default=True, alias="requiresManualReview")
    review_reasons: list[str] = Field(default_factory=list, alias="reviewReasons")
    checked_at: datetime = Field(alias="checkedAt")


class SourceHealth(BaseModel):
    """Operational metrics kept separate from source identity and job data."""

    source_id: str
    status: Literal["healthy", "not_modified", "stale", "blocked", "quarantined", "error", "not_ready"]
    fetched_at: datetime | None = None
    raw_count: int = 0
    unique_count: int = 0
    duplicate_ratio: float = 0.0
    field_completeness: float = 0.0
    detail_success_rate: float | None = None
    unknown_cohort_ratio: float = 0.0
    freshness_days: float | None = None
    content_hash: str | None = None
    not_modified: bool = False
    reason: str | None = None


def model_json(model: BaseModel) -> dict[str, Any]:
    """Serialize with JSON-compatible date/URL values."""

    return model.model_dump(mode="json")


def __getattr__(name: str) -> Any:
    """Lazy compatibility export for the discovery-only state-owned model."""

    if name == "StateOwnedCompanyCandidate":
        from .state_owned import StateOwnedCompanyCandidate

        return StateOwnedCompanyCandidate
    raise AttributeError(name)
