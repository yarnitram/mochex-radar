import asyncio
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.solana_authorities import SolanaAuthorities
from mochex_radar.api import app, get_authority_provider
from mochex_radar.authority_checks import PersistentAuthorities

MINT = "So11111111111111111111111111111111111111112"
ROUTE = f"/api/v1/security/solana/{MINT}/authorities"
FIXTURE = (Path(__file__).parent / "cluster/fixtures/solana-mint-authorities.json").read_text()


def test_disabled_and_missing_database_fail_closed(monkeypatch):
    monkeypatch.delenv("SOLANA_AUTHORITIES_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.get(ROUTE).status_code == 503
        assert client.get(ROUTE+"/history", params={"as_of":"2026-01-01T00:00:00Z"}).status_code == 503
        assert client.post(ROUTE).status_code == 405
    monkeypatch.setenv("SOLANA_AUTHORITIES_ENABLED", "true")
    with pytest.raises(ValueError, match="DATABASE_URL"), TestClient(app):
        pass


def test_api_persists_partial_evidence_and_never_approves_security(monkeypatch):
    import mochex_radar.api as api
    import mochex_radar.authority_checks as budget
    saved = []
    monkeypatch.setattr(budget, "reserve_request", lambda *args, **kwargs: 0)
    monkeypatch.setattr(api, "store_authority", lambda dsn, evidence: saved.append(evidence))
    with TestClient(app) as client:
        provider = PersistentAuthorities(SolanaAuthorities(httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200,text=FIXTURE)))), "unused", 100)
        app.dependency_overrides[get_authority_provider] = lambda: provider
        try:
            response = client.get(ROUTE)
            assert response.status_code == 200
            data = response.json()
            assert data["persisted"] is True and data["partial"] is True
            assert data["evidence"]["security_status"] == "UNKNOWN"
            assert data["evidence"]["approved_pump_watch"] is False
            assert len(saved) == 1
            assert client.get(ROUTE.replace(MINT,"z"*44)).status_code == 422
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize("failure", [BudgetExceeded(), psycopg.OperationalError("synthetic-sensitive-dsn")])
def test_budget_failure_prevents_rpc_transport(monkeypatch, failure):
    import mochex_radar.authority_checks as module

    def reserve(*args, **kwargs):
        raise failure

    monkeypatch.setattr(module, "reserve_request", reserve)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("no RPC"))) as client:
            with pytest.raises(ProviderUnavailable):
                await PersistentAuthorities(SolanaAuthorities(client), "unused", 100).check(MINT)

    asyncio.run(run())


def test_storage_failure_is_not_reported_as_successful_evidence(monkeypatch):
    import mochex_radar.api as api
    import mochex_radar.authority_checks as budget
    monkeypatch.setattr(budget, "reserve_request", lambda *args, **kwargs: 0)

    def fail(*args):
        raise psycopg.OperationalError("synthetic-sensitive-dsn")

    monkeypatch.setattr(api, "store_authority", fail)
    with TestClient(app) as client:
        provider = PersistentAuthorities(SolanaAuthorities(httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200,text=FIXTURE)))), "unused", 100)
        app.dependency_overrides[get_authority_provider] = lambda: provider
        try:
            response=client.get(ROUTE)
            assert response.status_code == 503
            assert "synthetic-sensitive-dsn" not in response.text
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize(("failure","status"),[(BudgetExceeded(),429),(ProviderUnavailable(),503)])
def test_api_budget_and_rpc_failures_are_explicit(failure,status):
    class FailedProvider:
        async def check(self,mint):
            raise failure

    app.dependency_overrides[get_authority_provider] = lambda: FailedProvider()
    try:
        with TestClient(app) as client:
            assert client.get(ROUTE).status_code == status
    finally:
        app.dependency_overrides.clear()


def test_snapshot_without_storage_is_disabled_and_never_uses_rpc(monkeypatch):
    import mochex_radar.api as api
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(api, "get_authority_provider", lambda *args: pytest.fail("no RPC"))
    with TestClient(app) as client:
        assert client.get("/api/v1/security/authorities/snapshot").json()=={"status":"storage_disabled","observations":[]}
        assert client.post("/api/v1/security/authorities/snapshot").status_code==405


def test_snapshot_query_errors_are_explicit(monkeypatch):
    import mochex_radar.api as api
    monkeypatch.setenv("DATABASE_URL","unused")
    with TestClient(app) as client:
        assert client.get("/api/v1/security/authorities/snapshot?limit=101").status_code==422
        def fail(*args):
            raise psycopg.OperationalError("synthetic-private-dsn")
        monkeypatch.setattr(api,"authority_snapshot",fail)
        response=client.get("/api/v1/security/authorities/snapshot")
        assert response.status_code==503 and "synthetic-private-dsn" not in response.text
