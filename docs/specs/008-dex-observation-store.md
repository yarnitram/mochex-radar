# Spec 008 — Immutable DEX observation store

Persist each successful optional DEX lookup when DATABASE_URL is configured.
Initialize the additive PostgreSQL schema at startup when DEX lookup is enabled.
No configured database => lookup returns `persisted: false`. Storage failures
return 503. Provider failures never write successful observations.

Identity is mint/pool/source/known_at. Exact repeats are idempotent; conflicting
content rolls back the transaction. Decimal values remain strings in the
normalized JSON and a SHA-256 digest records content. This is normalized evidence,
not a raw provider response archive. No empty-result or failed-request audit yet.

`GET /api/v1/dex/solana/{mint}/history?as_of=<UTC timestamp>&limit=100` returns at
most 1000 observations, newest first. Both provider-known time and database
ingestion time must be at or before the cutoff. A late import cannot appear in
an earlier replay. Index (mint, known_at DESC) supports the bounded history query.

Acceptance: PostgreSQL roundtrip, duplicate insert, conflicting immutable content,
and ingestion cutoff tests in CI. No unattended polling, retention deletion, or
historical universe completeness is claimed by this milestone.
