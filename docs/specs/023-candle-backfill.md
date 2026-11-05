# Spec 023 — Bounded candle history backfill

Closes the gap noted in spec 022: the collector stores only the newest closed candle per poll, so
core features need roughly five hours of running before 21 candles exist. A manual one-shot command
fills history from the public MEXC futures kline endpoint.

`python -m mochex_radar.backfill --candles N` (default 24, bounded 1..100) or
`docker compose --profile backfill run --rm backfill` (`BACKFILL_CANDLES`, restart "no"). It is not
scheduled. For the seven core pairs on 15m and 1h plus BTC_USDT 15m (15 targets) it requests
`N + 2` intervals of history, one target at a time with a 0.25 s pause, read-only and unauthenticated.

`futures_feed.parse_closed_history` applies the same OHLCV validation as the latest-candle parser,
drops candles still open, rejects duplicate/invalid/misaligned rows (the whole target fails, nothing
partial is kept), and rejects stale history (newest close older than two intervals).
`storage.store_candles` inserts with `ON CONFLICT DO NOTHING` and writes no `collector_cycles` row,
so collector status is not polluted and existing candles are never overwritten.

One target failing never blocks the others; the command prints counts and exits 1 if any target
failed (successfully fetched candles are still stored).

Point in time: backfilled candles carry `retrieved_at` = backfill time. Replays and the features
API with an earlier `as_of` therefore cannot see them, so history that was not actually known then
is never presented as known. They become visible from the backfill time onward.

Acceptance: ordering/bounds/open-candle exclusion, invalid/duplicate/stale/empty rejection, request
window and 500/provider-rejection mapping, count bounds, 15-target isolation with a single persist,
no persist when all fail, and a PostgreSQL test for idempotency with no cycle record.
