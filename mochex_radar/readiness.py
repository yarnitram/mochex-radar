"""Sanitized durable-store readiness; cache loss is a separate degraded condition."""

import psycopg

from mochex_radar.initialize import SCHEMA_VERSION

REQUIRED_TABLES = ("market_candles", "collector_cycles", "dex_observations", "provider_request_budgets",
                   "dex_scans", "alert_outbox", "profile_polls", "discovered_mints", "mint_authority_observations", "schema_versions")


def database_ready(dsn):
    if not dsn:
        return False
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '2s'")
            found = conn.execute("SELECT to_regclass(name) IS NOT NULL FROM unnest(%s::text[]) AS name", (list(REQUIRED_TABLES),)).fetchall()
            return all(row[0] for row in found) and conn.execute("SELECT 1 FROM schema_versions WHERE version=%s", (SCHEMA_VERSION,)).fetchone() is not None
    except psycopg.Error:
        return False
