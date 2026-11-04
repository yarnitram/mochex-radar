"""Read only foundation API; no market feed is connected yet."""

import httpx
from fastapi import Depends, FastAPI, HTTPException

from mochex_radar.futures_feed import INTERVALS, FeedUnavailable, fetch_latest_closed

from mochex_radar.markets import core_markets

app = FastAPI(title="Mochex Radar", version="0.1.0")


async def get_http_client():
    async with httpx.AsyncClient() as client:
        yield client


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


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
