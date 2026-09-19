import { z } from "zod";
import type { AutumnAssistantBackupV1 } from "../types";

const interest = z.enum(["UNSET", "SUITABLE", "UNSUITABLE"]);
const stage = z.enum(["NOT_APPLIED", "APPLIED", "SCREENING", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"]);
const eventType = z.enum(["SCREENING", "ASSESSMENT", "INTERVIEW", "FOLLOW_UP", "OFFER", "REJECTED", "NOTE"]);

const backupSchema = z.object({
  schema: z.literal("AutumnAssistantBackupV1"),
  exportedAt: z.string().datetime({ offset: true }),
  catalogVersion: z.string().min(1),
  preferences: z.object({
    id: z.literal("main"),
    cohort: z.string(),
    cities: z.array(z.string()),
    roles: z.array(z.string()),
    industries: z.array(z.string()),
    companyTypes: z.array(z.string()),
    educationLevels: z.array(z.string()).optional().default([]),
    batches: z.array(z.string()).optional().default([]),
    companyScales: z.array(z.string()).optional().default([]),
    setupComplete: z.boolean(),
    showProvisionalJobs: z.boolean().optional().default(false),
  }),
  jobStates: z.array(z.object({
    jobId: z.string().min(1),
    snapshot: z.object({
      companyId: z.string().optional(), title: z.string(), companyName: z.string(), city: z.string(), roleCategory: z.string(), companyIndustry: z.string(), applyUrl: z.string(), sourceUrl: z.string(), lastVerifiedAt: z.string(),
      companyType: z.string().optional(), companyScale: z.string().optional(), cohort: z.string().optional(), batch: z.string().optional(), education: z.string().optional(),
      majorTags: z.array(z.string()).optional(), skills: z.array(z.string()).optional(), description: z.string().optional(), requirements: z.array(z.string()).optional(),
      publishDate: z.string().optional(), deadline: z.string().optional(), firstSeenAt: z.string().optional(), sourceName: z.string().optional(), sourceLevel: z.string().optional(), changedAt: z.string().optional(),
    }),
    interest,
    stage,
    appliedAt: z.string().optional(),
    createdAt: z.string(),
    updatedAt: z.string(),
  })),
  events: z.array(z.object({
    id: z.number().optional(),
    jobId: z.string().min(1),
    type: eventType,
    round: z.number().optional(),
    scheduledAt: z.string().optional(),
    completedAt: z.string().optional(),
    locationOrLink: z.string().optional(),
    completed: z.boolean(),
    note: z.string().optional(),
    createdAt: z.string(),
  })),
});

export function parseBackup(value: unknown): AutumnAssistantBackupV1 {
  const parsed = backupSchema.parse(value);
  return {
    ...parsed,
    preferences: {
      ...parsed.preferences,
      educationLevels: parsed.preferences.educationLevels ?? [],
      batches: parsed.preferences.batches ?? [],
      companyScales: parsed.preferences.companyScales ?? [],
    },
  } as AutumnAssistantBackupV1;
}
