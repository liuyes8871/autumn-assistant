from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .adapters import fetch_source
from .authority_index import load_authority_index, load_candidate_company_configs
from .audience_policy import AUDIENCE_POLICY_VERSION, AudienceAssessment, AudienceDecision, assess_job
from .company_directory import build_company_directory
from .community import sanitize_community_catalog
from .company_discovery import sanitize_entry_observation_map
from .lifecycle import update_lifecycle
from .normalize import normalize_job, normalize_role_category
from .quality import deduplicate, source_quality
from .http_cache import CacheEntry, dump_cache, load_cache, update_entry
from .inbox import load_inbox
from .registry import (
    focus_company_map,
    load_companies,
    load_company_configs,
    load_focus_registry,
    load_sources,
    parser_for_source,
    public_source_record,
    source_can_run,
)
from .schema import NormalizedJob, RawJob, SourceConfig, model_json


SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_demo_source(job: RawJob) -> SourceConfig:
    hostname = urlparse(str(job.source_url)).hostname or "example.com"
    return SourceConfig(
        source_id=f"{job.company_id}-demo",
        company_id=job.company_id,
        company_name=job.company_name,
        source_url=job.source_url,
        apply_domain=hostname,
        source_level=job.source_level,
        adapter="fixture",
        access_mode="MANUAL",
        status="TARGET",
        note="演示夹具；正式来源需要人工核验后才能发布。",
    )


def make_inbox_source(entry: dict[str, Any]) -> SourceConfig:
    """Create an explicitly local, non-verified source for an inbox row."""

    source_url = str(entry.get("sourceUrl") or entry.get("applyUrl"))
    hostname = urlparse(str(entry.get("applyUrl") or source_url)).hostname or "local.invalid"
    company_key = str(entry.get("companyName") or "unknown").strip().casefold()
    company_id = "local-" + hashlib.sha256(company_key.encode("utf-8")).hexdigest()[:12]
    return SourceConfig(
        source_id=f"{company_id}-inbox",
        company_id=company_id,
        company_name=str(entry.get("companyName") or "本地导入企业"),
        source_url=source_url,
        apply_domain=hostname,
        source_level="B",
        adapter="manual",
        access_mode="MANUAL",
        status="TARGET",
        evidence_urls=[source_url],
        note="用户主动导入的公开岗位链接；不会代表官方来源已核验。",
    )


def raw_job_from_inbox(entry: dict[str, Any], source: SourceConfig) -> RawJob:
    return RawJob.model_validate({
        "source_id": source.source_id,
        "source_job_id": str(entry.get("id") or entry.get("applyUrl") or ""),
        "company_id": source.company_id,
        "company_name": source.company_name,
        "title": entry.get("title") or "",
        "city": entry.get("city") or "未知",
        "description": entry.get("description") or "",
        "requirements": entry.get("requirements") or [],
        "apply_url": entry.get("applyUrl"),
        "source_url": entry.get("sourceUrl") or entry.get("applyUrl"),
        "source_name": "用户主动导入（本地）",
        "source_level": source.source_level,
        "is_campus": entry.get("isCampus") if isinstance(entry.get("isCampus"), bool) else None,
        "cohort": entry.get("cohort") or "未知",
        "batch": entry.get("batch") or "未知",
        "role_category": entry.get("roleCategory") or "其他",
    })


def summary(job: dict[str, Any]) -> dict[str, Any]:
    detail_only = {
        "description", "requirements", "sourceEvidence", "sourceJobId", "isCampus",
        "campaignName", "campaignOpenDate", "campaignDeadline", "campaignOfficialUrl",
        "firstMissingSuccesses", "audienceDecision", "audienceReasonCodes",
    }
    return {key: value for key, value in job.items() if key not in detail_only and value not in (None, [], "")}


def camel_key(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Translate collector snake_case to the web catalog's camelCase contract."""

    def camelize(value: Any) -> Any:
        if isinstance(value, dict):
            return {camel_key(str(key)): camelize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [camelize(item) for item in value]
        return value

    return camelize(job)


def _read_previous_state(state_path: Path | None) -> tuple[list[NormalizedJob], dict[str, int]]:
    if not state_path or not state_path.exists():
        return [], {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        values = payload.get("jobs", payload) if isinstance(payload, dict) else payload
        observed = payload.get("sourceObservedCounts", {}) if isinstance(payload, dict) else {}
        observed_counts = {
            str(source_id): int(count)
            for source_id, count in observed.items()
            if isinstance(source_id, str) and isinstance(count, (int, float)) and count >= 0
        }
        jobs = [NormalizedJob.model_validate(value) for value in values if isinstance(value, dict)]
        return jobs, observed_counts
    except (OSError, ValueError, TypeError):
        # A corrupt operational state must never prevent a fresh safe catalog;
        # the report makes the absence visible to the workflow operator.
        return [], {}


def _read_previous(state_path: Path | None) -> list[NormalizedJob]:
    """Backward-compatible helper retained for callers and small utilities."""

    return _read_previous_state(state_path)[0]


def _read_runtime_metadata(state_path: Path | None) -> tuple[dict[str, CacheEntry], dict[str, list[int]]]:
    """Read mutable request validators and recent count history safely.

    Older state files contain only ``jobs`` and ``sourceObservedCounts``.  The
    collector treats missing or malformed metadata as an empty cache so a
    migration can never block a fresh run.
    """

    if not state_path or not state_path.exists():
        return {}, {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}, {}
    validators = load_cache(payload)
    raw_history = payload.get("sourceCountHistory", {}) if isinstance(payload, dict) else {}
    history: dict[str, list[int]] = {}
    if isinstance(raw_history, dict):
        for source_id, values in raw_history.items():
            if not isinstance(values, list):
                continue
            clean: list[int] = []
            for value in values[-6:]:
                if isinstance(value, bool):
                    continue
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if number >= 0:
                    clean.append(number)
            if clean:
                history[str(source_id)] = clean
    return validators, history


def _read_entry_observations(entry_state_path: Path | None) -> dict[str, dict[str, Any]] | None:
    """Read the daily directory-signal state without retaining page text.

    ``None`` deliberately means "no state has ever been produced" and keeps
    local/demo builds compatible with the original registry-only behaviour.
    An existing but empty state is authoritative and therefore yields an
    empty mapping, preventing stale career URLs from being published as
    current entries.
    """

    if not entry_state_path or not entry_state_path.exists():
        return None
    try:
        payload = json.loads(entry_state_path.read_text(encoding="utf-8"))
        values = payload.get("entries", payload) if isinstance(payload, dict) else {}
        return sanitize_entry_observation_map(values)
    except (OSError, ValueError, TypeError):
        return None


def _hiring_radar_company_count(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    try:
        from .hiring_radar import load_hiring_radar_seed

        payload = load_hiring_radar_seed(path)
        return len({str(item.get("companyName")) for item in payload.get("records", []) if isinstance(item, dict) and item.get("companyName")})
    except (OSError, ValueError, TypeError):
        return 0


def _hiring_radar_entry_url_count(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    try:
        from .hiring_radar import load_hiring_radar_seed

        payload = load_hiring_radar_seed(path)
        return sum(1 for item in payload.get("records", []) if isinstance(item, dict) and item.get("entryUrl"))
    except (OSError, ValueError, TypeError):
        return 0


def _authority_index_metadata(path: Path | None) -> tuple[str | None, int]:
    """Return the id and row count of the authority index used for a build.

    The authority file is validated by ``load_candidate_company_configs`` in
    live builds.  This helper still handles an absent or malformed file
    defensively so isolated fixture builds can produce a truthful manifest
    rather than crashing while trying to render optional discovery metadata.
    """

    if path is None or not path.exists():
        return None, 0
    try:
        payload = load_authority_index(path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, 0
    return str(payload.get("authorityId") or "") or None, len(payload.get("companies", []))


def _business_date(now: datetime) -> str:
    return now.astimezone(SHANGHAI).date().isoformat()


def _parse_fetched_at(value: Any) -> datetime | None:
    """Parse adapter timestamps before calculating source freshness."""

    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _campaigns(jobs: list[NormalizedJob], now: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not job.campaign_id or not job.campaign_name:
            continue
        campaign_id = job.campaign_id
        record = grouped.setdefault(campaign_id, {
            "id": campaign_id,
            "companyId": job.company_id,
            "companyName": job.company_name,
            "name": job.campaign_name,
            "cohort": job.cohort,
            "batch": job.batch,
            "openDate": job.campaign_open_date.isoformat() if job.campaign_open_date else None,
            "deadline": job.campaign_deadline.isoformat() if job.campaign_deadline else (job.deadline.isoformat() if job.deadline else None),
            "officialUrl": str(job.campaign_official_url or job.source_url),
            "sourceId": job.source_id,
            "verifiedAt": job.last_verified_at.isoformat(),
            "status": "OPEN",
            "jobIds": [],
        })
        if job.id not in record["jobIds"]:
            record["jobIds"].append(job.id)
        if job.last_verified_at.isoformat() > record["verifiedAt"]:
            record["verifiedAt"] = job.last_verified_at.isoformat()
        if record["deadline"] and record["deadline"] < now.astimezone(SHANGHAI).date().isoformat():
            record["status"] = "CLOSED"
    return sorted(grouped.values(), key=lambda item: (item.get("openDate") or "", item["companyName"], item["name"]), reverse=True)


def _source_result(
    source: SourceConfig,
    *,
    health: str,
    reason: str | None = None,
    job_count: int = 0,
    fetched_job_count: int | None = None,
    fetch_result: Any | None = None,
) -> dict[str, Any]:
    result = public_source_record(
        source,
        health=health,
        reason=reason,
        job_count=job_count,
        fetched_job_count=fetched_job_count if fetched_job_count is not None else job_count,
    )
    if fetch_result is not None:
        fetched_at = getattr(fetch_result, "fetched_at", None)
        result.update({
            "statusCode": getattr(fetch_result, "status_code", None),
            "fetchedAt": fetched_at.isoformat() if fetched_at else result.get("fetchedAt"),
            "notModified": bool(getattr(fetch_result, "not_modified", False)),
        })
        for key, value in (
            ("contentHash", getattr(fetch_result, "content_hash", None)),
            ("rawCount", getattr(fetch_result, "raw_count", None)),
            ("detailSuccessRate", getattr(fetch_result, "detail_success_rate", None)),
        ):
            if value is not None:
                result[key] = value
        response_meta = getattr(fetch_result, "response_headers", {}) or {}
        if isinstance(response_meta, dict):
            result["cacheValidators"] = {
                key: response_meta.get(key)
                for key in ("etag", "last-modified")
                if response_meta.get(key)
            }
    return result


def _fetch_source_group(
    sources: list[SourceConfig],
    cache_entries: dict[str, CacheEntry] | None = None,
) -> tuple[list[RawJob], list[dict[str, Any]], dict[str, bool]]:
    """Fetch one traffic domain serially so parallelism never amplifies host traffic."""

    jobs: list[RawJob] = []
    source_records: list[dict[str, Any]] = []
    fetch_ok: dict[str, bool] = {}
    for source in sources:
        ready, reason = source_can_run(source)
        if not ready:
            fetch_ok[source.source_id] = False
            source_records.append(_source_result(source, health="not_ready", reason=reason))
            continue
        try:
            cached = (cache_entries or {}).get(source.source_id)
            result = fetch_source(source, parser_for_source(source), cache_entry=cached) if cached else fetch_source(source, parser_for_source(source))
        except Exception as exc:  # adapters are isolated; no traceback goes to public data
            fetch_ok[source.source_id] = False
            source_records.append(_source_result(source, health="error", reason=f"adapter_error:{exc.__class__.__name__}"))
            continue
        if result.blocked:
            fetch_ok[source.source_id] = False
            source_records.append(_source_result(source, health="blocked", reason=result.error or "access_control", fetch_result=result))
            continue
        if result.error:
            fetch_ok[source.source_id] = False
            source_records.append(_source_result(source, health="error", reason=result.error, fetch_result=result))
            continue
        fetch_ok[source.source_id] = result.complete
        jobs.extend(result.jobs)
        health = "not_modified" if result.not_modified else "healthy"
        source_records.append(_source_result(source, health=health, job_count=len(result.jobs), fetched_job_count=result.raw_count or len(result.jobs), fetch_result=result))
    return jobs, source_records, fetch_ok


def _traffic_domain(host: str) -> str:
    """Collapse tenant subdomains to the registrable domain used for pacing.

    Several reviewed Feishu tenants use different subdomains but share the
    ``jobs.feishu.cn`` service. Treating each tenant as an independent worker
    could create a burst against one vendor. This small dependency-free rule
    covers the public suffixes used by the registry and keeps other hosts at
    their last two labels.
    """

    labels = [part for part in host.lower().split(".") if part]
    if len(labels) < 2:
        return host.lower()
    if len(labels) >= 3 and ".".join(labels[-2:]) in {"com.cn", "net.cn", "org.cn", "co.uk"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _fetch_live_sources(
    sources: list[SourceConfig],
    max_domain_workers: int = 4,
    cache_entries: dict[str, CacheEntry] | None = None,
) -> tuple[list[RawJob], list[dict[str, Any]], dict[str, bool]]:
    """Fetch at most four traffic domains concurrently and preserve stable output."""

    groups: dict[str, list[SourceConfig]] = defaultdict(list)
    for source in sources:
        host = source.ats_host or (urlparse(str(source.endpoint or source.source_url)).hostname or source.source_id)
        groups[_traffic_domain(host)].append(source)
    parts: list[tuple[str, tuple[list[RawJob], list[dict[str, Any]], dict[str, bool]]]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_domain_workers, 4))) as executor:
        futures = {executor.submit(_fetch_source_group, group, cache_entries): host for host, group in groups.items()}
        for future in as_completed(futures):
            parts.append((futures[future], future.result()))
    jobs: list[RawJob] = []
    records: list[dict[str, Any]] = []
    fetch_ok: dict[str, bool] = {}
    for _host, (group_jobs, group_records, group_ok) in sorted(parts, key=lambda item: item[0]):
        jobs.extend(group_jobs)
        records.extend(group_records)
        fetch_ok.update(group_ok)
    records.sort(key=lambda item: item["sourceId"])
    return jobs, records, fetch_ok


def _enrich_company_facts(raw: RawJob, companies: dict[str, dict[str, Any]]) -> RawJob:
    company = companies.get(raw.company_id)
    if not company:
        return raw
    updates: dict[str, Any] = {}
    for field, key in (("company_industry", "industry"), ("company_type", "type"), ("company_scale", "scale")):
        if getattr(raw, field) == "未知" and company.get(key):
            updates[field] = company[key]
    return raw.model_copy(update=updates) if updates else raw


def build(
    input_path: Path | None,
    output_dir: Path,
    *,
    sources_path: Path | None = None,
    state_path: Path | None = None,
    min_verified_sources: int = 0,
    max_domain_workers: int = 4,
    now: datetime | None = None,
    focus_path: Path | None = None,
    entry_state_path: Path | None = None,
    inbox_path: Path | None = None,
) -> dict[str, Any]:
    """Build a static catalog from a fixture or the reviewed-source registry.

    ``input_path`` keeps local/demo builds deterministic. Live mode is selected
    by omitting it and only runs sources that passed the registry gate. It is
    intentionally possible for a live run to produce zero jobs; the release
    gate then fails instead of replacing a known-good catalog with guesses.
    """

    now = now or datetime.now(UTC)
    previous, previous_observed_counts = _read_previous_state(state_path)
    source_validators, source_count_history = _read_runtime_metadata(state_path)
    previous_by_source: dict[str, list[NormalizedJob]] = defaultdict(list)
    previous_filter_counts: defaultdict[str, int] = defaultdict(int)
    previous_filter_samples: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in previous:
        source_id = job.source_id or "unknown"
        assessment = assess_job(job)
        if assessment.publishable:
            previous_by_source[source_id].append(job.model_copy(update={
                # Old state files may contain source-specific aliases such as
                # “销售、服务与支持”. Canonicalise them even when the source
                # is temporarily unavailable so the public filter taxonomy
                # remains stable across preserved snapshots.
                "role_category": normalize_role_category(job.role_category),
                "audience_decision": assessment.decision.value,
                "audience_reason_codes": list(assessment.reason_codes),
            }))
        else:
            previous_filter_counts[assessment.decision.value] += 1
            if len(previous_filter_samples[assessment.decision.value]) < 20:
                previous_filter_samples[assessment.decision.value].append(
                    {
                        "jobId": job.id,
                        "sourceId": source_id,
                        "companyName": job.company_name,
                        "title": job.title,
                        "reasonCodes": list(assessment.reason_codes),
                    }
                )

    raw_items: list[RawJob] = []
    reports: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    fetch_ok: dict[str, bool] = {}
    source_configs: dict[str, SourceConfig] = {}

    if input_path:
        values = json.loads(input_path.read_text(encoding="utf-8"))
        for item in values:
            try:
                raw = RawJob.model_validate(item)
                source = make_demo_source(raw)
                source_configs[source.source_id] = source
                raw_items.append(raw)
                fetch_ok[source.source_id] = True
            except (TypeError, ValueError) as exc:
                reports.append({"source_id": "fixture", "accepted": 0, "rejected": 1, "reasons": [f"invalid_raw:{exc.__class__.__name__}"]})
        source_records = [_source_result(source, health="healthy", job_count=0) for source in source_configs.values()]
    else:
        if not sources_path:
            raise ValueError("live build requires --sources")
        sources = load_sources(sources_path)
        source_configs = {source.source_id: source for source in sources}
        if source_validators:
            raw_items, source_records, fetch_ok = _fetch_live_sources(
                sources,
                max_domain_workers=max_domain_workers,
                cache_entries=source_validators,
            )
        else:
            # Preserve the compact call shape used by fixture harnesses and
            # older scheduled workers that monkeypatch the live fetcher.
            raw_items, source_records, fetch_ok = _fetch_live_sources(sources, max_domain_workers=max_domain_workers)

    # User-selected local jobs are an explicit supplement for portals without
    # a public feed.  They enter the same normalisation/audience pipeline, but
    # their source remains TARGET and is never counted as a VERIFIED source.
    if inbox_path and inbox_path.exists():
        try:
            for entry in load_inbox(inbox_path):
                try:
                    local_source = make_inbox_source(entry)
                    source_configs[local_source.source_id] = local_source
                    raw_items.append(raw_job_from_inbox(entry, local_source))
                    fetch_ok[local_source.source_id] = True
                except (TypeError, ValueError):
                    continue
        except (OSError, ValueError, TypeError):
            pass

    registry_path = Path(__file__).resolve().parent.parent / "registry" / "companies.json"
    company_values = load_companies(registry_path) if registry_path.exists() else []
    company_configs = load_company_configs(registry_path) if registry_path.exists() else []
    authority_index_path = registry_path.with_name("internet-authority-top100.json")
    hiring_radar_path = registry_path.with_name("hiring-radar-seed.json")
    candidate_company_configs = (
        load_candidate_company_configs(
            registry_path,
            authority_index_path if authority_index_path.exists() else None,
            hiring_radar_path if hiring_radar_path.exists() else None,
        )
        if registry_path.exists() else []
    )
    company_by_id = {item.get("id"): item for item in company_values if isinstance(item, dict) and item.get("id")}
    focus_registry_path = focus_path or registry_path.with_name("internet-focus.json")
    focus_payload = load_focus_registry(focus_registry_path)
    focused_companies = focus_company_map(focus_payload)
    raw_items = [_enrich_company_facts(raw, company_by_id) for raw in raw_items]

    # Keep source health based on the complete normalized response. The
    # audience gate is deliberately applied afterwards so removing technical
    # roles cannot look like a broken source or a >50% count drop.
    normalized_by_source: dict[str, list[NormalizedJob]] = defaultdict(list)
    current_by_source: dict[str, list[NormalizedJob]] = defaultdict(list)
    audience_counts: defaultdict[str, int] = defaultdict(int)
    audience_by_source: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    audience_reason_counts: defaultdict[str, int] = defaultdict(int)
    audience_reason_by_source: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    audience_samples: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    audience_review_jobs: list[dict[str, Any]] = []
    for raw in raw_items:
        source = source_configs.get(raw.source_id or "") or make_demo_source(raw)
        try:
            normalized = normalize_job(raw, source, now)
            normalized_by_source[source.source_id].append(normalized)
            assessment = assess_job(normalized)
            normalized = normalized.model_copy(update={
                "audience_decision": assessment.decision.value,
                "audience_reason_codes": list(assessment.reason_codes),
            })
            audience_counts[assessment.decision.value] += 1
            audience_by_source[source.source_id][assessment.decision.value] += 1
            for reason_code in assessment.reason_codes:
                audience_reason_counts[reason_code] += 1
                audience_reason_by_source[source.source_id][reason_code] += 1
            if not assessment.publishable:
                if assessment.decision == AudienceDecision.NEEDS_REVIEW:
                    # Keep the complete review queue as lightweight metadata;
                    # unlike the bounded exclusion samples, this list is what
                    # an operator uses to decide which ambiguous postings to
                    # inspect next. It intentionally contains no JD text.
                    audience_review_jobs.append(
                        {
                            "jobId": normalized.id,
                            "sourceId": source.source_id,
                            "companyName": normalized.company_name,
                            "title": normalized.title,
                            "reasonCodes": list(assessment.reason_codes),
                        }
                    )
                if len(audience_samples[assessment.decision.value]) < 40:
                    audience_samples[assessment.decision.value].append(
                        {
                            "jobId": normalized.id,
                            "sourceId": source.source_id,
                            "companyName": normalized.company_name,
                            "title": normalized.title,
                            "reasonCodes": list(assessment.reason_codes),
                        }
                    )
                continue
            current_by_source[source.source_id].append(normalized)
        except ValueError as exc:
            reports.append({"source_id": source.source_id, "accepted": 0, "rejected": 1, "reasons": [str(exc)]})

    merged: list[NormalizedJob] = []
    all_source_ids = set(source_configs) | set(previous_by_source)
    next_observed_counts: dict[str, int] = dict(previous_observed_counts)
    next_count_history: dict[str, list[int]] = {key: list(values) for key, values in source_count_history.items()}
    for source_id in sorted(all_source_ids):
        current = deduplicate(current_by_source.get(source_id, []))
        observed_current = deduplicate(normalized_by_source.get(source_id, []))
        old = previous_by_source.get(source_id, [])
        complete = fetch_ok.get(source_id, False)
        source_record = next((item for item in source_records if item.get("sourceId") == source_id), None)
        not_modified = bool(source_record and source_record.get("notModified"))
        if not_modified:
            # A validator hit means the server explicitly confirmed that the
            # previous representation is still current.  Reuse the old
            # normalized rows rather than treating an empty 304 body as a
            # missing snapshot.
            if old:
                current = list(old)
                observed_current = list(old)
            else:
                complete = False
                if source_record is not None:
                    # A 304 without a local snapshot is not a usable
                    # publication: the server confirmed its validator, but
                    # this worker has nothing to reuse.  Keep the source
                    # visible as stale instead of reporting a misleading
                    # healthy empty feed.
                    source_record["health"] = "stale"
                    source_record["reason"] = "not_modified_without_previous_snapshot"
        # V1 state did not have an observed-count baseline. Skipping the drop
        # comparison on that first migrated run avoids quarantining every
        # source merely because the new audience policy removed technical jobs.
        previous_observed = previous_observed_counts.get(source_id)
        fetch_meta = source_record or {}
        report = source_quality(
            observed_current,
            source_id,
            previous_count=previous_observed,
            fetch_ok=complete,
            raw_count=(int(fetch_meta.get("rawCount")) if isinstance(fetch_meta.get("rawCount"), (int, float)) else len(observed_current)),
            count_history=source_count_history.get(source_id),
            # Preserve the adapter's actual response time.  Using the build
            # time here made every source appear brand new and reduced the
            # freshness metric to zero even when a cached/previous snapshot
            # was being retained.
            fetched_at=_parse_fetched_at(fetch_meta.get("fetchedAt")),
            now=now,
            detail_success_rate=(float(fetch_meta.get("detailSuccessRate")) if isinstance(fetch_meta.get("detailSuccessRate"), (int, float)) else None),
        )
        report.fetch_complete = complete
        reports.append(model_json(report))
        source_stats = audience_by_source.get(source_id, {})
        published_current = current if complete and not report.quarantined else (old if old else current)
        eligible_count = len(published_current)
        observed_count_for_record = len(observed_current) if complete else previous_observed_counts.get(source_id, 0)
        if source_record is not None:
            source_record["jobCount"] = eligible_count
            source_record["fetchedJobCount"] = observed_count_for_record
            source_record["eligibleJobCount"] = len(current) if complete else len(old)
            source_record["excludedJobCount"] = int(source_stats.get(AudienceDecision.OUT_OF_SCOPE.value, 0))
            source_record["reviewJobCount"] = int(source_stats.get(AudienceDecision.NEEDS_REVIEW.value, 0))
            source_record["rawCount"] = report.raw_count
            source_record["uniqueCount"] = report.unique_count
            source_record["duplicateCount"] = report.duplicate_count
            source_record["duplicateRatio"] = report.duplicate_ratio
            source_record["fieldCompleteness"] = report.field_completeness
            source_record["unknownCohortRatio"] = report.unknown_cohort_ratio
            source_record["freshnessDays"] = report.freshness_days
            if report.quarantined:
                source_record["health"] = "quarantined"
                source_record["reason"] = "count_drop_over_50_percent"
            elif not complete and source_record.get("health") == "healthy":
                source_record["health"] = "stale"
        if complete:
            next_observed_counts[source_id] = len(observed_current)
            if not not_modified:
                history = next_count_history.setdefault(source_id, [])
                history.append(len(observed_current))
                next_count_history[source_id] = history[-6:]
        # A partial/blocked/sudden-drop response is never allowed to delete the
        # previous public snapshot. The next successful run can recover it.
        if not complete or report.quarantined:
            merged.extend(old if old else current)
        else:
            latest = {job.id: job for job in current}
            for job_id, old_job in {job.id: job for job in old}.items():
                fresh = latest.get(job_id)
                if not fresh:
                    continue
                latest[job_id] = fresh.model_copy(update={
                    "first_seen_at": old_job.first_seen_at,
                    "changed_at": now if fresh.content_hash != old_job.content_hash else old_job.changed_at,
                    "first_missing_successes": 0,
                })
            # Feed the full previous/current lists through the tested lifecycle
            # helper so two consecutive complete misses are required to close.
            merged.extend(update_lifecycle(old, list(latest.values()), fetch_ok=True))

    audience_report = {
        "reportType": "audience_filter",
        "policyVersion": AUDIENCE_POLICY_VERSION,
        "targetAudience": "文科、社科、商科及不限专业的通用校招岗位",
        "current": {
            "normalized": sum(len(items) for items in normalized_by_source.values()),
            "targetGeneralist": audience_counts[AudienceDecision.TARGET_GENERALIST.value],
            "outOfScope": audience_counts[AudienceDecision.OUT_OF_SCOPE.value],
            "needsReview": audience_counts[AudienceDecision.NEEDS_REVIEW.value],
        },
        "reasonCounts": dict(sorted(audience_reason_counts.items())),
        "bySource": {
            source_id: {
                "normalized": sum(audience_by_source[source_id].values()),
                "targetGeneralist": int(audience_by_source[source_id].get(AudienceDecision.TARGET_GENERALIST.value, 0)),
                "outOfScope": int(audience_by_source[source_id].get(AudienceDecision.OUT_OF_SCOPE.value, 0)),
                "needsReview": int(audience_by_source[source_id].get(AudienceDecision.NEEDS_REVIEW.value, 0)),
                "reasonCounts": dict(sorted(audience_reason_by_source[source_id].items())),
            }
            for source_id in sorted(set(source_configs) | set(audience_by_source))
        },
        "removedFromPreviousState": dict(previous_filter_counts),
        "previousSamples": dict(previous_filter_samples),
        "samples": dict(audience_samples),
        "reviewJobs": audience_review_jobs,
    }
    reports.append(audience_report)

    # Keep closed postings for 90 days so local snapshots and audit trails can
    # still explain what happened, then age them out of the public directory.
    cutoff = now - timedelta(days=90)
    accepted = [job for job in deduplicate(merged) if job.status.value != "CLOSED" or job.last_verified_at >= cutoff]
    generated_at = now.astimezone(UTC)
    catalog_version = generated_at.strftime("%Y.%m.%d.%H%M")
    # Keep the standalone audit artifact traceable to the exact catalog run;
    # the same dictionary is already embedded in manifest.reports.
    audience_report["generatedAt"] = generated_at.isoformat()
    audience_report["catalogVersion"] = catalog_version
    business_date = _business_date(now)
    # Enforce the live publication threshold before touching any catalog,
    # shard, campaign, or lifecycle-state files. A run below the reviewed
    # source bar must leave the last known-good snapshot byte-for-byte intact.
    # A validator hit is still a successful observation: the source has
    # explicitly confirmed that the previously published representation is
    # current.  Count ``not_modified`` alongside ``healthy`` so a normal 304
    # response cannot make the scheduled publication fail its verified-source
    # threshold on the next run.
    verified_health_values = {"healthy", "not_modified"}
    publishable_statuses = {"VERIFIED", "AUTO_VERIFIED"}
    live_verified = sum(
        1
        for item in source_records
        if item.get("status") in publishable_statuses and item.get("health") in verified_health_values
    )
    if min_verified_sources and live_verified < min_verified_sources:
        raise RuntimeError(f"verified_source_gate_failed:{live_verified}<{min_verified_sources}")
    output_dir.mkdir(parents=True, exist_ok=True)
    shards: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in accepted:
        payload = model_json(job)
        shard = f"{int(job.id.encode().hex()[:4], 16) % 64:02d}"
        payload["detail_shard"] = shard
        shards[shard].append(payload)
    (output_dir / "jobs").mkdir(parents=True, exist_ok=True)
    current_shard_names = {f"{shard}.json" for shard in shards}
    for stale_file in (output_dir / "jobs").glob("*.json"):
        if stale_file.name not in current_shard_names:
            stale_file.unlink()
    for shard, jobs in shards.items():
        (output_dir / "jobs" / f"{shard}.json").write_text(json.dumps({"schemaVersion": 1, "catalogVersion": catalog_version, "jobs": [public_job(job) for job in jobs]}, ensure_ascii=False, indent=2), encoding="utf-8")

    catalog_jobs = []
    for job in accepted:
        payload = model_json(job)
        payload["detail_shard"] = f"{int(job.id.encode().hex()[:4], 16) % 64:02d}"
        catalog_jobs.append(summary(public_job(payload)))
    catalog_jobs.sort(key=lambda item: (item.get("publishDate") or "", item["companyName"], item["title"]), reverse=True)
    (output_dir / "catalog.json").write_text(json.dumps({"schemaVersion": 1, "catalogVersion": catalog_version, "generatedAt": generated_at.isoformat(), "jobs": catalog_jobs}, ensure_ascii=False, indent=2), encoding="utf-8")

    campaign_values = _campaigns(accepted, now)
    (output_dir / "campaigns.json").write_text(json.dumps({"schemaVersion": 1, "catalogVersion": catalog_version, "generatedAt": generated_at.isoformat(), "campaigns": campaign_values}, ensure_ascii=False, indent=2), encoding="utf-8")

    # Company entries are a separate publication surface from runnable job
    # sources.  A registered public career URL can therefore be shown as an
    # explicitly labelled lead while only publishable VERIFIED/AUTO_VERIFIED
    # sources contribute jobs.
    community_leads: list[dict[str, Any]] = []
    sanitized_community_payload: dict[str, Any] | None = None
    community_leads_path = output_dir / "community-leads.json"
    if community_leads_path.exists():
        try:
            community_payload = json.loads(community_leads_path.read_text(encoding="utf-8"))
            sanitized_community_payload = sanitize_community_catalog(community_payload)
            community_leads = sanitized_community_payload["leads"]
        except (OSError, ValueError, TypeError):
            community_leads = []
            sanitized_community_payload = None
    entry_observations = _read_entry_observations(entry_state_path or (Path("collector/company-directory-state.json") if input_path is None else None))
    directory_company_values = [config.model_dump(mode="json", by_alias=True) for config in candidate_company_configs] if input_path is None else company_values
    directory_cohort = "2027"
    directory_records, directory_summary = build_company_directory(
        directory_company_values,
        source_configs.values(),
        accepted,
        now=now,
        cohort=directory_cohort,
        community_leads=community_leads,
        entry_observations=entry_observations,
        focus_segments={
            company_id: str(value.get("segment") or "").strip()
            for company_id, value in focused_companies.items()
            if isinstance(value, dict) and str(value.get("segment") or "").strip()
        },
    )

    healthy = sum(1 for item in source_records if item.get("health") == "healthy")
    quarantined = sum(1 for item in source_records if item.get("health") == "quarantined")
    stale = sum(1 for item in source_records if item.get("status") == "STALE" or item.get("health") == "stale")
    verified = sum(
        1
        for item in source_records
        if item.get("status") == "VERIFIED" and item.get("health") in verified_health_values
    )
    auto_verified = sum(
        1
        for item in source_records
        if item.get("status") == "AUTO_VERIFIED" and item.get("health") in verified_health_values
    )
    # Candidate-pool metrics are deliberately kept separate from source health:
    # a company in the registry is not an active source until its official
    # channel has passed the source gate and produced a public snapshot.
    candidate_company_count = 0 if input_path is not None else len(candidate_company_configs)
    confirmed_500_plus_company_count = 0 if input_path is not None else sum(
        1
        for company in candidate_company_configs
        if (company.employee_count is not None and company.employee_count >= 500)
        or company.scale in {"500–999", "1000–9999", "10000+"}
    )
    # Company-directory statistics are scoped to the configured current
    # cohort. Older/unknown snapshots remain searchable in the catalog, but
    # must not inflate the number of companies currently recruiting.
    companies_with_eligible_jobs = len({
        job.company_id
        for job in accepted
        if job.status.value == "ACTIVE" and job.cohort == directory_cohort
    })
    registered_company_ids = {company.id for company in candidate_company_configs}
    verified_company_ids = {
        str(item.get("companyId"))
        for item in source_records
        if item.get("status") in publishable_statuses and item.get("health") in verified_health_values
    }
    blocked_company_ids = {str(item.get("companyId")) for item in source_records if item.get("status") in {"BLOCKED", "QUARANTINED", "REPLACED", "STALE"} or item.get("health") in {"blocked", "quarantined"}}
    pending_review_company_count = len(registered_company_ids - verified_company_ids - blocked_company_ids) if input_path is None else 0
    registered_source_count = len(source_records)
    accessible_source_coverage_rate = round((verified + auto_verified) / registered_source_count, 4) if registered_source_count else None
    focus_ids = set(focused_companies)
    focus_company_count = len(focus_ids) if input_path is None else 0
    focus_source_company_ids = {
        source.company_id
        for source in source_configs.values()
        if input_path is None and source.company_id in focus_ids
    }
    focus_runnable_company_ids = {
        source.company_id
        for source in source_configs.values()
        if input_path is None and source.company_id in focus_ids and source_can_run(source)[0]
    }
    focus_active_jobs = [
        job
        for job in accepted
        if input_path is None and job.status.value == "ACTIVE" and job.company_id in focus_ids
    ]
    focus_segment_job_counts: dict[str, int] = defaultdict(int)
    for job in focus_active_jobs:
        segment = str(focused_companies.get(job.company_id, {}).get("segment") or "未分类")
        focus_segment_job_counts[segment] += 1
    for record in source_records:
        focus = focused_companies.get(str(record.get("companyId")))
        if focus:
            record["focusPriority"] = focus.get("priority")
            record["focusSegment"] = focus.get("segment")
    auto_verification_reports = [
        {
            "sourceId": record.get("sourceId"),
            **(record.get("autoVerification") if isinstance(record.get("autoVerification"), dict) else {}),
        }
        for record in source_records
        if record.get("status") == "AUTO_VERIFIED"
    ]
    authority_index_id, authority_index_company_count = _authority_index_metadata(authority_index_path)
    manifest = {
        "schemaVersion": 1,
        "locationSchemaVersion": 1,
        "catalogVersion": catalog_version,
        "generatedAt": generated_at.isoformat(),
        "businessDate": business_date,
        "totalJobs": len(accepted),
        "activeJobs": sum(1 for job in accepted if job.status.value == "ACTIVE"),
        "sourceCount": len(source_records),
        "verifiedSourceCount": verified,
        "autoVerifiedSourceCount": auto_verified,
        "publishableSourceCount": verified + auto_verified,
        "autoVerificationReports": auto_verification_reports,
        "isDemo": input_path is not None,
        "candidateCompanyCount": candidate_company_count,
        "companiesWithEligibleJobs": companies_with_eligible_jobs,
        "confirmed500PlusCompanyCount": confirmed_500_plus_company_count,
        "collectionCadenceHours": 5,
        "collectionFocus": {
            "id": focus_payload.get("focusId"),
            "mode": focus_payload.get("mode", "PRIORITIZE"),
            "target": focus_payload.get("target"),
            "focusCompanyCount": focus_company_count,
            "focusCompaniesWithSources": len(focus_source_company_ids),
            "focusCompaniesWithRunnableSources": len(focus_runnable_company_ids),
            "focusCompaniesWithEligibleJobs": len({job.company_id for job in focus_active_jobs}),
            "focusEligibleJobCount": len(focus_active_jobs),
            "focusEligibleJobsBySegment": dict(sorted(focus_segment_job_counts.items())),
            "preserveNonFocusSources": bool(focus_payload.get("preserveNonFocusSources", True)),
        },
        "coverage": {
            "scope": "registry_candidates_and_reviewed_sources",
            "status": "IN_PROGRESS",
            "discoveredCompanyCount": candidate_company_count,
            # This metric describes healthy, runnable official sources.  It is
            # intentionally separate from ``companiesWithEligibleJobs``:
            # a verified company may have no currently eligible generalist
            # posting, while a stale snapshot may still contain one.
            "verifiedActiveCompanyCount": len(verified_company_ids),
            "autoVerifiedSourceCount": auto_verified,
            "pendingReviewCompanyCount": pending_review_company_count,
            "blockedCompanyCount": len(blocked_company_ids),
            "accessibleSourceCoverageRate": accessible_source_coverage_rate if input_path is None else None,
            "lastDiscoveryAt": None,
            "consecutiveNoNewCycles": 0,
            "lastNewSourceAt": None,
        },
        "companyDiscovery": {
            # Read the checked-in authority metadata instead of inferring it
            # from a filename or assuming the index still contains 100 rows.
            # This keeps fixture/custom-index builds honest and makes the
            # public manifest traceable to the exact source file used by the
            # candidate-pool merge.
            "authorityIndexId": authority_index_id,
            "authorityIndexCompanyCount": authority_index_company_count,
            "candidatePoolCompanyCount": candidate_company_count,
            "hiringRadarCompanyCount": _hiring_radar_company_count(hiring_radar_path),
            "hiringRadarEntryUrlCount": _hiring_radar_entry_url_count(hiring_radar_path),
            "entryLayerSeparateFromJobSources": True,
        },
        "sourceHealth": {
            "healthy": healthy,
            "quarantined": quarantined,
            "stale": stale,
            "notModified": sum(1 for item in source_records if item.get("health") == "not_modified"),
            "blocked": sum(1 for item in source_records if item.get("health") == "blocked"),
            "error": sum(1 for item in source_records if item.get("health") == "error"),
            "autoVerified": auto_verified,
            "metricsVersion": 1,
        },
        "todayCampaignCount": sum(1 for campaign in campaign_values if campaign.get("openDate") == business_date),
        "todayPublishedJobCount": sum(1 for job in accepted if job.publish_date and job.publish_date.isoformat() == business_date and job.publish_date_source == "OFFICIAL"),
        "todayFirstSeenCount": sum(1 for job in accepted if job.first_seen_at.astimezone(SHANGHAI).date().isoformat() == business_date),
        "unknownLocationCount": sum(1 for job in accepted if not job.locations or any(location.scope.value == "UNKNOWN" for location in job.locations)),
        "audiencePolicy": {
            "version": AUDIENCE_POLICY_VERSION,
            "targetAudience": "文科、社科、商科及不限专业的通用校招岗位",
            "normalizedJobCount": sum(len(items) for items in normalized_by_source.values()),
            "eligibleJobCount": audience_counts[AudienceDecision.TARGET_GENERALIST.value],
            "excludedJobCount": audience_counts[AudienceDecision.OUT_OF_SCOPE.value],
            "reviewJobCount": audience_counts[AudienceDecision.NEEDS_REVIEW.value],
        },
        "companyDirectory": directory_summary,
        "shards": sorted(shards),
        "reports": reports,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "sources.json").write_text(json.dumps({"schemaVersion": 1, "catalogVersion": catalog_version, "generatedAt": generated_at.isoformat(), "sources": source_records}, ensure_ascii=False, indent=2), encoding="utf-8")

    if registry_path.exists():
        (output_dir / "companies.json").write_text(json.dumps({"schemaVersion": 1, "catalogVersion": catalog_version, "generatedAt": generated_at.isoformat(), "isDemo": input_path is not None, "companies": directory_records}, ensure_ascii=False, indent=2), encoding="utf-8")
    if sanitized_community_payload is not None:
        # Rewrite an existing public artifact through the privacy allow-list so
        # a legacy referralCode/referralUrl field cannot survive a catalog run.
        community_leads_path.write_text(json.dumps(sanitized_community_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if state_path:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        next_validators: dict[str, CacheEntry] = dict(source_validators)
        for record in source_records:
            source_id = str(record.get("sourceId") or "").strip()
            if not source_id or record.get("health") in {"not_ready", "blocked", "error"}:
                continue
            old_cache = next_validators.get(source_id, CacheEntry())
            validator_values = record.get("cacheValidators") if isinstance(record.get("cacheValidators"), dict) else {}
            next_validators[source_id] = CacheEntry(
                etag=str(validator_values.get("etag") or old_cache.etag or "") or None,
                last_modified=str(validator_values.get("last-modified") or old_cache.last_modified or "") or None,
                content_hash=str(record.get("contentHash") or old_cache.content_hash or "") or None,
                fetched_at=str(record.get("fetchedAt") or old_cache.fetched_at or "") or None,
                status_code=int(record.get("statusCode")) if isinstance(record.get("statusCode"), (int, float)) else old_cache.status_code,
                item_count=int(record.get("fetchedJobCount")) if isinstance(record.get("fetchedJobCount"), (int, float)) else old_cache.item_count,
            )
        state_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "audiencePolicyVersion": AUDIENCE_POLICY_VERSION,
                    "generatedAt": generated_at.isoformat(),
                    "sourceObservedCounts": next_observed_counts,
                    "sourceCountHistory": next_count_history,
                    "sourceValidators": dump_cache(next_validators),
                    "jobs": [model_json(job) for job in accepted],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # Only the reviewed live build targeting the checked-in public data
    # directory may update the repository-level audit artifact. Fixture/demo
    # builds and isolated temporary live builds (used by tests) must not
    # overwrite the report that the Pages workflow is about to publish.
    public_data_dir = (Path(__file__).resolve().parent.parent / "apps" / "web" / "public" / "data").resolve()
    if input_path is None and output_dir.resolve() == public_data_dir:
        audience_report_path = Path(__file__).resolve().parent.parent / "artifacts" / "audience-filter-report.json"
        audience_report_path.parent.mkdir(parents=True, exist_ok=True)
        audience_report_path.write_text(json.dumps(audience_report, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "accepted": sum(1 for job in accepted if job.status.value == "ACTIVE"),
        "reports": reports,
        "catalogVersion": catalog_version,
        "verifiedSourceCount": verified,
        "autoVerifiedSourceCount": auto_verified,
        "publishableSourceCount": verified + auto_verified,
        "isDemo": input_path is not None,
        "audiencePolicy": manifest["audiencePolicy"],
        "companyDirectory": manifest["companyDirectory"],
    }
    return result


def main(argv: list[str] | None = None) -> int:
    # Windows still commonly starts Python with a GBK console. Public job
    # titles can contain an otherwise harmless zero-width character, so make
    # the machine-readable status line safe to print without changing the
    # UTF-8 files written by the builder.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build a safe static job catalog from a reviewed source registry or fixture JSON.")
    parser.add_argument("--input", type=Path, help="Deterministic demo/fixture JSON; omit for reviewed live sources.")
    parser.add_argument("--sources", type=Path, default=Path("registry/sources.json"))
    parser.add_argument("--state", type=Path, help="Optional lifecycle state file to read/write between runs.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-verified-sources", type=int, default=0)
    parser.add_argument("--max-domain-workers", type=int, default=4)
    parser.add_argument("--focus", type=Path, default=Path("registry/internet-focus.json"))
    parser.add_argument("--entry-state", type=Path, default=Path("collector/company-directory-state.json"), help="daily entry-signal state; omitted uses registry fallback")
    parser.add_argument("--inbox", type=Path, help="optional user-selected local inbox JSON; rows use the same normalisation and audience gate")
    args = parser.parse_args(argv)
    result = build(args.input, args.output, sources_path=args.sources, state_path=args.state, min_verified_sources=args.min_verified_sources, max_domain_workers=args.max_domain_workers, focus_path=args.focus, entry_state_path=args.entry_state, inbox_path=args.inbox)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
