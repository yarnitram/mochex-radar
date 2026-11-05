# Spec 026 — Stored validation dataset export

Provide a manual read-only PostgreSQL export for the spec 025 comparison CLI.
Select one registered core MEXC futures instrument plus BTC context, one 15m/1h
interval, explicit UTC decision start/end, holdout and evaluation cutoffs. Decisions
are spaced by one interval; end must align with start; maximum 1,000 decisions.
Evaluation cannot exceed actual current time or precede the last decision.

Fetch a bounded range from 22 intervals before the first decision through the
evaluation cutoff. Preserve source, values and close/retrieval times exactly.
Rows closed or retrieved after evaluation are invisible. Use a single read-only
repeatable-read transaction, statement timeout, parameterized indexed identity/time
filters, deterministic ordering and limit 10,001; reject overflow rather than
silently truncating. Never initialize/migrate/write database schema or call a feed.

Write only a new JSON dataset in the format accepted by feature_validation.
Validate it through the comparison engine before creating the file. Reject empty
datasets, invalid identities/values/config and oversized serialized files. Missing
BTC, gaps and late backfills stay visible as missing evidence, not fabricated data.
Require DATABASE_URL in private environment; sanitize connection failures and never
print connection strings. Existing output must not be overwritten.

Acceptance: hand-built export/replay roundtrip; exact timestamp preservation;
future-close/retrieval exclusions, pair/interval isolation, bounds and no-overwrite;
PostgreSQL integration for the actual query, plus full regression/CI.

No configured local database is available at implementation time. CI exercises a
temporary database; real market coverage and profitability remain unvalidated.
