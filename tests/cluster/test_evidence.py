from datetime import UTC, datetime, timedelta

import pytest

from cluster_radar.intelligence.funding import FundingObservation, shared_funder_link
from cluster_radar.security.gate import SecurityEvidence, evaluate_security
from cluster_radar.signals.rules import SecurityStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_security_fails_closed_for_missing_and_future_evidence():
    assert evaluate_security(None, as_of=NOW) is SecurityStatus.UNKNOWN
    evidence = SecurityEvidence("fixture", NOW + timedelta(seconds=1), True, True, False)
    assert evaluate_security(evidence, as_of=NOW) is SecurityStatus.UNKNOWN


@pytest.mark.parametrize(
    ("mint", "freeze", "critical", "expected"),
    [
        (True, True, False, SecurityStatus.PASS),
        (None, True, False, SecurityStatus.UNKNOWN),
        (True, False, False, SecurityStatus.CAUTION),
        (True, True, True, SecurityStatus.BLOCK),
        (True, True, None, SecurityStatus.UNKNOWN),
    ],
)
def test_security_status(mint, freeze, critical, expected):
    evidence = SecurityEvidence("fixture", NOW, mint, freeze, critical)
    assert evaluate_security(evidence, as_of=NOW) is expected


def test_shared_funder_is_evidence_only_and_excludes_cex():
    left = FundingObservation("a", "f", NOW, "fixture-a", False)
    right = FundingObservation("b", "f", NOW, "fixture-b", False)
    link = shared_funder_link(left, right, as_of=NOW)
    assert link is not None
    assert link.conclusion == "potential_shared_funder"
    assert shared_funder_link(left, FundingObservation("b", "f", NOW, "fixture", True), as_of=NOW) is None
    assert shared_funder_link(left, right, as_of=NOW - timedelta(seconds=1)) is None
