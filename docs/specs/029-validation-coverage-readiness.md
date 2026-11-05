# Spec 029 — Offline validation coverage readiness

Assess bounded format-1/2 datasets through the existing comparison parser/engine.
Produce a read-only diagnostic artifact, not a trading/paper approval or statistical
sample adequacy judgment. Keep source timestamps intact; never repair gaps or turn
late backfills into earlier observations. No database/provider calls or alerts.

For each decision report core feature availability/reason, visible target history,
closed target candles not yet known, BTC relative-strength availability, independent
outcome status, boundary purge and comparison eligibility. Classify outcomes as
available, not_closed_by_evaluation, not_retrieved_by_evaluation or missing_from_dataset.
Later revisions cannot masquerade as missing first observations.

Summarize each development/holdout split with decision, purged, eligible and missing
counts; report distinct/repeated outcome windows without claiming independence.
Summarize target/BTC first-visible candles, first/last times, source names, retrieval
lag and internal missing intervals/gap runs (at most 20 details with truncation flag).
Compute gaps arithmetically from observations, never enumerate arbitrarily large
empty ranges. Preserve actual cutoff exclusions, including future rows in offline
input. Duplicate observations do not inflate inventory or warmup coverage.

coverage_complete requires both splits to contain eligible samples and every
nonpurged decision to have core features, outcome and BTC relative strength.
partial_coverage requires at least one eligible nonpurged sample; otherwise
insufficient_coverage. Separately indicate whether both splits have any comparison
samples. Neither status proves adequate sample size, authentic data, profitable
signals or execution feasibility. Always keep production_ready false, signals off
and dataset origin NOT_VERIFIED. Hypothetical costs cannot improve readiness.

Record version, dataset/config hash and cutoffs. CLI performs a bounded input read
and exclusive new output creation. Acceptance: complete/partial/empty coverage,
gaps, backfill delays, independent missing/pending outcomes, BTC gaps, duplicate
window diagnostics, split purge, future input, bounded gap detail, cost neutrality,
CLI no-overwrite and full regression/PostgreSQL/frontend CI.
