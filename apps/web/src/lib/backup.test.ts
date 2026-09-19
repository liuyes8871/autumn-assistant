import { describe, expect, it } from "vitest";
import { parseBackup } from "./backup";

const valid = {
  schema: "AutumnAssistantBackupV1",
  exportedAt: "2026-09-02T08:00:00.000Z",
  catalogVersion: "demo-2026.09.02",
  preferences: { id: "main", cohort: "2027", cities: [], roles: [], industries: [], companyTypes: [], setupComplete: true },
  jobStates: [],
  events: [],
};

describe("backup validation", () => {
  it("accepts a versioned empty backup", () => {
    expect(parseBackup(valid).schema).toBe("AutumnAssistantBackupV1");
  });

  it("rejects incompatible or damaged files", () => {
    expect(() => parseBackup({ ...valid, schema: "old-backup" })).toThrow();
    expect(() => parseBackup({ ...valid, events: "not-an-array" })).toThrow();
  });
});
