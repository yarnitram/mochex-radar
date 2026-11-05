# Cluster Radar — Product Requirements Document

**Version:** 1.0 (initial Codex handoff)  
**Date:** 2026-11-03  
**Status:** Draft / Implementation-ready specification, not a validated trading strategy  
**Owner:** Project owner  
**Product:** Solana Memecoin Intelligence Scanner  
**Canonical PRD path:** `docs/PRD.md`

## 1. Executive summary

Cluster Radar is a Python-based, research-first Solana memecoin monitor. It discovers newly launched and established memecoins, detects **potential early accumulation** (Pump Radar) and **possible post-pump distribution/reversal** (Dump Radar), inspects wallet funding and holder risk, and sends evidence-rich Telegram watchlist alerts. It continuously saves timestamped observations for reproducible backtesting.

**Key product constraint:** v1 is **read-only and alert-only**. It cannot hold keys, sign transactions, execute purchases or shorts, give guaranteed price predictions, or promote suspicious coordination as a safe opportunity.

The system must distinguish between **potentially coordinated accumulation** (a research signal), **rug/manipulation risk** (a negative risk factor), and **tradeable market conditions** (a separate liquidity consideration).

## 2. Goals, non-goals, success metrics

### Goals
1. Discover Solana memecoin candidates at the launchpad/bonding-curve, graduation, and post-graduation DEX stages.
2. Monitor market activity and independently compute Pump Radar and Dump Radar alerts.
3. Build explainable wallet-linkage evidence (shared funders, direct transfers, synchronized patterns), with meaningful limits on ownership inferences.
4. Reject or downgrade candidates when security, holder concentration, liquidity, or data quality is unfavorable.
5. Send deduplicated Telegram alerts containing evidence, confidence, timestamps, and source links.
6. Store point-in-time data and implement honest historical replay and forward testing.
7. Enforce per-provider request/credit budgets and gracefully handle API failures and gaps.

### Non-goals for v1
- Automatic trading, private key storage, swapping, shorting, leverage, custody, or wallet signing.
- Promises to predict pumps or identify a price top.
- Paid signal subscriptions or social/trending manipulation.
- EVM, Base, and centralized exchange derivatives scanning (future phases only).
- Web dashboard (defer until alerts and backtests prove useful).

### Initial operational acceptance targets (engineering targets, not alpha claims)
- In fixture-backed tests, 100% of injected duplicate swap records are deduplicated.
- No normal Pump Watch alert when critical security fields are unknown or hard-blocked.
- Same event does not produce duplicate Telegram alerts during an active cooldown.
- All decisions contain `observed_at`, `evaluated_at`, provider provenance, feature snapshot, and rule version.
- Scanner survives provider 429/timeout without losing durable progress markers or crashing.
- Demonstrable `doctor`, `demo`, unit tests, and point-in-time replay on local fixtures.
- Publish measured alert precision/recall/lead time; **do not** set arbitrary profitability goals before validation.

## 3. Target user and workflows

**Primary user:** individual Solana memecoin researcher who prefers Python, Docker, Telegram, and Codex-assisted development.

### Workflow A — Early pump watch
Discovery recognizes a token; normalizes mint/pool/stage; market filter passes; trade/owner analysis finds sustained net buying; wallet relationships evaluated; token security passes; Pump Watch Telegram notification is sent with the actual evidence and a caution label.

### Workflow B — Post-pump dump watch
An observed token rallies sharply; independent signs of distribution, fading buyers, liquidity deterioration, and/or price weakness appear; Dump Watch notification reports elevated downside risk, not a guaranteed reversal or short order.

### Workflow C — Rug/manipulation watch
Creator/linked-wallet concentration, token authority, risky extensions, or liquidity-control issues appear. Send `HIGH_RISK` notification even when Pump Radar accumulation score is high; don't classify as an approved pump candidate.

### Workflow D — Retrospective evaluation
At an evaluation cutoff, replay only the data that would have been known then, reconstruct alert state, compare subsequent outcomes after fees/slippage, and generate precision, recall, time-to-event, and drawdown metrics.

## 4. In-scope networks and market stages

**Network:** Solana mainnet only. Do not confuse token mint time, initial observed wallet activity, pool-creation time, and launchpad graduation time.

**Stages:** `LAUNCHPAD_CURVE`, `GRADUATING`, `DEX_LIVE`, `UNKNOWN`. A launchpad bonding curve does not necessarily have conventional DEX-pool liquidity; discovery and risk rules must be stage-aware. An event may move between stages while preserving one canonical mint identity and a history of pool/migration events.

**Launchpads:** Implement a pluggable adapter for Pump.fun and additional platforms supported by the actual provider entitlement and schema. Never assume undocumented or unsupported real-time feeds.

## 5. System architecture

```text
Discovery adapters (Birdeye REST / optional entitled WebSocket)
     -> token & market-stage normalizer -> deduped candidate queue
     -> DEX Screener market enrichment and pool selection
     -> trade/event ingestion and on-chain wallet enrichment (Helius)
     -> security/holder authority assessment (Birdeye/RugCheck/RPC)
     -> Pump Radar | Dump Radar | High-Risk engine
     -> durable evaluations & alert outbox (PostgreSQL)
     -> Telegram delivery + cooldown/updates
     -> snapshot-based replay, labels, metrics, reports
```

**Proposed stack:** Python 3.12+, `uv`, `asyncio`, `httpx`, `pydantic`, PostgreSQL/SQLAlchemy/asyncpg, `networkx`, `pytest`, `ruff`, Docker Compose. Begin with a single asynchronous service. Redis and a dashboard are optional later.

### Adapter boundaries
- `DiscoveryProvider`: `get_new_listings(cursor/since)` and optional `subscribe_launchpad_events`.
- `MarketProvider`: `get_token_pools(mint)`, `get_market_snapshot(mint, pool)`, `get_historical_bars` if entitled.
- `TradeProvider`: `get_trades(mint, pool, cursor)` with normalized sides, owner, timestamps, signature, instruction index, amounts and confidence.
- `WalletProvider`: `get_first_funder(wallet)`, `get_identity(wallet)`, `get_transfers(wallet, window)`, historical holdings only when obtainable.
- `SecurityProvider`: `assess(mint, pool, stage)` plus authoritative on-chain fallbacks.
- `AlertSink`: queue and send Telegram messages; never trade.

**All provider-specific schemas and credentials stay in adapters.** Keep official SDK/API schemas versioned. Use `UNKNOWN` and provenance when an endpoint does not supply a required field; no fabricated defaults.

## 6. Data sources and API controls

### Birdeye
- Discovery for new token listings and eligible meme-launchpad updates.
- Token trade/overview/security enrichment when the account supports it.
- Verify exact endpoint, pagination, response fields, WebSocket subscription, and plan entitlement at implementation time; document known 403 and 429 behavior.

### DEX Screener
- `GET /tokens/v1/solana/{comma-separated-mints}` for market enrichment, up to 30 token addresses in a request.
- `GET /token-pairs/v1/solana/{mint}` to inspect pools.
- Official docs list 300 requests/minute for these endpoints; enforce a lower configurable internal budget and throttle by actual provider responses.
- **Not** a comprehensive new-pair event feed.

### Helius
- Wallet funding `GET /v1/wallet/{wallet}/funded-by`; wallet identity `GET /v1/wallet/{wallet}/identity` (paid entitlement).
- Parsed Events / Streams or an adapter-compatible historical transaction strategy; beta schemas must be isolated.
- Support ledger event indexing and raw RPC fallback where necessary. Avoid depending on a single deprecated parsing method.

### RugCheck
- Token report/summary as a supplementary security provider; capture raw scores and flags, data age, cache status, and provider failure.
- Example route: `GET https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary` (reconfirm contract and limits before deployment).
- Independent RPC checks take priority when risk fields conflict; mark disputed checks `UNKNOWN` until reviewed.

### Telegram
- `sendMessage` via Bot API; message includes stage, mint, pool, market cap/FDV and source, score details, risk status, timestamps, and source links.
- Use notification outbox + deduplication and per-chat throttling; avoid leaking any API keys or private operational data.

### Request budget / reliability
- Defaults: discovery poll 30 seconds, market snapshots 30 seconds for shortlist, wallet funding checked once per new wallet (cache by wallet), security 10–15 minutes or on a material change.
- Retry transient errors with jitter/backoff, respect `Retry-After`, apply token buckets per provider, cap daily credits, and halt optional enrichment on budget exhaustion.
- Save `scan_cursor` / `last_seen_slot`, count source gaps, and replay missed ranges when possible.
- Maintain `provider_usage` counters: request count, credits estimate, rejected request count, last success, and last schema error.

## 7. Candidate discovery and filtering

### DEX-live candidate defaults (editable YAML, not validated)
- Pair age: 5 minutes–24 hours (record token age independently).
- FDV or market cap: $15k–$250k, retaining `market_cap_usd` and `fdv_usd` as separate values. Do not substitute one without explicitly labeling the proxy.
- Pool liquidity: $5k–$75k (more stringent safety floor possible for approved Pump Watch).
- 15m unique buyers ≥10; 30m change between −10% and +15%; buy/sell dollar-volume ratio ≥1.5.
- Minimum valid event/sample counts required, and outlier/wash-trade flags assessed.

### Curve-stage candidates
Use curve progress, creator details, curve reserves, wallet trading events, migration/graduation state, and stage-specific price/volume. Standard DEX liquidity and pool-creation filters are `NOT_APPLICABLE` rather than silently failing.

### Existing rallies for Dump Radar
- Candidate becomes eligible when price rose at least 100% in 1h or 200% in 6h, subject to adequate price/volume samples.
- Compare against cohort and historical baselines; eligible high-volatility tokens remain only `WATCH` until distribution evidence is independent and timely.

## 8. Pump Radar requirements

### Signals and weights (0–100, initial hypothesis)
| Signal | Weight | Example evidence |
|---|---:|---|
| Sustained independent buying | 25 | Buy/sell USD ratio >1.5; positive net buying in 3 consecutive 5m windows |
| Compression/structure | 20 | Range behavior, confirmed higher lows, low price displacement relative to net buying |
| New owner participation | 20 | Increasing *independent* unique buyers after known bot/related-wallet grouping |
| Wallet quality and concentration | 20 | No dominant linked cluster, limited creator/insider token exposure |
| Organic volume buildup | 15 | Active but below sustained volume-spike threshold, wash-trade penalties |

Use per-feature normalization and traceable sub-scores; missing features are not automatic zeroes. Store `score_confidence` and `missing_features` separately. Defaults: `PUMP_WATCH` only if score ≥75, validated liquidity/risk status PASS, sufficient data coverage, and no already-confirmed breakout. `BREAKOUT_CONFIRMED` must be distinct from `PRE_BREAKOUT_WATCH`.

**Wallet clusters are not automatically bullish.** Coordinated accumulation may trigger a high-risk alert or an eligibility block if related supply is concentrated.

## 9. Dump Radar requirements

### Signals and weights (0–100, initial hypothesis)
| Signal | Weight | Example evidence |
|---|---:|---|
| Insider/large-holder net distribution | 30 | Sustained net token outflow/sales from clearly identified holders |
| Buyer exhaustion | 20 | New buyer count slows, unique seller count rises |
| Price/volume divergence | 15 | High volume but repeated failed highs, weakening returns |
| Liquidity deterioration | 20 | Sell-executable depth or quote-side liquidity declining |
| Confirmed structure weakness | 15 | Confirmed lower high or break of a defined 1m/5m swing level |

Minimum: 2 independent warning **families** (not two highly correlated metrics from the same source) and score ≥75. States: `TOP_WATCH`, `DISTRIBUTION_DETECTED`, `BREAKDOWN_CONFIRMED`. Alert only on state changes or after cooldown with materially changed evidence. Store exact peak reference, window and lookback.

**No automatic short orders.** If derivatives are added later, verify instrument availability and independent liquidity/leverage conditions; not part of v1.

## 10. Wallet-link graph and rug/security assessment

Graph nodes represent on-chain owner wallets or labeled institutions/protocols, and edges carry evidence with timestamps and transaction signatures:

- Direct transfer of native SOL or token: strong potential link.
- Common immediate **non-exchange** first funder: potential link.
- Synchronized funding + synchronized trades: supporting evidence, not ownership proof.
- Same recognized CEX withdrawal wallet alone: not a cluster edge.
- Similar rounded trade sizes alone: weak evidence, never enough to infer a shared owner.

For every inferred connected component, compute independent wallet count, number of evidence families, observed net flow, likely shared inventory (when measurable), confidence, and concentration of supply excluding known pool/locker/burn entities. The initial wallet `first_funder` is **not** an actual wallet creation timestamp.

Security status: `PASS`, `CAUTION`, `BLOCK`, `UNKNOWN`.

Initial `BLOCK` conditions for conventional SPL/Token-2022 DEX tokens include unsafe mint/freeze or dangerous programmable extensions (unless documented safe exception), too little sell-executable liquidity, known transfer restrictions, or compelling concentrated controller evidence. Stage-specific curve authority design must be analyzed rather than blindly using the DEX rules. If key checks fail or disagree, use `UNKNOWN`: no approved Pump Watch alert. Separate LP-lock status, current liquidity, and likely removable liquidity; LP tokens burned/locked aren't a blanket safety guarantee.

Record all check results, raw provider flags, evidence timestamps, and any manual override with reason. Never hardcode one vendor's 0–100 risk score as universal semantics.

## 11. Alert requirements

### Notification types
`PUMP_WATCH`, `BREAKOUT_CONFIRMED`, `TOP_WATCH`, `DISTRIBUTION_DETECTED`, `BREAKDOWN_CONFIRMED`, `HIGH_RISK`, `DATA_UNAVAILABLE`, and `RECOVERY` (only important operational incidents). Separate Telegram chats/topics optionally.

### Telegram payload fields
- Token symbol **and mint**, stage, age basis, pair address and pool/launchpad name.
- Decision timestamp in UTC; provider freshness and confidence.
- Market cap and FDV separately; liquidity/depth; price movement and volume window.
- Pump and Dump scores, risk status, exact rules triggered, independent evidence families and key missing fields.
- Relevant holder/creator flags and cluster observations; never claim common ownership as fact from shared funding alone.
- Clickable DEX Screener, Solscan and security report links generated from validated mint/pool addresses.
- Explicit label `Research alert, not trade instruction`.

Deduplication key: token mint + pool/stage + alert type + rule-version + evaluation episode; configurable default 30m cooldown. Updates allowed on risk escalation, state changes or material score shifts. Telegram errors persist pending outbox work with capped retry.

## 12. Storage and data contracts

Use PostgreSQL migrations (Alembic). Keep raw inputs (within retention and API ToS) or compact reproducible event payloads, and normalized typed tables:

- `tokens`: mint PK, token program, first_seen_at, creator when known, metadata and status.
- `pools`: address PK, mint FK, AMM, created_at, quote mint, stage, migration history.
- `market_snapshots`: pool, observed_at, ingested_at, source, price, cap, fdv, liquidity, depth, volume and trade-count windows.
- `trades`: signature + instruction/path + pool unique key, block time/slot, owner, side, token/quote amounts, USD conversion provenance.
- `wallets`: wallet PK, first_seen_at, identity labels and confidence, first-funder metadata.
- `wallet_edges`: source, target, edge kind, transaction evidence, confidence, observed_at.
- `security_assessments`: mint/pool/stage, check results, assessment time, source, raw hash, risk status.
- `evaluations`: mint, stage, ruleset version, exact features, thresholds, decision, timestamps and missing-field list.
- `alerts_outbox`: idempotency key, payload, destination, state, attempt count and last error.
- `discovery_checkpoints`: provider/cursor/slot, last completed at, gap status.
- `outcomes`: future-window labels, earliest event timestamps, max favorable/adverse move, simulation metrics.
- `provider_usage`: credits, request counts, error counts and sampling coverage.

UTC time everywhere; store on-chain slot when supplied. Every feature must have a `known_at` timestamp. Primary pool selection must be deterministic, auditable, and must not aggregate incompatible quotes or double count cross-pool swaps. Treat migration events explicitly.

## 13. Backtesting and forward-testing specification

### Point-in-time rule
At evaluation timestamp `T`, read only events and metadata with `known_at <= T` (and respect modeled ingestion delay). Never backfill wallet relationships, security states, final-token survival, or a future high into earlier decisions.

### Dataset construction
- Include **all discovered candidates** in the observation universe (failed, rugged, de-listed and never-pumped tokens too), not only surviving chart histories.
- Preserve discovery time, provider outages, price/liquidity data gaps, and first eligibility times.
- Label the onset of volume expansion independently of price-rise outcome, to measure useful lead time.

### Example research labels (tunable, pre-registered)
- Pump event: price ≥ +50% versus alert reference **and** 5m volume ≥ 3× a pre-event baseline within 6h; run +25%, +100%, +200% sensitivity cases.
- Dump event: post-alert drawdown ≥30%/50%/80% within 15m, 1h, 6h; record whether the warning preceded the first significant decline.
- Execution feasibility: measurable quote/swap route, simulated size relative to depth, conservative slippage/fees, route failures, and feasible exits. Paper trade outcomes are **separate** from chart returns.

### Metrics
Precision, recall (against documented universe), PR curves, alerts/day, median lead time, false positives/day, median/max adverse excursion, rug-flag rate, execution-feasible outcome, provider gap rate, and estimated API cost per useful alert.

### Validation
Chronological train/validation/test splits; no per-token leakage; tune only on earlier periods. Benchmark against age/liquidity/volume-only and simple momentum heuristics. Test threshold robustness across launchpad stages and volatility regimes. Publish failures and limitations.

## 14. Quality, privacy, operational and safety requirements

- Never store or request a signing private key; only public read-only API credentials and Telegram bot token in `.env`, never in Git.
- Restrict Telegram destinations to configured chat IDs; redact provider keys from logs and exceptions.
- Validate Solana public keys, response types, URLs and currency units; reject impossible/negative prices, timestamps and quantities.
- Configurable budget ceilings, concurrency, sampling priority, retries, backfill, cancellation and clean shutdown.
- Reproducible provider fixtures and deterministic replay; no live network access in unit tests.
- Collect observability metrics for discovery delay, data freshness, coverage, memory, queue backlog and alert delivery.
- Explicitly separate `UNKNOWN`, `NOT_APPLICABLE`, `PASS`, `CAUTION`, `BLOCK` security field semantics.
- Respect provider ToS, rate limits and retention restrictions. Avoid abusive API polling.

## 15. Delivery milestones and acceptance criteria

### M0 — Initialization and architecture
- Initialize repo in `C:\Users\Samjie\ProjectCenter\ClusterRadar` **only if** the directory is absent or empty; inspect existing content first.
- Add `docs/PRD.md` (canonical), `README.md`, `AGENTS.md`, `.env.example`, configuration, Python package, tests, Docker Compose and architecture/test plans.
- Add Command Center project handoff under `C:\Users\Samjie\CommandCenter\02 - Projects\Active\ClusterRadar\handoff.md` following local conventions; don't destroy existing notes.
- Verify CLI and tests; report precise file changes and git status. Do not push/deploy without authorization.

### M1 — Discovery and market store
- Birdeye discovery + stage normalization + DEX Screener enrichment + safe provider fallbacks.
- Persist tokens/pools/market snapshots and checkpoints, plus budget usage.
- Deterministic tests with paginated discovery and migration fixtures.

### M2 — Risk and read-only alerts
- RugCheck/authority checks, security states, alert outbox, Telegram provider and high-risk notifications.
- Demonstrate BLOCK/UNKNOWN gate and idempotency with fault-injection tests.

### M3 — Pump/Dump features and wallet graph
- Trade ingestion, unique buyer/seller metrics, wallet funding/identity, NetworkX graphs, configurable scoring.
- Demonstrate examples of authentic independent buyers, single-funder cluster, shared CEX funding (not linked) and wash-trade patterns.

### M4 — Backtesting + paper outcomes
- Point-in-time replay, event labels, baseline comparisons, paper execution constraints, metrics and report generation.
- Run replay on a fixture cohort and then on a pre-specified forward dataset.

### M5 — Operational readiness
- Docker deployment locally, provider latency/credit monitoring, backfill/cursor recovery, Telegram operation and runbook.
- Only after tests, results and explicit approval: optional broader provider plan or cloud deployment.

## 16. Known risks and open implementation decisions

- Birdeye endpoints and entitlement may differ across plans; implement live entitlement preflight and feature flags.
- Bonding-curve data cannot use conventional DEX liquidity assumptions.
- Wash trading can mimic accumulation; coordinated funding may indicate insiders or simply shared exchange infrastructure.
- Holder sets and authority fields can change faster than cached provider reports.
- Sparse history, survivorship bias, stale liquidity, token migrations and noisy tiny price quotes can distort backtests.
- Market cap may not be available, while FDV may be misleading; use distinct nullable typed fields.
- Telegram delivery is best-effort and must not be described as a guaranteed instant alert.
- No automatic real-money action in v1 regardless of score.

## 17. Configuration contract (illustrative)

```yaml
chain: solana
mode: research_only
providers:
  birdeye: {enabled: true, discovery_poll_seconds: 30}
  dexscreener: {enabled: true, market_poll_seconds: 30}
  helius: {enabled: true, deep_wallet_checks: true}
  rugcheck: {enabled: true}
scanners:
  pump: {enabled: true, min_score: 75, min_liquidity_usd: 10000}
  dump: {enabled: true, min_score: 75, min_independent_warning_families: 2}
  rug: {enabled: true, block_unknown_security: true}
limits:
  max_deep_tokens: 20
  max_daily_provider_credits: null # override based on actual plan
  alert_cooldown_minutes: 30
trading:
  enabled: false
```

## 18. Reference documentation (verify at implementation time)

- DEX Screener official API: https://docs.dexscreener.com/api/reference
- Helius Wallet API: https://www.helius.dev/wallet-api
- Helius Parsed Events/Streams announcement (2026-09-03): https://www.helius.dev/blog/parsed-events-and-streams
- Birdeye API documentation: https://docs.birdeye.so/
- RugCheck risk API: https://api.rugcheck.xyz/docs
- Telegram Bot API: https://core.telegram.org/bots/api

**Product disclaimer:** All scores are heuristic research outputs. Memecoins are highly volatile and susceptible to insider manipulation, thin liquidity, technical failure and total loss. No alert is a guarantee of a pump, dump, or executable profit.
