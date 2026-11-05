# Spec 020 — Swap-derived research features

`cluster_radar.signals.features.extract_swap_features` derives the two PRD features that are
observable from normalized swaps alone, so research reports no longer need every feature
pre-normalized by hand. Offline only: no provider requests, database writes, alerts or approval.

Windows: current `(as_of-L, as_of]`, prior `(as_of-2L, as_of-L]`. Swaps use the existing
first-observation resolution (`first_observations`, shared with `swap_metrics`): knowledge after
`as_of` is invisible, later corrections cannot rewrite first evidence, conflicts fail.

- Dump `buyer_exhaustion` = clamp(1 - current_buy_usd / prior_buy_usd, 0..1). Unavailable when
  any buy lacks USD or the prior baseline is empty/zero (never treated as zero or exhaustion).
- Pump `new_owner_participation` = share of distinct current buyers not observed (buying or
  selling) in `[history_start, as_of-L]`. Unavailable with no current buyers.

`history_start` must cover both windows (`<= as_of-2L`); otherwise both features are
unavailable (`insufficient_history_coverage`). "New" means new within supplied history only.
Features share independence group `swap-flow:<mint>`, carry swap references and derived
source provenance, and independence stays UNVERIFIED. Formulas are unvalidated hypotheses.
Remaining PRD features (independent_buying, wallet_quality, organic_volume, holder
distribution, liquidity, price/volume, structure) need other evidence and stay missing, so
reports remain INCOMPLETE and approval/alerts stay off.

Acceptance: decline/growth/silence clamping, seller-counts-as-seen, history coverage guard,
missing USD, point-in-time knowledge, dedup provenance, mint filtering, scoring integration.
