import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from cluster_radar.providers.dexscreener import BudgetExceeded, DexScreener, ProviderUnavailable

MINT = "So11111111111111111111111111111111111111112"
FIXTURE = (Path(__file__).parent / "fixtures/dexscreener-pools.json").read_text()


def test_pool_contract_and_request_budget():
    async def run():
        def handler(request):
            assert request.url.path == f"/token-pairs/v1/solana/{MINT}"
            return httpx.Response(200, text=FIXTURE)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DexScreener(client, max_requests=1)
            pools = await provider.pools(MINT)
            assert pools[0].market_cap_usd is None
            assert pools[0].fdv_usd == Decimal(54321)
            assert pools[0].dex_liquidity_usd == Decimal("12345.67")
            assert pools[0].token_created_at is None
            assert pools[0].pool_created_at == datetime(2024, 1, 1, tzinfo=UTC)
            with pytest.raises(BudgetExceeded):
                await provider.pools(MINT)

    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_provider_errors_fail_closed(status):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(status)
        )) as client:
            with pytest.raises(ProviderUnavailable):
                await DexScreener(client).pools(MINT)

    asyncio.run(run())


@pytest.mark.parametrize("body", ["{}", "not-json", '[{"chainId": "solana"}]',
                                      FIXTURE.replace("12345.67", "-1")])
def test_invalid_payload_is_unavailable(body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=body)
        )) as client:
            with pytest.raises(ProviderUnavailable):
                await DexScreener(client).pools(MINT)

    asyncio.run(run())


def test_quote_side_values_are_not_assigned_to_requested_mint():
    async def run():
        raw = json.loads(FIXTURE)
        raw[0]["baseToken"]["address"] = "other-mint"
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=raw)
        )) as client:
            assert await DexScreener(client).pools(MINT) == []

    asyncio.run(run())
