import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from mochex_radar.history_provenance import HistoryProvenance
from mochex_radar.history_batch_store import initialize_history_batches, store_provenance, provenance_history


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_idempotent_provenance_respects_ingestion_cutoff():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_history_batches(dsn)
    now = datetime.now(timezone.utc)
    wallet = uuid4().hex
    p = HistoryProvenance("fixture", "v1", wallet, now - timedelta(hours=2),
                          now - timedelta(hours=1), now - timedelta(hours=1), "a" * 64, True)
    try:
        assert store_provenance(dsn, p) == store_provenance(dsn, p)
        assert provenance_history(dsn, wallet, now - timedelta(minutes=30)) == []
        assert provenance_history(dsn, wallet, datetime.now(timezone.utc) + timedelta(seconds=1)) == [p.envelope()]
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM history_provenance_batches WHERE wallet=%s", (wallet,))
