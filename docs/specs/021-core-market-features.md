# Spec 021 — Core market features (feature version core-features-v1)

`mochex_radar.market_features` computes read-only, provisional features for one MEXC USDT
futures contract from stored closed candles (15m or 1h). No signals, alerts, storage writes,
provider calls or trading. Wiring into the API/dashboard is a later increment.

Point in time: only candles with `close_time <= now` and `retrieved_at <= now`; the earliest
observation of each candle wins, so later revisions never alter earlier decisions. Input order
is irrelevant. `replay_features` applies this at each decision time.

Lookback: 21 consecutive closed candles. Gap, duplicate, non-UTC, bad OHLC/volume, stale
(newest close older than two intervals) or short history makes every feature unavailable with a
reason; missing is never zero.

Features: `atr` (simple mean of 14 true ranges), `atr_pct`, `range_atr` (latest range / ATR),
`relative_volume` (latest / mean of prior 20; unavailable when mean is zero),
`volatility_state` (expanding >= 2.0, compressed <= 0.5 range/ATR, else normal),
`structure_state` (close beyond prior-20 high/low: breakout_up / breakdown, else range),
`relative_strength` (asset 4-candle return minus BTC_USDT return over identical open times;
unavailable with `btc_not_aligned`/`btc_invalid` without disabling the other features).
Decimals are serialized as strings. Thresholds and windows are unvalidated hypotheses that
need replay/backtest comparison before any use in alerts. BTC remains context only.

Acceptance: known-series values, volume/volatility/structure states, gap/stale/lookback/invalid
guards, zero-volume unknown, BTC misalignment isolation, unretrieved/future/revised candle
exclusion, order-independent replay, UTC and interval validation.
