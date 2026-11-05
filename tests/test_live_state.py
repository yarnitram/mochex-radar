import asyncio
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from mochex_radar.api import app
from mochex_radar.futures_feed import Candle
from mochex_radar.live_state import LiveSnapshots, key
from mochex_radar.websocket_feed import consume
from test_websocket_feed import update

SOL = "cex:mexc-usdt-futures:SOL_USDT"


def candle(now):
    start = datetime.fromtimestamp(int(now.timestamp()) // 900 * 900, timezone.utc)
    return Candle(SOL, "15m", start, start + timedelta(minutes=15), now, Decimal(100), Decimal(110), Decimal(90), Decimal(101), Decimal(1))


@pytest.mark.asyncio
async def test_fresh_stale_future_corrupt_and_missing_are_explicit():
    now = datetime(2026, 11, 5, 12, 5, tzinfo=timezone.utc)
    class Memory:
        raw = None
        async def hget(self, *args):
            return self.raw if SOL in args[0] else None
    memory = Memory()
    live = LiveSnapshots(memory)
    assert (await live.snapshot(now=now))["markets"][0]["status"] == "missing"
    memory.raw = json.dumps(candle(now).to_dict())
    assert (await live.snapshot(now=now))["markets"][0]["status"] == "current"
    assert (await live.snapshot(now=now + timedelta(seconds=30)))["markets"][0]["status"] == "stale"
    for invalid in ("invalid-json", json.dumps(replace(candle(now), retrieved_at=now + timedelta(seconds=1)).to_dict())):
        memory.raw = invalid
        assert (await live.snapshot(now=now))["markets"][0]["status"] == "missing"


@pytest.mark.asyncio
async def test_redis_outage_does_not_prevent_rollover_persistence():
    class Socket:
        async def send(self, message): pass
        def __aiter__(self):
            async def frames():
                start = int(datetime.now(timezone.utc).timestamp() // 900 * 900)
                yield update(start=start - 900)
                yield update(start=start)
            return frames()
    saved, failures = [], []
    async def persist(value): saved.append(value)
    async def failed(value):
        failures.append(value)
        raise RedisError("private connection details")
    await consume(Socket(), persist, failed)
    assert len(saved) == len(failures) == 1


def test_live_api_disabled_and_interval_validation(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/live/core").json()["data_status"] == "live_disabled"
        assert client.get("/api/v1/live/core?interval=1m").status_code == 422
        class Failed:
            async def snapshot(self, *args): raise RedisError("private-connection")
            async def close(self): pass
        app.state.live_store = Failed()
        response = client.get("/api/v1/live/core")
        assert response.status_code == 503 and "private-connection" not in response.text


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="requires temporary Redis")
@pytest.mark.asyncio
async def test_real_redis_atomic_order_expiry_and_empty_restart_state():
    live = LiveSnapshots.from_url(os.environ["TEST_REDIS_URL"])
    now = datetime.now(timezone.utc)
    value = candle(now)
    target = key(SOL, "15m")
    try:
        await live.client.delete(target)
        await asyncio.gather(live.publish(value), live.publish(replace(value, retrieved_at=now - timedelta(microseconds=1))))
        assert not await live.publish(value)
        old_bar = replace(value, open_time=value.open_time - timedelta(minutes=15), close_time=value.close_time - timedelta(minutes=15), retrieved_at=datetime.now(timezone.utc))
        assert not await live.publish(old_bar)
        assert 0 < await live.client.pttl(target) <= 120000
        result = await live.snapshot(now=datetime.now(timezone.utc))
        assert result["markets"][0]["observation"]["retrieved_at"] == value.retrieved_at.isoformat()
        assert result["provisional"] and result["finalized"] is False
        await live.client.pexpire(target, 1)
        await asyncio.sleep(0.02)
        assert (await live.snapshot())["markets"][0]["status"] == "missing"
    finally:
        await live.client.delete(target)
        await live.close()
