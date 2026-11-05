from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from cluster_radar.providers.dexscreener import DexScreener
from mochex_radar.api import app, get_dex_provider

MINT = "So11111111111111111111111111111111111111112"
ROUTE = f"/api/v1/dex/solana/{MINT}/pools"
FIXTURE = (Path(__file__).parent / "cluster/fixtures/dexscreener-pools.json").read_text()


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DEX_LOOKUP_ENABLED", raising=False)
    with TestClient(app) as client:
        assert client.get(ROUTE).status_code == 503


def test_pool_lookup_and_budget():
    with TestClient(app) as client:
        provider = DexScreener(httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=FIXTURE)
        )), max_requests=1)
        app.dependency_overrides[get_dex_provider] = lambda: provider
        try:
            response = client.get(ROUTE)
            assert response.status_code == 200
            payload = response.json()
            assert payload["security_status"] == "UNKNOWN"
            assert payload["approved_pump_watch"] is False
            assert payload["pools"][0]["dex_liquidity_usd"] == "12345.67"
            assert client.get(ROUTE).status_code == 429
        finally:
            app.dependency_overrides.clear()


def test_invalid_mint_and_provider_failure():
    with TestClient(app) as client:
        provider = DexScreener(httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(429)
        )))
        app.dependency_overrides[get_dex_provider] = lambda: provider
        try:
            assert client.get("/api/v1/dex/solana/invalid/pools").status_code == 422
            assert provider.requests == 0
            assert client.get(ROUTE).status_code == 503
        finally:
            app.dependency_overrides.clear()


def test_history_disabled_and_invalid_cutoff(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        route = f"/api/v1/dex/solana/{MINT}/history"
        assert client.get(route, params={"as_of": "2026-01-01T00:00:00Z"}).status_code == 503
        monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
        assert client.get(route, params={"as_of": "2026-01-01T00:00:00"}).status_code == 422
        assert client.get(route, params={"as_of": "2026-01-01T00:00:00Z", "limit": 1001}).status_code == 422
