"""Immutable provenance envelopes; raw evidence and swap linkage are separate."""

import psycopg
from psycopg.types.json import Jsonb

from cluster_radar.intelligence.research import require_utc
from mochex_radar.history_provenance import HistoryProvenance


def initialize_history_batches(dsn):
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS history_provenance_batches (
            batch_id text PRIMARY KEY, wallet text NOT NULL,
            retrieved_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            envelope jsonb NOT NULL)""")
        conn.execute("""CREATE INDEX IF NOT EXISTS history_provenance_wallet_idx
            ON history_provenance_batches (wallet, retrieved_at DESC)""")


def store_provenance(dsn, provenance: HistoryProvenance):
    envelope = provenance.envelope()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        added = conn.execute("""INSERT INTO history_provenance_batches
            (batch_id,wallet,retrieved_at,envelope) VALUES (%s,%s,%s,%s)
            ON CONFLICT DO NOTHING RETURNING batch_id""",
            (envelope["batch_id"], provenance.wallet, provenance.retrieved_at, Jsonb(envelope))).fetchone()
        if added is None:
            old = conn.execute("SELECT envelope FROM history_provenance_batches WHERE batch_id=%s",
                               (envelope["batch_id"],)).fetchone()
            if old is None or old[0] != envelope:
                raise ValueError("conflicting provenance envelope")
    return envelope["batch_id"]


def provenance_history(dsn, wallet, as_of, limit=100):
    require_utc(as_of)
    if not wallet or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("wallet and limit 1..100 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        rows = conn.execute("""SELECT envelope FROM history_provenance_batches
            WHERE wallet=%s AND retrieved_at<=%s AND ingested_at<=%s
            ORDER BY retrieved_at DESC,batch_id LIMIT %s""",
            (wallet, as_of, as_of, limit + 1)).fetchall()
    if len(rows) > limit:
        raise ValueError("provenance history exceeds limit")
    return [row[0] for row in rows]
