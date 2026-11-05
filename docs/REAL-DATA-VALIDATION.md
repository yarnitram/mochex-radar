# Real-data validation runbook

Status: tooling implemented; actual market evaluation not yet run. No local
DATABASE_URL, private .env file or reachable PostgreSQL instance was present at
the implementation check. Do not treat synthetic/CI results as market evidence.

## Prerequisites and collection

Use an existing initialized Mochex Radar database with stored MEXC futures
observations. Set DATABASE_URL only in the private runtime environment. The export
command never initializes tables, collects data or sends alerts. A read-only
database account is preferred. No exchange account credentials are required.

Choose the instrument, interval, decision schedule and chronological holdout before
evaluating results. The current exporter requires at least two interval-spaced
decisions with a holdout after the first and no later than the last. Record the
selection rationale in project notes to disclose universe/threshold selection bias.

The ordinary collector and optional manual backfill can supply history. Preserve
their actual retrieved_at timestamps. Backfilled candles cannot be used at decisions
before download. An initial backfill can warm up later forward observations, but
cannot create an earlier live track record. Observe enough future data to cover
both development/holdout decisions and their outcome candles. Wait until outcome
candles are closed and collected before choosing evaluation_at.

Use actual UTC ISO timestamps ending in Z or +00:00. Decision end must equal start
plus a whole number of intervals; max 1,000 decisions. Missing BTC context does not
invalidate other features; relative strength remains unknown. Current collection
includes BTC 15m only, so 1h BTC context may be absent. Gaps and stale features are
excluded rather than repaired or assumed to be zero.

## Export and compare

Create an ignored work directory. Replace every timestamp placeholder below with
your preselected actual cutoffs; the commands never infer dates from current data.

```text
python -m mochex_radar.validation_export --market SOL_USDT --interval 15m --decision-start <UTC_START> --decision-end <UTC_END> --holdout-at <UTC_HOLDOUT> --evaluation-at <UTC_EVALUATION> --output work/sol-dataset-v1.json
python -m mochex_radar.feature_validation --input work/sol-dataset-v1.json --output work/sol-report-v1.json
```

Both output files must be new. Export uses a read-only snapshot, a five-second
query timeout, 10,000-row cap and five-MB serialized cap. Narrow the range if a
limit is reached. SQL filters close/retrieval cutoffs and preserves stored source
and values. The current candle table stores one immutable first-inserted row per
market/interval/open time; the export does not reconstruct missing observations
or prove that the upstream data was historically correct.

## Review and archive

Keep the exact dataset and report together in private research storage outside Git.
The report includes dataset/config hash, feature/report versions, cutoffs, per-row
evidence, excluded reasons, state groups and same-population unconditional baselines.
Record the source commit, selection rationale, coverage and failed/missing cases in
Command Center. Do not store the private connection string in notes or artifacts.

Inspect counts before comparing means. Outcomes may overlap and are not independent
trials. A positive mean or difference does not validate a strategy: returns are
gross next-boundary candle returns with no spread, fees, funding, slippage or
execution simulation. Statistical tests, larger independent holdouts, dataset/run
registry, cost/depth modeling and forward paper validation remain later work.
This process does not enable signals, alerts or live trading.
