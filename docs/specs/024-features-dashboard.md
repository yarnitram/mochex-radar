# Spec 024 — Stored core features dashboard

Continue phase/features-dashboard after user updates through 20c7381.
Read stored 15m features via the existing bounded snapshot; validate seven pairs,
provisional research and disabled signals. Show ATR percentage, relative volume,
BTC relative strength, volatility, structure, missing reasons and evidence times.
Missing is Unknown, never zero. Failed refresh marks retained data outdated.
No live provider requests, backfill, alerts or trading from the UI.

Acceptance: frontend build/typecheck, contract guards and browser regressions;
backend regressions. API failure remains isolated from other snapshot services.
