import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mochex_radar.validation_readiness import main, readiness_from_bytes

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=15)
SOL = "cex:mexc-usdt-futures:SOL_USDT"
BTC = "cex:mexc-usdt-futures:BTC_USDT"


def candle(i, asset=SOL):
    return {"asset_id": asset, "interval": "15m", "open_time": (START + i * STEP).isoformat(),
            "close_time": (START + (i + 1) * STEP).isoformat(), "retrieved_at": (START + (i + 1) * STEP).isoformat(),
            "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10", "source": "synthetic"}


def dataset():
    return {"format_version": 1, "candles": [candle(i, asset) for asset in (SOL, BTC) for i in range(30)],
            "asset_id": SOL, "interval": "15m", "decisions": [(START + i * STEP).isoformat() for i in (21, 22, 25, 26)],
            "holdout_at": (START + 25 * STEP).isoformat(), "evaluation_at": (START + 30 * STEP).isoformat()}


def assess(data):
    return readiness_from_bytes(json.dumps(data).encode())


def test_complete_coverage_is_not_production_or_statistical_approval():
    out = assess(dataset())
    assert out["coverage_status"] == "coverage_complete"
    assert out["both_splits_have_comparison_samples"] is True
    assert out["production_ready"] is False and out["signals_enabled"] is False
    assert out["dataset_origin"] == "NOT_VERIFIED"
    assert out["inventory"]["target"]["visible_unique_candles"] == 30
    assert out["inventory"]["target"]["internal_missing_intervals"] == 0
    assert all(s["eligible_samples"] == 2 and s["missing_samples"] == 0 for s in out["splits"].values())


def test_missing_btc_is_partial_without_discarding_core_comparison_samples():
    data = dataset()
    data["candles"] = [c for c in data["candles"] if c["asset_id"] == SOL]
    out = assess(data)
    assert out["coverage_status"] == "partial_coverage" and out["both_splits_have_comparison_samples"]
    assert out["inventory"]["btc"]["visible_unique_candles"] == 0
    assert all(r["btc_relative_strength_reason"] == "btc_not_aligned" for r in out["rows"])


def test_empty_input_and_backfill_delays_are_insufficient_not_fabricated():
    data = dataset()
    for c in data["candles"]:
        c["retrieved_at"] = data["evaluation_at"]
    out = assess(data)
    assert out["coverage_status"] == "insufficient_coverage"
    assert out["rows"][0]["closed_target_candles_not_yet_known"] == 21
    assert out["rows"][0]["visible_target_history_count"] == 0
    assert all(r["outcome_status"] == "available" for r in out["rows"])
    data["candles"] = []
    empty = assess(data)
    assert empty["coverage_status"] == "insufficient_coverage"
    assert empty["inventory"]["target"]["max_retrieval_lag_seconds"] is None


@pytest.mark.parametrize("kind,expected", [("missing", "missing_from_dataset"),
                                            ("late", "not_retrieved_by_evaluation"),
                                            ("pending", "not_closed_by_evaluation")])
def test_independent_outcome_diagnostics(kind, expected):
    data = dataset()
    target = next(c for c in data["candles"] if c["asset_id"] == SOL and c["open_time"] == (START + 26 * STEP).isoformat())
    if kind == "missing":
        data["candles"].remove(target)
    elif kind == "late":
        target["retrieved_at"] = (START + 31 * STEP).isoformat()
    else:
        data["evaluation_at"] = (START + 26 * STEP).isoformat()
    out = assess(data)
    assert out["rows"][-1]["outcome_status"] == expected
    assert out["rows"][-1]["core_feature_status"] == "ok"
    assert not out["rows"][-1]["eligible_for_comparison"]


def test_revisions_duplicates_and_input_order_do_not_inflate_visible_history():
    data = dataset()
    original = assess(data)
    revision = {**data["candles"][0], "retrieved_at": (START + 31 * STEP).isoformat(), "close": "102"}
    data["candles"] = list(reversed(data["candles"] + [data["candles"][0], revision]))
    out = assess(data)
    assert out["rows"] == original["rows"]
    assert out["inventory"]["target"]["visible_unique_candles"] == 30
    assert out["inventory"]["target"]["input_observations"] == 32
    assert out["inventory"]["target"]["future_retrieval_observations"] == 1


def test_internal_gap_diagnostics_are_exact_and_bounded():
    data = dataset()
    data["candles"] = [candle(2 * i) for i in range(50)]
    data["evaluation_at"] = (START + 100 * STEP).isoformat()
    out = assess(data)
    inventory = out["inventory"]["target"]
    assert inventory["internal_missing_intervals"] == inventory["gap_run_count"] == 49
    assert len(inventory["gap_details"]) == 20 and inventory["gap_details_truncated"]
    assert inventory["largest_internal_gap_intervals"] == 1
    assert inventory["gap_details"][0]["first_missing_open_at"] == (START + STEP).isoformat()


def test_large_sparse_gap_is_counted_without_enumerating_missing_candles():
    data = dataset()
    data["candles"] = [candle(0), candle(1_000_000)]
    data["evaluation_at"] = (START + 1_000_001 * STEP).isoformat()
    inventory = assess(data)["inventory"]["target"]
    assert inventory["internal_missing_intervals"] == 999_999
    assert inventory["gap_run_count"] == 1 and not inventory["gap_details_truncated"]


def test_purged_decisions_and_repeated_outcome_windows_are_explicit():
    data = dataset()
    data["decisions"] = [(START + i * STEP + timedelta(seconds=1)).isoformat() for i in (21, 24, 25, 26)]
    data["decisions"].insert(1, (START + 21 * STEP + timedelta(seconds=2)).isoformat())
    out = assess(data)
    development = out["splits"]["development"]
    assert development["boundary_purged"] == 1
    assert development["eligible_samples"] == 2 and development["distinct_outcome_windows"] == 1
    assert development["repeated_outcome_windows"] == 1
    assert development["missing_samples"] == 0


def test_hypothetical_costs_do_not_improve_coverage():
    data = dataset()
    before = assess(data)
    cost_fixture = Path(__file__).parent / "fixtures" / "core-feature-costs.json"
    scenarios = json.loads(cost_fixture.read_bytes())["cost_scenarios"]
    data.update(format_version=2, cost_scenarios=scenarios)
    after = assess(data)
    assert before["rows"] == after["rows"] and before["splits"] == after["splits"]
    assert before["coverage_status"] == after["coverage_status"]
    assert before["dataset_config_sha256"] != after["dataset_config_sha256"]


def test_cli_roundtrip_and_no_overwrite(tmp_path, monkeypatch):
    source, output = tmp_path / "input.json", tmp_path / "coverage.json"
    source.write_text(json.dumps(dataset()))
    monkeypatch.setattr(sys, "argv", ["coverage", "--input", str(source), "--output", str(output)])
    main()
    original = output.read_bytes()
    assert json.loads(original)["coverage_status"] == "coverage_complete"
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == original


def test_shared_bounds_and_invalid_evidence_are_enforced():
    with pytest.raises(ValueError, match="5MB"):
        readiness_from_bytes(b" " * 5_000_001)
    data = dataset()
    data["candles"][0]["close"] = "NaN"
    with pytest.raises(ValueError):
        assess(data)
    data = dataset()
    data["candles"][0]["source"] = None
    with pytest.raises(ValueError, match="source"):
        assess(data)
