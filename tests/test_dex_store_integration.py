import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from cluster_radar.discovery.identity import Candidate, MarketStage
from mochex_radar.dex_store import initialize_dex_store, observation_history, store_observations


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_immutable_history_and_ingestion_cutoff():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_dex_store(dsn)
    now = datetime.now(timezone.utc)
    mint = f"fixture-{uuid4()}"
    item = Candidate(mint, MarketStage.DEX, "pool", None, None, None,
                     Decimal("10000"), Decimal("5000"), "fixture", now - timedelta(days=1))
    try:
        assert store_observations(dsn, [item]) == 1
        assert store_observations(dsn, [item]) == 0
        # Old provider knowledge ingested today cannot appear in yesterday's replay.
        assert observation_history(dsn, mint, now - timedelta(hours=1)) == []
        history = observation_history(dsn, mint, datetime.now(timezone.utc))
        assert len(history) == 1
        assert history[0]["candidate"]["market_cap_usd"] is None
        assert history[0]["candidate"]["fdv_usd"] == "10000"
        with pytest.raises(ValueError, match="conflicting"):
            store_observations(dsn, [replace(item, fdv_usd=Decimal("1"))])
        assert observation_history(dsn, mint, datetime.now(timezone.utc))[0] == history[0]
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM dex_observations WHERE mint=%s", (mint,))
