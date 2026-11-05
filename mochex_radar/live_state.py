"""Ephemeral provisional MEXC snapshots; never a closed-candle data source."""

import json
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from redis.exceptions import RedisError

from mochex_radar.feature_validation import parse_candle_records
from mochex_radar.futures_feed import Candle
from mochex_radar.market_features import INTERVALS
from mochex_radar.markets import btc_context_market, core_markets

WRITE = """
local seen = tonumber(redis.call('HGET', KEYS[1], 'seen') or '-1')
local opened = tonumber(redis.call('HGET', KEYS[1], 'opened') or '-1')
if opened > tonumber(ARGV[3]) or (opened == tonumber(ARGV[3]) and seen >= tonumber(ARGV[1])) then return 0 end
redis.call('HSET', KEYS[1], 'seen', ARGV[1], 'payload', ARGV[2], 'opened', ARGV[3])
redis.call('EXPIRE', KEYS[1], 120)
return 1
"""


def _validate(candle: Candle, now: datetime):
    if candle.asset_id not in {m.asset_id for m in (*core_markets(), btc_context_market())} or candle.interval not in INTERVALS:
        raise ValueError("unsupported live identity")
    for value in (candle.open_time, candle.close_time, candle.retrieved_at, now):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("live UTC required")
    values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
    if (any(not v.is_finite() for v in values) or min(values[:4]) <= 0 or candle.volume < 0
            or candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close, candle.high)
            or candle.close_time - candle.open_time != INTERVALS[candle.interval]
            or candle.open_time.timestamp() % INTERVALS[candle.interval].total_seconds()
            or not candle.open_time <= candle.retrieved_at <= now
            or not isinstance(candle.source, str) or not 1 <= len(candle.source) <= 200):
        raise ValueError("invalid live candle")


def key(asset_id, interval):
    return f"mochex:live:v1:{asset_id}:{interval}"


class LiveSnapshots:
    def __init__(self, client):
        self.client = client

    @classmethod
    def from_url(cls, url):
        return cls(Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.25))

    async def close(self):
        await self.client.aclose()

    async def publish(self, candle):
        _validate(candle, datetime.now(timezone.utc))
        payload = json.dumps(candle.to_dict())
        if len(payload) > 8192:
            raise ValueError("live payload exceeds limit")
        return bool(await self.client.eval(WRITE, 1, key(candle.asset_id, candle.interval),
                                           int(candle.retrieved_at.timestamp() * 1_000_000), payload, int(candle.open_time.timestamp())))

    async def snapshot(self, interval="15m", now=None):
        if interval not in INTERVALS:
            raise ValueError("unsupported interval")
        now = now or datetime.now(timezone.utc)
        rows = []
        for market in core_markets():
            raw = await self.client.hget(key(market.asset_id, interval), "payload")
            observation, age = None, None
            if raw:
                try:
                    if len(raw) > 8192:
                        raise ValueError("oversized live payload")
                    candle = parse_candle_records([json.loads(raw)])[0]
                    _validate(candle, now)
                    if candle.asset_id != market.asset_id or candle.interval != interval:
                        raise ValueError("cache identity mismatch")
                    observation = candle.to_dict()
                    age = (now - candle.retrieved_at).total_seconds()
                except (ValueError, TypeError, KeyError, ArithmeticError):
                    pass
            rows.append({"base": market.base, "market_id": market.market_id,
                         "status": "missing" if observation is None else "current" if age < 30 else "stale",
                         "observation": observation, "age_seconds": age})
        return {"data_status": "ephemeral_observations", "as_of": now.isoformat(), "interval": interval,
                "provisional": True, "finalized": False, "signals_enabled": False, "markets": rows}
