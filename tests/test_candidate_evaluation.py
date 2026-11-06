from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from cluster_radar.providers.solana_authorities import encode_pubkey
from mochex_radar.api import app
from mochex_radar.candidate_evaluation import evaluate_stored_candidate

MINT = encode_pubkey(b"\x61" * 32)


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
    assert partial["token_risk"]["security_status"] == "UNKNOWN"
    assert partial["candidate_state"]["state"] == "DISCOVERED"
    assert partial["candidate_state"]["approved_live_signal"] is False


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
