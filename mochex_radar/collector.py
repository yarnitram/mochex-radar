"""Single-replica scheduled MEXC futures candle collector."""

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx

from mochex_radar.futures_feed import Candle, FeedUnavailable, INTERVALS, fetch_latest_closed
from mochex_radar.markets import CexMarket, btc_context_market, core_markets
from mochex_radar.storage import CycleResult, initialize_database, store_cycle
from mochex_radar.alert_store import initialize_alert_store
from mochex_radar.quality_notices import report_cycle_quality

log = logging.getLogger(__name__)
Fetch = Callable[[CexMarket, str, httpx.AsyncClient], Awaitable[Candle]]
Persist = Callable[[list[Candle], datetime, datetime, int], Awaitable[int]]
Pause = Callable[[float], Awaitable[None]]


async def collect_once(client: httpx.AsyncClient, persist: Persist,
                       fetch: Fetch = fetch_latest_closed,
                       pause: Pause = asyncio.sleep) -> CycleResult:
    started = datetime.now(timezone.utc)
    candles: list[Candle] = []
    failures = 0
    targets = [(market, interval) for market in core_markets() for interval in INTERVALS]
    targets.extend((btc_context_market(), interval) for interval in INTERVALS)
    for index, (market, interval) in enumerate(targets):
        try:
            candles.append(await fetch(market, interval, client))
        except FeedUnavailable:
            failures += 1
            log.warning("provider unavailable for %s %s", market.market_id, interval)
        if index < len(targets) - 1:
            await pause(0.15)
    finished = datetime.now(timezone.utc)
    stored = await persist(candles, started, finished, failures)
    return CycleResult(started, finished, stored, failures)


async def run(dsn: str, interval_seconds: int, once: bool = False) -> None:
    await asyncio.to_thread(initialize_database, dsn)
    notices_enabled = os.environ.get("ALERT_DATA_QUALITY_ENABLED", "false").lower() == "true"
    if notices_enabled:
        try:
            await asyncio.to_thread(initialize_alert_store, dsn)
        except Exception as exc:
            log.error("quality notice initialization unavailable (%s)", type(exc).__name__)
    async with httpx.AsyncClient() as client:
        async def persist(candles: list[Candle], started: datetime, finished: datetime, failures: int) -> int:
            return await asyncio.to_thread(store_cycle, dsn, candles, started, finished, failures)

        while True:
            try:
                result = await collect_once(client, persist)
                log.info("cycle complete stored=%d provider_failures=%d", result.stored_count, result.provider_failures)
                if notices_enabled:
                    outcome = await report_cycle_quality(dsn, result)
                    log.info("quality notice outcome=%s", outcome)
            except Exception:
                log.exception("collector cycle failed")
                if once:
                    raise
            if once:
                return
            await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public MEXC futures candles")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required")
    interval_seconds = int(os.environ.get("COLLECT_INTERVAL_SECONDS", "60"))
    if interval_seconds < 30:
        parser.error("COLLECT_INTERVAL_SECONDS must be at least 30")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(dsn, interval_seconds, args.once))


if __name__ == "__main__":
    main()
