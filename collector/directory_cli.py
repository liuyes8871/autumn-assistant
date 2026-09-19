from __future__ import annotations

"""Refresh the public company-entry file without making network requests.

This is useful for a Pages build that already has a known-good catalog: adding
an entry row must not require re-running the five-hour job collector.
"""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

from .authority_index import load_candidate_company_configs
from .company_directory import build_company_directory
from .community import sanitize_community_catalog
from .company_discovery import sanitize_entry_observation_map
from .registry import focus_company_map, load_companies, load_focus_registry, load_sources, source_can_run


def refresh_directory(
    *,
    companies_path: Path,
    sources_path: Path,
    data_dir: Path,
    output: Path | None = None,
    entry_state: Path | None = None,
    authority_index_path: Path | None = None,
    hiring_radar_path: Path | None = None,
) -> dict[str, object]:
    manifest_path = data_dir / "manifest.json"
    catalog_path = data_dir / "catalog.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(str(manifest.get("generatedAt"))).astimezone(UTC)
    jobs = [
        SimpleNamespace(
            company_id=item.get("companyId"),
            cohort=item.get("cohort"),
            status=item.get("status", "ACTIVE"),
        )
        for item in catalog.get("jobs", [])
        if isinstance(item, dict)
    ]
    community_leads: list[dict[str, object]] = []
    sanitized_community_payload: dict[str, object] | None = None
    leads_path = data_dir / "community-leads.json"
    if leads_path.exists():
        try:
            leads_payload = json.loads(leads_path.read_text(encoding="utf-8"))
            sanitized_community_payload = sanitize_community_catalog(leads_payload)
            community_leads = [item for item in sanitized_community_payload["leads"] if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            community_leads = []
            sanitized_community_payload = None
    # Daily entry discovery writes a small state file containing only status,
    # signal codes and URL evidence.  Feed its public observations into the
    # directory build so a company is shown only while the current-cohort
    # signal is active.  Missing/corrupt state keeps the legacy registry
    # fallback, which is important for local bundles and older workspaces.
    entry_observations: dict[str, dict[str, object]] | None = None
    entry_state_path = entry_state or Path("collector/company-directory-state.json")
    if entry_state_path.exists():
        try:
            payload = json.loads(entry_state_path.read_text(encoding="utf-8"))
            values = payload.get("entries", payload) if isinstance(payload, dict) else {}
            entry_observations = sanitize_entry_observation_map(values)
        except (OSError, ValueError, TypeError):
            entry_observations = None
    authority_path = authority_index_path or companies_path.with_name("internet-authority-top100.json")
    radar_path = hiring_radar_path or companies_path.with_name("hiring-radar-seed.json")
    candidate_configs = load_candidate_company_configs(
        companies_path,
        authority_path if authority_path.exists() else None,
        radar_path if radar_path.exists() else None,
    )
    company_values = [config.model_dump(mode="json", by_alias=True) for config in candidate_configs]
    focus_path = companies_path.with_name("internet-focus.json")
    focus_payload = load_focus_registry(focus_path if focus_path.exists() else None)
    focus_segments = {
        company_id: str(value.get("segment") or "").strip()
        for company_id, value in focus_company_map(focus_payload).items()
        if isinstance(value, dict) and str(value.get("segment") or "").strip()
    }
    source_values = load_sources(sources_path)
    records, summary = build_company_directory(
        company_values,
        source_values,
        jobs,
        now=generated_at,
        community_leads=community_leads,
        entry_observations=entry_observations,
        focus_segments=focus_segments,
    )
    target = output or (data_dir / "companies.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "catalogVersion": manifest.get("catalogVersion", catalog.get("catalogVersion", "")),
                "generatedAt": manifest.get("generatedAt", catalog.get("generatedAt", generated_at.isoformat())),
                "isDemo": bool(manifest.get("isDemo", False)),
                "companies": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if sanitized_community_payload is not None:
        leads_path.write_text(json.dumps(sanitized_community_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["companyDirectory"] = summary
    # A directory-only refresh is still a public data build. Keep source and
    # coverage counters aligned with the checked-in registries instead of
    # leaving the previous live-collector values in place after new TARGET
    # entries are added.
    verified_source_count = sum(1 for source in source_values if source.status == "VERIFIED")
    auto_verified_source_count = sum(1 for source in source_values if source.status == "AUTO_VERIFIED")
    manifest["sourceCount"] = len(source_values)
    manifest["verifiedSourceCount"] = verified_source_count
    manifest["autoVerifiedSourceCount"] = auto_verified_source_count
    manifest["publishableSourceCount"] = verified_source_count + auto_verified_source_count
    # Keep discovery-pool metrics honest in a directory-only refresh as well
    # as in a full live collector run.  Authority candidates have no career
    # URL by default, so they do not appear in ``companies.json`` until a
    # current first-party entry is confirmed.  Keep the caller-supplied path
    # here: CI and fixture builds often place the fixed index outside the
    # registry directory, and silently switching back to the default path
    # would make the manifest disagree with the directory that was just built.
    candidate_count = len(candidate_configs)
    hiring_radar_count = 0
    hiring_radar_entry_url_count = 0
    if radar_path.exists():
        try:
            from .hiring_radar import load_hiring_radar_seed

            radar_payload = load_hiring_radar_seed(radar_path)
            hiring_radar_count = len({str(item.get("companyName")) for item in radar_payload.get("records", []) if isinstance(item, dict) and item.get("companyName")})
            hiring_radar_entry_url_count = sum(1 for item in radar_payload.get("records", []) if isinstance(item, dict) and item.get("entryUrl"))
        except (OSError, ValueError, TypeError):
            hiring_radar_count = 0
            hiring_radar_entry_url_count = 0
    authority_index_id: str | None = None
    authority_index_company_count = 0
    if authority_path.exists():
        try:
            authority_payload = json.loads(authority_path.read_text(encoding="utf-8"))
            if isinstance(authority_payload, dict):
                authority_index_id = str(authority_payload.get("authorityId") or "") or None
                authority_index_company_count = len(authority_payload.get("companies", [])) if isinstance(authority_payload.get("companies"), list) else 0
        except (OSError, ValueError, TypeError):
            authority_index_id = None
            authority_index_company_count = 0
    manifest["candidateCompanyCount"] = candidate_count
    company_discovery = manifest.get("companyDiscovery") if isinstance(manifest.get("companyDiscovery"), dict) else {}
    manifest["companyDiscovery"] = {
        **company_discovery,
        "authorityIndexId": authority_index_id,
        "authorityIndexCompanyCount": authority_index_company_count,
        "candidatePoolCompanyCount": candidate_count,
        "hiringRadarCompanyCount": hiring_radar_count,
        "hiringRadarEntryUrlCount": hiring_radar_entry_url_count,
        "entryLayerSeparateFromJobSources": True,
    }
    coverage = manifest.get("coverage") if isinstance(manifest.get("coverage"), dict) else {}
    verified_company_ids = {source.company_id for source in source_values if source.status in {"VERIFIED", "AUTO_VERIFIED"}}
    blocked_company_ids = {source.company_id for source in source_values if source.status in {"BLOCKED", "QUARANTINED", "REPLACED", "STALE"}}
    pending_review_count = max(candidate_count - len(verified_company_ids) - len(blocked_company_ids), 0)
    accessible_rate = round((verified_source_count + auto_verified_source_count) / len(source_values), 4) if source_values else None
    manifest["coverage"] = {
        **coverage,
        "discoveredCompanyCount": candidate_count,
        "verifiedActiveCompanyCount": len(verified_company_ids),
        "pendingReviewCompanyCount": pending_review_count,
        "blockedCompanyCount": len(blocked_company_ids),
        "accessibleSourceCoverageRate": accessible_rate,
    }
    focus_ids = set(focus_segments)
    focus_source_company_ids = {source.company_id for source in source_values if source.company_id in focus_ids}
    focus_runnable_company_ids = {
        source.company_id
        for source in source_values
        if source.company_id in focus_ids and source_can_run(source)[0]
    }
    focus_jobs = [
        job for job in jobs
        if str(getattr(job, "status", "")) == "ACTIVE"
        and str(getattr(job, "cohort", "")) == "2027"
        and str(getattr(job, "company_id", "")) in focus_ids
    ]
    collection_focus = manifest.get("collectionFocus") if isinstance(manifest.get("collectionFocus"), dict) else {}
    manifest["collectionFocus"] = {
        **collection_focus,
        "focusCompanyCount": len(focus_ids),
        "focusCompaniesWithSources": len(focus_source_company_ids),
        "focusCompaniesWithRunnableSources": len(focus_runnable_company_ids),
        "focusCompaniesWithEligibleJobs": len({str(getattr(job, "company_id", "")) for job in focus_jobs}),
        "focusEligibleJobCount": len(focus_jobs),
        "preserveNonFocusSources": bool(focus_payload.get("preserveNonFocusSources", True)),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the public company-entry directory from the existing catalog.")
    parser.add_argument("--companies", type=Path, default=Path("registry/companies.json"))
    parser.add_argument("--sources", type=Path, default=Path("registry/sources.json"))
    parser.add_argument("--data", type=Path, default=Path("apps/web/public/data"))
    parser.add_argument("--entry-state", type=Path, default=Path("collector/company-directory-state.json"), help="daily entry-signal state; omitted uses registry fallback")
    parser.add_argument("--authority-index", type=Path, default=None)
    parser.add_argument("--hiring-radar", type=Path, default=None)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            refresh_directory(
                companies_path=args.companies,
                sources_path=args.sources,
                data_dir=args.data,
                entry_state=args.entry_state,
                authority_index_path=args.authority_index,
                hiring_radar_path=args.hiring_radar,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
