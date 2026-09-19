from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .audience_policy import AUDIENCE_POLICY_VERSION, assess_job
from .schema import RawJob

REQUIRED_JOB_FIELDS = ("title", "companyName", "city", "roleCategory", "cohort", "batch", "education", "applyUrl", "sourceUrl")
DIRECTORY_STATUSES = {"DISCOVERED", "ACTIVE_CONFIRMED", "ACTIVE_LEAD", "INACTIVE", "BLOCKED", "STALE"}
ENTRY_TYPES = {"OFFICIAL_CAREER_SITE", "OFFICIAL_ATS", "OFFICIAL_CAMPAIGN_PAGE", "ENTRY_LEAD"}


def _snake_key(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _snake_value(value: object) -> object:
    """Convert nested public camelCase payloads back to collector fields."""

    if isinstance(value, dict):
        return {_snake_key(str(key)): _snake_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snake_value(item) for item in value]
    return value


def _validate_catalog(catalog_path: Path, minimum_completeness: float = 0.95) -> dict[str, int | float]:
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    active = [job for job in jobs if isinstance(job, dict) and job.get("status", "ACTIVE") == "ACTIVE"]
    if not active:
        raise RuntimeError("release_gate_no_active_jobs")
    complete = sum(1 for job in active if all(str(job.get(field, "")).strip() for field in REQUIRED_JOB_FIELDS))
    completeness = complete / len(active)
    if completeness < minimum_completeness:
        raise RuntimeError(f"release_gate_required_fields:{completeness:.3f}<{minimum_completeness:.3f}")
    invalid_links = [job for job in active if any(urlparse(str(job.get(field, ""))).scheme != "https" for field in ("applyUrl", "sourceUrl"))]
    if invalid_links:
        raise RuntimeError(f"release_gate_non_https_links:{len(invalid_links)}")
    return {"activeJobs": len(active), "completeJobs": complete, "completeness": completeness}


def _validate_audience(catalog_path: Path, jobs_dir: Path) -> dict[str, int]:
    """Re-run the audience gate against detail shards before publication."""

    catalog_payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    public_jobs = [
        item for item in catalog_payload.get("jobs", [])
        if isinstance(item, dict)
    ]
    shard_cache: dict[str, list[dict[str, object]]] = {}
    checked = 0
    for summary in public_jobs:
        job_id = str(summary.get("id", ""))
        shard = str(summary.get("detailShard", ""))
        shard_path = jobs_dir / f"{shard}.json"
        if not job_id or not shard or not shard_path.exists():
            raise RuntimeError(f"release_gate_missing_detail_job:{job_id}")
        if shard not in shard_cache:
            payload = json.loads(shard_path.read_text(encoding="utf-8"))
            shard_cache[shard] = [item for item in payload.get("jobs", []) if isinstance(item, dict)]
        detail = next((item for item in shard_cache[shard] if str(item.get("id", "")) == job_id), None)
        if detail is None:
            raise RuntimeError(f"release_gate_missing_detail_job:{job_id}")
        assessment = assess_job(RawJob.model_validate(_snake_value(detail)))
        if not assessment.publishable:
            raise RuntimeError(
                f"release_gate_audience_policy:{job_id}:{assessment.decision.value}:{','.join(assessment.reason_codes)}"
            )
        checked += 1
    return {"audienceCheckedJobs": checked, "audiencePolicyVersion": AUDIENCE_POLICY_VERSION}


def _validate_company_directory(companies_path: Path, manifest: dict[str, object] | None = None) -> dict[str, int]:
    """Validate the separate company-entry publication surface.

    A directory entry is allowed to be a lead, but its status and URL shape
    must be explicit.  Inactive/blocked/stale records are not public and
    therefore fail the gate instead of silently appearing in the website.
    This check never promotes a TARGET source to VERIFIED.
    """

    payload = json.loads(companies_path.read_text(encoding="utf-8"))
    records = payload.get("companies", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        raise RuntimeError("release_gate_invalid_company_directory")
    ids: set[str] = set()
    active = official = leads = 0
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("release_gate_invalid_company_directory_record")
        company_id = str(record.get("id", "")).strip()
        directory = record.get("directory")
        if not company_id or company_id in ids or not isinstance(directory, dict):
            raise RuntimeError(f"release_gate_invalid_company_directory_record:{company_id or 'missing'}")
        ids.add(company_id)
        status = str(directory.get("directoryStatus", ""))
        entry_type = str(directory.get("entryType", ""))
        if status not in DIRECTORY_STATUSES:
            raise RuntimeError(f"release_gate_invalid_directory_status:{company_id}:{status}")
        if entry_type not in ENTRY_TYPES:
            raise RuntimeError(f"release_gate_invalid_entry_type:{company_id}:{entry_type}")
        if status not in {"ACTIVE_CONFIRMED", "ACTIVE_LEAD"}:
            raise RuntimeError(f"release_gate_inactive_company_directory:{company_id}:{status}")
        career_url = str(directory.get("careerUrl", ""))
        evidence_url = str(directory.get("evidenceUrl", ""))
        if any(urlparse(value).scheme != "https" or not urlparse(value).hostname for value in (career_url, evidence_url)):
            raise RuntimeError(f"release_gate_non_https_company_directory:{company_id}")
        if status == "ACTIVE_LEAD" and entry_type != "ENTRY_LEAD":
            raise RuntimeError(f"release_gate_lead_entry_type_mismatch:{company_id}")
        if status == "ACTIVE_CONFIRMED" and entry_type == "ENTRY_LEAD":
            raise RuntimeError(f"release_gate_confirmed_entry_type_mismatch:{company_id}")
        active += 1
        if entry_type == "ENTRY_LEAD":
            leads += 1
        else:
            official += 1
    result = {"directoryCompanyCount": active, "directoryOfficialEntryCount": official, "directoryEntryLeadCount": leads}
    summary = manifest.get("companyDirectory") if isinstance(manifest, dict) else None
    if isinstance(summary, dict):
        expected = {
            "directorySourceCompanyCount": active,
            "activeRecruitingCompanyCount": active,
            "officialEntryCount": official,
            "entryLeadCount": leads,
        }
        mismatches = [key for key, value in expected.items() if summary.get(key) is not None and summary.get(key) != value]
        if mismatches:
            raise RuntimeError(f"release_gate_company_directory_summary:{','.join(mismatches)}")
    return result


def validate_manifest(
    manifest_path: Path,
    min_verified_sources: int,
    catalog_path: Path | None = None,
    jobs_dir: Path | None = None,
    companies_path: Path | None = None,
) -> dict[str, int | float | bool | str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified = int(manifest.get("verifiedSourceCount", 0))
    auto_verified = int(manifest.get("autoVerifiedSourceCount", 0))
    publishable = int(manifest.get("publishableSourceCount", verified + auto_verified))
    total = int(manifest.get("sourceCount", 0))
    if manifest.get("isDemo") is True:
        raise RuntimeError("release_gate_demo_catalog")
    if publishable < min_verified_sources:
        raise RuntimeError(f"release_gate_verified_sources:{publishable}<{min_verified_sources}")
    if auto_verified < 0 or verified < 0 or publishable != verified + auto_verified:
        raise RuntimeError("release_gate_invalid_publishable_source_counts")
    if total < publishable:
        raise RuntimeError("release_gate_invalid_source_counts")
    auto_reports = manifest.get("autoVerificationReports")
    if auto_verified:
        if not isinstance(auto_reports, list) or len(auto_reports) < auto_verified:
            raise RuntimeError("release_gate_auto_verification_reports_missing")
        auto_report_ids: set[str] = set()
        for report in auto_reports:
            if not isinstance(report, dict) or report.get("conclusion") != "AUTO_VERIFIED":
                raise RuntimeError("release_gate_auto_verification_incomplete")
            source_id = str(report.get("sourceId") or "").strip()
            if not source_id or source_id in auto_report_ids:
                raise RuntimeError("release_gate_auto_verification_source_ids")
            auto_report_ids.add(source_id)
    result: dict[str, int | float | bool] = {"isDemo": False, "verifiedSourceCount": verified, "autoVerifiedSourceCount": auto_verified, "publishableSourceCount": publishable, "sourceCount": total}
    if catalog_path:
        result.update(_validate_catalog(catalog_path))
    if jobs_dir:
        if not catalog_path:
            raise RuntimeError("release_gate_audience_requires_catalog")
        result.update(_validate_audience(catalog_path, jobs_dir))
        policy = manifest.get("audiencePolicy")
        if not isinstance(policy, dict) or policy.get("version") != AUDIENCE_POLICY_VERSION:
            raise RuntimeError("release_gate_audience_policy_version")
    if companies_path:
        result.update(_validate_company_directory(companies_path, manifest))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Prevent a demo or under-audited catalog from being published.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--min-verified-sources", type=int, required=True)
    parser.add_argument("--catalog", type=Path, help="Optional catalog.json to enforce active-job completeness and HTTPS links.")
    parser.add_argument("--jobs-dir", type=Path, help="Optional detail-shard directory for audience-policy revalidation.")
    parser.add_argument("--companies", type=Path, help="Optional companies.json to validate public entry statuses and HTTPS evidence.")
    args = parser.parse_args()
    print(json.dumps(validate_manifest(args.manifest, args.min_verified_sources, args.catalog, args.jobs_dir, args.companies), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
