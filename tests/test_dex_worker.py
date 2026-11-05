import asyncio

import pytest
from pydantic import ValidationError

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from mochex_radar.dex_worker import Watchlist, WatchToken, scan_once


def token(char="A"):
    return WatchToken(mint=char * 32, categories=["ai"], category_source="operator:test")


def test_watchlist_rejects_duplicates_unknown_category_and_invalid_mint():
    with pytest.raises(ValidationError):
        Watchlist(version=1, tokens=[token(), token()])
    with pytest.raises(ValidationError):
        WatchToken(mint="invalid", categories=["ai"], category_source="fixture")
    with pytest.raises(ValidationError):
        WatchToken(mint="A" * 32, categories=["guaranteed-profit"], category_source="fixture")


def test_scan_audits_empty_failure_and_budget_without_fabricated_pools():
    class Provider:
        calls = 0

        async def pools(self, mint):
            self.calls += 1
            if self.calls == 1:
                return []
            if self.calls == 2:
                raise ProviderUnavailable()
            raise BudgetExceeded()

    async def run():
        persisted = []

        async def persist(*args):
            persisted.append(args)

        provider = Provider()
        statuses = await scan_once([token(char) for char in "ABCD"], provider, persist)
        assert statuses == ["empty", "provider_error", "budget_exhausted", "skipped_budget"]
        assert provider.calls == 3
        assert len(persisted) == 4
        assert all(row[-1] == [] for row in persisted)
        assert all(row[0].category_source == "operator:test" for row in persisted)

    asyncio.run(run())
