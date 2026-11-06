"""Manual read-only audit of stored feature lookbacks; no provider requests."""

import json
import os
from datetime import datetime, timezone

import psycopg

from mochex_radar.market_features import INTERVALS, compute_features, point_in_time_candles
from mochex_radar.markets import core_markets
from mochex_radar.validation_export import stored_validation_candles


def coverage_report(load, now):
    rows = []
    for market in core_markets():
        for interval, step in INTERVALS.items():
            candles = load(market.asset_id, interval, now - 24 * step, now)
            visible = point_in_time_candles(candles, market.asset_id, interval, now)
            features = compute_features(candles, candles, market.asset_id, interval, now)
            rows.append({
                "asset_id": market.asset_id, "interval": interval,
                "visible_rows": len(visible),
                "latest_close": visible[-1].close_time.isoformat() if visible else None,
                "latest_retrieval": max(c.retrieved_at for c in visible).isoformat() if visible else None,
                "gap_count": sum(b.open_time - a.open_time != step for a, b in zip(visible, visible[1:])),
                "feature_status": features["status"], "reason": features["reason"],
                "btc_alignment_reason": features["relative_strength_reason"],
            })
    return {"as_of": now.isoformat(), "window_intervals": 24,
            "websocket_freshness": "not_assessed", "markets": rows}


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required in private configuration")
    try:
        report = coverage_report(lambda *args: stored_validation_candles(dsn, *args),
                                 datetime.now(timezone.utc))
    except psycopg.Error:
        raise SystemExit("Coverage unavailable; inspect private database diagnostics") from None
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
