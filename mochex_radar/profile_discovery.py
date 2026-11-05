"""Persist the observed profile window before selecting a bounded pool-scan subset."""

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row

from cluster_radar.providers.dexscreener import BudgetExceeded, DexScreener, ProviderUnavailable
from cluster_radar.providers.profiles import SOURCE, ProfileBatch, ProfileFeed
from mochex_radar.dex_worker import WatchToken, initialize_scan_store, scan_once, store_scan
from mochex_radar.provider_budget import PersistentDexScreener, reserve_request

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS profile_polls (
    id uuid PRIMARY KEY, source text NOT NULL,
    started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('success','provider_error','budget_exhausted')),
    response_hash text, input_count integer, discovered_count integer,
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS discovered_mints (
    mint text NOT NULL, source text NOT NULL,
    first_known_at timestamptz NOT NULL, last_known_at timestamptz NOT NULL,
    first_ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_scan_at timestamptz, PRIMARY KEY (mint,source)
);
CREATE TABLE IF NOT EXISTS profile_observations (
    poll_id uuid NOT NULL REFERENCES profile_polls(id),
    mint text NOT NULL, known_at timestamptz NOT NULL, PRIMARY KEY (poll_id,mint)
);
CREATE INDEX IF NOT EXISTS profile_polls_recent_idx ON profile_polls (finished_at DESC,id);
CREATE INDEX IF NOT EXISTS discovered_mints_recent_idx ON discovered_mints (first_ingested_at DESC,mint);
"""


def initialize_discovery_store(dsn: str):
    initialize_scan_store(dsn)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA)


def store_poll(dsn: str, identity, started, finished, status: str, batch: ProfileBatch | None):
    if (status == "success") != (batch is not None):
        raise ValueError("successful poll requires a batch; failure cannot include one")
    digest = batch.response_hash if batch else None
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        added = conn.execute("""INSERT INTO profile_polls
            (id,source,started_at,finished_at,status,response_hash,input_count,discovered_count)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
            (identity, SOURCE, started, finished, status, digest,
             batch.input_count if batch else None, len(batch.mints) if batch else None)).fetchone()
        if added is None:
            old = conn.execute("SELECT status,response_hash FROM profile_polls WHERE id=%s", (identity,)).fetchone()
            if old != (status, digest):
                raise ValueError("conflicting immutable poll")
            return
        if batch:
            for mint in batch.mints:
                conn.execute("""INSERT INTO discovered_mints (mint,source,first_known_at,last_known_at)
                    VALUES (%s,%s,%s,%s) ON CONFLICT (mint,source) DO UPDATE
                    SET last_known_at=greatest(discovered_mints.last_known_at,excluded.last_known_at)""",
                    (mint, SOURCE, batch.known_at, batch.known_at))
                conn.execute("INSERT INTO profile_observations (poll_id,mint,known_at) VALUES (%s,%s,%s)",
                             (identity, mint, batch.known_at))


def select_targets(dsn: str, poll_id, limit: int) -> list[WatchToken]:
    if not 1 <= limit <= 20:
        raise ValueError("pool scan limit must be 1..20")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute("""SELECT m.mint FROM discovered_mints m
            JOIN profile_observations o ON o.mint=m.mint
            WHERE o.poll_id=%s AND m.source=%s
            ORDER BY m.last_scan_at ASC NULLS FIRST,m.first_known_at,m.mint LIMIT %s""",
            (poll_id, SOURCE, limit)).fetchall()
    return [WatchToken(mint=row[0], categories=["unclassified"], category_source=SOURCE) for row in rows]


def persist_discovery_scan(dsn: str, token, identity, started, finished, status, pools):
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        store_scan(dsn, token, identity, started, finished, status, pools, connection=conn)
        if status not in ("budget_exhausted", "skipped_budget"):
            conn.execute("UPDATE discovered_mints SET last_scan_at=%s WHERE mint=%s AND source=%s",
                         (finished, token.mint, SOURCE))


async def fetch_profiles(dsn: str, feed: ProfileFeed, daily_limit: int):
    try:
        while delay := await asyncio.to_thread(reserve_request, dsn, daily_limit, provider=SOURCE, spacing_seconds=1.1):
            await asyncio.sleep(delay)
    except psycopg.Error as exc:
        raise ProviderUnavailable("profile budget unavailable") from exc
    return await feed.latest()


async def discover_once(fetch, persist_poll, choose_targets, provider, persist_scan):
    identity = uuid4()
    started = datetime.now(timezone.utc)
    batch = None
    try:
        batch = await fetch()
        status = "success"
    except BudgetExceeded:
        status = "budget_exhausted"
    except ProviderUnavailable:
        status = "provider_error"
    await persist_poll(identity, started, datetime.now(timezone.utc), status, batch)
    # Persistence must succeed before any candidate can be promoted to pool scanning.
    if status != "success":
        return status, []
    tokens = await choose_targets(identity)
    outcomes = await scan_once(tokens, provider, persist_scan)
    return status, outcomes


def recent_polls(dsn: str, limit: int = 100):
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
        return conn.execute("""SELECT id,source,started_at,finished_at,status,response_hash,input_count,
            discovered_count,ingested_at FROM profile_polls ORDER BY finished_at DESC,id LIMIT %s""", (limit,)).fetchall()


def discovered_catalog(dsn: str, limit: int = 100, offset: int = 0):
    if not 1 <= limit <= 1000 or not 0 <= offset <= 10000:
        raise ValueError("limit 1..1000 and offset 0..10000 required")
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
        return conn.execute("""SELECT mint,source,first_known_at,last_known_at,first_ingested_at,last_scan_at
            FROM discovered_mints ORDER BY first_ingested_at DESC,mint LIMIT %s OFFSET %s""", (limit,offset)).fetchall()


async def run(dsn: str, interval: int, profile_limit: int, pool_limit: int, max_scans: int, once=False):
    if interval < 60 or min(profile_limit, pool_limit) < 1 or not 1 <= max_scans <= 20:
        raise ValueError("invalid discovery limits")
    await asyncio.to_thread(initialize_discovery_store, dsn)
    async with httpx.AsyncClient() as client:
        feed = ProfileFeed(client, max_requests=2**63-1)
        provider = PersistentDexScreener(DexScreener(client, max_requests=2**63-1), dsn, pool_limit)

        async def fetch():
            return await fetch_profiles(dsn, feed, profile_limit)

        async def persist(*args):
            await asyncio.to_thread(store_poll, dsn, *args)

        async def choose(identity):
            return await asyncio.to_thread(select_targets, dsn, identity, max_scans)

        async def save_scan(*args):
            await asyncio.to_thread(persist_discovery_scan, dsn, *args)

        while True:
            status, outcomes = await discover_once(fetch, persist, choose, provider, save_scan)
            log.info("profile discovery poll=%s pool_scan_outcomes=%s", status, ",".join(outcomes))
            if once:
                return
            await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Observe public Solana profiles and scan bounded pool candidates")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL required")
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run(dsn, int(os.environ.get("PROFILE_POLL_SECONDS", "3600")),
            int(os.environ.get("PROFILE_DAILY_REQUESTS", "24")),
            int(os.environ.get("DEX_LOOKUP_DAILY_REQUESTS", "100")),
            int(os.environ.get("PROFILE_MAX_POOL_SCANS", "3")), args.once))
    except Exception as exc:
        parser.exit(1, f"Profile discovery stopped: {type(exc).__name__}; check configuration and services.\n")


if __name__ == "__main__":
    main()
