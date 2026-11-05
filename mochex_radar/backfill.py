"""One-shot, bounded MEXC futures candle history backfill; manual, read-only provider access."""

import argparse
import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from mochex_radar.futures_feed import Candle, FeedUnavailable, INTERVALS, fetch_history
from mochex_radar.markets import CexMarket, btc_context_market, core_markets
from mochex_radar.storage import initialize_database, store_candles

log = logging.getLogger(__name__)
MAX_CANDLES = 100
FetchHistory = Callable[[CexMarket, str, httpx.AsyncClient, int], Awaitable[list[Candle]]]
Persist = Callable[[list[Candle]], Awaitable[int]]
Pause = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class BackfillResult:
    targets: int
    fetched: int
    stored: int
    failures: int


async def backfill(client: httpx.AsyncClient, persist: Persist, count: int,
                   fetch: FetchHistory = fetch_history, pause: Pause = asyncio.sleep) -> BackfillResult:
    """Fetch up to `count` closed candles per target (seven pairs x 15m/1h plus BTC 15m) and store idempotently.

    One target's failure never blocks the others. Backfilled rows are stamped with the time they
    were retrieved, so they cannot appear in point-in-time replays of earlier decisions.
    """
    if not 1 <= count <= MAX_CANDLES:
        raise ValueError(f"count must be 1..{MAX_CANDLES}")
    targets = [(market, interval) for market in core_markets() for interval in INTERVALS]
    targets.append((btc_context_market(), "15m"))
    candles: list[Candle] = []
    failures = 0
    for index, (market, interval) in enumerate(targets):
        try:
            candles.extend(await fetch(market, interval, client, count))
        except FeedUnavailable:
            failures += 1
            log.warning("history unavailable for %s %s", market.market_id, interval)
        if index < len(targets) - 1:
            await pause(0.25)
    stored = await persist(candles) if candles else 0
    return BackfillResult(len(targets), len(candles), stored, failures)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill closed MEXC futures candle history (one-shot)")
    parser.add_argument("--candles", type=int, default=24, help=f"candles per pair/interval, 1..{MAX_CANDLES}")
    args = parser.parse_args()
    if not 1 <= args.candles <= MAX_CANDLES:
        parser.error(f"--candles must be 1..{MAX_CANDLES}")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required")
    logging.basicConfig(level=logging.INFO)

    async def run() -> BackfillResult:
        await asyncio.to_thread(initialize_database, dsn)
        async with httpx.AsyncClient() as client:
            async def persist(candles: list[Candle]) -> int:
                return await asyncio.to_thread(store_candles, dsn, candles)

            return await backfill(client, persist, args.candles)

    result = asyncio.run(run())
    print(f"targets={result.targets} fetched={result.fetched} stored_new={result.stored} failed_targets={result.failures}")
    raise SystemExit(1 if result.failures else 0)


if __name__ == "__main__":
    main()
