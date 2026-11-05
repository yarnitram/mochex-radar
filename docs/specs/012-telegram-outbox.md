# Spec 012 — Operational Telegram outbox

## Scope and guardrails

Durable delivery foundation for explicit `SYSTEM_TEST` and `DATA_QUALITY` notices.
No market-signal producer is connected; Pump/Dump notice types are rejected.
Messages retain asset identity, rule version, evidence, known-at and expiry times,
operational category, unassessed confidence and UNKNOWN security. Plain text only,
no formatting interpretation, disabled link previews and paid broadcast disabled.
Templates must fit 4096 UTF-16 code units; notices live at most 24 hours.

## Durable behavior

Enqueue deduplicates by asset/kind/rule/30-minute known-at window. A serialized
30-minute enqueue cooldown also prevents duplicates around adjacent windows.
Duplicates retain their original body. Future and expired notices are rejected.
Database stores no bot token or chat ID; destination alias is `primary`.

Claim uses a short transaction, shared delivery gate and `FOR UPDATE SKIP LOCKED`.
Attempt count increments before transport. All sender processes must use the same
`TELEGRAM_DAILY_ATTEMPTS` (default 100); the shared UTC-day limit and one-second
reservation spacing survive restarts. Cancellation consumes the reservation.
Each notice has at most four attempts and a 60-second worker lease.

Confirmed Telegram success becomes sent. Connect failures or 429 can retry after
max(exponential backoff, provider retry_after), without blocking a DB transaction.
429 also postpones the global delivery gate. Permanent rejection becomes failed.
Read/write timeout, malformed confirmation, server failure or abandoned lease
becomes uncertain and is never automatically resent. Delay beyond 24 hours is
treated as unsupported and held uncertain. Expired pending notices never send.

There is no exactly-once delivery guarantee: Telegram acceptance followed by a
database failure remains uncertain. An operator must investigate uncertain rows;
there is deliberately no automatic or HTTP requeue endpoint. Queue status is
available at `GET /api/v1/alerts/status`, with counts only and no message content.

## Operator workflow

1. Configure a private DATABASE_URL; run `python -m mochex_radar.alert_worker --enqueue-test --dry-run`.
   This explicitly enqueues a test and prints pending public notice bodies. Dry-run
   alone does not claim rows, increment attempts, mark delivered or use HTTP.
2. Optional `--notice-file <path>` accepts an operational notice JSON matching
   `ResearchNotice`. Never embed secrets in notice content.
3. To enable actual sending later, configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
   securely, set TELEGRAM_SEND_ENABLED=true, and invoke `--send --once` for a single
   due notice or `--send` for a worker. This requires the operator's delivery setup.
4. Compose `alerts` profile is optional and fails closed when opt-in or credentials
   are missing. No credentials are committed. Do not print resolved Compose config
   after adding secrets. Keep one configured primary destination; review pending
   notices before changing bot or chat configuration, since pending rows use the alias.

Worker initializes additive schema. Startup/DB errors log only sanitized error
classes. HTTPX URL logs redact bot tokens; raw Telegram errors and chat IDs are
not persisted or logged. Recovery holds ambiguous notices for manual review.

## Acceptance

- Synthetic official-schema fixtures cover successful send, 429 retry_after, 403,
  malformed replies, timeout ambiguity and token redaction.
- Dry run never dispatches; sending requires flag plus environment opt-in.
- PostgreSQL verifies dedup/cooldown, nonmutating preview, concurrent claims,
  daily limit, global 429 pause, four-attempt cap, expiry and abandoned leases.
- No live message is sent during automated verification.

Official contract checked 2026-11-05:
https://core.telegram.org/bots/api#sendmessage
https://core.telegram.org/bots/api#responseparameters
