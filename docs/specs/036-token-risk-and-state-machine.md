# Spec 036 — Token-2022 extensions, stage-aware liquidity, holder concentration, and candidate state machine

Implements Roadmap Areas 1 and 2 in `cluster_radar`:

1. `cluster_radar/security/token_risk.py` (`solana-token-risk-v1`):
   - `parse_mint_and_extensions`: evaluates finalized SPL Token (`Tokenkeg...`, 82 bytes)
     and Token-2022 (`TokenzQd...`, 82 bytes or 166+ byte TLV layout) mint accounts.
   - Evaluates `TransferFeeConfig` (type 1; `BLOCK` > 500 bps, `CAUTION` > 0 bps or active
     config authority), `DefaultAccountState` (type 6; `BLOCK` when frozen),
     `NonTransferable` (type 9; `BLOCK`), `PermanentDelegate` (type 12; `BLOCK` when
     present), and `TransferHook` (type 14; `BLOCK` when program_id is non-zero, `CAUTION`
     when authority is non-zero). Any unsupported TLV extension type or malformed layout
     fails closed as `UNKNOWN`.
   - `evaluate_stage_liquidity`: enforces `MarketStage.CURVE` (`curve_quote_reserve_usd`
     and `graduation_progress`; DEX pool fields forbidden and marked `NOT_APPLICABLE`) vs
     `MarketStage.DEX` (requires both `dex_liquidity_usd` and `sell_depth_2pct_usd`).
   - `evaluate_holder_concentration`: evaluates `top_1_unlocked_pct` and
     `top_10_unlocked_pct` (`BLOCK` at >= 30% / >= 70%, `CAUTION` at >= 15% / >= 50%).
   - `evaluate_token_risk`: aggregates all three checks; any `BLOCK` produces `BLOCK`, any
     missing/stale/unsupported check keeps `UNKNOWN`, and a vendor `SAFE` verdict alone
     can never produce `PASS`.

2. `cluster_radar/signals/state_machine.py` (`candidate-state-machine-v1`):
   - `evaluate_candidate_state`: transitions candidates across `DISCOVERED`, `WATCHING`,
     `PUMP_WATCH_PROVISIONAL`, `DUMP_WARNING`, and `BLOCKED_SECURITY` using point-in-time
     evidence. `BLOCKED_SECURITY` preempts all states, and `DUMP_WARNING` preempts
     `PUMP_WATCH_PROVISIONAL`. Missing features, `UNKNOWN`/`CAUTION` security, or
     unverified buyer independence block `PUMP_WATCH_PROVISIONAL`.
   - `replay_candidate_states`: builds deterministic transition records across strictly
     ordered UTC decision timestamps.
