from __future__ import annotations

"""Synchronise the public source index with the checked-in registry.

The five-hour collector writes this file as part of a live build.  Directory
and candidate-only refreshes do not make network requests, so this small
utility fills in newly registered TARGET rows while preserving the last known
health and job counters for existing sources.  It never promotes a source or
copies response bodies into public data.
"""

import argparse
import json
from pathlib import Path

from collector.registry import load_sources, public_source_record


def refresh(registry_path: Path, public_path: Path, manifest_path: Path) -> dict[str, int]:
    sources = load_sources(registry_path)
    previous: dict[str, dict] = {}
    if public_path.exists():
        payload = json.loads(public_path.read_text(encoding="utf-8"))
        previous = {
            str(item.get("sourceId")): item
            for item in payload.get("sources", [])
            if isinstance(item, dict) and item.get("sourceId")
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    added = 0
    for source in sources:
        old = previous.get(source.source_id)
        if old is not None:
            # Registry metadata is authoritative; operational counters and
            # last health are retained until the next live collection.
            row = dict(old)
            old_status = str(old.get("status") or "")
            row.update(
                {
                    "sourceId": source.source_id,
                    "companyId": source.company_id,
                    "companyName": source.company_name,
                    "sourceUrl": str(source.source_url),
                    "sourceLevel": source.source_level.value,
                    "status": source.status,
                    "adapter": source.adapter,
                    "accessMode": source.access_mode,
                    "verifiedAt": source.verified_at.isoformat() if source.verified_at else None,
                    "robotsReviewedAt": source.robots_reviewed_at.isoformat() if source.robots_reviewed_at else None,
                    "termsReviewedAt": source.terms_reviewed_at.isoformat() if source.terms_reviewed_at else None,
                }
            )
            refreshed = public_source_record(source, health=str(row.get("health") or "not_ready"), job_count=int(row.get("jobCount") or 0), fetched_job_count=int(row.get("fetchedJobCount") or 0))
            if "autoVerification" in refreshed:
                row["autoVerification"] = refreshed["autoVerification"]
            else:
                row.pop("autoVerification", None)
            if old_status != source.status:
                # A registry promotion/demotion is an audit event, not a
                # successful fetch.  Do not leave a stale ``healthy`` label
                # next to a newly changed source status; the next live run
                # must establish fresh evidence before the row is healthy
                # again.
                row["health"] = "not_ready"
                row["notModified"] = False
                row["reason"] = (
                    "awaiting_initial_collection"
                    if source.status in {"VERIFIED", "AUTO_VERIFIED"}
                    else f"status_{str(source.status).lower()}"
                )
            elif source.status not in {"VERIFIED", "AUTO_VERIFIED"}:
                # A TARGET/blocked row must never retain a previously healthy
                # label merely because its status did not change in this
                # registry snapshot.
                row["health"] = "not_ready"
                row["notModified"] = False
                row["reason"] = f"status_{str(source.status).lower()}"
        else:
            row = public_source_record(
                source,
                health="healthy" if source.status in {"VERIFIED", "AUTO_VERIFIED"} else "not_ready",
                job_count=0,
                fetched_job_count=0,
                eligible_job_count=0,
                excluded_job_count=0,
                review_job_count=0,
            )
            added += 1
        rows.append(row)

    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "catalogVersion": manifest.get("catalogVersion", ""),
                "generatedAt": manifest.get("generatedAt", ""),
                "sources": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"registrySources": len(sources), "publicSources": len(rows), "added": added}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh public source metadata without fetching jobs.")
    parser.add_argument("--registry", type=Path, default=Path("registry/sources.json"))
    parser.add_argument("--public", type=Path, default=Path("apps/web/public/data/sources.json"))
    parser.add_argument("--manifest", type=Path, default=Path("apps/web/public/data/manifest.json"))
    args = parser.parse_args()
    print(json.dumps(refresh(args.registry, args.public, args.manifest), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
