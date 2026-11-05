import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from mochex_radar.alert_store import claim_notice, enqueue, finish_notice, initialize_alert_store, preview_pending
from mochex_radar.alerts import ResearchNotice
from mochex_radar.telegram import DeliveryResult


@pytest.fixture
def queue():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("requires temporary PostgreSQL")
    initialize_alert_store(dsn)
    asset = f"system:fixture:{uuid4()}"

    def reset_gate():
        with psycopg.connect(dsn) as conn:
            conn.execute("""UPDATE alert_delivery_gate SET used=0,budget_day=DATE '1970-01-01',
                next_at=TIMESTAMPTZ '1970-01-01 00:00:00+00' WHERE destination='primary'""")

    def notice(**overrides):
        now = datetime.now(timezone.utc) - timedelta(seconds=1)
        fields = dict(asset_id=asset, kind="SYSTEM_TEST", rule_version="fixture-v1", known_at=now,
                      expires_at=now + timedelta(hours=1), summary="Fixture", evidence=["offline example"])
        return ResearchNotice(**(fields | overrides))

    reset_gate()
    yield dsn, asset, notice
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM alert_attempts WHERE outbox_id IN (SELECT id FROM alert_outbox WHERE asset_id=%s)", (asset,))
        conn.execute("DELETE FROM alert_outbox WHERE asset_id=%s", (asset,))
        conn.execute("DELETE FROM alert_cooldowns WHERE asset_id=%s", (asset,))
    reset_gate()


def test_dedup_cooldown_and_nonmutating_preview(queue):
    dsn, asset, notice = queue
    item = notice()
    identity = enqueue(dsn, item)
    assert enqueue(dsn, item) == identity
    assert enqueue(dsn, notice(known_at=item.known_at - timedelta(minutes=31))) is None
    with pytest.raises(ValueError, match="future"):
        enqueue(dsn, notice(rule_version="future-test", known_at=datetime.now(timezone.utc) + timedelta(minutes=1)))
    assert any(row["id"] == identity for row in preview_pending(dsn))
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT state,attempts FROM alert_outbox WHERE id=%s", (identity,)).fetchone() == ("pending", 0)


def test_concurrent_claim_and_crash_recovery_are_not_duplicate_sends(queue):
    dsn, asset, notice = queue
    identity = enqueue(dsn, notice())
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(lambda _: claim_notice(dsn), range(4)))
    owned = [claim for claim in claims if claim is not None]
    assert len(owned) == 1
    with psycopg.connect(dsn) as conn:
        conn.execute("UPDATE alert_outbox SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (identity,))
    assert claim_notice(dsn) is None
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT state FROM alert_outbox WHERE id=%s", (identity,)).fetchone()[0] == "uncertain"
    with pytest.raises(ValueError, match="lease"):
        finish_notice(dsn, owned[0], DeliveryResult("sent", "late_confirmation"))


def test_rate_limit_defers_queue_and_daily_budget_survives_reconnection(queue):
    dsn, asset, notice = queue
    identity = enqueue(dsn, notice())
    claimed = claim_notice(dsn, daily_limit=1)
    assert finish_notice(dsn, claimed, DeliveryResult("retry", "provider_rate_limit", 120)) == "pending"
    with psycopg.connect(dsn) as conn:
        next_at, used = conn.execute("SELECT next_at,used FROM alert_delivery_gate WHERE destination='primary'").fetchone()
        assert used == 1
        assert next_at > datetime.now(timezone.utc) + timedelta(seconds=115)
        conn.execute("UPDATE alert_delivery_gate SET next_at=clock_timestamp()-interval '1 second'")
        conn.execute("UPDATE alert_outbox SET next_attempt_at=clock_timestamp() WHERE id=%s", (identity,))
    assert claim_notice(dsn, daily_limit=1) is None


def test_retry_limit_and_expired_notices(queue):
    dsn, asset, notice = queue
    identity = enqueue(dsn, notice())
    for attempt in range(1, 5):
        with psycopg.connect(dsn) as conn:
            conn.execute("UPDATE alert_delivery_gate SET next_at=clock_timestamp()-interval '1 second'")
            conn.execute("UPDATE alert_outbox SET next_attempt_at=clock_timestamp() WHERE id=%s", (identity,))
        claimed = claim_notice(dsn)
        assert claimed.attempt == attempt
        assert finish_notice(dsn, claimed, DeliveryResult("retry", "connection_unavailable", 60)) == ("failed" if attempt == 4 else "pending")
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM alert_attempts WHERE outbox_id=%s", (identity,)).fetchone()[0] == 4


def test_successful_ack_and_expiry(queue):
    dsn, asset, notice = queue
    identity = enqueue(dsn, notice())
    claimed = claim_notice(dsn)
    assert finish_notice(dsn, claimed, DeliveryResult("sent", "provider_confirmed")) == "sent"
    assert claim_notice(dsn) is None
    other = enqueue(dsn, notice(rule_version="fixture-expiry"))
    with psycopg.connect(dsn) as conn:
        conn.execute("UPDATE alert_outbox SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (other,))
    assert claim_notice(dsn) is None
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT state,attempts FROM alert_outbox WHERE id=%s", (other,)).fetchone() == ("expired", 0)
