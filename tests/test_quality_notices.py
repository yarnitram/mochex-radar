from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from mochex_radar.quality_notices import collection_notice, report_cycle_quality
from mochex_radar.storage import CycleResult


def cycle(failures=1, stored=14):
    now = datetime.now(timezone.utc)
    return CycleResult(now - timedelta(seconds=5), now, stored, failures)


def test_healthy_duplicate_cycle_does_not_generate_warning():
    assert collection_notice(cycle(failures=0, stored=0)) is None


def test_failed_cycle_keeps_evidence_and_expires():
    result = cycle()
    notice = collection_notice(result)
    assert notice.kind == "DATA_QUALITY"
    assert notice.known_at == result.finished_at
    assert notice.expires_at == result.finished_at + timedelta(hours=1)
    assert "1 of 15" in notice.render()
    assert "Security: UNKNOWN" in notice.render()


@pytest.mark.asyncio
async def test_optional_queue_failure_is_sanitized_and_does_not_fail_collection(monkeypatch, caplog):
    import mochex_radar.quality_notices as module

    def fail(*args):
        raise psycopg.OperationalError("synthetic-sensitive-dsn")

    monkeypatch.setattr(module, "enqueue", fail)
    assert await report_cycle_quality("unused", cycle()) == "queue_unavailable"
    assert "synthetic-sensitive-dsn" not in caplog.text


@pytest.mark.asyncio
async def test_notice_cooldown_is_not_reported_as_delivery(monkeypatch):
    import mochex_radar.quality_notices as module
    monkeypatch.setattr(module, "enqueue", lambda *args: None)
    assert await report_cycle_quality("unused", cycle()) == "cooldown"


@pytest.mark.asyncio
async def test_collector_does_not_queue_when_disabled_and_does_queue_when_enabled(monkeypatch):
    import mochex_radar.collector as module
    records = []
    monkeypatch.setattr(module, "initialize_database", lambda _: None)
    monkeypatch.setattr(module, "initialize_alert_store", lambda _: None)

    async def collect(*args):
        return cycle()

    async def report(*args):
        records.append(True)
        return "queued_or_existing"

    monkeypatch.setattr(module, "collect_once", collect)
    monkeypatch.setattr(module, "report_cycle_quality", report)
    monkeypatch.delenv("ALERT_DATA_QUALITY_ENABLED", raising=False)
    await module.run("unused", 60, once=True)
    assert records == []
    monkeypatch.setenv("ALERT_DATA_QUALITY_ENABLED", "true")
    await module.run("unused", 60, once=True)
    assert records == [True]
