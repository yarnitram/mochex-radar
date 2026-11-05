"""Scheduled public pool discovery for an explicitly curated Solana watchlist."""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cluster_radar.providers.dexscreener import BudgetExceeded, DexScreener, ProviderUnavailable
from mochex_radar.dex_store import initialize_dex_store, store_observations
from mochex_radar.provider_budget import PersistentDexScreener, initialize_budget_store

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS dex_scans (
    id uuid PRIMARY KEY,
    mint text NOT NULL,
    categories text[] NOT NULL,
    category_source text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN
        ('success', 'empty', 'provider_error', 'budget_exhausted', 'skipped_budget')),
    pool_count integer NOT NULL CHECK (pool_count >= 0),
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (finished_at >= started_at)
);
CREATE INDEX IF NOT EXISTS dex_scans_recent_idx ON dex_scans (finished_at DESC, id);
"""


class WatchToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mint: str = Field(pattern=r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    categories: list[Literal["meme", "ai", "unclassified"]] = Field(min_length=1, max_length=3)
    category_source: str = Field(min_length=1, max_length=200)


class Watchlist(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    tokens: list[WatchToken] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_mints(self):
        if len({token.mint for token in self.tokens}) != len(self.tokens):
            raise ValueError("duplicate mint in watchlist")
        return self


def initialize_scan_store(dsn: str) -> None:
    initialize_dex_store(dsn)
    initialize_budget_store(dsn)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA)


def store_scan(dsn: str, token: WatchToken, scan_id, started, finished, status, pools, *, connection=None) -> None:
    if connection is None:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            return store_scan(dsn, token, scan_id, started, finished, status, pools, connection=conn)
    store_observations(dsn, pools, connection=connection)
    connection.execute(
        """INSERT INTO dex_scans
        (id, mint, categories, category_source, started_at, finished_at, status, pool_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (scan_id, token.mint, token.categories, token.category_source,
         started, finished, status, len(pools)),
    )


def recent_scans(dsn: str, limit: int = 100) -> list[dict]:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")
    with psycopg.connect(dsn, connect_timeout=5, row_factory=psycopg.rows.dict_row) as conn:
        return conn.execute(
            """SELECT id, mint, categories, category_source, started_at, finished_at, status, pool_count
            FROM dex_scans ORDER BY finished_at DESC, id LIMIT %s""", (limit,),
        ).fetchall()


async def scan_once(tokens: list[WatchToken], provider, persist) -> list[str]:
    statuses = []
    exhausted = False
    for token in tokens:
        started = datetime.now(timezone.utc)
        pools = []
        if exhausted:
            status = "skipped_budget"
        else:
            try:
                pools = await provider.pools(token.mint)
                status = "success" if pools else "empty"
            except BudgetExceeded:
                status, exhausted = "budget_exhausted", True
            except ProviderUnavailable:
                status = "provider_error"
        await persist(token, uuid4(), started, datetime.now(timezone.utc), status, pools)
        statuses.append(status)
    return statuses


async def run(dsn: str, tokens: list[WatchToken], interval: int, daily_limit: int, once=False):
    if not tokens or interval < 60 or daily_limit < 1:
        raise ValueError("nonempty watchlist, interval >=60 and positive daily limit required")
    await asyncio.to_thread(initialize_scan_store, dsn)
    async with httpx.AsyncClient() as client:
        # Durable daily budget controls unattended operation; no lifetime ceiling resets needed.
        provider = PersistentDexScreener(DexScreener(client, max_requests=2**63-1), dsn, daily_limit)

        async def persist(*args):
            await asyncio.to_thread(store_scan, dsn, *args)

        while True:
            statuses = await scan_once(tokens, provider, persist)
            log.info("DEX cycle completed targets=%d outcomes=%s", len(tokens), ",".join(statuses))
            if once:
                return
            await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Scan configured Solana mints for public DEX pools")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--watchlist", default=os.environ.get("DEX_WATCHLIST_PATH", "config/dex-watchlist.json"))
    args = parser.parse_args()
    try:
        watchlist = Watchlist.model_validate(json.loads(Path(args.watchlist).read_text(encoding="utf-8")))
        dsn = os.environ.get("DATABASE_URL")
        if not dsn or not watchlist.tokens:
            raise ValueError("DATABASE_URL and nonempty watchlist required")
        interval = int(os.environ.get("DEX_SCAN_INTERVAL_SECONDS", "900"))
        daily_limit = int(os.environ.get("DEX_LOOKUP_DAILY_REQUESTS", "100"))
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run(dsn, watchlist.tokens, interval, daily_limit, args.once))
    except Exception as exc:
        # Avoid printing configuration, DSNs, or raw provider bodies.
        parser.exit(1, f"DEX worker stopped: {type(exc).__name__}; check configuration and services.\n")


if __name__ == "__main__":
    main()
