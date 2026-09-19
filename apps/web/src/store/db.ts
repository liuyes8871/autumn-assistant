import Dexie, { type Table } from "dexie";
import type { ApplicationEvent, JobPosting, Preferences, UserJobState } from "../types";
import { DEFAULT_PREFERENCES } from "../types";

export interface MetadataRecord {
  key: string;
  value: string;
}

class AutumnDatabase extends Dexie {
  preferences!: Table<Preferences, string>;
  jobStates!: Table<UserJobState, string>;
  events!: Table<ApplicationEvent, number>;
  metadata!: Table<MetadataRecord, string>;

  constructor() {
    super("autumn-assistant-local");
    this.version(1).stores({
      preferences: "id",
      jobStates: "jobId, stage, interest, updatedAt",
      events: "++id, jobId, scheduledAt, type",
      metadata: "key"
    });
    // Keep the original stores intact and normalize records written by the
    // first MVP. Dexie will run this upgrade only for existing databases, so
    // no user interest, stage, event, or snapshot is discarded.
    this.version(2).stores({
      preferences: "id",
      jobStates: "jobId, stage, interest, updatedAt",
      events: "++id, jobId, scheduledAt, type",
      metadata: "key"
    }).upgrade(async (transaction) => {
      const preferencesTable = transaction.table<Preferences, string>("preferences");
      const existing = await preferencesTable.get("main");
      if (existing) {
        await preferencesTable.put({
          ...DEFAULT_PREFERENCES,
          ...existing,
          educationLevels: existing.educationLevels ?? [],
          batches: existing.batches ?? [],
          companyScales: existing.companyScales ?? [],
          locationScopes: existing.locationScopes ?? ["MAINLAND_CHINA"],
          provinceCodes: existing.provinceCodes ?? [],
          cityCodes: existing.cityCodes ?? [],
          showProvisionalJobs: existing.showProvisionalJobs ?? false,
        });
      }
    });
  }
}

export const db = new AutumnDatabase();

export async function ensurePreferences(): Promise<Preferences> {
  const existing = await db.preferences.get("main");
  if (existing) {
    const normalized = { ...DEFAULT_PREFERENCES, ...existing, educationLevels: existing.educationLevels ?? [], batches: existing.batches ?? [], companyScales: existing.companyScales ?? [], locationScopes: existing.locationScopes ?? ["MAINLAND_CHINA"], provinceCodes: existing.provinceCodes ?? [], cityCodes: existing.cityCodes ?? [], showProvisionalJobs: existing.showProvisionalJobs ?? false };
    if (JSON.stringify(normalized) !== JSON.stringify(existing)) await db.preferences.put(normalized);
    return normalized;
  }
  await db.preferences.put(DEFAULT_PREFERENCES);
  return DEFAULT_PREFERENCES;
}

export async function savePreferences(preferences: Preferences): Promise<void> {
  await db.preferences.put({
    ...DEFAULT_PREFERENCES,
    ...preferences,
    educationLevels: preferences.educationLevels ?? [],
    batches: preferences.batches ?? [],
    companyScales: preferences.companyScales ?? [],
    locationScopes: preferences.locationScopes ?? ["MAINLAND_CHINA"],
    provinceCodes: preferences.provinceCodes ?? [],
    cityCodes: preferences.cityCodes ?? [],
    showProvisionalJobs: preferences.showProvisionalJobs ?? false,
  });
}

export async function saveJobState(
  job: JobPosting,
  patch: Partial<Pick<UserJobState, "interest" | "stage" | "appliedAt">>
): Promise<UserJobState> {
  const now = new Date().toISOString();
  const previous = await db.jobStates.get(job.id);
  const next: UserJobState = {
    jobId: job.id,
    snapshot: {
      companyId: job.companyId,
      title: job.title,
      companyName: job.companyName,
      city: job.city,
      locations: job.locations ? [...job.locations] : undefined,
      roleCategory: job.roleCategory,
      companyIndustry: job.companyIndustry,
      companyType: job.companyType,
      companyScale: job.companyScale,
      cohort: job.cohort,
      batch: job.batch,
      education: job.education,
      majorTags: [...job.majorTags],
      skills: [...job.skills],
      description: job.description,
      requirements: [...job.requirements],
      publishDate: job.publishDate,
      deadline: job.deadline,
      firstSeenAt: job.firstSeenAt,
      applyUrl: job.applyUrl,
      sourceUrl: job.sourceUrl,
      sourceName: job.sourceName,
      sourceLevel: job.sourceLevel,
      changedAt: job.changedAt,
      lastVerifiedAt: job.lastVerifiedAt
    },
    interest: patch.interest ?? previous?.interest ?? "UNSET",
    stage: patch.stage ?? previous?.stage ?? "NOT_APPLIED",
    appliedAt: patch.appliedAt ?? previous?.appliedAt,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now
  };
  await db.jobStates.put(next);
  return next;
}

export async function deleteJobState(jobId: string): Promise<void> {
  await db.jobStates.delete(jobId);
}

export async function addEvent(event: Omit<ApplicationEvent, "id" | "createdAt">): Promise<number> {
  return db.events.add({ ...event, createdAt: new Date().toISOString() });
}

export async function toggleEvent(event: ApplicationEvent): Promise<void> {
  if (event.id === undefined) return;
  await db.events.update(event.id, {
    completed: !event.completed,
    completedAt: !event.completed ? new Date().toISOString() : undefined,
  });
}

export async function replaceAllLocalData(
  preferences: Preferences,
  jobStates: UserJobState[],
  events: ApplicationEvent[]
): Promise<void> {
  await db.transaction("rw", db.preferences, db.jobStates, db.events, async () => {
    await db.preferences.clear();
    await db.jobStates.clear();
    await db.events.clear();
    await db.preferences.put({
      ...DEFAULT_PREFERENCES,
      ...preferences,
      educationLevels: preferences.educationLevels ?? [],
      batches: preferences.batches ?? [],
      companyScales: preferences.companyScales ?? [],
      locationScopes: preferences.locationScopes ?? ["MAINLAND_CHINA"],
      provinceCodes: preferences.provinceCodes ?? [],
      cityCodes: preferences.cityCodes ?? [],
      showProvisionalJobs: preferences.showProvisionalJobs ?? false,
    });
    if (jobStates.length) await db.jobStates.bulkPut(jobStates);
    if (events.length) await db.events.bulkAdd(events.map(({ id: _id, ...event }) => event));
  });
}

export async function clearLocalData(): Promise<void> {
  await db.transaction("rw", db.preferences, db.jobStates, db.events, async () => {
    await db.preferences.clear();
    await db.jobStates.clear();
    await db.events.clear();
    await db.preferences.put(DEFAULT_PREFERENCES);
  });
}
