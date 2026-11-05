from datetime import datetime, timezone

import pytest

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.profiles import ProfileBatch
from mochex_radar.profile_discovery import discover_once
from mochex_radar.dex_worker import WatchToken


@pytest.mark.asyncio
async def test_profile_window_is_saved_before_bounded_pool_scanning():
    events = []

    async def fetch():
        return ProfileBatch(("A" * 32, "B" * 32), datetime.now(timezone.utc), "fixture-hash", 2)

    async def save_poll(*args):
        events.append("persist_window")
        assert len(args[-1].mints) == 2

    async def choose(identity):
        assert events == ["persist_window"]
        return [WatchToken(mint="A" * 32, categories=["unclassified"], category_source="fixture")]

    class Provider:
        async def pools(self, mint):
            events.append("pool_lookup")
            return []

    async def save_scan(*args):
        assert args[0].categories == ["unclassified"]
        events.append("save_scan")

    assert await discover_once(fetch, save_poll, choose, Provider(), save_scan) == ("success", ["empty"])
    assert events == ["persist_window", "pool_lookup", "save_scan"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "expected"), [(BudgetExceeded(), "budget_exhausted"), (ProviderUnavailable(), "provider_error")])
async def test_failed_feed_is_audited_and_never_promoted(failure, expected):
    async def fetch():
        raise failure

    async def save(*args):
        assert args[-2] == expected
        assert args[-1] is None

    async def forbidden(*args):
        pytest.fail("failed feed cannot scan")

    assert await discover_once(fetch, save, forbidden, None, forbidden) == (expected, [])


@pytest.mark.asyncio
async def test_persistence_failure_prevents_scanning():
    async def fetch():
        return ProfileBatch(("A" * 32,), datetime.now(timezone.utc), "fixture-hash", 1)

    async def fail(*args):
        raise RuntimeError("database unavailable")

    async def forbidden(*args):
        pytest.fail("unpersisted feed cannot scan")

    with pytest.raises(RuntimeError):
        await discover_once(fetch, fail, forbidden, None, forbidden)


def test_profile_history_disabled_is_explicit_and_read_only(monkeypatch):
    from fastapi.testclient import TestClient
    from mochex_radar.api import app
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/discovery/profiles/polls").json() == {"status":"storage_disabled", "polls":[]}
        assert client.get("/api/v1/discovery/profiles/mints").json() == {"status":"storage_disabled", "mints":[]}
        assert client.post("/api/v1/discovery/profiles/polls").status_code == 405
