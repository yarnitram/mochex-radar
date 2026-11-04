"""Deterministic, point-in-time replay for provisional BTC context."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from mochex_radar.btc_context import classify
from mochex_radar.futures_feed import Candle


@dataclass(frozen=True)
class ReplayResult:
    decision_at: datetime
    state: str
    reason: str
    rule_version: str
    input_open_times: tuple[str, ...]


def replay_btc_context(candles: list[Candle], decisions: list[datetime]) -> list[ReplayResult]:
    """At each decision use only candles closed and retrieved by then."""
    if any(t.tzinfo is None or t.utcoffset() != timedelta(0) for t in decisions):
        raise ValueError("decision times must be UTC")
    if any(c.retrieved_at.tzinfo is None or c.retrieved_at.utcoffset() != timedelta(0) for c in candles):
        raise ValueError("retrieved_at must be UTC")
    results = []
    for decision in decisions:
        eligible = [
            c for c in candles
            if c.retrieved_at <= decision and c.close_time <= decision
            and c.asset_id == "cex:mexc-usdt-futures:BTC_USDT" and c.interval == "15m"
        ]
        # Prefer the earliest observation of a candle to avoid applying a later revision.
        first_seen: dict[datetime, Candle] = {}
        for candle in sorted(eligible, key=lambda c: (c.retrieved_at, c.open_time)):
            first_seen.setdefault(candle.open_time, candle)
        window = sorted(first_seen.values(), key=lambda c: c.open_time)[-4:]
        outcome = classify(window, decision)
        results.append(ReplayResult(
            decision_at=decision,
            state=str(outcome["state"]),
            reason=str(outcome["reason"]),
            rule_version=str(outcome["rule_version"]),
            input_open_times=tuple(outcome["input_open_times"]),
        ))
    return results
