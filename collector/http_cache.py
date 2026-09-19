from __future__ import annotations

"""Small, file-friendly HTTP validator cache for public source requests.

The collector intentionally keeps this cache as plain JSON metadata.  It is
not a response cache: response bodies, cookies and authentication headers are
never persisted.  A cache entry only lets a public endpoint answer ``304`` and
lets the next run avoid re-requesting unchanged detail pages.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Any, Mapping


@dataclass
class CacheEntry:
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    fetched_at: str | None = None
    status_code: int | None = None
    item_count: int | None = None

    @classmethod
    def from_value(cls, value: Any) -> "CacheEntry":
        if not isinstance(value, Mapping):
            return cls()
        # State files from earlier runs used camelCase, while response
        # metadata naturally uses lower-case header names.  Treat these forms
        # as equivalent so a harmless migration never loses validators.
        normalised = {
            str(key).casefold().replace("-", "_"): raw
            for key, raw in value.items()
        }

        def text(*keys: str) -> str | None:
            raw = next((normalised.get(key.casefold().replace("-", "_")) for key in keys if key.casefold().replace("-", "_") in normalised), None)
            return str(raw).strip()[:256] if raw not in (None, "") else None
        status = normalised.get("statuscode", normalised.get("status_code"))
        try:
            status_int = int(status) if status is not None and not isinstance(status, bool) else None
        except (TypeError, ValueError):
            status_int = None
        count = normalised.get("itemcount", normalised.get("item_count"))
        try:
            count_int = int(count) if count is not None and not isinstance(count, bool) and int(count) >= 0 else None
        except (TypeError, ValueError):
            count_int = None
        return cls(
            etag=text("etag"),
            last_modified=text("lastModified", "last_modified", "last-modified"),
            content_hash=text("contentHash", "content_hash"),
            fetched_at=text("fetchedAt", "fetched_at"),
            status_code=status_int,
            item_count=count_int,
        )

    def request_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        return headers

    def to_json(self) -> dict[str, Any]:
        return {
            "etag": self.etag,
            "lastModified": self.last_modified,
            "contentHash": self.content_hash,
            "fetchedAt": self.fetched_at,
            "statusCode": self.status_code,
            "itemCount": self.item_count,
        }


def response_headers(response: Any) -> dict[str, str]:
    raw = getattr(response, "headers", None)
    if raw is None:
        return {}
    try:
        return {str(key).lower(): str(value) for key, value in raw.items() if value not in (None, "")}
    except AttributeError:
        return {}


def response_content_hash(response: Any) -> str | None:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return hashlib.sha256(content).hexdigest()
    return None


def update_entry(
    previous: CacheEntry | Mapping[str, Any] | None,
    response: Any,
    *,
    item_count: int | None = None,
    now: datetime | None = None,
) -> CacheEntry:
    """Merge validators from a response without persisting its body."""

    old = previous if isinstance(previous, CacheEntry) else CacheEntry.from_value(previous)
    headers = response_headers(response)
    status = getattr(response, "status_code", None)
    try:
        status_int = int(status) if status is not None else old.status_code
    except (TypeError, ValueError):
        status_int = old.status_code
    return CacheEntry(
        etag=headers.get("etag") or old.etag,
        last_modified=headers.get("last-modified") or old.last_modified,
        content_hash=response_content_hash(response) or old.content_hash,
        fetched_at=(now or datetime.now(UTC)).isoformat(),
        status_code=status_int,
        item_count=item_count if item_count is not None else old.item_count,
    )


def load_cache(payload: Any) -> dict[str, CacheEntry]:
    """Load and sanitize a ``sourceId -> validator`` mapping."""

    if not isinstance(payload, Mapping):
        return {}
    if "sourceValidators" not in payload and "sourceCache" not in payload:
        return {}
    values = payload.get("sourceValidators", payload.get("sourceCache", {}))
    if not isinstance(values, Mapping):
        return {}
    return {str(key): CacheEntry.from_value(value) for key, value in values.items() if str(key).strip()}


def dump_cache(values: Mapping[str, CacheEntry | Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(key): (value.to_json() if isinstance(value, CacheEntry) else CacheEntry.from_value(value).to_json())
        for key, value in values.items()
        if str(key).strip()
    }
