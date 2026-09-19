import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { JobLocation, JobPosting, Preferences, UserJobState } from "../types";

/** Merge Tailwind utility classes while preserving the last semantic value. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const SHANGHAI_TIME_ZONE = "Asia/Shanghai";

function asDate(value?: string): Date | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

export function formatDate(value?: string): string {
  const date = asDate(value);
  if (!date) return value ? value.slice(0, 10) : "未标注";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: SHANGHAI_TIME_ZONE,
    month: "numeric",
    day: "numeric",
  }).format(date);
}

export function formatDateTime(value?: string): string {
  const date = asDate(value);
  if (!date) return value ? value.slice(0, 16).replace("T", " ") : "未标注";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: SHANGHAI_TIME_ZONE,
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

/** Number of calendar days from now in the Shanghai business time zone. */
export function daysFromNow(value?: string): number | null {
  const date = asDate(value);
  if (!date) return null;
  const day = (input: Date) => {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: SHANGHAI_TIME_ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(input);
    const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
    return Date.UTC(Number(values.year), Number(values.month) - 1, Number(values.day));
  };
  return Math.round((day(date) - day(new Date())) / 86400000);
}

export function isDeadlineSoon(value?: string, days = 7): boolean {
  const remaining = daysFromNow(value);
  return remaining !== null && remaining >= 0 && remaining <= days;
}

export function isOverdue(value?: string): boolean {
  const remaining = daysFromNow(value);
  return remaining !== null && remaining < 0;
}

export function splitCities(value?: string): string[] {
  if (!value) return [];
  const seen = new Set<string>();
  return value
    .split(/[、/，,；;|]+/)
    .map((item) => item.trim().replace(/市$/, ""))
    .filter((item) => item && !seen.has(item) && seen.add(item));
}

export function displayLocations(job: Pick<JobPosting, "city" | "locations">): string {
  const structured = (job.locations ?? []).map((location) => location.displayName.trim()).filter(Boolean);
  if (structured.length) return Array.from(new Set(structured)).join("、");
  const cities = splitCities(job.city);
  return cities.length ? cities.join("、") : job.city || "地点待定";
}

function normalizedLocationName(value?: string): string {
  return (value ?? "").trim().replace(/市$/, "");
}

function locationMatchesLegacyCity(location: JobLocation, cities: string[]): boolean {
  if (!cities.length) return true;
  const candidates = [location.displayName, location.raw, location.cityCode?.split("-").slice(-1)[0]]
    .filter(Boolean)
    .map(normalizedLocationName);
  return cities.some((city) => candidates.includes(normalizedLocationName(city)));
}

/**
 * Location filters are intentionally evaluated per location record. This keeps
 * a province and city selection from matching two different locations on a
 * multi-city posting.
 */
export function matchesLocation(job: Pick<JobPosting, "city" | "locations">, preferences: Preferences): boolean {
  const scopes = preferences.locationScopes ?? [];
  const provinces = preferences.provinceCodes ?? [];
  const cityCodes = preferences.cityCodes ?? [];
  const cities = preferences.cities ?? [];
  if (!scopes.length && !provinces.length && !cityCodes.length && !cities.length) return true;

  const locations = job.locations?.length
    ? job.locations
    : splitCities(job.city).map((city): JobLocation => ({
        scope: "MAINLAND_CHINA",
        displayName: city,
        raw: city,
      }));
  if (!locations.length) return false;

  return locations.some((location) => {
    const scopeMatch = !scopes.length || scopes.includes(location.scope);
    const provinceMatch = !provinces.length || Boolean(location.provinceCode && provinces.includes(location.provinceCode));
    const cityCodeMatch = !cityCodes.length || Boolean(location.cityCode && cityCodes.includes(location.cityCode));
    const legacyCityMatch = !cities.length || locationMatchesLegacyCity(location, cities);
    const nationwide = /全国|大陆|不限/.test(location.displayName) || /全国|大陆|不限/.test(location.raw);
    const regionMatch = nationwide && (location.scope === "MAINLAND_CHINA" || !scopes.length);
    return scopeMatch && (regionMatch || (provinceMatch && cityCodeMatch && legacyCityMatch));
  });
}

function intersects<T>(selected: readonly T[] | undefined, value: T | undefined): boolean {
  return !selected?.length || (value !== undefined && selected.includes(value));
}

export function matchesPreferences(job: JobPosting, preferences: Preferences): boolean {
  return matchesLocation(job, preferences)
    && (!preferences.cohort || job.cohort === preferences.cohort)
    && intersects(preferences.roles, job.roleCategory)
    && intersects(preferences.industries, job.companyIndustry)
    && intersects(preferences.companyTypes, job.companyType)
    && intersects(preferences.educationLevels, job.education)
    && intersects(preferences.batches, job.batch)
    && intersects(preferences.companyScales, job.companyScale);
}

export function snapshotFromState(state: UserJobState): JobPosting {
  const snapshot = state.snapshot;
  return {
    id: state.jobId,
    companyId: snapshot.companyId ?? `local-${state.jobId}`,
    companyName: snapshot.companyName,
    companyIndustry: snapshot.companyIndustry,
    companyType: snapshot.companyType ?? "未知",
    companyScale: snapshot.companyScale ?? "未知",
    title: snapshot.title,
    city: snapshot.city,
    locations: snapshot.locations,
    roleCategory: snapshot.roleCategory,
    cohort: snapshot.cohort ?? "未知",
    batch: snapshot.batch ?? "未知",
    education: snapshot.education ?? "不限",
    majorTags: snapshot.majorTags ?? [],
    skills: snapshot.skills ?? [],
    description: snapshot.description ?? "",
    requirements: snapshot.requirements ?? [],
    publishDate: snapshot.publishDate,
    deadline: snapshot.deadline,
    firstSeenAt: snapshot.firstSeenAt ?? state.createdAt,
    lastVerifiedAt: snapshot.lastVerifiedAt,
    contentHash: "local-snapshot",
    status: "CLOSED",
    applyUrl: snapshot.applyUrl,
    sourceUrl: snapshot.sourceUrl,
    sourceName: snapshot.sourceName ?? "本机历史快照",
    sourceLevel: snapshot.sourceLevel ?? "DEMO",
    detailShard: "local-snapshot",
    changedAt: snapshot.changedAt,
  };
}

export function escapeCsvCell(value: unknown): string {
  const text = String(value ?? "");
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function downloadFile(filename: string, content: string | Blob, mimeType = "text/plain;charset=utf-8"): void {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
