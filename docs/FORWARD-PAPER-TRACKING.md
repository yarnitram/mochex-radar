# Manual forward research tracking

Status: local journal infrastructure only. No real forward campaign has been
started or validated. Opt-in stored-snapshot scheduling is implemented;
authenticated data acquisition, depth/impact and actual execution simulation remain separate work.

## Predeclare a plan

Use a private ignored `work/` directory. Create a JSON plan with exactly these
fields; replace the UTC placeholders with future ISO timestamps before running:

```json
{
  "format_version": 1,
  "asset_id": "cex:mexc-usdt-futures:SOL_USDT",
  "interval": "15m",
  "decision_start": "<FUTURE_UTC_START>",
  "decision_end": "<FUTURE_UTC_END>",
  "holdout_at": "<UTC_HOLDOUT_AFTER_START_AND_AT_OR_BEFORE_END>",
  "capture_grace_seconds": 30,
  "data_kind": "observed",
  "selection_rationale": "Record the instrument, schedule and holdout rationale before observing outcomes.",
  "cost_scenarios": []
}
```

Use `synthetic` for test data. `observed` is a caller declaration and does not
authenticate the provider. Plans require 2..1000 interval-spaced decision times,
a holdout after the first and at/before the last, and a 1..300-second capture grace.
No costs are inferred when the explicit list is empty; add scenarios using the
spec-028 schema before registering if cost sensitivity is intended.

```text
python -m mochex_radar.paper_journal create --registry work/paper-plans --config work/paper-config.json
```

Registration must occur before the first decision. The command returns PLAN_ID;
the directory stores a content-derived immutable plan, local registration time,
source fingerprints and fixed assumptions. Preserve the source commit. There is
no CLI clock override. A local clock and hashes are not independently attested
evidence: administrators can alter files/clock, and no external signature exists.

## Capture then record outcomes separately

Prepare a bounded snapshot from a trusted read-only acquisition path:
`{"format_version": 1, "candles": [...]}`. Each row uses the existing candle JSON
schema (identity, interval, ISO UTC open/close/retrieved timestamps, decimal-string
OHLCV and source). Empty snapshots are permitted to record unavailable features.
No future close/retrieval timestamps are accepted. Snapshot generation is manual
in this increment: the journal does not contact providers or query a database.

```text
python -m mochex_radar.paper_journal capture --plan work/paper-plans/<PLAN_ID> --index 0 --snapshot work/capture-snapshot.json
python -m mochex_radar.paper_journal outcome --plan work/paper-plans/<PLAN_ID> --index 0 --snapshot work/outcome-snapshot.json
python -m mochex_radar.paper_journal summary --plan work/paper-plans/<PLAN_ID> --output work/paper-summary-v1.json
```

Indices are zero-based and fixed by the plan. Capture must occur within the
scheduled grace window and before the outcome closes. Features use only candles
closed and retrieved at/before the decision, even if capture is slightly later.
Late backfilled history cannot be made visible by changing timestamps.

The outcome is the open-to-close return of the first interval starting at or after
the decision, using the earliest observation supplied for that candle. Record it
only after its close and retrieval. A missing outcome raises an error and remains
pending; later recording may retry. Captured features never get recomputed with
later data. Captured unavailable features and holdout-crossing outcomes retain null
returns/cost estimates. All price/cost results remain illustrative research values.

## Integrity and coverage review

Snapshot bytes and stage records are created exclusively; duplicates cannot
overwrite a capture/outcome. A completion record is written last. Interrupted
directories stay incomplete and block reuse. Preserve them for review rather than
silently removing failed observations. New records require matching source; source
changes require a new predeclared plan. Existing summaries can inspect old source
plans without pretending to replay them under new code.

Summary lists every scheduled slot, including awaiting, missed, pending, excluded
and incomplete observations. It verifies hashes and capture/outcome linkage; any
integrity failure stops the read. Summary outputs must be new files. Never drop
missed/unavailable samples or count these manual records as authenticated fills.
No account access, signing, orders, signals or alerts are enabled. Portfolio P&L,
position sizing, short execution, leverage, liquidation, market impact, reliable
long-running operations and statistically adequate real-data validation are unfinished.

## Optional stored-observation worker

`python -m mochex_radar.paper_worker --plan work/paper-plans/<PLAN_ID> --once`
captures due decisions and records available post-close outcomes from PostgreSQL
only. Supply DATABASE_URL privately. Omit `--once` for polling; default is five
seconds, maximum five actions per cycle, with due captures prioritized. A query
that finishes after capture grace does not backdate a record. Database failures
leave missing evidence visible and retry on later cycles. Invalid source/journal
state stops the worker. No schema initialization or provider request occurs.

Optional Compose profile `paper` mounts private `work/paper-plans` at `/research`.
Set PAPER_PLAN_ID to an existing future plan. Before starting, verify the mounted
directory is writable by the image's runtime user. Run one configured worker per
plan with shared persistent storage; separate filesystem copies are separate
journals. Exclusive stage creation protects duplicate writes to the shared journal.
Do not enable the profile as part of a synthetic/container smoke test.
