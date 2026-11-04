"""Provisional, versioned BTC context screening from closed candles."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mochex_radar.futures_feed import Candle

RULE_VERSION = "btc-context-v1"
INTERVAL = timedelta(minutes=15)


def classify(candles: list[Candle], now: datetime) -> dict[str, object]:
    base: dict[str, object] = {"state": "unknown", "reason": "insufficient_data", "rule_version": RULE_VERSION,
                               "provisional": True, "return_1h": None, "data_as_of": None,
                               "data_age_seconds": None, "input_open_times": []}
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("now must be UTC")
    if len(candles) != 4:
        return base
    ordered = sorted(candles, key=lambda item: item.open_time)
    if any(item.asset_id != "cex:mexc-usdt-futures:BTC_USDT" or item.interval != "15m" or
           item.open_time.tzinfo is None or item.close_time.tzinfo is None or
           item.open_time.utcoffset() != timedelta(0) or item.close_time.utcoffset() != timedelta(0)
           for item in ordered):
        return {**base, "reason": "invalid_identity_or_time"}
    if any(ordered[index + 1].open_time - ordered[index].open_time != INTERVAL for index in range(3)) or any(
        item.close_time - item.open_time != INTERVAL for item in ordered
    ):
        return {**base, "reason": "gap_or_duplicate"}
    latest = ordered[-1]
    age_seconds = (now - latest.close_time).total_seconds()
    if latest.close_time > now or now - latest.close_time > 2 * INTERVAL:
        return {**base, "reason": "stale_or_future_data", "data_as_of": latest.close_time.isoformat(),
                "data_age_seconds": age_seconds}
    if ordered[0].open <= 0 or any(item.close <= 0 for item in ordered):
        return {**base, "reason": "invalid_price"}
    change = latest.close / ordered[0].open - Decimal(1)
    if change <= Decimal("-0.02"):
        state = "blocked"
    elif change <= Decimal("-0.01"):
        state = "caution"
    elif change >= Decimal("0.01"):
        state = "supportive"
    else:
        state = "neutral"
    return {"state": state, "reason": "provisional_return_rule", "rule_version": RULE_VERSION,
            "provisional": True, "return_1h": str(change), "data_as_of": latest.close_time.isoformat(),
            "data_age_seconds": age_seconds,
            "input_open_times": [item.open_time.isoformat() for item in ordered]}
