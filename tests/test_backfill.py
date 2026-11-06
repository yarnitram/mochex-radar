import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import psycopg
import pytest

from mochex_radar.backfill import MAX_CANDLES, backfill
from mochex_radar.futures_feed import Candle, FeedUnavailable, fetch_history, parse_closed_history
from mochex_radar.markets import CexMarket, core_markets
from mochex_radar.storage import initialize_database, recent_candles, store_candles

SOL = CexMarket("mexc-usdt-futures", "SOL_USDT", "SOL", "USDT")
NOW = datetime(2026, 1, 1, 12, 7, tzinfo=UTC)


def payload(count=6, step=900, end=None, **overrides):
    end = end or NOW
    last_open = int((end - timedelta(seconds=step)).timestamp()) // step * step
    times = [last_open - i * step for i in reversed(range(count))]
    data = {"time": times, "open": [10] * count, "high": [12] * count, "low": [9] * count,
            "close": [11] * count, "vol": [5] * count}
    data.update(overrides)
    return data


def test_history_returns_closed_candles_oldest_first_and_bounded():
    data = payload(6)
    data["time"].append(data["time"][-1] + 900)  # candle still open at NOW
    for key in ("open", "high", "low", "close", "vol"):
        data[key].append(data[key][-1])
    candles = parse_closed_history(data, SOL, "15m", NOW, 4)
    assert len(candles) == 4 and candles == sorted(candles, key=lambda c: c.open_time)
    assert all(c.close_time <= NOW and c.retrieved_at == NOW and c.asset_id == SOL.asset_id for c in candles)
    assert candles[-1].open_time == datetime.fromtimestamp(payload(6)["time"][-1], UTC)


@pytest.mark.parametrize("change", [
    {"high": [12, 12, 12, 12, 12, 8]},                      # high below close
    {"vol": [5, 5, 5, 5, 5, -1]},
    {"open": [10, 10, 10, 10, 10, 0]},
    {"close": [11, 11, 11, 11, 11, "x"]},
    {"vol": [5, 5, 5]},                                      # misaligned
])
def test_invalid_history_is_rejected_entirely(change):
    with pytest.raises(ValueError):
        parse_closed_history(payload(6, **change), SOL, "15m", NOW, 10)


def test_duplicate_and_stale_and_empty_history_rejected():
    data = payload(3)
    data["time"][1] = data["time"][0]
    with pytest.raises(ValueError, match="duplicate"):
        parse_closed_history(data, SOL, "15m", NOW, 10)
    with pytest.raises(ValueError, match="stale"):
        parse_closed_history(payload(3, end=NOW - timedelta(hours=2)), SOL, "15m", NOW, 10)
    with pytest.raises(ValueError):
        parse_closed_history({"time": [], "open": [], "high": [], "low": [], "close": [], "vol": []}, SOL, "15m", NOW, 10)


@pytest.mark.asyncio
async def test_fetch_history_uses_bounded_window_and_maps_failures():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        end = datetime.fromtimestamp(int(request.url.params["end"]), UTC)
        return httpx.Response(200, json={"success": True, "code": 0, "data": payload(24, end=end)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        candles = await fetch_history(SOL, "15m", client, 24)
        assert len(candles) == 24 and int(seen["end"]) - int(seen["start"]) == 900 * 26
        for bad in (0, 101):
            with pytest.raises(ValueError):
                await fetch_history(SOL, "15m", client, bad)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        with pytest.raises(FeedUnavailable):
            await fetch_history(SOL, "15m", client, 5)
    reject = httpx.MockTransport(lambda r: httpx.Response(200, json={"success": False, "code": 1}))
    async with httpx.AsyncClient(transport=reject) as client:
        with pytest.raises(FeedUnavailable):
            await fetch_history(SOL, "15m", client, 5)


def candle(market, interval, minutes):
    t = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)
    return Candle(market.asset_id, interval, t, t + timedelta(minutes=15), NOW, Decimal(1), Decimal(2), Decimal(1), Decimal(1), Decimal(1))


@pytest.mark.asyncio
async def test_backfill_visits_all_fifteen_targets_isolates_failures_and_persists_once():
    visited, saved = [], []

    async def fetch(market, interval, client, count):
        visited.append((market.market_id, interval, count))
        if market.market_id == "XRP_USDT" and interval == "1h":
            raise FeedUnavailable("offline")
        return [candle(market, interval, 0), candle(market, interval, 15)]

    async def persist(candles):
        saved.append(len(candles))
        return len(candles) - 1

    pauses = []

    async def pause(seconds):
        pauses.append(seconds)

    async with httpx.AsyncClient() as client:
        result = await backfill(client, persist, 24, fetch=fetch, pause=pause)
    assert len(set(visited)) == 16 and all(v[2] == 24 for v in visited) and len(pauses) == 15
    assert ("BTC_USDT", "1h", 24) in visited
    assert saved == [30] and (result.targets, result.fetched, result.stored, result.failures) == (16, 30, 29, 1)
    assert len(core_markets()) == 7


@pytest.mark.asyncio
async def test_backfill_bounds_and_all_failed_does_not_persist():
    async def fail(market, interval, client, count):
        raise FeedUnavailable("offline")

    async def persist(candles):
        raise AssertionError("nothing to persist")

    async with httpx.AsyncClient() as client:
        result = await backfill(client, persist, 5, fetch=fail, pause=lambda s: _noop())
        assert result.failures == 16 and result.stored == 0
        for bad in (0, MAX_CANDLES + 1):
            with pytest.raises(ValueError):
                await backfill(client, persist, bad, fetch=fail)


async def _noop():
    return None


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_store_candles_is_idempotent_and_writes_no_cycle_record():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_database(dsn)
    market = CexMarket("mexc-usdt-futures", "TESTFILL_USDT", "TESTFILL", "USDT")
    rows = [candle(market, "15m", m) for m in (0, 15, 30)]
    try:
        with psycopg.connect(dsn) as conn:
            before = conn.execute("SELECT count(*) FROM collector_cycles").fetchone()[0]
        assert store_candles(dsn, rows) == 3 and store_candles(dsn, rows) == 0
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT count(*) FROM collector_cycles").fetchone()[0] == before
        assert len(recent_candles(dsn, "TESTFILL_USDT", "15m", NOW + timedelta(hours=1))) == 3
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM market_candles WHERE market_id=%s", ("TESTFILL_USDT",))
