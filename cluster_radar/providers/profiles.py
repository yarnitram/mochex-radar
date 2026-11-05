"""Public profile-window observations, not a token-creation or security feed."""

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

import httpx
from pydantic import BaseModel, StrictStr

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable

SOURCE = "dexscreener:token-profiles-latest-v1"


class Profile(BaseModel):
    chainId: StrictStr
    tokenAddress: StrictStr


@dataclass(frozen=True)
class ProfileBatch:
    mints: tuple[str, ...]
    known_at: datetime
    response_hash: str
    input_count: int
    source: str = SOURCE


class ProfileFeed:
    def __init__(self, client: httpx.AsyncClient, *, max_requests: int = 24):
        if max_requests < 1:
            raise ValueError("positive request limit required")
        self.client = client
        self.max_requests = max_requests
        self.requests = 0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def latest(self) -> ProfileBatch:
        async with self._lock:
            if self.requests >= self.max_requests:
                raise BudgetExceeded("profile request budget exhausted")
            await asyncio.sleep(max(0, self._next_at - monotonic()))
            self.requests += 1
            self._next_at = monotonic() + 1.1
            try:
                response = await self.client.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
                response.raise_for_status()
                if len(response.content) > 1_000_000:
                    raise ValueError("profile response too large")
                data = response.json()
                if not isinstance(data, list):
                    raise TypeError("expected profile array")
                if len(data) > 1000:
                    raise ValueError("too many profile records")
                mints = []
                for item in data:
                    profile = Profile.model_validate(item)
                    if profile.chainId != "solana":
                        continue
                    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", profile.tokenAddress):
                        raise ValueError("invalid Solana mint encoding")
                    if profile.tokenAddress not in mints:
                        mints.append(profile.tokenAddress)
                return ProfileBatch(tuple(mints), datetime.now(UTC),
                                    hashlib.sha256(response.content).hexdigest(), len(data))
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise ProviderUnavailable("profile feed unavailable") from exc
