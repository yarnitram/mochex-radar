import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from cluster_radar.discovery.identity import Candidate, MarketStage
from mochex_radar.dex_worker import WatchToken, initialize_scan_store, recent_scans, store_scan


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_scan_and_observations_commit_atomically():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_scan_store(dsn)
    now = datetime.now(timezone.utc)
    token = WatchToken(mint="B" * 32, categories=["meme"], category_source="operator:fixture")
    scan_id = uuid4()
    candidate = Candidate(token.mint, MarketStage.DEX, str(uuid4()), None, None,
                          None, None, None, "fixture", now)
    try:
        store_scan(dsn, token, scan_id, now, now, "success", [candidate])
        scans = [row for row in recent_scans(dsn) if row["id"] == scan_id]
        assert scans[0]["categories"] == ["meme"]
        assert scans[0]["pool_count"] == 1
        # Duplicate audit identity fails after inserting a new observation; both roll back.
        with pytest.raises(psycopg.errors.UniqueViolation):
            store_scan(dsn, token, scan_id, now, now, "success",
                       [replace(candidate, known_at=now + timedelta(seconds=1))])
        with psycopg.connect(dsn) as conn:
            count = conn.execute("SELECT count(*) FROM dex_observations WHERE pool_id=%s",
                                 (candidate.pool_id,)).fetchone()[0]
        assert count == 1
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM dex_scans WHERE id=%s", (scan_id,))
            conn.execute("DELETE FROM dex_observations WHERE pool_id=%s", (candidate.pool_id,))
