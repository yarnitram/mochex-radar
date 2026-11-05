import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from cluster_radar.providers.dexscreener import BudgetExceeded
from mochex_radar.provider_budget import initialize_budget_store, reserve_request


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_shared_durable_limit_pacing_and_utc_rollover():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_budget_store(dsn)
    provider = f"fixture-{uuid4()}"

    def reserve_until_done():
        while True:
            try:
                delay = reserve_request(dsn, 2, provider=provider)
                if not delay:
                    return "reserved"
                time.sleep(delay)
            except BudgetExceeded:
                return "exhausted"

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: reserve_until_done(), range(4)))
        assert results.count("reserved") == 2
        assert results.count("exhausted") == 2
        # A new connection/process still sees the exhausted durable budget.
        with pytest.raises(BudgetExceeded):
            reserve_request(dsn, 2, provider=provider)
        with psycopg.connect(dsn) as conn:
            conn.execute("""UPDATE provider_request_budgets SET budget_day=DATE '2000-01-01',
                         next_request_at=TIMESTAMPTZ '2000-01-01 00:00:00+00' WHERE provider=%s""", (provider,))
        assert reserve_request(dsn, 2, provider=provider) == 0
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT used FROM provider_request_budgets WHERE provider=%s", (provider,)).fetchone()[0] == 1
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM provider_request_budgets WHERE provider=%s", (provider,))
