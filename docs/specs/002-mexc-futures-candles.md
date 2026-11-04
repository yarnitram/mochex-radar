# Spec 002 — MEXC USDT futures public candle adapter

Status: implementation candidate (2026-11-05)

## Decision and scope

The user's primary venue is MEXC USDT futures. This phase reads public contract candles for the seven USDT markets, at 15m and 1h. Futures identity uses `mexc-usdt-futures` and contract IDs such as `SOL_USDT`; Spot is a separate market. No account key is used.

## Contract

- `GET /api/v1/market-data/{symbol}/{interval}` accepts only the seven configured contract IDs and `15m` or `1h`.
- Read `GET https://contract.mexc.com/api/v1/contract/kline/{symbol}` with `Min15` or `Min60`, a bounded recent start/end window, and a five-second timeout.
- Parse aligned `time`, `open`, `high`, `low`, `close`, and `vol` arrays. Select the newest fully closed bar; never present an open bar as final.
- Validate timestamps, finite positive and internally consistent OHLC, nonnegative volume, and response success. A latest bar older than two intervals is unavailable.
- Return venue-scoped identity, source, UTC open/close/retrieval times, and decimal fields as strings.
- Timeout, HTTP or provider failure, malformed payload, or no fresh closed bar returns 503, with no fabricated candle.

## Out of scope

WebSocket streaming, history persistence, indicator calculations, BTC context, signals, and exchange listing verification. This is a public on-demand read; a later worker must handle continuous feeds and request budgets.

## Acceptance

- Fixture tests cover valid data, current open bar, malformed arrays/prices, stale data, wrong contract/interval, and provider failure.
- API tests use a fake transport and never contact MEXC.

Provider reference: [MEXC Contract API](https://mexcdevelop.github.io/apidocs/contract_v1_en/) (`K-line data`, `GET api/v1/contract/kline/{symbol}`).
