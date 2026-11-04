import httpx
from fastapi.testclient import TestClient

from mochex_radar.api import app, get_http_client


client = TestClient(app)


def test_health_and_configured_universe() -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    response = client.get("/api/v1/markets/core")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"] == "configuration_only"
    assert len(payload["markets"]) == 7


def test_no_mutating_market_route() -> None:
    assert client.post("/api/v1/markets/core", json={}).status_code == 405
    assert client.post("/api/v1/orders", json={}).status_code == 404


def test_market_data_route_uses_public_feed_and_whitelist() -> None:
    from datetime import datetime, timezone
    current = int(datetime.now(timezone.utc).timestamp() // 900 * 900)
    data = {"time": [current - 900, current], "open": [100, 100], "high": [110, 110], "low": [90, 90], "close": [105, 105], "vol": [12, 12]}

    async def fake_client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"success": True, "code": 0, "data": data}))) as provider:
            yield provider

    app.dependency_overrides[get_http_client] = fake_client
    try:
        response = client.get("/api/v1/market-data/SOL_USDT/15m")
        assert response.status_code == 200
        assert response.json()["candle"]["asset_id"] == "cex:mexc-usdt-futures:SOL_USDT"
        assert client.get("/api/v1/market-data/UNKNOWN/15m").status_code == 404
        assert client.get("/api/v1/market-data/SOL_USDT/2h").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_market_data_provider_failure_does_not_fabricate_data() -> None:
    async def fake_client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as provider:
            yield provider

    app.dependency_overrides[get_http_client] = fake_client
    try:
        response = client.get("/api/v1/market-data/SOL_USDT/15m")
        assert response.status_code == 503
        assert response.json() == {"detail": "market data unavailable"}
    finally:
        app.dependency_overrides.clear()
