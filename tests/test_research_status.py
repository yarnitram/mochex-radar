import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from mochex_radar.api import app
from mochex_radar.paper_journal import capture, create_plan, record_outcome
from mochex_radar.research_status import research_status

BASE = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=15)
DECISION = BASE + 21 * STEP
SOL = "cex:mexc-usdt-futures:SOL_USDT"
BTC = "cex:mexc-usdt-futures:BTC_USDT"


def _config():
    return {
        "format_version": 1,
        "asset_id": SOL,
        "interval": "15m",
        "decision_start": DECISION.isoformat(),
        "decision_end": (DECISION + 2 * STEP).isoformat(),
        "holdout_at": (DECISION + STEP).isoformat(),
        "capture_grace_seconds": 30,
        "data_kind": "synthetic",
        "selection_rationale": "Synthetic predeclared cohort",
        "cost_scenarios": [],
    }


def _snapshot(count=21):
    return {
        "format_version": 1,
        "candles": [
            {
                "asset_id": asset,
                "interval": "15m",
                "open_time": (BASE + i * STEP).isoformat(),
                "close_time": (BASE + (i + 1) * STEP).isoformat(),
                "retrieved_at": (BASE + (i + 1) * STEP).isoformat(),
                "open": "100",
                "high": "102",
                "low": "99",
                "close": "101",
                "volume": "10",
                "source": "synthetic",
            }
            for asset in (SOL, BTC)
            for i in range(count)
        ],
    }


def test_disabled_status_when_root_not_configured():
    out = research_status(None, [])
    assert out == {"status": "disabled", "research_only": True, "plans": []}


def test_configured_status_summarizes_selected_plans_and_isolates_missing_or_corrupt(tmp_path):
    plan_path = create_plan(tmp_path, _config(), now=DECISION - timedelta(seconds=1))
    capture(plan_path, 0, json.dumps(_snapshot()).encode(), now=DECISION + timedelta(seconds=1))
    record_outcome(plan_path, 0, json.dumps(_snapshot(22)).encode(), now=DECISION + STEP)

    missing_id = "b" * 64
    out = research_status(tmp_path, [plan_path.name, missing_id])
    assert out["status"] == "configured" and out["research_only"] is True
    assert len(out["plans"]) == 2

    first, second = out["plans"]
    assert first["plan_id"] == plan_path.name
    assert first["status"] == "available"
    assert first["asset_id"] == SOL and first["interval"] == "15m"
    assert first["decision_start"] == DECISION.isoformat()
    assert first["decision_end"] == (DECISION + 2 * STEP).isoformat()
    assert first["total_slots"] == 3
    assert first["status_counts"]["complete"] == 1
    assert first["status_counts"]["missed_capture"] == 2
    assert first["feature_status_counts"] == {"ok": 1, "unavailable": 0}
    assert "gross_return" not in json.dumps(out)
    assert str(tmp_path) not in json.dumps(out)

    assert second == {
        "plan_id": missing_id,
        "status": "unavailable",
        "asset_id": None,
        "interval": None,
        "decision_start": None,
        "decision_end": None,
        "total_slots": None,
        "as_of": None,
        "status_counts": None,
        "feature_status_counts": None,
    }


def test_validation_rejects_bad_ids_duplicates_too_many_and_symlinks(monkeypatch, tmp_path):
    valid = "a" * 64
    for bad in (
        ["not-a-sha"],
        ["../" + "a" * 61],
        [valid, valid],
        [f"{i:064x}" for i in range(11)],
    ):
        with pytest.raises(ValueError, match="plan IDs"):
            research_status(tmp_path, bad)
    monkeypatch.setattr("pathlib.Path.is_symlink", lambda self: self == tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        research_status(tmp_path, [valid])


def test_api_endpoint_disabled_configured_and_invalid_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("RADAR_API_TOKEN", raising=False)
    monkeypatch.delenv("RESEARCH_STATUS_ROOT", raising=False)
    monkeypatch.delenv("RESEARCH_STATUS_PLAN_IDS", raising=False)
    client = TestClient(app)

    disabled = client.get("/api/v1/research/status")
    assert disabled.status_code == 200
    assert disabled.json() == {"status": "disabled", "research_only": True, "plans": []}

    plan_path = create_plan(tmp_path, _config(), now=DECISION - timedelta(seconds=1))
    monkeypatch.setenv("RESEARCH_STATUS_ROOT", str(tmp_path))
    monkeypatch.setenv("RESEARCH_STATUS_PLAN_IDS", plan_path.name)
    configured = client.get("/api/v1/research/status")
    assert configured.status_code == 200
    body = configured.json()
    assert body["status"] == "configured" and body["plans"][0]["plan_id"] == plan_path.name

    monkeypatch.setenv("RESEARCH_STATUS_PLAN_IDS", "invalid-plan-id")
    invalid = client.get("/api/v1/research/status")
    assert invalid.status_code == 503
    assert "tmp_path" not in invalid.text and str(tmp_path) not in invalid.text
