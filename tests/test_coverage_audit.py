from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mochex_radar.coverage_audit import coverage_report
from mochex_radar.futures_feed import Candle


def test_missing_markets_remain_visible():
    report = coverage_report(lambda *args: [], datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert len(report["markets"]) == 14
    assert all(row["visible_rows"] == 0 and row["feature_status"] == "unavailable"
               and row["latest_close"] is None for row in report["markets"])
    assert report["websocket_freshness"] == "not_assessed"


def test_future_retrieval_is_excluded_and_gaps_are_reported():
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    def load(asset, interval, start, cutoff):
        step = timedelta(minutes=15) if interval == "15m" else timedelta(hours=1)
        def candle(offset, retrieved):
            opened = now - offset * step
            return Candle(asset, interval, opened, opened + step, retrieved,
                          Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(1))
        return [candle(4, now), candle(2, now), candle(1, now + step)]
    report = coverage_report(load, now)
    assert all(row["visible_rows"] == 2 and row["gap_count"] == 1
               and row["feature_status"] == "unavailable" for row in report["markets"])
