import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDirectory, "..");
const outputPath = resolve(projectRoot, "apps/web/public/data/community-leads.json");
const companiesPath = resolve(projectRoot, "registry/companies.json");
const sourcesPath = resolve(projectRoot, "registry/sources.json");
const openCliProfile = process.env.XHS_OPENCLI_PROFILE || process.env.OPENCLI_PROFILE || "";

// This is deliberately a local, opt-in discovery command. OpenCLI reuses the
// browser session the user already opened; this script never reads, prints or
// persists browser cookies, xsec_token values, or private account data.
const QUERIES = [
  "互联网公司 秋招 内推码 2027",
  "2027届 校招 官方招聘 互联网",
  "携程 内推码 2027",
  "京东 内推码 2027",
  "网易 内推码 2027",
  "小红书 内推 2027",
];
const WAIT_MS = 3000;

const sleep = (milliseconds) => new Promise((resolveResult) => setTimeout(resolveResult, milliseconds));

function parseOpenCliJson(stdout) {
  const first = stdout.indexOf("[");
  const last = stdout.lastIndexOf("]");
  if (first < 0 || last <= first) throw new Error("OpenCLI 没有返回可解析的搜索结果");
  const payload = JSON.parse(stdout.slice(first, last + 1));
  return Array.isArray(payload) ? payload : [];
}

function canonicalNoteUrl(value) {
  try {
    const parsed = new URL(String(value));
    const id = parsed.pathname.match(/(?:search_result|explore)\/([^/?]+)/)?.[1];
    return id ? `https://www.xiaohongshu.com/explore/${id}` : null;
  } catch {
    return null;
  }
}

function normalizedText(value) {
  return String(value || "").trim().toLowerCase().replace(/[\s·・()（）【】\[\]{}]/g, "");
}

function buildCompanyIndex(companies) {
  const aliases = new Map();
  const add = (label, company) => {
    const key = normalizedText(label);
    if (key.length >= 2 && !aliases.has(key)) aliases.set(key, company);
  };
  for (const company of companies) {
    add(company.name, company);
    add(company.id, company);
    for (const alias of company.aliases || []) add(alias, company);
  }
  // Common short names found in community titles. These are matching hints,
  // not evidence that a post is official.
  const extraAliases = {
    "字节": "bytedance", "抖音": "bytedance", "阿里": "alibaba", "阿里巴巴": "alibaba",
    "京东": "jd", "美团": "meituan", "携程": "ctrip", "滴滴": "didi", "小米": "xiaomi",
    "网易": "netease-games", "小红书": "xiaohongshu", "b站": "bilibili", "哔哩哔哩": "bilibili",
    "安克": "anker", "米哈游": "mihoyo", "贝壳": "ke", "快手": "kuaishou",
    "吉比特": "gigabyte", "shein": "shein", "希音": "shein", "宝宝巴士": "babybus",
    "赛力斯": "seres", "funplus": "funplus",
  };
  for (const [label, id] of Object.entries(extraAliases)) {
    const company = companies.find((item) => item.id === id);
    if (company) add(label, company);
  }
  return aliases;
}

function matchCompany(title, companyIndex) {
  const text = normalizedText(title);
  const matches = [...companyIndex.entries()]
    .filter(([alias]) => text.includes(alias))
    .sort((left, right) => right[0].length - left[0].length);
  return matches[0]?.[1] || null;
}

function officialUrlFor(company, sources) {
  if (!company) return { url: null, verified: false };
  const verified = sources.find((source) => source.companyId === company.id && source.status === "VERIFIED");
  if (verified?.sourceUrl) return { url: verified.sourceUrl, verified: true };
  return { url: company.careerUrl || sources.find((source) => source.companyId === company.id)?.sourceUrl || null, verified: false };
}

function leadFromResult(result, companyIndex, companies, sources, generatedAt) {
  const title = String(result.title || "").trim();
  const sourceUrl = canonicalNoteUrl(result.url);
  if (!title || !sourceUrl) return null;
  const company = matchCompany(title, companyIndex);
  const officialAccountSignal = /招聘|校招官方|官方招聘/.test(String(result.author || ""));
  const official = officialUrlFor(company, sources);
  return {
    id: `xhs:${sourceUrl.split("/").pop()}`,
    companyId: company?.id || null,
    companyName: company?.name || null,
    title,
    officialUrl: official.url,
    officialUrlVerified: official.verified,
    sourceUrl,
    sourcePlatform: "xiaohongshu",
    sourceAuthorLabel: officialAccountSignal ? "企业招聘账号信号" : "社区公开帖子",
    publishedAt: /^\d{4}-\d{2}-\d{2}$/.test(String(result.published_at || "")) ? result.published_at : null,
    discoveredAt: generatedAt,
    verificationStatus: "NEEDS_REVIEW",
    note: "仅作为公开招聘线索；企业官方入口和岗位状态需独立核验。个人内推信息不写入公共目录。",
  };
}

async function search(query) {
  const windowsOpenCliEntry = process.platform === "win32"
    ? resolve(process.env.APPDATA || "", "npm/node_modules/@jackwener/opencli/dist/src/main.js")
    : null;
  const command = process.platform === "win32" ? process.execPath : "opencli";
  const profileArgs = openCliProfile ? ["--profile", openCliProfile] : [];
  const args = windowsOpenCliEntry
    ? [windowsOpenCliEntry, ...profileArgs, "xiaohongshu", "search", query, "-f", "json"]
    : [...profileArgs, "xiaohongshu", "search", query, "-f", "json"];
  const { stdout, stderr } = await execFileAsync(command, args, {
    cwd: projectRoot,
    windowsHide: true,
    maxBuffer: 8 * 1024 * 1024,
  });
  // OpenCLI may print update notices to stderr. They are intentionally not
  // copied to the public artifact.
  if (stderr && /security|blocked|登录|captcha/i.test(stderr)) {
    throw new Error(`小红书搜索受限：${stderr.trim().slice(0, 240)}`);
  }
  return parseOpenCliJson(stdout);
}

async function main() {
  const [companiesPayload, sourcesPayload] = await Promise.all([
    readFile(companiesPath, "utf8").then(JSON.parse),
    readFile(sourcesPath, "utf8").then(JSON.parse),
  ]);
  const companies = Array.isArray(companiesPayload) ? companiesPayload : [];
  const sources = Array.isArray(sourcesPayload) ? sourcesPayload : [];
  const companyIndex = buildCompanyIndex(companies);
  const generatedAt = new Date().toISOString();
  const raw = [];
  const errors = [];

  for (const [index, query] of QUERIES.entries()) {
    try {
      raw.push(...await search(query));
    } catch (error) {
      errors.push({ query, message: error instanceof Error ? error.message : String(error) });
    }
    if (index < QUERIES.length - 1) await sleep(WAIT_MS);
  }

  const deduped = new Map();
  for (const result of raw) {
    const lead = leadFromResult(result, companyIndex, companies, sources, generatedAt);
    if (lead && !deduped.has(lead.id)) deduped.set(lead.id, lead);
  }
  const leads = [...deduped.values()].sort((left, right) => {
    const leftDate = left.publishedAt || "";
    const rightDate = right.publishedAt || "";
    return rightDate.localeCompare(leftDate) || left.title.localeCompare(right.title, "zh-CN");
  });
  const payload = {
    schemaVersion: 1,
    generatedAt,
    source: "xiaohongshu_opencli",
    privacy: {
      cookiesPersisted: false,
      xsecTokensPersisted: false,
      privateContentIncluded: false,
      referralCodesPersisted: false,
      disclaimer: "仅保存公开搜索结果的脱敏企业入口线索；社区帖子不等同于企业官方信息，个人内推信息不会写入公共目录。",
    },
    queries: QUERIES,
    errors,
    leads,
  };
  await writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ output: outputPath, queryCount: QUERIES.length, resultCount: raw.length, leadCount: leads.length, errorCount: errors.length }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
