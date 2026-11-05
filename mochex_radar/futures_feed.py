"""Read only MEXC USDT futures public REST candle adapter."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from mochex_radar.markets import CexMarket

INTERVALS = {"15m": ("Min15", 900), "1h": ("Min60", 3600)}
BASE_URL = "https://api.mexc.com"


class FeedUnavailable(Exception):
    """Provider data cannot safely be returned."""


@dataclass(frozen=True)
class Candle:
    asset_id: str
    interval: str
    open_time: datetime
    close_time: datetime
    retrieved_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str = "mexc-usdt-futures"

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) if isinstance(value, Decimal) else value.isoformat() if isinstance(value, datetime) else value for key, value in asdict(self).items()}


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("nonfinite decimal")
    return result


def parse_latest_closed(data: Any, market: CexMarket, interval: str, now: datetime) -> Candle:
    if not isinstance(data, dict):
        raise ValueError("invalid kline data")
    columns = ("time", "open", "high", "low", "close", "vol")
    arrays = [data.get(key) for key in columns]
    if any(not isinstance(values, list) for values in arrays):
        raise ValueError("missing kline columns")
    if not arrays[0] or len({len(values) for values in arrays}) != 1:
        raise ValueError("misaligned kline columns")
    seconds = INTERVALS[interval][1]
    candidates = []
    for ts, opening, high, low, closing, volume in zip(*arrays):
        if isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0:
            raise ValueError("invalid kline time")
        try:
            opened = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("invalid kline time") from exc
        closed = opened + timedelta(seconds=seconds)
        if closed > now:
            continue
        o, h, l, c, v = map(_decimal, (opening, high, low, closing, volume))
        if min(o, h, l, c) <= 0 or v < 0 or l > min(o, c) or h < max(o, c):
            raise ValueError("invalid OHLCV")
        candidates.append(Candle(market.asset_id, interval, opened, closed, now, o, h, l, c, v))
    if not candidates:
        raise ValueError("no closed candle")
    latest = max(candidates, key=lambda candle: candle.open_time)
    if now - latest.close_time > timedelta(seconds=seconds * 2):
        raise ValueError("stale candle")
    return latest


async def fetch_latest_closed(market: CexMarket, interval: str, client: httpx.AsyncClient) -> Candle:
    if market.venue != "mexc-usdt-futures" or interval not in INTERVALS:
        raise ValueError("unsupported market or interval")
    provider_interval, seconds = INTERVALS[interval]
    now = datetime.now(timezone.utc)
    try:
        response = await client.get(
            f"{BASE_URL}/api/v1/contract/kline/{market.market_id}",
            params={"interval": provider_interval, "start": int(now.timestamp()) - seconds * 4, "end": int(now.timestamp())},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = json.loads(response.text, parse_float=Decimal)
        if not isinstance(payload, dict) or payload.get("success") is not True or payload.get("code") != 0:
            raise ValueError("provider rejected request")
        return parse_latest_closed(payload.get("data"), market, interval, now)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise FeedUnavailable("MEXC contract candle unavailable") from exc


def parse_closed_history(data: Any, market: CexMarket, interval: str, now: datetime, max_candles: int) -> list[Candle]:
    """All closed candles in a payload (newest `max_candles`, oldest first), validated like the latest-candle parser.

    Candles are stamped as retrieved at `now`, so replay at earlier decision times never sees them.
    """
    if not isinstance(data, dict):
        raise ValueError("invalid kline data")
    columns = ("time", "open", "high", "low", "close", "vol")
    arrays = [data.get(key) for key in columns]
    if any(not isinstance(values, list) for values in arrays):
        raise ValueError("missing kline columns")
    if not arrays[0] or len({len(values) for values in arrays}) != 1:
        raise ValueError("misaligned kline columns")
    seconds = INTERVALS[interval][1]
    seen: set[int] = set()
    candles = []
    for ts, opening, high, low, closing, volume in zip(*arrays):
        if isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0 or ts in seen:
            raise ValueError("invalid or duplicate kline time")
        seen.add(ts)
        try:
            opened = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("invalid kline time") from exc
        closed = opened + timedelta(seconds=seconds)
        if closed > now:
            continue
        o, h, l, c, v = map(_decimal, (opening, high, low, closing, volume))
        if min(o, h, l, c) <= 0 or v < 0 or l > min(o, c) or h < max(o, c):
            raise ValueError("invalid OHLCV")
        candles.append(Candle(market.asset_id, interval, opened, closed, now, o, h, l, c, v))
    if not candles:
        raise ValueError("no closed candle")
    candles.sort(key=lambda candle: candle.open_time)
    if now - candles[-1].close_time > timedelta(seconds=seconds * 2):
        raise ValueError("stale candle")
    return candles[-max_candles:]


async def fetch_history(market: CexMarket, interval: str, client: httpx.AsyncClient, count: int) -> list[Candle]:
    if market.venue != "mexc-usdt-futures" or interval not in INTERVALS or not 1 <= count <= 100:
        raise ValueError("unsupported market, interval or count")
    provider_interval, seconds = INTERVALS[interval]
    now = datetime.now(timezone.utc)
    try:
        response = await client.get(
            f"{BASE_URL}/api/v1/contract/kline/{market.market_id}",
            params={"interval": provider_interval, "start": int(now.timestamp()) - seconds * (count + 2),
                    "end": int(now.timestamp())},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = json.loads(response.text, parse_float=Decimal)
        if not isinstance(payload, dict) or payload.get("success") is not True or payload.get("code") != 0:
            raise ValueError("provider rejected request")
        return parse_closed_history(payload.get("data"), market, interval, now, count)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise FeedUnavailable("MEXC contract candle history unavailable") from exc
