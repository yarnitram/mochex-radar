"""Manual, bounded, read-only stored-candle export for offline comparison."""

import argparse
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from mochex_radar.feature_validation import MAX_BYTES, _timestamp, validation_report
from mochex_radar.futures_feed import Candle
from mochex_radar.market_features import INTERVALS
from mochex_radar.markets import core_markets

MAX_ROWS = 10000
Loader = Callable[[str, str, datetime, datetime], list[Candle]]


def stored_validation_candles(dsn: str, asset_id: str, interval: str,
                              start: datetime, evaluation_at: datetime, open_end: datetime | None = None) -> list[Candle]:
    """One bounded snapshot. Does not create tables or mutate application data."""
    if asset_id not in {m.asset_id for m in core_markets()} or interval not in INTERVALS:
        raise ValueError("unsupported market or interval")
    # Validate UTC even for callers outside the CLI.
    for timestamp in (start, evaluation_at):
        _timestamp(timestamp.isoformat())
    if open_end is not None:
        _timestamp(open_end.isoformat())
    market_id = asset_id.split(":", 2)[2]
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        rows = conn.execute(
            """SELECT market_id, interval, open_time, close_time, retrieved_at,
                      open_price, high_price, low_price, close_price, volume, source
               FROM market_candles
               WHERE venue = %s AND market_id IN (%s, %s) AND interval = %s
                 AND open_time >= %s AND open_time < %s
                 AND close_time <= %s AND retrieved_at <= %s
               ORDER BY market_id, open_time, retrieved_at LIMIT %s""",
            ("mexc-usdt-futures", market_id, "BTC_USDT", interval, start,
             min(evaluation_at, open_end) if open_end else evaluation_at, evaluation_at, evaluation_at, MAX_ROWS + 1),
        ).fetchall()
    if len(rows) > MAX_ROWS:
        raise ValueError("dataset exceeds 10000 rows; narrow the time range")
    return [Candle(f"cex:mexc-usdt-futures:{row[0]}", *row[1:]) for row in rows]


def build_dataset(load: Loader, asset_id: str, interval: str, decision_start: datetime,
                  decision_end: datetime, holdout_at: datetime, evaluation_at: datetime,
                  now: datetime | None = None) -> dict:
    """Preserve observations as stored, including backfill retrieval timestamps."""
    for timestamp in (decision_start, decision_end, holdout_at, evaluation_at, now or datetime.now(timezone.utc)):
        _timestamp(timestamp.isoformat())
    if asset_id not in {m.asset_id for m in core_markets()} or interval not in INTERVALS:
        raise ValueError("unsupported market or interval")
    step = INTERVALS[interval]
    span = decision_end - decision_start
    if span.total_seconds() < 0 or span % step or span // step >= 1000:
        raise ValueError("require 1..1000 interval-spaced decisions with aligned end")
    if not decision_start < holdout_at <= decision_end or not decision_end <= evaluation_at <= (now or datetime.now(timezone.utc)):
        raise ValueError("invalid holdout or evaluation cutoff")
    decisions = [decision_start + i * step for i in range(span // step + 1)]
    start = decision_start - 22 * step
    candles = load(asset_id, interval, start, evaluation_at)
    if not candles or len(candles) > MAX_ROWS:
        raise ValueError("empty or oversized stored dataset")
    validation_report(candles, asset_id, interval, decisions, holdout_at, evaluation_at)
    # Fail closed if an injected loader violates the same snapshot contract.
    if any(c.open_time < start or c.close_time > evaluation_at or c.retrieved_at > evaluation_at for c in candles):
        raise ValueError("loader returned data outside snapshot cutoff")
    if not any(c.asset_id == asset_id for c in candles):
        raise ValueError("target market has no observations")
    ordered = sorted(candles, key=lambda c: (c.asset_id, c.open_time, c.retrieved_at))
    return {"format_version": 1, "asset_id": asset_id, "interval": interval,
            "candles": [c.to_dict() for c in ordered], "decisions": [d.isoformat() for d in decisions],
            "holdout_at": holdout_at.isoformat(), "evaluation_at": evaluation_at.isoformat()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=[m.market_id for m in core_markets()], required=True)
    parser.add_argument("--interval", choices=list(INTERVALS), default="15m")
    for name in ("decision-start", "decision-end", "holdout-at", "evaluation-at"):
        parser.add_argument(f"--{name}", type=_timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required in private environment")
    if args.output.exists():
        parser.error("output already exists; choose a new file")
    try:
        data = build_dataset(lambda *values: stored_validation_candles(dsn, *values),
                             f"cex:mexc-usdt-futures:{args.market}", args.interval,
                             args.decision_start, args.decision_end, args.holdout_at, args.evaluation_at)
    except psycopg.Error:
        parser.exit(1, "Stored dataset unavailable; check private connection and schema configuration.\n")
    except ValueError:
        parser.exit(1, "Dataset rejected; check time range, coverage, row bounds and stored candle validity.\n")
    serialized = json.dumps(data, indent=2) + "\n"
    if len(serialized.encode("utf-8")) > MAX_BYTES:
        parser.exit(1, "Dataset exceeds 5MB; narrow the time range.\n")
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    print(f"Exported {len(data['candles'])} stored candles and {len(data['decisions'])} decisions; research only.")


if __name__ == "__main__":
    main()
