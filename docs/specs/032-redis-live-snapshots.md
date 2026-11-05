# Spec 032 — Redis provisional live snapshots

Optional Redis stores latest public intrabar observations only; PostgreSQL remains
durable candle/evidence/outbox authority. Streamer publishes accepted MEXC updates;
Lua compare-and-set rejects older/equal observations across publishers. Keys expire
after 120 seconds; read age under 30 seconds is current, older is stale, absent or
invalid is missing. All snapshots are provisional/not finalized and cannot feed
closed-candle research, signals or paper outcomes.

GET /api/v1/live/core returns seven registered pairs from Redis only, with explicit
disabled/unavailable states and interval validation. Redis outage must not prevent
streamer rollover persistence; use bounded socket timeouts and 30-second publish
failure backoff. Redis carries no credentials, alerts or durable work queues.
Compose Redis has no host port and disposable state. Default restarts lose live
state safely, then fresh publisher observations repopulate it.

Tests: concurrent order/idempotency, stale/future/invalid payloads, key expiry,
Redis failure plus durable candle rollover, API disabled shape, real Redis/PG CI.
Worker scheduling continues to rely on exclusive durable journal writes; this
increment does not claim Redis leases alone provide distributed exactly-once work.

References: https://redis.io/docs/latest/develop/clients/redis-py/async/
and https://redis.io/docs/latest/commands/eval/ (checked 2026-11-05).
