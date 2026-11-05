# Spec 025 — Offline core feature outcome comparison

Build a bounded, deterministic research report for one registered core MEXC
USDT futures instrument and 15m/1h candles. Reuse core-features-v1 at explicit UTC
decision times. Feature inputs must be closed and retrieved by the decision.
Do not rewrite retrieval times to make historical backfills appear observable.

Separate outcome evidence from feature evidence. At each decision, select the
first interval boundary at or after that decision and measure that candle's
open-to-close return. Require a completed valid candle retrieved by evaluation_at.
This is a descriptive gross price return, not an executable trade or net P&L.
No fees, spread, funding, slippage or latency simulation is claimed.

Require an explicit chronological holdout boundary. Exclude decisions whose
outcome crosses that boundary. Compare each volatility/structure state against
the unconditional baseline on exactly the same eligible split population.
Report sample counts, missing reasons, mean gross return and positive fraction;
empty groups remain null. Never optimize thresholds or claim statistical alpha.

Reject non-UTC/invalid/nonfinite candles, ambiguous equal-time revisions,
duplicate/unordered decisions, unknown identities, unsupported intervals and
oversized datasets (10,000 candles total; 1,000 decisions). Record canonical
dataset/config hash, feature/report versions, split and evaluation cutoffs.
No network, storage mutation, alerts, approvals or trading. CLI accepts an
explicit JSON dataset and creates a new report, refusing overwrite.

Acceptance: hand-computed returns and baselines; holdout isolation and boundary
purge; future retrieval and backfill exclusion; missing outcomes; revision/order
determinism; strict input/bounds; no-overwrite CLI and full regression/CI.
