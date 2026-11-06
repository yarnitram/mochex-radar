# Spec 038 — Solana holder concentration RPC adapter, history normalizer, and category coverage dashboard

Implements the read-only provider and dashboard scanner increments for Roadmap Areas 1, 2, and 4:

1. `cluster_radar/providers/solana_holders.py` (`solana-holder-concentration-v1`):
   - Evaluates finalized `getTokenSupply` and `getTokenLargestAccounts` RPC responses.
   - Enforces slot equality between supply and largest accounts (`holder_rpc_slot_mismatch` fails closed as `UNKNOWN`).
   - Supports explicit exclusion of verified locked/LP token accounts (`excluded_token_accounts`), computes `top_1_unlocked_pct` and `top_10_unlocked_pct` using exact `Decimal` arithmetic, and feeds `HolderRiskEvidence` into `evaluate_holder_concentration`.
   - Enforces a per-process request budget ceiling (`max_requests`) and rate-limit spacing (`1.1s`), while keeping `security_status="UNKNOWN"` and `approved_pump_watch=False`.

2. `cluster_radar/providers/solana_history.py` (`solana-wallet-history-v1`):
   - Normalizes enhanced Solana address transaction payloads into point-in-time `Swap` and `FundingEvidence` records (`cluster_radar/intelligence/research.py`).
   - Skips failed transactions (`transactionError is not None`), excludes future events (`event_at > as_of`), and defaults unverified funders to `"UNKNOWN"` so unverified or CEX transfers never trigger false `NON_CEX` cluster grouping.
   - Includes a bounded `SolanaHistoryAdapter` with `max_requests` ceiling and rate-limiting.

3. `dashboard/app/categories-panel.tsx` and `categoriesSchema` (`dashboard/lib/contracts.ts`):
   - Wires `GET /api/v1/categories/registry` into `/api/dashboard` and renders `section#categories` ("Meme and AI category coverage").
   - Filters across `All registry`, `Meme sector`, `AI sector`, `Unclassified`, and `Coverage gaps`, displaying canonical venue-scoped identities, risk models, overlapping `meme · ai` tags, provenance, and conflict/coverage-gap badges.
