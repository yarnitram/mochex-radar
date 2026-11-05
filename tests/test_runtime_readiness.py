import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from mochex_radar.api import app
from mochex_radar.initialize import SCHEMA_VERSION, initialize
from mochex_radar.readiness import database_ready


def test_api_token_covers_data_and_docs_without_exposing_secret(monkeypatch):
    monkeypatch.setenv("RADAR_API_TOKEN", "private-test-token")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        for path in ("/api/v1/markets/core", "/openapi.json", "/docs"):
            response = client.get(path)
            assert response.status_code == 401 and "private-test-token" not in response.text
        assert client.get("/api/v1/live/core", headers={"Authorization": "Bearer private-test-token"}).status_code == 200
        assert client.get("/api/v1/live/core", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_cache_failure_is_degraded_when_durable_database_is_ready(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("mochex_radar.api.database_ready", lambda dsn: True)
    class Down:
        client = None
        async def ping(self): raise RedisError("private-password")
        async def close(self): pass
    with TestClient(app) as client:
        down = Down(); down.client = down
        app.state.live_store = down
        response = client.get("/health/ready")
        assert response.status_code == 200 and response.json()["status"] == "degraded"
        assert "private-password" not in response.text


def test_database_readiness_sanitizes_connection_failure(monkeypatch):
    def failed(*args, **kwargs): raise psycopg.OperationalError("private-password")
    monkeypatch.setattr("mochex_radar.readiness.psycopg.connect", failed)
    assert database_ready("private-dsn") is False and database_ready(None) is False


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_bootstrap_is_idempotent_and_ready_without_provider_calls():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize(dsn)
    initialize(dsn)
    assert database_ready(dsn)
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM schema_versions WHERE version=%s", (SCHEMA_VERSION,)).fetchone()[0] == 1
