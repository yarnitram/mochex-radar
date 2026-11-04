# Spec 004 — BTC market context

Status: implementation candidate (2026-11-05)

## Scope

Collect MEXC `BTC_USDT` 15m contract candles as context only. BTC does not enter the seven market watchlist or any trading endpoint. Classify a rolling four closed candle window from PostgreSQL and expose the result at `GET /api/v1/market-context/btc`.

## Contract

- Require four consecutive 15m closed candles from the same venue and market ID; no duplicate or gap is allowed.
- If data is missing, stale (latest close over 30 minutes old), non-UTC, or invalid, return `unknown` with an explicit reason and no directional interpretation.
- Calculate the one hour change as `(last close / first open) - 1` using decimal arithmetic.
- Version `btc-context-v1` is a provisional screening rule: change at or below -2% is `blocked`, at or below -1% is `caution`, at or above +1% is `supportive`, otherwise `neutral`.
- Include four input timestamps, latest close, calculated return, data age, rule version, and provisional status. These thresholds require backtesting before they can govern alerts.
- The endpoint must not read live data or emit an order. Database failure returns 503. Missing data returns HTTP 200 with `unknown`.

## Acceptance

- Unit tests cover all states, boundary values, missing candles, gaps, and staleness.
- Integration test stores four BTC candles in PostgreSQL and reads them back in order.
- The collector adds exactly one BTC 15m target to its existing fourteen watchlist targets; BTC remains absent from `GET /api/v1/markets/core`.
