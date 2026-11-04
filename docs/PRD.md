# Crypto Radar — Product Requirements Document

**Status:** Draft for discovery and implementation planning  
**Version:** 1.0  
**Date:** 2026-11-05  
**Scope:** Read-only crypto intelligence and alerting platform; no live trading

## 1. Product summary

Crypto Radar is a unified, evidence-first platform for monitoring seven primary exchange pairs, listed meme and AI assets, newly discovered DEX tokens, and Solana wallet-cluster behavior. It combines a Python/FastAPI scanner engine with a Next.js/TypeScript dashboard, PostgreSQL history, Redis live state/queues, real-time CEX feeds, DEX discovery, BTC market context, and Telegram alerts.

The existing separate Cluster Radar Solana project is a protected dependency. Its code, PRD, tests, adapters, thresholds, and alerting behavior must be audited and preserved before integration. Integration must occur through adapters and shared contracts, not a destructive rewrite.

## 2. Goals and non-goals

### Goals

- Monitor `SOL/USDT`, `XRP/USDT`, `DOGE/USDT`, `LINK/USDT`, `SUI/USDT`, `AVAX/USDT`, and `ADA/USDT`.
- Classify market conditions as slow, active, or explosive using volatility, range, volume, and liquidity measures.
- Provide separate dashboard areas for Core Altcoins, Listed Meme, AI Sector, New DEX Tokens, Cluster Radar, Signals, Backtests, and System Health.
- Preserve and expose Cluster Radar’s Pump Radar, Dump Radar, wallet-cluster search, and risk checks as independent evidence streams.
- Apply BTC market-context filters to reduce false positives during adverse broad-market conditions.
- Store raw observations, normalized features, signals, risk findings, alerts, and outcomes for replay and backtesting.
- Send explainable Telegram alerts with evidence, timestamps, freshness, confidence, and explicit risk disclaimers.
- Support local Docker development and a provider-agnostic data layer.
- Deploy the read-only platform on the user’s Proxmox environment using documented, reproducible guests and backups.

### Non-goals for the initial release

- Live order placement, account access, custody, wallet signing, copy trading, or automated execution.
- Claims that a wallet cluster proves common ownership or malicious intent.
- Guaranteed early detection of pumps, tops, rugs, or profitable trades.
- Reliance on a single provider or undocumented scraping as a core dependency.
- Replacing the existing Cluster Radar project with a monolith.

## 3. Users and primary workflows

### Primary user

A discretionary trader/researcher who wants a ranked, explainable watchlist and alerts, then makes all trading decisions manually in an external venue.

### Core workflows

1. Open the Core Altcoins page and see pair health, BTC regime, volatility state, relative strength, structure state, and latest evidence.
2. Open Meme or AI pages to review category-specific candidates without mixing their risk models into Core Altcoins.
3. Open Cluster Radar for Solana tokens and inspect Pump Radar, Dump Radar, wallet-cluster evidence, and manipulation/rug checks separately.
4. Open a token detail view to review evidence, data freshness, invalidation, risk flags, and historical signal outcomes.
5. Receive a Telegram alert only when configured thresholds, deduplication, cooldown, and risk gates are satisfied.
6. Run a backtest using frozen historical data and inspect metrics, assumptions, and failure cases.

## 4. Asset identity and categories

Asset identity must never be based on symbol alone.

- CEX asset: `venue`, `market_id`, `base`, `quote`, contract/network when available.
- DEX asset: `chain_id`, `token_address`, `pool_address`, `base/quote`, DEX, and first-seen time.
- Cluster Radar asset: Solana mint address plus token metadata snapshot.

Categories are tags, not mutually exclusive identities. DOGE may appear in Core Altcoins and Listed Meme. New DEX tokens must remain distinct from listed meme futures/perpetuals because liquidity, execution, and risk characteristics differ.

## 5. Functional requirements

### 5.1 Data ingestion

- Consume CEX WebSocket trades, order-book top levels, and candles where supported.
- Maintain REST polling as a bounded recovery path, with rate limits, retries, backoff, and source timestamps.
- Discover DEX pools/tokens through documented provider APIs only; record provider, query time, response version, and freshness.
- Ingest Solana transaction/token data through the existing Cluster Radar adapters after audit; add new adapters only behind interfaces.
- Normalize all events to UTC and retain provider event time plus ingestion time.
- Detect stale, delayed, duplicated, out-of-order, and contradictory data.

### 5.2 Market features

At minimum, calculate per asset and timeframe:

- OHLCV, spread, depth proxy, trade count, realized volatility, ATR, candle range/ATR, and relative volume.
- Return over 5m/15m/1h/4h/1d, rolling highs/lows, compression/expansion state, and liquidity state.
- Market structure features: swing points, BOS, CHoCH, displacement, liquidity sweep, supply/demand zones, and invalidation level.
- Relative strength against BTC and configurable benchmark baskets.
- Feature version and lookback metadata so signals are reproducible.

### 5.3 BTC market-context filter

BTC is a context filter, not a trade target in this product.

- Track BTC trend, volatility regime, impulse/decline, market-wide correlation proxy, and data freshness.
- Emit a context state such as `supportive`, `neutral`, `caution`, or `blocked` using versioned, configurable rules.
- Each altcoin signal must declare whether BTC context supported, weakened, or blocked it.
- A blocked context suppresses alerts by default but must not erase observations or backtest records.
- Thresholds are hypotheses until validated on historical data; no hard-coded “safe” claim.

### 5.4 Core Altcoin scanner

Initial universe: the seven pairs listed in Section 2. Provide configurable timeframes, initially 15m and 1h.

Candidate evidence may include volatility wake-up, relative volume expansion, structure shift, breakout watch, retest quality, and relative strength. A signal is not valid unless its evidence timestamp, data freshness, invalidation, estimated costs, and risk gates are present.

### 5.5 Meme and AI scanners

- Listed Meme: exchange-listed meme assets with momentum, volatility, liquidation/short-squeeze warnings where available, and separate risk thresholds.
- AI Sector: category registry with provenance, sector breadth/relative strength, momentum, and concentration warnings.
- New DEX Tokens: pool age, liquidity, volume quality, holder concentration, buy/sell tax indicators if reliably available, mint/freeze/ownership privileges, liquidity lock/burn evidence where available, and suspicious transfer/creator behavior.
- Every category must identify its source of classification and allow manual review/correction.

### 5.6 Cluster Radar integration

Preserve existing behavior first. During discovery, document the current project structure, runtime, entry points, data adapters, thresholds, tests, and PRD. Create a compatibility adapter rather than moving files.

Required exposed capabilities:

- Pump Radar: accumulation/coordination evidence with score, components, and freshness.
- Dump Radar: distribution/weakening-demand evidence with score and independent warning evidence.
- Wallet Cluster Search: candidate relationships based on explicit evidence types. The prior design’s “at least four linked wallets and two evidence types” is a screening threshold, not proof of shared ownership.
- Rug/manipulation checks: liquidity, privileges, ownership concentration, transfer behavior, and other available checks, with unknown status when data is missing.
- Existing score thresholds such as 75 must be treated as inherited configuration pending audit and backtest, not as validated truth.

Cluster signals must remain distinguishable from technical market signals and must include `evidence`, `limitations`, `unknowns`, and `review_status`.

### 5.7 Unified signal contract

Every signal must support:

```json
{
  "signal_id": "uuid",
  "asset_id": "venue-or-chain-specific-id",
  "category": "core_altcoin|listed_meme|ai|new_dex|cluster",
  "signal_type": "string",
  "direction": "long_bias|short_bias|watch|risk_warning|blocked",
  "score": 0,
  "confidence": "low|medium|high|unknown",
  "observed_at": "UTC timestamp",
  "data_as_of": "UTC timestamp",
  "feature_version": "string",
  "evidence": [],
  "risk_flags": [],
  "btc_context": "supportive|neutral|caution|blocked|unknown",
  "entry_zone": null,
  "invalidation": null,
  "estimated_costs": null,
  "expiry_at": "UTC timestamp",
  "backtest_reference": null,
  "disclaimer": "Research signal only; not financial advice."
}
```

No signal may be shown as an executable order or a guarantee. Missing data lowers confidence or blocks the signal; it must not be silently imputed without a recorded policy.

### 5.8 Alerts

- Telegram bot token and chat IDs are secrets supplied through environment/secret storage only.
- Alert templates must include asset identity, category, signal type, score/confidence, BTC context, evidence, risk flags, data age, invalidation, and a research-only disclaimer.
- Deduplicate by asset/signal/rule/time window; apply cooldowns and daily rate limits.
- Provide test delivery without exposing secrets.
- Record delivery attempt, provider response class, and retry state.

### 5.9 Dashboard

Next.js/TypeScript dashboard with server-side API access and typed contracts.

Pages:

- Overview: BTC context, system health, ranked signals.
- Core Altcoins: seven-pair matrix and detail pages.
- Meme: listed and DEX subviews.
- AI Sector: registry, breadth, relative strength.
- Cluster Radar: Pump, Dump, clusters, risk checks.
- Signals: filterable evidence ledger.
- Backtests: run registry and metrics.
- Settings/Health: providers, freshness, queues, alert status, read-only configuration visibility.

## 6. Architecture

```text
crypto-radar/
  dashboard/                 Next.js + TypeScript
  services/
    api/                     FastAPI application and auth boundary
    market-scanner/          Python features and signal rules
    dex-scanner/             DEX discovery and token-risk adapters
    cluster-radar-adapter/   Compatibility boundary to existing project
    backtester/              Replay and evaluation engine
    alert-worker/            Telegram delivery and dedupe
  shared/
    schemas/                 Versioned JSON/Pydantic/TypeScript contracts
    token-registry/          Asset identity and category provenance
  infrastructure/
    postgres/                Migrations and indexes
    redis/                   Streams/queues/cache with TTLs
    docker/                  Local services and health checks
  docs/
    discovery/               Audit findings and decisions
```

Use a modular monorepo only if the discovered Cluster Radar project can be referenced safely. Otherwise keep it as a sibling service/repository and integrate via HTTP/events/shared schemas. The first implementation must not copy or rewrite unknown source files.

Suggested runtime boundaries:

- FastAPI: read-only query API, health, signal ledger, backtest control, configuration validation.
- Workers: ingestion, feature calculation, scanners, Cluster Radar adapter, alert delivery.
- PostgreSQL: durable source observations, normalized candles, features, signals, risks, alerts, outcomes, audit log.
- Redis: short-lived market state, dedupe keys, queues/streams, worker heartbeats; never the sole source of truth.
- Next.js: read-only presentation and user-configured filters.

### Proxmox deployment target

Proxmox is the target self-hosted runtime after local validation. The deployment must remain portable and reproducible through Docker Compose or equivalent pinned service definitions.

- Preferred initial layout: one dedicated unprivileged Proxmox VM for the application stack, with Docker/Compose inside the VM; keep the option to split workers later if load requires it.
- Services inside the guest: dashboard, FastAPI, scanner workers, backtester on demand, PostgreSQL, Redis, and alert worker. Do not expose PostgreSQL or Redis directly to the LAN or Internet.
- Use a reverse proxy or private network boundary for dashboard/API access, TLS where accessed beyond localhost, and explicit firewall rules.
- Store persistent PostgreSQL data and approved application configuration on dedicated VM-backed storage. Redis remains rebuildable cache/queue state unless a specific durability need is documented.
- Define CPU, memory, disk, retention, and network requirements from measured workloads rather than guesses; start with conservative development sizing and record observed utilization.
- Back up PostgreSQL, migrations/configuration, dashboards, and deployment definitions. Test restore before release. Do not back up secrets in plaintext.
- Use Proxmox snapshots only as a convenience; they do not replace application-consistent database backups.
- Keep secrets outside Git and inject them through protected guest storage or a secret manager. Never put exchange keys or private keys in the VM.
- Add guest and service health checks, time synchronization, restart policies, disk-space alerts, provider-latency alerts, and a documented recovery procedure.
- Initial release may be single-node and non-HA. High availability, GPU use, and Kubernetes are out of scope unless later justified by measured requirements.

## 7. Data-provider constraints

- Providers must be selected and documented per capability; do not assume one provider supplies complete CEX, DEX, and Solana data.
- Prefer official/documented APIs and WebSockets. Respect terms, rate limits, attribution, and retention rules.
- Store raw payloads only when allowed and redact secrets. Persist normalized data plus provider metadata.
- Implement provider interfaces and contract tests; use recorded fixtures in CI.
- Every provider failure must surface in health state and affect signal confidence/freshness.
- Historical availability, symbol mapping, token metadata quality, and DEX coverage are discovery risks, not assumptions.

## 8. Security, privacy, and risk guardrails

- No private keys, seed phrases, exchange trading keys, or wallet signing.
- No live trading endpoints or order-placement code in the initial product.
- Secrets only through environment/secret manager; never commit `.env`, tokens, chat IDs, or raw credentials.
- Validate all external payloads; use timeouts, retries with bounds, circuit breakers, and idempotency keys.
- Apply least privilege to database roles and provider credentials.
- Rate-limit dashboard/API endpoints and Telegram delivery.
- Audit configuration changes and alert decisions.
- Label uncertainty, missing data, provider disagreement, and model/rule version.
- Cluster evidence is probabilistic screening; never label an address “fraudulent” solely from linkage.
- Risk checks may block or warn; they do not certify safety.
- Backtests must include fees, spread, slippage, latency, missing candles, delisted assets, survivorship bias, and signal availability timing.

## 9. Backtesting and evaluation

- Event-driven replay using only data available at each historical timestamp.
- Separate discovery, calibration, validation, and holdout periods.
- Avoid look-ahead leakage in pivots, zones, categories, and wallet graph construction.
- Record rule/feature/provider versions and exact configuration.
- Report trade-independent signal metrics: coverage, precision by horizon, alert rate, false-positive rate, time-to-expiry, and calibration.
- If a strategy simulation is added, report fees, spread, slippage, latency, max adverse/favorable excursion, drawdown, turnover, and sample size.
- Compare against simple baselines such as buy-and-hold, random alert timing, and BTC-context-only filters where appropriate.
- No threshold becomes a default recommendation until it passes reproducible validation and manual review.

## 10. Observability and operations

- Structured logs with correlation IDs and no secrets.
- Metrics for ingestion lag, provider errors, queue depth, worker heartbeat, feature latency, signal counts, alert delivery, and database health.
- Health endpoints: liveness, readiness, provider freshness, Redis, PostgreSQL, and Cluster Radar adapter.
- Dead-letter handling for malformed events and failed alert deliveries.
- Reconciliation jobs for gaps, duplicate candles, and token identity conflicts.
- Local Docker compose must start dependencies with documented seed/fixture data.

## 11. Spec-Driven Development and testing

Crypto Radar will use Spec-Driven Development (SDD). No implementation task is complete from a verbal description alone.

### SDD workflow

1. Write or update a small feature spec with scope, inputs, outputs, invariants, failure behavior, security impact, and acceptance criteria.
2. Record the decision in the appropriate project/ADR document when architecture or provider behavior changes.
3. Define contract/schema tests and representative fixtures before or alongside implementation.
4. Implement the smallest change that satisfies the spec; preserve existing Cluster Radar behavior unless the spec explicitly approves a compatibility change.
5. Run focused tests, then the broader regression suite, static checks, and security checks.
6. Update documentation, test evidence, handoff, and known limitations before marking the feature complete.

### Required test layers

- **Unit:** indicators, feature calculations, scoring, thresholds, identity normalization, risk gates, dedupe, and alert formatting.
- **Property/invariant:** timestamp ordering, non-negative volumes, bounded scores, deterministic replay, idempotency, and no signal from stale/blocked required inputs.
- **Contract:** Pydantic/TypeScript schemas, provider adapters, Cluster Radar compatibility boundary, and Telegram client fake.
- **Integration:** FastAPI with PostgreSQL/Redis, worker queues, migrations, provider fixtures, alert persistence, and dashboard API contracts.
- **End-to-end:** ingestion fixture → features → signal → risk gate → API/dashboard → alert audit record.
- **Backtest/replay:** point-in-time data availability, no look-ahead leakage, versioned rules, fees/spread/slippage/latency, and baseline comparisons.
- **Resilience:** provider outage, rate limiting, stale data, duplicate/out-of-order events, malformed payloads, queue failure, database restart, disk-full behavior, and Telegram failure.
- **Security:** secret scanning, dependency audit, input validation, authorization boundaries, safe logging, and confirmation that no trading/private-key path exists.
- **Deployment:** clean-checkout startup, migration/rollback checks, Proxmox guest restart, backup/restore, health checks, resource limits, and private service networking.

### Quality gates

- A pull request cannot be accepted without its linked spec, test evidence, and risk/rollback notes.
- CI must run formatting/linting, type checks, unit/property/contract/integration tests, security checks, and a smoke test.
- Full end-to-end, backtest, resilience, and Proxmox checks may run in a scheduled or release pipeline when dependencies are available.
- Coverage is a signal, not the only quality measure; critical risk and data-integrity paths require explicit tests even if coverage is already high.
- A failed or skipped required test blocks release and must be explained in the handoff.

## 12. Milestones and acceptance criteria

### M0 — Discovery and preservation

Acceptance:

- Existing Cluster Radar path(s) are verified or explicitly marked missing.
- Inventory identifies code, PRD, tests, adapters, entry points, runtime, and run instructions.
- No existing Cluster Radar file is overwritten or moved.
- Discovery report lists unknowns, compatibility risks, and recommended integration boundary.

### M1 — Foundations

Acceptance:

- Local services start reproducibly.
- Versioned asset and signal schemas validate in Python and TypeScript.
- PostgreSQL migrations and Redis health checks pass.
- Provider interfaces have fixtures and failure tests.

### M2 — Core Altcoins and BTC context

Acceptance:

- Seven pairs are represented by venue-specific identity.
- Historical fixtures produce deterministic features and context states.
- Dashboard shows freshness, volatility state, relative strength, and evidence.
- No live order or wallet-signing path exists.

### M3 — Meme, AI, and DEX discovery

Acceptance:

- Category provenance is visible.
- Listed meme, AI, and new DEX rules are separate and tested.
- DEX risk checks fail closed when required data is missing.

### M4 — Cluster Radar compatibility integration

Acceptance:

- Existing tests still pass unchanged where possible.
- Adapter exposes Pump, Dump, cluster, and risk results through the shared contract.
- Thresholds and evidence are labeled inherited/unvalidated until backtested.
- Dashboard preserves Cluster-specific limitations and unknowns.

### M5 — Alerts and backtesting

Acceptance:

- Telegram test delivery, dedupe, cooldown, retries, and audit records work.
- Replay is timestamp-correct and produces reproducible reports.
- Reports include costs, slippage, latency assumptions, leakage controls, and baselines.

### M6 — Hardening and release candidate

Acceptance:

- Security review finds no secrets or trading endpoints.
- Provider outage, stale data, malformed payload, and database restart tests pass.
- Documentation covers setup, configuration, recovery, and known limitations.
- User explicitly approves any scope expansion beyond read-only alerts.

### M7 — Proxmox deployment

Acceptance:

- A dedicated Proxmox guest runs the documented stack from a clean checkout using pinned configuration.
- Dashboard/API access is protected by the documented network boundary; PostgreSQL and Redis are not publicly exposed.
- Persistent data, backup, restore, restart, and disk-capacity procedures are documented and tested.
- Secrets are injected without entering Git, image layers, logs, or backups in plaintext.
- Proxmox guest/service health checks and failure recovery are demonstrated.
- The deployment remains read-only: no exchange account access, wallet signing, or order-placement path exists.

## 13. Open decisions for discovery

- Which CEX is the initial reference venue for the seven pairs?
- Which documented DEX/Solana providers are available and permitted?
- Is Cluster Radar a sibling checkout, package, or service, and what runtime/version does it require?
- Which historical datasets are legally and technically available?
- What are the user’s preferred timeframes, alert windows, and Telegram routing rules?
- Are existing thresholds configurable in the old project or embedded in code?

## 14. Definition of done for initial release

The initial release is done only when the platform is read-only, auditable, reproducible, provider-failure aware, and able to show explainable signals for the seven pairs plus separately labeled meme/AI/DEX/Cluster Radar evidence. It must preserve the existing Cluster Radar project and clearly distinguish research signals from financial advice or executable trading instructions.
