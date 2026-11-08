"""Immutable provenance envelopes, retained raw evidence, and atomic swap/funding batch linkage."""

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from cluster_radar.intelligence.research import FundingEvidence, Swap, require_utc
from mochex_radar.funding_store import initialize_funding_store, store_funding
from mochex_radar.history_provenance import HistoryProvenance
from mochex_radar.swap_store import initialize_swap_store, store_swap


def canonical_raw_sha256(raw_payload: object) -> str:
    if not isinstance(raw_payload, (list, dict)):
        raise ValueError("raw_payload must be a JSON list or object")
    encoded = json.dumps(raw_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def initialize_history_batches(dsn) -> None:
    initialize_swap_store(dsn)
    initialize_funding_store(dsn)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS history_provenance_batches (
            batch_id text PRIMARY KEY, wallet text NOT NULL,
            retrieved_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            envelope jsonb NOT NULL)""")
        conn.execute("""CREATE INDEX IF NOT EXISTS history_provenance_wallet_idx
            ON history_provenance_batches (wallet, retrieved_at DESC)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS history_raw_evidence (
            raw_sha256 text PRIMARY KEY,
            raw_payload jsonb NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS history_batch_items (
            batch_id text NOT NULL REFERENCES history_provenance_batches(batch_id),
            item_type text NOT NULL CHECK (item_type IN ('swap', 'funding')),
            item_key text NOT NULL,
            content_hash text NOT NULL,
            PRIMARY KEY (batch_id, item_type, item_key))""")


def store_provenance(dsn, provenance: HistoryProvenance, *, connection=None) -> str:
    if connection is None:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            return store_provenance(dsn, provenance, connection=conn)
    envelope = provenance.envelope()
    added = connection.execute(
        """INSERT INTO history_provenance_batches
        (batch_id,wallet,retrieved_at,envelope) VALUES (%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING batch_id""",
        (envelope["batch_id"], provenance.wallet, provenance.retrieved_at, Jsonb(envelope)),
    ).fetchone()
    if added is None:
        old = connection.execute(
            "SELECT envelope FROM history_provenance_batches WHERE batch_id=%s",
            (envelope["batch_id"],),
        ).fetchone()
        if old is None or old[0] != envelope:
            raise ValueError("conflicting provenance envelope")
    return envelope["batch_id"]


def _store_raw_evidence(connection, raw_sha256: str, raw_payload: object) -> None:
    computed = canonical_raw_sha256(raw_payload)
    if computed != raw_sha256:
        raise ValueError("raw payload SHA256 does not match provenance raw_sha256")
    added = connection.execute(
        """INSERT INTO history_raw_evidence (raw_sha256, raw_payload)
        VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING raw_sha256""",
        (raw_sha256, Jsonb(raw_payload)),
    ).fetchone()
    if added is None:
        old = connection.execute(
            "SELECT raw_payload FROM history_raw_evidence WHERE raw_sha256=%s",
            (raw_sha256,),
        ).fetchone()
        if old is None or canonical_raw_sha256(old[0]) != raw_sha256:
            raise ValueError("conflicting retained raw evidence")


def _link_batch_item(connection, batch_id: str, item_type: str, item_key: str, content_hash: str) -> None:
    added = connection.execute(
        """INSERT INTO history_batch_items (batch_id, item_type, item_key, content_hash)
        VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING content_hash""",
        (batch_id, item_type, item_key, content_hash),
    ).fetchone()
    if added is None:
        old = connection.execute(
            """SELECT content_hash FROM history_batch_items
            WHERE batch_id=%s AND item_type=%s AND item_key=%s""",
            (batch_id, item_type, item_key),
        ).fetchone()
        if old is None or old[0] != content_hash:
            raise ValueError("conflicting batch item linkage")


def store_history_batch(
    dsn,
    provenance: HistoryProvenance,
    *,
    raw_payload: object | None = None,
    swaps: Sequence[Swap] = (),
    funding: Sequence[FundingEvidence] = (),
) -> str:
    if raw_payload is not None and canonical_raw_sha256(raw_payload) != provenance.raw_sha256:
        raise ValueError("raw payload SHA256 does not match provenance raw_sha256")
    for swap in swaps:
        if swap.source != provenance.source or swap.known_at > provenance.retrieved_at:
            raise ValueError("swap violates batch provenance source or retrieval timestamp")
    for item in funding:
        if item.source != provenance.source or item.known_at > provenance.retrieved_at:
            raise ValueError("funding violates batch provenance source or retrieval timestamp")

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        batch_id = store_provenance(dsn, provenance, connection=conn)
        if raw_payload is not None:
            _store_raw_evidence(conn, provenance.raw_sha256, raw_payload)
        for swap in swaps:
            digest = store_swap(dsn, swap, connection=conn)
            path_str = ".".join(map(str, swap.instruction_path))
            key = f"{swap.source}:{swap.signature}:{path_str}:{swap.swap_index}"
            _link_batch_item(conn, batch_id, "swap", key, digest)
        for item in funding:
            digest = store_funding(dsn, item, connection=conn)
            key = f"{item.source}:{item.signature}:{item.wallet}:{item.funder}"
            _link_batch_item(conn, batch_id, "funding", key, digest)
    return batch_id


def provenance_history(dsn, wallet: str, as_of: datetime, limit: int = 100) -> list[dict]:
    require_utc(as_of)
    if not wallet or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("wallet and limit 1..100 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        rows = conn.execute(
            """SELECT envelope FROM history_provenance_batches
            WHERE wallet=%s AND retrieved_at<=%s AND ingested_at<=%s
            ORDER BY retrieved_at DESC,batch_id LIMIT %s""",
            (wallet, as_of, as_of, limit + 1),
        ).fetchall()
    if len(rows) > limit:
        raise ValueError("provenance history exceeds limit")
    return [row[0] for row in rows]


def retained_raw_evidence(dsn, raw_sha256: str, as_of: datetime) -> object | None:
    require_utc(as_of)
    if not isinstance(raw_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_sha256):
        raise ValueError("valid raw_sha256 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        row = conn.execute(
            """SELECT raw_payload FROM history_raw_evidence
            WHERE raw_sha256=%s AND ingested_at<=%s""",
            (raw_sha256, as_of),
        ).fetchone()
    return row[0] if row else None
