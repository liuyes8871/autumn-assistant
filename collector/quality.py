from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from statistics import median
from urllib.parse import urlparse

from .normalize import host_matches

from .schema import NormalizedJob, QualityReport


def is_official_url(value: str, allowed_domain: str | None = None) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return not allowed_domain or host_matches(parsed.hostname, allowed_domain)


def source_quality(
    jobs: Iterable[NormalizedJob],
    source_id: str,
    previous_count: int | None = None,
    fetch_ok: bool = True,
    *,
    raw_count: int | None = None,
    count_history: Iterable[int] | None = None,
    fetched_at: datetime | None = None,
    now: datetime | None = None,
    detail_success_rate: float | None = None,
) -> QualityReport:
    items = list(jobs)
    raw_total = max(len(items), int(raw_count or 0))
    unique_total = len({item.id for item in items})
    duplicate_total = max(0, raw_total - unique_total)
    valid_items = [item for item in items if item.title and item.company_name and item.city and is_official_url(str(item.apply_url))]
    completeness = (len(valid_items) / unique_total) if unique_total else 0.0
    unknown_cohort = sum(1 for item in items if item.cohort in {"", "未知"})
    report = QualityReport(
        source_id=source_id,
        raw_count=raw_total,
        unique_count=unique_total,
        duplicate_count=duplicate_total,
        duplicate_ratio=(duplicate_total / raw_total) if raw_total else 0.0,
        field_completeness=completeness,
        unknown_cohort_ratio=(unknown_cohort / unique_total) if unique_total else 0.0,
        detail_success_rate=detail_success_rate,
    )
    if not fetch_ok:
        report.quarantined = False
        report.reasons.append("fetch_failed_preserve_previous_catalog")
        return report
    history_values: list[int] = []
    for value in list(count_history or [])[-3:]:
        if isinstance(value, bool):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number >= 0 and (not isinstance(value, float) or value.is_integer()):
            history_values.append(number)
    if isinstance(previous_count, int) and not isinstance(previous_count, bool) and previous_count >= 0 and previous_count not in history_values:
        history_values.append(previous_count)
    baseline = int(median(history_values)) if history_values else previous_count
    report.baseline_count = baseline
    report.baseline_source = "median_recent_runs" if len(history_values) > 1 else "previous_run" if baseline is not None else None
    if baseline and len(items) < baseline * 0.5:
        report.quarantined = True
        report.reasons.append(f"count_drop_over_50_percent:{baseline}->{len(items)}")
    for job in items:
        if not job.title or not job.company_name or not job.city:
            report.rejected += 1
            report.reasons.append(f"missing_required_field:{job.id}")
            continue
        if not is_official_url(str(job.apply_url)):
            report.rejected += 1
            report.reasons.append(f"invalid_apply_url:{job.id}")
            continue
        report.accepted += 1
    if fetched_at:
        reference = now or datetime.now(UTC)
        report.fetched_at = fetched_at
        report.freshness_days = max(0.0, (reference - fetched_at).total_seconds() / 86400)
    return report


def source_health_metrics(
    jobs: Iterable[NormalizedJob],
    *,
    source_id: str,
    raw_count: int | None = None,
    count_history: Iterable[int] | None = None,
    fetch_ok: bool = True,
    fetched_at: datetime | None = None,
    now: datetime | None = None,
    detail_success_rate: float | None = None,
) -> dict[str, object]:
    """Return a serialisable operational view for dashboards and audits."""

    history = list(count_history or [])
    report = source_quality(
        jobs,
        source_id,
        previous_count=history[-1] if history else None,
        fetch_ok=fetch_ok,
        raw_count=raw_count,
        count_history=history,
        fetched_at=fetched_at,
        now=now,
        detail_success_rate=detail_success_rate,
    )
    return report.model_dump(mode="json")


def deduplicate(jobs: Iterable[NormalizedJob]) -> list[NormalizedJob]:
    seen: dict[str, NormalizedJob] = {}
    for job in jobs:
        existing = seen.get(job.id)
        if existing is None or job.last_verified_at > existing.last_verified_at:
            seen[job.id] = job
    return list(seen.values())
