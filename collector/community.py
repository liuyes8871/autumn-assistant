from __future__ import annotations

"""Privacy boundary for optional community discovery leads.

Community search results can contain personal referral codes, tracking URLs or
session artefacts even when the upstream command intends to omit them.  The
public artifact therefore passes through this allow-list before it is read by
the collector or served by Pages.  The helper is intentionally deterministic
and does not inspect or recover values from removed fields.
"""

from typing import Any


PUBLIC_LEAD_KEYS = (
    "id",
    "companyId",
    "companyName",
    "title",
    "officialUrl",
    "officialUrlVerified",
    "sourceUrl",
    "sourcePlatform",
    "sourceAuthorLabel",
    "publishedAt",
    "discoveredAt",
    "verificationStatus",
    "note",
)


def sanitize_community_lead(value: Any) -> dict[str, Any] | None:
    """Return only public, non-referral fields from one lead record."""

    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in PUBLIC_LEAD_KEYS if key in value}
    # A public lead without a stable id, title or source link is not useful
    # and should not be exposed as a partially parsed record.
    if not str(result.get("id") or "").strip() or not str(result.get("title") or "").strip() or not str(result.get("sourceUrl") or "").strip():
        return None
    # The source is currently fixed to Xiaohongshu.  Do not let an arbitrary
    # value from an old artifact turn into a new public integration.
    if result.get("sourcePlatform") not in (None, "xiaohongshu"):
        return None
    return result


def sanitize_community_catalog(value: Any) -> dict[str, Any]:
    """Strip referral/session fields from a community-leads catalog."""

    payload = value if isinstance(value, dict) else {}
    leads = [clean for item in payload.get("leads", []) if (clean := sanitize_community_lead(item))]
    privacy_value = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    privacy = {
        "cookiesPersisted": False,
        "xsecTokensPersisted": False,
        "privateContentIncluded": False,
        "referralCodesPersisted": False,
        "disclaimer": "仅保存公开搜索结果的脱敏企业入口线索；社区帖子不等同于企业官方信息，个人内推码不会写入公共目录。",
    }
    # Preserve harmless query/error metadata for auditability, but never copy
    # an internal stack or arbitrary nested response object into Pages.
    queries = [str(item)[:200] for item in payload.get("queries", []) if isinstance(item, str)][:50]
    errors: list[dict[str, str]] = []
    for item in payload.get("errors", []) if isinstance(payload.get("errors"), list) else []:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "")[:200]
        message = str(item.get("message") or "")[:300]
        if query or message:
            errors.append({"query": query, "message": message})
    return {
        "schemaVersion": int(payload.get("schemaVersion", 1) or 1),
        "generatedAt": str(payload.get("generatedAt") or ""),
        "source": "xiaohongshu_opencli",
        "privacy": privacy,
        "queries": queries,
        "errors": errors,
        "leads": leads,
    }
