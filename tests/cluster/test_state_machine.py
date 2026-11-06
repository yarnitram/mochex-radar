from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cluster_radar.signals.research import WEIGHTS, FeatureEvidence
from cluster_radar.signals.state_machine import (
    CandidateState,
    evaluate_candidate_state,
    replay_candidate_states,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _features(mode: str, value: Decimal = Decimal("0.9"), as_of: datetime = NOW) -> list[FeatureEvidence]:
    return [
        FeatureEvidence(
            name,
            value,
            as_of - timedelta(minutes=15),
            as_of,
            as_of,
            "fixture",
            f"group:{name}",
            (f"ref:{name}",),
        )
        for name in WEIGHTS[mode]
    ]


def _risk(status: str = "UNKNOWN", as_of: datetime = NOW, flags: list[str] | None = None) -> dict:
    return {
        "as_of": as_of,
        "security_status": status,
        "flags": flags or [],
    }


def test_discovered_watching_and_provisional_pump_watch_gates():
    discovered = evaluate_candidate_state(
        mint="mint-a",
        as_of=NOW,
        window_end=NOW,
        pump_features=[],
        dump_features=[],
        token_risk=_risk("UNKNOWN"),
    )
    assert discovered["state"] == CandidateState.DISCOVERED.value
    assert "incomplete_pump_features" in discovered["blocking_gates"]

    # High pump score with UNKNOWN security or unverified buyer independence stays WATCHING.
    watching = evaluate_candidate_state(
        mint="mint-a",
        as_of=NOW,
        window_end=NOW,
        pump_features=_features("pump"),
        dump_features=[],
        token_risk=_risk("UNKNOWN"),
        buyer_independence_verified=False,
    )
    assert watching["state"] == CandidateState.WATCHING.value
    assert "security_status_unknown" in watching["blocking_gates"]
    assert "buyer_independence_unverified" in watching["blocking_gates"]

    # All gates met -> PUMP_WATCH_PROVISIONAL (still provisional and alerts disabled).
    pump_watch = evaluate_candidate_state(
        mint="mint-a",
        as_of=NOW,
        window_end=NOW,
        pump_features=_features("pump"),
        dump_features=[],
        token_risk=_risk("PASS"),
        buyer_independence_verified=True,
        already_broken_out=False,
    )
    assert pump_watch["state"] == CandidateState.PUMP_WATCH_PROVISIONAL.value
    assert pump_watch["blocking_gates"] == []
    assert pump_watch["approved_live_signal"] is False
    assert pump_watch["alerts_enabled"] is False


def test_security_block_and_dump_warning_preempt_pump_watch():
    # Even if pump features, independence, and dump features are all high, BLOCK wins.
    blocked = evaluate_candidate_state(
        mint="mint-a",
        as_of=NOW,
        window_end=NOW,
        pump_features=_features("pump"),
        dump_features=_features("dump"),
        token_risk=_risk("BLOCK", flags=["permanent_delegate_present"]),
        buyer_independence_verified=True,
    )
    assert blocked["state"] == CandidateState.BLOCKED_SECURITY.value
    assert "permanent_delegate_present" in blocked["blocking_gates"]

    # When security is PASS, an active Dump Warning preempts Pump Watch.
    dump_preempts = evaluate_candidate_state(
        mint="mint-a",
        as_of=NOW,
        window_end=NOW,
        pump_features=_features("pump"),
        dump_features=_features("dump"),
        token_risk=_risk("PASS"),
        buyer_independence_verified=True,
    )
    assert dump_preempts["state"] == CandidateState.DUMP_WARNING.value
    assert "dump_warning_preempts_pump_watch" in dump_preempts["blocking_gates"]

    # Correlated dump warnings (< 2 independent groups) do NOT trigger DUMP_WARNING.
    correlated_dump = [replace(f, independence_group="same") for f in _features("dump")]
    no_dump = evaluate_candidate_state(
        mint="mint-a",
        as_of=NOW,
        window_end=NOW,
        pump_features=_features("pump"),
        dump_features=correlated_dump,
        token_risk=_risk("PASS"),
        buyer_independence_verified=True,
    )
    assert no_dump["state"] == CandidateState.PUMP_WATCH_PROVISIONAL.value


def test_replay_candidate_states_tracks_transitions_and_enforces_ordering():
    t0 = NOW
    t1 = NOW + timedelta(minutes=15)
    t2 = NOW + timedelta(minutes=30)
    t3 = NOW + timedelta(minutes=45)

    e0 = evaluate_candidate_state(
        mint="mint-a", as_of=t0, window_end=t0, pump_features=[], dump_features=[], token_risk=_risk("UNKNOWN", t0)
    )
    e1 = evaluate_candidate_state(
        mint="mint-a",
        as_of=t1,
        window_end=t1,
        pump_features=_features("pump", as_of=t1),
        dump_features=[],
        token_risk=_risk("PASS", t1),
        buyer_independence_verified=True,
    )
    e2 = evaluate_candidate_state(
        mint="mint-a",
        as_of=t2,
        window_end=t2,
        pump_features=_features("pump", as_of=t2),
        dump_features=_features("dump", as_of=t2),
        token_risk=_risk("PASS", t2),
        buyer_independence_verified=True,
    )
    e3 = evaluate_candidate_state(
        mint="mint-a",
        as_of=t3,
        window_end=t3,
        pump_features=_features("pump", as_of=t3),
        dump_features=[],
        token_risk=_risk("BLOCK", t3, ["excessive_transfer_fee"]),
        buyer_independence_verified=True,
    )

    replayed = replay_candidate_states([e0, e1, e2, e3])
    assert [r["transition"] for r in replayed] == [
        "NONE->DISCOVERED",
        "DISCOVERED->PUMP_WATCH_PROVISIONAL",
        "PUMP_WATCH_PROVISIONAL->DUMP_WARNING",
        "DUMP_WARNING->BLOCKED_SECURITY",
    ]
    assert all(r["transitioned"] is True for r in replayed)

    with pytest.raises(ValueError, match="ordered"):
        replay_candidate_states([e1, e0])
    with pytest.raises(ValueError, match="single candidate"):
        replay_candidate_states([e0, {**e1, "mint": "mint-b"}])
