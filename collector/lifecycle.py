from __future__ import annotations

from collections.abc import Iterable

from .schema import JobStatus, NormalizedJob


def update_lifecycle(previous: Iterable[NormalizedJob], current: Iterable[NormalizedJob], fetch_ok: bool) -> list[NormalizedJob]:
    """Preserve old jobs on failures; close only after two complete missing snapshots."""

    old = {job.id: job for job in previous}
    latest = {job.id: job for job in current}
    if not fetch_ok:
        return list(old.values())
    output: list[NormalizedJob] = list(latest.values())
    for job_id, previous_job in old.items():
        if job_id in latest:
            continue
        missing = previous_job.first_missing_successes + 1
        if missing < 2:
            output.append(previous_job.model_copy(update={"first_missing_successes": missing}))
        else:
            output.append(previous_job.model_copy(update={"first_missing_successes": missing, "status": JobStatus.CLOSED}))
    return output
