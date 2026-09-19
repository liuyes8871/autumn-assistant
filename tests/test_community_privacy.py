from __future__ import annotations

from collector.community import sanitize_community_catalog


def test_legacy_referral_fields_are_removed_from_public_leads() -> None:
    payload = sanitize_community_catalog({
        "schemaVersion": 1,
        "generatedAt": "2026-09-08T00:00:00Z",
        "source": "xiaohongshu_opencli",
        "leads": [{
            "id": "xhs:1",
            "title": "某公司 2027 校招",
            "sourceUrl": "https://www.xiaohongshu.com/explore/1",
            "sourcePlatform": "xiaohongshu",
            "referralCode": "secret",
            "referralUrl": "https://example.test/ref",
            "xsecToken": "secret",
        }],
    })
    assert payload["privacy"]["referralCodesPersisted"] is False
    assert payload["leads"] == [{
        "id": "xhs:1",
        "title": "某公司 2027 校招",
        "sourceUrl": "https://www.xiaohongshu.com/explore/1",
        "sourcePlatform": "xiaohongshu",
    }]
    assert "referralCode" not in payload["leads"][0]
    assert "xsecToken" not in payload["leads"][0]

