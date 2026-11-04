import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from mochex_radar.futures_feed import Candle
from mochex_radar.storage import initialize_database, latest_cycle, store_cycle


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_idempotent_candle_storage_and_cycle_status() -> None:
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_database(dsn)
    now = datetime.now(timezone.utc)
    candle = Candle("cex:mexc-usdt-futures:TEST_USDT", "15m", now - timedelta(minutes=15), now,
                    now, Decimal("1"), Decimal("2"), Decimal("0.5"), Decimal("1.5"), Decimal("10"))
    try:
        assert store_cycle(dsn, [candle], now, now, 0) == 1
        assert store_cycle(dsn, [candle], now, now, 0) == 0
        assert latest_cycle(dsn)["stored_count"] == 0
        with psycopg.connect(dsn) as conn:
            row = conn.execute("SELECT count(*), max(close_price) FROM market_candles WHERE market_id = %s", ("TEST_USDT",)).fetchone()
        assert row == (1, Decimal("1.5"))
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM market_candles WHERE market_id = %s", ("TEST_USDT",))
            conn.execute("DELETE FROM collector_cycles WHERE started_at = %s", (now,))
