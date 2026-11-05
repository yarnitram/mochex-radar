import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from mochex_radar.dashboard import core_snapshot
from mochex_radar.futures_feed import Candle
from mochex_radar.storage import initialize_database, store_stream_candle


def test_disabled_storage_still_shows_seven_pairs_without_invented_prices():
    snapshot = core_snapshot(None)
    assert len(snapshot["markets"]) == 7
    assert snapshot["data_status"] == "storage_disabled"
    assert all(m["close"] is None and m["status"] == "missing" for m in snapshot["markets"])


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_stored_snapshot_freshness_and_decimal_return():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_database(dsn)
    now = datetime.now(timezone.utc)
    candle = Candle("cex:mexc-usdt-futures:SOL_USDT", "15m", now - timedelta(minutes=15), now,
                    now, Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101"), Decimal("1"))
    try:
        store_stream_candle(dsn, candle)
        market = next(m for m in core_snapshot(dsn, now)["markets"] if m["base"] == "SOL")
        assert market["close"] == "101"
        assert market["candle_return"] == "0.01"
        assert market["status"] == "current"
        assert next(m for m in core_snapshot(dsn, now + timedelta(hours=1))["markets"] if m["base"] == "SOL")["status"] == "stale"
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM market_candles WHERE market_id=%s AND open_time=%s", ("SOL_USDT", candle.open_time))
