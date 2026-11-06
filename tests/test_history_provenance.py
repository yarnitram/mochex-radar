from datetime import datetime, timedelta, timezone

import pytest

from mochex_radar.history_provenance import HistoryProvenance


def make(**changes):
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    return HistoryProvenance(**{**dict(source="fixture", parser_version="v1", wallet="wallet",
        window_start=now - timedelta(hours=1), window_end=now, retrieved_at=now,
        raw_sha256="a" * 64, pagination_exhausted=True), **changes})


def test_pagination_exhaustion_does_not_certify_history():
    result = make().envelope()
    assert result["completeness"] == "unverified"
    assert result["signals_enabled"] is False
    assert result == make().envelope()
    assert result["batch_id"] != make(parser_version="v2").envelope()["batch_id"]


def test_rejects_unsupported_verification_and_invalid_hash():
    for changes in ({"coverage_verified": True}, {"raw_sha256": "bad"}, {"pagination_exhausted": 1}):
        with pytest.raises(ValueError):
            make(**changes)
