import asyncio

import httpx
import psycopg
import pytest

from cluster_radar.providers.dexscreener import BudgetExceeded, DexScreener, ProviderUnavailable
from mochex_radar.provider_budget import PersistentDexScreener

MINT = "So11111111111111111111111111111111111111112"


@pytest.mark.parametrize("failure", [BudgetExceeded("daily limit"), psycopg.OperationalError("offline")])
def test_reservation_failure_never_calls_provider(monkeypatch, failure):
    import mochex_radar.provider_budget as module

    def reserve(*args):
        raise failure

    monkeypatch.setattr(module, "reserve_request", reserve)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: pytest.fail("provider should not be called")
        )) as client:
            provider = PersistentDexScreener(DexScreener(client), "unused", 10)
            with pytest.raises(ProviderUnavailable):
                await provider.pools(MINT)

    asyncio.run(run())


def test_failure_after_reservation_keeps_budget_and_invalid_input_does_not_reserve(monkeypatch):
    import mochex_radar.provider_budget as module
    reservations = []

    def reserve(*args):
        reservations.append(True)
        return 0.0

    monkeypatch.setattr(module, "reserve_request", reserve)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(429)
        )) as client:
            provider = PersistentDexScreener(DexScreener(client), "unused", 10)
            with pytest.raises(ValueError):
                await provider.pools("invalid")
            assert reservations == []
            with pytest.raises(ProviderUnavailable):
                await provider.pools(MINT)
            assert len(reservations) == 1

    asyncio.run(run())
