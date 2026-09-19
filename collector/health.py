from __future__ import annotations

"""Source-level health and freshness reporting.

The report consumes the lightweight ``sources.json`` artifact and optional
collector state.  It is safe to publish because it contains counts and
timestamps only, never job descriptions or request/session data.
"""

from datetime import UTC, datetime
import json
import argparse
from pathlib import Path
from statistics import median
from typing import Any


def count_drop_baseline(history: list[int] | tuple[int, ...] | None) -> int | None:
    # The quarantine contract is based on the median of the latest three
    # complete observations, not an old all-time peak.  Accept integral JSON
    # numbers defensively because state files may have been produced by a
    # different serializer.
    values: list[int] = []
    for value in list(history or [])[-3:]:
        if isinstance(value, bool):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number >= 0 and (not isinstance(value, float) or value.is_integer()):
            values.append(number)
    return int(median(values)) if values else None


def source_health_row(
    source: dict[str, Any],
    *,
    history: list[int] | None = None,
    now: datetime | None = None,
    drop_threshold: float = 0.5,
) -> dict[str, Any]:
    current = source.get("fetchedJobCount", source.get("jobCount", 0))
    try:
        current_count = max(0, int(current))
    except (TypeError, ValueError):
        current_count = 0
    baseline = count_drop_baseline(history)
    anomalous_drop = bool(baseline and current_count < baseline * drop_threshold and source.get("health") not in {"blocked", "error", "not_ready"})
    fetched_at = source.get("fetchedAt")
    freshness_days: float | None = source.get("freshnessDays") if isinstance(source.get("freshnessDays"), (int, float)) else None
    if freshness_days is None and fetched_at:
        try:
            timestamp = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            freshness_days = max(0.0, ((now or datetime.now(UTC)) - timestamp).total_seconds() / 86400)
        except (TypeError, ValueError):
            freshness_days = None
    return {
        "sourceId": source.get("sourceId"),
        "companyId": source.get("companyId"),
        "companyName": source.get("companyName"),
        "status": source.get("health", "unknown"),
        "registryStatus": source.get("status"),
        "fetchedJobCount": current_count,
        "eligibleJobCount": source.get("eligibleJobCount", source.get("jobCount", 0)),
        "baselineCount": baseline,
        "anomalousDrop": anomalous_drop,
        "duplicateRatio": source.get("duplicateRatio", 0.0),
        "fieldCompleteness": source.get("fieldCompleteness", 0.0),
        "detailSuccessRate": source.get("detailSuccessRate"),
        "unknownCohortRatio": source.get("unknownCohortRatio", 0.0),
        "freshnessDays": freshness_days,
        "notModified": bool(source.get("notModified")),
        "contentHash": source.get("contentHash"),
        "statusCode": source.get("statusCode"),
        "reason": source.get("reason"),
    }


def build_source_health_report(sources_path: Path, state_path: Path | None = None, *, output: Path | None = None) -> dict[str, Any]:
    payload = json.loads(sources_path.read_text(encoding="utf-8"))
    values = payload.get("sources", payload) if isinstance(payload, dict) else payload
    state: dict[str, Any] = {}
    if state_path and state_path.exists():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            state = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError, TypeError):
            state = {}
    histories = state.get("sourceCountHistory", {}) if isinstance(state.get("sourceCountHistory"), dict) else {}
    rows = [source_health_row(item, history=histories.get(str(item.get("sourceId")), [])) for item in values if isinstance(item, dict)]
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "catalogVersion": payload.get("catalogVersion") if isinstance(payload, dict) else None,
        "summary": {
            "sourceCount": len(rows),
            "healthy": sum(1 for row in rows if row["status"] in {"healthy", "not_modified"}),
            "notModified": sum(1 for row in rows if row["notModified"]),
            "anomalousDrop": sum(1 for row in rows if row["anomalousDrop"]),
            "stale": sum(1 for row in rows if row["status"] in {"stale", "error", "blocked"}),
            "quarantined": sum(1 for row in rows if row["status"] == "quarantined"),
        },
        "sources": rows,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe source health report.")
    parser.add_argument("--sources", type=Path, default=Path("apps/web/public/data/sources.json"))
    parser.add_argument("--state", type=Path, default=Path("collector/state.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/source-health.json"))
    args = parser.parse_args(argv)
    report = build_source_health_report(args.sources, args.state, output=args.output)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
