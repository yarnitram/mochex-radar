"""Immutable normalized wallet funding observations; no provider calls or signal approval."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from cluster_radar.intelligence.research import FundingEvidence, require_utc


def initialize_funding_store(dsn) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS normalized_funding_observations (
            source text NOT NULL,
            signature text NOT NULL,
            wallet text NOT NULL,
            funder text NOT NULL,
            event_at timestamptz NOT NULL,
            known_at timestamptz NOT NULL,
            label text NOT NULL CHECK (label IN ('CEX', 'NON_CEX', 'UNKNOWN')),
            label_known_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            content_hash text NOT NULL,
            payload jsonb NOT NULL,
            PRIMARY KEY (source, signature, wallet, funder))""")
        conn.execute("""CREATE INDEX IF NOT EXISTS normalized_funding_wallet_idx
            ON normalized_funding_observations (wallet, known_at DESC)""")


def store_funding(dsn, funding: FundingEvidence, *, connection=None) -> str:
    if connection is None:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            return store_funding(dsn, funding, connection=conn)
    payload = asdict(funding)
    for name in ("event_at", "known_at", "label_known_at"):
        payload[name] = payload[name].isoformat()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = (funding.source, funding.signature, funding.wallet, funding.funder)
    row = connection.execute(
        """INSERT INTO normalized_funding_observations
        (source, signature, wallet, funder, event_at, known_at, label, label_known_at, content_hash, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING RETURNING content_hash""",
        (
            *key,
            funding.event_at,
            funding.known_at,
            funding.label,
            funding.label_known_at,
            digest,
            Jsonb(payload),
        ),
    ).fetchone()
    if row is None:
        previous = connection.execute(
            """SELECT content_hash FROM normalized_funding_observations
            WHERE source=%s AND signature=%s AND wallet=%s AND funder=%s""",
            key,
        ).fetchone()
        if previous is None or previous[0] != digest:
            raise ValueError("conflicting immutable funding observation")
    return digest


def _normalize_wallets(wallets: str | Iterable[str]) -> list[str]:
    if isinstance(wallets, str):
        items = [wallets]
    elif isinstance(wallets, Iterable):
        items = list(wallets)
    else:
        raise ValueError("nonempty wallet or wallet list required")
    if not items or len(items) > 500:
        raise ValueError("nonempty valid wallet set (max 500) required")
    cleaned = sorted({w for w in items if isinstance(w, str) and w.strip()})
    if not cleaned or len(cleaned) != len(set(items)):
        raise ValueError("nonempty valid wallet set (max 500) required")
    return cleaned


def funding_history(dsn, wallets: str | Iterable[str], as_of: datetime, limit: int = 1000) -> list[FundingEvidence]:
    require_utc(as_of)
    target_wallets = _normalize_wallets(wallets)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit 1..1000 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        rows = conn.execute(
            """SELECT payload FROM normalized_funding_observations
            WHERE wallet = ANY(%s) AND event_at <= %s AND known_at <= %s AND ingested_at <= %s
            ORDER BY known_at DESC, source, signature, wallet, funder LIMIT %s""",
            (target_wallets, as_of, as_of, as_of, limit + 1),
        ).fetchall()
    if len(rows) > limit:
        raise ValueError("funding history exceeds limit; completeness unknown")
    records: list[FundingEvidence] = []
    for (payload,) in rows:
        data = dict(payload)
        for name in ("event_at", "known_at", "label_known_at"):
            data[name] = datetime.fromisoformat(data[name])
        records.append(FundingEvidence(**data))
    return records
