# Spec 017 — Partial Solana mint authority evidence

## Scope

Add read-only getAccountInfo authority evidence from the fixed public mainnet RPC,
requesting full base64 data at finalized commitment. No transaction creation,
signing, submission, private keys or exchange account access. RPC is an external
data source, not cryptographic proof. Public rate limits may change; dedicated
production RPC support remains a deployment prerequisite.

Validate mint/owner public keys decode to 32 bytes. Decode only original SPL Token
Program non-executable initialized mint accounts of exactly 82 bytes. Mint and
freeze authority COption fields have offsets 0 and 46. Recognized absent authority
is DISABLED; present option records its public authority address. Malformed layout,
token accounts, unsupported owners, missing/uninitialized accounts and Token-2022
extensions remain unknown with explicit reasons. Provider/envelope/encoding errors
return unavailable, not fabricated evidence. These observations do not infer common
wallet ownership, creator identity, liquidity safety or stage-specific authority policy.

Even both disabled authorities keep security_status=UNKNOWN and
approved_pump_watch=false. Critical risk, transfer restrictions, Token-2022,
liquidity and controller checks are not complete. No signal or alert is produced.

## API and budget

`GET /api/v1/security/solana/{mint}/authorities` is disabled by default. Enable
SOLANA_AUTHORITIES_ENABLED=true with DATABASE_URL; missing storage prevents startup.
SOLANA_AUTHORITY_DAILY_REQUESTS defaults to 100 shared UTC-day attempted requests.
Database-backed budget uses a dedicated source key and 1.1s reservation spacing.
Every instance must use the same limit. Failed/cancelled calls consume reservations;
DB budget failure prevents RPC calls. There are no automatic retries or caches.
Invalid key => 422, local ceiling => 429, RPC/storage failure => 503.

Success requires evidence storage, returns persisted=true/partial=true, and retains
request-known time, RPC context slot, owner, authorities, parser version and raw
response SHA-256 hash. Slot is not creation time. Complete raw bodies are not archived.

`GET /api/v1/security/solana/{mint}/authorities/history?as_of=<UTC>&limit=10`
performs no provider calls. Both known_at and DB ingestion must precede the cutoff.
Limit is 1..100. Evidence is current for 15 minutes relative to that cutoff and
then stale; stale records are retained. A late import cannot appear in an earlier
replay. This freshness rule does not turn partial evidence into a security approval.

## Persistence and tests

Add immutable normalized observations keyed by mint/source/known_at. Identical
inserts are idempotent; conflicts fail. Payload has a DB constraint preserving
UNKNOWN overall security and false approval. Mint/known_at index bounds history.

Upstream fixtures follow official RPC envelope and Rust mint layout. Test present,
absent/freeze authorities, executable/token accounts, malformed RPC/slot/option data,
Token-2022 unknown behavior, public-key validation, request ceilings and HTTP failures.
Platform tests cover opt-in/storage guards, budget preventing transport, 422/429/503,
storage failure, immutable PG history, ingestion cutoffs, staleness and DB guardrails.

## Verified references (2026-11-05)

https://solana.com/docs/rpc/http/getaccountinfo
https://solana.com/docs/tokens
https://solana.com/docs/references/clusters
https://github.com/solana-program/token/blob/main/interface/src/state.rs
https://github.com/solana-program/token/blob/main/interface/src/lib.rs
https://github.com/solana-program/token-2022/blob/main/interface/src/lib.rs
