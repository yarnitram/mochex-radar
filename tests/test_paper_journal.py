import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from mochex_radar.paper_journal import capture, create_plan, main, record_outcome, summarize

BASE = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=15)
DECISION = BASE + 21 * STEP
SOL = "cex:mexc-usdt-futures:SOL_USDT"
BTC = "cex:mexc-usdt-futures:BTC_USDT"


def config():
    return {"format_version": 1, "asset_id": SOL, "interval": "15m", "decision_start": DECISION.isoformat(),
            "decision_end": (DECISION + 2 * STEP).isoformat(), "holdout_at": (DECISION + STEP).isoformat(),
            "capture_grace_seconds": 30, "data_kind": "synthetic", "selection_rationale": "Synthetic predeclared cohort",
            "cost_scenarios": [{"name": "explicit_cost", "entry_fee_bps": "10", "exit_fee_bps": "20",
                                "entry_half_spread_bps": "0", "exit_half_spread_bps": "0",
                                "entry_slippage_bps": "0", "exit_slippage_bps": "0", "funding_cost_bps": "0"}]}


def snapshot(count=21):
    return {"format_version": 1, "candles": [
        {"asset_id": asset, "interval": "15m", "open_time": (BASE + i * STEP).isoformat(),
         "close_time": (BASE + (i + 1) * STEP).isoformat(), "retrieved_at": (BASE + (i + 1) * STEP).isoformat(),
         "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10", "source": "synthetic"}
        for asset in (SOL, BTC) for i in range(count)]}


def raw(data=None):
    return json.dumps(snapshot() if data is None else data).encode()


def plan(tmp_path):
    return create_plan(tmp_path, config(), now=DECISION - timedelta(seconds=1))


def test_lifecycle_preserves_capture_then_records_independent_later_outcome(tmp_path):
    path = plan(tmp_path)
    observed = capture(path, 0, raw(), now=DECISION + timedelta(seconds=1))
    assert observed["features"]["status"] == "ok"
    assert summarize(path, now=DECISION + timedelta(seconds=2))["status_counts"] == {"pending_outcome": 1, "scheduled": 2}
    result = record_outcome(path, 0, raw(snapshot(22)), now=DECISION + STEP)
    assert Decimal(result["gross_return"]) == Decimal("0.01")
    assert Decimal(result["cost_estimates"]["explicit_cost"]["net_return"]) == Decimal("0.00698")
    summary = summarize(path, now=DECISION + 3 * STEP)
    assert summary["status_counts"] == {"complete": 1, "missed_capture": 2}
    assert summary["production_ready"] is False and summary["signals_enabled"] is False
    assert (path / "captures" / "0000" / "snapshot.json").read_bytes() == raw()


@pytest.mark.parametrize("when", [DECISION, DECISION + STEP])
def test_retroactive_plan_registration_is_rejected(tmp_path, when):
    with pytest.raises(ValueError, match="before"):
        create_plan(tmp_path, config(), now=when)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("offset", [-1, 31, 900])
def test_capture_grace_and_early_guards(tmp_path, offset):
    path = plan(tmp_path)
    with pytest.raises(ValueError, match="grace"):
        capture(path, 0, raw(), now=DECISION + timedelta(seconds=offset))
    assert not (path / "captures").exists()


def test_capture_rejects_future_evidence_and_retains_unavailable_features(tmp_path):
    path = plan(tmp_path)
    with pytest.raises(ValueError, match="future"):
        capture(path, 0, raw(snapshot(22)), now=DECISION)
    data = snapshot()
    for candle in data["candles"]:
        candle["retrieved_at"] = (DECISION + timedelta(seconds=1)).isoformat()
    captured = capture(path, 0, raw(data), now=DECISION + timedelta(seconds=1))
    assert captured["features"]["reason"] == "insufficient_lookback"
    outcome = record_outcome(path, 0, raw(snapshot(22)), now=DECISION + STEP)
    assert outcome["gross_return"] is None
    assert outcome["cost_estimates"]["explicit_cost"]["net_return"] is None
    assert summarize(path, now=DECISION + STEP)["status_counts"]["complete_excluded"] == 1


def test_outcome_early_and_missing_evidence_stays_pending(tmp_path):
    path = plan(tmp_path)
    capture(path, 0, raw(), now=DECISION)
    with pytest.raises(ValueError, match="before"):
        record_outcome(path, 0, raw(), now=DECISION + timedelta(seconds=1))
    with pytest.raises(ValueError, match="unavailable"):
        record_outcome(path, 0, raw(), now=DECISION + STEP)
    assert summarize(path, now=DECISION + STEP)["rows"][0]["status"] == "pending_outcome"
    assert not (path / "outcomes").exists()


def test_later_corrections_do_not_recompute_captured_features_or_replace_first_label(tmp_path):
    path = plan(tmp_path)
    before = capture(path, 0, raw(), now=DECISION)
    data = snapshot(22)
    label = next(c for c in data["candles"] if c["asset_id"] == SOL and c["open_time"] == DECISION.isoformat())
    data["candles"].append({**label, "retrieved_at": (DECISION + 2 * STEP).isoformat(), "close": "102"})
    result = record_outcome(path, 0, raw(data), now=DECISION + 2 * STEP)
    assert Decimal(result["gross_return"]) == Decimal("0.01")
    record = json.loads((path / "captures" / "0000" / "record.json").read_bytes())["record"]
    assert record["features"] == before["features"]


def test_boundary_crossing_is_excluded(tmp_path):
    settings = config()
    settings["decision_start"] = (DECISION + timedelta(seconds=1)).isoformat()
    settings["decision_end"] = (DECISION + 2 * STEP + timedelta(seconds=1)).isoformat()
    path = create_plan(tmp_path, settings, now=DECISION)
    capture(path, 0, raw(), now=DECISION + timedelta(seconds=1))
    result = record_outcome(path, 0, raw(snapshot(23)), now=DECISION + 2 * STEP)
    assert result["excluded_reason"] == "split_boundary_crossing" and result["gross_return"] is None


def test_duplicate_stages_and_snapshot_tampering_are_detected(tmp_path):
    path = plan(tmp_path)
    capture(path, 0, raw(), now=DECISION)
    with pytest.raises(FileExistsError):
        capture(path, 0, raw(), now=DECISION)
    record_outcome(path, 0, raw(snapshot(22)), now=DECISION + STEP)
    with pytest.raises(FileExistsError):
        record_outcome(path, 0, raw(snapshot(22)), now=DECISION + STEP)
    with (path / "captures" / "0000" / "snapshot.json").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="integrity"):
        summarize(path, now=DECISION + STEP)


def test_source_drift_blocks_new_records_but_allows_existing_summary(tmp_path, monkeypatch):
    path = plan(tmp_path)
    monkeypatch.setattr("mochex_radar.paper_journal._sources", lambda: {"changed": "source"})
    with pytest.raises(ValueError, match="source"):
        capture(path, 0, raw(), now=DECISION)
    assert summarize(path, now=DECISION)["status_counts"]["awaiting_capture"] == 1


def test_interrupted_capture_directory_is_explicit_and_never_overwritten(tmp_path):
    path = plan(tmp_path)
    (path / "captures" / "0000").mkdir(parents=True)
    assert summarize(path, now=DECISION)["rows"][0]["status"] == "incomplete_capture"
    with pytest.raises(FileExistsError):
        capture(path, 0, raw(), now=DECISION)


def test_interrupted_outcome_and_clock_rollback_are_explicit(tmp_path):
    path = plan(tmp_path)
    capture(path, 0, raw(), now=DECISION)
    (path / "outcomes" / "0000").mkdir(parents=True)
    assert summarize(path, now=DECISION + STEP)["rows"][0]["status"] == "incomplete_outcome"
    with pytest.raises(FileExistsError):
        record_outcome(path, 0, raw(snapshot(22)), now=DECISION + STEP)
    with pytest.raises(ValueError, match="clock"):
        summarize(path, now=DECISION - STEP)


def test_plan_tampering_and_snapshot_bounds_reject_before_capture(tmp_path):
    path = plan(tmp_path)
    with pytest.raises(ValueError, match="5MB"):
        capture(path, 0, b" " * 5_000_001, now=DECISION)
    assert not (path / "captures").exists()
    plan_file = path / "plan.json"
    document = json.loads(plan_file.read_bytes())
    document["plan"]["config"]["capture_grace_seconds"] = 300
    plan_file.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="identity"):
        capture(path, 0, raw(), now=DECISION)


def test_cli_create_capture_outcome_summary_with_internal_test_clock(tmp_path, monkeypatch, capsys):
    settings, observations, output = tmp_path / "config.json", tmp_path / "snapshot.json", tmp_path / "summary.json"
    settings.write_text(json.dumps(config()))
    monkeypatch.setattr("mochex_radar.paper_journal._now", lambda value=None: DECISION - timedelta(seconds=1))
    monkeypatch.setattr(sys, "argv", ["journal", "create", "--registry", str(tmp_path / "runs"), "--config", str(settings)])
    main()
    path = tmp_path / "runs" / json.loads(capsys.readouterr().out)["plan_id"]
    observations.write_bytes(raw())
    monkeypatch.setattr("mochex_radar.paper_journal._now", lambda value=None: DECISION)
    monkeypatch.setattr(sys, "argv", ["journal", "capture", "--plan", str(path), "--index", "0", "--snapshot", str(observations)])
    main()
    observations.write_bytes(raw(snapshot(22)))
    monkeypatch.setattr("mochex_radar.paper_journal._now", lambda value=None: DECISION + STEP)
    monkeypatch.setattr(sys, "argv", ["journal", "outcome", "--plan", str(path), "--index", "0", "--snapshot", str(observations)])
    main()
    monkeypatch.setattr(sys, "argv", ["journal", "summary", "--plan", str(path), "--output", str(output)])
    main()
    assert json.loads(output.read_bytes())["status_counts"]["complete"] == 1
    with pytest.raises(FileExistsError):
        main()


@pytest.mark.parametrize("field,value", [("capture_grace_seconds", True), ("capture_grace_seconds", 301),
    ("format_version", True), ("cost_scenarios", None), ("data_kind", "verified"),
    ("decision_end", DECISION.isoformat()), ("holdout_at", DECISION.isoformat()), ("asset_id", "unknown")])
def test_bad_plan_inputs_rejected_without_creating_files(tmp_path, field, value):
    settings = {**config(), field: value}
    with pytest.raises(ValueError):
        create_plan(tmp_path, settings, now=DECISION - STEP)
    assert not list(tmp_path.iterdir())
