import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mochex_radar.alerts import ResearchNotice
from mochex_radar.telegram import send_message

FIXTURES = Path(__file__).parent / "fixtures/telegram"
TOKEN = "123456:fixture-secret"
CHAT = "-100123456789"


@pytest.mark.parametrize(("fixture", "status", "outcome", "delay"), [
    ("sent", 200, "sent", 0), ("rate-limit", 429, "retry", 120), ("forbidden", 403, "failed", 0),
])
def test_telegram_contract_and_secret_redaction(fixture, status, outcome, delay, caplog):
    caplog.set_level(logging.INFO)

    def handler(request):
        assert request.url.host == "api.telegram.org"
        body = json.loads(request.content)
        assert body["chat_id"] == CHAT
        assert body["allow_paid_broadcast"] is False
        assert body["link_preview_options"]["is_disabled"] is True
        assert "parse_mode" not in body
        return httpx.Response(status, text=(FIXTURES / f"{fixture}.json").read_text())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await send_message(client, TOKEN, CHAT, "Research test")
            assert (result.outcome, result.retry_after) == (outcome, delay)

    asyncio.run(run())
    assert TOKEN not in caplog.text
    assert CHAT not in caplog.text
    assert "fixture-secret" not in caplog.text


@pytest.mark.parametrize(("error", "outcome"), [(httpx.ConnectTimeout, "retry"), (httpx.ReadTimeout, "uncertain"), (httpx.WriteTimeout, "uncertain")])
def test_transport_ambiguity(error, outcome):
    def handler(request):
        raise error("synthetic transport failure", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await send_message(client, TOKEN, CHAT, "test")).outcome == outcome

    asyncio.run(run())


@pytest.mark.parametrize(("status", "body"), [(500, '{}'), (200, '{"ok":true}'), (200, 'not-json'),
    (429, '{"parameters":{"retry_after":999999999999999999999}}')])
def test_unconfirmed_delivery_is_not_automatically_retried(status, body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, text=body))) as client:
            assert (await send_message(client, TOKEN, CHAT, "test")).outcome == "uncertain"

    asyncio.run(run())


def test_notice_guardrails_and_plain_text_rendering():
    now = datetime.now(timezone.utc)
    fields = dict(asset_id="system:test", kind="SYSTEM_TEST", rule_version="test-v1", known_at=now,
                  expires_at=now + timedelta(hours=1), summary="<b>plain text</b>", evidence=["fixture"])
    notice = ResearchNotice(**fields)
    assert "Security: UNKNOWN" in notice.render()
    assert "<b>plain text</b>" in notice.render()
    with pytest.raises(ValidationError):
        ResearchNotice(**{**fields, "kind": "PUMP_WATCH"})
    with pytest.raises(ValidationError):
        ResearchNotice(**{**fields, "expires_at": now + timedelta(days=2)})
    with pytest.raises(ValidationError):
        ResearchNotice(**{**fields, "known_at": now.replace(tzinfo=None)})


def test_dry_run_never_dispatches(monkeypatch, capsys):
    from mochex_radar import alert_worker
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setattr("sys.argv", ["alert_worker", "--dry-run"])
    monkeypatch.setattr(alert_worker, "initialize_alert_store", lambda _: None)
    monkeypatch.setattr(alert_worker, "preview_pending", lambda _: [])
    monkeypatch.setattr(alert_worker, "run_sender", lambda *args: pytest.fail("must not send"))
    alert_worker.main()
    assert json.loads(capsys.readouterr().out)["mode"] == "dry_run"


def test_live_worker_requires_explicit_opt_in_before_database_access(monkeypatch):
    from mochex_radar import alert_worker
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.delenv("TELEGRAM_SEND_ENABLED", raising=False)
    monkeypatch.setattr("sys.argv", ["alert_worker", "--send"])
    monkeypatch.setattr(alert_worker, "initialize_alert_store", lambda _: pytest.fail("must fail before DB"))
    with pytest.raises(SystemExit):
        alert_worker.main()


def test_alert_status_exposes_no_content_and_has_no_send_route(monkeypatch):
    from fastapi.testclient import TestClient
    from mochex_radar.api import app
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/alerts/status").json() == {"status": "storage_disabled", "states": {}}
        assert client.post("/api/v1/alerts/status").status_code == 405
        assert client.post("/api/v1/alerts/send").status_code == 404
