"""Explainable first-funder links without assuming common wallet ownership."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FundingObservation:
    wallet: str
    funder: str
    known_at: datetime
    source: str
    funder_is_cex: bool | None


@dataclass(frozen=True)
class FundingLink:
    wallets: tuple[str, str]
    funder: str
    evidence_sources: tuple[str, ...]
    conclusion: str = "potential_shared_funder"


def shared_funder_link(
    left: FundingObservation, right: FundingObservation, *, as_of: datetime
) -> FundingLink | None:
    """Return possible funding relation, never an ownership claim."""
    if any(t.tzinfo is None for t in (left.known_at, right.known_at, as_of)):
        raise ValueError("timestamps must be timezone-aware")
    if left.wallet == right.wallet or left.funder != right.funder:
        return None
    if left.known_at > as_of or right.known_at > as_of:
        return None
    if left.funder_is_cex is not False or right.funder_is_cex is not False:
        return None
    return FundingLink(
        wallets=tuple(sorted((left.wallet, right.wallet))),
        funder=left.funder,
        evidence_sources=tuple(sorted((left.source, right.source))),
    )
