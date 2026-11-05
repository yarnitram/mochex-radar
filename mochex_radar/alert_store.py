"""Durable operational notice outbox; credentials are resolved only by the worker."""

from dataclasses import dataclass
from datetime import timedelta, timezone
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from mochex_radar.alerts import ResearchNotice
from mochex_radar.telegram import DeliveryResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_outbox (
    id uuid PRIMARY KEY,
    dedup_key text UNIQUE NOT NULL,
    asset_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('SYSTEM_TEST','DATA_QUALITY')),
    rule_version text NOT NULL,
    payload jsonb NOT NULL,
    body text NOT NULL,
    expires_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN
        ('pending','processing','sent','failed','uncertain','expired')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 4),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_id uuid,
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS alert_outbox_due_idx ON alert_outbox (next_attempt_at, created_at)
WHERE state='pending';
CREATE INDEX IF NOT EXISTS alert_outbox_preview_idx ON alert_outbox (created_at,id)
WHERE state='pending';
CREATE INDEX IF NOT EXISTS alert_outbox_lease_idx ON alert_outbox (lease_until)
WHERE state='processing';
CREATE TABLE IF NOT EXISTS alert_cooldowns (
    asset_id text NOT NULL, kind text NOT NULL, rule_version text NOT NULL,
    last_queued_at timestamptz NOT NULL DEFAULT TIMESTAMPTZ '1970-01-01 00:00:00+00',
    PRIMARY KEY (asset_id,kind,rule_version)
);
CREATE TABLE IF NOT EXISTS alert_delivery_gate (
    destination text PRIMARY KEY CHECK (destination='primary'),
    budget_day date NOT NULL DEFAULT DATE '1970-01-01',
    used integer NOT NULL DEFAULT 0 CHECK (used>=0),
    next_at timestamptz NOT NULL DEFAULT TIMESTAMPTZ '1970-01-01 00:00:00+00'
);
CREATE TABLE IF NOT EXISTS alert_attempts (
    outbox_id uuid NOT NULL REFERENCES alert_outbox(id),
    attempt integer NOT NULL,
    outcome text NOT NULL,
    reason text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    PRIMARY KEY (outbox_id,attempt)
);
"""


@dataclass(frozen=True)
class ClaimedNotice:
    id: UUID
    lease_id: UUID
    body: str
    attempt: int


def initialize_alert_store(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA)
        conn.execute("INSERT INTO alert_delivery_gate (destination) VALUES ('primary') ON CONFLICT DO NOTHING")


def enqueue(dsn: str, notice: ResearchNotice) -> UUID | None:
    """Return existing/new identity, or None when a 30-minute cooldown suppresses it."""
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        key = (notice.asset_id, notice.kind, notice.rule_version)
        conn.execute("""INSERT INTO alert_cooldowns (asset_id,kind,rule_version)
                     VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", key)
        last = conn.execute("""SELECT last_queued_at FROM alert_cooldowns
                             WHERE asset_id=%s AND kind=%s AND rule_version=%s FOR UPDATE""", key).fetchone()[0]
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        if notice.known_at > now or notice.expires_at <= now:
            raise ValueError("future or expired notice")
        existing = conn.execute("SELECT id FROM alert_outbox WHERE dedup_key=%s", (notice.dedup_key(),)).fetchone()
        if existing:
            return existing[0]
        if now - last < timedelta(minutes=30):
            return None
        identity = uuid4()
        conn.execute("""INSERT INTO alert_outbox
                     (id,dedup_key,asset_id,kind,rule_version,payload,body,expires_at)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (identity, notice.dedup_key(), *key, Jsonb(notice.model_dump(mode="json")),
                      notice.render(), notice.expires_at))
        conn.execute("""UPDATE alert_cooldowns SET last_queued_at=%s
                     WHERE asset_id=%s AND kind=%s AND rule_version=%s""", (now, *key))
    return identity


def preview_pending(dsn: str, limit: int = 10) -> list[dict]:
    if not 1 <= limit <= 100:
        raise ValueError("preview limit must be 1..100")
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
        return conn.execute("""SELECT id,kind,asset_id,body,expires_at FROM alert_outbox
            WHERE state='pending' AND expires_at>clock_timestamp()
            ORDER BY created_at,id LIMIT %s""", (limit,)).fetchall()


def claim_notice(dsn: str, daily_limit: int = 100) -> ClaimedNotice | None:
    if daily_limit < 1:
        raise ValueError("positive daily limit required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        day, used, next_at = conn.execute("""SELECT budget_day,used,next_at
            FROM alert_delivery_gate WHERE destination='primary' FOR UPDATE""").fetchone()
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        # A crashed sender might already have delivered. Do not replay its lease.
        conn.execute("""UPDATE alert_attempts a SET outcome='uncertain',reason='lease_expired',finished_at=%s
            FROM alert_outbox o WHERE a.outbox_id=o.id AND a.attempt=o.attempts
            AND o.state='processing' AND o.lease_until<=%s""", (now, now))
        conn.execute("""UPDATE alert_outbox SET state='uncertain',lease_id=NULL,lease_until=NULL
            WHERE state='processing' AND lease_until<=%s""", (now,))
        conn.execute("UPDATE alert_outbox SET state='expired' WHERE state='pending' AND expires_at<=%s", (now,))
        today = now.astimezone(timezone.utc).date()
        used = used if day == today else 0
        if used >= daily_limit or next_at > now:
            return None
        row = conn.execute("""SELECT id,body,attempts FROM alert_outbox WHERE state='pending'
            AND next_attempt_at<=%s AND expires_at>%s AND attempts<4
            ORDER BY next_attempt_at,created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""", (now, now)).fetchone()
        if row is None:
            return None
        lease = uuid4()
        attempt = row[2] + 1
        conn.execute("""UPDATE alert_outbox SET state='processing',attempts=%s,lease_id=%s,
            lease_until=%s WHERE id=%s""", (attempt, lease, now + timedelta(seconds=60), row[0]))
        conn.execute("""UPDATE alert_delivery_gate SET budget_day=%s,used=%s,next_at=%s
            WHERE destination='primary'""", (today, used + 1, now + timedelta(seconds=1)))
        conn.execute("INSERT INTO alert_attempts (outbox_id,attempt,outcome,reason) VALUES (%s,%s,'reserved','claimed')",
                     (row[0], attempt))
    return ClaimedNotice(row[0], lease, row[1], attempt)


def finish_notice(dsn: str, notice: ClaimedNotice, result: DeliveryResult) -> str:
    if result.outcome not in ("sent", "failed", "uncertain", "retry"):
        raise ValueError("invalid delivery outcome")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        # Match claim lock order: global gate, then the outbox row.
        conn.execute("SELECT destination FROM alert_delivery_gate WHERE destination='primary' FOR UPDATE")
        row = conn.execute("""SELECT expires_at FROM alert_outbox
            WHERE id=%s AND lease_id=%s AND state='processing' FOR UPDATE""", (notice.id, notice.lease_id)).fetchone()
        if row is None:
            raise ValueError("notice lease no longer owned")
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        state = result.outcome
        due = now
        if state == "retry":
            due = now + timedelta(seconds=max(60 * 2 ** (notice.attempt - 1), result.retry_after))
            state = "failed" if notice.attempt >= 4 else "expired" if due >= row[0] else "pending"
            if result.reason == "provider_rate_limit":
                conn.execute("UPDATE alert_delivery_gate SET next_at=greatest(next_at,%s) WHERE destination='primary'", (due,))
        conn.execute("""UPDATE alert_outbox SET state=%s,next_attempt_at=%s,lease_id=NULL,lease_until=NULL
            WHERE id=%s""", (state, due, notice.id))
        conn.execute("""UPDATE alert_attempts SET outcome=%s,reason=%s,finished_at=%s
            WHERE outbox_id=%s AND attempt=%s""", (state, result.reason, now, notice.id, notice.attempt))
    return state


def outbox_status(dsn: str) -> dict:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute("SELECT state,count(*) FROM alert_outbox GROUP BY state").fetchall()
    return {"states": dict(rows)}
