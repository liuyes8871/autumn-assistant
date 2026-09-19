import { describe, expect, it } from "vitest";
import { DEMO_JOBS } from "../data/catalog";
import { escapeCsvCell, matchesPreferences, snapshotFromState, splitCities } from "./utils";
import type { Preferences } from "../types";

const preference = (overrides: Partial<Preferences> = {}): Preferences => ({
  id: "main",
  cohort: "2027",
  cities: [],
  roles: [],
  industries: [],
  companyTypes: [],
  setupComplete: true,
  ...overrides,
});

describe("job matching", () => {
  it("matches one city inside a multi-city official posting", () => {
    expect(splitCities("北京、武汉市 / 上海")).toEqual(["北京", "武汉", "上海"]);
    const job = { ...DEMO_JOBS[0], city: "北京、武汉、上海" };
    expect(matchesPreferences(job, preference({ cities: ["武汉"] }))).toBe(true);
  });

  it("matches every selected dimension transparently", () => {
    const job = DEMO_JOBS.find((item) => item.id === "demo-tencent-operations-wuhan")!;
    expect(matchesPreferences(job, preference({ cities: ["武汉"], roles: ["运营"] }))).toBe(true);
    expect(matchesPreferences(job, preference({ cities: ["上海"] }))).toBe(false);
    expect(matchesPreferences(job, preference({ cohort: "2028" }))).toBe(false);
  });

  it("allows an empty preference dimension", () => {
    const job = DEMO_JOBS[0];
    expect(matchesPreferences(job, preference({ cohort: "" }))).toBe(true);
  });

  it("keeps province and city filters on the same location record", () => {
    const job = {
      ...DEMO_JOBS[0],
      city: "北京、上海",
      locations: [
        { scope: "MAINLAND_CHINA" as const, provinceCode: "BJ", cityCode: "BJ-北京", displayName: "北京", raw: "北京" },
        { scope: "MAINLAND_CHINA" as const, provinceCode: "SH", cityCode: "SH-上海", displayName: "上海", raw: "上海" },
      ],
    };
    expect(matchesPreferences(job, preference({ provinceCodes: ["BJ"], cityCodes: ["SH"] }))).toBe(false);
    expect(matchesPreferences(job, preference({ provinceCodes: ["SH"], cityCodes: ["SH-上海"] }))).toBe(true);
  });

  it("keeps nationwide postings visible for selected mainland regions", () => {
    const job = {
      ...DEMO_JOBS[0],
      city: "全国",
      locations: [{ scope: "MAINLAND_CHINA" as const, displayName: "中国大陆 · 全国", raw: "全国" }],
    };
    expect(matchesPreferences(job, preference({ provinceCodes: ["HB"], cityCodes: ["HB-武汉"] }))).toBe(true);
  });
});

describe("CSV safety", () => {
  it("quotes commas and neutralizes spreadsheet formulas", () => {
    expect(escapeCsvCell("上海,北京")).toBe('"上海,北京"');
    expect(escapeCsvCell("=HYPERLINK(\"https://example.com\")")).toBe('"\'=HYPERLINK(""https://example.com"")"');
    expect(escapeCsvCell("普通文本")).toBe('"普通文本"');
  });
});

describe("demo catalog contract", () => {
  it("has official-looking links and required dates for every demo job", () => {
    for (const job of DEMO_JOBS) {
      expect(job.applyUrl.startsWith("https://")).toBe(true);
      expect(job.sourceUrl.startsWith("https://")).toBe(true);
      expect(job.firstSeenAt).toContain("2026");
      expect(job.lastVerifiedAt).toContain("2026");
      expect(job.detailShard).toBe("demo-a");
    }
  });
});

describe("local snapshot", () => {
  it("keeps the JD available when a public posting is gone", () => {
    const job = DEMO_JOBS[0];
    const snapshot = snapshotFromState({
      jobId: job.id,
      snapshot: {
        title: job.title,
        companyName: job.companyName,
        city: job.city,
        roleCategory: job.roleCategory,
        companyIndustry: job.companyIndustry,
        companyType: job.companyType,
        companyScale: job.companyScale,
        cohort: job.cohort,
        batch: job.batch,
        education: job.education,
        majorTags: job.majorTags,
        skills: job.skills,
        description: job.description,
        requirements: job.requirements,
        publishDate: job.publishDate,
        deadline: job.deadline,
        firstSeenAt: job.firstSeenAt,
        applyUrl: job.applyUrl,
        sourceUrl: job.sourceUrl,
        sourceName: job.sourceName,
        sourceLevel: job.sourceLevel,
        lastVerifiedAt: job.lastVerifiedAt,
      },
      interest: "SUITABLE",
      stage: "APPLIED",
      createdAt: "2026-09-02T08:00:00.000Z",
      updatedAt: "2026-09-02T08:00:00.000Z",
    });
    expect(snapshot.description).toContain("参与产品用户运营");
    expect(snapshot.requirements).toEqual(job.requirements);
    expect(snapshot.deadline).toBe(job.deadline);
    expect(snapshot.status).toBe("CLOSED");
  });
});
