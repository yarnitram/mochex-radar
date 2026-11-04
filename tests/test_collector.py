from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from mochex_radar.collector import collect_once
from mochex_radar.futures_feed import Candle, FeedUnavailable


@pytest.mark.asyncio
async def test_collects_all_targets_despite_one_provider_failure() -> None:
    visited = []
    pauses = []
    stored = []

    async def fetch(market, interval, client):
        visited.append((market.market_id, interval))
        if market.market_id == "XRP_USDT" and interval == "1h":
            raise FeedUnavailable("offline")
        now = datetime.now(timezone.utc)
        return Candle(market.asset_id, interval, now, now, now, Decimal(1), Decimal(1), Decimal(1), Decimal(1), Decimal(0))

    async def save(candles, started, finished, failures):
        stored.extend(candles)
        assert failures == 1
        assert finished >= started
        return len(candles)

    async def pause(seconds):
        pauses.append(seconds)

    async with httpx.AsyncClient() as client:
        result = await collect_once(client, save, fetch=fetch, pause=pause)
    assert len(visited) == 15
    assert len(set(visited)) == 15
    assert ("BTC_USDT", "15m") in visited
    assert len(pauses) == 14 and all(item == 0.15 for item in pauses)
    assert len(stored) == 14
    assert result.provider_failures == 1 and result.stored_count == 14


@pytest.mark.asyncio
async def test_persistence_failure_propagates() -> None:
    async def fetch(market, interval, client):
        now = datetime.now(timezone.utc)
        return Candle(market.asset_id, interval, now, now, now, Decimal(1), Decimal(1), Decimal(1), Decimal(1), Decimal(0))

    async def save(*args):
        raise RuntimeError("database unavailable")

    async def pause(seconds):
        pass

    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="database unavailable"):
            await collect_once(client, save, fetch=fetch, pause=pause)
