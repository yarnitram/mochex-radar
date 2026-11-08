import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from cluster_radar.intelligence.research import FundingEvidence
from mochex_radar.funding_store import (
    funding_history,
    initialize_funding_store,
    store_funding,
)


def test_funding_history_rejects_invalid_cutoff_wallets_and_limits_before_connecting():
    now = datetime.now(timezone.utc)
    for limit in (0, 1001, True):
        with pytest.raises(ValueError):
            funding_history("not-a-dsn", ["wallet-a"], now, limit)
    for bad_wallets in ("", [], [""], ["a"] * 501):
        with pytest.raises(ValueError):
            funding_history("not-a-dsn", bad_wallets, now, 10)
    with pytest.raises(ValueError):
        funding_history("not-a-dsn", ["wallet-a"], datetime.now())


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_immutable_funding_roundtrip_cutoffs_and_conflict():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_funding_store(dsn)
    now = datetime.now(timezone.utc)
    wallet = "wallet-" + uuid4().hex
    funding = FundingEvidence(
        wallet=wallet,
        funder="funder-1",
        signature="sig-1",
        event_at=now - timedelta(hours=2),
        known_at=now - timedelta(hours=1),
        label="NON_CEX",
        label_known_at=now - timedelta(hours=1),
        source="fixture",
    )
    try:
        store_funding(dsn, funding)
        store_funding(dsn, funding)
        assert funding_history(dsn, wallet, now - timedelta(minutes=30)) == []
        cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
        assert funding_history(dsn, [wallet], cutoff) == [funding]
        with pytest.raises(ValueError, match="conflicting"):
            store_funding(dsn, replace(funding, label="CEX"))
        store_funding(dsn, replace(funding, signature="sig-2"))
        with pytest.raises(ValueError, match="exceeds limit"):
            funding_history(dsn, wallet, datetime.now(timezone.utc) + timedelta(seconds=1), 1)
        future = replace(funding, signature="sig-future", known_at=now + timedelta(days=1))
        store_funding(dsn, future)
        assert len(funding_history(dsn, wallet, datetime.now(timezone.utc) + timedelta(seconds=1))) == 2
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM normalized_funding_observations WHERE wallet=%s", (wallet,))
