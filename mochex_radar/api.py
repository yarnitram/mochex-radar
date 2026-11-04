"""Read only market data and collector status API."""

import asyncio
import os
from datetime import datetime, timezone
import httpx
import psycopg
from fastapi import Depends, FastAPI, HTTPException

from mochex_radar.futures_feed import INTERVALS, FeedUnavailable, fetch_latest_closed
from mochex_radar.btc_context import classify

from mochex_radar.markets import core_markets
from mochex_radar.storage import latest_cycle, recent_btc_candles

app = FastAPI(title="Mochex Radar", version="0.1.0")


async def get_http_client():
    async with httpx.AsyncClient() as client:
        yield client


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/collector/status")
async def collector_status() -> dict[str, object]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {"status": "disabled", "last_cycle": None}
    try:
        cycle = await asyncio.to_thread(latest_cycle, dsn)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="collector status unavailable") from exc
    return {"status": "completed" if cycle else "pending", "last_cycle": cycle}


@app.get("/api/v1/market-context/btc")
async def btc_context() -> dict[str, object]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return classify([], datetime.now(timezone.utc))
    try:
        candles = await asyncio.to_thread(recent_btc_candles, dsn)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="BTC context unavailable") from exc
    return classify(candles, datetime.now(timezone.utc))


@app.get("/api/v1/markets/core")
def list_core_markets() -> dict[str, object]:
    markets = core_markets()
    return {
        "data_status": "configuration_only",
        "markets": [
            {
                "asset_id": market.asset_id,
                "venue": market.venue,
                "market_id": market.market_id,
                "base": market.base,
                "quote": market.quote,
            }
            for market in markets
        ],
    }


@app.get("/api/v1/market-data/{symbol}/{interval}")
async def latest_candle(symbol: str, interval: str, client: httpx.AsyncClient = Depends(get_http_client)) -> dict[str, object]:
    market = next((item for item in core_markets() if item.market_id == symbol.upper()), None)
    if market is None or interval not in INTERVALS:
        raise HTTPException(status_code=404, detail="unsupported market or interval")
    try:
        candle = await fetch_latest_closed(market, interval, client)
    except FeedUnavailable as exc:
        raise HTTPException(status_code=503, detail="market data unavailable") from exc
    return {"data_status": "observed", "candle": candle.to_dict()}
