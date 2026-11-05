"""Opt-in single-plan paper capture worker using stored observations only."""

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from mochex_radar.market_features import INTERVALS
from mochex_radar.paper_journal import _load_plan, _slot, capture, record_outcome, summarize
from mochex_radar.validation_export import stored_validation_candles

log = logging.getLogger(__name__)


def run_once(path, load, clock=lambda: datetime.now(timezone.utc)):
    plan = _load_plan(path, True)
    config = plan["config"]
    now = clock()
    summary = summarize(path, now)
    due_captures = [r for r in summary["rows"] if r["status"] == "awaiting_capture"]
    pending = [r for r in summary["rows"] if r["status"] == "pending_outcome" and _slot(plan, r["index"])[2] <= now]
    result = {"captured": 0, "outcomes": 0, "unavailable": 0, "duplicates": 0, "deadline_missed": 0}
    for row in (due_captures + pending)[:5]:
        index = row["index"]
        decision, _, close = _slot(plan, index)
        observed_at = clock()
        if row["status"] == "awaiting_capture" and observed_at > decision + timedelta(seconds=config["capture_grace_seconds"]):
            result["deadline_missed"] += 1
            continue
        try:
            candles = load(config["asset_id"], config["interval"], decision - 22 * INTERVALS[config["interval"]], observed_at,
                           observed_at if row["status"] == "awaiting_capture" else close)
        except psycopg.Error:
            result["unavailable"] += 1
            continue
        raw = json.dumps({"format_version": 1, "candles": [c.to_dict() for c in candles]}).encode()
        recorded_at = clock()
        if row["status"] == "awaiting_capture" and recorded_at > decision + timedelta(seconds=config["capture_grace_seconds"]):
            result["deadline_missed"] += 1
            continue
        if row["status"] == "pending_outcome" and not any(c.asset_id == config["asset_id"] and c.open_time == _slot(plan, index)[1] for c in candles):
            result["unavailable"] += 1
            continue
        try:
            if row["status"] == "awaiting_capture":
                capture(path, index, raw, now=recorded_at)
                result["captured"] += 1
            else:
                record_outcome(path, index, raw, now=recorded_at)
                result["outcomes"] += 1
        except FileExistsError:
            result["duplicates"] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.poll_seconds <= 30:
        parser.error("poll-seconds must be 1..30")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL required in private configuration")
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            result = run_once(args.plan, lambda *values: stored_validation_candles(dsn, *values))
            log.info("paper cycle %s", json.dumps(result, sort_keys=True))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.error("paper journal/configuration unavailable (%s)", type(exc).__name__)
            raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
