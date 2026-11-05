# Mochex Radar — Remaining product roadmap

Eight major work areas remain. Completed development increments are tracked
separately in the project handoff. Each group below can take several increments;
provider validation may change the scope estimate and sequencing.

1. **Wallet intelligence and Pump/Dump signals — in progress.** Offline normalized
   swap/funding metrics and provisional PRD-weighted scores are now implemented.
   Still needed: verified live history adapters, feature extraction/normalization,
   cluster evidence validation, complete state transitions and gated signal production.
   Exit: provider contracts, point-in-time replay, CEX/unknown exclusion, independent
   warning tests and forward paper evidence pass; missing data cannot approve signals.
2. **Remaining token-risk checks.** Original SPL authorities are partial evidence.
   Add Token-2022/transfer restrictions, stage-aware curve rules, liquidity/sell-depth,
   holder/controller concentration and independently verified provider findings.
   Exit: supported risk checks are complete and explainable; unsupported/missing
   checks stay UNKNOWN; no vendor score alone becomes a universal safety verdict.
3. **Core market features and scoring — in progress.** Stored point-in-time calculations, API and bounded manual backfill are implemented; dashboard is complete. Offline split outcome/baseline reporting is implemented; real-data evidence and threshold validation remain. Expand stored history and verified MEXC
   futures feeds as needed for volatility, volume, relative strength, structure and
   BTC context. Exit: seven instruments have validated identities, required lookbacks,
   reproducible feature versions, stale/gap guards and replayed baseline comparisons.
4. **Meme and AI coverage.** Add provenance-backed category registries and suitable
   scanner views across listed futures and DEX assets. Exit: overlapping categories
   preserve identities and risk models; ambiguous assets remain unclassified and
   provider coverage gaps are visible.
5. **Outcome backtesting and forward paper validation.** Existing replay foundations
   need dataset/run registries, labels, metrics, baseline/holdout comparisons and
   fee/slippage/depth assumptions. Exit: no future knowledge/ingestion leaks, universe
   bias is disclosed, reproducible reports include failed cases and paper feasibility.
6. **Redis live state and coordination.** Add ephemeral live snapshots/queues/cache
   and controlled worker coordination while PostgreSQL retains durable evidence.
   Exit: restart, duplicate work, stale cache and Redis-outage tests pass without
   presenting stale data as current or losing durable outbox/evidence records.
7. **Operational hardening.** Complete access control, secrets management, readiness,
   metrics/provider-cost accounting, pinned dependencies/images, migrations and
   tested backup/restore. Exit: full stack tests and recovery runbook pass, logs
   redact credentials, and public access is configured deliberately.
8. **Proxmox deployment.** Verify host/guest IDs, source and backup paths; deploy
   the tested stack to a dedicated guest with restricted access. Add controlled
   Git fast-forward updates of verified commits, health checks and rollback.
   Exit: reboot/recovery, update failure, backup restore and external dependencies
   are exercised on the actual guest. Host/access details are needed for this gate.

Live wallet provider selection/access, dedicated production RPC, private Telegram
bot/destination setup, and verified Proxmox host/guest details are external inputs.
Keep credentials in private configuration, outside chat, Git and Markdown. They do
not block the current offline research implementation. No live trading is in scope.
