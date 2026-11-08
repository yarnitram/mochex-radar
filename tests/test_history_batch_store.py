import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from cluster_radar.intelligence.research import FundingEvidence, Swap
from mochex_radar.funding_store import funding_history
from mochex_radar.history_batch_store import (
    canonical_raw_sha256,
    initialize_history_batches,
    provenance_history,
    retained_raw_evidence,
    store_history_batch,
    store_provenance,
)
from mochex_radar.history_provenance import HistoryProvenance
from mochex_radar.swap_store import swap_history


def test_batch_store_validates_raw_hash_and_provenance_boundaries_before_db():
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    raw = [{"signature": "sig-1", "timestamp": 1700000000}]
    sha = canonical_raw_sha256(raw)
    prov = HistoryProvenance(
        "fixture",
        "v1",
        "wallet-a",
        now - timedelta(hours=2),
        now - timedelta(hours=1),
        now - timedelta(hours=1),
        sha,
        True,
    )
    with pytest.raises(ValueError, match="raw payload SHA256"):
        store_history_batch("not-a-dsn", prov, raw_payload=[{"signature": "tampered"}])

    bad_source_swap = Swap(
        "sig-1",
        (0,),
        0,
        "mint-a",
        "pool-a",
        "wallet-a",
        "BUY",
        Decimal(5),
        Decimal(10),
        now - timedelta(hours=2),
        now - timedelta(hours=1),
        "other-source",
    )
    with pytest.raises(ValueError, match="violates batch provenance"):
        store_history_batch("not-a-dsn", prov, swaps=[bad_source_swap])

    future_funding = FundingEvidence(
        "wallet-a",
        "funder-a",
        "sig-1",
        now - timedelta(hours=1),
        now,
        "NON_CEX",
        now,
        "fixture",
    )
    with pytest.raises(ValueError, match="violates batch provenance"):
        store_history_batch("not-a-dsn", prov, funding=[future_funding])

    with pytest.raises(ValueError, match="valid raw_sha256"):
        retained_raw_evidence("not-a-dsn", "bad-hash", now)


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


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_atomic_history_batch_persists_and_rolls_back_on_conflict():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_history_batches(dsn)
    now = datetime.now(timezone.utc)
    wallet = "wallet-" + uuid4().hex
    mint = "mint-" + uuid4().hex
    raw = [{"signature": "sig-atomic", "wallet": wallet}]
    sha = canonical_raw_sha256(raw)
    prov = HistoryProvenance(
        "fixture",
        "v1",
        wallet,
        now - timedelta(hours=2),
        now - timedelta(hours=1),
        now - timedelta(hours=1),
        sha,
        True,
    )
    swap = Swap(
        "sig-atomic",
        (0,),
        0,
        mint,
        "pool-a",
        wallet,
        "BUY",
        Decimal(10),
        Decimal(25),
        now - timedelta(hours=2),
        now - timedelta(hours=1),
        "fixture",
    )
    funding = FundingEvidence(
        wallet,
        "funder-a",
        "sig-atomic",
        now - timedelta(hours=2),
        now - timedelta(hours=1),
        "NON_CEX",
        now - timedelta(hours=1),
        "fixture",
    )
    try:
        batch_id = store_history_batch(dsn, prov, raw_payload=raw, swaps=[swap], funding=[funding])
        assert store_history_batch(dsn, prov, raw_payload=raw, swaps=[swap], funding=[funding]) == batch_id
        cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
        assert retained_raw_evidence(dsn, sha, cutoff) == raw
        assert swap_history(dsn, mint, cutoff) == [swap]
        assert funding_history(dsn, wallet, cutoff) == [funding]

        # Conflicting swap in a second batch must roll back the new batch envelope atomically
        raw2 = [{"signature": "sig-atomic-2", "wallet": wallet}]
        prov2 = HistoryProvenance(
            "fixture",
            "v2",
            wallet,
            now - timedelta(hours=2),
            now - timedelta(hours=1),
            now - timedelta(hours=1),
            canonical_raw_sha256(raw2),
            True,
        )
        conflicting_swap = replace(swap, token_amount=Decimal(99))
        with pytest.raises(ValueError, match="conflicting"):
            store_history_batch(dsn, prov2, raw_payload=raw2, swaps=[conflicting_swap])
        assert provenance_history(dsn, wallet, datetime.now(timezone.utc) + timedelta(seconds=1)) == [prov.envelope()]
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM history_batch_items WHERE batch_id=%s", (prov.envelope()["batch_id"],))
            conn.execute("DELETE FROM history_provenance_batches WHERE wallet=%s", (wallet,))
            conn.execute("DELETE FROM history_raw_evidence WHERE raw_sha256=%s", (sha,))
            conn.execute("DELETE FROM normalized_swap_observations WHERE mint=%s", (mint,))
            conn.execute("DELETE FROM normalized_funding_observations WHERE wallet=%s", (wallet,))
