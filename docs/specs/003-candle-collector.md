# Spec 003 — Scheduled futures candle collection

Status: implementation candidate (2026-11-05)

## Scope

Collect the newest fully closed MEXC USDT futures candles for seven contracts at 15m and 1h and store them durably in PostgreSQL. The worker is a separate process from the API. One cycle scans 14 configured market/interval combinations sequentially. A failed market must not block other markets.

## Contract and invariants

- The worker requires `DATABASE_URL` and runs one cycle with `--once` or repeatedly at a configurable interval (default 60 seconds). Cycles cannot overlap within one worker. Deploy exactly one worker replica until distributed locking exists.
- Provider calls are spaced by at least 150 ms and use the adapter's five-second timeout. A full cycle remains below the documented MEXC contract API rate limit in normal operation. Provider errors are logged by market and counted.
- Store venue, contract ID, interval, UTC open/close/retrieval times, OHLCV, and source. A unique key on venue, contract ID, interval, and open time makes replay idempotent. A duplicate must not overwrite the original observation.
- Record cycle start/end, successes, provider failures, and database status. If persistence fails, the cycle fails visibly; no success heartbeat is written.
- The API's collector status endpoint reports disabled when no DB is configured, unavailable when the DB fails, and last completed cycle when available.
- No exchange credentials, private APIs, signals, alerts, or trading operations.

## Failure behavior

- An empty/invalid/stale provider response contributes a failure for that market. Other markets continue.
- Database errors abort persistence and surface in logs and the next status query. The worker retries on the next cycle with bounded delay.
- The worker is single instance for now; no multi replica coordination is claimed.

## Acceptance

- Unit tests cover partial provider failure, sequential scheduling, 14 target combinations, and store failure propagation.
- PostgreSQL integration tests verify schema creation, insertion, idempotency, and cycle status.
- CI starts a temporary PostgreSQL service; local setup is documented.
- Docker Compose defines PostgreSQL, API, and one collector with a persistent named volume and a health check. Backup/restore is a later release gate.
