# Mochex Radar

Unified read-only Crypto Radar platform.

This repository is the source-code home for the Mochex Radar project. Planning artifacts are maintained in the Command Center vault under `02 - Projects/Active/Crypto-Radar`.

## Scope

- Python/FastAPI scanner engine
- Next.js/TypeScript dashboard
- PostgreSQL and Redis
- Real-time CEX and DEX data adapters
- BTC market-context filter
- Meme, AI, and new DEX token scanners
- Protected Solana Cluster Radar integration
- Telegram alerts and backtesting

The initial release must not place trades, access exchange accounts, sign wallets, or handle private keys.

## Start here

- `docs/PRD.md`
- `docs/Codex-Prompts.md`
- Command Center vault: `C:\Users\Samjie\CommandCenter\02 - Projects\Active\Crypto-Radar`

## Foundation development

Use Python 3.12 or newer. In a virtual environment, install with `python -m pip install -e ".[test]"`, run `python -m pytest`, and start the API with `python -m uvicorn mochex_radar.api:app --reload`. `GET /api/v1/markets/core` reports configured markets only; it does not provide live prices. See `docs/specs/001-foundation-api.md` for the current feature contract.

MEXC USDT futures is the first public reference venue. `GET /api/v1/market-data/SOL_USDT/15m` fetches the newest closed contract candle on demand without an account key. The response is an observation, not a signal. See `docs/specs/002-mexc-futures-candles.md`.

## Scheduled collection (phase 3)

Copy `.env.example` to `.env` and replace both placeholder values with the same strong password (URL encode special characters in `DATABASE_URL`). Run `docker compose up --build` to start PostgreSQL, the API, and a single collector. PostgreSQL stays inside the Compose network; the API binds to localhost port 8000. The collector visits seven contracts at 15m and 1h every 60 seconds and stores closed candles idempotently. `GET /api/v1/collector/status` shows the last completed cycle. Keep exactly one collector replica until distributed coordination is implemented. Backups and restore testing are required before Proxmox deployment. See `docs/specs/003-candle-collector.md`.

The collector also observes `BTC_USDT` at 15m for context only. After four consecutive closed candles, `GET /api/v1/market-context/btc` returns a provisional BTC regime with its evidence; until then it returns `unknown`. Thresholds are screening hypotheses and do not trigger any trading action. See `docs/specs/004-btc-context.md`.

## MEXC WebSocket stream

The Compose stack includes a public futures `streamer` process. It subscribes to the same 15 candle targets, maintains application pings, and persists a candle only after its next window begins. The REST collector continues to reconcile closed windows. Run `python -m mochex_radar.websocket_feed --smoke` to verify one public SOL subscription without database access or writes. See `docs/specs/005-mexc-websocket.md`.

## Cluster Radar and Solana pool context

The preserved Cluster Radar source is included as a versioned package snapshot;
see `integrations/cluster-radar/README.md` for provenance and update instructions.
Set `DEX_LOOKUP_ENABLED=true` to enable `GET /api/v1/dex/solana/{mint}/pools`.
One API worker may attempt up to `DEX_LOOKUP_MAX_REQUESTS` (default 100) lookups
per process lifetime. Keep it behind trusted internal access. Responses retain
unknown security status until independent risk evidence is implemented.
See `docs/specs/007-cluster-integration.md` for limits and remaining scope.

With a database configured, DEX lookups also share a durable UTC-day ceiling
(`DEX_LOOKUP_DAILY_REQUESTS`, default 100). Failed requests count and API restarts
retain usage. All workers must use the same setting. See
`docs/specs/009-persistent-provider-budget.md`.

The optional `dex-scanner` Compose profile scans configured Solana mints on a
schedule, using the shared durable request budget. Populate `config/dex-watchlist.json`
with explicit categories and provenance before enabling it. Scan audit records are
available at `GET /api/v1/dex/scans`. Setup and limits:
`docs/specs/010-dex-watchlist-worker.md`.

## Dashboard

Compose includes the Next.js dashboard at `http://localhost:3000`. It reads stored
observations, shows BTC context and scan history, and refreshes every 30 seconds.
For local development, start the FastAPI service on port 8000, then run `npm ci`
and `npm run dev` inside `dashboard` (Node 24). For a local production preview,
run `npm run build` then `npm start`. Override server-only `RADAR_API_ORIGIN` if
your API runs elsewhere. See `docs/specs/011-nextjs-dashboard.md`.

## Operational Telegram outbox

Preview with `python -m mochex_radar.alert_worker --enqueue-test --dry-run` after
configuring a private DATABASE_URL. Actual sending requires both `--send` and
`TELEGRAM_SEND_ENABLED=true`, plus private bot token and destination configuration.
The worker uses durable deduplication, cooldowns, expiry and attempt limits.
Ambiguous delivery is held for review. Market-signal producers are not enabled.
See `docs/specs/012-telegram-outbox.md` before enabling the optional Compose
`alerts` profile. `GET /api/v1/alerts/status` reports counts only.

Optional `ALERT_DATA_QUALITY_ENABLED=true` queues incomplete MEXC collection-cycle
notices after candle storage succeeds. It does not enable Telegram sending.
Healthy duplicate cycles do not create warnings; queue errors do not undo stored
candles. See `docs/specs/013-collector-quality-notices.md`.

Dashboard Alert delivery shows stored operational-notice state counts, including
uncertain deliveries held for review. It does not send or retry messages and does
not assert worker availability. Disabled/unavailable storage remains explicit.
See `docs/specs/014-alert-health-dashboard.md`.

## Solana profile discovery

Optional `docker compose --profile discovery up --build -d` observes the public
DEX Screener latest-profile window and selects bounded pool scans. Defaults are
one poll/hour, 24 profile requests/day and three deeper candidates per poll.
The pool budget is shared with manual/curated lookups. Candidates stay unclassified
with UNKNOWN security. Profile appearance does not prove token age or quality.
Read-only poll/catalog APIs and coverage limits: `docs/specs/015-profile-discovery.md`.

The dashboard Discovery catalog displays up to 100 newest observed profiles and
10 recent polls. Mint search and scan-attempt filters apply to the loaded subset.
It preserves UNKNOWN security and distinguishes observation time from token age.
See `docs/specs/016-discovery-catalog-dashboard.md`.

## Partial Solana authority evidence

Optional `SOLANA_AUTHORITIES_ENABLED=true` enables read-only original SPL mint and
freeze authority lookup, backed by mandatory PostgreSQL evidence storage and a
shared daily request budget. Overall security stays UNKNOWN, including when both
authorities are disabled. Token-2022 and other security checks remain unevaluated.
API, history/freshness behavior and public-RPC constraints:
`docs/specs/017-solana-authority-evidence.md`.

Dashboard Authority evidence reads stored partial observations without making RPC
calls. Mint search/freshness filters apply to the newest 100 readings. Permission
absence is distinct from safety; overall security remains UNKNOWN. See
`docs/specs/018-authority-evidence-dashboard.md`.

## Offline wallet research

`python -m mochex_radar.research_report --input tests/fixtures/research-dataset.json`
generates a synthetic example of point-in-time swap/funding metrics and provisional
PRD-weighted Pump/Dump scores. It makes no provider calls, approves no signal and
sends no alert. Strict input/provenance requirements and limitations:
`docs/specs/019-wallet-research-reports.md`. Remaining major work areas:
`docs/REMAINING-ROADMAP.md`.

## Offline core-feature comparison

`python -m mochex_radar.feature_validation --input tests/fixtures/core-feature-validation.json --output work/core-feature-report.json`

Create the output directory first. The synthetic fixture demonstrates chronological
development/holdout comparisons and unconditional baselines; it is not live market
performance. Reports retain unavailable reasons, first-observation cutoffs and
dataset/config hashes, and refuse to overwrite files. Gross candle returns do not
simulate execution, costs or profitability. See `docs/specs/025-core-feature-validation.md`.

For actual stored observations, the manual `mochex_radar.validation_export` command
creates an input dataset without calling the exchange or changing the database.
Runbook, prerequisites and timestamp limitations: `docs/REAL-DATA-VALIDATION.md`.

`python -m mochex_radar.research_registry --help` provides private local run bundles,
hash verification and source-matched replay. It preserves exact dataset bytes and
keeps synthetic/observed labels explicit; neither label establishes data authenticity.

Optional format-2 inputs add explicit hypothetical fee/spread/slippage/funding
scenarios to the same comparison and registry commands. The example
`tests/fixtures/core-feature-costs.json` uses invented costs, not a MEXC fee schedule.
Model formulas, limits and assumptions: `docs/specs/028-research-cost-sensitivity.md`.

`python -m mochex_radar.validation_readiness --input work/sol-dataset-v1.json --output work/sol-coverage-v1.json`
checks point-in-time history, gaps, BTC context and outcome coverage before
interpreting comparisons. Complete coverage does not establish statistical sample
adequacy, data authenticity or production readiness. See `docs/specs/029-validation-coverage-readiness.md`.

Manual forward tracking is available through `python -m mochex_radar.paper_journal --help`.
It predeclares future plans and preserves separate capture/outcome snapshots,
including missed and unavailable observations. No live campaign is started by
installation. Workflow and limits: `docs/FORWARD-PAPER-TRACKING.md`.
