"""Bounded public Solana pool lookup; provider data never implies security approval."""

import asyncio
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from cluster_radar.discovery.identity import Candidate, MarketStage


class ProviderUnavailable(Exception):
    """Lookup failed; callers must retain unknown risk status."""


class BudgetExceeded(ProviderUnavailable):
    """The configured request ceiling has been reached."""


class Token(BaseModel):
    address: StrictStr


class Liquidity(BaseModel):
    usd: Decimal | None = None


class Pair(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chainId: StrictStr
    pairAddress: StrictStr = Field(min_length=1)
    baseToken: Token
    marketCap: Decimal | None = None
    fdv: Decimal | None = None
    liquidity: Liquidity | None = None
    pairCreatedAt: StrictInt | None = None


class DexScreener:
    """One shared instance per worker; no automatic retries or paid endpoints.

    Default ceiling is 100 attempted requests per instance. Pacing stays below the
    documented 300/minute pool limit; aggregate limits across workers are separate.
    """

    def __init__(self, client: httpx.AsyncClient, *, max_requests: int = 100):
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        self.client = client
        self.max_requests = max_requests
        self.requests = 0
        self._lock = asyncio.Lock()
        self._next_request = 0.0

    async def pools(self, mint: str) -> list[Candidate]:
        if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", mint):
            raise ValueError("invalid Solana mint encoding")
        async with self._lock:
            if self.requests >= self.max_requests:
                raise BudgetExceeded("request budget exhausted")
            await asyncio.sleep(max(0, self._next_request - monotonic()))
            self.requests += 1
            self._next_request = monotonic() + 0.25
            try:
                response = await self.client.get(
                    f"https://api.dexscreener.com/token-pairs/v1/solana/{mint}",
                    timeout=10,
                )
                response.raise_for_status()
                raw = json.loads(response.text, parse_float=Decimal)
                if not isinstance(raw, list):
                    raise TypeError("expected pool list")
                known_at = datetime.now(UTC)
                candidates = []
                identities = set()
                for item in raw:
                    pair = Pair.model_validate(item)
                    # Valuations refer to the base token, never infer quote-token values.
                    if pair.chainId != "solana" or pair.baseToken.address != mint:
                        continue
                    created = None
                    if pair.pairCreatedAt is not None:
                        if pair.pairCreatedAt < 0:
                            raise ValueError("invalid creation time")
                        created = datetime.fromtimestamp(pair.pairCreatedAt / 1000, UTC)
                    candidate = Candidate(
                        mint=mint, stage=MarketStage.DEX, pool_id=pair.pairAddress,
                        token_created_at=None, pool_created_at=created,
                        market_cap_usd=pair.marketCap, fdv_usd=pair.fdv,
                        dex_liquidity_usd=pair.liquidity.usd if pair.liquidity else None,
                        source="dexscreener:token-pairs-v1", known_at=known_at,
                    )
                    if candidate.identity in identities:
                        raise ValueError("duplicate pool identity")
                    identities.add(candidate.identity)
                    candidates.append(candidate)
                return candidates
            except (httpx.HTTPError, ValueError, TypeError, OverflowError, OSError) as exc:
                raise ProviderUnavailable("DEX Screener pool lookup unavailable") from exc
