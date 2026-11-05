"""Durable UTC-day request budgets and aggregate pacing for public DEX lookups."""

import asyncio
import re
from datetime import timezone

import psycopg

from cluster_radar.providers.dexscreener import BudgetExceeded, DexScreener, ProviderUnavailable

PROVIDER = "dexscreener:token-pairs-v1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_request_budgets (
    provider text PRIMARY KEY,
    budget_day date NOT NULL DEFAULT DATE '1970-01-01',
    used integer NOT NULL DEFAULT 0 CHECK (used >= 0),
    next_request_at timestamptz NOT NULL DEFAULT TIMESTAMPTZ '1970-01-01 00:00:00+00'
);
"""


def initialize_budget_store(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA)


def reserve_request(dsn: str, daily_limit: int, *, provider: str = PROVIDER, spacing_seconds: float = 0.25) -> float:
    """Return zero when reserved, or delay before retry; exhaustion raises.

    Lock one provider row to serialize processes. Failed or cancelled requests
    retain the reservation. Database clock defines UTC day and spacing.
    """
    if daily_limit < 1 or not 0.25 <= spacing_seconds <= 3600:
        raise ValueError("positive daily limit and spacing 0.25..3600 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("INSERT INTO provider_request_budgets (provider) VALUES (%s) ON CONFLICT DO NOTHING",
                     (provider,))
        day, used, next_at = conn.execute(
            "SELECT budget_day, used, next_request_at FROM provider_request_budgets WHERE provider=%s FOR UPDATE",
            (provider,),
        ).fetchone()
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        today = now.astimezone(timezone.utc).date()
        if day != today:
            used = 0
        if used >= daily_limit:
            raise BudgetExceeded("daily provider request budget exhausted")
        delay = (next_at - now).total_seconds()
        if delay > 0:
            return delay
        conn.execute(
            """UPDATE provider_request_budgets SET budget_day=%s, used=%s,
            next_request_at=%s::timestamptz + %s * interval '1 second' WHERE provider=%s""",
            (today, used + 1, now, spacing_seconds, provider),
        )
    return 0.0


class PersistentDexScreener:
    """Platform wrapper; keeps the separately preserved adapter unchanged."""

    def __init__(self, inner: DexScreener, dsn: str, daily_limit: int):
        if daily_limit < 1:
            raise ValueError("daily_limit must be positive")
        self.inner = inner
        self.dsn = dsn
        self.daily_limit = daily_limit
        self._lock = asyncio.Lock()

    async def pools(self, mint: str):
        if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", mint):
            raise ValueError("invalid Solana mint encoding")
        async with self._lock:
            # Avoid charging a durable reservation when the inner ceiling is already exhausted.
            if self.inner.requests >= self.inner.max_requests:
                raise BudgetExceeded("process request budget exhausted")
            try:
                while delay := await asyncio.to_thread(reserve_request, self.dsn, self.daily_limit):
                    await asyncio.sleep(delay)
            except psycopg.Error as exc:
                raise ProviderUnavailable("provider request budget unavailable") from exc
            return await self.inner.pools(mint)
