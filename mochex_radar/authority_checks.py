"""Bounded partial security evidence with immutable point-in-time storage."""

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.solana_authorities import SOURCE, AuthorityObservation, SolanaAuthorities, decode_pubkey
from mochex_radar.provider_budget import initialize_budget_store, reserve_request

SCHEMA = """
CREATE TABLE IF NOT EXISTS mint_authority_observations (
    mint text NOT NULL, source text NOT NULL, known_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    slot bigint NOT NULL CHECK (slot>=0), content_hash text NOT NULL,
    payload jsonb NOT NULL CHECK (payload @> '{"security_status":"UNKNOWN","approved_pump_watch":false}'::jsonb),
    PRIMARY KEY (mint,source,known_at)
);
CREATE INDEX IF NOT EXISTS mint_authority_history_idx ON mint_authority_observations (mint,known_at DESC);
CREATE INDEX IF NOT EXISTS mint_authority_recent_idx ON mint_authority_observations (known_at DESC,mint,source);
"""


def initialize_authority_store(dsn: str):
    initialize_budget_store(dsn)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA)


def store_authority(dsn: str, observation: AuthorityObservation):
    decode_pubkey(observation.mint)
    if observation.known_at.tzinfo is None or observation.known_at.utcoffset() != timedelta(0):
        raise ValueError("known_at must be UTC")
    payload = jsonable_encoder(asdict(observation))
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = (observation.mint, observation.source, observation.known_at)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        added = conn.execute("""INSERT INTO mint_authority_observations
            (mint,source,known_at,slot,content_hash,payload) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING RETURNING mint""", (*key, observation.slot, digest, Jsonb(payload))).fetchone()
        if added is None:
            old = conn.execute("""SELECT content_hash FROM mint_authority_observations
                WHERE mint=%s AND source=%s AND known_at=%s""", key).fetchone()
            if old is None or old[0] != digest:
                raise ValueError("conflicting immutable authority evidence")


def authority_history(dsn: str, mint: str, as_of: datetime, limit: int = 10):
    decode_pubkey(mint)
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0) or not 1 <= limit <= 100:
        raise ValueError("UTC cutoff and limit 1..100 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute("""SELECT payload,known_at,ingested_at FROM mint_authority_observations
            WHERE mint=%s AND known_at<=%s AND ingested_at<=%s
            ORDER BY known_at DESC,source LIMIT %s""", (mint, as_of, as_of, limit)).fetchall()
    return _format_rows(rows, as_of)


def _format_rows(rows, as_of):
    return [{"evidence":row[0], "ingested_at":row[2].isoformat(),
             "freshness":"current" if as_of-row[1] < timedelta(minutes=15) else "stale",
             "expires_at":(row[1]+timedelta(minutes=15)).isoformat()} for row in rows]


def authority_snapshot(dsn: str, limit: int = 100, *, as_of: datetime | None = None):
    as_of = as_of or datetime.now(timezone.utc)
    if not 1 <= limit <= 100 or as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("limit 1..100 and UTC as_of required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute("""SELECT payload,known_at,ingested_at FROM mint_authority_observations
            WHERE known_at<=%s AND ingested_at<=%s
            ORDER BY known_at DESC,mint,source LIMIT %s""", (as_of,as_of,limit)).fetchall()
    return {"status":"stored_partial_evidence", "as_of":as_of.isoformat(),
            "observations":_format_rows(rows,as_of), "security_status":"UNKNOWN", "approved_pump_watch":False}


class PersistentAuthorities:
    def __init__(self, inner: SolanaAuthorities, dsn: str, daily_limit: int):
        if daily_limit < 1:
            raise ValueError("positive authority request limit required")
        self.inner, self.dsn, self.daily_limit = inner, dsn, daily_limit
        self._lock = asyncio.Lock()

    async def check(self, mint: str):
        decode_pubkey(mint)
        async with self._lock:
            if self.inner.requests >= self.inner.max_requests:
                raise BudgetExceeded("process authority request ceiling exhausted")
            try:
                while delay := await asyncio.to_thread(reserve_request, self.dsn, self.daily_limit,
                                                       provider=SOURCE, spacing_seconds=1.1):
                    await asyncio.sleep(delay)
            except psycopg.Error as exc:
                raise ProviderUnavailable("authority request budget unavailable") from exc
            return await self.inner.check(mint)
