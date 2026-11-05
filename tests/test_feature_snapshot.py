import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from mochex_radar.api import app
from mochex_radar.feature_snapshot import core_feature_snapshot
from mochex_radar.futures_feed import Candle
from mochex_radar.storage import initialize_database, recent_candles, store_stream_candle

STEP = timedelta(minutes=15)
START = datetime(2026, 1, 1, tzinfo=UTC)


def series(market_id, count=25, base=100):
    out = []
    for i in range(count):
        t = START + i * STEP
        p = Decimal(base) + i
        out.append(Candle(f"cex:mexc-usdt-futures:{market_id}", "15m", t, t + STEP, t + STEP, p, p + 2, p - 1, p + 1, Decimal(10)))
    return out


NOW = START + 25 * STEP + timedelta(seconds=5)


def test_storage_disabled_lists_seven_unavailable_pairs_without_invented_values():
    snap = core_feature_snapshot(None, "15m", NOW)
    assert snap["data_status"] == "storage_disabled" and len(snap["markets"]) == 7
    assert snap["signals_enabled"] is False and snap["research_only"] is True
    assert all(m["status"] == "unavailable" and all(v is None for v in m["features"].values()) for m in snap["markets"])


def test_snapshot_uses_loader_per_pair_and_isolates_missing_pairs():
    data = {m: series(m) for m in ("BTC_USDT", "SOL_USDT", "XRP_USDT")}
    calls = []

    def load(market_id, interval, as_of, limit):
        calls.append((market_id, interval, limit))
        return [c for c in data.get(market_id, []) if c.close_time <= as_of]

    snap = core_feature_snapshot(load, "15m", NOW)
    status = {m["base"]: m["status"] for m in snap["markets"]}
    assert status["SOL"] == status["XRP"] == "ok" and status["DOGE"] == "unavailable"
    assert snap["markets"][0]["features"]["relative_strength"] is not None
    assert sum(1 for c in calls if c[0] == "BTC_USDT") == 1 and all(c[2] == 21 for c in calls)


def test_snapshot_rejects_bad_interval_and_naive_time():
    with pytest.raises(ValueError, match="interval"):
        core_feature_snapshot(None, "5m", NOW)
    with pytest.raises(ValueError, match="UTC"):
        core_feature_snapshot(None, "15m", datetime(2026, 1, 1))


def test_api_endpoint_without_database_and_with_invalid_interval(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    body = client.get("/api/v1/features/core").json()
    assert body["data_status"] == "storage_disabled" and len(body["markets"]) == 7
    assert client.get("/api/v1/features/core?interval=1h").json()["interval"] == "1h"
    assert client.get("/api/v1/features/core?interval=5m").status_code == 422


def test_api_reports_database_failure_as_503(monkeypatch):
    def broken(*args, **kwargs):
        raise psycopg.OperationalError("down")

    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid")
    monkeypatch.setattr("mochex_radar.api.recent_candles", broken)
    assert TestClient(app).get("/api/v1/features/core").status_code == 503


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_recent_candles_respects_close_retrieval_and_limit():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_database(dsn)
    base = datetime(2030, 1, 1, tzinfo=UTC)
    candles = [Candle("cex:mexc-usdt-futures:TESTFEAT_USDT", "15m", base + i * STEP, base + (i + 1) * STEP,
                      base + (i + 1) * STEP + timedelta(seconds=1), Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(1))
               for i in range(5)]
    try:
        for c in candles:
            store_stream_candle(dsn, c)
        got = recent_candles(dsn, "TESTFEAT_USDT", "15m", base + 4 * STEP + timedelta(seconds=1), limit=3)
        assert [c.open_time for c in got] == [base + i * STEP for i in (1, 2, 3)]
        assert got[-1].close_time <= base + 4 * STEP and got == sorted(got, key=lambda c: c.open_time)
        with pytest.raises(ValueError):
            recent_candles(dsn, "TESTFEAT_USDT", "15m", base, limit=0)
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM market_candles WHERE market_id=%s", ("TESTFEAT_USDT",))
