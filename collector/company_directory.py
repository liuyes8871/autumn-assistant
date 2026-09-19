from __future__ import annotations

"""Build the public company-entry directory.

Company discovery is deliberately broader than runnable job collection.  This
module only emits a lightweight, auditable entry for companies that already
have a registered public career URL or source.  It never promotes a source to
VERIFIED and never copies job descriptions into the directory.
"""

from collections import defaultdict
from datetime import UTC, datetime
import re
from typing import Any, Iterable
from urllib.parse import urlparse


CURRENT_COHORT = "2027"


def _url(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _entry_type(source: Any | None, career_url: str) -> str:
    if source is None:
        return "ENTRY_LEAD"
    adapter = str(getattr(source, "adapter", "") or "").lower()
    access_mode = str(getattr(source, "access_mode", "") or "").upper()
    if access_mode == "JSON" or adapter in {"feishu", "beisen", "workday", "greenhouse", "lever", "successfactors", "moka"}:
        return "OFFICIAL_ATS"
    if "/campus" in career_url.lower() or "xiaozhao" in career_url.lower() or "school" in career_url.lower():
        return "OFFICIAL_CAMPAIGN_PAGE"
    return "OFFICIAL_CAREER_SITE"


def build_company_directory(
    companies: Iterable[dict[str, Any]],
    sources: Iterable[Any],
    jobs: Iterable[Any],
    *,
    now: datetime,
    cohort: str = CURRENT_COHORT,
    directory_source: str = "registry/companies.json",
    community_leads: Iterable[dict[str, Any]] | None = None,
    entry_observations: dict[str, dict[str, Any]] | None = None,
    focus_segments: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int | str | None]]:
    """Return public company records and separate directory metrics.

    ``ACTIVE_CONFIRMED`` requires a reviewed source, an active job emitted by
    one, or a daily first-party current-cohort signal observation.  A
    registered but unreviewed career URL is retained as an ``ACTIVE_LEAD`` so
    users can reach the employer while seeing the lower confidence label.
    Records without any public URL are not displayed.
    """

    checked_at = now.astimezone(UTC).isoformat()
    source_by_company: dict[str, list[Any]] = defaultdict(list)
    for source in sources:
        company_id = str(getattr(source, "company_id", "") or "")
        if company_id:
            source_by_company[company_id].append(source)

    current_jobs_by_company: dict[str, list[Any]] = defaultdict(list)
    for job in jobs:
        company_id = str(getattr(job, "company_id", "") or "")
        status = str(getattr(getattr(job, "status", None), "value", getattr(job, "status", "")) or "")
        job_cohort = str(getattr(job, "cohort", "") or "")
        if company_id and status == "ACTIVE" and job_cohort == cohort:
            current_jobs_by_company[company_id].append(job)

    company_values = [dict(company) for company in companies if isinstance(company, dict) and company.get("id")]
    # Community posts can help discover a public employer URL, but they never
    # become official evidence.  Only leads that mention the configured cohort
    # (or a clearly labelled autumn campus campaign) are considered, and no
    # referral code is copied into this directory.
    lead_urls: dict[str, tuple[str, dict[str, Any]]] = {}
    cohort_pattern = re.compile(rf"{re.escape(cohort)}\s*(?:届|级|校招|校园招聘)|秋招|秋季校园招聘", re.I)
    for lead in community_leads or []:
        if not isinstance(lead, dict):
            continue
        company_id = str(lead.get("companyId") or "")
        url = str(lead.get("officialUrl") or "").strip()
        title = str(lead.get("title") or "")
        if not company_id or not url or not url.startswith("https://") or not cohort_pattern.search(title):
            continue
        if not lead.get("officialUrlVerified", False) and str(lead.get("verificationStatus") or "NEEDS_REVIEW") != "NEEDS_REVIEW":
            continue
        previous = lead_urls.get(company_id)
        if previous is None or bool(lead.get("officialUrlVerified")) and not bool(previous[1].get("officialUrlVerified")):
            lead_urls[company_id] = (url, lead)

    company_by_id = {str(company["id"]): company for company in company_values}
    # Add a known company that has a current community lead but no registered
    # careerUrl. Unknown social-only names are intentionally not materialised.
    for company_id, (url, _lead) in lead_urls.items():
        company = company_by_id.get(company_id)
        if company and not company.get("careerUrl"):
            company["careerUrl"] = url

    records: list[dict[str, Any]] = []
    official_count = 0
    lead_count = 0
    confirmed_job_company_ids: set[str] = set()
    last_verified: str | None = None
    observed_dates = [
        str(value.get("lastCheckedAt") or value.get("checkedAt") or "")
        for value in (entry_observations or {}).values()
        if isinstance(value, dict) and str(value.get("lastCheckedAt") or value.get("checkedAt") or "").strip()
    ]

    # Iterate over the normalised copy rather than the original iterable.
    # ``company_values`` may have been materialised from a generator and also
    # carries a career URL filled from a community lead.  Iterating the
    # original input here would both consume generators a second time and
    # drop that lead-only company from the public directory.
    for rank, company in enumerate(company_values, start=1):
        if not isinstance(company, dict) or not company.get("id"):
            continue
        company_id = str(company["id"])
        company_sources = source_by_company.get(company_id, [])
        observed = (entry_observations or {}).get(company_id, {})
        # Once a daily signal state is supplied it becomes the source of truth
        # for directory visibility.  A missing company in that state means
        # that no current-cohort signal was observed and must not fall back to
        # a legacy career URL or an old job snapshot.  ``None`` keeps the
        # backwards-compatible registry behaviour for first-time/local builds.
        if entry_observations is not None and company_id not in entry_observations:
            continue
        # A daily signal report can explicitly suppress a stale/inactive
        # generic career URL.  In its absence we retain the existing registry
        # behaviour for backward-compatible static catalogs.
        observed_status = str(observed.get("directoryStatus") or "")
        if observed and observed_status not in {"ACTIVE_CONFIRMED", "ACTIVE_LEAD"}:
            continue
        if entry_observations is not None and observed_status not in {"ACTIVE_CONFIRMED", "ACTIVE_LEAD"}:
            continue
        career_url = _url(observed.get("careerUrl")) or _url(company.get("careerUrl"))
        if not career_url:
            career_url = next((_url(getattr(source, "source_url", None)) for source in company_sources), None)
        if not career_url:
            continue

        reviewed = [source for source in company_sources if str(getattr(source, "status", "")) in {"VERIFIED", "AUTO_VERIFIED"}]
        current_jobs = current_jobs_by_company.get(company_id, [])
        confirmed = bool(reviewed or current_jobs)
        # An entry observation can confirm the current cohort even before a
        # job source is reviewed.  Keep the entry layer status separate from
        # ``sourceStatus`` while still allowing a verified source/job to
        # upgrade the label from a lead to an official entry.
        observed_confirmed = observed_status == "ACTIVE_CONFIRMED"
        entry_status = "ACTIVE_CONFIRMED" if (confirmed or observed_confirmed) else "ACTIVE_LEAD"
        observed_entry_type = str(observed.get("entryType") or "").strip()
        entry_type = observed_entry_type if observed_entry_type in {"OFFICIAL_CAREER_SITE", "OFFICIAL_ATS", "OFFICIAL_CAMPAIGN_PAGE", "ENTRY_LEAD"} else _entry_type(reviewed[0] if reviewed else (company_sources[0] if company_sources else None), career_url)
        if not confirmed and not observed_confirmed:
            entry_type = "ENTRY_LEAD"
        if entry_type == "ENTRY_LEAD":
            lead_count += 1
        else:
            official_count += 1
        if current_jobs:
            confirmed_job_company_ids.add(company_id)

        source_evidence = next((_url(getattr(source, "source_url", None)) for source in reviewed), None)
        lead_evidence = lead_urls.get(company_id)
        if not source_evidence and lead_evidence:
            # An XHS/community lead remains a lead even when its URL was
            # manually checked; the source cannot upgrade a TARGET channel.
            evidence_url = _url(lead_evidence[1].get("sourceUrl")) or lead_evidence[0]
        else:
            evidence_url = None
        observed_evidence = _url(observed.get("evidenceUrl"))
        evidence_url = source_evidence or observed_evidence or evidence_url or _url(company.get("discoveryEvidenceUrls", [None])[0] if isinstance(company.get("discoveryEvidenceUrls"), list) and company.get("discoveryEvidenceUrls") else None) or career_url
        verified_dates = [str(getattr(source, "verified_at", "") or "") for source in reviewed if getattr(source, "verified_at", None)]
        if verified_dates:
            last_verified = max(last_verified or "", max(verified_dates))
        observed_signals = [str(value) for value in observed.get("signals", observed.get("detectedSignals", [])) if str(value).strip()]
        signals = observed_signals or [f"{cohort} 届校招入口已登记"]
        if current_jobs:
            signals.append(f"已同步 {len(current_jobs)} 条合格岗位")
        elif observed_signals:
            pass
        elif confirmed or observed_confirmed:
            signals.append("官方校园招聘来源已核验")
        else:
            signals.append("入口线索待完成企业官网反向确认")
        entry = {
            "companyId": company_id,
            "cohort": cohort,
            "directoryStatus": entry_status,
            "entryType": entry_type,
            "careerUrl": career_url,
            "evidenceUrl": evidence_url,
            "evidenceText": str(observed.get("evidenceText") or (
                "官方页面检测到当前届校园招聘信号；具体岗位以企业官网和岗位详情为准。"
                if observed_confirmed and not confirmed
                else "官方校园招聘来源已完成基础核验；具体岗位以企业官网和岗位详情为准。"
                if confirmed
                else "已登记公开招聘入口，当前届活动和官方性仍待人工确认；不会自动采集该入口的岗位。"
            )),
            "detectedSignals": signals,
            "directorySource": directory_source + ("+community-leads.json" if lead_evidence and not source_evidence else ""),
            "directoryRank": rank,
            "firstConfirmedAt": observed.get("firstConfirmedAt") or (checked_at if confirmed else None),
            "lastCheckedAt": observed.get("lastCheckedAt") or observed.get("checkedAt") or checked_at,
        }
        record = dict(company)
        # Keep discovery focus metadata available to the UI's optional
        # segment filter without conflating it with source verification.  The
        # field is descriptive only; it never changes directoryStatus or
        # sourceStatus.
        focus_segment = str((focus_segments or {}).get(company_id) or "").strip()
        if focus_segment:
            record["focusSegment"] = focus_segment
        record["directory"] = entry
        records.append(record)

    records.sort(key=lambda item: (
        0 if item.get("directory", {}).get("directoryStatus") == "ACTIVE_CONFIRMED" else 1,
        str(item.get("name", "")),
    ))
    summary: dict[str, int | str | None] = {
        "cohort": cohort,
        "directorySourceCompanyCount": len(records),
        "activeRecruitingCompanyCount": len(records),
        "officialEntryCount": official_count,
        "entryLeadCount": lead_count,
        "companiesWithEligibleJobs": len(confirmed_job_company_ids),
        "eligibleJobCount": sum(len(values) for values in current_jobs_by_company.values()),
        "lastDiscoveryAt": max(observed_dates) if observed_dates else checked_at,
        "lastVerifiedAt": last_verified,
    }
    return records, summary
