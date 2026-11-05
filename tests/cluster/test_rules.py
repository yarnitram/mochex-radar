from cluster_radar.signals.rules import PumpEvaluation, SecurityStatus, approved_pump_watch


def test_unknown_security_blocks_pump_watch():
    x = PumpEvaluation(99, SecurityStatus.UNKNOWN, 50_000, True, False)
    assert approved_pump_watch(x) is False


def test_approved_watch_requires_pass_and_valid_liquidity():
    x = PumpEvaluation(80, SecurityStatus.PASS, 15_000, True, False)
    assert approved_pump_watch(x) is True
    assert approved_pump_watch(PumpEvaluation(80, SecurityStatus.PASS, None, True, False)) is False
    assert approved_pump_watch(PumpEvaluation(80, SecurityStatus.PASS, 15_000, True, True)) is False
