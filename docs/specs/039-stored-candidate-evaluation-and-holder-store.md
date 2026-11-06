# Spec 039 — Stored Solana candidate risk and state-machine evaluation & holder concentration store

Integrates `cluster_radar`'s token-risk and candidate state-machine engines with `mochex_radar`'s point-in-time PostgreSQL stores and FastAPI endpoints (`mochex_radar/candidate_evaluation.py`, `mochex_radar/api.py`, `mochex_radar/initialize.py`):

1. **Immutable Holder Concentration Store (`mint_holder_observations`)**:
   - `initialize_holder_store`, `store_holder_observation`, `holder_history`, and `PersistentHolderConcentration` (with `provider_budget.reserve_request`).
   - Enforces `payload @> '{"security_status":"UNKNOWN","approved_pump_watch":false}'::jsonb` and rejects conflicting content hashes at identical `(mint, source, known_at)`.
   - Exposes `GET /api/v1/security/solana/{mint}/holders` (disabled by default unless `SOLANA_HOLDERS_ENABLED=true`) and `GET /api/v1/security/solana/{mint}/holders/history`.

2. **Point-in-Time Stored Candidate Evaluation (`evaluate_stored_candidate` & `GET /api/v1/candidates/solana/{mint}/evaluation`)**:
   - Reads stored authority observations (`authority_history`), DEX pool observations (`observation_history`), and holder concentration observations (`holder_history`) strictly at `known_at <= as_of AND ingested_at <= as_of`.
   - Synthesizes explainable `token_risk` (`solana-token-risk-v1`) and `candidate_state` (`candidate-state-machine-v1`) without triggering live RPC calls.
   - Preserves `approved_live_signal: false` and `alerts_enabled: false`.
