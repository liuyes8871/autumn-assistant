from __future__ import annotations

"""User-initiated local job inbox for sources without a public feed.

This is deliberately an import boundary, not a browser automation feature.
The user supplies a copied JSON record or a bookmarklet export.  Credentials,
cookies, headers and arbitrary page HTML are discarded before the record is
written to disk.
"""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .normalize import clean_list, clean_text


MAX_DESCRIPTION = 12_000
DISALLOWED_KEYS = {
    "cookie", "cookies", "token", "access_token", "authorization", "password", "passwd",
    "headers", "session", "sessionid", "captcha", "html", "responsebody", "rawhtml",
}


def _https_url(value: Any) -> str | None:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return text[:2048]


def sanitize_inbox_entry(value: Any, *, imported_at: datetime | None = None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if any(str(key).casefold() in DISALLOWED_KEYS for key in value):
        # Drop sensitive keys rather than rejecting an otherwise useful user
        # record.  The resulting artifact contains only the allow-list below.
        pass
    title = clean_text(str(value.get("title") or value.get("jobTitle") or ""), 240)
    company = clean_text(str(value.get("companyName") or value.get("company") or ""), 240)
    apply_url = _https_url(value.get("applyUrl") or value.get("url") or value.get("jobUrl"))
    source_url = _https_url(value.get("sourceUrl") or value.get("careerUrl") or apply_url)
    if not title or not company or not apply_url or not source_url:
        return None
    requirements_value = value.get("requirements") or value.get("qualifications") or []
    if isinstance(requirements_value, str):
        requirements = [requirements_value]
    elif isinstance(requirements_value, list):
        requirements = [str(item) for item in requirements_value if item not in (None, "")]
    else:
        requirements = []
    now = imported_at or datetime.now(UTC)
    return {
        "id": clean_text(str(value.get("id") or value.get("jobId") or apply_url), 240),
        "title": title,
        "companyName": company,
        "city": clean_text(str(value.get("city") or value.get("location") or "未知"), 160) or "未知",
        "description": clean_text(str(value.get("description") or ""), MAX_DESCRIPTION),
        "requirements": clean_list(requirements),
        "applyUrl": apply_url,
        "sourceUrl": source_url,
        "importedAt": now.isoformat(),
        "source": "USER_IMPORTED_LOCAL_INBOX",
    }


def load_inbox(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("entries", payload) if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        return []
    output: list[dict[str, Any]] = []
    for item in values:
        clean = sanitize_inbox_entry(item)
        if clean and clean["id"] not in {entry["id"] for entry in output}:
            output.append(clean)
    return output


def import_inbox(input_path: Path, output_path: Path, *, append: bool = True) -> dict[str, int]:
    incoming = load_inbox(input_path)
    existing = load_inbox(output_path) if append and output_path.exists() else []
    by_id = {entry["id"]: entry for entry in existing}
    for entry in incoming:
        by_id[entry["id"]] = entry
    result = sorted(by_id.values(), key=lambda entry: (entry.get("importedAt", ""), entry.get("companyName", ""), entry.get("title", "")), reverse=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"schemaVersion": 1, "updatedAt": datetime.now(UTC).isoformat(), "entries": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"inputCount": len(incoming), "existingCount": len(existing), "outputCount": len(result)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import user-selected public job links into a local inbox.")
    parser.add_argument("--input", type=Path, required=True, help="JSON export containing user-selected jobs")
    parser.add_argument("--output", type=Path, default=Path("collector/local-inbox.json"))
    parser.add_argument("--replace", action="store_true", help="replace the inbox instead of merging by id")
    args = parser.parse_args(argv)
    print(json.dumps(import_inbox(args.input, args.output, append=not args.replace), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

