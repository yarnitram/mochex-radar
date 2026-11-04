# Spec 006 — Point-in-time BTC context replay

## Objective

Replay the existing provisional BTC classifier at chosen UTC decision times using only closed candles observed by that time. This is a foundation for later signal backtests, not a profitability claim.

## Contract

- A candle is eligible only if `close_time` and `retrieved_at` are no later than the decision time.
- Repeated observations of one candle use the earliest eligible observation.
- The existing versioned classifier handles gaps, stale data, and incomplete four-candle windows.
- Results retain decision time, rule version, reason, state, and input candle times.
- Naive or non-UTC decision/retrieval times are rejected.

## Acceptance

Offline tests show delayed retrieval cannot influence an earlier decision, later revisions cannot rewrite a prior decision, and invalid decision times fail.
