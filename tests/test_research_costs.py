import copy
import json
import sys
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from pathlib import Path

import pytest

from mochex_radar.feature_validation import COST_FIELDS, main, report_from_bytes
from mochex_radar.research_registry import register_run, verify_run

FIXTURE = Path(__file__).parent / "fixtures" / "core-feature-validation.json"


def scenario(name="assumed", **values):
    return {"name": name, **{field: "0" for field in COST_FIELDS}, **values}


def dataset(scenarios=None):
    data = json.loads(FIXTURE.read_bytes())
    data["format_version"] = 2
    data["cost_scenarios"] = [scenario()] if scenarios is None else scenarios
    return data


def report(data):
    return report_from_bytes(json.dumps(data).encode())


def eligible(out):
    return [row for row in out["rows"] if row["gross_return"] is not None]


def test_zero_cost_equivalence_v1_unchanged_and_explicit_v2_guards():
    old = report_from_bytes(FIXTURE.read_bytes())
    out = report(dataset())
    assert old["report_version"] == "core-feature-validation-v1" and "cost_sensitivity" not in old
    assert out["report_version"] == "core-feature-validation-v2"
    assert out["splits"] == old["splits"]
    assert all(Decimal(r["cost_estimates"]["assumed"]["net_return"]) == Decimal(r["gross_return"]) for r in eligible(out))
    assert all(Decimal(r["cost_estimates"]["assumed"]["cost_drag"]) == 0 for r in eligible(out))
    assert out["signals_enabled"] is False and out["execution_simulated"] is False
    assert out["cost_sensitivity"]["assumptions_status"] == "USER_SUPPLIED_NOT_VERIFIED"
    assert out["dataset_config_sha256"] != old["dataset_config_sha256"]


@pytest.mark.parametrize("closing", ["99", "100", "101"])
def test_entry_and_exit_fees_apply_to_respective_notionals(closing):
    data = dataset([scenario(entry_fee_bps="10", exit_fee_bps="20")])
    for candle in data["candles"]:
        candle["close"] = closing
    out = report(data)
    # One-unit entry at 100: independently charge each fee on its own notional.
    exit_ratio = Decimal(closing) / 100
    expected = exit_ratio - 1 - Decimal("0.001") - exit_ratio * Decimal("0.002")
    assert Decimal(eligible(out)[0]["cost_estimates"]["assumed"]["net_return"]) == expected


def test_adverse_reference_prices_and_signed_total_funding():
    out = report(dataset([scenario(entry_half_spread_bps="5", entry_slippage_bps="5",
                                   exit_half_spread_bps="10", exit_slippage_bps="10", funding_cost_bps="3")]))
    # Independently price one unit with the assumed entry/exit changes.
    with localcontext() as context:
        context.prec = 100
        entry_price = Decimal(100) * Decimal("1.001")
        exit_price = Decimal(101) * Decimal("0.998")
        expected = exit_price / entry_price - 1 - Decimal("0.0003")
    net = Decimal(eligible(out)[0]["cost_estimates"]["assumed"]["net_return"])
    assert abs(net - expected) < Decimal("1e-95")
    credit = report(dataset([scenario(funding_cost_bps="-5")]))
    assert Decimal(eligible(credit)[0]["cost_estimates"]["assumed"]["net_return"]) == Decimal("0.0105")


def test_each_adverse_cost_is_monotonic_and_can_turn_gain_into_loss():
    base = Decimal(eligible(report(dataset()))[0]["cost_estimates"]["assumed"]["net_return"])
    for field in COST_FIELDS:
        net = Decimal(eligible(report(dataset([scenario(**{field: "20"})])))[0]["cost_estimates"]["assumed"]["net_return"])
        assert net < base
    loss = report(dataset([scenario(entry_fee_bps="100", exit_fee_bps="100")]))
    assert Decimal(eligible(loss)[0]["cost_estimates"]["assumed"]["net_return"]) < 0


def test_missing_rows_and_empty_groups_stay_unknown_with_identical_populations():
    out = report(dataset([scenario("zero"), scenario("stress", entry_fee_bps="100")]))
    missing = [r for r in out["rows"] if r["gross_return"] is None]
    assert missing and all(value == {"net_return": None, "cost_drag": None}
                           for r in missing for value in r["cost_estimates"].values())
    for split, values in out["cost_sensitivity"]["splits"].items():
        for value in values.values():
            assert value["baseline"]["count"] == out["splits"][split]["baseline"]["count"]
            assert value["groups"]["structure_state"]["breakout_up"]["mean_net_return"] is None


def test_changing_holdout_outcomes_does_not_change_development_cost_results():
    data = dataset([scenario(entry_fee_bps="10")])
    original = report(data)
    changed = copy.deepcopy(data)
    for candle in changed["candles"]:
        if candle["open_time"] >= changed["holdout_at"]:
            candle["close"] = "102"
    out = report(changed)
    assert out["cost_sensitivity"]["splits"]["development"] == original["cost_sensitivity"]["splits"]["development"]
    assert out["rows"][1]["features"] == original["rows"][1]["features"]


@pytest.mark.parametrize("bad", [[], None, [scenario()] * 11, [scenario(), scenario()],
    [scenario(name=" ")], [scenario(name=" x ")], [scenario(name="x" * 41)],
    [scenario(entry_fee_bps=1)], [scenario(entry_fee_bps=True)],
    [scenario(entry_fee_bps="NaN")], [scenario(entry_fee_bps="Infinity")],
    [scenario(entry_fee_bps="1e999999")], [scenario(entry_fee_bps="-1")],
    [scenario(exit_fee_bps="1001")], [scenario(funding_cost_bps="-1001")],
    [scenario(entry_slippage_bps="0.000000001")], [scenario(entry_fee_bps="invalid")],
    [{"name": "incomplete"}], [{**scenario(), "unexpected": "0"}]])
def test_bad_scenarios_rejected(bad):
    data = dataset()
    data["cost_scenarios"] = bad
    with pytest.raises(ValueError):
        report(data)


def test_costs_require_explicit_v2_and_participate_in_registry_replay(tmp_path, monkeypatch):
    data = dataset([scenario("explicit", entry_fee_bps="10")])
    invalid = {**data, "format_version": 1}
    with pytest.raises(ValueError):
        report(invalid)
    source, target = tmp_path / "input.json", tmp_path / "output.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(sys, "argv", ["comparison", "--input", str(source), "--output", str(target)])
    main()
    assert json.loads(target.read_bytes())["report_version"] == "core-feature-validation-v2"
    bundle = register_run(tmp_path / "registry", source, "synthetic", "Assumed costs for regression only")
    assert verify_run(bundle, replay=True)["replayed"] is True
    data["cost_scenarios"][0]["entry_fee_bps"] = "20"
    source.write_text(json.dumps(data))
    second = register_run(tmp_path / "registry", source, "synthetic", "Assumed costs for regression only")
    assert second.name != bundle.name


def test_cost_reports_ignore_callers_precision():
    data = dataset([scenario(entry_half_spread_bps="1", exit_fee_bps="0.12345678")])
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_UP
        first = report(data)
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_DOWN
        second = report(data)
    assert first == second
