import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from cluster_radar.providers.solana_authorities import TOKEN_PROGRAM, AuthorityObservation, encode_pubkey
from mochex_radar.authority_checks import authority_history, initialize_authority_store, store_authority


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_authority_evidence_is_immutable_point_in_time_and_never_safe():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_authority_store(dsn)
    now = datetime.now(timezone.utc)
    mint = encode_pubkey(uuid4().bytes * 2)
    observation = AuthorityObservation(mint, now-timedelta(minutes=1), 123456, TOKEN_PROGRAM,
        "partial_authority_evidence", "a"*64, "DISABLED", "DISABLED")
    try:
        store_authority(dsn, observation)
        store_authority(dsn, observation)
        with pytest.raises(ValueError, match="conflicting"):
            store_authority(dsn, replace(observation, slot=123457))
        assert authority_history(dsn, mint, now-timedelta(seconds=30)) == []
        rows = authority_history(dsn, mint, datetime.now(timezone.utc))
        assert len(rows) == 1
        assert rows[0]["freshness"] == "current"
        assert rows[0]["evidence"]["security_status"] == "UNKNOWN"
        assert rows[0]["evidence"]["approved_pump_watch"] is False
        assert authority_history(dsn, mint, observation.known_at+timedelta(minutes=15))[0]["freshness"] == "stale"
        assert authority_history(dsn, mint, now+timedelta(hours=1))[0]["freshness"] == "stale"
        with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(dsn) as conn:
            conn.execute("UPDATE mint_authority_observations SET payload=%s WHERE mint=%s",
                (Jsonb({"security_status":"PASS","approved_pump_watch":True}),mint))
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM mint_authority_observations WHERE mint=%s",(mint,))
