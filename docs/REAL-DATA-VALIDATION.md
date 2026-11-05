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

## Register and reproduce a run

For a private local registry, use the ignored work directory:

```text
python -m mochex_radar.research_registry create --registry work/research-runs --input work/sol-dataset-v1.json --data-kind observed --rationale "Preselected SOL 15m observation window and chronological holdout; record the exact selection rationale here"
python -m mochex_radar.research_registry verify --bundle work/research-runs/<RUN_ID> --replay
```

Use `--data-kind synthetic` for the repository example fixture. The observed label
is caller-declared and does not establish provider authenticity. Keep secrets out
of the rationale. Registration outputs a content-derived RUN_ID and saves the
original dataset bytes, report, source fingerprints and completion manifest.
Repeated registration of the same content/rationale/source is refused.

Verification checks hashes and recorded run identity. Replay additionally requires
matching engine source and reproduces the report exactly. Preserve the source
commit alongside the bundle so it can be checked out later. Hashes provide
consistency checks, not a signature or protection against someone rewriting the
whole registry. Interrupted bundles without a complete manifest remain incomplete;
they are never silently overwritten or automatically deleted. Registry files use
ordinary filesystem permissions; put them in private research storage.

## Compare explicit cost assumptions

Format 1 remains gross-only. To run hypothetical cost sensitivity, make a new
dataset with `format_version: 2` and `cost_scenarios`. Keep the original export.
Use `tests/fixtures/core-feature-costs.json` as a synthetic schema example. Every
scenario must specify entry/exit fees, entry/exit half-spreads, entry/exit adverse
slippage and the total assumed interval funding cost, all as basis-point strings.
Do not copy the invented example values as your actual account fee schedule.

The ordinary comparison and registry commands accept both versions. Format 2
records the assumptions in config hashes and produces per-row and per-split/group
estimated net returns alongside the unchanged gross comparison. Missing or excluded
outcomes stay unknown. No scenario is selected as a winner, and no cost is inferred
from a venue/account tier. Record the rationale before examining holdout results.

The model assumes an illustrative unlevered long and adverse reference-price
changes. Exit fees apply to estimated exit notional; entry fees and signed funding
cost apply to entry notional. Negative funding cost represents an assumed credit.
Funding is a total interval assumption, not a prorated advertised rate. Candle
prices do not establish order-book mids or fills. This is cost sensitivity, with no
observed depth, price impact, margin, liquidation, short-fill or latency simulation.
Independent real-data evaluation and forward paper validation remain necessary.

## Inspect coverage before interpreting results

Run the offline readiness check on the exact exported dataset:

```text
python -m mochex_radar.validation_readiness --input work/sol-dataset-v1.json --output work/sol-coverage-v1.json
```

Keep the coverage artifact alongside the dataset/report and record its dataset/config
hash. The command accepts format 1 and 2, makes no database/provider call, and refuses
to overwrite output. It diagnoses feature warmup/gaps, closed observations not yet
retrieved at each decision, missing BTC relative-strength context, independent
missing/late/pending outcomes and deliberate holdout-boundary exclusions.

`coverage_complete` means all nonpurged decisions have core features, BTC context
and an outcome, and each split has at least one eligible comparison sample.
`partial_coverage` means at least one eligible sample exists but some coverage
requirements are unmet; `insufficient_coverage` means none are eligible. The
separate both-splits flag shows whether each split has any comparison sample.
These are data-completeness checks, not minimum statistical sample-size thresholds.
Missing BTC can leave core comparisons usable while coverage remains partial.

Inventory gap counts cover first-to-last visible candles only. Leading/trailing
history is not presumed complete. At most 20 gap runs are listed with an explicit
truncation flag; counts include all internal gaps. Future-close/retrieval observation
counts may overlap. Identical observations and later revisions cannot inflate unique
history counts. Repeated outcome windows are disclosed and must not be counted as
independent trials. Cost scenarios never improve coverage.

Dataset origin remains NOT_VERIFIED and production_ready remains false even with
complete coverage. Diagnose missing evidence and preserve failures before moving to
independent evaluation and forward paper tracking; do not relabel synthetic results
or rewrite retrieval timestamps to pass a coverage check.
