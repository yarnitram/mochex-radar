"""Idempotent one-shot pilot schema bootstrap; no provider requests or sending."""

import os

import psycopg

from mochex_radar.alert_store import initialize_alert_store
from mochex_radar.authority_checks import initialize_authority_store
from mochex_radar.candidate_evaluation import initialize_holder_store
from mochex_radar.funding_store import initialize_funding_store
from mochex_radar.history_batch_store import initialize_history_batches
from mochex_radar.profile_discovery import initialize_discovery_store
from mochex_radar.storage import initialize_database
from mochex_radar.swap_store import initialize_swap_store

SCHEMA_VERSION = "pilot-schema-v1"


def initialize(dsn: str):
    # Existing initializers are additive/idempotent. Mark complete only after all succeed.
    initialize_database(dsn)
    initialize_discovery_store(dsn)
    initialize_authority_store(dsn)
    initialize_holder_store(dsn)
    initialize_swap_store(dsn)
    initialize_funding_store(dsn)
    initialize_history_batches(dsn)
    initialize_alert_store(dsn)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_versions (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT clock_timestamp())")
        conn.execute("INSERT INTO schema_versions (version) VALUES (%s) ON CONFLICT DO NOTHING", (SCHEMA_VERSION,))


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL required in private configuration")
    try:
        initialize(dsn)
    except psycopg.Error:
        raise SystemExit("Schema bootstrap failed; check private connection and permissions") from None
    print("Pilot schema initialized; no provider calls or messages sent.")


if __name__ == "__main__":
    main()
