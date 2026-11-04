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

Use Python 3.11 or newer. In a virtual environment, install with `python -m pip install -e ".[test]"`, run `python -m pytest`, and start the API with `python -m uvicorn mochex_radar.api:app --reload`. `GET /api/v1/markets/core` reports configured markets only; it does not provide live prices. See `docs/specs/001-foundation-api.md` for the current feature contract.

MEXC USDT futures is the first public reference venue. `GET /api/v1/market-data/SOL_USDT/15m` fetches the newest closed contract candle on demand without an account key. The response is an observation, not a signal. See `docs/specs/002-mexc-futures-candles.md`.

## Scheduled collection (phase 3)

Copy `.env.example` to `.env` and replace both placeholder values with the same strong password (URL encode special characters in `DATABASE_URL`). Run `docker compose up --build` to start PostgreSQL, the API, and a single collector. PostgreSQL stays inside the Compose network; the API binds to localhost port 8000. The collector visits seven contracts at 15m and 1h every 60 seconds and stores closed candles idempotently. `GET /api/v1/collector/status` shows the last completed cycle. Keep exactly one collector replica until distributed coordination is implemented. Backups and restore testing are required before Proxmox deployment. See `docs/specs/003-candle-collector.md`.
