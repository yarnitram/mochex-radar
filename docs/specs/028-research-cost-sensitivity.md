# Spec 028 — Explicit research cost sensitivity

Extend offline core comparisons with optional dataset format 2 containing 1..10
caller-supplied cost scenarios. Format 1 gross reports remain unchanged. Format 2
requires unique bounded names and all seven cost inputs as decimal strings:
entry/exit fee, entry/exit half-spread, entry/exit adverse slippage and funding cost
in basis points. No default fee schedule or MEXC account tier is inferred.
All except funding must be 0..1000 bps; funding may be -1000..1000 (credit negative).
Reject missing/extra inputs, nonfinite/nonstring values and precision over 8 decimals.

Use an illustrative unlevered long, entry-notional-normalized sensitivity model:
entry_multiplier = 1 + (entry_half_spread_bps + entry_slippage_bps)/10000;
exit_multiplier = 1 - (exit_half_spread_bps + exit_slippage_bps)/10000;
exit_value = (1 + gross_return) * exit_multiplier / entry_multiplier;
net_return = exit_value * (1 - exit_fee_bps/10000) - 1
             - entry_fee_bps/10000 - funding_cost_bps/10000.

Funding is the caller-assumed total over the outcome interval, not a rate prorated
or tied to a venue funding clock. Candle prices are illustrative reference prices,
not observed book mids/fills. No liquidity, queue, impact, sizing, margin, leverage,
short execution, latency or liquidation simulation is provided.

Preserve gross rows/features/splits, exclude the same missing/boundary samples,
and retain unknown estimates as null. Provide per-scenario rows and split/group
net means, positive fractions and cost drag, including empty null groups. Include
cost inputs in dataset/config hashes and registry replay. Use report version
core-feature-validation-v2 only when scenarios are supplied; preserve v1 otherwise.
Costs are USER_SUPPLIED_NOT_VERIFIED; execution_simulated and signals_enabled
remain false. A positive sensitivity result does not validate profitability.

Acceptance: independently calculated fees on entry/exit notionals, adverse prices,
funding charge/credit, zero-cost equivalence, increasing-cost monotonicity,
missing-data/split isolation, bad inputs, v1 compatibility, CLI fixture and registry
identity/replay coverage, full local and PostgreSQL/frontend CI.
