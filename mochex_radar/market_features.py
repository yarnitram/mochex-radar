"""Provisional, versioned core-pair features from closed candles; read-only, no signals."""

from datetime import datetime, timedelta
from decimal import Decimal

from mochex_radar.futures_feed import Candle

FEATURE_VERSION = "core-features-v1"
INTERVALS = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1)}
ATR_PERIOD = 14
VOLUME_LOOKBACK = 20
STRUCTURE_LOOKBACK = 20
RS_CANDLES = 4
# Newest candle plus the prior window needed by the widest feature (volume/structure: 20 prior).
REQUIRED_CANDLES = VOLUME_LOOKBACK + 1
EXPANDING_RANGE_ATR = Decimal(2)
COMPRESSED_RANGE_ATR = Decimal("0.5")
BTC_ASSET_ID = "cex:mexc-usdt-futures:BTC_USDT"
FEATURES = ("atr", "atr_pct", "range_atr", "relative_volume", "volatility_state", "structure_state", "relative_strength")


def _utc(*times: datetime) -> bool:
    return all(t.tzinfo is not None and t.utcoffset() == timedelta(0) for t in times)


def point_in_time_candles(candles: list[Candle], asset_id: str, interval: str, now: datetime) -> list[Candle]:
    """Closed and retrieved by now; earliest observation of each candle wins; ordered by open time."""
    first: dict[datetime, Candle] = {}
    for c in sorted(candles, key=lambda c: (c.retrieved_at, c.open_time)):
        if c.asset_id == asset_id and c.interval == interval and c.retrieved_at <= now and c.close_time <= now:
            first.setdefault(c.open_time, c)
    return sorted(first.values(), key=lambda c: c.open_time)


def _unavailable(reason: str, asset_id: str, interval: str, now: datetime, **extra) -> dict:
    return {"asset_id": asset_id, "interval": interval, "feature_version": FEATURE_VERSION, "provisional": True,
            "status": "unavailable", "reason": reason, "decision_at": now.isoformat(), "data_as_of": None,
            "data_age_seconds": None, "features": {name: None for name in FEATURES},
            "relative_strength_reason": None, "input_open_times": [], **extra}


def _valid_window(window: list[Candle], step: timedelta) -> str | None:
    for c in window:
        if not _utc(c.open_time, c.close_time, c.retrieved_at) or c.close_time - c.open_time != step:
            return "invalid_identity_or_time"
        if min(c.open, c.high, c.low, c.close) <= 0 or c.high < max(c.open, c.close, c.low) \
                or c.low > min(c.open, c.close, c.high) or c.volume < 0:
            return "invalid_price_or_volume"
    if any(b.open_time - a.open_time != step for a, b in zip(window, window[1:], strict=False)):
        return "gap_or_duplicate"
    return None


def _true_range(candle: Candle, previous_close: Decimal) -> Decimal:
    return max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close))


def compute_features(candles: list[Candle], btc_candles: list[Candle], asset_id: str, interval: str,
                     now: datetime) -> dict:
    """Features for one asset using only candles closed and retrieved at or before `now`.

    Any gap, invalid candle, stale data or insufficient lookback makes every feature unavailable;
    missing values are never zero. Relative strength is separately unavailable without aligned BTC.
    Thresholds are unvalidated hypotheses and nothing here approves a signal or alert.
    """
    if interval not in INTERVALS:
        raise ValueError("unsupported interval")
    if not _utc(now):
        raise ValueError("now must be UTC")
    step = INTERVALS[interval]
    window = point_in_time_candles(candles, asset_id, interval, now)[-REQUIRED_CANDLES:]
    if len(window) < REQUIRED_CANDLES:
        return _unavailable("insufficient_lookback", asset_id, interval, now)
    problem = _valid_window(window, step)
    latest = window[-1]
    if problem:
        return _unavailable(problem, asset_id, interval, now)
    age = (now - latest.close_time).total_seconds()
    if now - latest.close_time > 2 * step:
        return _unavailable("stale_data", asset_id, interval, now, data_as_of=latest.close_time.isoformat(),
                            data_age_seconds=age)

    recent = window[-(ATR_PERIOD + 1):]
    atr = sum((_true_range(c, p.close) for p, c in zip(recent, recent[1:], strict=False)), Decimal(0)) / ATR_PERIOD
    prior = window[:-1]
    mean_volume = sum((c.volume for c in prior), Decimal(0)) / len(prior)
    range_atr = (latest.high - latest.low) / atr if atr > 0 else None
    if range_atr is None:
        volatility = None
    elif range_atr >= EXPANDING_RANGE_ATR:
        volatility = "expanding"
    elif range_atr <= COMPRESSED_RANGE_ATR:
        volatility = "compressed"
    else:
        volatility = "normal"
    structure_window = prior[-STRUCTURE_LOOKBACK:]
    high, low = max(c.high for c in structure_window), min(c.low for c in structure_window)
    structure = "breakout_up" if latest.close > high else "breakdown" if latest.close < low else "range"

    rs, rs_reason = None, None
    wanted = window[-(RS_CANDLES + 1):]
    btc = {c.open_time: c for c in point_in_time_candles(btc_candles, BTC_ASSET_ID, interval, now)}
    aligned = [btc.get(c.open_time) for c in wanted]
    if any(c is None for c in aligned):
        rs_reason = "btc_not_aligned"
    elif _valid_window(aligned, step):
        rs_reason = "btc_invalid"
    else:
        rs = (latest.close / wanted[0].open - 1) - (aligned[-1].close / aligned[0].open - 1)
    features = {"atr": atr, "atr_pct": atr / latest.close, "range_atr": range_atr,
                "relative_volume": latest.volume / mean_volume if mean_volume > 0 else None,
                "volatility_state": volatility, "structure_state": structure, "relative_strength": rs}
    return {"asset_id": asset_id, "interval": interval, "feature_version": FEATURE_VERSION, "provisional": True,
            "status": "ok", "reason": None, "decision_at": now.isoformat(), "data_as_of": latest.close_time.isoformat(),
            "data_age_seconds": age,
            "features": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in features.items()},
            "relative_strength_reason": rs_reason, "input_open_times": [c.open_time.isoformat() for c in window]}


def replay_features(candles: list[Candle], btc_candles: list[Candle], asset_id: str, interval: str,
                    decisions: list[datetime]) -> list[dict]:
    """Deterministic replay: each decision sees only what was closed and retrieved by then."""
    if not all(_utc(t) for t in decisions):
        raise ValueError("decision times must be UTC")
    return [compute_features(candles, btc_candles, asset_id, interval, t) for t in decisions]
