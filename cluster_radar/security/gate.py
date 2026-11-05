"""Conservative, point-in-time security gate for research signals."""

from dataclasses import dataclass
from datetime import UTC, datetime

from cluster_radar.signals.rules import SecurityStatus


@dataclass(frozen=True)
class SecurityEvidence:
    source: str
    known_at: datetime
    mint_authority_disabled: bool | None
    freeze_authority_disabled: bool | None
    critical_risk: bool | None


def evaluate_security(evidence: SecurityEvidence | None, *, as_of: datetime) -> SecurityStatus:
    """Unknown or future evidence cannot approve a Pump Watch."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if evidence is None:
        return SecurityStatus.UNKNOWN
    if evidence.known_at.tzinfo is None:
        raise ValueError("known_at must be timezone-aware")
    if evidence.known_at.astimezone(UTC) > as_of.astimezone(UTC):
        return SecurityStatus.UNKNOWN
    if evidence.critical_risk is True:
        return SecurityStatus.BLOCK
    if evidence.critical_risk is None:
        return SecurityStatus.UNKNOWN
    if evidence.mint_authority_disabled is False or evidence.freeze_authority_disabled is False:
        return SecurityStatus.CAUTION
    if evidence.mint_authority_disabled is None or evidence.freeze_authority_disabled is None:
        return SecurityStatus.UNKNOWN
    return SecurityStatus.PASS
