from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import zipfile

from collector.sasac import fetch_sasac_central_enterprises, parse_sasac_central_enterprises, validate_sasac_rows
from collector.state_owned import (
    StateOwnedCompanyCandidate,
    import_equity_nature_xlsx,
    match_company_identity,
    normalize_stock_code,
)
from collector.state_owned_discovery import extract_recruitment_links
from collector.state_owned_discovery import probe_state_owned_company


ROOT = Path(__file__).resolve().parents[1]


def _write_minimal_xlsx(path: Path) -> None:
    def cell(ref: str, value: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'

    headers = [
        "EN_EquityNatureAll.Symbol", "EN_EquityNatureAll.ShortName", "EN_EquityNatureAll.EndDate",
        "EN_EquityNatureAll.EquityNature", "STK_LISTEDCOINFOANL.ShortName", "STK_LISTEDCOINFOANL.ListedCoID",
        "STK_LISTEDCOINFOANL.SecurityID", "STK_LISTEDCOINFOANL.FullName", "STK_LISTEDCOINFOANL.Website",
        "STK_LISTEDCOINFOANL.MAINBUSSINESS", "STK_LISTEDCOINFOANL.LISTINGSTATE",
    ]
    values = ["000001", "示例股份", "2025-12-31", "国企", "示例股份", "", "", "示例股份有限公司", "example.com", "主营", "正常上市"]
    mixed = ["000002", "混合股份", "2025-12-31", "国企,民营", "混合股份", "", "", "混合股份有限公司", "", "主营", "正常上市"]
    rows = []
    for index, row in enumerate([headers, ["证券代码", "证券简称", "截止日期", "股权性质", "股票简称", "上市公司ID", "证券ID", "中文全称", "公司网址", "主营业务", "上市状态"], ["没有单位"] * 9 + ["", ""], values, mixed], start=1):
        rows.append(f'<row r="{index}">' + "".join(cell(f"{chr(65 + col)}{index}", value) for col, value in enumerate(row)) + "</row>")
    xml = '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:A6"/><sheetData>' + "".join(rows) + "</sheetData></worksheet>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", xml)


def test_xlsx_import_preserves_cells_outside_declared_dimension_and_filters_exact_nature(tmp_path: Path) -> None:
    workbook = tmp_path / "equity.xlsx"
    _write_minimal_xlsx(workbook)
    result = import_equity_nature_xlsx(workbook)
    assert result.summary["sourceRowCount"] == 2
    assert result.summary["stateOwnedCount"] == 1
    assert result.summary["mixedOwnershipCount"] == 1
    assert result.summary["websiteCount"] == 1
    assert result.state_owned_rows[0].stock_code == "000001"
    assert result.state_owned_rows[0].homepage_candidates == ["https://example.com"]
    assert result.review_rows[0]["reason"] == "mixed_equity_nature_manual_review"


def test_state_owned_workbook_counts_match_user_export_when_copy_is_available() -> None:
    source = Path(__import__("tempfile").gettempdir()) / "autumn-assistant-equity-nature-readonly.xlsx"
    if not source.exists():
        return
    result = import_equity_nature_xlsx(source)
    assert result.summary["sourceRowCount"] == 5297
    assert result.summary["stateOwnedCount"] == 1441
    assert result.summary["websiteCount"] == 1402
    assert result.summary["missingWebsiteCount"] == 39
    assert result.summary["normalListingCount"] == 1424
    assert result.summary["otherListingStateCount"] == 17
    assert result.summary["equityAsOf"] == "2025-12-31"
    assert result.summary["websiteAnomalyCount"] == 14
    assert all(len(row.stock_code or "") == 6 for row in result.state_owned_rows)


def test_stock_code_normalisation_keeps_leading_zeroes() -> None:
    assert normalize_stock_code("000001") == "000001"
    assert normalize_stock_code(1) == "000001"
    assert normalize_stock_code("600000.0") == "600000"
    assert normalize_stock_code("SSE:002415") == "002415"


def test_identity_matching_uses_code_before_name_and_refuses_cross_key_conflict() -> None:
    candidate = StateOwnedCompanyCandidate(
        candidateId="x", stockCode="000001", shortName="甲", legalName="甲股份有限公司", equityNature="国企",
        equityAsOf=date(2025, 12, 31), homepageCandidates=["https://a.example.com"],
    )
    assert match_company_identity(candidate, [{"id": "one", "name": "甲", "stockCodes": ["000001"]}])["matchMethod"] == "STOCK_CODE"
    conflict = match_company_identity(candidate, [
        {"id": "one", "name": "乙", "stockCodes": ["000001"]},
        {"id": "two", "name": "甲", "stockCodes": []},
    ])
    assert conflict["matchMethod"] == "CONFLICT"
    assert conflict["candidateCompanyIds"] == ["one", "two"]


def test_identity_matching_considers_short_name_alias_when_legal_name_differs() -> None:
    candidate = StateOwnedCompanyCandidate(
        candidateId="alias", stockCode="000003", shortName="简称甲", legalName="法定名称甲有限公司", equityNature="国企",
    )
    result = match_company_identity(candidate, [{"id": "company-a", "name": "另一展示名", "aliases": ["简称甲"]}])
    assert result["matchedCompanyId"] == "company-a"
    assert result["matchMethod"] == "LEGAL_NAME_OR_ALIAS"


def test_sasac_registry_is_complete_and_parser_handles_two_column_rows() -> None:
    payload = json.loads((ROOT / "registry" / "sasac-central-enterprises.json").read_text(encoding="utf-8"))
    assert payload["valid"] is True
    assert len(payload["companies"]) == 99
    assert validate_sasac_rows(payload["companies"]) == (True, [])
    html = "<table><tr><th>序号</th><th>企业(集团)名称</th><th></th><th>序号</th><th>企业(集团)名称</th></tr>" + "".join(
        f'<tr><td>{left}</td><td><a href="https://{left}.example.com">集团{left}</a></td><td></td><td>{right}</td><td><a href="https://{right}.example.com">集团{right}</a></td></tr>'
        for left, right in [(1, 51), (2, 52)]
    ) + "</table>"
    rows = parse_sasac_central_enterprises(html, expected_count=4)
    assert [row["rank"] for row in rows] == [1, 2, 51, 52]


def test_sasac_fetch_retains_previous_rows_when_public_page_is_blocked() -> None:
    class Response:
        status_code = 403
        headers = {"content-type": "text/html"}
        content = b"access denied"

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    previous = [{"groupId": "sasac-central-001", "rank": 1, "name": "上一版集团"}]
    result = fetch_sasac_central_enterprises(client=Client(), previous_rows=previous)
    assert result["valid"] is False
    assert result["warnings"] == ["access_blocked"]
    assert result["retainedPreviousOnFailure"] is True
    assert result["companies"] == previous


def test_recruitment_link_discovery_ignores_unrelated_external_links() -> None:
    html = '<a href="/about">关于我们</a><a href="/campus-recruit">校园招聘</a><a href="https://social.example.net/company">招聘广告</a>'
    assert extract_recruitment_links(html, page_url="https://company.example.com/") == ["https://company.example.com/campus-recruit"]


def test_state_owned_probe_keeps_discovered_entry_as_target_and_drops_response_body() -> None:
    class Response:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        url = "https://company.example.com/"
        content = '<a href="/campus">2027届校园招聘</a>'.encode("utf-8")

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    result = probe_state_owned_company({
        "candidateId": "soes-demo", "stockCode": "000001", "shortName": "示例", "legalName": "示例有限公司",
        "homepageObserved": "company.example.com", "homepageCandidates": ["https://company.example.com/"],
    }, client=Client())
    assert result["sourceStatus"] == "TARGET"
    assert result["runnable"] is False
    assert result["verified"] is False
    assert "content" not in result and "responseBody" not in result


def test_state_owned_probe_uses_public_validators_and_reuses_previous_row_on_304() -> None:
    calls: list[dict[str, str]] = []

    class Response:
        status_code = 304
        headers = {"etag": 'W/"demo"', "last-modified": "Wed, 16 Sep 2026 00:00:00 GMT"}
        content = b""

    class Client:
        def get(self, *_args: object, **kwargs: object) -> Response:
            calls.append(dict(kwargs.get("headers") or {}))
            return Response()

    previous = {
        "candidateId": "soes-demo",
        "homepageUrl": "https://company.example.com/",
        "recruitmentLinks": ["https://company.example.com/campus"],
        "classification": "CONNECTOR_CANDIDATE",
        "sourceStatus": "TARGET",
        "runnable": False,
        "etag": 'W/"old"',
        "lastModified": "Tue, 15 Sep 2026 00:00:00 GMT",
        "contentHash": "old-hash",
    }
    result = probe_state_owned_company({
        "candidateId": "soes-demo", "stockCode": "000001", "shortName": "示例", "legalName": "示例有限公司",
        "homepageObserved": "company.example.com", "homepageCandidates": ["https://company.example.com/"],
    }, client=Client(), previous_result=previous)
    assert calls[0]["If-None-Match"] == 'W/"old"'
    assert calls[0]["If-Modified-Since"] == "Tue, 15 Sep 2026 00:00:00 GMT"
    assert result["notModified"] is True
    assert result["recruitmentLinks"] == previous["recruitmentLinks"]
    assert result["classification"] == "CONNECTOR_CANDIDATE"
    assert result["contentHash"] == "old-hash"
    assert result["sourceStatus"] == "TARGET"
    assert result["runnable"] is False
