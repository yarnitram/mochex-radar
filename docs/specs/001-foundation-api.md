# Spec 001 — Foundation API and asset identity

Status: implementation candidate (2026-11-05)

## Scope

Create a read only FastAPI service with a deterministic registry for the seven core USDT markets. This phase supplies no market data, signals, accounts, or trading operations.

## Contract

- `GET /health/live` returns HTTP 200 and `{"status":"ok"}` when the process can serve requests.
- `GET /api/v1/markets/core` returns seven configured CEX markets and a `data_status` of `configuration_only`.
- Each market has `venue`, `market_id`, `base`, `quote`, and `asset_id`. The ID is derived from venue and market ID, not ticker alone.
- `BTC` is absent from the trading universe. It will enter a later phase as market context.
- Spec 002 assigns the initial venue and contract IDs to MEXC USDT futures; this supersedes the original `unassigned` placeholder.
- Unsupported HTTP methods and nonexistent paths cannot place orders or mutate state.

## Invariants and failure behavior

- Exactly one market per configured venue and market ID.
- Pair symbols do not determine identity; the same ticker on another venue has a distinct identity.
- Empty venue or market ID is rejected during registry construction.
- All responses are explicit that no live data is connected.

## Acceptance

- Unit tests cover uniqueness, identity collision, and input validation.
- API tests cover health, seven pairs, and rejection of mutation requests.
- The service starts locally with documented commands.
