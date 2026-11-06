"""MEXC public futures kline stream; only rollover-finalized candles are stored."""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from mochex_radar.futures_feed import Candle, INTERVALS, _decimal, fetch_latest_closed
from mochex_radar.markets import CexMarket, btc_context_market, core_markets
from mochex_radar.storage import initialize_database, store_stream_candle
from mochex_radar.live_state import LiveSnapshots, RedisError

log = logging.getLogger(__name__)
URL = "wss://contract.mexc.com/edge"
MARKETS = {market.market_id: market for market in (*core_markets(), btc_context_market())}
PROVIDER_INTERVALS = {value[0]: (key, value[1]) for key, value in INTERVALS.items()}
TARGETS = [(market, interval) for market in core_markets() for interval in INTERVALS]
TARGETS.extend((btc_context_market(), interval) for interval in INTERVALS)
TARGET_KEYS = {(market.market_id, interval) for market, interval in TARGETS}


def subscriptions() -> list[str]:
    return [json.dumps({"method": "sub.kline", "param": {"symbol": market.market_id,
                      "interval": INTERVALS[interval][0]}}) for market, interval in TARGETS]


def parse_update(raw: str | bytes, received_at: datetime) -> Candle | None:
    try:
        payload = json.loads(raw, parse_float=Decimal)
        if not isinstance(payload, dict) or payload.get("channel") != "push.kline":
            return None
        data = payload["data"]
        symbol = payload["symbol"]
        if not isinstance(data, dict) or data.get("symbol") != symbol or symbol not in MARKETS:
            return None
        provider_interval = data["interval"]
        if provider_interval not in PROVIDER_INTERVALS:
            return None
        interval, seconds = PROVIDER_INTERVALS[provider_interval]
        if (symbol, interval) not in TARGET_KEYS:
            return None
        ts = data["t"]
        if isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0:
            return None
        opened = datetime.fromtimestamp(ts, timezone.utc)
        if opened > received_at or received_at - opened > timedelta(seconds=seconds * 2):
            return None
        o, h, l, c, v = (_decimal(data[key]) for key in ("o", "h", "l", "c", "q"))
        if min(o, h, l, c) <= 0 or v < 0 or l > min(o, c) or h < max(o, c):
            return None
        return Candle(MARKETS[symbol].asset_id, interval, opened,
                      opened + timedelta(seconds=seconds), received_at, o, h, l, c, v)
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


class Rollover:
    def __init__(self) -> None:
        self.pending: dict[tuple[str, str], Candle] = {}

    def accept(self, candle: Candle) -> Candle | None:
        key = (candle.asset_id, candle.interval)
        old = self.pending.get(key)
        if old is None:
            self.pending[key] = candle
            return None
        if candle.open_time < old.open_time:
            return None
        if candle.open_time == old.open_time:
            self.pending[key] = candle
            return None
        self.pending[key] = candle
        if candle.open_time != old.close_time:
            return None  # Gap: REST collector remains the source of recovery.
        return old


async def app_ping(websocket: Any) -> None:
    while True:
        await asyncio.sleep(15)
        await websocket.send('{"method":"ping"}')


async def consume(websocket: Any, save: Callable[[Candle], Awaitable[None]], publish=None) -> None:
    for subscription in subscriptions():
        await websocket.send(subscription)
    rollover = Rollover()
    ping_task = asyncio.create_task(app_ping(websocket))
    suppress_live_until = 0.0
    try:
        async for raw in websocket:
            candle = parse_update(raw, datetime.now(timezone.utc))
            if candle is None:
                continue
            if publish is not None and asyncio.get_running_loop().time() >= suppress_live_until:
                try:
                    await publish(candle)
                except (RedisError, ValueError):
                    suppress_live_until = asyncio.get_running_loop().time() + 30
                    log.warning("ephemeral live cache unavailable; durable collection continues")
            finalized = rollover.accept(candle)
            if finalized is not None:
                await save(finalized)
    finally:
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass


async def reconcile(dsn: str) -> None:
    async with httpx.AsyncClient() as client:
        for market, interval in TARGETS:
            try:
                candle = await fetch_latest_closed(market, interval, client)
                await asyncio.to_thread(store_stream_candle, dsn, candle)
            except Exception:
                log.warning("REST reconciliation failed for %s %s", market.market_id, interval)
            await asyncio.sleep(0.15)


async def run(dsn: str) -> None:
    await asyncio.to_thread(initialize_database, dsn)
    await reconcile(dsn)

    async def save(candle: Candle) -> None:
        await asyncio.to_thread(store_stream_candle, dsn, candle)

    live = LiveSnapshots.from_url(os.environ["REDIS_URL"]) if os.environ.get("REDIS_URL") else None
    try:
        async for websocket in connect(URL, open_timeout=10, ping_interval=20, max_size=1_048_576):
            try:
                await consume(websocket, save, live.publish if live else None)
            except ConnectionClosed:
                log.warning("WebSocket disconnected; reconnecting")
    finally:
        if live:
            await live.close()


async def smoke() -> None:
    """Check a public subscription without writing data or needing a database."""
    async with connect(URL, open_timeout=10, ping_interval=20) as websocket:
        await websocket.send(json.dumps({"method": "sub.kline", "param":
                                        {"symbol": "SOL_USDT", "interval": "Min15"}}))
        for _ in range(10):
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            candle = parse_update(raw, datetime.now(timezone.utc))
            if candle is not None:
                print(f"public stream observed {candle.asset_id} {candle.interval}")
                return
    raise RuntimeError("no valid public kline received")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream public MEXC futures candles")
    parser.add_argument("--smoke", action="store_true", help="validate one public SOL kline without database writes")
    args = parser.parse_args()
    if args.smoke:
        asyncio.run(smoke())
        return
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(dsn))


if __name__ == "__main__":
    main()
