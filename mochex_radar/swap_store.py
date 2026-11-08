"""Immutable normalized swap observations; no provider calls or signal approval."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

from cluster_radar.intelligence.research import Swap, require_utc


def initialize_swap_store(dsn):
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS normalized_swap_observations (
            source text NOT NULL, signature text NOT NULL, instruction_path integer[] NOT NULL,
            swap_index integer NOT NULL, mint text NOT NULL, known_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            content_hash text NOT NULL, payload jsonb NOT NULL,
            PRIMARY KEY (source, signature, instruction_path, swap_index))""")
        conn.execute("""CREATE INDEX IF NOT EXISTS normalized_swap_history_idx
            ON normalized_swap_observations (mint, known_at DESC)""")


def store_swap(dsn, swap: Swap, *, connection=None) -> str:
    if connection is None:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            return store_swap(dsn, swap, connection=conn)
    payload = asdict(swap)
    for name in ("event_at", "known_at"):
        payload[name] = payload[name].isoformat()
    for name in ("token_amount", "usd_amount"):
        if payload[name] is not None:
            payload[name] = str(payload[name])
    payload["instruction_path"] = list(swap.instruction_path)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = (swap.source, swap.signature, list(swap.instruction_path), swap.swap_index)
    row = connection.execute("""INSERT INTO normalized_swap_observations
        (source,signature,instruction_path,swap_index,mint,known_at,content_hash,payload)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING content_hash""",
        (*key, swap.mint, swap.known_at, digest, Jsonb(payload))).fetchone()
    if row is None:
        previous = connection.execute("""SELECT content_hash FROM normalized_swap_observations
            WHERE source=%s AND signature=%s AND instruction_path=%s::integer[] AND swap_index=%s""", key).fetchone()
        if previous is None or previous[0] != digest:
            raise ValueError("conflicting immutable swap observation")
    return digest


def swap_history(dsn, mint: str, as_of: datetime, limit=1000):
    require_utc(as_of)
    if not mint or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("mint and limit 1..1000 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        rows = conn.execute("""SELECT payload FROM normalized_swap_observations
            WHERE mint=%s AND known_at<=%s AND ingested_at<=%s
            ORDER BY known_at DESC,source,signature,instruction_path,swap_index LIMIT %s""",
            (mint, as_of, as_of, limit + 1)).fetchall()
    if len(rows) > limit:
        raise ValueError("swap history exceeds limit; completeness unknown")
    swaps = []
    for (payload,) in rows:
        data = dict(payload)
        for name in ("event_at", "known_at"):
            data[name] = datetime.fromisoformat(data[name])
        for name in ("token_amount", "usd_amount"):
            if data[name] is not None:
                data[name] = Decimal(data[name])
        data["instruction_path"] = tuple(data["instruction_path"])
        swaps.append(Swap(**data))
    return swaps
