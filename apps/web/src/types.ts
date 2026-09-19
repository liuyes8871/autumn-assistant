export type Interest = "UNSET" | "SUITABLE" | "UNSUITABLE";

export type Stage =
  | "NOT_APPLIED"
  | "APPLIED"
  | "SCREENING"
  | "ASSESSMENT"
  | "INTERVIEW"
  | "OFFER"
  | "REJECTED"
  | "WITHDRAWN";

export type JobStatus = "ACTIVE" | "CLOSED" | "QUARANTINED";
export type SourceLevel = "A" | "B" | "C" | "DEMO";
export type DateSource = "OFFICIAL" | "UNKNOWN" | "DEMO";
export type CampaignStatus = "OPEN" | "CLOSED" | "UNKNOWN";
export type SourceStatus = "TARGET" | "AUTO_VERIFIED" | "VERIFIED" | "QUARANTINED" | "BLOCKED" | "REPLACED" | "STALE";

/** Company-directory visibility is intentionally separate from job-source health. */
export type CompanyDirectoryStatus =
  | "DISCOVERED"
  | "ACTIVE_CONFIRMED"
  | "ACTIVE_LEAD"
  | "INACTIVE"
  | "BLOCKED"
  | "STALE";

export type CareerEntryType =
  | "OFFICIAL_CAREER_SITE"
  | "OFFICIAL_ATS"
  | "OFFICIAL_CAMPAIGN_PAGE"
  | "ENTRY_LEAD";

export type LocationScope = "MAINLAND_CHINA" | "HONG_KONG_MACAU_TAIWAN" | "OVERSEAS" | "REMOTE" | "UNKNOWN";

export interface JobLocation {
  scope: LocationScope;
  countryCode?: string;
  provinceCode?: string;
  cityCode?: string;
  districtCode?: string;
  displayName: string;
  raw: string;
}

export const INTEREST_LABELS: Record<Interest, string> = {
  UNSET: "未判断",
  SUITABLE: "合适",
  UNSUITABLE: "不合适"
};

export const STAGE_LABELS: Record<Stage, string> = {
  NOT_APPLIED: "未投递",
  APPLIED: "已投递",
  SCREENING: "初筛",
  ASSESSMENT: "测评",
  INTERVIEW: "面试",
  OFFER: "Offer",
  REJECTED: "已挂",
  WITHDRAWN: "已放弃"
};

export const STAGE_ORDER: Stage[] = [
  "NOT_APPLIED",
  "APPLIED",
  "SCREENING",
  "ASSESSMENT",
  "INTERVIEW",
  "OFFER",
  "REJECTED",
  "WITHDRAWN"
];

export const ROLE_CATEGORIES = [
  "软件研发",
  "算法/AI",
  "数据",
  "硬件/芯片",
  "产品",
  "运营",
  "市场/品牌",
  "公关",
  "销售/商务",
  "供应链/采购/物流",
  "项目管理",
  "咨询",
  "金融/投研",
  "财务/审计",
  "人力资源",
  "法务/合规",
  "设计",
  "游戏策划/发行",
  "生产制造/质量",
  "医药/研发",
  "职能综合",
  "其他"
] as const;

export type RoleCategory = (typeof ROLE_CATEGORIES)[number];

/**
 * Categories currently exposed by the public discovery experience. The full
 * RoleCategory union remains intentionally unchanged so old IndexedDB
 * snapshots and backups can still be read without migration loss.
 */
export const PUBLIC_ROLE_CATEGORIES: readonly RoleCategory[] = [
  "产品",
  "数据",
  "运营",
  "市场/品牌",
  "公关",
  "销售/商务",
  "供应链/采购/物流",
  "项目管理",
  "咨询",
  "金融/投研",
  "财务/审计",
  "人力资源",
  "游戏策划/发行",
  "职能综合",
  "其他",
] as const;

export const COMPANY_TYPES = ["央企", "地方国企", "民企", "外企", "合资", "事业单位/科研机构", "其他", "未知"] as const;
export type CompanyType = (typeof COMPANY_TYPES)[number];

export const COMPANY_SCALES = ["0–99", "100–499", "500–999", "1000–9999", "10000+", "未知"] as const;
export type CompanyScale = (typeof COMPANY_SCALES)[number];

export const BATCHES = ["提前批", "秋招正式批", "秋招补录", "春招", "春招补录", "管培生/专项计划", "实习转正", "日常校招", "未知"] as const;
export type RecruitmentBatch = (typeof BATCHES)[number];

export interface CompanyMeta {
  id: string;
  name: string;
  aliases: string[];
  industry: string;
  type: CompanyType;
  scale: CompanyScale;
  /** Optional first-party asset, populated only after a logo source audit. */
  logoUrl?: string;
  logoSource?: "OFFICIAL" | "SIMPLE_ICONS" | "TEXT";
  logoVerified?: boolean;
  evidenceUrl: string;
  evidenceDate: string;
  sourceStatus: SourceStatus;
  note?: string;
}

/**
 * A current-cohort campus entry shown even when its concrete jobs have not
 * passed the verified-source gate. Entry leads are clickable but never imply
 * that the source is runnable or that its jobs are published.
 */
export interface CampusRecruitmentEntry {
  companyId: string;
  cohort: string;
  directoryStatus: CompanyDirectoryStatus;
  entryType: CareerEntryType;
  careerUrl: string;
  evidenceUrl: string;
  evidenceText: string;
  detectedSignals: string[];
  directorySource: string;
  directoryRank?: number;
  firstConfirmedAt?: string | null;
  lastCheckedAt: string;
  expiresAt?: string | null;
}

export interface CompanyDirectoryCompany {
  id: string;
  name: string;
  aliases?: string[];
  industry?: string;
  type?: CompanyType;
  scale?: CompanyScale;
  listingStatus?: "LISTED" | "UNLISTED" | "UNKNOWN";
  employeeCount?: number;
  /** Discovery metadata used only for optional company-segment filtering. */
  focusSegment?: string;
  authoritySegment?: string;
  hiringRadar?: { segment?: string; [key: string]: unknown };
  careerUrl?: string;
  sourceStatus?: SourceStatus;
  directory?: CampusRecruitmentEntry;
  /** Existing registry evidence remains optional for old generated files. */
  [key: string]: unknown;
}

export interface JobPosting {
  id: string;
  companyId: string;
  companyName: string;
  companyIndustry: string;
  companyType: CompanyType;
  companyScale: CompanyScale;
  title: string;
  city: string;
  /** Structured location hierarchy. `city` remains for V1 cache and backup compatibility. */
  locations?: JobLocation[];
  roleCategory: RoleCategory;
  cohort: string;
  batch: RecruitmentBatch;
  education: string;
  majorTags: string[];
  skills: string[];
  description: string;
  requirements: string[];
  /** Official publication date when the source explicitly provides one. */
  publishDate?: string;
  publishDateSource?: DateSource;
  deadline?: string;
  firstSeenAt: string;
  lastVerifiedAt: string;
  contentHash: string;
  status: JobStatus;
  applyUrl: string;
  sourceUrl: string;
  sourceEvidence?: string[];
  sourceName: string;
  sourceLevel: SourceLevel;
  detailShard: string;
  sourceId?: string;
  campaignId?: string;
  isDemo?: boolean;
  changedAt?: string;
  audienceDecision?: "TARGET_GENERALIST" | "OUT_OF_SCOPE" | "NEEDS_REVIEW";
  audienceReasonCodes?: string[];
  /** Public-entry jobs are intentionally kept separate from the formal
   * verified catalog and carry a visible disclosure in the UI. */
  provisional?: boolean;
  publicationLabel?: string;
  sourceStatus?: SourceStatus;
}

export interface RecruitmentCampaign {
  id: string;
  companyId: string;
  companyName: string;
  name: string;
  cohort: string;
  batch: RecruitmentBatch;
  openDate?: string;
  deadline?: string;
  officialUrl: string;
  sourceId: string;
  verifiedAt: string;
  status: CampaignStatus;
  jobIds: string[];
  isDemo?: boolean;
}

export type JobSummary = Omit<JobPosting, "description" | "requirements" | "majorTags" | "skills"> & {
  majorTags?: string[];
  skills?: string[];
};

export interface CatalogManifest {
  schemaVersion: number;
  catalogVersion: string;
  generatedAt: string;
  totalJobs: number;
  activeJobs: number;
  sourceCount: number;
  verifiedSourceCount: number;
  autoVerifiedSourceCount?: number;
  publishableSourceCount?: number;
  autoVerificationReports?: Array<{
    sourceId: string;
    conclusion?: "AUTO_VERIFIED" | "PROVISIONAL" | "QUARANTINED" | "BLOCKED";
    failureReasons?: string[];
    sampledJobs?: number;
    requiredFieldCompleteness?: number;
    invalidRowRatio?: number;
    duplicateRatio?: number;
    consecutiveHealthyRuns?: number;
    anomalousDrop?: boolean;
  }>;
  isDemo: boolean;
  sourceHealth: { healthy: number; quarantined: number; stale: number };
  shards: string[];
  businessDate?: string;
  todayCampaignCount?: number;
  todayPublishedJobCount?: number;
  todayFirstSeenCount?: number;
  audiencePolicy?: AudiencePolicySummary;
  locationSchemaVersion?: number;
  unknownLocationCount?: number;
  /** Discovery-only company pool metrics; never imply that candidates are live sources. */
  candidateCompanyCount?: number;
  companiesWithEligibleJobs?: number;
  confirmed500PlusCompanyCount?: number;
  collectionCadenceHours?: number;
  nextScheduledCollectionAt?: string;
  /** Discovery priority only; focused companies are not automatically live sources. */
  collectionFocus?: CollectionFocusSummary;
  /** Public, discovery-only coverage metrics. Candidate companies are not live sources. */
  coverage?: CoverageSummary;
  /** Fixed authority/seed import metadata; candidates are not live sources. */
  companyDiscovery?: CompanyDiscoverySummary;
  companyDirectory?: CompanyDirectorySummary;
}

export interface CompanyDiscoverySummary {
  authorityIndexId?: string | null;
  authorityIndexCompanyCount?: number;
  candidatePoolCompanyCount?: number;
  hiringRadarCompanyCount?: number;
  hiringRadarEntryUrlCount?: number;
  entryLayerSeparateFromJobSources?: boolean;
}

export interface CompanyDirectorySummary {
  cohort?: string;
  directorySourceCompanyCount?: number;
  activeRecruitingCompanyCount?: number;
  officialEntryCount?: number;
  entryLeadCount?: number;
  companiesWithEligibleJobs?: number;
  eligibleJobCount?: number;
  lastDiscoveryAt?: string | null;
  lastVerifiedAt?: string | null;
}

export interface CollectionFocusSummary {
  id?: string | null;
  mode?: "PRIORITIZE";
  target?: string;
  focusCompanyCount?: number;
  focusCompaniesWithSources?: number;
  focusCompaniesWithRunnableSources?: number;
  focusCompaniesWithEligibleJobs?: number;
  focusEligibleJobCount?: number;
  focusEligibleJobsBySegment?: Record<string, number>;
  preserveNonFocusSources?: boolean;
}

export interface CoverageSummary {
  scope?: string;
  status?: "IN_PROGRESS" | "SATURATED";
  discoveredCompanyCount?: number;
  verifiedActiveCompanyCount?: number;
  autoVerifiedSourceCount?: number;
  pendingReviewCompanyCount?: number;
  blockedCompanyCount?: number;
  accessibleSourceCoverageRate?: number | null;
  lastDiscoveryAt?: string | null;
  consecutiveNoNewCycles?: number;
  lastNewSourceAt?: string | null;
}

export interface AudiencePolicySummary {
  version: string;
  targetAudience: string;
  normalizedJobCount: number;
  eligibleJobCount: number;
  excludedJobCount: number;
  reviewJobCount: number;
}

export interface JobCatalog {
  schemaVersion: number;
  catalogVersion: string;
  generatedAt: string;
  jobs: JobSummary[];
}

/**
 * A separately published, quantity-first snapshot built from public
 * recruitment pages. It never changes the formal catalog or source registry.
 */
export interface ProvisionalJobCatalog {
  schemaVersion: number;
  generatedAt: string;
  reportType?: string;
  provisional: boolean;
  sourceStatus?: SourceStatus;
  publicationLabel?: string;
  verificationMode?: string;
  quantityFirst?: boolean;
  includesNeedsReview?: boolean;
  summary?: {
    jobCount?: number;
    companyCount?: number;
    eligibleJobCount?: number;
    reviewJobCount?: number;
    sourcePageCount?: number;
  };
  jobs: JobPosting[];
}

export interface CompanyDirectoryCatalog {
  schemaVersion: number;
  catalogVersion: string;
  generatedAt: string;
  isDemo?: boolean;
  companies: CompanyDirectoryCompany[];
}

export interface CampaignCatalog {
  schemaVersion: number;
  catalogVersion: string;
  generatedAt: string;
  campaigns: RecruitmentCampaign[];
}

export interface PublicSourceSummary {
  sourceId: string;
  companyId: string;
  companyName: string;
  sourceUrl: string;
  sourceLevel: SourceLevel;
  status: SourceStatus;
  health: string;
  adapter: string;
  accessMode: string;
  verifiedAt?: string | null;
  robotsReviewedAt?: string | null;
  termsReviewedAt?: string | null;
  jobCount: number;
  fetchedJobCount?: number;
  eligibleJobCount?: number;
  excludedJobCount?: number;
  reviewJobCount?: number;
  focusPriority?: number;
  focusSegment?: string;
  reason?: string;
  autoVerification?: {
    conclusion?: "AUTO_VERIFIED" | "PROVISIONAL" | "QUARANTINED" | "BLOCKED";
    atsType?: string | null;
    tenant?: string | null;
    sampledJobs?: number;
    requiredFieldCompleteness?: number;
    invalidRowRatio?: number;
    duplicateRatio?: number;
    consecutiveHealthyRuns?: number;
    anomalousDrop?: boolean;
    failureReasons?: string[];
    checkedAt?: string | null;
  };
}

export interface SourceCatalog {
  schemaVersion: number;
  catalogVersion: string;
  generatedAt: string;
  sources: PublicSourceSummary[];
}

/**
 * A lead found in a public community post. Community leads are deliberately
 * kept separate from verified company sources and public job postings.
 */
export interface CommunityLead {
  id: string;
  companyId?: string | null;
  companyName?: string | null;
  title: string;
  officialUrl?: string | null;
  officialUrlVerified?: boolean;
  /** @deprecated Legacy backups may contain these keys; public artifacts are
   * sanitised and the UI never renders or exports their values. */
  referralCode?: string | null;
  /** @deprecated See referralCode. */
  referralUrl?: string | null;
  /** @deprecated See referralCode. */
  referralCodeVerified?: boolean;
  /** @deprecated See referralCode. */
  referralEvidence?: "NOTE_CONTENT" | "TITLE_ONLY";
  sourceUrl: string;
  sourcePlatform: "xiaohongshu";
  sourceAuthorLabel?: string;
  publishedAt?: string | null;
  discoveredAt: string;
  verificationStatus: "NEEDS_REVIEW" | "VERIFIED_OFFICIAL" | "EXPIRED";
  note?: string;
}

export interface CommunityLeadCatalog {
  schemaVersion: number;
  generatedAt: string;
  source: string;
  privacy?: {
    cookiesPersisted?: boolean;
    xsecTokensPersisted?: boolean;
    privateContentIncluded?: boolean;
    disclaimer?: string;
  };
  queries?: string[];
  errors?: Array<{ query: string; message: string }>;
  leads: CommunityLead[];
}

export interface JobStateSnapshot {
  /** Kept with the local snapshot so brand metadata survives catalog expiry. */
  companyId?: string;
  title: string;
  companyName: string;
  city: string;
  locations?: JobLocation[];
  roleCategory: RoleCategory;
  companyIndustry: string;
  applyUrl: string;
  sourceUrl: string;
  lastVerifiedAt: string;
  companyType?: CompanyType;
  companyScale?: CompanyScale;
  cohort?: string;
  batch?: RecruitmentBatch;
  education?: string;
  majorTags?: string[];
  skills?: string[];
  description?: string;
  requirements?: string[];
  publishDate?: string;
  deadline?: string;
  firstSeenAt?: string;
  sourceName?: string;
  sourceLevel?: SourceLevel;
  changedAt?: string;
}

export interface UserJobState {
  jobId: string;
  snapshot: JobStateSnapshot;
  interest: Interest;
  stage: Stage;
  appliedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export type EventType = "SCREENING" | "ASSESSMENT" | "INTERVIEW" | "FOLLOW_UP" | "OFFER" | "REJECTED" | "NOTE";

export interface ApplicationEvent {
  id?: number;
  jobId: string;
  type: EventType;
  round?: number;
  scheduledAt?: string;
  completedAt?: string;
  locationOrLink?: string;
  completed: boolean;
  note?: string;
  createdAt: string;
}

export interface Preferences {
  id: "main";
  cohort: string;
  cities: string[];
  locationScopes?: LocationScope[];
  provinceCodes?: string[];
  cityCodes?: string[];
  roles: RoleCategory[];
  industries: string[];
  companyTypes: CompanyType[];
  educationLevels?: string[];
  batches?: RecruitmentBatch[];
  companyScales?: CompanyScale[];
  setupComplete: boolean;
  /** Public-entry jobs stay hidden from the formal catalog until explicitly enabled. */
  showProvisionalJobs?: boolean;
}

export interface AutumnAssistantBackupV1 {
  schema: "AutumnAssistantBackupV1";
  exportedAt: string;
  catalogVersion: string;
  preferences: Preferences;
  jobStates: UserJobState[];
  events: ApplicationEvent[];
}

export const DEFAULT_PREFERENCES: Preferences = {
  id: "main",
  cohort: "2027",
  cities: [],
  locationScopes: ["MAINLAND_CHINA"],
  provinceCodes: [],
  cityCodes: [],
  roles: [],
  industries: [],
  companyTypes: [],
  educationLevels: [],
  batches: [],
  companyScales: [],
  setupComplete: false,
  showProvisionalJobs: false
};

export const EVENT_LABELS: Record<EventType, string> = {
  SCREENING: "初筛",
  ASSESSMENT: "测评",
  INTERVIEW: "面试",
  FOLLOW_UP: "跟进",
  OFFER: "Offer",
  REJECTED: "未通过",
  NOTE: "备注"
};
