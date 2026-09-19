import {
  Archive,
  ArrowUpRight,
  BellRinging as BellRing,
  Bookmark,
  Briefcase as BriefcaseBusiness,
  Buildings as Building2,
  Calendar as CalendarDays,
  CalendarDots as CalendarRange,
  Check,
  CheckCircle as CheckCircle2,
  CaretRight as ChevronRight,
  Question as CircleHelp,
  ClipboardText as ClipboardCheck,
  Clock as Clock3,
  Download,
  ArrowSquareOut as ExternalLink,
  FileText as FileJson,
  Funnel as Filter,
  Flag,
  FolderOpen,
  Heart,
  Info,
  Layout as LayoutGrid,
  ListDashes as ListFilter,
  CircleNotch as LoaderCircle,
  LockKey as LockKeyhole,
  DotsThree as MoreHorizontal,
  MapPin,
  Package as PackageOpen,
  Pencil,
  Plus,
  ArrowCounterClockwise as RotateCcw,
  ArrowsClockwise as RefreshCw,
  MagnifyingGlass as Search,
  GearSix as Settings2,
  SlidersHorizontal,
  Sparkle as Sparkles,
  Tag,
  Target,
  Trash as Trash2,
  Upload,
  X,
} from "@phosphor-icons/react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useLiveQuery } from "dexie-react-hooks";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { DEMO_CAMPAIGNS, DEMO_CATALOG, DEMO_JOB_BY_ID } from "./data/catalog";
import { CompanyLogo } from "./components/CompanyLogo";
import { ModernSelect, type SelectOption } from "./components/ModernSelect";
import { MultiSelectField } from "./components/MultiSelectField";
import { BrandMark, GlobalHeader, MobileBottomNavigation, NAV_ITEMS, type AppRoute } from "./components/Navigation";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./components/ui/dialog";
import { parseBackup } from "./lib/backup";
import {
  addEvent,
  clearLocalData,
  db,
  ensurePreferences,
  replaceAllLocalData,
  saveJobState,
  savePreferences,
  toggleEvent,
} from "./store/db";
import {
  BATCHES,
  COMPANY_SCALES,
  COMPANY_TYPES,
  DEFAULT_PREFERENCES,
  EVENT_LABELS,
  INTEREST_LABELS,
  PUBLIC_ROLE_CATEGORIES,
  STAGE_LABELS,
  STAGE_ORDER,
  type ApplicationEvent,
  type CampaignCatalog,
  type CatalogManifest,
  type CommunityLead,
  type CommunityLeadCatalog,
  type CompanyDirectoryCatalog,
  type CompanyDirectoryCompany,
  type CampusRecruitmentEntry,
  type EventType,
  type Interest,
  type JobPosting,
  type JobSummary,
  type JobLocation,
  type LocationScope,
  type JobCatalog,
  type ProvisionalJobCatalog,
  type Preferences,
  type RoleCategory,
  type RecruitmentCampaign,
  type PublicSourceSummary,
  type SourceCatalog,
  type Stage,
  type UserJobState,
} from "./types";
import {
  daysFromNow,
  displayLocations,
  downloadFile,
  escapeCsvCell,
  formatDate,
  formatDateTime,
  isDeadlineSoon,
  isOverdue,
  matchesPreferences,
  matchesLocation,
  splitCities,
  snapshotFromState,
} from "./lib/utils";

type Route = AppRoute;

const EVENT_TYPES: EventType[] = ["SCREENING", "ASSESSMENT", "INTERVIEW", "FOLLOW_UP", "OFFER", "REJECTED", "NOTE"];
const BLOCKED_PUBLIC_ROLE_CATEGORIES = new Set(["软件研发", "算法/AI", "硬件/芯片", "技术", "生产制造/质量", "医药/研发", "法务/合规", "设计"]);
const BLOCKED_PUBLIC_TITLE_PATTERN = new RegExp([
  "算法", "机器学习", "深度学习", "大模型", "人工智能", "自然语言处理", "计算机视觉", "机器视觉", "数据科学", "数据科学家", "数据工程", "数据工程师", "分析工程师", "信息安全", "网络安全",
  "computer[- ]?science", "computer[- ]?engineering", "software[- ]?engineering", "information[- ]?technology", "electrical[- ]?engineering", "electronic[- ]?engineering", "mechanical[- ]?engineering", "civil[- ]?engineering", "materials?[- ]?engineering", "chemical[- ]?engineering", "machine[- ]?learning", "deep[- ]?learning", "artificial[- ]?intelligence", "computer[- ]?vision", "machine[- ]?vision", "natural[- ]?language", "data[- ]?science", "data[- ]?scientist", "data[- ]?engineering", "information[- ]?security", "network[- ]?security", "large[- ]?language[- ]?models?", "multimodal(?:ity)?", "multi[- ]?modal", "reinforcement[- ]?learning", "world[- ]?model", "speech[- ]?synthesis", "video[- ]?generation", "algorithm", "(?:^|[^a-z])ai(?:$|[^a-z])", "(?:^|[^a-z])nlp(?:$|[^a-z])", "(?:^|[^a-z])llms?(?:$|[^a-z])", "(?:^|[^a-z])ml(?:$|[^a-z])", "(?:^|[^a-z])rl(?:$|[^a-z])",
  "软件开发", "系统开发", "应用开发", "平台开发", "开发工程师", "研发", "后端", "前端", "客户端", "安卓", "android", "ios", "测试开发", "测试工程师", "软件测试", "测试岗", "运维", "运维工程师", "IT运维", "devops", "sre", "数据库管理员", "数据库管理", "系统管理员", "网络管理员", "网络工程师", "云计算", "云平台", "平台运维", "信息技术", "系统架构", "架构师", "back[- ]?end", "front[- ]?end", "full[- ]?stack", "softwaredevelopment", "applicationdevelopment", "platformdevelopment",
  "工程师", "工程技术", "工程研发", "工程项目", "工程管理", "技术开发", "技术研发", "技术岗", "技术专员", "技术经理", "嵌入式", "芯片", "硬件", "电路", "fpga", "机械工程", "电子工程", "自动化工程", "车辆工程", "工艺工程", "电网", "电力", "输电", "变电", "配电", "电力建设", "工程建设", "系统设计", "结构设计", "电驱", "动力系统", "bms", "机器人", "技术运营", "技术产品", "技术项目", "技术支持", "技术岗位", "技术策划", "系统工程", "engineer", "developer", "software", "technical", "embedded", "systemdesign", "structuraldesign", "powertrain", "datascientist", "dataengineer", "database(?:administrator|admin)?", "databasemanager", "it\\s+operations?", "itoperations?", "researchanddevelopment", "research\\s*[&+]\\s*development", "research&development", "r&d", "engineeringresearch", "engineresearch", "researchscientist", "modelresearcher", "technicalresearch", "codingllms?", "agenticrl", "cloudinfrastructure", "infrastructureengineer", "networkengineer", "systems?administrator",
  "量化", "精算", "实验室", "实验研究", "科研", "quantitative", "actuary", "scientist", "laboratory", "researchscientist", "医学", "临床", "药物研发", "药理", "药剂", "医师", "护士", "medical", "clinical", "pharma", "physician", "nurse", "法务", "律师", "法律", "合规", "专利", "legal", "lawyer", "compliance", "patent", "制造工程", "生产工艺", "质量工程", "工艺技术", "工业设计", "建筑设计", "建筑师", "视觉设计", "ui设计", "ux设计", "交互设计", "产品设计", "运营设计", "品牌创意设计", "设计师", "设计岗", "设计类", "设计方向", "美术", "原画", "插画", "体育教练", "industrialdesign", "architect", "visualdesigner", "uidesigner", "uxdesigner", "designer", "design",
].join("|"), "i");

function isPublicAudienceJob(job: JobPosting): boolean {
  return !BLOCKED_PUBLIC_ROLE_CATEGORIES.has(job.roleCategory) && !BLOCKED_PUBLIC_TITLE_PATTERN.test(job.title);
}

function isPublishableSourceStatus(status: PublicSourceSummary["status"] | undefined): boolean {
  return status === "VERIFIED" || status === "AUTO_VERIFIED";
}

function sourceStatusLabel(status: PublicSourceSummary["status"]): string {
  if (status === "AUTO_VERIFIED") return "自动核验";
  if (status === "VERIFIED") return "人工核验";
  if (status === "QUARANTINED") return "已隔离";
  if (status === "BLOCKED") return "已阻断";
  if (status === "STALE") return "已过期";
  if (status === "REPLACED") return "已替换";
  return "待核验";
}

const LOCAL_DEMO_MANIFEST: CatalogManifest = {
  schemaVersion: 1,
  catalogVersion: DEMO_CATALOG.catalogVersion,
  generatedAt: DEMO_CATALOG.generatedAt,
  totalJobs: DEMO_CATALOG.jobs.length,
  activeJobs: DEMO_CATALOG.jobs.length,
  sourceCount: 0,
  verifiedSourceCount: 0,
  isDemo: true,
  sourceHealth: { healthy: 0, quarantined: 0, stale: 0 },
  shards: ["demo-a"],
  candidateCompanyCount: 0,
  companiesWithEligibleJobs: new Set(DEMO_CATALOG.jobs.map((job) => job.companyId)).size,
  confirmed500PlusCompanyCount: 0,
  collectionCadenceHours: 5,
  businessDate: "2026-09-02",
  todayCampaignCount: DEMO_CAMPAIGNS.filter((campaign) => campaign.openDate === "2026-09-02").length,
  todayPublishedJobCount: DEMO_CATALOG.jobs.filter((job) => job.publishDate === "2026-09-02").length,
  todayFirstSeenCount: DEMO_CATALOG.jobs.filter((job) => job.firstSeenAt.startsWith("2026-09-02")).length,
  audiencePolicy: {
    version: "humanities-social-business-v1",
    targetAudience: "文科、社科、商科及不限专业的通用校招岗位",
    normalizedJobCount: DEMO_CATALOG.jobs.length,
    eligibleJobCount: DEMO_CATALOG.jobs.length,
    excludedJobCount: 4,
    reviewJobCount: 0,
  },
};

function assetPath(path: string): string {
  const cleanPath = path.replace(/^\/+/, "");
  // Vite's single-file production build is also used from Explorer. Relative
  // URLs keep the bundled demo's images/data beside dist/index.html while a
  // configured BASE_URL still scopes assets correctly on GitHub Pages.
  if (window.location.protocol === "file:") return cleanPath;
  const base = (import.meta.env.BASE_URL || "/").replace(/\/?$/, "/");
  return `${base}${cleanPath}`;
}

/**
 * The frame is deliberately shared by every route so the product reads as one
 * publication rather than four unrelated hero panels. Route-specific artwork
 * is layered by PageVignette below.
 */
function routeVisualAsset(_route: AppRoute, _mobile = false): string {
  return assetPath("assets/visuals/ink-frame.webp");
}

type InkPageVisualConfig = {
  route: "jobs" | "progress" | "schedule" | "settings";
  desktopSrc: string;
  desktopWidth: number;
  desktopHeight: number;
  mobileSrc: string;
  mobileWidth: number;
  mobileHeight: number;
  objectPosition: string;
  mobileObjectPosition: string;
  textScrimStop: string;
};

const PAGE_VISUAL_FILES: Record<InkPageVisualConfig["route"], Omit<InkPageVisualConfig, "route" | "desktopSrc" | "mobileSrc"> & { desktopFile: string; mobileFile: string }> = {
  jobs: {
    desktopFile: "hero-jobs-crossing.webp",
    mobileFile: "hero-jobs-crossing-mobile.webp",
    desktopWidth: 1800,
    desktopHeight: 750,
    mobileWidth: 900,
    mobileHeight: 375,
    objectPosition: "center center",
    mobileObjectPosition: "center center",
    textScrimStop: "42%",
  },
  progress: {
    desktopFile: "hero-progress-passage-v2.webp",
    mobileFile: "hero-progress-passage-v2-mobile.webp",
    desktopWidth: 1800,
    desktopHeight: 750,
    mobileWidth: 900,
    mobileHeight: 375,
    objectPosition: "center center",
    mobileObjectPosition: "center center",
    textScrimStop: "40%",
  },
  schedule: {
    desktopFile: "hero-schedule-celestial-v2.webp",
    mobileFile: "hero-schedule-celestial-v2-mobile.webp",
    desktopWidth: 1800,
    desktopHeight: 750,
    mobileWidth: 900,
    mobileHeight: 375,
    objectPosition: "center center",
    mobileObjectPosition: "center center",
    textScrimStop: "42%",
  },
  settings: {
    desktopFile: "hero-settings-seal-v2.webp",
    mobileFile: "hero-settings-seal-v2-mobile.webp",
    desktopWidth: 1800,
    desktopHeight: 750,
    mobileWidth: 900,
    mobileHeight: 375,
    objectPosition: "center center",
    mobileObjectPosition: "center center",
    textScrimStop: "40%",
  },
};

function pageVisualConfig(route: InkPageVisualConfig["route"]): InkPageVisualConfig {
  const visual = PAGE_VISUAL_FILES[route];
  return {
    route,
    desktopSrc: assetPath(`assets/visuals/${visual.desktopFile}`),
    mobileSrc: assetPath(`assets/visuals/${visual.mobileFile}`),
    desktopWidth: visual.desktopWidth,
    desktopHeight: visual.desktopHeight,
    mobileWidth: visual.mobileWidth,
    mobileHeight: visual.mobileHeight,
    objectPosition: visual.objectPosition,
    mobileObjectPosition: visual.mobileObjectPosition,
    textScrimStop: visual.textScrimStop,
  };
}

function repositoryUrl(): string {
  return (import.meta.env.VITE_REPOSITORY_URL as string | undefined)?.replace(/\/$/, "") || "https://github.com/";
}

function reportIssueUrl(job?: JobPosting): string {
  const repository = repositoryUrl();
  if (repository === "https://github.com/") return repository;
  const issue = new URL(`${repository}/issues/new`);
  issue.searchParams.set("template", "source-report.yml");
  issue.searchParams.set("title", job ? `[来源纠错] ${job.companyName} · ${job.title}` : "[来源纠错] 岗位数据");
  if (job) issue.searchParams.set("job-url", job.sourceUrl);
  return issue.toString();
}

function useHashRoute(): [Route, (route: Route) => void] {
  const read = (): Route => {
    const value = window.location.hash.replace(/^#\/?/, "").split("/")[0];
    return NAV_ITEMS.some((item) => item.id === value) ? (value as Route) : "jobs";
  };
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const onHashChange = () => setRoute(read());
    window.addEventListener("hashchange", onHashChange);
    if (!window.location.hash) window.history.replaceState(null, "", "#/jobs");
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  // Hash navigation does not reliably reset the document scroll position when
  // the previous route was left deep in its workbench.  Returning to the
  // route's masthead keeps the large editorial hero and its primary action in
  // view, while job-detail hashes remain on the same `jobs` route and are not
  // affected by this effect.
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [route]);
  return [route, (next) => { window.location.hash = `/${next}`; }];
}

function readHashJobId(): string | undefined {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/");
  if (parts[0] !== "jobs" || !parts[1]) return undefined;
  try {
    return decodeURIComponent(parts.slice(1).join("/"));
  } catch {
    return parts.slice(1).join("/");
  }
}

function summaryToPosting(summary: JobSummary): JobPosting {
  return {
    ...summary,
    majorTags: summary.majorTags ?? [],
    skills: summary.skills ?? [],
    description: "",
    requirements: [],
  };
}

function shanghaiDay(value?: string): string {
  if (!value) return "";
  // A date-only value is already a business date. Timestamp values are
  // converted explicitly so a UTC snapshot near midnight cannot appear in
  // the wrong "today" bucket for users in China.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function localDay(value?: string): string {
  return shanghaiDay(value);
}

function todayInShanghai(): string {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function isSameDay(value?: string): boolean {
  return Boolean(value) && shanghaiDay(value) === todayInShanghai();
}

function isWithinNextDays(value?: string, days = 7): boolean {
  if (!value) return false;
  const diff = new Date(value).getTime() - Date.now();
  return diff >= 0 && diff <= days * 86400000;
}

function localDateInputValue(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16);
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 16);
}

function demoDirectoryCompanies(): CompanyDirectoryCompany[] {
  const seen = new Set<string>();
  return DEMO_CATALOG.jobs.filter((job) => {
    if (seen.has(job.companyId)) return false;
    seen.add(job.companyId);
    return true;
  }).map((job, index) => ({
    id: job.companyId,
    name: job.companyName,
    industry: job.companyIndustry,
    type: job.companyType,
    scale: job.companyScale,
    careerUrl: job.applyUrl,
    sourceStatus: "TARGET" as const,
    directory: {
      companyId: job.companyId,
      cohort: job.cohort,
      directoryStatus: "ACTIVE_CONFIRMED" as const,
      entryType: "OFFICIAL_CAMPAIGN_PAGE" as const,
      careerUrl: job.applyUrl,
      evidenceUrl: job.sourceUrl,
      evidenceText: "演示目录中的公开校招入口。",
      detectedSignals: [`${job.cohort} 届校招入口`],
      directorySource: "demo-catalog",
      directoryRank: index + 1,
      firstConfirmedAt: job.firstSeenAt,
      lastCheckedAt: job.lastVerifiedAt,
    } satisfies CampusRecruitmentEntry,
  }));
}

type VignetteMetric = { label: string; value: string | number; note?: string };

/** Keep legacy stored scale values intact while using a plain hyphen in UI. */
function displayCompanyScale(value: string): string {
  return value.replace(/[\u2013\u2014]/g, "-");
}

/**
 * Shared editorial masthead for the four product areas. The artwork is made
 * from CSS layers so the product stays useful before optional image assets
 * arrive, and still has a distinct visual signature in offline builds.
 */
function PageVignette({ variant, title, metrics, action, children }: {
  variant: "jobs" | "progress" | "schedule" | "settings";
  title: string;
  metrics: VignetteMetric[];
  action?: ReactNode;
  children?: ReactNode;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const [imageReady, setImageReady] = useState(false);
  const ghost = variant === "jobs" ? "岗" : variant === "progress" ? "进" : variant === "schedule" ? "时" : "藏";
  const visual = pageVisualConfig(variant);
  return <section className={`page-vignette page-vignette-${variant}`} aria-labelledby={`${variant}-vignette-title`}>
    <div className="vignette-copy">
      <h1 id={`${variant}-vignette-title`}>{title}</h1>
      <div className="vignette-metrics">{metrics.map((metric) => <div className="vignette-metric" key={metric.label}><strong>{metric.value}</strong><span>{metric.label}</span>{metric.note && <small>{metric.note}</small>}</div>)}</div>
      {action && <div className="vignette-action">{action}</div>}
    </div>
    <div className={`vignette-art ${imageReady ? "has-vignette-image" : imageFailed ? "is-image-fallback" : "is-image-loading"}`} aria-hidden="true" style={{ "--hero-object-position": visual.objectPosition, "--hero-mobile-object-position": visual.mobileObjectPosition, "--hero-text-scrim-stop": visual.textScrimStop } as CSSProperties}>
      {!imageFailed && <picture className="vignette-picture">
        <source media="(max-width: 900px)" srcSet={visual.mobileSrc} />
        <img className="vignette-image" src={visual.desktopSrc} alt="" width={visual.desktopWidth} height={visual.desktopHeight} loading="eager" fetchPriority="high" decoding="async" onLoad={() => setImageReady(true)} onError={() => { setImageFailed(true); setImageReady(false); }} />
      </picture>}
      <span className="vignette-ghost">{ghost}</span>
      <span className="ink-wash ink-wash-one" />
      <span className="ink-wash ink-wash-two" />
      <span className="ink-river" />
      <span className="ink-river ink-river-secondary" />
      <span className="ink-boat"><BoatGlyph /></span>
      <span className="ink-seal" />
    </div>
    {children}
  </section>;
}

function BoatGlyph() {
  return <BrandMark compact />;
}

function App() {
  const [route, navigate] = useHashRoute();
  const [hashJobId, setHashJobId] = useState<string | undefined>(readHashJobId);
  const jobStates = useLiveQuery(() => db.jobStates.toArray(), [], []) ?? [];
  const events = useLiveQuery(() => db.events.toArray(), [], []) ?? [];
  const storedPreferences = useLiveQuery(() => db.preferences.get("main"), [], DEFAULT_PREFERENCES);
  const preferences = storedPreferences ?? DEFAULT_PREFERENCES;
  const [catalog, setCatalog] = useState<JobCatalog>(DEMO_CATALOG);
  const [provisionalCatalog, setProvisionalCatalog] = useState<ProvisionalJobCatalog | null>(null);
  const [campaigns, setCampaigns] = useState<RecruitmentCampaign[]>(DEMO_CAMPAIGNS);
  const [sources, setSources] = useState<PublicSourceSummary[]>([]);
  const [directoryCompanies, setDirectoryCompanies] = useState<CompanyDirectoryCompany[]>(demoDirectoryCompanies);
  const [communityLeads, setCommunityLeads] = useState<CommunityLead[]>([]);
  const [manifest, setManifest] = useState<CatalogManifest | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [offlineCatalog, setOfflineCatalog] = useState(false);
  const [demoCatalog, setDemoCatalog] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [catalogBannerDismissed, setCatalogBannerDismissed] = useState(false);
  const [provisionalBannerDismissed, setProvisionalBannerDismissed] = useState(false);
  const [audienceBannerDismissed, setAudienceBannerDismissed] = useState(false);
  const [selectedJob, setSelectedJob] = useState<JobPosting | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [updateReady, setUpdateReady] = useState(false);
  const lastVisitRef = useRef<string>(localStorage.getItem("autumn-last-visit") ?? "");
  const suppressHashOpenRef = useRef(false);
  const detailRequestRef = useRef(0);
  const detailTriggerRef = useRef<HTMLElement | null>(null);

  const restoreDetailFocus = useCallback(() => {
    const trigger = detailTriggerRef.current;
    detailTriggerRef.current = null;
    if (trigger?.isConnected) window.setTimeout(() => trigger.focus(), 0);
  }, []);

  useEffect(() => {
    void ensurePreferences();
    const now = new Date().toISOString();
    const timer = window.setTimeout(() => localStorage.setItem("autumn-last-visit", now), 1200);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    // The live query starts with defaults while IndexedDB is opening. Close a
    // previously completed onboarding modal as soon as the persisted
    // preference arrives; otherwise a page reload would leave an invisible
    // stale overlay intercepting every click.
    setOnboardingOpen(!preferences.setupComplete);
  }, [preferences.setupComplete]);

  useEffect(() => {
    const onUpdate = () => setUpdateReady(true);
    window.addEventListener("autumn-update-ready", onUpdate);
    return () => window.removeEventListener("autumn-update-ready", onUpdate);
  }, []);

  useEffect(() => {
    const onHashChange = () => {
      const nextJobId = readHashJobId();
      if (!nextJobId) {
        // Browser back, a navigation click, and the drawer's own close action
        // all converge on a jobs hash without an id. Clear the rendered
        // drawer here as well as in closeJob so history navigation cannot
        // leave a stale overlay intercepting the page.
        detailRequestRef.current += 1;
        setSelectedJob(null);
        setDetailLoading(false);
        restoreDetailFocus();
      }
      // Closing a modal updates the hash after clearing selectedJob. Ignore
      // the stale job id during that same tick so the deep-link effect cannot
      // immediately reopen the modal that the user just closed.
      if (!nextJobId && suppressHashOpenRef.current) suppressHashOpenRef.current = false;
      setHashJobId(nextJobId);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [restoreDetailFocus]);

  useEffect(() => {
    // A bundled build can be opened directly from Explorer. Chromium blocks
    // fetch(file://...) for the JSON directory, so use the same embedded demo
    // catalog that powers the first-render fallback instead of logging a
    // failed request and leaving the user uncertain about the data state.
    if (window.location.protocol === "file:") {
      setManifest(LOCAL_DEMO_MANIFEST);
      setCampaigns(DEMO_CAMPAIGNS);
      setSources([]);
      setDirectoryCompanies(demoDirectoryCompanies());
      setCommunityLeads([]);
      setDemoCatalog(true);
      setOfflineCatalog(true);
      setCatalogLoading(false);
      setProvisionalCatalog(null);
      setNotice("当前打开的是本地离线版本，使用内置演示目录；在线打开可读取最新目录。");
      return;
    }

    let cancelled = false;
    setCatalogLoading(true);
    Promise.all([
      fetch(assetPath("data/catalog.json"), { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("catalog");
        return response.json() as Promise<JobCatalog>;
      }),
      fetch(assetPath("data/manifest.json"), { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("manifest");
        return response.json() as Promise<CatalogManifest>;
      }),
      fetch(assetPath("data/campaigns.json"), { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("campaigns");
        return response.json() as Promise<CampaignCatalog>;
      }).catch(() => ({ schemaVersion: 1, catalogVersion: "", generatedAt: "", campaigns: [] } as CampaignCatalog)),
      fetch(assetPath("data/sources.json"), { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("sources");
        return response.json() as Promise<SourceCatalog>;
      }).catch(() => ({ schemaVersion: 1, catalogVersion: "", generatedAt: "", sources: [] } as SourceCatalog)),
      fetch(assetPath("data/community-leads.json"), { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("community-leads");
        return response.json() as Promise<CommunityLeadCatalog>;
      }).catch(() => ({ schemaVersion: 1, generatedAt: "", source: "", leads: [] } as CommunityLeadCatalog)),
      fetch(assetPath("data/companies.json"), { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("companies");
        return response.json() as Promise<CompanyDirectoryCatalog>;
      }).catch(() => ({ schemaVersion: 1, catalogVersion: "", generatedAt: "", companies: [] } as CompanyDirectoryCatalog)),
      fetch(assetPath("data/provisional-jobs.json"), { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("provisional-jobs");
        return response.json() as Promise<ProvisionalJobCatalog>;
      }).catch(() => null),
    ])
      .then(([nextCatalog, nextManifest, nextCampaigns, nextSources, nextCommunityLeads, nextCompanies, nextProvisional]) => {
        if (cancelled) return;
        const isDemo = Boolean(nextManifest.isDemo);
        const resolvedCatalog = isDemo ? DEMO_CATALOG : nextCatalog;
        const resolvedCampaigns = isDemo ? DEMO_CAMPAIGNS : (nextCampaigns.campaigns ?? []);
        const resolvedManifest = isDemo ? {
          ...nextManifest,
          businessDate: nextManifest.businessDate ?? "2026-09-02",
          todayCampaignCount: DEMO_CAMPAIGNS.filter((campaign) => campaign.openDate === (nextManifest.businessDate ?? "2026-09-02")).length,
          todayPublishedJobCount: DEMO_CATALOG.jobs.filter((job) => job.publishDate === (nextManifest.businessDate ?? "2026-09-02")).length,
          todayFirstSeenCount: DEMO_CATALOG.jobs.filter((job) => localDay(job.firstSeenAt) === (nextManifest.businessDate ?? "2026-09-02")).length,
        } : nextManifest;
        setCatalog(resolvedCatalog);
        setManifest(resolvedManifest);
        setCampaigns(resolvedCampaigns);
        setSources(isDemo ? [] : (nextSources.sources ?? []));
        setCommunityLeads(isDemo ? [] : (nextCommunityLeads.leads ?? []));
        setDirectoryCompanies(isDemo ? demoDirectoryCompanies() : (nextCompanies.companies ?? []));
        setProvisionalCatalog(isDemo ? null : nextProvisional);
        setDemoCatalog(isDemo);
        setOfflineCatalog(false);
      })
      .catch(() => {
        if (cancelled) return;
        setOfflineCatalog(true);
        setNotice("当前使用内置演示目录；网络恢复后可在设置页查看最新目录。");
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // The collector and release gate are authoritative. This small client-side
  // guard also protects users opening a stale V1 cache before the next catalog
  // update, without touching their local IndexedDB snapshots.
  const formalJobs = useMemo(() => catalog.jobs.map(summaryToPosting), [catalog.jobs]);
  const jobs = useMemo(() => {
    const provisionalJobs = (provisionalCatalog?.jobs ?? []).map((job) => ({
      ...job,
      provisional: true,
      publicationLabel: provisionalCatalog?.publicationLabel ?? "公开入口临时采集 · 待核验",
      sourceStatus: "TARGET" as const,
    }));
    const unique = new Map<string, JobPosting>();
    [...formalJobs, ...(preferences.showProvisionalJobs ? provisionalJobs : [])].forEach((job) => unique.set(job.id, job));
    return [...unique.values()].filter(isPublicAudienceJob);
  }, [formalJobs, preferences.showProvisionalJobs, provisionalCatalog]);
  const jobMap = useMemo(() => new Map(jobs.map((job) => [job.id, job])), [jobs]);
  const stateMap = useMemo(() => new Map(jobStates.map((state) => [state.jobId, state])), [jobStates]);
  const matchedCount = useMemo(() => formalJobs.filter((job) => matchesPreferences(job, preferences)).length, [formalJobs, preferences]);
  const newCount = useMemo(() => {
    if (!lastVisitRef.current) return Math.min(formalJobs.length, 5);
    const previous = new Date(lastVisitRef.current).getTime();
    return formalJobs.filter((job) => new Date(job.firstSeenAt).getTime() > previous).length;
  }, [formalJobs]);
  const soonCount = useMemo(() => formalJobs.filter((job) => isDeadlineSoon(job.deadline)).length, [formalJobs]);
  const activeTrackedCount = jobStates.filter((state) => !["NOT_APPLIED", "REJECTED", "WITHDRAWN"].includes(state.stage)).length;
  const businessDate = manifest?.businessDate ?? (demoCatalog ? "2026-09-02" : todayInShanghai());
  const todayPublishedJobCount = manifest?.todayPublishedJobCount ?? formalJobs.filter((job) => localDay(job.publishDate) === businessDate).length;
  const provisionalReviewCount = provisionalCatalog?.summary?.reviewJobCount ?? 0;
  const provisionalDisclosure = provisionalCatalog?.includesNeedsReview && provisionalReviewCount > 0
    ? `其中 ${provisionalReviewCount} 条信息不足，已按数量优先展示并标记待核验。`
    : "这些岗位来自企业公开页面，属于临时采集 · 待核验。";

  const showNotice = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice((current) => current === message ? null : current), 4500);
  }, []);

  const hydrateJob = useCallback(async (job: JobPosting): Promise<JobPosting> => {
    const localDemo = DEMO_JOB_BY_ID.get(job.id);
    if (localDemo) return localDemo;
    if (job.description || !job.detailShard || job.detailShard === "local") return job;
    try {
      const response = await fetch(assetPath(`data/jobs/${job.detailShard}.json`));
      if (!response.ok) return job;
      const payload = await response.json() as { jobs: JobPosting[] };
      return payload.jobs.find((item) => item.id === job.id) ?? job;
    } catch {
      return job;
    }
  }, []);

  const openJob = useCallback(async (job: JobPosting) => {
    const requestId = ++detailRequestRef.current;
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement && activeElement !== document.body) detailTriggerRef.current = activeElement;
    setSelectedJob(job);
    if (window.location.hash !== `#/jobs/${encodeURIComponent(job.id)}`) {
      window.location.hash = `#/jobs/${encodeURIComponent(job.id)}`;
    }
    setDetailLoading(true);
    try {
      const hydrated = await hydrateJob(job);
      // A user may close the modal while a detail shard is still loading. Do
      // not let that stale promise resurrect the modal after it was closed.
      if (detailRequestRef.current === requestId && !suppressHashOpenRef.current) setSelectedJob(hydrated);
    } catch {
      if (detailRequestRef.current === requestId) showNotice("详情分片暂时不可用，已显示岗位摘要。你仍可打开官方链接核验。");
    } finally {
      if (detailRequestRef.current === requestId) setDetailLoading(false);
    }
  }, [hydrateJob, showNotice]);

  useEffect(() => {
    if (catalogLoading || selectedJob || suppressHashOpenRef.current) return;
    const job = hashJobId ? jobMap.get(hashJobId) : undefined;
    if (job) void openJob(job);
  }, [catalogLoading, hashJobId, jobMap, openJob, selectedJob]);

  const closeJob = useCallback(() => {
    detailRequestRef.current += 1;
    suppressHashOpenRef.current = true;
    setSelectedJob(null);
    setDetailLoading(false);
    setHashJobId(undefined);
    restoreDetailFocus();
    if (window.location.hash.match(/^#\/?jobs\//)) {
      window.location.hash = "#/jobs";
    } else {
      suppressHashOpenRef.current = false;
    }
  }, [restoreDetailFocus]);

  const updateInterest = useCallback(async (job: JobPosting, interest: Interest) => {
    await saveJobState(await hydrateJob(job), { interest });
    showNotice(interest === "SUITABLE" ? "已标记为合适，之后可在进度页继续记录。" : interest === "UNSUITABLE" ? "已标记为不合适，筛选时可以隐藏。" : "已恢复为未判断。");
  }, [hydrateJob, showNotice]);

  const updateStage = useCallback(async (job: JobPosting, stage: Stage) => {
    const before = stateMap.get(job.id);
    const hydratedJob = await hydrateJob(job);
    const appliedAt = stage !== "NOT_APPLIED" && stage !== "WITHDRAWN" ? (before?.appliedAt ?? new Date().toISOString()) : before?.appliedAt;
    await saveJobState(hydratedJob, { stage, appliedAt });
    if (stage !== before?.stage) {
      const eventType: EventType | null = stage === "SCREENING" ? "SCREENING" : stage === "ASSESSMENT" ? "ASSESSMENT" : stage === "INTERVIEW" ? "INTERVIEW" : stage === "OFFER" ? "OFFER" : stage === "REJECTED" ? "REJECTED" : null;
      if (eventType) await addEvent({ jobId: job.id, type: eventType, completed: false, note: `阶段更新为「${STAGE_LABELS[stage]}」` });
      if (stage === "APPLIED") await addEvent({ jobId: job.id, type: "NOTE", completed: true, note: "已登记投递" });
    }
    showNotice(`已更新「${job.title}」为${STAGE_LABELS[stage]}。`);
  }, [hydrateJob, showNotice, stateMap]);

  const saveOnboarding = async (next: Preferences) => {
    // Close the overlay immediately. Persisting preferences is local and
    // asynchronous; keeping the modal mounted until IndexedDB resolves can
    // briefly block navigation when someone clicks “先看看岗位” and then
    // changes pages right away.
    setOnboardingOpen(false);
    await savePreferences({ ...next, setupComplete: true });
    showNotice("偏好已保存，岗位页会用透明规则标出符合项。");
  };

  const exportJson = async () => {
    const backup = {
      schema: "AutumnAssistantBackupV1" as const,
      exportedAt: new Date().toISOString(),
      catalogVersion: manifest?.catalogVersion ?? catalog.catalogVersion,
      preferences,
      jobStates,
      events,
    };
    downloadFile(`秋招助手备份-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(backup, null, 2), "application/json;charset=utf-8");
    showNotice("JSON 备份已生成，文件只包含本地记录。");
  };

  const toggleEventComplete = useCallback(async (event: ApplicationEvent) => {
    await toggleEvent(event);
    showNotice(event.completed ? "已恢复为待处理。" : "已标记为完成。");
  }, [showNotice]);

  const exportCsv = () => {
    const header = ["公司", "岗位", "城市", "岗位类别", "行业", "意向", "投递阶段", "投递日期", "截止日期", "官方投递链接", "最后核验"];
    const rows = jobStates.map((state) => {
      const job = jobMap.get(state.jobId);
      return [
        state.snapshot.companyName,
        state.snapshot.title,
        state.snapshot.city,
        state.snapshot.roleCategory,
        state.snapshot.companyIndustry,
        INTEREST_LABELS[state.interest],
        STAGE_LABELS[state.stage],
        state.appliedAt ? formatDate(state.appliedAt) : "",
        job?.deadline ? formatDate(job.deadline) : "",
        state.snapshot.applyUrl,
        formatDateTime(state.snapshot.lastVerifiedAt),
      ];
    });
    const csv = [header, ...rows].map((row) => row.map(escapeCsvCell).join(",")).join("\r\n");
    downloadFile(`秋招助手进度-${new Date().toISOString().slice(0, 10)}.csv`, `\uFEFF${csv}`, "text/csv;charset=utf-8");
    showNotice("CSV 已生成，默认不包含面试笔记和自由文本备注。");
  };

  const importJson = async (file: File) => {
    try {
      const raw = parseBackup(JSON.parse(await file.text()));
      await replaceAllLocalData(raw.preferences, raw.jobStates, raw.events);
      showNotice(`已恢复 ${raw.jobStates.length} 条岗位记录和 ${raw.events.length} 条时间线事件。`);
    } catch {
      showNotice("备份文件无法识别；请确认使用的是秋招助手导出的 JSON。");
    }
  };

  const context = {
    jobs,
    campaigns,
    sources,
    directoryCompanies,
    communityLeads,
    jobMap,
    stateMap,
    jobStates,
    events,
    preferences,
    catalogLoading,
    offlineCatalog,
    manifest,
    openJob,
    updateInterest,
    updateStage,
    toggleEventComplete,
    showNotice,
    businessDate,
    todayPublishedJobCount,
    provisionalJobCount: provisionalCatalog?.summary?.jobCount ?? provisionalCatalog?.jobs.length ?? 0,
    lastVisitAt: lastVisitRef.current,
  };

  return (
    <div className="app-shell ink-overhaul" style={{
      "--ink-route-image": `url("${routeVisualAsset(route)}")`,
      "--ink-route-mobile-image": `url("${routeVisualAsset(route, true)}")`,
      "--ink-paper-image": `url("${assetPath("assets/visuals/paper-texture.webp")}")`,
      "--ink-section-rule-image": `url("${assetPath("assets/visuals/ink-section-rule.webp")}")`,
      "--ink-frame-supplement": `url("${assetPath("assets/visuals/ink-frame-supplement.webp")}")`,
      "--ink-stage-route-supplement": `url("${assetPath("assets/visuals/ink-stage-route-supplement.webp")}")`,
      "--ink-wash-right-supplement": `url("${assetPath("assets/visuals/ink-wash-right-supplement.webp")}")`,
      "--company-band-art": `url("${assetPath("assets/visuals/company-band-ink-landscape.webp")}")`,
      "--ink-timeline-supplement": `url("${assetPath("assets/visuals/ink-timeline-supplement.webp")}")`,
      "--ink-stage-stamp-supplement": `url("${assetPath("assets/visuals/ink-stage-stamp-supplement.webp")}")`,
      "--ink-paper-supplement": `url("${assetPath("assets/visuals/paper-texture-supplement.webp")}")`,
    } as CSSProperties}>
      <div className="main-column">
        <a className="skip-to-content" href="#main-content">跳到主要内容</a>
        <GlobalHeader route={route} navigate={navigate} offlineCatalog={offlineCatalog} demoCatalog={demoCatalog} />
        {(offlineCatalog || demoCatalog) && !catalogBannerDismissed && <div className={`catalog-banner ${offlineCatalog ? "is-offline" : ""}`}><div className="catalog-banner-content"><span className="catalog-banner-mark" aria-hidden="true"><BrandMark compact /></span><Info size={16} /><span>{offlineCatalog ? "当前网络不可用，正在使用上次缓存的目录，数据可能不是最新。" : "当前目录含演示快照，正式发布前会由采集器完成官方来源核验，岗位请以企业官网为准。"}</span><button className="text-button" onClick={() => navigate("settings")}>查看数据说明 <ChevronRight size={14} /></button></div><button className="icon-button catalog-banner-dismiss" aria-label="关闭目录提示" onClick={() => setCatalogBannerDismissed(true)}><X size={15} /></button></div>}
        {route === "jobs" && !audienceBannerDismissed && <div className="catalog-banner audience-scope-banner"><div className="catalog-banner-content"><Target size={16} /><span>公共岗位库聚焦文科、社科、商科及不限专业的通用校招岗位；具体专业要求以企业官网为准。</span><button className="text-button" onClick={() => navigate("settings")}>查看筛选口径 <ChevronRight size={14} /></button></div><button className="icon-button catalog-banner-dismiss" aria-label="关闭岗位口径提示" onClick={() => setAudienceBannerDismissed(true)}><X size={15} /></button></div>}
        {route === "jobs" && provisionalCatalog && preferences.showProvisionalJobs && !provisionalBannerDismissed && <div className="catalog-banner provisional-jobs-banner"><div className="catalog-banner-content"><Sparkles size={16} /><span>已加入 {provisionalCatalog.jobs.length} 条公开入口岗位（{provisionalCatalog.summary?.companyCount ?? "多"} 家公司）。{provisionalDisclosure} 可直接打开来源核对。</span><button className="text-button" onClick={() => navigate("settings")}>查看说明 <ChevronRight size={14} /></button></div><button className="icon-button catalog-banner-dismiss" aria-label="关闭临时岗位提示" onClick={() => setProvisionalBannerDismissed(true)}><X size={15} /></button></div>}
        <main id="main-content" className="page-content">
          {route === "jobs" && <JobsPage {...context} newCount={newCount} soonCount={soonCount} matchedCount={matchedCount} activeTrackedCount={activeTrackedCount} />}
          {route === "progress" && <ProgressPage {...context} />}
          {route === "schedule" && <SchedulePage {...context} />}
          {route === "settings" && <SettingsPage {...context} exportJson={exportJson} exportCsv={exportCsv} importJson={importJson} />}
        </main>
      </div>
      <MobileBottomNavigation route={route} navigate={navigate} />
      {selectedJob && <JobModal job={selectedJob} historical={!jobMap.has(selectedJob.id)} state={stateMap.get(selectedJob.id)} events={events.filter((event) => event.jobId === selectedJob.id)} loading={detailLoading} onClose={closeJob} onInterest={(interest) => updateInterest(selectedJob, interest)} onStage={(stage) => updateStage(selectedJob, stage)} onEvent={async (event) => { await addEvent(event); showNotice("时间线事件已保存到本地。"); }} onToggleEvent={toggleEventComplete} />}
      {onboardingOpen && <Onboarding preferences={preferences} onSave={saveOnboarding} onSkip={() => saveOnboarding({ ...preferences, setupComplete: true })} />}
      {notice && <div className="toast" role="status" aria-live="polite"><CheckCircle2 size={17} /><span>{notice}</span><button type="button" aria-label="关闭提示" onClick={() => setNotice(null)}><X size={15} /></button></div>}
      {updateReady && <div className="update-toast" role="status" aria-live="polite"><span>有新的目录版本可用。</span><button onClick={() => window.location.reload()}>刷新</button><button className="icon-button" aria-label="关闭更新提示" onClick={() => setUpdateReady(false)}><X size={15} /></button></div>}
    </div>
  );
}

type SharedPageProps = {
  jobs: JobPosting[];
  campaigns: RecruitmentCampaign[];
  sources: PublicSourceSummary[];
  directoryCompanies: CompanyDirectoryCompany[];
  communityLeads: CommunityLead[];
  jobMap: Map<string, JobPosting>;
  stateMap: Map<string, UserJobState>;
  jobStates: UserJobState[];
  events: ApplicationEvent[];
  preferences: Preferences;
  catalogLoading: boolean;
  offlineCatalog: boolean;
  manifest: CatalogManifest | null;
  openJob: (job: JobPosting) => void;
  updateInterest: (job: JobPosting, interest: Interest) => Promise<void>;
  updateStage: (job: JobPosting, stage: Stage) => Promise<void>;
  toggleEventComplete: (event: ApplicationEvent) => Promise<void>;
  showNotice: (message: string) => void;
  businessDate: string;
  todayPublishedJobCount: number;
  provisionalJobCount: number;
  lastVisitAt: string;
};

function selectOptions(items: string[], allLabel: string): SelectOption[] {
  return [{ value: "__all__", label: allLabel }, ...items.map((item) => ({ value: item, label: item }))];
}

function demoCatalogLabel(catalogLoading: boolean): string {
  return catalogLoading ? "正在读取目录" : "公开来源优先";
}

function matchReasons(job: JobPosting, preferences: Preferences): string[] {
  const reasons: string[] = [];
  const preferredCity = locationsForJob(job).find((location) => preferences.cities.includes(location.displayName) || preferences.cities.includes(location.raw) || Boolean(location.cityCode && preferences.cityCodes?.includes(location.cityCode)));
  if (preferredCity) reasons.push(preferredCity.displayName);
  if (preferences.roles.includes(job.roleCategory)) reasons.push(job.roleCategory);
  if (preferences.companyTypes.includes(job.companyType)) reasons.push(job.companyType);
  if (preferences.cohort && job.cohort === preferences.cohort) reasons.push(`${job.cohort} 届`);
  return reasons.slice(0, 3);
}

type CompanyJobGroup = {
  companyName: string;
  companyId: string;
  jobs: JobPosting[];
  directory?: CompanyDirectoryCompany;
};

/**
 * Company segments are discovery metadata, not a second copy of the job
 * taxonomy.  Existing catalog snapshots may not have the optional fields, so
 * the helper deliberately falls back to the company industry for a stable,
 * useful filter value instead of inventing a segment from the job title.
 */
function companySegment(company?: CompanyDirectoryCompany, fallback?: string): string {
  const radar = company?.hiringRadar;
  const radarSegment = radar && typeof radar === "object" && !Array.isArray(radar)
    ? (radar as { segment?: unknown }).segment
    : undefined;
  const value = company?.focusSegment ?? company?.authoritySegment ?? radarSegment ?? fallback;
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

type EntryStatusFilter = "" | "OFFICIAL" | "ENTRY_LEAD" | "SYNCED" | "ENTRY_ONLY";

function groupEntryStatus(group: CompanyJobGroup): Exclude<EntryStatusFilter, ""> {
  if (group.jobs.length > 0) return "SYNCED";
  return group.directory?.directory?.entryType === "ENTRY_LEAD" ? "ENTRY_LEAD" : "OFFICIAL";
}

function matchesEntryStatus(group: CompanyJobGroup, filter: EntryStatusFilter): boolean {
  if (!filter) return true;
  if (filter === "SYNCED") return group.jobs.length > 0;
  if (filter === "ENTRY_ONLY") return group.jobs.length === 0;
  if (filter === "ENTRY_LEAD") return group.jobs.length === 0 && groupEntryStatus(group) === "ENTRY_LEAD";
  // Concrete jobs can only come from a reviewed source, so they count as an
  // official entry even when an old directory snapshot has no company row.
  // A lead-only company remains excluded from this filter.
  return group.jobs.length > 0 || groupEntryStatus(group) === "OFFICIAL";
}

const LEGACY_OVERSEAS_CITIES = new Set(["东京", "大阪", "新加坡", "纽约", "伦敦", "巴黎", "悉尼", "多伦多", "温哥华", "旧金山", "洛杉矶", "首尔", "迪拜", "墨尔本", "曼谷", "吉隆坡", "雅加达", "胡志明", "马尼拉", "莫斯科", "圣保罗", "波哥大", "布宜诺斯艾利斯", "华沙", "鹿特丹", "马德里", "慕尼黑", "西雅图", "帕罗奥多", "杜塞尔多夫"]);
const LEGACY_CITY_PROVINCE: Record<string, string> = {
  北京: "BJ", 上海: "SH", 天津: "TJ", 重庆: "CQ", 广州: "GD", 深圳: "GD", 珠海: "GD", 东莞: "GD", 惠州: "GD", 肇庆: "GD",
  武汉: "HB", 成都: "SC", 济南: "SD", 青岛: "SD", 德州: "SD", 崂山区: "SD", 杭州: "ZJ", 宁波: "ZJ", 南京: "JS", 苏州: "JS", 昆山: "JS", 建邺区: "JS",
  合肥: "AH", 郑州: "HA", 长沙: "HN", 南昌: "JX", 福州: "FJ", 厦门: "FJ", 泉州: "FJ", 莆田: "FJ", 宁德: "FJ", 南平: "FJ", 龙岩: "FJ",
  西安: "SN", 昆明: "YN", 太原: "SX", 石家庄: "HEB", 廊坊: "HEB", 固安县: "HEB", 沈阳: "LN", 大连: "LN", 长春: "JL", 白城: "JL", 南宁: "GX", 柳州: "GX",
  贵阳: "GZ", 兰州: "GS", 海口: "HI", 乌鲁木齐: "XJ", 五家渠: "XJ", 头屯河区: "XJ", 呼和浩特: "NMG", 通辽: "NMG", 大同: "SX", 房山区: "BJ", 广阳区: "HEB", 嘉定区: "SH",
};
const LEGACY_CITY_PARENT: Record<string, string> = { 嘉定区: "上海", 浦东新区: "上海", 黄浦区: "上海", 海淀区: "北京", 朝阳区: "北京", 天河区: "广州", 南山区: "深圳", 福田区: "深圳", 洪山区: "武汉", 建邺区: "南京", 崂山区: "青岛", 广阳区: "廊坊", 房山区: "北京", 头屯河区: "乌鲁木齐", 固安县: "廊坊" };
const LEGACY_OVERSEAS_COUNTRIES: Record<string, string> = {
  东京: "JP", 大阪: "JP", 新加坡: "SG", 纽约: "US", 伦敦: "GB", 巴黎: "FR", 悉尼: "AU", 多伦多: "CA", 温哥华: "CA", 旧金山: "US", 洛杉矶: "US", 首尔: "KR", 迪拜: "AE", 墨尔本: "AU", 曼谷: "TH", 吉隆坡: "MY", 雅加达: "ID", 胡志明: "VN", 马尼拉: "PH", 莫斯科: "RU", 圣保罗: "BR", 波哥大: "CO", 布宜诺斯艾利斯: "AR", 华沙: "PL", 鹿特丹: "NL", 马德里: "ES", 慕尼黑: "DE", 西雅图: "US", 帕罗奥多: "US", 杜塞尔多夫: "DE",
};
const COUNTRY_LABELS: Record<string, string> = { JP: "日本", SG: "新加坡", US: "美国", GB: "英国", FR: "法国", AU: "澳大利亚", CA: "加拿大", KR: "韩国", AE: "阿联酋", TH: "泰国", MY: "马来西亚", ID: "印度尼西亚", VN: "越南", PH: "菲律宾", RU: "俄罗斯", BR: "巴西", CO: "哥伦比亚", AR: "阿根廷", PL: "波兰", NL: "荷兰", ES: "西班牙", DE: "德国" };

function locationsForJob(job: Pick<JobPosting, "city" | "locations">): JobLocation[] {
  if (job.locations?.length) return job.locations;
  return splitCities(job.city).map((city) => {
    const overseas = LEGACY_OVERSEAS_CITIES.has(city);
    const countryCode = LEGACY_OVERSEAS_COUNTRIES[city];
    return {
      scope: overseas ? "OVERSEAS" : "MAINLAND_CHINA",
      countryCode,
      provinceCode: LEGACY_CITY_PROVINCE[city],
      cityCode: city ? `${LEGACY_CITY_PROVINCE[city] ?? "UNKNOWN"}-${city}` : undefined,
      displayName: overseas && countryCode ? `${COUNTRY_LABELS[countryCode] ?? countryCode} · ${city}` : LEGACY_CITY_PARENT[city] ? `${LEGACY_CITY_PARENT[city]} · ${city}` : city || "地点待确认",
      raw: city || job.city,
    };
  });
}

function groupJobsByCompany(jobs: JobPosting[], sort: string = "company", preferences?: Preferences, directoryById?: Map<string, CompanyDirectoryCompany>): CompanyJobGroup[] {
  const grouped = new Map<string, CompanyJobGroup>();
  jobs.forEach((job) => {
    const current = grouped.get(job.companyId) ?? { companyName: job.companyName, companyId: job.companyId, jobs: [], directory: directoryById?.get(job.companyId) };
    current.jobs.push(job);
    grouped.set(job.companyId, current);
  });
  const compareJobs = (a: JobPosting, b: JobPosting) => {
    if (sort === "deadline") return (a.deadline ?? "9999").localeCompare(b.deadline ?? "9999") || (b.publishDate ?? "").localeCompare(a.publishDate ?? "");
    if (sort === "match" && preferences) return Number(matchesPreferences(b, preferences)) - Number(matchesPreferences(a, preferences)) || (b.publishDate ?? "").localeCompare(a.publishDate ?? "");
    return (b.publishDate ?? "").localeCompare(a.publishDate ?? "") || a.title.localeCompare(b.title, "zh-CN");
  };
  const groups = [...grouped.values()].map((group) => ({ ...group, jobs: group.jobs.slice().sort(compareJobs) }));
  return groups.sort((a, b) => {
    if (sort === "company") return a.companyName.localeCompare(b.companyName, "zh-CN");
    if (sort === "open") {
      const aDate = a.directory?.directory?.firstConfirmedAt || a.jobs[0]?.firstSeenAt || "";
      const bDate = b.directory?.directory?.firstConfirmedAt || b.jobs[0]?.firstSeenAt || "";
      return String(bDate).localeCompare(String(aDate)) || a.companyName.localeCompare(b.companyName, "zh-CN");
    }
    return compareJobs(a.jobs[0], b.jobs[0]) || a.companyName.localeCompare(b.companyName, "zh-CN");
  });
}

type TodayMode = "campaigns" | "published" | "firstSeen";

const LOCATION_SCOPE_LABELS: Record<LocationScope, string> = {
  MAINLAND_CHINA: "中国大陆",
  HONG_KONG_MACAU_TAIWAN: "港澳台",
  OVERSEAS: "海外",
  REMOTE: "远程",
  UNKNOWN: "地点待确认",
};

const PROVINCE_LABELS: Record<string, string> = {
  BJ: "北京市", SH: "上海市", TJ: "天津市", CQ: "重庆市", GD: "广东省", HB: "湖北省", ZJ: "浙江省", JS: "江苏省",
  AH: "安徽省", SC: "四川省", SN: "陕西省", HA: "河南省", HN: "湖南省", SD: "山东省", FJ: "福建省", LN: "辽宁省",
  HLJ: "黑龙江省", JX: "江西省", YN: "云南省", HEB: "河北省", GX: "广西壮族自治区", GZ: "贵州省", JL: "吉林省", SX: "山西省",
  NMG: "内蒙古自治区", XJ: "新疆维吾尔自治区", GS: "甘肃省", HI: "海南省", NX: "宁夏回族自治区", QH: "青海省", XZ: "西藏自治区",
};

function locationScopeFor(job: JobPosting): LocationScope {
  return job.locations?.[0]?.scope ?? "UNKNOWN";
}

/* Legacy TodayLaunchSection was intentionally removed from the jobs page.
   The hero keeps the three date metrics; the large Today rail no longer renders.
  const todayCampaigns = campaigns.filter((campaign) => campaign.openDate === businessDate && campaign.status === "OPEN");
  // Keep the user's selected date meaning stable even when the count is zero.
  // An empty campaign tab is useful evidence, not a reason to silently switch
  // to a different date definition.
  const [mode, setMode] = useState<TodayMode>("campaigns");
  const tabRefs = useRef<Record<TodayMode, HTMLButtonElement | null>>({ campaigns: null, published: null, firstSeen: null });
  const tabOrder: TodayMode[] = ["campaigns", "published", "firstSeen"];
  const publishedJobs = jobs.filter((job) => job.status === "ACTIVE" && (job.publishDateSource === "OFFICIAL" || job.publishDateSource === "DEMO") && localDay(job.publishDate) === businessDate);
  const firstSeenJobs = jobs.filter((job) => job.status === "ACTIVE" && localDay(job.firstSeenAt) === businessDate);
  const modeJobs = mode === "published" ? publishedJobs : firstSeenJobs;
  const companyGroups = groupJobsByCompany(modeJobs);
  const moveTab = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!(["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key))) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabOrder.length - 1 : (index + (event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1) + tabOrder.length) % tabOrder.length;
    const next = tabOrder[nextIndex];
    setMode(next);
    window.setTimeout(() => tabRefs.current[next]?.focus(), 0);
  };
  return <section className="today-launch" id="today-launch" aria-labelledby="today-launch-title">
    <div className="today-launch-heading">
        <div className="today-launch-copy">
          <div className="today-kicker"><span className="date-chip">{businessDate.replaceAll("-", ".")}</span></div>
          <h2 id="today-launch-title">今日新开</h2>
      </div>
      <div className="today-date-lockup"><strong>{businessDate.slice(5).replace("-", " / ")}</strong></div>
    </div>
    <div className="today-tabs" role="tablist" aria-label="今日新开分类">
      <button id="today-tab-campaigns" ref={(node) => { tabRefs.current.campaigns = node; }} role="tab" tabIndex={mode === "campaigns" ? 0 : -1} aria-selected={mode === "campaigns"} aria-controls="today-panel-campaigns" className={mode === "campaigns" ? "is-active" : ""} onClick={() => setMode("campaigns")} onKeyDown={(event) => moveTab(event, 0)}><Building2 size={16} /><span>今日开放校招</span><b>{todayCampaigns.length}</b></button>
      <button id="today-tab-published" ref={(node) => { tabRefs.current.published = node; }} role="tab" tabIndex={mode === "published" ? 0 : -1} aria-selected={mode === "published"} aria-controls="today-panel-published" className={mode === "published" ? "is-active" : ""} onClick={() => setMode("published")} onKeyDown={(event) => moveTab(event, 1)}><Sparkles size={16} /><span>今日发布岗位</span><b>{publishedJobs.length}</b></button>
      <button id="today-tab-firstSeen" ref={(node) => { tabRefs.current.firstSeen = node; }} role="tab" tabIndex={mode === "firstSeen" ? 0 : -1} aria-selected={mode === "firstSeen"} aria-controls="today-panel-firstSeen" className={mode === "firstSeen" ? "is-active" : ""} onClick={() => setMode("firstSeen")} onKeyDown={(event) => moveTab(event, 2)}><Clock3 size={16} /><span>今日首次收录</span><b>{firstSeenJobs.length}</b></button>
    </div>
    {mode === "campaigns" ? <div id="today-panel-campaigns" className="campaign-grid" role="tabpanel" aria-labelledby="today-tab-campaigns" tabIndex={0}>
      {todayCampaigns.length ? todayCampaigns.map((campaign) => {
        const campaignJobs = campaign.jobIds.map((id) => jobs.find((job) => job.id === id)).filter((job): job is JobPosting => Boolean(job && job.status === "ACTIVE"));
        return <article className={`campaign-card ${todayCampaigns[0]?.id === campaign.id ? "is-featured" : ""}`} key={campaign.id}>
          <div className="campaign-card-head"><CompanyLogo companyId={campaign.companyId} companyName={campaign.companyName} size="today" /><div><strong>{campaign.companyName}</strong><span>{campaign.name}</span></div><span className="open-pill">今天开放</span></div>
          <div className="campaign-card-meta"><span><CalendarRange size={14} />{campaign.openDate} 开放</span><span><Clock3 size={14} />{campaign.deadline ? `${campaign.deadline} 截止` : "截止日待确认"}</span></div>
          <div className="campaign-job-list">{campaignJobs.map((job) => <button key={job.id} onClick={() => openJob(job)}><span>{job.title}</span><ChevronRight size={15} /></button>)}</div>
          <a href={campaign.officialUrl} target="_blank" rel="noreferrer" className="source-link">查看官方活动页 <ExternalLink size={13} /></a>
        </article>;
      }) : <TodayEmpty text="今天暂未发现官网明确开放的校招活动。" />}
    </div> : <div id={`today-panel-${mode}`} className="today-company-grid" role="tabpanel" aria-labelledby={`today-tab-${mode}`} tabIndex={0}>
      {companyGroups.length ? companyGroups.map((group, index) => <article className={`today-company-card ${index === 0 ? "is-featured" : ""}`} key={group.companyId}>
        <div className="today-company-head"><CompanyLogo companyId={group.companyId} companyName={group.companyName} size="today" /><div><strong>{group.companyName}</strong><span>{group.jobs.length} 个岗位</span></div></div>
        <div className="campaign-job-list">{group.jobs.map((job) => <button key={job.id} onClick={() => openJob(job)}><span>{job.title}<small>{displayLocations(job)} · {job.roleCategory}</small></span><ChevronRight size={15} /></button>)}</div>
      </article>) : <TodayEmpty text={mode === "published" ? "今天暂未发现官网明确发布的岗位。" : "今天暂未发现新收录岗位。"} />}
    </div>}
  </section>;
}

function TodayEmpty({ text }: { text: string }) {
  return <div className="today-empty-state"><div className="empty-icon"><CalendarDays size={22} /></div><strong>{text}</strong><span>可以先用下方筛选浏览全部仍在开放的校招岗位。</span></div>;
}

*/
function JobsPage(props: SharedPageProps & { newCount: number; soonCount: number; matchedCount: number; activeTrackedCount: number }) {
  const { jobs, stateMap, preferences, catalogLoading, openJob, updateInterest, updateStage, campaigns, businessDate, lastVisitAt, directoryCompanies, manifest, provisionalJobCount } = props;
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [locationScope, setLocationScope] = useState<LocationScope | "">("MAINLAND_CHINA");
  const [provinceCodes, setProvinceCodes] = useState<string[]>([]);
  const [countryCode, setCountryCode] = useState("");
  const [cityCodes, setCityCodes] = useState<string[]>([]);
  const [roles, setRoles] = useState<RoleCategory[]>([]);
  const [industry, setIndustry] = useState("");
  const [segment, setSegment] = useState("");
  const [entryStatus, setEntryStatus] = useState<EntryStatusFilter>("");
  const [companyType, setCompanyType] = useState("");
  const [cohort, setCohort] = useState("");
  const [batch, setBatch] = useState("");
  const [education, setEducation] = useState("");
  const [companyScale, setCompanyScale] = useState("");
  const [publishFrom, setPublishFrom] = useState("");
  const [publishTo, setPublishTo] = useState("");
  const [deadlineFrom, setDeadlineFrom] = useState("");
  const [deadlineTo, setDeadlineTo] = useState("");
  const [stage, setStage] = useState("");
  const [interest, setInterest] = useState("");
  const [onlySoon, setOnlySoon] = useState(false);
  const [onlyMatched, setOnlyMatched] = useState(false);
  const [includeEntryCompanies, setIncludeEntryCompanies] = useState(true);
  const [sort, setSort] = useState("latest");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [expandedCompanies, setExpandedCompanies] = useState<Set<string>>(new Set());
  const filterTriggerRef = useRef<HTMLButtonElement>(null);
  const filterPanelRef = useRef<HTMLElement>(null);
  const normalizedDirectoryCompanies = useMemo(() => directoryCompanies.map((company, index) => {
    if (company.directory || !company.careerUrl) return company;
    return {
      ...company,
      directory: {
        companyId: company.id,
        cohort: "2027",
      directoryStatus: isPublishableSourceStatus(company.sourceStatus) ? "ACTIVE_CONFIRMED" as const : "ACTIVE_LEAD" as const,
      entryType: isPublishableSourceStatus(company.sourceStatus) ? "OFFICIAL_CAREER_SITE" as const : "ENTRY_LEAD" as const,
        careerUrl: company.careerUrl,
        evidenceUrl: company.careerUrl,
        evidenceText: company.sourceStatus === "AUTO_VERIFIED" ? "官方公开来源已完成自动核验。" : company.sourceStatus === "VERIFIED" ? "官方校园招聘来源已完成人工核验。" : "已登记公开招聘入口，当前届校招信号待确认。",
        detectedSignals: ["2027 届校招入口已登记"],
        directorySource: "companies.json",
        directoryRank: index + 1,
        lastCheckedAt: new Date().toISOString(),
      } satisfies CampusRecruitmentEntry,
    };
  }), [directoryCompanies]);
  const directoryById = useMemo(() => new Map(normalizedDirectoryCompanies.map((company) => [company.id, company])), [normalizedDirectoryCompanies]);
  const activeDirectoryCompanies = useMemo(() => normalizedDirectoryCompanies.filter((company) => {
    const status = company.directory?.directoryStatus;
    return status === "ACTIVE_CONFIRMED" || status === "ACTIVE_LEAD";
  }), [normalizedDirectoryCompanies]);
  const directoryOverview = useMemo(() => {
    const syncedCompanyIds = new Set(jobs.filter((job) => job.status === "ACTIVE" && job.cohort === "2027").map((job) => job.companyId));
    const recruiting = manifest?.companyDirectory?.activeRecruitingCompanyCount ?? activeDirectoryCompanies.length;
    const syncedCompanies = manifest?.companyDirectory?.companiesWithEligibleJobs ?? syncedCompanyIds.size;
    return {
      recruiting,
      syncedJobs: jobs.filter((job) => job.status === "ACTIVE").length,
      entryOnly: Math.max(recruiting - syncedCompanies, 0),
      official: manifest?.companyDirectory?.officialEntryCount ?? activeDirectoryCompanies.filter((company) => company.directory?.entryType !== "ENTRY_LEAD").length,
      leads: manifest?.companyDirectory?.entryLeadCount ?? activeDirectoryCompanies.filter((company) => company.directory?.entryType === "ENTRY_LEAD").length,
    };
  }, [activeDirectoryCompanies, jobs, manifest]);
  const todayCampaignCount = manifest?.todayCampaignCount ?? campaigns.filter((campaign) => campaign.openDate === businessDate && campaign.status === "OPEN").length;
  const todayPublishedCount = manifest?.todayPublishedJobCount ?? jobs.filter((job) => job.status === "ACTIVE" && (job.publishDateSource === "OFFICIAL" || job.publishDateSource === "DEMO") && localDay(job.publishDate) === businessDate).length;
  const todayFirstSeenCount = manifest?.todayFirstSeenCount ?? jobs.filter((job) => job.status === "ACTIVE" && localDay(job.firstSeenAt) === businessDate).length;
  const industries = useMemo(() => [...new Set(jobs.map((job) => job.companyIndustry))].sort(), [jobs]);
  const segments = useMemo(() => {
    const values = new Set<string>();
    jobs.forEach((job) => {
      const company = directoryById.get(job.companyId);
      const value = companySegment(company, job.companyIndustry);
      if (value) values.add(value);
    });
    activeDirectoryCompanies.forEach((company) => {
      const value = companySegment(company, company.industry);
      if (value) values.add(value);
    });
    return [...values].sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [activeDirectoryCompanies, directoryById, jobs]);
  const entryStatusOptions: SelectOption[] = [
    { value: "OFFICIAL", label: "官方入口" },
    { value: "ENTRY_LEAD", label: "入口线索·待确认" },
    { value: "SYNCED", label: "已同步岗位" },
    { value: "ENTRY_ONLY", label: "仅入口公司" },
  ];
  const publicRoleCategories = useMemo(() => {
    const available = new Set(jobs.map((job) => job.roleCategory));
    return available.size ? PUBLIC_ROLE_CATEGORIES.filter((category) => available.has(category)) : [...PUBLIC_ROLE_CATEGORIES];
  }, [jobs]);
  const locationRecords = useMemo(() => jobs.flatMap((job) => locationsForJob(job)), [jobs]);
  const mainlandProvinceOptions = useMemo(() => [...new Set(locationRecords.filter((item) => item.scope === "MAINLAND_CHINA" && item.provinceCode).map((item) => item.provinceCode as string))].sort().map((value) => ({ value, label: PROVINCE_LABELS[value] ?? value })), [locationRecords]);
  const countryOptions = useMemo(() => [...new Map(locationRecords.filter((item) => item.scope === "OVERSEAS" && item.countryCode).map((item) => [item.countryCode, { value: item.countryCode as string, label: item.displayName.split(" · ")[0] || item.countryCode as string }])).values()].sort((a, b) => a.label.localeCompare(b.label, "zh-CN")), [locationRecords]);
  const countrySelectOptions = useMemo(() => [{ value: "__all__", label: "全部国家/地区" }, ...countryOptions], [countryOptions]);
  const provinceSet = useMemo(() => new Set(provinceCodes), [provinceCodes]);
  const citySet = useMemo(() => new Set(cityCodes), [cityCodes]);
  const isNationwideLocation = (item: JobLocation) => item.scope === "MAINLAND_CHINA" && /全国/.test(`${item.displayName} ${item.raw}`);
  const cityOptions = useMemo(() => {
    const records = locationRecords.filter((item) => (!locationScope || item.scope === locationScope) && (!countryCode || item.countryCode === countryCode) && (!provinceCodes.length || isNationwideLocation(item) || (item.provinceCode && provinceSet.has(item.provinceCode))));
    return [...new Map(records.filter((item) => item.displayName && item.cityCode && !isNationwideLocation(item)).map((item) => [item.cityCode as string, { value: item.cityCode as string, label: item.displayName }])).values()].sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
  }, [countryCode, locationRecords, locationScope, provinceCodes.length, provinceSet]);
  const locationMatches = useCallback((job: JobPosting) => locationsForJob(job).some((item) => {
    if (locationScope && item.scope !== locationScope) return false;
    if (countryCode && item.countryCode !== countryCode) return false;
    if (provinceCodes.length && !isNationwideLocation(item) && (!item.provinceCode || !provinceSet.has(item.provinceCode))) return false;
    if (cityCodes.length && !isNationwideLocation(item) && (!item.cityCode || !citySet.has(item.cityCode))) return false;
    return true;
  }), [cityCodes.length, citySet, countryCode, locationScope, provinceCodes.length, provinceSet]);

  const filteredJobs = useMemo(() => {
    const query = deferredSearch.trim().toLowerCase();
    return jobs.filter((job) => {
      const userState = stateMap.get(job.id);
      const company = directoryById.get(job.companyId);
      const jobSegment = companySegment(company, job.companyIndustry);
      const haystack = [job.companyName, job.title, displayLocations(job), job.roleCategory, job.companyIndustry, jobSegment, ...job.skills, ...job.majorTags].join(" ").toLowerCase();
      return (!query || haystack.includes(query)) && locationMatches(job) && (!roles.length || roles.includes(job.roleCategory)) && (!industry || job.companyIndustry === industry) && (!segment || jobSegment === segment) && (!companyType || job.companyType === companyType) && (!companyScale || job.companyScale === companyScale) && (!cohort || job.cohort === cohort) && (!batch || job.batch === batch) && (!education || job.education === education) && (!publishFrom || Boolean(job.publishDate && job.publishDate >= publishFrom)) && (!publishTo || Boolean(job.publishDate && job.publishDate <= publishTo)) && (!deadlineFrom || Boolean(job.deadline && job.deadline >= deadlineFrom)) && (!deadlineTo || Boolean(job.deadline && job.deadline <= deadlineTo)) && (!stage || userState?.stage === stage) && (!interest || userState?.interest === interest) && (!onlySoon || isDeadlineSoon(job.deadline)) && (!onlyMatched || matchesPreferences(job, preferences));
    }).sort((a, b) => {
      if (sort === "deadline") return (a.deadline ?? "9999").localeCompare(b.deadline ?? "9999");
      if (sort === "company") return a.companyName.localeCompare(b.companyName, "zh-CN");
      if (sort === "match") return Number(matchesPreferences(b, preferences)) - Number(matchesPreferences(a, preferences));
      if (sort === "open") return String(b.firstSeenAt || "").localeCompare(String(a.firstSeenAt || ""));
      return (b.publishDate ?? "").localeCompare(a.publishDate ?? "");
    });
  }, [batch, companyScale, companyType, cohort, countryCode, deadlineFrom, deadlineTo, deferredSearch, directoryById, education, industry, interest, jobs, locationMatches, onlyMatched, onlySoon, preferences, publishFrom, publishTo, roles, segment, sort, stage, stateMap]);
  const companyGroups = useMemo(() => {
    const allJobGroups = groupJobsByCompany(filteredJobs, sort, preferences, directoryById);
    const jobGroups = allJobGroups
      .filter((group) => matchesEntryStatus(group, entryStatus))
      .filter((group) => {
        const company = group.directory;
        const groupIndustry = company?.industry || group.jobs[0]?.companyIndustry || "";
        const groupType = company?.type || group.jobs[0]?.companyType || "";
        const groupScale = company?.scale || group.jobs[0]?.companyScale || "";
        const groupSegment = companySegment(company, groupIndustry);
        return (!industry || groupIndustry === industry)
          && (!companyType || groupType === companyType)
          && (!companyScale || groupScale === companyScale)
          && (!segment || groupSegment === segment);
      });
    const query = deferredSearch.trim().toLowerCase();
    const hasJobSpecificFilters = Boolean(
      (locationScope && locationScope !== "MAINLAND_CHINA") || countryCode || provinceCodes.length || cityCodes.length || roles.length || cohort || batch || education
      || publishFrom || publishTo || deadlineFrom || deadlineTo || stage || interest || onlySoon || onlyMatched,
    );
    // Keep companies that have concrete jobs from being misclassified as
    // entry-only just because an entry-status filter removed their job group.
    const jobCompanyIds = new Set(allJobGroups.map((group) => group.companyId));
    const entryOnlyGroups = activeDirectoryCompanies
      .filter(() => includeEntryCompanies)
      .filter((company) => !jobCompanyIds.has(company.id))
      .filter((company) => !hasJobSpecificFilters)
      .filter((company) => !industry || company.industry === industry)
      .filter((company) => !segment || companySegment(company, company.industry) === segment)
      .filter((company) => !companyType || company.type === companyType)
      .filter((company) => !companyScale || company.scale === companyScale)
      .filter((company) => matchesEntryStatus({ companyName: company.name, companyId: company.id, jobs: [], directory: company }, entryStatus))
      .filter((company) => {
        if (!query) return true;
        const haystack = [company.name, company.industry, companySegment(company, company.industry), ...(company.aliases ?? [])].join(" ").toLowerCase();
        return haystack.includes(query);
      })
      .map((company) => ({ companyName: company.name, companyId: company.id, jobs: [], directory: company } satisfies CompanyJobGroup));
    const merged = [...jobGroups, ...entryOnlyGroups];
    if (sort === "company") return merged.sort((a, b) => a.companyName.localeCompare(b.companyName, "zh-CN"));
    return merged.sort((a, b) => {
      if (a.jobs.length === 0 && b.jobs.length > 0) return 1;
      if (b.jobs.length === 0 && a.jobs.length > 0) return -1;
      if (sort === "open") {
        const aDate = a.directory?.directory?.firstConfirmedAt || a.jobs[0]?.firstSeenAt || "";
        const bDate = b.directory?.directory?.firstConfirmedAt || b.jobs[0]?.firstSeenAt || "";
        return String(bDate).localeCompare(String(aDate)) || a.companyName.localeCompare(b.companyName, "zh-CN");
      }
      return a.companyName.localeCompare(b.companyName, "zh-CN");
    });
  }, [activeDirectoryCompanies, batch, cityCodes.length, cohort, companyScale, companyType, countryCode, deadlineFrom, deadlineTo, deferredSearch, directoryById, education, entryStatus, includeEntryCompanies, industry, interest, locationScope, onlyMatched, onlySoon, preferences, provinceCodes.length, publishFrom, publishTo, roles.length, segment, sort, stage, filteredJobs]);
  const resetFilters = () => { setLocationScope("MAINLAND_CHINA"); setProvinceCodes([]); setCountryCode(""); setCityCodes([]); setRoles([]); setIndustry(""); setSegment(""); setEntryStatus(""); setCompanyType(""); setCompanyScale(""); setCohort(""); setBatch(""); setEducation(""); setPublishFrom(""); setPublishTo(""); setDeadlineFrom(""); setDeadlineTo(""); setStage(""); setInterest(""); setOnlySoon(false); setOnlyMatched(false); setIncludeEntryCompanies(true); setSearch(""); setExpandedCompanies(new Set()); };
  const activeFilterCount = [locationScope !== "MAINLAND_CHINA" ? locationScope : "", countryCode, industry, segment, entryStatus, companyType, companyScale, cohort, batch, education, publishFrom, publishTo, deadlineFrom, deadlineTo, stage, interest, onlySoon, onlyMatched].filter(Boolean).length + provinceCodes.length + cityCodes.length + roles.length;
  const activeFilterTags: Array<{ label: string; clear: () => void }> = [
    locationScope && locationScope !== "MAINLAND_CHINA" ? { label: `地区：${LOCATION_SCOPE_LABELS[locationScope]}`, clear: () => { setLocationScope("MAINLAND_CHINA"); setProvinceCodes([]); setCountryCode(""); setCityCodes([]); } } : null,
    ...provinceCodes.map((value) => ({ label: `省份：${PROVINCE_LABELS[value] ?? value}`, clear: () => { const next = provinceCodes.filter((item) => item !== value); setProvinceCodes(next); const allowed = new Set(locationRecords.filter((item) => !next.length || isNationwideLocation(item) || (item.provinceCode && next.includes(item.provinceCode))).map((item) => item.cityCode).filter(Boolean)); setCityCodes((current) => current.filter((item) => allowed.has(item))); } })),
    countryCode ? { label: `国家/地区：${COUNTRY_LABELS[countryCode] ?? countryCode}`, clear: () => { setCountryCode(""); setCityCodes([]); } } : null,
    ...cityCodes.map((value) => ({ label: `城市：${cityOptions.find((item) => item.value === value)?.label ?? value}`, clear: () => setCityCodes((current) => current.filter((item) => item !== value)) })),
    ...roles.map((value) => ({ label: `类别：${value}`, clear: () => setRoles((current) => current.filter((item) => item !== value)) })),
    industry ? { label: `行业：${industry}`, clear: () => setIndustry("") } : null,
    segment ? { label: `细分赛道：${segment}`, clear: () => setSegment("") } : null,
    entryStatus ? { label: `入口状态：${entryStatusOptions.find((item) => item.value === entryStatus)?.label ?? entryStatus}`, clear: () => setEntryStatus("") } : null,
    companyType ? { label: `类型：${companyType}`, clear: () => setCompanyType("") } : null,
    companyScale ? { label: `规模：${displayCompanyScale(companyScale)}`, clear: () => setCompanyScale("") } : null,
    cohort ? { label: `届别：${cohort}`, clear: () => setCohort("") } : null,
    batch ? { label: `批次：${batch}`, clear: () => setBatch("") } : null,
    education ? { label: `学历：${education}`, clear: () => setEducation("") } : null,
    publishFrom ? { label: `发布≥${publishFrom}`, clear: () => setPublishFrom("") } : null,
    publishTo ? { label: `发布≤${publishTo}`, clear: () => setPublishTo("") } : null,
    deadlineFrom ? { label: `截止≥${deadlineFrom}`, clear: () => setDeadlineFrom("") } : null,
    deadlineTo ? { label: `截止≤${deadlineTo}`, clear: () => setDeadlineTo("") } : null,
    stage ? { label: `阶段：${STAGE_LABELS[stage as Stage]}`, clear: () => setStage("") } : null,
    interest ? { label: `意向：${INTEREST_LABELS[interest as Interest]}`, clear: () => setInterest("") } : null,
    onlySoon ? { label: "7 天内截止", clear: () => setOnlySoon(false) } : null,
    onlyMatched ? { label: "符合偏好", clear: () => setOnlyMatched(false) } : null,
  ].filter((item): item is { label: string; clear: () => void } => Boolean(item));

  const toggleCompany = (companyId: string) => setExpandedCompanies((current) => { const next = new Set(current); if (next.has(companyId)) next.delete(companyId); else next.add(companyId); return next; });
  useEffect(() => {
    if (!filtersOpen) {
      filterTriggerRef.current?.focus({ preventScroll: true });
      return;
    }
    const timer = window.setTimeout(() => {
      const firstControl = filterPanelRef.current?.querySelector<HTMLElement>("button, input, select, [tabindex='0']");
      firstControl?.focus({ preventScroll: true });
    }, 40);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setFiltersOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [filtersOpen]);
  const locationScopeOptions = [{ value: "__all__", label: "全部地区" }, ...Object.entries(LOCATION_SCOPE_LABELS).map(([value, label]) => ({ value, label }))];
  const showMainlandLocation = locationScope === "MAINLAND_CHINA";
  const showOverseasLocation = locationScope === "OVERSEAS";
  const showCityLocation = showMainlandLocation || showOverseasLocation || locationScope === "HONG_KONG_MACAU_TAIWAN";
  return <>
    <PageVignette
      variant="jobs"
      title="岗位"
      metrics={[
        { label: "今日开放校招", value: todayCampaignCount },
        { label: "今日发布岗位", value: todayPublishedCount },
        { label: "今日首次收录", value: todayFirstSeenCount },
      ]}
      action={<button className="secondary-button" onClick={() => setFiltersOpen(true)}><SlidersHorizontal size={17} />打开筛选</button>}
    />
    <div className="jobs-discovery-layout">
      <div className="jobs-main-column">
        <section className="jobs-workspace" id="job-list">
      <div className="section-heading"><div><h2>全部岗位 <span className="count-badge">{filteredJobs.length}</span></h2><span className="results-count">{companyGroups.length} 家公司 · {filteredJobs.length} 个岗位{companyGroups.filter((group) => group.jobs.length === 0).length > 0 && ` · ${companyGroups.filter((group) => group.jobs.length === 0).length} 家仅入口`}</span></div><div className="heading-tools"><span className="last-updated"><span className="mini-dot" />最后核验 {formatDateTime(jobs[0]?.lastVerifiedAt)}</span>{activeFilterTags.length > 0 && <button className="clear-toolbar-button" onClick={resetFilters}>清除筛选</button>}<button ref={filterTriggerRef} className={`filter-toggle ${filtersOpen ? "is-active" : ""}`} aria-expanded={filtersOpen} aria-controls="jobs-filter-panel" onClick={() => setFiltersOpen((open) => !open)}><SlidersHorizontal size={17} />筛选{activeFilterCount > 0 && <b>{activeFilterCount}</b>}</button></div></div>
      <div className="search-row"><div className="search-box"><Search size={18} aria-hidden="true" /><input type="search" name="job-search" autoComplete="off" inputMode="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索公司、岗位、城市或技能" aria-label="搜索公司、岗位、城市或技能" /><kbd aria-hidden="true">/</kbd></div><button className={`quick-filter ${onlySoon ? "is-active" : ""}`} aria-pressed={onlySoon} onClick={() => setOnlySoon((value) => !value)}><Clock3 size={16} aria-hidden="true" />即将截止</button><button className={`quick-filter ${onlyMatched ? "is-active" : ""}`} aria-pressed={onlyMatched} onClick={() => setOnlyMatched((value) => !value)}><Target size={16} aria-hidden="true" />符合偏好</button><span className="entry-visibility-toggle" role="group" aria-label="公司入口显示"><button className={includeEntryCompanies ? "is-active" : ""} aria-pressed={includeEntryCompanies} onClick={() => setIncludeEntryCompanies(true)}><Building2 size={15} aria-hidden="true" />包含仅入口公司</button><button className={!includeEntryCompanies ? "is-active" : ""} aria-pressed={!includeEntryCompanies} onClick={() => setIncludeEntryCompanies(false)}><BriefcaseBusiness size={15} aria-hidden="true" />仅看已同步岗位</button></span><ModernSelect label="排序" value={sort} onChange={setSort} options={[{ value: "latest", label: "最新发布" }, { value: "deadline", label: "即将截止" }, { value: "match", label: "最匹配偏好" }, { value: "open", label: "校招新开放" }, { value: "company", label: "公司名称" }]} compact ariaLabel="排序方式" name="job-sort" /></div>
      {activeFilterTags.length > 0 && <div className="active-filter-tags" aria-label="已启用筛选">{activeFilterTags.map((item) => <button key={item.label} onClick={item.clear}>{item.label}<X size={13} /></button>)}<button className="clear-all-filters" onClick={resetFilters}>清空标签</button></div>}
      <div className="jobs-utility-row">
        <div className="company-filter-row" role="group" aria-label="公司筛选"><ModernSelect label="细分赛道" value={segment} onChange={setSegment} options={selectOptions(segments, "全部细分赛道")} compact ariaLabel="按细分赛道筛选" name="company-segment" /><ModernSelect label="入口状态" value={entryStatus} onChange={(value) => setEntryStatus(value as EntryStatusFilter)} options={selectOptions(entryStatusOptions.map((item) => item.value), "全部入口状态").map((item) => item.value === "__all__" ? item : ({ value: item.value, label: entryStatusOptions.find((option) => option.value === item.value)?.label ?? item.value }))} compact ariaLabel="按入口状态筛选" name="company-entry-status" /></div>
        <div className="jobs-catalog-metrics" aria-label="岗位目录概览">
          <div><span>当前校招公司</span><strong>{directoryOverview.recruiting}</strong></div>
          <div><span>可浏览岗位</span><strong>{directoryOverview.syncedJobs}</strong></div>
          <div><span>目录状态</span><strong>{catalogLoading ? "同步中" : "已更新"}</strong></div>
        </div>
      </div>
      <div className="job-browser-shell">
        {createPortal(<div className="ink-overhaul-portal">
          {filtersOpen && <button className="filter-backdrop" aria-label="关闭筛选" onClick={() => setFiltersOpen(false)} />}
          <aside id="jobs-filter-panel" ref={filterPanelRef} className={`filter-panel ${filtersOpen ? "is-open" : ""}`} role="region" aria-label="岗位筛选" aria-hidden={!filtersOpen}><div className="filter-panel-head"><strong>筛选岗位</strong><button type="button" className="icon-button filter-close" aria-label="关闭筛选" onClick={() => setFiltersOpen(false)}><X size={17} aria-hidden="true" /></button></div><ModernSelect label="地区范围" name="location-scope" value={locationScope} onChange={(value) => { setLocationScope(value as LocationScope | ""); setProvinceCodes([]); setCountryCode(""); setCityCodes([]); }} options={locationScopeOptions} />{showMainlandLocation && <MultiSelectField label="省份" values={provinceCodes} onChange={(values) => { setProvinceCodes(values); const allowed = new Set(locationRecords.filter((item) => !values.length || isNationwideLocation(item) || (item.provinceCode && values.includes(item.provinceCode))).map((item) => item.cityCode).filter(Boolean)); setCityCodes((current) => current.filter((item) => allowed.has(item))); }} options={mainlandProvinceOptions} placeholder="全部省份" ariaLabel="选择省份" />}{showOverseasLocation && <ModernSelect label="国家/地区" name="country-code" value={countryCode} onChange={(value) => { setCountryCode(value); setCityCodes([]); }} options={countrySelectOptions} />}{showCityLocation && <MultiSelectField label="城市" values={cityCodes} onChange={setCityCodes} options={cityOptions} placeholder="全部城市" ariaLabel="选择城市" />}{!showMainlandLocation && !showOverseasLocation && !showCityLocation && <div className="filter-context-note"><MapPin size={14} aria-hidden="true" />该地区范围不再细分城市</div>}<MultiSelectField label="岗位类别" values={roles} onChange={(values) => setRoles(values as RoleCategory[])} options={publicRoleCategories.map((value) => ({ value, label: value }))} placeholder="全部类别" ariaLabel="选择岗位类别" /><ModernSelect label="行业" name="job-industry" value={industry} onChange={setIndustry} options={selectOptions(industries, "全部行业")} /><ModernSelect label="公司类型" name="company-type" value={companyType} onChange={setCompanyType} options={selectOptions([...COMPANY_TYPES], "全部类型")} /><ModernSelect label="公司规模" name="company-scale" value={companyScale} onChange={setCompanyScale} options={selectOptions([...COMPANY_SCALES], "全部规模").map((item) => item.value === "__all__" ? item : ({ ...item, label: displayCompanyScale(item.label) }))} /><ModernSelect label="届别" name="target-cohort" value={cohort} onChange={setCohort} options={selectOptions(["2026", "2027", "2028", "2029", "未知"], "全部届别")} /><ModernSelect label="招聘批次" name="recruitment-batch" value={batch} onChange={setBatch} options={selectOptions([...BATCHES], "全部批次")} /><ModernSelect label="学历要求" name="education" value={education} onChange={setEducation} options={selectOptions([...new Set(jobs.map((job) => job.education))], "全部学历")} /><label className="filter-date">发布日期起<input name="publish-from" type="date" autoComplete="off" value={publishFrom} onChange={(event) => setPublishFrom(event.target.value)} /></label><label className="filter-date">发布日期止<input name="publish-to" type="date" autoComplete="off" value={publishTo} onChange={(event) => setPublishTo(event.target.value)} /></label><label className="filter-date">截止日期起<input name="deadline-from" type="date" autoComplete="off" value={deadlineFrom} onChange={(event) => setDeadlineFrom(event.target.value)} /></label><label className="filter-date">截止日期止<input name="deadline-to" type="date" autoComplete="off" value={deadlineTo} onChange={(event) => setDeadlineTo(event.target.value)} /></label><ModernSelect label="我的阶段" name="application-stage-filter" value={stage} onChange={setStage} options={selectOptions(STAGE_ORDER, "全部阶段").map((item) => item.value === "__all__" ? item : ({ value: item.value, label: STAGE_LABELS[item.value as Stage] }))} /><ModernSelect label="我的意向" name="interest-filter" value={interest} onChange={setInterest} options={selectOptions(Object.keys(INTEREST_LABELS), "全部意向").map((item) => item.value === "__all__" ? item : ({ value: item.value, label: INTEREST_LABELS[item.value as Interest] }))} /><button type="button" className="reset-button" onClick={resetFilters}><RotateCcw size={15} aria-hidden="true" />清除筛选</button></aside>
        </div>, document.body)}
        <div className="job-results-pane">{catalogLoading ? <div className="loading-state"><LoaderCircle className="spin" size={23} /><span>正在读取岗位目录…</span></div> : companyGroups.length === 0 ? <EmptyState onReset={resetFilters} /> : <GroupedJobList groups={companyGroups} expandedCompanies={expandedCompanies} toggleCompany={toggleCompany} stateMap={stateMap} preferences={preferences} lastVisitAt={lastVisitAt} openJob={openJob} updateInterest={updateInterest} updateStage={updateStage} />}<div className="catalog-footnote"><Info size={15} /><span>{provisionalJobCount > 0 && !preferences.showProvisionalJobs ? `另有 ${provisionalJobCount} 条公开入口临时岗位可在设置中开启；` : "正式岗位来自已核验来源；"}{preferences.showProvisionalJobs ? "已开启待核验线索，所有临时岗位均带有明确状态标识，不计入正式统计。" : "岗位请以企业官网为准。"}</span><a href={reportIssueUrl()} target="_blank" rel="noreferrer">报告错误 <ExternalLink size={13} /></a></div></div>
      </div>
        </section>
      </div>
    </div>
  </>;
}

type GroupedJobRow = { kind: "company"; group: CompanyJobGroup } | { kind: "job"; group: CompanyJobGroup; job: JobPosting } | { kind: "expand"; group: CompanyJobGroup; expanded: boolean } | { kind: "entry"; group: CompanyJobGroup };

function flattenGroupedRows(groups: CompanyJobGroup[], expandedCompanies: Set<string>): GroupedJobRow[] {
  return groups.flatMap((group) => {
    if (group.jobs.length === 0) return [{ kind: "company", group } as GroupedJobRow, { kind: "entry", group } as GroupedJobRow];
    const expanded = expandedCompanies.has(group.companyId);
    const rows: GroupedJobRow[] = [{ kind: "company", group }];
    (expanded ? group.jobs : group.jobs.slice(0, 5)).forEach((job) => rows.push({ kind: "job", group, job }));
    if (group.jobs.length > 5) rows.push({ kind: "expand", group, expanded });
    return rows;
  });
}

function GroupedJobList(props: { groups: CompanyJobGroup[]; expandedCompanies: Set<string>; toggleCompany: (companyId: string) => void; stateMap: Map<string, UserJobState>; preferences: Preferences; lastVisitAt: string; openJob: (job: JobPosting) => void; updateInterest: (job: JobPosting, interest: Interest) => Promise<void>; updateStage: (job: JobPosting, stage: Stage) => Promise<void> }) {
  const rows = useMemo(() => flattenGroupedRows(props.groups, props.expandedCompanies), [props.expandedCompanies, props.groups]);
  if (rows.length > 36) return <VirtualGroupedJobList {...props} rows={rows} />;
  return <div className="job-list job-list-scroll" aria-label="按公司分组的岗位列表">{rows.map((row, index) => <GroupedJobRow key={row.kind === "job" ? row.job.id : `${row.kind}-${row.group.companyId}`} row={row} index={index} {...props} />)}</div>;
}

function VirtualGroupedJobList(props: { rows: GroupedJobRow[]; groups: CompanyJobGroup[]; expandedCompanies: Set<string>; toggleCompany: (companyId: string) => void; stateMap: Map<string, UserJobState>; preferences: Preferences; lastVisitAt: string; openJob: (job: JobPosting) => void; updateInterest: (job: JobPosting, interest: Interest) => Promise<void>; updateStage: (job: JobPosting, stage: Stage) => Promise<void> }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({ count: props.rows.length, getScrollElement: () => parentRef.current, estimateSize: (index) => props.rows[index]?.kind === "company" ? 64 : props.rows[index]?.kind === "entry" ? 64 : props.rows[index]?.kind === "expand" ? 42 : 174, overscan: 8 });
  return <div ref={parentRef} className="virtual-job-list" aria-label="按公司分组的岗位列表"><div className="virtual-job-list-inner" style={{ height: virtualizer.getTotalSize() }}>{virtualizer.getVirtualItems().map((item) => <div key={item.key} ref={virtualizer.measureElement} data-index={item.index} className="virtual-job-row" style={{ transform: `translateY(${item.start}px)` }}><GroupedJobRow row={props.rows[item.index]} index={item.index} {...props} /></div>)}</div></div>;
}

function jobSourceLabel(job?: JobPosting): string {
  if (job?.provisional) return (job.publicationLabel ?? "公开入口临时采集 · 待核验").replace("公开入口临时采集", "临时入口");
  return job?.sourceLevel === "DEMO" ? "演示数据" : "官方来源";
}

function GroupedJobRow({ row, toggleCompany, stateMap, preferences, lastVisitAt, openJob, updateInterest, updateStage }: { row: GroupedJobRow; index: number; toggleCompany: (companyId: string) => void; stateMap: Map<string, UserJobState>; preferences: Preferences; lastVisitAt: string; openJob: (job: JobPosting) => void; updateInterest: (job: JobPosting, interest: Interest) => Promise<void>; updateStage: (job: JobPosting, stage: Stage) => Promise<void> }) {
  if (row.kind === "company") {
    const representative = row.group.jobs[0];
    return <div className="company-group-header company-band"><CompanyLogo companyId={row.group.companyId} companyName={row.group.companyName} size="today" /><div className="company-band-copy"><strong>{row.group.companyName}</strong><span>{row.group.jobs.length ? `${row.group.jobs.length} 个匹配岗位` : "当前校招入口"} · {representative?.companyIndustry || row.group.directory?.industry || "行业待确认"}</span></div><span className="company-band-art" aria-hidden="true" /><span className={`company-group-source ${row.group.jobs.length === 0 ? "is-lead" : ""}`}>{row.group.jobs.length === 0 ? (row.group.directory?.directory?.entryType === "ENTRY_LEAD" ? "入口线索·待确认" : "官方入口") : jobSourceLabel(representative)}</span></div>;
  }
  if (row.kind === "entry") {
    const entry = row.group.directory?.directory;
    if (!entry) return null;
    return <a className="company-entry-row" href={entry.careerUrl} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}><span><strong>校招入口</strong><small>{entry.evidenceText}</small></span><span className="company-entry-link">打开招聘网站 <ExternalLink size={14} /></span></a>;
  }
  if (row.kind === "expand") return <button className="company-group-expand" onClick={() => toggleCompany(row.group.companyId)} aria-expanded={row.expanded}>{row.expanded ? "收起岗位" : `展开全部 ${row.group.jobs.length} 条岗位`}<ChevronRight size={15} className={row.expanded ? "is-rotated" : ""} /></button>;
  const job = row.job;
  return <JobCard job={job} state={stateMap.get(job.id)} preferences={preferences} isNew={Boolean(lastVisitAt) && new Date(job.firstSeenAt).getTime() > new Date(lastVisitAt).getTime()} grouped onOpen={() => openJob(job)} onInterest={(value) => updateInterest(job, value)} onStage={(value) => updateStage(job, value)} />;
}

function JobCard({ job, state, preferences, isNew, grouped = false, onOpen, onInterest, onStage }: { job: JobPosting; state?: UserJobState; preferences: Preferences; isNew: boolean; grouped?: boolean; onOpen: () => void; onInterest: (interest: Interest) => void; onStage: (stage: Stage) => void }) {
  const deadlineDays = daysFromNow(job.deadline);
  const interest = state?.interest ?? "UNSET";
  return <article className={`job-card ${grouped ? "is-grouped" : ""}`} data-job-id={job.id} tabIndex={0} onClick={onOpen} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(); } }}>
    <div className="job-card-main"><div className="job-card-header">{!grouped && <CompanyLogo companyId={job.companyId} companyName={job.companyName} />}<div className={`job-title-group ${grouped ? "is-grouped" : ""}`}><div className="company-line">{grouped ? <span className="job-row-label">岗位</span> : <strong>{job.companyName}</strong>}{isNew && <span className="new-badge">刚收录</span>}<span className={`source-badge ${job.provisional ? "source-provisional" : `source-${job.sourceLevel.toLowerCase()}`}`}>{jobSourceLabel(job)}</span></div><h3>{job.title}</h3></div><button className={`heart-button ${interest === "SUITABLE" ? "is-liked" : ""}`} aria-label={interest === "SUITABLE" ? "取消合适标记" : "标记为合适"} onClick={(event) => { event.stopPropagation(); onInterest(interest === "SUITABLE" ? "UNSET" : "SUITABLE"); }}>{interest === "SUITABLE" ? <Heart fill="currentColor" size={19} /> : <Heart size={19} />}</button></div><div className="job-meta"><span><MapPin size={14} />{displayLocations(job)}</span><span><Tag size={14} />{job.roleCategory}</span><span><BriefcaseBusiness size={14} />{job.companyIndustry}</span><span className="meta-muted">{job.cohort} · {job.batch}</span></div>{matchReasons(job, preferences).length > 0 && <div className="job-card-insight"><Target size={13} />符合你的 {matchReasons(job, preferences).join(" · ")}</div>}<div className="tag-row">{job.skills.slice(0, 3).map((skill) => <span className="skill-tag" key={skill}>{skill}</span>)}</div></div>
    <div className="job-card-side"><div className={`deadline ${deadlineDays !== null && deadlineDays <= 7 ? "urgent" : ""}`}>{job.deadline ? <><span>{deadlineDays !== null && deadlineDays >= 0 ? `${deadlineDays} 天后截止` : "已截止"}</span><small>{formatDate(job.deadline)}</small></> : <span>截止日待确认</span>}</div><div className="card-actions"><div className="stage-select" onClick={(event) => event.stopPropagation()}><ModernSelect name={`job-stage-${job.id}`} value={state?.stage ?? "NOT_APPLIED"} onChange={(next) => onStage(next as Stage)} options={STAGE_ORDER.map((item) => ({ value: item, label: STAGE_LABELS[item] }))} compact ariaLabel="更新投递阶段" /></div><button className="detail-link" onClick={(event) => { event.stopPropagation(); onOpen(); }}>查看详情 <ChevronRight size={15} /></button></div></div>
  </article>;
}

function EmptyState({ onReset }: { onReset: () => void }) {
  return <div className="empty-state"><div className="empty-ink-mark" aria-hidden="true"><BrandMark compact /></div><div className="empty-icon"><PackageOpen size={27} /></div><h3>还没有符合条件的岗位</h3><p>试试减少一个筛选条件，或者清除筛选重新看看。</p><button className="secondary-button" onClick={onReset}><RotateCcw size={15} />清除筛选</button></div>;
}

function ProgressPage(props: SharedPageProps) {
  const { jobStates, jobMap, stateMap, updateStage, openJob, events } = props;
  const [view, setView] = useState<"board" | "table">("board");
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<Stage | "">("");
  const tracked = jobStates.filter((state) => {
    const job = jobMap.get(state.jobId);
    const haystack = `${state.snapshot.companyName} ${state.snapshot.title} ${state.snapshot.city} ${job?.title ?? ""}`.toLowerCase();
    return (!query || haystack.includes(query.toLowerCase())) && (!stageFilter || state.stage === stageFilter);
  });
  const counts = useMemo(() => STAGE_ORDER.reduce<Record<string, number>>((result, stage) => { result[stage] = jobStates.filter((item) => item.stage === stage).length; return result; }, {}), [jobStates]);
  const nextActions = useMemo(() => events
    .filter((event) => event.scheduledAt && !event.completed)
    .sort((a, b) => new Date(a.scheduledAt ?? 0).getTime() - new Date(b.scheduledAt ?? 0).getTime())
    .slice(0, 5), [events]);
  const railStages = STAGE_ORDER.filter((stage) => stage !== "NOT_APPLIED" || counts[stage] > 0);
  return <>
    <PageVignette
      variant="progress"
      title="进度"
      metrics={[
        { label: "已投递", value: jobStates.filter((item) => item.stage !== "NOT_APPLIED").length },
        { label: "待处理安排", value: nextActions.length },
        { label: "本机记录", value: jobStates.length, note: "仅保存在当前浏览器" },
      ]}
      action={<button className="secondary-button" onClick={() => setView((value) => value === "board" ? "table" : "board")}><LayoutGrid size={16} />{view === "board" ? "切换表格" : "切换看板"}</button>}
    />
    <section className="progress-stage-rail" aria-label="按投递阶段筛选">
      <button className={`progress-stage-step ${!stageFilter ? "is-active" : ""}`} onClick={() => setStageFilter("")}><span>总投递</span><strong>{jobStates.filter((item) => item.stage !== "NOT_APPLIED").length}</strong></button>
      {railStages.map((stage) => <button key={stage} className={`progress-stage-step stage-${stage.toLowerCase()} ${stageFilter === stage ? "is-active" : ""}`} onClick={() => setStageFilter(stage)} aria-pressed={stageFilter === stage}><span>{STAGE_LABELS[stage]}</span><strong>{counts[stage] ?? 0}</strong></button>)}
    </section>
     <div className="progress-layout">
       <section className="progress-main-pane">
         <div className="progress-toolbar"><div className="search-box compact"><Search size={17} aria-hidden="true" /><input type="search" name="progress-search" autoComplete="off" inputMode="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按公司、岗位或城市搜索" aria-label="搜索我的投递" /></div><span className="progress-result-count">{tracked.length} 条记录</span></div>
         {tracked.length === 0 ? <div className="empty-state page-empty"><img className="empty-art" src={assetPath("assets/visuals/progress-empty.webp")} alt="" width="900" height="675" loading="lazy" /><div className="empty-icon"><FolderOpen size={27} /></div><h3>{jobStates.length ? "没有匹配的投递" : "还没有投递记录"}</h3><p>{jobStates.length ? "试试清除阶段或搜索条件。" : "在岗位行上更新阶段，或打开岗位详情登记第一笔投递。"}</p>{jobStates.length ? <button className="primary-button" onClick={() => { setStageFilter(""); setQuery(""); }}>清除筛选 <ArrowUpRight size={16} /></button> : <a className="primary-button" href="#/jobs">去找岗位 <ArrowUpRight size={16} /></a>}</div> : view === "board" ? <div className="kanban-board">{railStages.map((stage) => <div className="kanban-column" key={stage}><div className="kanban-column-header"><span className={`stage-dot stage-${stage.toLowerCase()}`} /><strong>{STAGE_LABELS[stage]}</strong><span className="column-count">{counts[stage] ?? 0}</span></div><div className="kanban-cards">{tracked.filter((item) => item.stage === stage).map((state) => <ProgressCard key={state.jobId} state={state} job={jobMap.get(state.jobId)} onOpen={() => openJob(jobMap.get(state.jobId) ?? snapshotFromState(state))} onStage={(next) => updateStage(jobMap.get(state.jobId) ?? snapshotFromState(state), next)} />)}</div></div>)}</div> : <div className="progress-table-wrap"><table className="progress-table"><thead><tr><th>公司 / 岗位</th><th>城市</th><th>阶段</th><th>意向</th><th>更新时间</th><th /></tr></thead><tbody>{tracked.map((state) => { const job = jobMap.get(state.jobId); return <tr key={state.jobId}><td><button className="table-job" onClick={() => openJob(job ?? snapshotFromState(state))}><CompanyLogo companyId={state.snapshot.companyId} companyName={state.snapshot.companyName} size="small" /><span><strong>{state.snapshot.companyName}</strong><small>{state.snapshot.title}</small>{!job && <em className="local-history-tag">历史岗位 · 已退出公共库</em>}</span></button></td><td>{state.snapshot.city}</td><td><div className="stage-select table-stage"><ModernSelect name={`progress-stage-${state.jobId}`} value={state.stage} onChange={(next) => updateStage(job ?? snapshotFromState(state), next as Stage)} options={STAGE_ORDER.map((item) => ({ value: item, label: STAGE_LABELS[item] }))} compact ariaLabel="更新阶段" /></div></td><td><span className={`interest-text interest-${state.interest.toLowerCase()}`}>{INTEREST_LABELS[state.interest]}</span></td><td>{formatDateTime(state.updatedAt)}</td><td><button className="icon-button" aria-label="查看岗位详情" onClick={() => openJob(job ?? snapshotFromState(state))}><ChevronRight size={17} /></button></td></tr>; })}</tbody></table></div>}
       </section>
     </div>
  </>;
}

function ProgressCard({ state, job, onOpen, onStage }: { state: UserJobState; job?: JobPosting; onOpen: () => void; onStage: (stage: Stage) => void }) {
  return <article className={`progress-card ${job ? "" : "is-local-history"}`}><button className="progress-card-open" onClick={onOpen}><div className="progress-card-company"><CompanyLogo companyId={state.snapshot.companyId} companyName={state.snapshot.companyName} size="tiny" /><span>{state.snapshot.companyName}</span></div><strong>{state.snapshot.title}</strong><span className="progress-card-meta">{state.snapshot.city} · {state.snapshot.roleCategory}</span>{!job && <em className="local-history-tag">历史岗位 · 已退出公共库</em>}</button><div className="progress-card-footer"><span className={`interest-pill interest-${state.interest.toLowerCase()}`}>{INTEREST_LABELS[state.interest]}</span><div className="stage-select card-stage"><ModernSelect name={`progress-stage-${state.jobId}`} value={state.stage} onChange={(next) => onStage(next as Stage)} options={STAGE_ORDER.map((item) => ({ value: item, label: STAGE_LABELS[item] }))} compact ariaLabel="更新阶段" /></div></div></article>;
}

function SchedulePage(props: SharedPageProps) {
  const { events, jobMap, jobStates, openJob, showNotice, toggleEventComplete } = props;
  const [formOpen, setFormOpen] = useState(false);
  const [filter, setFilter] = useState<"all" | "today" | "week" | "overdue">("all");
  const todayKey = todayInShanghai();
  const [selectedDate, setSelectedDate] = useState(todayKey);
  const [newEvent, setNewEvent] = useState<{ jobId: string; type: EventType; scheduledAt: string; locationOrLink: string; note: string; round: string }>({ jobId: jobStates[0]?.jobId ?? "", type: "INTERVIEW", scheduledAt: "", locationOrLink: "", note: "", round: "1" });
  // Events can outlive a public posting. Resolve through the current catalog
  // first, then fall back to the user's local snapshot so a historical event
  // still shows its company/title and can reopen the historical detail view.
  const localJobMap = useMemo(() => new Map(jobStates.map((state) => [state.jobId, jobMap.get(state.jobId) ?? snapshotFromState(state)])), [jobMap, jobStates]);
  const scheduled = events.filter((event) => event.scheduledAt).sort((a, b) => (a.scheduledAt ?? "").localeCompare(b.scheduledAt ?? ""));
  const shown = scheduled.filter((event) => filter === "today" ? shanghaiDay(event.scheduledAt) === selectedDate : filter === "week" ? isWithinNextDays(event.scheduledAt, 7) : filter === "overdue" ? isOverdue(event.scheduledAt) && !event.completed : true);
  const todayEvents = scheduled.filter((event) => isSameDay(event.scheduledAt));
  const weekEvents = scheduled.filter((event) => isWithinNextDays(event.scheduledAt, 7));
  const overdueEvents = scheduled.filter((event) => isOverdue(event.scheduledAt) && !event.completed);
  const weekDates = useMemo(() => {
    const base = new Date(`${todayKey}T00:00:00+08:00`);
    return Array.from({ length: 7 }, (_, index) => {
      const date = new Date(base);
      date.setDate(base.getDate() + index);
      return { key: shanghaiDay(date.toISOString()), day: new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", weekday: "short" }).format(date), label: new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric" }).format(date) };
    });
  }, [todayKey]);
  const submitEvent = async (event: FormEvent) => {
    event.preventDefault();
    if (!newEvent.jobId || !newEvent.scheduledAt) { showNotice("请先选择岗位并填写时间。"); return; }
    await addEvent({ jobId: newEvent.jobId, type: newEvent.type, scheduledAt: new Date(newEvent.scheduledAt).toISOString(), locationOrLink: newEvent.locationOrLink || undefined, note: newEvent.note || undefined, round: newEvent.type === "INTERVIEW" ? Number(newEvent.round) || 1 : undefined, completed: false });
    setFormOpen(false);
    setNewEvent((current) => ({ ...current, scheduledAt: "", locationOrLink: "", note: "" }));
    showNotice("日程已添加，进入网站后即可看到提醒。");
  };
  return <>
    <PageVignette
      variant="schedule"
      title="日程"
      metrics={[
        { label: "今日安排", value: todayEvents.length },
        { label: "未来 7 天", value: weekEvents.length },
        { label: "逾期待跟进", value: overdueEvents.length },
      ]}
      action={<button className="primary-button" onClick={() => setFormOpen(true)}><Plus size={17} />添加日程</button>}
    >
      <div className="vignette-date-strip" aria-label="本周日期"><span>本周</span>{weekDates.slice(0, 7).map((date) => <button key={date.key} className={date.key === selectedDate ? "is-selected" : ""} onClick={() => { setSelectedDate(date.key); setFilter("today"); }}><small>{date.day}</small><strong>{date.label}</strong></button>)}</div>
    </PageVignette>
    <section className="schedule-highlight"><div className="today-card"><div className="today-card-top"><div><h2>{todayEvents.length ? `今天有 ${todayEvents.length} 件安排` : "今天暂时没有安排"}</h2></div><div className="today-date">{new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "long", day: "numeric", weekday: "short" }).format(new Date())}</div></div>{todayEvents.length ? <div className="today-event-list">{todayEvents.slice(0, 3).map((event) => <EventRow key={event.id} event={event} job={localJobMap.get(event.jobId)} onOpen={() => { const job = localJobMap.get(event.jobId); if (job) openJob(job); }} onToggleComplete={toggleEventComplete} />)}</div> : <div className="today-empty"><CheckCircle2 size={19} /><span>把下一轮面试或跟进记下来，给自己一个明确的下一步。</span><button className="text-button" onClick={() => setFormOpen(true)}>添加第一条 <ChevronRight size={14} /></button></div>}</div><div className="schedule-side-stats"><button className={`mini-stat ${filter === "overdue" ? "is-active" : ""}`} onClick={() => setFilter(filter === "overdue" ? "all" : "overdue")}><span className="mini-stat-icon danger"><Flag size={17} /></span><span><strong>{overdueEvents.length}</strong><small>逾期待跟进</small></span><ChevronRight size={15} /></button><button className={`mini-stat ${filter === "today" ? "is-active" : ""}`} onClick={() => setFilter(filter === "today" ? "all" : "today")}><span className="mini-stat-icon blue"><BellRing size={17} /></span><span><strong>{todayEvents.length}</strong><small>今日安排</small></span><ChevronRight size={15} /></button><button className={`mini-stat ${filter === "week" ? "is-active" : ""}`} onClick={() => setFilter(filter === "week" ? "all" : "week")}><span className="mini-stat-icon blue"><CalendarRange size={17} /></span><span><strong>{weekEvents.length}</strong><small>未来 7 天</small></span><ChevronRight size={15} /></button></div></section>
    <section className="timeline-section"><div className="section-heading compact-heading"><div><h2>{filter === "overdue" ? "需要尽快处理" : filter === "today" ? "今天的安排" : filter === "week" ? "未来 7 天" : "全部安排"} <span className="count-badge">{shown.length}</span></h2></div><div className="segmented-control"><button className={filter === "all" ? "is-active" : ""} onClick={() => setFilter("all")}>全部</button><button className={filter === "today" ? "is-active" : ""} onClick={() => setFilter("today")}>今日</button><button className={filter === "week" ? "is-active" : ""} onClick={() => setFilter("week")}>未来 7 天</button><button className={filter === "overdue" ? "is-active" : ""} onClick={() => setFilter("overdue")}>逾期</button></div></div>{shown.length ? <div className="timeline-list">{shown.map((event) => <EventRow key={event.id} event={event} job={localJobMap.get(event.jobId)} onOpen={() => { const job = localJobMap.get(event.jobId); if (job) openJob(job); }} onToggleComplete={toggleEventComplete} detailed />)}</div> : <div className="empty-state compact-empty"><img className="empty-art" src={assetPath("assets/visuals/schedule-empty.webp")} alt="" width="640" height="640" loading="lazy" /><div className="empty-icon"><CalendarDays size={25} /></div><h3>这里还没有日程</h3><p>在岗位详情里添加面试轮次，或者点击“添加日程”。</p></div>}</section>
    {formOpen && <EventForm jobs={jobStates.map((state) => jobMap.get(state.jobId) ?? snapshotFromState(state))} value={newEvent} onChange={setNewEvent} onSubmit={submitEvent} onClose={() => setFormOpen(false)} />}
  </>;
}

function EventRow({ event, job, onOpen, onToggleComplete, detailed = false }: { event: ApplicationEvent; job?: JobPosting; onOpen: () => void; onToggleComplete?: (event: ApplicationEvent) => Promise<void>; detailed?: boolean }) {
  const displayTime = event.scheduledAt ?? event.createdAt;
  const icon = event.completed
    ? <Check size={16} aria-hidden="true" />
    : event.type === "INTERVIEW"
      ? <CalendarDays size={16} aria-hidden="true" />
      : event.type === "ASSESSMENT"
        ? <ClipboardCheck size={16} aria-hidden="true" />
        : event.type === "FOLLOW_UP"
          ? <BellRing size={16} aria-hidden="true" />
          : <CheckCircle2 size={16} aria-hidden="true" />;
  return <article className={`event-row ${event.completed ? "is-complete" : ""}`}>
    {onToggleComplete
      ? <button type="button" className={`event-icon event-toggle event-${event.type.toLowerCase()}`} aria-label={event.completed ? "标记为待处理" : "标记为完成"} aria-pressed={event.completed} onClick={() => void onToggleComplete(event)}>{icon}</button>
      : <span className={`event-icon event-${event.type.toLowerCase()}`} aria-hidden="true">{icon}</span>}
    <button type="button" className="event-row-main" onClick={onOpen}>
      <span className="event-content"><span className="event-title"><strong>{EVENT_LABELS[event.type]}{event.round ? ` · 第 ${event.round} 轮` : ""}</strong>{job && <small>{job.companyName} · {job.title}</small>}</span>{event.note && <span className="event-note">{event.note}</span>}</span>
      <span className="event-time"><strong>{formatDateTime(displayTime)}</strong>{event.locationOrLink && detailed && <small>{event.locationOrLink}</small>}</span>
      <ChevronRight className="event-row-arrow" size={16} aria-hidden="true" />
    </button>
  </article>;
}

type EventDraft = { jobId: string; type: EventType; scheduledAt: string; locationOrLink: string; note: string; round: string };

function EventForm({ jobs, value, onChange, onSubmit, onClose }: { jobs: JobPosting[]; value: EventDraft; onChange: (value: EventDraft) => void; onSubmit: (event: FormEvent) => void; onClose: () => void }) {
  const jobOptions = [{ value: "__all__", label: "请选择岗位" }, ...jobs.map((job) => ({ value: job.id, label: `${job.companyName} · ${job.title}` }))];
  const eventOptions = EVENT_TYPES.map((item) => ({ value: item, label: EVENT_LABELS[item] }));
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}><DialogContent className="schedule-dialog-content" aria-describedby="event-form-description"><DialogHeader className="schedule-dialog-header"><DialogTitle id="event-form-title">添加日程</DialogTitle><DialogDescription id="event-form-description">把面试、测评或跟进安排记录到本机时间线。</DialogDescription></DialogHeader><form className="event-form" onSubmit={onSubmit}><ModernSelect label="关联岗位" name="event-job" value={value.jobId} onChange={(jobId) => onChange({ ...value, jobId })} options={jobOptions} placeholder="请选择岗位" /><div className="form-two-col"><ModernSelect label="事件类型" name="event-type" value={value.type} onChange={(type) => onChange({ ...value, type: type as EventType })} options={eventOptions} />{value.type === "INTERVIEW" && <label>面试轮次<input name="interview-round" type="number" min="1" max="20" inputMode="numeric" autoComplete="off" value={value.round} onChange={(event) => onChange({ ...value, round: event.target.value })} /></label>}</div><label>时间<input name="scheduled-at" type="datetime-local" autoComplete="off" value={value.scheduledAt} onChange={(event) => onChange({ ...value, scheduledAt: event.target.value })} /></label><label>地点或会议链接（可选）<input name="location-or-link" type="url" autoComplete="off" value={value.locationOrLink} onChange={(event) => onChange({ ...value, locationOrLink: event.target.value })} placeholder="例如：腾讯会议 / 会议室" /></label><label>备注（可选）<textarea name="event-note" autoComplete="off" rows={3} value={value.note} onChange={(event) => onChange({ ...value, note: event.target.value })} placeholder="面试准备、跟进内容…" /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button"><Check size={16} aria-hidden="true" />保存到本机</button></div></form></DialogContent></Dialog>;
}

function SettingsPage(props: SharedPageProps & { exportJson: () => Promise<void>; exportCsv: () => void; importJson: (file: File) => Promise<void> }) {
  const { preferences, manifest, sources, directoryCompanies, communityLeads, jobs, jobStates, events, exportJson, exportCsv, importJson, showNotice, provisionalJobCount } = props;
  const fallbackCompanyCount = useMemo(() => new Set(jobs.filter((job) => job.status === "ACTIVE").map((job) => job.companyId)).size, [jobs]);
  const directoryStats = useMemo(() => {
    const active = directoryCompanies.filter((company) => ["ACTIVE_CONFIRMED", "ACTIVE_LEAD"].includes(company.directory?.directoryStatus ?? ""));
    return {
      active: active.length,
      official: active.filter((company) => company.directory?.entryType !== "ENTRY_LEAD").length,
      leads: active.filter((company) => company.directory?.entryType === "ENTRY_LEAD").length,
      withJobs: new Set(jobs.filter((job) => job.status === "ACTIVE").map((job) => job.companyId)).size,
    };
  }, [directoryCompanies, jobs]);
  const [confirmClear, setConfirmClear] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(preferences);
  useEffect(() => setDraft(preferences), [preferences]);
  const save = async (event: FormEvent) => { event.preventDefault(); await savePreferences({ ...draft, setupComplete: true }); showNotice("偏好设置已保存。"); };
  const toggleRole = (role: RoleCategory) => setDraft((current) => ({ ...current, roles: current.roles.includes(role) ? current.roles.filter((item) => item !== role) : [...current.roles, role] }));
  const toggleCompanyType = (type: typeof COMPANY_TYPES[number]) => setDraft((current) => ({ ...current, companyTypes: current.companyTypes.includes(type) ? current.companyTypes.filter((item) => item !== type) : [...current.companyTypes, type] }));
  const toggleEducation = (education: string) => setDraft((current) => ({ ...current, educationLevels: (current.educationLevels ?? []).includes(education) ? (current.educationLevels ?? []).filter((item) => item !== education) : [...(current.educationLevels ?? []), education] }));
  const toggleBatch = (batch: typeof BATCHES[number]) => setDraft((current) => ({ ...current, batches: (current.batches ?? []).includes(batch) ? (current.batches ?? []).filter((item) => item !== batch) : [...(current.batches ?? []), batch] }));
  const toggleScale = (scale: typeof COMPANY_SCALES[number]) => setDraft((current) => ({ ...current, companyScales: (current.companyScales ?? []).includes(scale) ? (current.companyScales ?? []).filter((item) => item !== scale) : [...(current.companyScales ?? []), scale] }));
  const clear = async () => { await clearLocalData(); setConfirmClear(false); showNotice("本机求职记录已清空，公共岗位目录仍然保留。"); };
  const toggleProvisionalJobs = async (checked: boolean) => {
    const next = { ...draft, showProvisionalJobs: checked };
    setDraft(next);
    await savePreferences(next);
    showNotice(checked ? "已显示待核验线索；它们不会计入正式统计。" : "已隐藏待核验线索，岗位页只显示正式目录。" );
  };
  return <>
    <PageVignette
      variant="settings"
      title="设置"
      metrics={[
        { label: "本机岗位记录", value: jobStates.length },
        { label: "时间线事件", value: events.length },
        { label: "公开临时岗位", value: provisionalJobCount, note: "公开入口 · 待核验" },
        { label: "目录状态", value: manifest?.isDemo ? "演示" : "已同步", note: "数据只保存在当前浏览器" },
      ]}
      action={<a className="secondary-button" href="#settings-preferences"><Pencil size={16} />编辑求职偏好</a>}
    />
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="设置章节"><span className="settings-nav-label">设置章节</span><a href="#settings-preferences">求职偏好</a><a href="#settings-data">本地数据</a><a href="#settings-coverage">来源与覆盖</a><a href="#settings-privacy">隐私与开源</a></nav>
      <div className="settings-content">
      <div className="settings-grid">
      <section id="settings-preferences" className="settings-card preference-card"><div className="settings-card-heading"><div><h2>求职偏好</h2></div><Pencil size={18} /></div><form onSubmit={save} className="preferences-form">
        <ModernSelect label="目标届别" name="preferences-cohort" value={draft.cohort} onChange={(cohort) => setDraft({ ...draft, cohort })} options={selectOptions(["2026", "2027", "2028", "2029"], "不限届别")} />
        <label>目标城市 <span className="label-hint">用逗号分隔，可留空</span><input name="target-cities" type="text" autoComplete="off" value={draft.cities.join(", ")} onChange={(event) => setDraft({ ...draft, cities: event.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} placeholder="例如：武汉，北京" /></label>
        <div className="choice-group"><span className="choice-label">岗位类别 <small>{draft.roles.length ? `已选 ${draft.roles.length} 项` : "不限"}</small></span><p className="field-help">公共岗位库暂聚焦文科、社科、商科及不限专业的通用岗位。</p><div className="choice-chips">{PUBLIC_ROLE_CATEGORIES.map((role) => <button type="button" key={role} className={`choice-chip ${draft.roles.includes(role) ? "is-selected" : ""}`} onClick={() => toggleRole(role)}>{draft.roles.includes(role) && <Check size={13} />}{role}</button>)}</div></div>
        <div className="choice-group"><span className="choice-label">公司类型 <small>{draft.companyTypes.length ? `已选 ${draft.companyTypes.length} 项` : "不限"}</small></span><div className="choice-chips compact-chips">{COMPANY_TYPES.map((type) => <button type="button" key={type} className={`choice-chip ${draft.companyTypes.includes(type) ? "is-selected" : ""}`} onClick={() => toggleCompanyType(type)}>{draft.companyTypes.includes(type) && <Check size={13} />}{type}</button>)}</div></div>
        <div className="choice-group"><span className="choice-label">学历要求 <small>{draft.educationLevels?.length ? `已选 ${draft.educationLevels.length} 项` : "不限"}</small></span><div className="choice-chips compact-chips">{["本科及以上", "硕士及以上", "博士", "本科", "硕士"].map((level) => <button type="button" key={level} className={`choice-chip ${draft.educationLevels?.includes(level) ? "is-selected" : ""}`} onClick={() => toggleEducation(level)}>{draft.educationLevels?.includes(level) && <Check size={13} />}{level}</button>)}</div></div>
        <div className="choice-group"><span className="choice-label">公司规模 <small>{draft.companyScales?.length ? `已选 ${draft.companyScales.length} 项` : "不限"}</small></span><div className="choice-chips compact-chips">{COMPANY_SCALES.map((scale) => <button type="button" key={scale} className={`choice-chip ${draft.companyScales?.includes(scale) ? "is-selected" : ""}`} onClick={() => toggleScale(scale)}>{draft.companyScales?.includes(scale) && <Check size={13} />}{displayCompanyScale(scale)}</button>)}</div></div>
        <div className="choice-group"><span className="choice-label">招聘批次 <small>{draft.batches?.length ? `已选 ${draft.batches.length} 项` : "不限"}</small></span><div className="choice-chips compact-chips">{BATCHES.map((item) => <button type="button" key={item} className={`choice-chip ${draft.batches?.includes(item) ? "is-selected" : ""}`} onClick={() => toggleBatch(item)}>{draft.batches?.includes(item) && <Check size={13} />}{item}</button>)}</div></div>
        <button className="primary-button save-preferences" type="submit"><Check size={16} />保存偏好</button>
      </form></section>
      <section id="settings-data" className="settings-card data-card"><div className="settings-card-heading"><div><h2>本地数据</h2></div><LockKeyhole size={18} /></div><div className="privacy-summary"><div className="privacy-row"><LockKeyhole size={16} /><span><strong>本地存储</strong><small>求职状态、日程和备注仅保存在当前浏览器。</small></span><span className="status-pill success">开启</span></div><div className="privacy-row"><PackageOpen size={16} /><span><strong>公共目录</strong><small>{manifest?.isDemo ? "当前为演示快照，正式目录会定期更新。" : `目录版本 ${manifest?.catalogVersion ?? "读取中"}`}</small></span><span className={`status-pill ${manifest?.isDemo ? "warning" : "success"}`}>{manifest?.isDemo ? "演示" : "已同步"}</span></div><div className="privacy-row"><RefreshCw size={16} /><span><strong>采集节奏</strong><small>{manifest?.isDemo ? "正式目录约每 5 小时检查公开来源。" : `最近生成 ${manifest?.generatedAt ? formatDateTime(manifest.generatedAt) : "读取中"}，约每 5 小时检查一次。`}</small></span><span className={`status-pill ${manifest?.isDemo ? "warning" : "success"}`}>{manifest?.isDemo ? "待接入" : "自动更新"}</span></div><div className="privacy-row"><BellRing size={16} /><span><strong>提醒方式</strong><small>进入网站后查看站内提醒。</small></span><span className="status-pill muted">站内</span></div></div><label className="provisional-toggle"><input type="checkbox" checked={Boolean(draft.showProvisionalJobs)} onChange={(event) => void toggleProvisionalJobs(event.target.checked)} /><span><strong>显示待核验线索</strong><small>仅显示公开入口临时岗位，带有“待核验”标识，不计入正式搜索、公司数和今日统计。</small></span><span className="status-pill warning">{provisionalJobCount} 条</span></label><div className="data-actions"><button className="data-action" onClick={() => void exportJson()}><span className="data-action-icon blue"><FileJson size={18} /></span><span><strong>导出完整 JSON</strong></span><Download size={16} /></button><button className="data-action" onClick={() => fileRef.current?.click()}><span className="data-action-icon blue"><Upload size={18} /></span><span><strong>恢复 JSON 备份</strong></span><ChevronRight size={16} /></button><input ref={fileRef} type="file" accept="application/json,.json" aria-label="选择 JSON 备份文件" className="visually-hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importJson(file); event.currentTarget.value = ""; }} /><button className="data-action" onClick={exportCsv}><span className="data-action-icon green"><Download size={18} /></span><span><strong>导出 CSV</strong></span><Download size={16} /></button></div><div className="record-count"><span>当前本机记录</span><strong>{jobStates.length} 个岗位 · {events.length} 条事件</strong></div><div className="danger-zone"><div><strong>清空本机数据</strong><p>公共岗位目录不会受影响，清空后只能通过 JSON 备份恢复。</p></div>{confirmClear ? <div className="confirm-actions"><button className="secondary-button" onClick={() => setConfirmClear(false)}>取消</button><button className="danger-button" onClick={() => void clear()}>确认清空</button></div> : <button className="danger-outline" onClick={() => setConfirmClear(true)}><Trash2 size={15} />清空</button>}</div></section>
    </div>
     <section id="settings-coverage" className="settings-card directory-summary-card" aria-labelledby="directory-summary-title"><div className="settings-card-heading"><div><h2 id="directory-summary-title">来源与覆盖</h2></div><Building2 size={18} /></div><p className="settings-helper">入口线索先登记，完成来源审核后才会自动同步岗位。</p><div className="directory-summary-metrics"><div><span>当前校招入口</span><strong>{manifest?.companyDirectory?.activeRecruitingCompanyCount ?? directoryStats.active}</strong></div><div><span>官方入口</span><strong>{manifest?.companyDirectory?.officialEntryCount ?? directoryStats.official}</strong></div><div><span>入口线索·待确认</span><strong>{manifest?.companyDirectory?.entryLeadCount ?? directoryStats.leads}</strong></div><div><span>已有合格岗位</span><strong>{manifest?.companyDirectory?.companiesWithEligibleJobs ?? directoryStats.withJobs}</strong></div></div><p className="settings-helper directory-summary-foot">当前届别 {manifest?.companyDirectory?.cohort ?? "2027"}，最后发现 {manifest?.companyDirectory?.lastDiscoveryAt ? formatDateTime(manifest.companyDirectory.lastDiscoveryAt) : "待更新"}。</p></section>
     <section className="settings-card source-health-card"><div className="settings-card-heading"><div><h2>来源状态</h2></div><CircleHelp size={18} /></div><div className="health-metrics"><div><span>候选公司池</span><strong>{manifest?.candidateCompanyCount ?? "暂无"}</strong><small>发现队列</small></div><div><span>人工核验来源</span><strong>{manifest?.verifiedSourceCount ?? 0}</strong><small>完成审核</small></div><div><span>自动核验来源</span><strong>{manifest?.autoVerifiedSourceCount ?? 0}</strong><small>公开证据完整</small></div><div><span>当前有岗位的公司</span><strong>{manifest?.companyDirectory?.companiesWithEligibleJobs ?? manifest?.companiesWithEligibleJobs ?? fallbackCompanyCount}</strong><small>当前届别</small></div><div><span>当前校招入口</span><strong>{manifest?.companyDirectory?.activeRecruitingCompanyCount ?? directoryStats.active}</strong><small>官方与线索</small></div><div><span>500 人以上</span><strong>{manifest?.confirmed500PlusCompanyCount ?? "暂无"}</strong><small>有规模证据</small></div><div><span>活跃岗位</span><strong>{manifest?.activeJobs ?? 0}</strong><small>目录总量 {manifest?.totalJobs ?? 0}</small></div><div><span>健康状态</span><strong>{manifest?.sourceHealth.healthy ?? 0}</strong><small>隔离 {manifest?.sourceHealth.quarantined ?? 0}，陈旧 {manifest?.sourceHealth.stale ?? 0}</small></div><div><span>已发现企业</span><strong>{manifest?.coverage?.discoveredCompanyCount ?? "暂无"}</strong><small>发现队列</small></div><div><span>待核验企业</span><strong>{manifest?.coverage?.pendingReviewCompanyCount ?? "暂无"}</strong><small>不进入岗位库</small></div><div><span>公开来源接入率</span><strong>{manifest?.coverage?.accessibleSourceCoverageRate == null ? "暂无" : `${Math.round(manifest.coverage.accessibleSourceCoverageRate * 100)}%`}</strong><small>登记来源</small></div><div><span>Hiring Radar 公司</span><strong>{manifest?.companyDiscovery?.hiringRadarCompanyCount ?? "暂无"}</strong><small>发现队列</small></div><div><span>Radar 入口 URL</span><strong>{manifest?.companyDiscovery?.hiringRadarEntryUrlCount ?? "暂无"}</strong><small>待审核</small></div></div>{sources.length > 0 && <div className="source-audit-list"><div className="source-audit-heading"><strong>已公开审计摘要</strong><span>{sources.length} 个来源</span></div>{sources.slice(0, 8).map((source) => <a className="source-audit-row" href={source.sourceUrl} target="_blank" rel="noreferrer" key={source.sourceId}><span className={`source-health-dot health-${source.health}`} /><span><strong>{source.companyName}</strong><small>{source.adapter} · {source.jobCount} 条岗位（抓取 {source.fetchedJobCount ?? source.jobCount}，符合口径 {source.eligibleJobCount ?? source.jobCount}）</small></span><em>{sourceStatusLabel(source.status)}</em><ExternalLink size={13} /></a>)}</div>}<p className="settings-helper">“自动核验”表示来源满足公开访问、校招、公司身份、字段完整度和连续健康运行等机器检查；“人工核验”仍是另一条来源状态。</p></section>
    <CommunityLeadsSection leads={communityLeads} />
    <section id="settings-privacy" className="settings-card about-card"><div className="about-item"><Flag size={18} /><div><strong>报告错误或遗漏</strong><p>只生成预填充的 GitHub Issue，不会把你的投递状态或备注附加进去。</p><a className="text-button" href={reportIssueUrl()} target="_blank" rel="noreferrer">打开反馈入口 <ExternalLink size={13} /></a></div></div><div className="about-item"><Archive size={18} /><div><strong>开源与复用</strong><p>项目以 AGPL-3.0 发布，采集器会保留第三方适配器的版权与许可证说明。</p><a className="text-button" href={repositoryUrl()} target="_blank" rel="noreferrer">查看项目仓库 <ExternalLink size={13} /></a></div></div><div className="about-item"><Building2 size={18} /><div><strong>公司标识</strong><p>优先使用本地品牌标识；没有完成官方素材核验的公司会回退文字，不把第三方图标冒充官网 Logo。</p></div></div></section>
    <FocusCoverageSummary manifest={manifest} />
      </div>
      </div>
  </>;
}

function CommunityLeadsSection({ leads }: { leads: CommunityLead[] }) {
  // Referral codes can be tied to a person's identity, reward relationship or
  // an expiring platform campaign.  Keep those fields out of the public UI;
  // community posts remain discovery evidence only.
  const visibleLeads = [...leads].slice(0, 24);
  return <details className="settings-card community-leads-card community-leads-details">
    <summary className="community-leads-summary"><span><Tag size={18} /><strong>小红书招聘线索</strong><small>公开社区线索，仅用于发现企业官网</small></span><ChevronRight size={17} /></summary>
    <div className="community-leads-body"><p className="settings-helper community-leads-intro">社区线索只用于发现官网，不等同于已核验岗位。</p>
    {visibleLeads.length === 0 ? <div className="community-leads-empty"><strong>还没有社区线索</strong><span>在已打开并登录的浏览器会话中运行 <code>npm run xhs:sync</code>，生成脱敏线索后刷新页面。</span></div> : <div className="community-lead-list">{visibleLeads.map((lead) => <article className="community-lead-row" key={lead.id}>
      <div className="community-lead-main"><strong>{lead.companyName || "待识别公司"}</strong><span>{lead.title}</span><small>{lead.publishedAt ? `发布于 ${lead.publishedAt}` : "发布时间未知"} · {lead.sourceAuthorLabel || "公开帖子"}</small></div>
      <div className="community-lead-actions">{lead.officialUrl && <a href={lead.officialUrl} target="_blank" rel="noreferrer">{lead.officialUrlVerified ? "已核验入口" : "登记入口"} <ExternalLink size={13} /></a>}<a href={lead.sourceUrl} target="_blank" rel="noreferrer">来源帖子 <ExternalLink size={13} /></a><span className="lead-review-status">需核验</span></div>
    </article>)}</div>}
    {leads.length > visibleLeads.length && <p className="settings-helper community-leads-more">已显示 {visibleLeads.length} 条，共 {leads.length} 条；完整线索保存在公开目录文件中。</p>}</div>
  </details>;
}

function FocusCoverageSummary({ manifest }: { manifest: CatalogManifest | null }) {
  const focus = manifest?.collectionFocus;
  return <section className="focus-coverage-strip" aria-label="互联网重点覆盖"><div><span>互联网重点公司</span><strong>{focus?.focusCompanyCount ?? "暂无"}</strong><small>优先发现</small></div><div><span>已登记来源</span><strong>{focus?.focusCompaniesWithSources ?? "暂无"}</strong><small>待核验分开统计</small></div><div><span>可运行来源</span><strong>{focus?.focusCompaniesWithRunnableSources ?? "暂无"}</strong><small>通过来源门禁</small></div><div><span>当前合格岗位</span><strong>{focus?.focusEligibleJobCount ?? "暂无"}</strong><small>受众口径</small></div><p>重点名单只改变发现顺序，不会自动提升来源状态。</p></section>;
}

function Onboarding({ preferences, onSave, onSkip }: { preferences: Preferences; onSave: (preferences: Preferences) => Promise<void>; onSkip: () => void }) {
  const [draft, setDraft] = useState(preferences);
  const [step, setStep] = useState(1);
  const toggleRole = (role: RoleCategory) => setDraft((current) => ({ ...current, roles: current.roles.includes(role) ? current.roles.filter((item) => item !== role) : [...current.roles, role] }));
  return <div className="modal-backdrop onboarding-backdrop"><section className="modal onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="onboarding-title"><div className="onboarding-progress"><span className="is-active" /><span className={step > 1 ? "is-active" : ""} /><span className={step > 2 ? "is-active" : ""} /><button type="button" className="skip-link" onClick={onSkip}>先看看岗位</button></div>{step === 1 ? <div className="onboarding-step"><div className="onboarding-welcome-art"><img src={assetPath("assets/visuals/welcome-workspace.webp")} alt="" width="900" height="506" loading="lazy" /></div><div className="onboarding-mark onboarding-brand"><BrandMark compact /></div><h2 id="onboarding-title">先选一个目标届别</h2><p>我们只用这些选择做透明筛选，不会生成黑盒分数。之后随时可以在设置中修改。</p><div className="cohort-options">{["2026", "2027", "2028", "2029"].map((year) => <button type="button" key={year} className={draft.cohort === year ? "is-selected" : ""} onClick={() => setDraft({ ...draft, cohort: year })}><strong>{year}</strong><span>届毕业生</span>{draft.cohort === year && <CheckCircle2 size={18} />}</button>)}</div><button type="button" className="primary-button onboarding-next" onClick={() => setStep(2)}>下一步 <ChevronRight size={16} /></button></div> : step === 2 ? <div className="onboarding-step"><div className="onboarding-mark soft"><SlidersHorizontal size={24} /></div><h2>想去哪些城市？</h2><p>可以多选，也可以跳过。搜索和筛选页仍能看到全部岗位。</p><input className="onboarding-input" name="onboarding-cities" type="text" autoComplete="off" value={draft.cities.join(", ")} onChange={(event) => setDraft({ ...draft, cities: event.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} placeholder="例如：武汉，北京，上海" /><div className="suggestion-row">{["武汉", "北京", "上海", "深圳", "杭州", "广州"].map((city) => <button type="button" key={city} className={draft.cities.includes(city) ? "is-selected" : ""} onClick={() => setDraft({ ...draft, cities: draft.cities.includes(city) ? draft.cities.filter((item) => item !== city) : [...draft.cities, city] })}>{draft.cities.includes(city) && <Check size={13} />}{city}</button>)}</div><div className="onboarding-buttons"><button type="button" className="secondary-button" onClick={() => setStep(1)}>上一步</button><button type="button" className="primary-button" onClick={() => setStep(3)}>下一步 <ChevronRight size={16} /></button></div></div> : <div className="onboarding-step"><div className="onboarding-mark green"><Heart size={24} /></div><h2>你更想看哪些岗位？</h2><p>先选 1-3 个最关注的方向，之后还可以继续调整。</p><div className="onboarding-role-grid">{PUBLIC_ROLE_CATEGORIES.filter((role) => role !== "其他" && role !== "财务/审计").slice(0, 9).map((role) => <button type="button" key={role} className={draft.roles.includes(role) ? "is-selected" : ""} onClick={() => toggleRole(role)}>{draft.roles.includes(role) && <Check size={14} />}{role}</button>)}</div><div className="onboarding-buttons"><button type="button" className="secondary-button" onClick={() => setStep(2)}>上一步</button><button type="button" className="primary-button" onClick={() => void onSave(draft)}>完成设置 <Check size={16} /></button></div></div>}</section></div>;
}

function JobModal({ job, historical = false, state, events, loading, onClose, onInterest, onStage, onEvent, onToggleEvent }: { job: JobPosting; historical?: boolean; state?: UserJobState; events: ApplicationEvent[]; loading: boolean; onClose: () => void; onInterest: (interest: Interest) => void; onStage: (stage: Stage) => void; onEvent: (event: Omit<ApplicationEvent, "id" | "createdAt">) => Promise<void>; onToggleEvent: (event: ApplicationEvent) => Promise<void> }) {
  const [eventForm, setEventForm] = useState(false);
  const [applyConfirmOpen, setApplyConfirmOpen] = useState(false);
  const [draft, setDraft] = useState({ type: "INTERVIEW" as EventType, scheduledAt: "", locationOrLink: "", note: "", round: "1" });
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [onClose]);
  const submitEvent = async (event: FormEvent) => { event.preventDefault(); if (!draft.scheduledAt) return; await onEvent({ jobId: job.id, type: draft.type, scheduledAt: new Date(draft.scheduledAt).toISOString(), locationOrLink: draft.locationOrLink || undefined, note: draft.note || undefined, round: draft.type === "INTERVIEW" ? Number(draft.round) || 1 : undefined, completed: false }); setEventForm(false); setDraft({ ...draft, scheduledAt: "", locationOrLink: "", note: "" }); };
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className={`modal job-modal ${job.provisional ? "is-provisional" : ""}`} role="dialog" aria-modal="true" aria-labelledby="job-modal-title"><div className="modal-header"><div className="modal-source-line"><span className={`source-badge ${job.provisional ? "source-provisional" : `source-${job.sourceLevel.toLowerCase()}`}`}>{job.provisional ? jobSourceLabel(job) : job.sourceLevel === "DEMO" ? "演示快照" : "官方来源"}</span>{historical && <span className="source-badge source-history">历史岗位</span>}<span>最后核验 {formatDateTime(job.lastVerifiedAt)}</span></div><button type="button" className="icon-button" onClick={onClose} aria-label="关闭岗位详情"><X size={19} aria-hidden="true" /></button></div><div className="job-modal-heading"><CompanyLogo companyId={job.companyId} companyName={job.companyName} size="large" /><div><span className="company-line"><strong>{job.companyName}</strong><span className={`source-badge source-${job.sourceLevel.toLowerCase()}`}>{job.companyType}</span></span><h2 id="job-modal-title">{job.title}</h2><p>{displayLocations(job)} · {job.roleCategory} · {job.companyIndustry}</p></div></div>{historical && <div className="historical-notice" role="status"><Archive size={15} aria-hidden="true" /><span>这是你保存在本机的历史岗位，已退出当前公共收录范围；投递阶段、面试记录和备注仍会保留。</span></div>}<div className="modal-meta-grid"><MetaItem label="届别 / 批次" value={`${job.cohort} · ${job.batch}`} /><MetaItem label="学历要求" value={job.education} /><MetaItem label="企业发布日期" value={job.publishDate ? formatDate(job.publishDate) : "官网未标注"} /><MetaItem label="申请截止" value={job.deadline ? formatDate(job.deadline) : "待确认"} /></div>{loading && <div className="detail-loading"><LoaderCircle className="spin" size={18} aria-hidden="true" />正在加载完整 JD…</div>}<div className="job-detail-body"><section><h3>岗位描述</h3><p>{job.description || "详情正在从来源分片加载。"}</p></section><section><h3>任职要求</h3><ul>{(job.requirements.length ? job.requirements : ["请以企业官网最新岗位页面为准"]).map((item) => <li key={item}>{item}</li>)}</ul></section><section><h3>关键词</h3><div className="tag-row">{[...job.skills, ...job.majorTags].map((item) => <span className="skill-tag" key={item}>{item}</span>)}</div></section><section className="provenance-box"><div><Info size={16} aria-hidden="true" /><span><strong>来源证据</strong><small>{job.sourceName} · 首次收录 {formatDateTime(job.firstSeenAt)} · 最后核验 {formatDateTime(job.lastVerifiedAt)}</small></span></div><a href={job.sourceUrl} target="_blank" rel="noreferrer">查看来源 <ExternalLink size={14} aria-hidden="true" /></a></section></div><div className="application-panel"><div className="application-panel-heading"><div><h3>我的记录</h3><p>记录这份岗位的投递阶段与兴趣。</p></div><span className="local-only"><LockKeyhole size={13} aria-hidden="true" />只在本机</span></div><div className="interest-actions"><button type="button" className={`interest-button suitable ${state?.interest === "SUITABLE" ? "is-active" : ""}`} onClick={() => onInterest(state?.interest === "SUITABLE" ? "UNSET" : "SUITABLE")}><Heart size={16} fill={state?.interest === "SUITABLE" ? "currentColor" : "none"} aria-hidden="true" />合适</button><button type="button" className={`interest-button unsuitable ${state?.interest === "UNSUITABLE" ? "is-active" : ""}`} onClick={() => onInterest(state?.interest === "UNSUITABLE" ? "UNSET" : "UNSUITABLE")}><Archive size={16} aria-hidden="true" />不合适</button></div><div className="stage-progress"><ModernSelect label="投递阶段" name={`job-detail-stage-${job.id}`} value={state?.stage ?? "NOT_APPLIED"} onChange={(next) => onStage(next as Stage)} options={STAGE_ORDER.map((item) => ({ value: item, label: STAGE_LABELS[item] }))} ariaLabel="投递阶段" /><button type="button" className="primary-button apply-button" onClick={() => { window.open(job.applyUrl, "_blank", "noopener,noreferrer"); setApplyConfirmOpen(true); }}><ExternalLink size={16} aria-hidden="true" />去官网投递</button></div>{applyConfirmOpen && <div className="apply-confirm" role="status"><div><strong>投递完成了吗？</strong><span>回到这里后再登记，不会自动修改你的阶段。</span></div><div className="apply-confirm-actions"><button type="button" className="secondary-button" onClick={() => setApplyConfirmOpen(false)}>暂不登记</button><button type="button" className="primary-button" onClick={() => { onStage("APPLIED"); setApplyConfirmOpen(false); }}>登记为已投递</button></div></div>}</div><div className="modal-timeline"><div className="timeline-heading"><div><h3>本地时间线</h3><p>阶段变更和你手动添加的事件会按时间保留。</p></div><button type="button" className="secondary-button" onClick={() => setEventForm((value) => !value)}><Plus size={15} aria-hidden="true" />添加事件</button></div>{eventForm && <form className="inline-event-form" onSubmit={submitEvent}><ModernSelect name="inline-event-type" value={draft.type} onChange={(type) => setDraft({ ...draft, type: type as EventType })} options={EVENT_TYPES.map((item) => ({ value: item, label: EVENT_LABELS[item] }))} ariaLabel="事件类型" />{draft.type === "INTERVIEW" && <input name="inline-interview-round" type="number" min="1" max="20" autoComplete="off" inputMode="numeric" value={draft.round} onChange={(event) => setDraft({ ...draft, round: event.target.value })} aria-label="面试轮次" /> }<input name="inline-scheduled-at" type="datetime-local" autoComplete="off" value={draft.scheduledAt} onChange={(event) => setDraft({ ...draft, scheduledAt: event.target.value })} aria-label="时间" /><input name="inline-event-note" autoComplete="off" value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} placeholder="备注" aria-label="备注" /><button className="primary-button" type="submit"><Check size={14} aria-hidden="true" />保存</button></form>}{events.length ? <div className="modal-event-list">{events.slice().sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? "")).map((event) => <EventRow key={event.id} event={event} job={job} onOpen={() => undefined} onToggleComplete={onToggleEvent} detailed />)}</div> : <p className="muted-copy">阶段变更会自动出现在这里；面试、测评和跟进可以添加多轮安排。</p>}</div><div className="modal-footer-links"><span>数据源：{job.sourceName}</span><span>来源级别 {job.provisional ? "临时入口 · 待核验" : job.sourceLevel}</span><span>内容变更 {job.changedAt ? formatDateTime(job.changedAt) : "未标记"}</span></div></section></div>;
}

function MetaItem({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

export { App };
