from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from cluster_radar.intelligence.research import FundingEvidence, Swap
from cluster_radar.providers.solana_authorities import encode_pubkey
from cluster_radar.signals.research import FeatureEvidence
from mochex_radar.api import app
from mochex_radar.candidate_evaluation import (
    evaluate_stored_candidate,
    evaluate_stored_history_features,
)

MINT = encode_pubkey(b"\x61" * 32)
POOL = encode_pubkey(b"\x62" * 32)
BUYER_A = encode_pubkey(b"\x63" * 32)
BUYER_B = encode_pubkey(b"\x64" * 32)
FUNDER_CEX = encode_pubkey(b"\x65" * 32)
FUNDER_SHARED = encode_pubkey(b"\x66" * 32)


def test_evaluate_stored_candidate_storage_disabled() -> None:
    as_of = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    result = evaluate_stored_candidate(None, MINT, as_of=as_of)
    assert result["data_status"] == "storage_disabled"
    assert result["mint"] == MINT
    assert result["token_risk"]["security_status"] == "UNKNOWN"
    assert result["candidate_state"]["state"] == "DISCOVERED"
    assert result["candidate_state"]["approved_live_signal"] is False
    assert result["candidate_state"]["alerts_enabled"] is False


def test_evaluate_stored_candidate_synthesizes_blocked_and_partial_evidence(monkeypatch) -> None:
    as_of = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    known = "2026-11-06T11:55:00+00:00"

    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.authority_history",
        lambda _dsn, _mint, _cutoff, limit=1: [
            {
                "freshness": "current",
                "evidence": {
                    "reason": "partial_authority_evidence",
                    "mint_authority_status": "DISABLED",
                    "freeze_authority_status": "DISABLED",
                },
            }
        ],
    )
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.observation_history",
        lambda _dsn, _mint, _cutoff, limit=1: [
            {
                "candidate": {
                    "known_at": known,
                    "source": "dexscreener",
                    "liquidity_usd": "50000",
                }
            }
        ],
    )
    # Case 1: Holder concentration is 42% (>= 30% block threshold) -> BLOCKED_SECURITY
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.holder_history",
        lambda _dsn, _mint, _cutoff, limit=1: [
            {
                "freshness": "current",
                "evidence": {
                    "known_at": known,
                    "source": "solana-public-mainnet:getTokenLargestAccounts:finalized",
                    "top_1_unlocked_pct": str(Decimal(42)),
                    "top_10_unlocked_pct": str(Decimal(65)),
                },
            }
        ],
    )
    blocked = evaluate_stored_candidate("postgresql://unused", MINT, as_of=as_of)
    assert blocked["data_status"] == "stored_evaluation"
    assert blocked["token_risk"]["security_status"] == "BLOCK"
    assert blocked["candidate_state"]["state"] == "BLOCKED_SECURITY"
    assert "critical_top_1_concentration" in blocked["token_risk"]["flags"]
    assert blocked["token_risk"]["checks"]["holder_concentration"]["top_1_account_pct"] == "42"
    assert blocked["token_risk"]["checks"]["holder_concentration"]["top_1_unlocked_pct"] == "42"
    assert blocked["token_risk"]["checks"]["holder_concentration"]["top_10_account_pct"] == "65"
    assert blocked["token_risk"]["checks"]["holder_concentration"]["top_10_unlocked_pct"] == "65"

    # Case 1b: Holder concentration with top_1_account_pct in evidence (v2 format)
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.holder_history",
        lambda _dsn, _mint, _cutoff, limit=1: [
            {
                "freshness": "current",
                "evidence": {
                    "known_at": known,
                    "source": "solana-public-mainnet:getTokenLargestAccounts:finalized",
                    "top_1_account_pct": str(Decimal(42)),
                    "top_10_account_pct": str(Decimal(65)),
                },
            }
        ],
    )
    blocked_v2 = evaluate_stored_candidate("postgresql://unused", MINT, as_of=as_of)
    assert blocked_v2["token_risk"]["security_status"] == "BLOCK"
    assert blocked_v2["token_risk"]["checks"]["holder_concentration"]["top_1_account_pct"] == "42"
    assert blocked_v2["token_risk"]["checks"]["holder_concentration"]["top_1_unlocked_pct"] == "42"

    # Case 2: Holder concentration is 8% / 25% (PASS), authority PASS, but 2% sell depth missing -> UNKNOWN
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.holder_history",
        lambda _dsn, _mint, _cutoff, limit=1: [
            {
                "freshness": "current",
                "evidence": {
                    "known_at": known,
                    "source": "solana-public-mainnet:getTokenLargestAccounts:finalized",
                    "top_1_unlocked_pct": str(Decimal(8)),
                    "top_10_unlocked_pct": str(Decimal(25)),
                },
            }
        ],
    )
    partial = evaluate_stored_candidate("postgresql://unused", MINT, as_of=as_of)
    assert partial["token_risk"]["checks"]["mint_and_extensions"]["status"] == "PASS"
    assert partial["token_risk"]["checks"]["holder_concentration"]["status"] == "UNKNOWN"
    assert partial["token_risk"]["checks"]["holder_concentration"]["reason"] == "token_account_only_ownership_and_locks_unverified"
    assert partial["token_risk"]["checks"]["stage_liquidity"]["status"] == "UNKNOWN"
    assert (
        partial["token_risk"]["checks"]["stage_liquidity"]["reason"]
        == "incomplete_dex_liquidity_or_depth"
    )
    assert partial["token_risk"]["checks"]["stage_liquidity"]["dex_liquidity_usd"] == "50000"
    assert partial["token_risk"]["checks"]["stage_liquidity"]["sell_depth_2pct_usd"] is None
    assert partial["token_risk"]["security_status"] == "UNKNOWN"
    assert partial["candidate_state"]["state"] == "DISCOVERED"
    assert partial["candidate_state"]["approved_live_signal"] is False

    # Case 3: observation_history provides dex_liquidity_usd key (real dex observation format)
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.observation_history",
        lambda _dsn, _mint, _cutoff, limit=1: [
            {
                "candidate": {
                    "known_at": known,
                    "source": "dexscreener:token-pairs-v1",
                    "dex_liquidity_usd": "6260788.31",
                }
            }
        ],
    )
    dex_v2 = evaluate_stored_candidate("postgresql://unused", MINT, as_of=as_of)
    assert dex_v2["token_risk"]["checks"]["stage_liquidity"]["status"] == "UNKNOWN"
    assert dex_v2["token_risk"]["checks"]["stage_liquidity"]["dex_liquidity_usd"] == "6260788.31"
    assert dex_v2["token_risk"]["checks"]["stage_liquidity"]["sell_depth_2pct_usd"] is None


def test_history_scoring_integration_gates_incomplete_coverage_and_shared_references(monkeypatch) -> None:
    as_of = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    lookback = timedelta(minutes=15)
    prior_swap = Swap(
        "sig-prior",
        (0,),
        0,
        MINT,
        POOL,
        BUYER_A,
        "BUY",
        Decimal(100),
        Decimal(1000),
        as_of - timedelta(minutes=20),
        as_of - timedelta(minutes=19),
        "helius",
    )
    current_swap = Swap(
        "sig-current",
        (0,),
        0,
        MINT,
        POOL,
        BUYER_B,
        "BUY",
        Decimal(10),
        Decimal(100),
        as_of - timedelta(minutes=5),
        as_of - timedelta(minutes=4),
        "helius",
    )
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.swap_history",
        lambda _dsn, _mint, _cutoff, limit=1000: [current_swap, prior_swap],
    )
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.funding_history",
        lambda _dsn, _wallets, _cutoff, limit=1000: [
            FundingEvidence(
                BUYER_A,
                FUNDER_CEX,
                "f-1",
                as_of - timedelta(hours=1),
                as_of - timedelta(hours=1),
                "CEX",
                as_of - timedelta(hours=1),
                "helius",
            ),
            FundingEvidence(
                BUYER_B,
                FUNDER_SHARED,
                "f-2",
                as_of - timedelta(hours=1),
                as_of - timedelta(hours=1),
                "UNKNOWN",
                as_of - timedelta(hours=1),
                "helius",
            ),
        ],
    )
    monkeypatch.setattr(
        "mochex_radar.candidate_evaluation.provenance_history",
        lambda _dsn, _wallet, _cutoff, limit=10: [{"completeness": "unverified"}],
    )
    monkeypatch.setattr("mochex_radar.candidate_evaluation.authority_history", lambda *a, **k: [])
    monkeypatch.setattr("mochex_radar.candidate_evaluation.observation_history", lambda *a, **k: [])
    monkeypatch.setattr("mochex_radar.candidate_evaluation.holder_history", lambda *a, **k: [])

    # 1. Without verified history_start covering both windows, features remain unavailable (never zero-filled)
    unverified_hist = evaluate_stored_history_features("postgresql://unused", MINT, as_of=as_of, lookback=lookback)
    assert unverified_hist["pump_features"] == []
    assert unverified_hist["dump_features"] == []
    assert unverified_hist["unavailable_features"]["buyer_exhaustion"] == "insufficient_history_coverage"
    assert unverified_hist["unavailable_features"]["new_owner_participation"] == "insufficient_history_coverage"
    assert unverified_hist["buyer_independence_verified"] is False
    assert unverified_hist["funding_groups"]["groups"] == []

    # 2. With history_start covering prior window, swap features derive 1 pump and 1 dump feature,
    #    moving candidate to WATCHING while keeping scores None (missing remaining 4 dimensions)
    covered_start = as_of - timedelta(minutes=30)
    covered_eval = evaluate_stored_candidate(
        "postgresql://unused",
        MINT,
        as_of=as_of,
        lookback=lookback,
        history_start=covered_start,
    )
    assert covered_eval["candidate_state"]["state"] == "WATCHING"
    assert covered_eval["candidate_state"]["pump_score"] is None
    assert covered_eval["candidate_state"]["dump_score"] is None
    assert "incomplete_pump_features" in covered_eval["candidate_state"]["blocking_gates"]
    assert "buyer_independence_unverified" in covered_eval["candidate_state"]["blocking_gates"]
    assert covered_eval["candidate_state"]["provisional"] is True
    assert covered_eval["candidate_state"]["approved_live_signal"] is False
    assert covered_eval["candidate_state"]["alerts_enabled"] is False

    # 3. Shared references across dump features collapse warning groups to 1, preventing false DUMP_WARNING
    shared_ref = f"swap:{current_swap.signature}/0/0"
    extra_dump = [
        FeatureEvidence("holder_distribution", Decimal("0.9"), covered_start, as_of, as_of, "derived:helius", "group-a", (shared_ref,)),
        FeatureEvidence("price_volume_divergence", Decimal("0.9"), covered_start, as_of, as_of, "derived:helius", "group-b", (shared_ref,)),
        FeatureEvidence("liquidity_deterioration", Decimal("0.9"), covered_start, as_of, as_of, "derived:helius", "group-c", (shared_ref,)),
        FeatureEvidence("structure_weakness", Decimal("0.9"), covered_start, as_of, as_of, "derived:helius", "group-d", (shared_ref,)),
    ]
    collapsed_eval = evaluate_stored_candidate(
        "postgresql://unused",
        MINT,
        as_of=as_of,
        lookback=lookback,
        history_start=covered_start,
        extra_dump_features=extra_dump,
    )
    assert collapsed_eval["candidate_state"]["dump_score"] == "90.0"
    assert collapsed_eval["candidate_state"]["dump_warning_groups"] == 1
    assert collapsed_eval["candidate_state"]["state"] == "WATCHING"


def test_candidate_evaluation_and_holders_api_endpoints(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RADAR_API_TOKEN", raising=False)
    with TestClient(app) as client:
        eval_resp = client.get(
            f"/api/v1/candidates/solana/{MINT}/evaluation?as_of=2026-11-06T12:00:00Z"
        )
        assert eval_resp.status_code == 200
        body = eval_resp.json()
        assert body["data_status"] == "storage_disabled"
        assert body["candidate_state"]["state"] == "DISCOVERED"

        bad_mint = client.get("/api/v1/candidates/solana/not-a-pubkey/evaluation")
        assert bad_mint.status_code == 422

        holders_disabled = client.get(f"/api/v1/security/solana/{MINT}/holders")
        assert holders_disabled.status_code == 503
        assert "disabled" in holders_disabled.json()["detail"]

        history_disabled = client.get(
            f"/api/v1/security/solana/{MINT}/holders/history?as_of=2026-11-06T12:00:00Z"
        )
        assert history_disabled.status_code == 503
