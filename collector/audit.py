from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .normalize import host_matches
from .registry import load_sources


def _sample(items: list[dict[str, Any]], size: int = 3) -> list[dict[str, Any]]:
    if len(items) <= size:
        return items
    indexes = sorted({0, len(items) // 2, len(items) - 1})
    return [items[index] for index in indexes[:size]]


def audit_catalog(catalog_path: Path, sources_path: Path, *, check_links: bool = False) -> dict[str, Any]:
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs", [])
    sources = {source.source_id: source for source in load_sources(sources_path)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in jobs:
        grouped[job.get("sourceId", "unknown")].append(job)

    source_rows: list[dict[str, Any]] = []
    invalid_domains: list[str] = []
    client = httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": "AutumnAssistantCollector/0.2 (+link-audit)"}) if check_links else None
    for source_id, source_jobs in sorted(grouped.items()):
        source = sources.get(source_id)
        allowed = [source.apply_domain, *source.apply_domains, *([source.ats_host] if source and source.ats_host else [])] if source else []
        samples = []
        for job in _sample(source_jobs):
            apply_url = str(job.get("applyUrl") or "")
            host = (urlparse(apply_url).hostname or "").lower()
            domain_ok = bool(source and any(host_matches(host, domain) for domain in allowed))
            if not domain_ok:
                invalid_domains.append(f"{source_id}:{job.get('id')}")
            link_status: int | None = None
            if client and domain_ok:
                try:
                    response = client.head(apply_url)
                    if response.status_code in {400, 403, 405}:
                        response = client.get(apply_url, headers={"Range": "bytes=0-1024"})
                    link_status = response.status_code
                except httpx.HTTPError:
                    link_status = 0
            samples.append({
                "jobId": job.get("id"), "title": job.get("title"), "companyName": job.get("companyName"),
                "cohort": job.get("cohort"), "batch": job.get("batch"), "applyUrl": apply_url,
                "domainValid": domain_ok, "httpStatus": link_status,
            })
        source_rows.append({
            "sourceId": source_id, "jobCount": len(source_jobs), "sampleCount": len(samples),
            "meetsThreeSampleTarget": len(samples) >= 3, "unknownCohortCount": sum(job.get("cohort") == "未知" for job in source_jobs),
            "unknownBatchCount": sum(job.get("batch") == "未知" for job in source_jobs), "samples": samples,
        })
    if client:
        client.close()
    return {
        "schemaVersion": 1, "generatedAt": datetime.now(UTC).isoformat(), "catalogVersion": payload.get("catalogVersion"),
        "jobCount": len(jobs), "sourceCount": len(source_rows), "invalidApplyDomainCount": len(invalid_domains),
        "invalidApplyDomains": invalid_domains, "linkChecksPerformed": check_links, "sources": source_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a generated catalog without changing it.")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=Path("registry/sources.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-links", action="store_true")
    args = parser.parse_args(argv)
    report = audit_catalog(args.catalog, args.sources, check_links=args.check_links)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "sources"}, ensure_ascii=False))
    return 1 if report["invalidApplyDomainCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
