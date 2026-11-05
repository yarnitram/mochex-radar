"""Read only market data and collector status API."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import httpx
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from cluster_radar.providers.dexscreener import BudgetExceeded, DexScreener, ProviderUnavailable

from mochex_radar.futures_feed import INTERVALS, FeedUnavailable, fetch_latest_closed
from mochex_radar.btc_context import classify

from mochex_radar.markets import core_markets
from mochex_radar.storage import latest_cycle, recent_btc_candles
from mochex_radar.dex_store import initialize_dex_store, observation_history, store_observations

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.dex_provider = None
    async with httpx.AsyncClient() as client:
        if os.environ.get("DEX_LOOKUP_ENABLED", "false").lower() == "true":
            if dsn := os.environ.get("DATABASE_URL"):
                await asyncio.to_thread(initialize_dex_store, dsn)
            app.state.dex_provider = DexScreener(
                client, max_requests=int(os.environ.get("DEX_LOOKUP_MAX_REQUESTS", "100"))
            )
        yield


app = FastAPI(title="Mochex Radar", version="0.1.0", lifespan=lifespan)


def get_dex_provider(request: Request) -> DexScreener:
    provider = getattr(request.app.state, "dex_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="DEX lookup disabled")
    return provider


@app.get("/api/v1/dex/solana/{mint}/pools")
async def solana_pools(mint: str, provider: DexScreener = Depends(get_dex_provider)):
    try:
        pools = await provider.pools(mint)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="DEX lookup request budget exhausted") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="DEX pool data unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid Solana mint") from exc
    persisted = False
    if dsn := os.environ.get("DATABASE_URL"):
        try:
            await asyncio.to_thread(store_observations, dsn, pools)
            persisted = True
        except (psycopg.Error, ValueError) as exc:
            raise HTTPException(status_code=503, detail="DEX observation storage unavailable") from exc
    return {
        "data_status": "observed",
        "persisted": persisted,
        "security_status": "UNKNOWN",
        "approved_pump_watch": False,
        "pools": [jsonable_encoder(asdict(pool), custom_encoder={Decimal: str}) for pool in pools],
    }


@app.get("/api/v1/dex/solana/{mint}/history")
async def solana_pool_history(mint: str, as_of: datetime, limit: int = 100):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DEX observation storage disabled")
    try:
        observations = await asyncio.to_thread(observation_history, dsn, mint, as_of, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="UTC as_of and limit 1..1000 required") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="DEX observation history unavailable") from exc
    return {"data_status": "stored_observations", "observations": observations}


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
