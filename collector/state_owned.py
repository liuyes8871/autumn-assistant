from __future__ import annotations

"""Read-only import and identity matching for state-owned listed companies.

The workbook supplied by the user is an upstream research export, not a web
asset and not a source registry.  This module deliberately reads the OOXML
worksheet directly instead of relying on the workbook dimension metadata: the
export has cells in columns A:K while its ``dimension`` says ``A1:A5300``.
Reading the cells directly preserves leading zeroes in stock codes and keeps
the importer usable in CI without requiring Excel or WPS.

The output is a discovery backlog.  A homepage is evidence for where to look
for an official campus page; it is never a career URL, a verified source, or a
job snapshot by itself.
"""

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Literal, Mapping
from urllib.parse import urlparse
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field


XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XLSX_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
SASAC_SOURCE_URL = "http://www.sasac.gov.cn/n2588045/n27271785/n27271792/c14159097/content.html"
IMPORT_SCHEMA_VERSION = 1


class StateOwnedCompanyCandidate(BaseModel):
    """Discovery-only identity record for one exact ``国企`` workbook row."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    candidate_id: str = Field(alias="candidateId")
    stock_code: str | None = Field(default=None, alias="stockCode")
    short_name: str = Field(alias="shortName")
    legal_name: str = Field(alias="legalName")
    equity_nature: str = Field(alias="equityNature")
    equity_as_of: date | None = Field(default=None, alias="equityAsOf")
    listing_state: str | None = Field(default=None, alias="listingState")
    homepage_observed: str | None = Field(default=None, alias="homepageObserved")
    homepage_candidates: list[str] = Field(default_factory=list, alias="homepageCandidates")
    ownership_class: Literal["CENTRAL_GROUP", "CENTRAL_SUBSIDIARY", "LOCAL_STATE_OWNED", "UNCLASSIFIED_STATE_OWNED"] = Field(default="UNCLASSIFIED_STATE_OWNED", alias="ownershipClass")
    parent_group_id: str | None = Field(default=None, alias="parentGroupId")
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    review_status: str = Field(default="NEEDS_REVIEW", alias="reviewStatus")
    review_reasons: list[str] = Field(default_factory=list, alias="reviewReasons")
    matched_company_id: str | None = Field(default=None, alias="matchedCompanyId")
    match_method: str | None = Field(default=None, alias="matchMethod")
    candidate_company_ids: list[str] = Field(default_factory=list, alias="candidateCompanyIds")
    display_type: str = Field(default="未知", alias="displayType")


@dataclass(frozen=True)
class WorkbookImport:
    """Validated workbook rows plus a privacy-safe summary."""

    rows: list[dict[str, Any]]
    state_owned_rows: list[StateOwnedCompanyCandidate]
    review_rows: list[dict[str, Any]]
    summary: dict[str, Any]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).replace("\u3000", " ").strip()


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _column_name(cell_ref: str) -> str:
    match = re.match(r"([A-Za-z]+)", str(cell_ref or ""))
    return match.group(1).upper() if match else ""


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return ["".join(node.itertext()) for node in root.findall(f".//{{{XLSX_MAIN_NS}}}si")]


def _sheet_path(archive: zipfile.ZipFile) -> str:
    """Resolve the first worksheet through workbook relationships."""

    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return "xl/worksheets/sheet1.xml"
    rel_map = {
        str(item.get("Id")): str(item.get("Target") or "")
        for item in rels
        if item.get("Id") and item.get("Target")
    }
    sheets = workbook.find(f"{{{XLSX_MAIN_NS}}}sheets")
    if sheets is not None:
        for sheet in sheets:
            relation = sheet.get(f"{{{XLSX_REL_NS}}}id")
            target = rel_map.get(str(relation or ""), "")
            if target:
                target = target.lstrip("/")
                return target if target.startswith("xl/") else f"xl/{target}"
    return "xl/worksheets/sheet1.xml"


def _cell_value(cell: ET.Element, strings: list[str]) -> Any:
    cell_type = str(cell.get("t") or "")
    if cell_type == "inlineStr":
        return "".join(cell.findtext(f".//{{{XLSX_MAIN_NS}}}t", default=""))
    raw = cell.findtext(f"{{{XLSX_MAIN_NS}}}v", default="")
    if cell_type == "s":
        try:
            return strings[int(raw)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return raw == "1"
    if cell_type in {"str", "e"}:
        return raw
    return raw


def read_xlsx_rows(path: Path) -> list[dict[str, Any]]:
    """Read every non-empty OOXML row, including cells outside bad dimensions."""

    with zipfile.ZipFile(path) as archive:
        sheet = _sheet_path(archive)
        strings = _shared_strings(archive)
        root = ET.fromstring(archive.read(sheet))
    rows: list[dict[str, Any]] = []
    for row in root.findall(f".//{{{XLSX_MAIN_NS}}}row"):
        values: dict[str, Any] = {}
        for cell in row.findall(f"{{{XLSX_MAIN_NS}}}c"):
            column = _column_name(cell.get("r", ""))
            if column:
                values[column] = _cell_value(cell, strings)
        if values:
            values["__row__"] = int(row.get("r") or len(rows) + 1)
            rows.append(values)
    return rows


HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "stock_code": ("EN_EquityNatureAll.Symbol", "证券代码", "股票代码", "Symbol"),
    "short_name": ("EN_EquityNatureAll.ShortName", "证券简称", "股票简称", "简称"),
    "equity_as_of": ("EN_EquityNatureAll.EndDate", "截止日期"),
    "equity_nature": ("EN_EquityNatureAll.EquityNature", "股权性质"),
    "legal_name": ("STK_LISTEDCOINFOANL.FullName", "中文全称", "法定全称", "公司全称"),
    "homepage": ("STK_LISTEDCOINFOANL.Website", "公司网址", "官网", "网站"),
    "business": ("STK_LISTEDCOINFOANL.MAINBUSSINESS", "主营业务"),
    "listing_state": ("STK_LISTEDCOINFOANL.LISTINGSTATE", "上市状态"),
}


def _header_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Map canonical fields to columns using English and Chinese header rows."""

    candidates = rows[:3]
    result: dict[str, str] = {}
    for field, aliases in HEADER_ALIASES.items():
        for row in candidates:
            for column, raw in row.items():
                if column.startswith("__"):
                    continue
                if _text(raw) in aliases:
                    result[field] = column
                    break
            if field in result:
                break
    # The export has a stable A:K layout.  These fallbacks also keep the
    # parser useful for a workbook whose header text was translated.
    fallbacks = {
        "stock_code": "A", "short_name": "B", "equity_as_of": "C",
        "equity_nature": "D", "legal_name": "H", "homepage": "I",
        "business": "J", "listing_state": "K",
    }
    for field, column in fallbacks.items():
        result.setdefault(field, column)
    return result


def _decimal_to_code(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        digits = str(int(value))
    elif isinstance(value, int):
        digits = str(value)
    else:
        text = _text(value).replace(",", "")
        if not text:
            return None
        # Excel exports may serialise an otherwise textual code as 1.0 or
        # scientific notation. Decimal avoids binary float rounding here.
        try:
            number = Decimal(text)
            if number == number.to_integral_value():
                digits = format(number.quantize(Decimal("1")), "f")
            else:
                digits = ""
        except (InvalidOperation, ValueError):
            digits = ""
        if not digits:
            digits_match = re.fullmatch(r"(?:[A-Za-z]{1,6}[:.]?)?(\d{1,6})", text)
            if not digits_match:
                return None
            digits = digits_match.group(1)
    digits = re.sub(r"\D", "", digits)
    if not digits or len(digits) > 6:
        return None
    return digits.zfill(6)


def normalize_stock_code(value: Any) -> str | None:
    """Return a six-character code without losing leading zeroes."""

    return _decimal_to_code(value)


def parse_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    match = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def split_homepage_values(value: Any) -> list[str]:
    """Split a raw website field without treating it as a career URL."""

    text = _text(value)
    if not text:
        return []
    # A whitespace inside a domain (``www. example.com``) is retained as an
    # anomaly by the caller rather than silently repaired.
    values = [part.strip() for part in re.split(r"[;,；，、\n\r\t]+", text) if part.strip()]
    return values or [text]


def normalize_homepage(value: Any) -> tuple[list[str], list[str]]:
    """Return (safe candidates, reasons) for an observed homepage field."""

    values = split_homepage_values(value)
    candidates: list[str] = []
    reasons: list[str] = []
    for raw in values:
        if re.search(r"\s", raw):
            reasons.append("homepage_contains_whitespace")
            continue
        candidate = raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}"
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            reasons.append("homepage_invalid_url")
            continue
        if parsed.path in {"", "/"} and not parsed.query and not parsed.fragment:
            pass
        if candidate not in candidates:
            candidates.append(candidate)
    if len(values) > 1:
        reasons.append("homepage_multiple_addresses")
    if not values:
        reasons.append("homepage_missing")
    return candidates, list(dict.fromkeys(reasons))


def normalize_identity(value: Any) -> str:
    """Normalize an exact identity key without dropping legal suffixes."""

    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", _text(value).casefold())


def normalized_domain(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    parsed = urlparse(text if re.match(r"^https?://", text, re.I) else f"https://{text}")
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def candidate_id_for_stock(stock_code: str | None, legal_name: str, short_name: str) -> str:
    seed = f"{stock_code or ''}|{normalize_identity(legal_name)}|{normalize_identity(short_name)}"
    return "soes-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _raw_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapping = _header_map(rows)
    output: list[dict[str, Any]] = []
    for row in rows:
        if int(row.get("__row__", 0) or 0) <= 3:
            continue
        get = lambda field: row.get(mapping[field], "")
        nature = _text(get("equity_nature"))
        if not any(_text(value) for key, value in row.items() if not key.startswith("__")):
            continue
        output.append({
            "rowNumber": int(row.get("__row__", 0) or 0),
            "stockCode": normalize_stock_code(get("stock_code")),
            "stockCodeObserved": _text(get("stock_code")),
            "shortName": _text(get("short_name")),
            "equityAsOf": parse_date(get("equity_as_of")),
            "equityNature": nature,
            "legalName": _text(get("legal_name")),
            "homepageObserved": _text(get("homepage")) or None,
            "business": _text(get("business")),
            "listingState": _text(get("listing_state")) or None,
        })
    return output


def _is_mixed_ownership(value: str) -> bool:
    compact = _compact(value)
    return "国企" in compact and compact != "国企"


def _candidate_from_row(row: Mapping[str, Any]) -> tuple[StateOwnedCompanyCandidate | None, dict[str, Any] | None]:
    nature = _text(row.get("equityNature"))
    if _is_mixed_ownership(nature):
        return None, {
            "rowNumber": row.get("rowNumber"),
            "stockCode": row.get("stockCode"),
            "shortName": row.get("shortName"),
            "legalName": row.get("legalName"),
            "equityNature": nature,
            "reason": "mixed_equity_nature_manual_review",
        }
    if nature != "国企":
        return None, None
    legal = _text(row.get("legalName"))
    short = _text(row.get("shortName"))
    stock_code = row.get("stockCode")
    homepage_observed = _text(row.get("homepageObserved")) or None
    homepage_candidates, homepage_reasons = normalize_homepage(homepage_observed)
    review_reasons = list(homepage_reasons)
    if not stock_code:
        review_reasons.append("stock_code_missing_or_invalid")
    if not legal:
        review_reasons.append("legal_name_missing")
    candidate = StateOwnedCompanyCandidate(
        candidateId=candidate_id_for_stock(stock_code, legal, short),
        stockCode=stock_code,
        shortName=short or "未命名企业",
        legalName=legal or short or "未命名企业",
        equityNature=nature,
        equityAsOf=row.get("equityAsOf"),
        listingState=row.get("listingState"),
        homepageObserved=homepage_observed,
        homepageCandidates=homepage_candidates,
        ownershipClass="UNCLASSIFIED_STATE_OWNED",
        parentGroupId=None,
        evidence=[{
            "type": "EQUITY_WORKBOOK",
            "rowNumber": row.get("rowNumber"),
            "asOf": row.get("equityAsOf").isoformat() if isinstance(row.get("equityAsOf"), date) else None,
        }],
        reviewStatus="NEEDS_REVIEW" if review_reasons else "DISCOVERED",
        reviewReasons=list(dict.fromkeys(review_reasons)),
        displayType="未知",
    )
    return candidate, None


def import_equity_nature_xlsx(path: Path) -> WorkbookImport:
    """Import the exact ``股权性质 = 国企`` rows from a workbook."""

    rows = _raw_rows(read_xlsx_rows(path))
    state_rows: list[StateOwnedCompanyCandidate] = []
    review_rows: list[dict[str, Any]] = []
    for row in rows:
        candidate, review = _candidate_from_row(row)
        if candidate is not None:
            state_rows.append(candidate)
        if review is not None:
            review_rows.append(review)
    # ``websiteCount`` follows the workbook's non-empty field count (the
    # promised 1,402). ``validWebsiteCount`` is stricter and excludes the one
    # malformed single-address value as well as the 14 multi-address rows.
    websites = sum(bool(row.homepage_observed) for row in state_rows)
    valid_websites = sum(bool(row.homepage_candidates) for row in state_rows)
    normal_listing = sum(row.listing_state == "正常上市" for row in state_rows)
    dates = sorted({row.equity_as_of.isoformat() for row in state_rows if row.equity_as_of})
    anomaly_count = sum("homepage_multiple_addresses" in row.review_reasons or "homepage_contains_whitespace" in row.review_reasons for row in state_rows)
    summary = {
        "sourceRowCount": len(rows),
        "stateOwnedCount": len(state_rows),
        "mixedOwnershipCount": len(review_rows),
        "websiteCount": websites,
        "validWebsiteCount": valid_websites,
        "missingWebsiteCount": len(state_rows) - websites,
        "normalListingCount": normal_listing,
        "otherListingStateCount": len(state_rows) - normal_listing,
        "equityAsOf": dates[0] if len(dates) == 1 else dates,
        "websiteAnomalyCount": anomaly_count,
        "sourceReadOnly": True,
        "sourceFileName": path.name,
        "sourceSha256": _sha256(path),
    }
    return WorkbookImport(rows=rows, state_owned_rows=state_rows, review_rows=review_rows, summary=summary)


def _company_stock_codes(company: Mapping[str, Any]) -> set[str]:
    values = company.get("stockCodes") or company.get("stock_codes") or []
    if not isinstance(values, list):
        values = [values]
    output: set[str] = set()
    for value in values:
        code = normalize_stock_code(str(value).split(":")[-1])
        if code:
            output.add(code)
    return output


def _company_domains(company: Mapping[str, Any]) -> set[str]:
    values: list[Any] = [company.get("careerUrl"), company.get("homepage"), company.get("website")]
    for key in ("discoveryEvidenceUrls", "officialDomains", "homepageCandidates"):
        raw = company.get(key)
        values.extend(raw if isinstance(raw, list) else [raw])
    return {domain for value in values if (domain := normalized_domain(value))}


def match_company_identity(candidate: StateOwnedCompanyCandidate | Mapping[str, Any], companies: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Match code → exact legal/alias → exact domain, refusing conflicts."""

    row = candidate.model_dump(mode="json", by_alias=True) if isinstance(candidate, BaseModel) else dict(candidate)
    code = normalize_stock_code(row.get("stockCode") or row.get("stock_code"))
    # Keep both legal and short names in the exact-name pass.  A registry may
    # only carry a listed-name alias while the workbook contains the legal
    # name (or the reverse); using ``or`` here would silently discard one of
    # the two keys and make a safe alias match look like a miss.
    names = {
        normalize_identity(row.get("legalName") or row.get("legal_name")),
        normalize_identity(row.get("shortName") or row.get("short_name")),
    }
    names.discard("")
    domains = {domain for value in (row.get("homepageCandidates") or row.get("homepage_candidates") or []) if (domain := normalized_domain(value))}
    code_matches: list[Mapping[str, Any]] = []
    name_matches: list[Mapping[str, Any]] = []
    domain_matches: list[Mapping[str, Any]] = []
    for company in companies:
        company_id = str(company.get("id") or "")
        if not company_id:
            continue
        if code and code in _company_stock_codes(company):
            code_matches.append(company)
        company_names = {normalize_identity(company.get("name")), normalize_identity(company.get("legalName")), *(normalize_identity(value) for value in (company.get("aliases") or []))}
        if names & {value for value in company_names if value}:
            name_matches.append(company)
        if domains & _company_domains(company):
            domain_matches.append(company)
    sets = [code_matches, name_matches, domain_matches]
    non_empty_ids = {str(item.get("id")) for group in sets for item in group}
    if len(non_empty_ids) > 1:
        return {
            "matchedCompanyId": None,
            "matchMethod": "CONFLICT",
            "candidateCompanyIds": sorted(non_empty_ids),
            "reviewReason": "identity_keys_point_to_multiple_companies",
        }
    for method, group in (("STOCK_CODE", code_matches), ("LEGAL_NAME_OR_ALIAS", name_matches), ("OFFICIAL_DOMAIN", domain_matches)):
        ids = {str(item.get("id")) for item in group}
        if len(ids) == 1:
            return {"matchedCompanyId": next(iter(ids)), "matchMethod": method, "candidateCompanyIds": sorted(ids)}
        if len(ids) > 1:
            return {"matchedCompanyId": None, "matchMethod": "CONFLICT", "candidateCompanyIds": sorted(ids), "reviewReason": f"multiple_{method.lower()}_matches"}
    return {"matchedCompanyId": None, "matchMethod": None, "candidateCompanyIds": []}


def _sasac_group_keys(groups: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in groups:
        rank = row.get("rank")
        # Parenthesise the fallback so an explicitly supplied groupId is not
        # lost when a malformed fixture omits/serialises rank as text.
        fallback = f"sasac-central-{int(rank):03d}" if isinstance(rank, int) else ""
        group_id = str(row.get("groupId") or fallback)
        for value in [row.get("name"), *(row.get("aliases") or [])]:
            key = normalize_identity(value)
            if key:
                result[key] = group_id
    return result


def enrich_state_owned_candidates(
    candidates: Iterable[StateOwnedCompanyCandidate],
    companies: Iterable[Mapping[str, Any]],
    sasac_groups: Iterable[Mapping[str, Any]] = (),
) -> list[StateOwnedCompanyCandidate]:
    """Attach safe identity matches and evidence-based central-group labels."""

    company_values = [dict(company) for company in companies if isinstance(company, Mapping)]
    group_keys = _sasac_group_keys(sasac_groups)
    output: list[StateOwnedCompanyCandidate] = []
    for candidate in candidates:
        match = match_company_identity(candidate, company_values)
        reasons = list(candidate.review_reasons)
        status = candidate.review_status
        if match.get("matchMethod") == "CONFLICT":
            status = "NEEDS_REVIEW"
            reasons.append("identity_match_conflict")
        elif match.get("matchedCompanyId"):
            status = "MATCHED_REGISTRY"
        else:
            reasons.append("no_exact_registry_identity_match")
        ownership = candidate.ownership_class
        parent = candidate.parent_group_id
        legal_key = normalize_identity(candidate.legal_name)
        if legal_key in group_keys:
            ownership = "CENTRAL_GROUP"
            parent = group_keys[legal_key]
        company = next((item for item in company_values if str(item.get("id")) == match.get("matchedCompanyId")), None)
        # A subsidiary label is accepted only when the registry already carries
        # an explicit parent and evidence URL.  No relationship is inferred
        # from a similar name, sector, or the fact that a group is in SASAC.
        if company and company.get("parentGroupId") and (company.get("ownershipEvidenceUrls") or company.get("ownershipEvidence")):
            ownership = "CENTRAL_SUBSIDIARY" if str(company.get("ownershipClass") or "").upper() != "LOCAL_STATE_OWNED" else "LOCAL_STATE_OWNED"
            parent = str(company.get("parentGroupId"))
        display_type = "央企" if ownership in {"CENTRAL_GROUP", "CENTRAL_SUBSIDIARY"} else "地方国企" if ownership == "LOCAL_STATE_OWNED" else "未知"
        output.append(candidate.model_copy(update={
            "matchedCompanyId": match.get("matchedCompanyId"),
            "matchMethod": match.get("matchMethod"),
            "candidateCompanyIds": match.get("candidateCompanyIds", []),
            "ownershipClass": ownership,
            "parentGroupId": parent,
            "reviewStatus": status,
            "reviewReasons": list(dict.fromkeys(reasons + ([str(match["reviewReason"])] if match.get("reviewReason") else []))),
            "displayType": display_type,
        }))
    return output


def build_state_owned_candidate_report(
    workbook_path: Path,
    *,
    companies_path: Path | None = None,
    sasac_path: Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    imported = import_equity_nature_xlsx(workbook_path)
    companies: list[dict[str, Any]] = []
    if companies_path and companies_path.exists():
        payload = json.loads(companies_path.read_text(encoding="utf-8"))
        companies = [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    groups: list[dict[str, Any]] = []
    if sasac_path and sasac_path.exists():
        payload = json.loads(sasac_path.read_text(encoding="utf-8"))
        values = payload.get("companies", payload.get("rows", payload)) if isinstance(payload, dict) else payload
        groups = [dict(item) for item in values if isinstance(item, dict)] if isinstance(values, list) else []
    candidates = enrich_state_owned_candidates(imported.state_owned_rows, companies, groups)
    report = {
        "schemaVersion": IMPORT_SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "reportType": "state_owned_company_candidates",
        "discoveryOnly": True,
        "source": {
            "fileName": workbook_path.name,
            "sha256": imported.summary["sourceSha256"],
            "readOnly": True,
            "notCopiedToWebAssets": True,
        },
        "summary": {
            **imported.summary,
            "matchedRegistryCount": sum(bool(row.matched_company_id) for row in candidates),
            "identityConflictCount": sum(row.match_method == "CONFLICT" for row in candidates),
            "centralGroupCount": sum(row.ownership_class == "CENTRAL_GROUP" for row in candidates),
            "centralSubsidiaryCount": sum(row.ownership_class == "CENTRAL_SUBSIDIARY" for row in candidates),
            "localStateOwnedCount": sum(row.ownership_class == "LOCAL_STATE_OWNED" for row in candidates),
            "unclassifiedStateOwnedCount": sum(row.ownership_class == "UNCLASSIFIED_STATE_OWNED" for row in candidates),
        },
        "promotionRule": "Excel股权性质和国资委名录只产生候选；官网反向确认、访问边界、当前届信号、三条岗位抽查和投递域名核验完成前不得登记VERIFIED来源或发布岗位。",
        "reviewQueue": imported.review_rows,
        "candidates": [row.model_dump(mode="json", by_alias=True) for row in candidates],
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# Friendly aliases used by notebooks and future scheduled jobs.
load_state_owned_company_candidates = import_equity_nature_xlsx
parse_equity_nature_xlsx = import_equity_nature_xlsx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only import of exact state-owned listed-company rows from an Excel export.")
    parser.add_argument("--excel", "--input", dest="excel", type=Path, required=True)
    parser.add_argument("--companies", type=Path, default=None)
    parser.add_argument("--sasac", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("artifacts/state-owned-company-candidates.json"))
    args = parser.parse_args(argv)
    report = build_state_owned_candidate_report(args.excel, companies_path=args.companies, sasac_path=args.sasac, output=args.output)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
