# Spec 010 — Scheduled configured-mint DEX scanner

Run `python -m mochex_radar.dex_worker --once` for one scan or omit `--once` for
scheduled scans. DATABASE_URL and a nonempty `config/dex-watchlist.json` are required.
`DEX_WATCHLIST_PATH` or `--watchlist` overrides the path. File version is 1, max 20
unique Solana mints, with explicit categories and category_source:

```json
{
  "version": 1,
  "tokens": [{
    "mint": "So11111111111111111111111111111111111111112",
    "categories": ["unclassified"],
    "category_source": "operator:manual-context-example"
  }]
}
```

The example is wrapped SOL for context validation, not a Meme/AI recommendation.
Categories are operator claims (`meme`, `ai`, `unclassified`) with provenance;
the worker never classifies from symbol or name. The committed watchlist is empty.

Compose service is optional: after configuring targets, use
`docker compose --profile dex up --build -d`. It mounts the watchlist read-only.
Config changes require worker restart. `DEX_SCAN_INTERVAL_SECONDS` defaults to 900
and must be at least 60. Shared `DEX_LOOKUP_DAILY_REQUESTS` defaults to 100 including
API lookups. At 900 seconds one mint needs up to 96 attempts/day; multiple mints
need a longer interval or an explicitly raised ceiling. Requests are public only.

Each target gets a scan record: success, empty, provider_error, budget_exhausted,
or skipped_budget. An exhausted cycle skips remaining provider calls. Successful
pool observations and their audit record commit in one transaction. A persistence
error stops the worker; Compose retries at most three times. Interrupted calls
may consume reserved budget without a completed scan record. Restart scans the
configured targets again, retaining existing observations and durable budget.

`GET /api/v1/dex/scans?limit=100` returns up to 1000 recent audit records. Without
DATABASE_URL it reports disabled; before schema initialization it returns 503.
This is new-pool discovery for configured mints, not an exhaustive new-token feed.
Wallet history, independent security checks, and Pump/Dump scores remain separate.

Acceptance: config validation, empty/error/budget outcome isolation, aggregate
budget reuse, PostgreSQL audit roundtrip, and rollback of observations when the
audit insert fails.
