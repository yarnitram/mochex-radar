"""Immutable DEX observations with separate provider and ingestion knowledge times."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from cluster_radar.discovery.identity import Candidate, MarketStage

SCHEMA = """
CREATE TABLE IF NOT EXISTS dex_observations (
    mint text NOT NULL,
    pool_id text NOT NULL,
    source text NOT NULL,
    known_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    content_hash text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (mint, pool_id, source, known_at)
);
CREATE INDEX IF NOT EXISTS dex_observations_history_idx
ON dex_observations (mint, known_at DESC);
"""


def initialize_dex_store(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA)


def store_observations(dsn: str, candidates: list[Candidate], *, connection=None) -> int:
    """A repeated observation is idempotent; conflicting content rolls back the batch."""
    if connection is None:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            return store_observations(dsn, candidates, connection=conn)
    inserted = 0
    conn = connection
    for candidate in candidates:
        if candidate.stage is not MarketStage.DEX:
            raise ValueError("only DEX pool observations are supported")
        payload = jsonable_encoder(asdict(candidate), custom_encoder={Decimal: str})
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        key = (candidate.mint, candidate.pool_id, candidate.source, candidate.known_at)
        cursor = conn.execute(
            """INSERT INTO dex_observations
            (mint, pool_id, source, known_at, content_hash, payload)
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (*key, digest, Jsonb(payload)),
        )
        inserted += cursor.rowcount
        if not cursor.rowcount:
            existing = conn.execute(
                """SELECT content_hash FROM dex_observations
                WHERE mint=%s AND pool_id=%s AND source=%s AND known_at=%s""", key,
            ).fetchone()
            if existing is None or existing[0] != digest:
                raise ValueError("conflicting immutable observation")
    return inserted


def observation_history(dsn: str, mint: str, as_of: datetime, *, limit: int = 100) -> list[dict]:
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be UTC")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(
            """SELECT payload, ingested_at, content_hash FROM dex_observations
            WHERE mint=%s AND known_at<=%s AND ingested_at<=%s
            ORDER BY known_at DESC, pool_id, source LIMIT %s""",
            (mint, as_of, as_of, limit),
        ).fetchall()
    return [{"candidate": row[0], "ingested_at": row[1].isoformat(), "content_hash": row[2]}
            for row in rows]
