import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from cluster_radar.intelligence.research import Swap
from mochex_radar.swap_store import initialize_swap_store, store_swap, swap_history


def test_history_rejects_invalid_cutoff_and_limits_before_connecting():
    for limit in (0, 1001, True):
        with pytest.raises(ValueError):
            swap_history("not-a-dsn", "mint", datetime.now(timezone.utc), limit)
    with pytest.raises(ValueError):
        swap_history("not-a-dsn", "mint", datetime.now())


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
@pytest.mark.parametrize("instruction_path", [(0,), (40000,), (0, 1)])
def test_immutable_roundtrip_cutoffs_and_overflow(instruction_path):
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_swap_store(dsn)
    now = datetime.now(timezone.utc)
    mint = "test-" + uuid4().hex
    swap = Swap("sig", instruction_path, 0, mint, "pool", "owner", "BUY", Decimal(2),
                None, now - timedelta(hours=2), now - timedelta(hours=1), "fixture")
    try:
        store_swap(dsn, swap)
        store_swap(dsn, swap)
        assert swap_history(dsn, mint, now - timedelta(minutes=30)) == []
        cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
        assert swap_history(dsn, mint, cutoff) == [swap]
        with pytest.raises(ValueError, match="conflicting"):
            store_swap(dsn, replace(swap, token_amount=Decimal(3)))
        store_swap(dsn, replace(swap, signature="sig2"))
        with pytest.raises(ValueError, match="exceeds limit"):
            swap_history(dsn, mint, datetime.now(timezone.utc) + timedelta(seconds=1), 1)
        future = replace(swap, signature="future", known_at=now + timedelta(days=1))
        store_swap(dsn, future)
        assert len(swap_history(dsn, mint, datetime.now(timezone.utc) + timedelta(seconds=1))) == 2
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM normalized_swap_observations WHERE mint=%s", (mint,))
