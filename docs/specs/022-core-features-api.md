# Spec 022 — Core features API

`GET /api/v1/features/core?interval=15m|1h` returns the spec 021 features for the seven core
MEXC USDT futures pairs from stored candles only; it never calls an exchange. Per-pair
`status` is `ok` or `unavailable` with a reason, so one pair's gap or stale data never hides
the others. Without `DATABASE_URL` it reports `storage_disabled` with seven unavailable pairs
and no invented values; database failure is HTTP 503; unsupported interval is HTTP 422.

`storage.recent_candles` loads at most 21 candles closed and retrieved at or before the decision
time, oldest first. BTC_USDT is loaded once per request as context for relative strength.
The response is research-only (`signals_enabled: false`); it creates no signal, alert or approval.

Known limit: the collector stores only the latest closed candle per poll, so a fresh database
needs about 21 closed candles per pair and interval (roughly five hours on 15m) before features
become available. A bounded history backfill is a separate increment. Dashboard display and
threshold validation by replay/backtest are also still to do.

Acceptance: storage-disabled shape, per-pair isolation with one BTC load, UTC/interval
validation, 422/503 mapping, and a PostgreSQL test of the close/retrieval cutoff and limit.
