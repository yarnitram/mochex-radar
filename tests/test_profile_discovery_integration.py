import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from cluster_radar.providers.profiles import ProfileBatch, SOURCE
from mochex_radar.profile_discovery import discovered_catalog, initialize_discovery_store, persist_discovery_scan, select_targets, store_poll
from mochex_radar.provider_budget import reserve_request


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_discovery_retains_unselected_mints_and_rotates_atomic_scan_progress():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_discovery_store(dsn)
    now = datetime.now(timezone.utc)
    identity = uuid4()
    # Base58-shaped isolated fixture identifiers; never sent to a provider.
    mint1 = "A" + str(uuid4().int).replace("0", "1")[:31].ljust(31, "1")
    mint2 = "B" + mint1[1:]
    batch = ProfileBatch((mint1, mint2), now, "hash1", 2)
    scan = uuid4()
    failure = uuid4()
    budget_key = f"fixture-profile:{uuid4()}"
    try:
        store_poll(dsn, identity, now, now, "success", batch)
        store_poll(dsn, identity, now, now, "success", batch)
        with pytest.raises(ValueError, match="conflicting"):
            store_poll(dsn, identity, now, now, "success", replace(batch, response_hash="hash2"))
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT count(*) FROM profile_observations WHERE poll_id=%s", (identity,)).fetchone()[0] == 2
        catalog = [row for row in discovered_catalog(dsn) if row["mint"] in batch.mints]
        assert len(catalog) == 2
        assert all(row["first_ingested_at"] >= row["first_known_at"] for row in catalog)
        target = select_targets(dsn, identity, 1)[0]
        assert target.categories == ["unclassified"]
        persist_discovery_scan(dsn, target, scan, now, now, "empty", [])
        assert select_targets(dsn, identity, 1)[0].mint != target.mint
        # A duplicate audit ID must roll back the progress timestamp too.
        with pytest.raises(psycopg.errors.UniqueViolation):
            persist_discovery_scan(dsn, target, scan, now, now + timedelta(seconds=1), "empty", [])
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT last_scan_at FROM discovered_mints WHERE mint=%s AND source=%s", (target.mint, SOURCE)).fetchone()[0] == now
        store_poll(dsn, failure, now, now, "provider_error", None)
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT discovered_count FROM profile_polls WHERE id=%s", (failure,)).fetchone()[0] is None
        with psycopg.connect(dsn) as conn:
            before = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        assert reserve_request(dsn, 10, provider=budget_key, spacing_seconds=1.1) == 0
        with psycopg.connect(dsn) as conn:
            next_at, after = conn.execute("SELECT next_request_at,clock_timestamp() FROM provider_request_budgets WHERE provider=%s", (budget_key,)).fetchone()
            assert before + timedelta(seconds=1.1) <= next_at <= after + timedelta(seconds=1.1)
            conn.execute("UPDATE provider_request_budgets SET next_request_at=clock_timestamp()+interval '5 seconds' WHERE provider=%s", (budget_key,))
        assert reserve_request(dsn, 10, provider=budget_key, spacing_seconds=1.1) > 0
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM profile_observations WHERE poll_id=ANY(%s)", ([identity, failure],))
            conn.execute("DELETE FROM profile_polls WHERE id=ANY(%s)", ([identity, failure],))
            conn.execute("DELETE FROM discovered_mints WHERE mint=ANY(%s)", ([mint1,mint2],))
            conn.execute("DELETE FROM dex_scans WHERE id=%s", (scan,))
            conn.execute("DELETE FROM provider_request_budgets WHERE provider=%s", (budget_key,))
