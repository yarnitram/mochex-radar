# Stored coverage audit

Run `python -m mochex_radar.coverage_audit` inside the deployed API container.
Use its private DATABASE_URL without displaying credentials. This manual command
reads the existing bounded export adapter and makes no provider calls or writes.

Report all seven markets on both intervals, visible rows over 24 intervals,
latest close/retrieval, gap count, feature readiness and BTC alignment reason.
Preserve missing rows and ingestion cutoffs. Each market query has its own snapshot;
the report is not a database-wide atomic snapshot. WebSocket freshness is explicitly
unassessed and requires separate evidence. This report does not validate profits.
