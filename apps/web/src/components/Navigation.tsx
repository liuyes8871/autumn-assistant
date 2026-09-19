import {
  Boat,
  Briefcase,
  CalendarBlank,
  CircleNotch,
  GearSix,
  Package,
  SquaresFour,
} from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

export type AppRoute = "jobs" | "progress" | "schedule" | "settings";

export const NAV_ITEMS: ReadonlyArray<{ id: AppRoute; label: string; icon: Icon }> = [
  { id: "jobs", label: "岗位", icon: SquaresFour },
  { id: "progress", label: "进度", icon: Briefcase },
  { id: "schedule", label: "日程", icon: CalendarBlank },
  { id: "settings", label: "设置", icon: GearSix },
];

function assetPath(path: string): string {
  const base = (import.meta.env.BASE_URL || "/").replace(/\/?$/, "/");
  return `${base}${path.replace(/^\/+/, "")}`;
}

const BRAND_MARK_ASSET = assetPath("assets/visuals/brand-yizhou-mark-new.webp");

type NavigationProps = {
  route: AppRoute;
  navigate: (route: AppRoute) => void;
  offlineCatalog: boolean;
  demoCatalog: boolean;
};

export function GlobalHeader({ route, navigate, offlineCatalog, demoCatalog }: NavigationProps) {
  const sentinelRef = useRef<HTMLSpanElement>(null);
  const [compact, setCompact] = useState(false);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(([entry]) => {
      setCompact(!entry.isIntersecting);
    }, { rootMargin: "0px", threshold: 0 });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <span ref={sentinelRef} className="masthead-sentinel" aria-hidden="true" />
      <header className={`topbar ${compact ? "is-compact" : ""}`}>
      <a className="brand-lockup" href="#/jobs" aria-label="秋招助手首页">
        <BrandMark />
        <span className="brand-copy"><strong>秋招助手</strong></span>
      </a>
      <nav className="topbar-nav" aria-label="主导航">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
          <a key={id} className={`topbar-nav-item ${route === id ? "is-active" : ""}`} href={`#/${id}`} aria-current={route === id ? "page" : undefined}>
            <Icon className="topbar-nav-icon" size={18} weight="regular" /><span>{label}</span>
          </a>
        ))}
      </nav>
      <div className="topbar-actions">
        <span className={`sync-status ${offlineCatalog || demoCatalog ? "is-demo" : ""}`}>
          <span className="sync-status-icon">{offlineCatalog ? <Package size={16} weight="regular" /> : <CircleNotch size={16} weight="regular" />}</span>
          {offlineCatalog ? "离线缓存" : demoCatalog ? "演示目录" : "目录已同步"}
        </span>
      </div>
      </header>
    </>
  );
}

export function MobileBottomNavigation({ route, navigate }: Pick<NavigationProps, "route" | "navigate">) {
  return (
    <nav className="mobile-nav" aria-label="底部导航">
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
        <button key={id} className={route === id ? "is-active" : ""} onClick={() => navigate(id)} aria-current={route === id ? "page" : undefined}>
          <Icon size={21} weight="regular" /><span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

/** A compact boat-and-seal mark that remains legible at favicon scale. */
export function BrandMark({ compact = false }: { compact?: boolean }) {
  const [imageFailed, setImageFailed] = useState(false);
  return <span className={`brand-mark ${compact ? "is-compact" : ""} ${imageFailed ? "is-fallback" : "has-image"}`} aria-hidden="true">
    {imageFailed ? <>
      <Boat className="brand-mark-boat" size={compact ? 20 : 24} weight="bold" />
      <span className="brand-mark-wave" />
      <span className="brand-mark-seal" />
    </> : <><img className="brand-mark-image" src={BRAND_MARK_ASSET} alt="" width="512" height="220" onError={() => setImageFailed(true)} /><span className="brand-mark-image-seal" /></>}
  </span>;
}
