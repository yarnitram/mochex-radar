# Spec 015 — Bounded Solana profile discovery

## Provider contract and limitations

Official DEX Screener reference checked 2026-11-05:
https://docs.dexscreener.com/api/reference
`GET /token-profiles/latest/v1` is documented at 60 requests/minute. A public
HTTP 200 smoke returned an array of 30 records, despite the rendered reference
showing an individual profile schema. Contract fixture is synthetic and uses
documented chainId/tokenAddress fields. Parser accepts an array, rejects oversized
or malformed windows, selects Solana, and deduplicates mints within that response.

A profile observation is not a token birth, trust assessment, or Meme/AI label.
Coverage has profile/marketing bias, no supported cursor here, and no historical
universe completeness. Candidates stay unclassified and security UNKNOWN.

## Persistence and selection

Store the entire valid Solana window before selecting any pool-scan targets.
Immutable poll and per-mint observation rows retain timestamps, source, response
hash and input/discovered counts. Full raw bodies are not archived. Failed and
budget-exhausted polls have null counts rather than pretending to be empty success.
Poll ID replay is idempotent and conflicting response hashes fail the transaction.

The current mint catalog records first observation/ingestion, last observation
and last completed scan. It is a mutable convenience view, not the replay source.
Future replays must use immutable profile observations plus poll ingestion cutoffs.
No token/pool age is inferred from first observation. Every observed mint is kept,
including those not selected for deeper scanning.

Select at most three candidates by default from the current poll, preferring
unscanned or least recently scanned mints. Pool observation/audit/progress commit
atomically. Skipped/exhausted budgets do not advance scan progress. One discovery
worker is supported; replicas could select the same candidate and waste budget.
Candidates falling out of later provider windows are retained but may remain unscanned.

## Budgets and operation

Optional Compose profile `discovery`, or `python -m mochex_radar.profile_discovery --once`.
DATABASE_URL is mandatory. Defaults: PROFILE_POLL_SECONDS=3600,
PROFILE_DAILY_REQUESTS=24, PROFILE_MAX_POOL_SCANS=3 (range 1..20).
Profile requests use an independent persistent UTC-day budget and 1.1s spacing.
Pool scans use the existing shared DEX_LOOKUP_DAILY_REQUESTS budget (default 100),
including API and curated watchlist scans. All workers must share these settings.
At hourly polling default deeper scans use at most 72 pool attempts/day, leaving
28 from the default pool budget for other consumers. Failed HTTP attempts count.
No automatic retry within a cycle; subsequent scheduled polls are separate attempts.
Storage errors stop the worker and Compose retries up to three times.

Read-only APIs: `/api/v1/discovery/profiles/polls?limit=100` and
`/api/v1/discovery/profiles/mints?limit=100&offset=0`. Limits cap at 1000; catalog
offset caps at 10000. Catalog explicitly reports coverage=profile_window_only,
category=unclassified, security_status=UNKNOWN and approved_pump_watch=false.
Existing DEX scan history displays the selected candidates and their source tags.

## Acceptance

- Upstream adapter fixture tests and lint pass; source snapshot provenance updated.
- Persist before selection; failed feed/storage never promotes candidates.
- PostgreSQL tests verify full-window retention, idempotency/conflict handling,
  least-recent scan selection, atomic progress and independent profile pacing.
- Existing provider budget tests still pass after configurable spacing is added.
- No unattended scanner, paid request, live alert or trading is enabled by this phase.
