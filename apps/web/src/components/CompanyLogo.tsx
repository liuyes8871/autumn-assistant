import {
  siBilibili,
  siDji,
  siHuawei,
  siLenovo,
  siMeituan,
  siOppo,
  siVivo,
  siXiaomi,
} from "simple-icons";
import type { SimpleIcon } from "simple-icons";
import tencentOfficialMark from "../assets/company-logos/tencent.png";
import lenovoOfficialMark from "../assets/company-logos/lenovo-official.png";

/**
 * A small, local-first company mark.
 *
 * The Simple Icons package provides the path data locally, so the PWA does
 * not make a logo request at runtime. These are recognizable brand marks,
 * not a claim that the asset is an official recruitment-page logo. Sources
 * that have not passed an asset audit intentionally fall back to a text mark.
 */
const BRAND_MARKS: Record<string, SimpleIcon | undefined> = {
  bilibili: siBilibili,
  dji: siDji,
  huawei: siHuawei,
  lenovo: siLenovo,
  meituan: siMeituan,
  oppo: siOppo,
  vivo: siVivo,
  xiaomi: siXiaomi,
};

/** First-party assets are opt-in and kept in the repository for offline use. */
const OFFICIAL_MARKS: Record<string, string | undefined> = {
  lenovo: lenovoOfficialMark,
  tencent: tencentOfficialMark,
};

type LogoSize = "default" | "today" | "small" | "tiny" | "large";

export function CompanyLogo({
  companyId,
  companyName,
  size = "default",
  className = "",
}: {
  companyId?: string;
  companyName: string;
  size?: LogoSize;
  className?: string;
}) {
  const officialMark = companyId ? OFFICIAL_MARKS[companyId] : undefined;
  const mark = companyId ? BRAND_MARKS[companyId] : undefined;
  // Keep a visible, deterministic mark for companies whose official artwork
  // has not been audited yet. A first character is safer than guessing a
  // third-party logo, while the surrounding seal styling makes it read as an
  // icon rather than an empty tile.
  const fallback = companyName.trim().slice(0, 1) || "企";
  const hasMark = Boolean(officialMark || mark);
  const classes = [
    "company-avatar",
    "company-logo",
    size !== "default" ? size === "today" ? "today-avatar" : size : "",
    hasMark ? "has-brand-mark" : "is-text-mark",
    className,
  ].filter(Boolean).join(" ");

  return <span
    className={classes}
    aria-hidden="true"
    title={`${companyName}${officialMark ? "官方品牌标识" : mark ? "品牌标识" : "文字标识"}`}
    data-logo-kind={officialMark ? "official-mark" : mark ? "brand-mark" : "text-mark"}
    data-logo-source={officialMark ? companyId === "lenovo" ? "lenovo.com" : "tencent.com" : mark ? "simple-icons" : "fallback"}
  >
    {officialMark ? <img src={officialMark} alt="" aria-hidden="true" /> : mark ? <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
      <title>{mark.title}</title>
      <path d={mark.path} />
    </svg> : <span className="company-logo-fallback"><span>{fallback}</span><i aria-hidden="true" /></span>}
  </span>;
}

export const companyBrandMarkIds = Object.keys(BRAND_MARKS);
