"""Deterministic point-in-time candidate signal state machine; provisional research only."""

from datetime import datetime
from enum import Enum

from cluster_radar.intelligence.research import require_utc
from cluster_radar.signals.research import FeatureEvidence, score_research
from cluster_radar.signals.rules import SecurityStatus

RULE_VERSION = "candidate-state-machine-v1"


class CandidateState(str, Enum):
    DISCOVERED = "DISCOVERED"
    WATCHING = "WATCHING"
    PUMP_WATCH_PROVISIONAL = "PUMP_WATCH_PROVISIONAL"
    DUMP_WARNING = "DUMP_WARNING"
    BLOCKED_SECURITY = "BLOCKED_SECURITY"


def evaluate_candidate_state(
    *,
    mint: str,
    as_of: datetime,
    window_end: datetime,
    pump_features: list[FeatureEvidence],
    dump_features: list[FeatureEvidence],
    token_risk: dict,
    buyer_independence_verified: bool = False,
    already_broken_out: bool = False,
) -> dict:
    """Evaluate point-in-time candidate state with fail-closed security and Dump preemption."""
    require_utc(as_of, window_end)
    if not mint or window_end > as_of:
        raise ValueError("mint and non-future window_end required")
    if token_risk.get("as_of") != as_of:
        raise ValueError("token_risk as_of must match evaluation as_of")
    security_status = token_risk.get("security_status")
    if security_status not in {s.value for s in SecurityStatus}:
        raise ValueError("invalid token_risk security_status")

    pump = score_research("pump", pump_features, as_of=as_of, window_end=window_end)
    dump = score_research("dump", dump_features, as_of=as_of, window_end=window_end)

    pump_blockers: list[str] = []
    if not pump["research_threshold_met"]:
        pump_blockers.append(
            "incomplete_pump_features" if pump["missing_features"] else "pump_score_below_threshold"
        )
    if security_status != SecurityStatus.PASS.value:
        pump_blockers.append(f"security_status_{security_status.lower()}")
    if not buyer_independence_verified:
        pump_blockers.append("buyer_independence_unverified")
    if already_broken_out:
        pump_blockers.append("already_broken_out")

    if security_status == SecurityStatus.BLOCK.value:
        state = CandidateState.BLOCKED_SECURITY.value
        blocking_gates = ["security_blocked", *token_risk.get("flags", [])]
    elif dump["research_threshold_met"]:
        state = CandidateState.DUMP_WARNING.value
        blocking_gates = ["dump_warning_preempts_pump_watch", *pump_blockers]
    elif not pump_blockers:
        state = CandidateState.PUMP_WATCH_PROVISIONAL.value
        blocking_gates = []
    elif (
        pump["observed_points"] is not None
        or dump["observed_points"] is not None
        or security_status != SecurityStatus.UNKNOWN.value
    ):
        state = CandidateState.WATCHING.value
        blocking_gates = pump_blockers
    else:
        state = CandidateState.DISCOVERED.value
        blocking_gates = pump_blockers

    return {
        "rule_version": RULE_VERSION,
        "mint": mint,
        "as_of": as_of,
        "window_end": window_end,
        "state": state,
        "security_status": security_status,
        "pump_score": pump["score"],
        "dump_score": dump["score"],
        "dump_warning_groups": dump["warning_groups"],
        "blocking_gates": blocking_gates,
        "provisional": True,
        "approved_live_signal": False,
        "alerts_enabled": False,
    }


def replay_candidate_states(evaluations: list[dict]) -> list[dict]:
    """Build deterministic state-transition records across strictly ordered decision times."""
    if not evaluations:
        return []
    mint = evaluations[0]["mint"]
    previous_state: str | None = None
    previous_time: datetime | None = None
    history: list[dict] = []
    for item in evaluations:
        as_of = item["as_of"]
        require_utc(as_of)
        if item["mint"] != mint:
            raise ValueError("replay requires a single candidate mint")
        if previous_time is not None and as_of <= previous_time:
            raise ValueError("replay evaluations must be strictly ordered by as_of")
        current_state = item["state"]
        history.append({
            **item,
            "previous_state": previous_state,
            "transitioned": previous_state != current_state,
            "transition": f"{previous_state or 'NONE'}->{current_state}",
        })
        previous_state = current_state
        previous_time = as_of
    return history
