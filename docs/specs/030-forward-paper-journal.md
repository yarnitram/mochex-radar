# Spec 030 — Manual forward paper research journal

Register an explicit plan before its first decision using the local UTC clock.
Plan fixes one core MEXC futures instrument, 15m/1h interval, 2..1000 equally spaced
decisions, chronological holdout, 1..300-second capture grace, caller-declared data
kind, selection rationale and optional explicit cost scenarios. Freeze engine and
tracker source fingerprints. No CLI clock override or backdated registration.

Capture a bounded caller-provided candle snapshot only during the scheduled
decision's grace window and before its outcome closes. Compute features using
close/retrieval cutoff at the decision, not capture time. Record missing features
as unavailable; record all scheduled slots in summaries so missed capture cannot
disappear. Reject snapshot observations with future close/retrieval timestamps.

Record a separate outcome after its next-boundary candle closes. Outcome must be
present, known by recording time, and use the first supplied observation when
revisions exist. Gross/cost comparisons stay null for unavailable captured features
and for holdout-boundary crossings. Never recompute captured features with later
data. No entry/exit fill, strategy portfolio, leverage, depth or execution claim.

Store exact snapshot bytes and hash-linked records in exclusive per-plan/stage/slot
directories; completion record is written last. Refuse overwrite/duplicate stages.
Incomplete directories remain visible and never silently repaired/deleted. Verify
plan identity, stage identity, snapshot hash and captured-record linkage on reads;
require current source match for new captures/outcomes. Summary distinguishes
scheduled, awaiting capture, missed, captured/pending, complete and incomplete.
Hashes establish consistency, not provider provenance or an attested clock.

Manual snapshot schema: {format_version: 1, candles: [...existing candle schema]}.
Maximum 5MB/10,000 rows; plans 64KB and stage records 128KB. CLI create/capture/
outcome/summary only; summary to new file refuses overwrite. Private local ignored
work paths; no provider calls, database writes, signals, alerts, signing or trading.
This is tracking infrastructure, not a running forward-validation campaign.

Acceptance: future-only plan registration, grace deadline/clock guards, immutable
snapshots and unavailable captures, independent later outcomes, no future knowledge,
split isolation, source/tamper/duplicate/incomplete checks, missed-slot accounting,
synthetic CLI lifecycle and full regression/PostgreSQL/frontend CI.
