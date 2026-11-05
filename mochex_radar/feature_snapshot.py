"""Stored-candle feature snapshot for the seven core pairs; never calls an exchange."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from mochex_radar.futures_feed import Candle
from mochex_radar.market_features import BTC_ASSET_ID, INTERVALS, REQUIRED_CANDLES, compute_features
from mochex_radar.markets import btc_context_market, core_markets

Loader = Callable[[str, str, datetime, int], list[Candle]]


def core_feature_snapshot(load: Loader | None, interval: str = "15m", now: datetime | None = None) -> dict:
    """`load(market_id, interval, as_of, limit)` returns stored candles; None means storage disabled."""
    if interval not in INTERVALS:
        raise ValueError("unsupported interval")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("now must be UTC")
    btc = load(btc_context_market().market_id, interval, now, REQUIRED_CANDLES) if load else []
    markets = []
    for market in core_markets():
        candles = load(market.market_id, interval, now, REQUIRED_CANDLES) if load else []
        result = compute_features(candles, btc, market.asset_id, interval, now)
        markets.append({"base": market.base, "quote": market.quote, "market_id": market.market_id, **result})
    return {"data_status": "stored_observations" if load else "storage_disabled", "as_of": now.isoformat(),
            "interval": interval, "btc_asset_id": BTC_ASSET_ID, "markets": markets,
            "research_only": True, "signals_enabled": False}
