# Spec 007 — Cluster Radar source integration and DEX pool context

## Scope

Include a versioned snapshot of the preserved sibling project's package and tests
in the Mochex Radar distribution. Preserve the original PRD and provenance.
Raise the platform runtime floor to Python 3.12 to match Cluster Radar.

## Endpoint

`GET /api/v1/dex/solana/{mint}/pools` uses the shared public DEX Screener adapter.
It is disabled unless `DEX_LOOKUP_ENABLED=true`; `DEX_LOOKUP_MAX_REQUESTS` defaults
to 100 attempted requests per API process lifetime. The instance serializes and
paces calls. Restart resets the budget. Keep the service on trusted internal
access and use one API worker; an aggregate persistent budget is needed before
scaling. Compose keeps its existing loopback-only binding.

Responses retain explicit missing values, decimal strings, known-at timestamps,
stage and provenance. Security is always UNKNOWN and approved Pump Watch false;
pool context alone cannot approve a signal. Invalid mint => 422; disabled or upstream
failure => 503; exhausted local budget => 429. Provider errors never return empty
success data. No retries, credentials, wallet access or paid endpoints.

This is mint lookup, not exhaustive new-token discovery. It does not infer Meme/AI
categories from names or social descriptions. Token age is unavailable in this feed.

## Acceptance

- Imported offline upstream contract tests pass alongside existing platform tests.
- API tests cover disabled mode, valid serialization, local budget, invalid mint,
  provider failure and conservative security fields.
- Distribution and Docker build context include the imported package.

Official provider contract: https://docs.dexscreener.com/api/reference (checked 2026-11-05).
