from __future__ import annotations

"""专门解析国务院国资委中央企业名录的双栏表。

国资委正文页把序号 1--50 和 51--99 放在同一行的左右两组单元格里。
普通表格解析器通常只取一行的第一个名称，结果会漏掉右栏的一半。本模块
按 ``序号, 名称, 间隔, 序号, 名称`` 成对解析，并在数量异常时拒绝替换
上一版名单。名单只是权威身份与官网发现证据，不是招聘岗位来源。
"""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx


SASAC_SOURCE_URL = "http://www.sasac.gov.cn/n2588045/n27271785/n27271792/c14159097/content.html"
SASAC_EXPECTED_COUNT = 99
SASAC_SCHEMA_VERSION = 1
SASAC_HOSTS = {"www.sasac.gov.cn", "sasac.gov.cn", "wap.sasac.gov.cn"}


class SasacStructureError(ValueError):
    """Raised when the official page no longer yields the expected 99 rows."""


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_homepage(value: Any, *, source_url: str) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    url = urljoin(source_url, raw)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    # The two records for which SASAC currently has no group site link back to
    # this same catalogue.  That is authority evidence, not a company site.
    source_host = (urlparse(source_url).hostname or "").casefold()
    if (parsed.hostname or "").casefold() in SASAC_HOSTS or (parsed.hostname or "").casefold() == source_host:
        return None
    return url


def _rank(value: Any) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", _text(value))
    if not match:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= SASAC_EXPECTED_COUNT else None


def _pair_from_cells(cells: list[Any]) -> list[tuple[Any, Any]]:
    """Return left/right rank-name pairs from one table row."""

    if len(cells) < 2:
        return []
    pairs = [(cells[0], cells[1])]
    # The current page comments out the empty right half of row 50.  Accept a
    # two-cell left-only row while still requiring all five cells for the
    # normal two-column case.
    if len(cells) >= 5:
        pairs.append((cells[3], cells[4]))
    return pairs


def parse_sasac_central_enterprises(
    html: bytes | str,
    *,
    source_url: str = SASAC_SOURCE_URL,
    expected_count: int = SASAC_EXPECTED_COUNT,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Parse all left/right records and retain only lightweight metadata.

    ``strict=True`` is used by scheduled jobs and fixtures. A changed page is
    surfaced as an error instead of silently publishing a partial list.
    """

    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else str(html or "")
    soup = BeautifulSoup(raw, "html.parser")
    by_rank: dict[int, dict[str, Any]] = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue
            for rank_cell, name_cell in _pair_from_cells(cells):
                rank = _rank(rank_cell.get_text(" ", strip=True))
                if rank is None:
                    continue
                anchor = name_cell.find("a", href=True)
                name = _text(name_cell.get_text(" ", strip=True))
                if not name or name in {"企业(集团)名称", "企业集团名称"}:
                    continue
                homepage_observed = _text(anchor.get("href")) if anchor else None
                homepage = _safe_homepage(homepage_observed, source_url=source_url)
                row = {
                    "groupId": f"sasac-central-{rank:03d}",
                    "rank": rank,
                    "name": name,
                    "homepage": homepage,
                    "homepageObserved": homepage_observed,
                    "sourceUrl": source_url,
                    "ownershipClass": "CENTRAL_GROUP",
                    "requiresOfficialCareerReview": True,
                    "homepageReviewRequired": homepage is None,
                }
                previous = by_rank.get(rank)
                # Nested/desktop mirrors can contain the same row twice. Keep
                # the first complete row and do not count the duplicate.
                if previous is None or (not previous.get("homepage") and homepage):
                    by_rank[rank] = row
    rows = [by_rank[key] for key in sorted(by_rank)]
    if strict and len(rows) != expected_count:
        raise SasacStructureError(f"sasac_expected_{expected_count}_rows_got_{len(rows)}")
    return rows


def validate_sasac_rows(rows: Iterable[Mapping[str, Any]], *, expected_count: int = SASAC_EXPECTED_COUNT) -> tuple[bool, list[str]]:
    values = [row for row in rows if isinstance(row, Mapping)]
    reasons: list[str] = []
    ranks = [row.get("rank") for row in values]
    if len(values) != expected_count:
        reasons.append(f"row_count_{len(values)}_expected_{expected_count}")
    if sorted(rank for rank in ranks if isinstance(rank, int)) != list(range(1, expected_count + 1)):
        reasons.append("rank_sequence_incomplete_or_duplicate")
    names = [str(row.get("name") or "").strip() for row in values]
    if any(not name for name in names):
        reasons.append("empty_group_name")
    if len(set(names)) != len(names):
        reasons.append("duplicate_group_name")
    return not reasons, reasons


def build_sasac_report(
    html: bytes | str,
    *,
    source_url: str = SASAC_SOURCE_URL,
    previous_rows: Iterable[Mapping[str, Any]] = (),
    expected_count: int = SASAC_EXPECTED_COUNT,
    output: Path | None = None,
) -> dict[str, Any]:
    """Build a safe report and retain previous rows if the page is malformed."""

    parsed = parse_sasac_central_enterprises(html, source_url=source_url, expected_count=expected_count)
    valid, reasons = validate_sasac_rows(parsed, expected_count=expected_count)
    previous = [dict(row) for row in previous_rows if isinstance(row, Mapping)]
    rows = parsed if valid else previous
    report = {
        "schemaVersion": SASAC_SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "authorityId": "sasac-central-soes",
        "sourceUrl": source_url,
        "expectedCount": expected_count,
        "parsedCount": len(parsed),
        "valid": valid,
        "warnings": reasons,
        "retainedPreviousOnFailure": bool(not valid and previous),
        "companies": rows,
        "summary": {
            "centralGroupCount": len(rows),
            "homepageCount": sum(bool(row.get("homepage")) for row in rows),
            "homepageReviewRequiredCount": sum(bool(row.get("homepageReviewRequired")) for row in rows),
            "sourceIsAuthorityOnly": True,
        },
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def fetch_sasac_central_enterprises(
    *,
    url: str = SASAC_SOURCE_URL,
    timeout: float = 20.0,
    previous_rows: Iterable[Mapping[str, Any]] = (),
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch the official page without retrying or bypassing access controls."""

    previous_values = [dict(row) for row in previous_rows if isinstance(row, Mapping)]
    own_client = client is None
    http_client = client or httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        response = http_client.get(url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "autumn-assistant-sasac-discovery/0.1"})
        if response.status_code in {401, 403, 405, 429}:
            return build_sasac_report(b"", source_url=url, previous_rows=previous_values, output=None) | {"valid": False, "warnings": ["access_blocked"], "statusCode": response.status_code}
        if response.status_code >= 400:
            return build_sasac_report(b"", source_url=url, previous_rows=previous_values, output=None) | {"valid": False, "warnings": [f"http_status_{response.status_code}"], "statusCode": response.status_code}
        report = build_sasac_report(response.content, source_url=url, previous_rows=previous_values)
        report.update({"statusCode": response.status_code, "bytes": len(response.content)})
        return report
    except httpx.TimeoutException:
        return {"authorityId": "sasac-central-soes", "sourceUrl": url, "valid": False, "warnings": ["timeout"], "retainedPreviousOnFailure": bool(previous_values)}
    except httpx.RequestError as exc:
        return {"authorityId": "sasac-central-soes", "sourceUrl": url, "valid": False, "warnings": [f"request_error_{exc.__class__.__name__}"], "retainedPreviousOnFailure": bool(previous_values)}
    finally:
        if own_client:
            http_client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse the official SASAC 99 central-enterprise two-column catalogue.")
    parser.add_argument("--html", type=Path, default=None, help="optional saved HTML fixture; otherwise fetch the official page")
    parser.add_argument("--url", default=SASAC_SOURCE_URL)
    parser.add_argument("--previous", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("registry/sasac-central-enterprises.json"))
    args = parser.parse_args(argv)
    previous: list[dict[str, Any]] = []
    if args.previous and args.previous.exists():
        payload = json.loads(args.previous.read_text(encoding="utf-8"))
        values = payload.get("companies", payload) if isinstance(payload, dict) else payload
        previous = [dict(row) for row in values if isinstance(row, dict)] if isinstance(values, list) else []
    if args.html:
        report = build_sasac_report(args.html.read_bytes(), source_url=args.url, previous_rows=previous, output=args.output)
    else:
        report = fetch_sasac_central_enterprises(url=args.url, previous_rows=previous)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.get("summary", {"valid": report.get("valid"), "warnings": report.get("warnings", [])}), ensure_ascii=False))
    return 0 if report.get("valid") else 2


if __name__ == "__main__":
    raise SystemExit(main())
