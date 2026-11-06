# BTC hourly context

Collect and backfill BTC_USDT at both supported intervals, 15m and 1h.
Include both in streamer reconciliation targets. There are now 16 acquisition
targets: seven core pairs plus BTC, each at two intervals. Existing identity,
retrieval timestamps, closed-candle validation and idempotent persistence apply.

After deployment, backfill 24 candles and rerun coverage_audit. Hourly relative
strength must remain unavailable until matching BTC history is present. Acceptance:
both BTC intervals are requested, provider failures stay isolated and coverage
shows aligned BTC after guest backfill. No earlier decision can use late backfills.
