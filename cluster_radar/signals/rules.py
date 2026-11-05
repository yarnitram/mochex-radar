"""Simple, testable initial eligibility primitives; not a validated signal engine."""

from dataclasses import dataclass
from enum import Enum


class SecurityStatus(str, Enum):
    PASS = "PASS"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PumpEvaluation:
    score: int
    security_status: SecurityStatus
    liquidity_usd: float | None
    sufficient_data: bool
    already_broken_out: bool


def approved_pump_watch(e: PumpEvaluation, *, minimum_score: int = 75,
                        minimum_liquidity_usd: float = 10_000.0) -> bool:
    """Fail closed; do not infer a safe trade from a high heuristic score."""
    return (
        0 <= e.score <= 100
        and e.score >= minimum_score
        and e.security_status is SecurityStatus.PASS
        and e.liquidity_usd is not None
        and e.liquidity_usd >= minimum_liquidity_usd
        and e.sufficient_data
        and not e.already_broken_out
    )
