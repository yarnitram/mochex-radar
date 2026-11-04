from fastapi.testclient import TestClient

from mochex_radar.api import app


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
