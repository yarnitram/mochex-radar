import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.profiles import ProfileFeed

FIXTURE = (Path(__file__).parent / "fixtures/dexscreener-profiles.json").read_bytes()


def test_profile_contract_deduplicates_sol_only_and_budgets():
    async def run():
        def handle(request):
            assert request.url.path == "/token-profiles/latest/v1"
            return httpx.Response(200, content=FIXTURE)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            feed = ProfileFeed(client, max_requests=1)
            batch = await feed.latest()
            assert len(batch.mints) == 1
            assert batch.input_count == 3
            assert batch.response_hash == hashlib.sha256(FIXTURE).hexdigest()
            assert batch.known_at.utcoffset().total_seconds() == 0
            with pytest.raises(BudgetExceeded):
                await feed.latest()

    asyncio.run(run())


@pytest.mark.parametrize(("status", "body"), [(429, "[]"), (403, "[]"), (500, "[]"), (200, "{}"),
    (200, "bad-json"), (200, '[{"chainId":"solana","tokenAddress":"invalid"}]'),
    (200, '[{"chainId":"solana"}]')])
def test_bad_profiles_never_become_empty_success(status, body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, text=body))) as client:
            with pytest.raises(ProviderUnavailable):
                await ProfileFeed(client).latest()

    asyncio.run(run())
