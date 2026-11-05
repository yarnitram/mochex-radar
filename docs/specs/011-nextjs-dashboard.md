# Spec 011 — Next.js research dashboard

## Scope

Next.js App Router and TypeScript UI for stored seven-pair core observations,
provisional BTC context, last collector cycle, and recorded DEX scans. Category
filters use operator-provided Meme/AI tags. Signal scores are unavailable until
their independent evaluation engines are implemented.

## Data and failure behavior

New FastAPI endpoint `/api/v1/dashboard/core` reads the newest stored 15m candle
for each of the seven MEXC USDT futures contracts. No exchange call is made.
Observations older than 30 minutes, future closes or future retrievals are stale.
Missing price is null and rendered as an em dash. Stored price remains a decimal
string; display formatting uses browser numbers only, never financial calculations.

Browser fetches same-origin `/api/dashboard` every 30s or on manual refresh.
The Next server aggregates four fixed FastAPI paths with independent 5s timeouts,
runtime schemas and no caching. `RADAR_API_ORIGIN` stays server-side (default
`http://127.0.0.1:8000`). Individual failures show unavailable data. A failed browser
refresh retains the last snapshot and explicitly marks core observations outdated.
The last collector cycle is not presented as a live worker heartbeat.

## Running

Node 24 and Python 3.12 are the tested runtime targets. In `dashboard`, run
`npm ci`, `npm run dev`, or `npm run build` then `npm start`. Local listeners bind
to loopback. Docker uses Next standalone output under an unprivileged user.
Compose adds dashboard at localhost:3000 with the internal API origin. No public
hosting, authentication, or Proxmox rollout is part of this feature. Keep access
internal until the deployment access-control milestone.

## Acceptance

- Production build and TypeScript check pass.
- Browser tests cover all seven rows, missing/stale data, category filters,
  failed-refresh retention, explicit unavailable services and mobile overflow.
- Actual Next-to-FastAPI smoke shows seven configured pairs with missing prices
  when storage is disabled; no fixture is used by production code.
- PostgreSQL CI tests verify persisted snapshot prices and freshness.

References checked 2026-11-05:
https://nextjs.org/docs/app/getting-started/installation
https://nextjs.org/docs/app/api-reference/config/next-config-js/output
