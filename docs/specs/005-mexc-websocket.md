# Spec 005 — MEXC futures WebSocket feed

Status: design draft (2026-11-05)

## Scope

Use MEXC's public USDT futures WebSocket at `wss://contract.mexc.com/edge` to observe the seven core contracts at 15m and 1h plus BTC_USDT at 15m. Keep REST collection as reconciliation and gap recovery until streaming is proven reliable.

## Protocol and data rules

- Send `sub.kline` for each of 15 contract/interval targets; send application `ping` every 15 seconds, since the documented server disconnects after one minute without a ping.
- Accept only `push.kline` events with a subscribed symbol and interval. Validate the envelope, exchange timestamp, window start, finite OHLC, and nonnegative quantity.
- A pushed candle is a live update, not a final candle. Finalize a window only after the next window begins or REST confirms it closed; never store a mutable candle as final.
- Deduplicate final candles through the existing PostgreSQL key. On startup, reconcile via REST. If the socket disconnects or a gap is detected, reconnect with bounded backoff; the existing REST collector continues reconciling closed windows independently.
- Connection and finalization failures are logged. A persistent stream health endpoint is deferred to the next observability phase; the current API exposes the REST collector's last cycle only.
- No account login, signed subscriptions, orders, or wallet operations.

## Acceptance

- Fixture tests for subscription, ping/pong, valid and malformed events, duplicate/out-of-order updates, rollover finalization, disconnect/reconnect, and REST gap recovery.
- Integration test persists a finalized candle exactly once in PostgreSQL.
- An opt-in live smoke test verifies a public subscription without requiring credentials.

Reference: [MEXC Contract API, WebSocket and K-line](https://mexcdevelop.github.io/apidocs/contract_v1_en/).
