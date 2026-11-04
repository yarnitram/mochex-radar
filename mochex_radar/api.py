"""Read only foundation API; no market feed is connected yet."""

from fastapi import FastAPI

from mochex_radar.markets import core_markets

app = FastAPI(title="Mochex Radar", version="0.1.0")


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
