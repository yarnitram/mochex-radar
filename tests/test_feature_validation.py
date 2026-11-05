import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from mochex_radar.feature_validation import main, validation_report
from mochex_radar.futures_feed import Candle

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=15)
SOL = "cex:mexc-usdt-futures:SOL_USDT"


def series(count=30):
    return [Candle(SOL, "15m", START + i * STEP, START + (i + 1) * STEP,
                   START + (i + 1) * STEP, Decimal(100), Decimal(102), Decimal(99),
                   Decimal(101), Decimal(10)) for i in range(count)]


def report(candles=None, decisions=None, holdout=None, evaluation=None):
    return validation_report(series() if candles is None else candles, SOL, "15m",
                             decisions or [START + i * STEP for i in (21, 22, 25, 26)],
                             holdout or START + 25 * STEP, evaluation or START + 30 * STEP)


def test_known_returns_baseline_and_empty_groups():
    out = report()
    for split in out["splits"].values():
        assert split["baseline"] == {"count": 2, "mean_gross_return": "0.01", "positive_fraction": "1"}
        assert split["groups"]["structure_state"]["range"] == split["baseline"]
        assert split["groups"]["structure_state"]["breakout_up"]["mean_gross_return"] is None
    assert out["signals_enabled"] is False and out["execution_simulated"] is False


def test_holdout_does_not_rewrite_earlier_features_or_development_metrics():
    baseline = report()
    changed = [replace(c, close=Decimal(102)) if c.open_time >= START + 25 * STEP else c for c in series()]
    out = report(changed)
    assert out["splits"]["development"] == baseline["splits"]["development"]
    assert out["rows"][0]["features"] == baseline["rows"][0]["features"]
    assert out["splits"]["holdout"]["baseline"]["mean_gross_return"] == "0.02"


def test_boundary_crossing_is_purged_and_outcome_starts_after_decision():
    decision = START + 24 * STEP + timedelta(seconds=1)
    out = report(decisions=[decision])
    assert out["rows"][0]["reason"] == "split_boundary_crossing"
    assert out["rows"][0]["outcome_open_at"] == (START + 25 * STEP).isoformat()
    assert out["splits"]["development"]["baseline"]["count"] == 0


def test_future_and_backfilled_data_cannot_supply_earlier_features():
    backfilled = [replace(c, retrieved_at=START + 30 * STEP) for c in series()]
    out = report(backfilled)
    assert all(r["reason"] == "insufficient_lookback" for r in out["rows"])
    late = [replace(c, retrieved_at=START + 31 * STEP) if c.open_time == START + 26 * STEP else c for c in series()]
    assert report(late)["rows"][-1]["reason"] == "outcome_unavailable"


def test_earliest_revision_and_order_determinism():
    candles = series()
    revised = replace(candles[21], close=Decimal(102), retrieved_at=START + 29 * STEP)
    first = report(candles + [revised])
    assert first == report(list(reversed(candles + [revised])))
    assert first["rows"][0]["gross_return"] == "0.01"
    conflict = replace(candles[21], close=Decimal(102))
    with pytest.raises(ValueError, match="ambiguous"):
        report(candles + [conflict])


def test_invalid_data_bounds_and_decisions_fail_closed():
    candles = series()
    for invalid in (replace(candles[0], close=Decimal("NaN")),
                    replace(candles[0], retrieved_at=START),
                    replace(candles[0], open_time=START.replace(tzinfo=None))):
        with pytest.raises(ValueError):
            report([invalid] + candles[1:])
    for decisions in ([START, START], [START + STEP, START], [START.replace(tzinfo=None)], [START] * 1001):
        with pytest.raises(ValueError):
            report(decisions=decisions)
    with pytest.raises(ValueError):
        report(candles * 334)
    with pytest.raises(ValueError, match="magnitude"):
        report([replace(candles[0], high=Decimal("1e100000"))] + candles[1:])


def test_report_precision_is_independent_of_callers_decimal_context():
    with localcontext() as context:
        context.prec = 6
        low = report()
    with localcontext() as context:
        context.prec = 40
        high = report()
    assert low == high


def test_hourly_and_unknown_market_guards():
    hourly = [replace(c, interval="1h", open_time=START + i * timedelta(hours=1),
                      close_time=START + (i + 1) * timedelta(hours=1),
                      retrieved_at=START + (i + 1) * timedelta(hours=1)) for i, c in enumerate(series())]
    out = validation_report(hourly, SOL, "1h", [START + timedelta(hours=21)],
                            START + timedelta(hours=25), START + timedelta(hours=30))
    assert out["rows"][0]["gross_return"] == "0.01"
    with pytest.raises(ValueError, match="unsupported"):
        validation_report([], "UNKNOWN", "15m", [START], START, START)


def test_cli_roundtrip_and_no_overwrite(tmp_path, monkeypatch):
    source, target = tmp_path / "input.json", tmp_path / "output.json"
    data = {"format_version": 1, "candles": [c.to_dict() for c in series()], "asset_id": SOL,
            "interval": "15m", "decisions": [(START + 21 * STEP).isoformat()],
            "holdout_at": (START + 25 * STEP).isoformat(), "evaluation_at": (START + 30 * STEP).isoformat()}
    source.write_text(json.dumps(data))
    monkeypatch.setattr(sys, "argv", ["validation", "--input", str(source), "--output", str(target)])
    main()
    assert json.loads(target.read_text())["rows"][0]["gross_return"] == "0.01"
    with pytest.raises(FileExistsError):
        main()
    data["candles"][0]["open"] = 100
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="decimal strings"):
        main()
