# Spec 040 — Solana candidate risk & state inspector dashboard panel

Implements an interactive point-in-time candidate state inspector on the Mochex Radar dashboard:

1. `dashboard/app/candidate-inspector.tsx`:
   - Interactive search and evaluation inspector (`section#candidate`).
   - Evaluates any valid Solana mint address via `/api/candidate?mint=...`.
   - Displays synthesized point-in-time `CandidateState` (`DISCOVERED`, `WATCHING`, `PUMP_WATCH_PROVISIONAL`, `DUMP_WARNING`, `BLOCKED_SECURITY`) and `security_status` (`BLOCK`, `CAUTION`, `UNKNOWN`, `PASS`).
   - Renders active blocking gates (e.g. `buyer_independence_unverified`, `security_status_unknown`, `incomplete_dex_liquidity_or_depth`).
   - Displays 3-column risk inspection:
     - Mint & Token-2022 extensions: status, mint authority, freeze authority, flags.
     - Stage liquidity: status, DEX liquidity USD, 2% sell-depth USD, flags.
     - Holder concentration: status, Top 1 % unlocked, Top 10 % unlocked, flags.
   - Guardrails: clearly notes that vendor scores alone never yield PASS and live signals / alerts remain disabled.

2. `dashboard/app/api/candidate/route.ts` & `dashboard/lib/contracts.ts`:
   - Server route proxying `GET /api/v1/candidates/solana/{mint}/evaluation`.
   - `candidateEvaluationSchema` validating strict types, non-null guards, and disabled signals.
