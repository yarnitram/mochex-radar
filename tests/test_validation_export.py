import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from mochex_radar.feature_validation import main as compare_main
from mochex_radar.futures_feed import Candle
from mochex_radar.storage import initialize_database, store_candles
from mochex_radar.validation_export import build_dataset, main, stored_validation_candles

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=15)
SOL = "cex:mexc-usdt-futures:SOL_USDT"
BTC = "cex:mexc-usdt-futures:BTC_USDT"


def candles():
    return [Candle(asset, "15m", START + i * STEP, START + (i + 1) * STEP,
                   START + (i + 1) * STEP, Decimal(100), Decimal(102), Decimal(99),
                   Decimal(101), Decimal(10)) for asset in (SOL, BTC) for i in range(30)]


def build(load=None, **kwargs):
    config = {"asset_id": SOL, "interval": "15m", "decision_start": START + 21 * STEP,
              "decision_end": START + 27 * STEP, "holdout_at": START + 25 * STEP,
              "evaluation_at": START + 30 * STEP, "now": START + 31 * STEP}
    config.update(kwargs)
    return build_dataset(load or (lambda *args: candles()), **config)


def test_preserves_sources_times_and_roundtrips_comparison(tmp_path, monkeypatch):
    calls = []

    def load(*args):
        calls.append(args)
        return list(reversed(candles()))

    data = build(load)
    assert calls == [(SOL, "15m", START - STEP, START + 30 * STEP)]
    assert data == build()
    assert data["candles"][0]["retrieved_at"] == (START + STEP).isoformat()
    assert data["candles"][0]["source"] == "mexc-usdt-futures"
    source, target = tmp_path / "dataset.json", tmp_path / "report.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(sys, "argv", ["compare", "--input", str(source), "--output", str(target)])
    compare_main()
    report = json.loads(target.read_text())
    assert report["splits"]["development"]["baseline"]["count"] == 4
    assert report["splits"]["holdout"]["baseline"]["count"] == 3
    assert report["signals_enabled"] is False


def test_backfill_times_preserved_and_missing_btc_not_invented():
    rows = [replace(c, retrieved_at=START + 30 * STEP) for c in candles() if c.asset_id == SOL]
    data = build(lambda *args: rows)
    assert {c["retrieved_at"] for c in data["candles"]} == {(START + 30 * STEP).isoformat()}
    assert all(c["asset_id"] == SOL for c in data["candles"])


@pytest.mark.parametrize("config", [
    {"decision_end": START + 20 * STEP},
    {"decision_end": START + 27 * STEP + timedelta(seconds=1)},
    {"decision_end": START + 1021 * STEP},
    {"holdout_at": START + 21 * STEP},
    {"evaluation_at": START + 32 * STEP},
    {"evaluation_at": START + 26 * STEP},
    {"decision_start": START.replace(tzinfo=None)},
    {"asset_id": "cex:mexc-usdt-futures:UNKNOWN_USDT"},
    {"interval": "5m"},
])
def test_bad_config_never_calls_database(config):
    def forbidden(*args):
        pytest.fail("invalid configuration reached database")
    with pytest.raises(ValueError):
        build(forbidden, **config)


def test_loader_bounds_and_wrong_identity_rejected():
    for rows in ([], candles() * 167, [c for c in candles() if c.asset_id == BTC],
                 [replace(candles()[0], retrieved_at=START + 31 * STEP)],
                 [replace(candles()[0], asset_id="unexpected")]):
        with pytest.raises(ValueError):
            build(lambda *args: rows)


def cli_args(output):
    return ["export", "--market", "SOL_USDT", "--decision-start", (START + 21 * STEP).isoformat(),
            "--decision-end", (START + 27 * STEP).isoformat(), "--holdout-at", (START + 25 * STEP).isoformat(),
            "--evaluation-at", (START + 30 * STEP).isoformat(), "--output", str(output)]


def test_cli_private_connection_and_no_overwrite(tmp_path, monkeypatch, capsys):
    output = tmp_path / "dataset.json"
    monkeypatch.setattr(sys, "argv", cli_args(output))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        main()
    monkeypatch.setenv("DATABASE_URL", "private-connection-never-log")
    monkeypatch.setattr("mochex_radar.validation_export.stored_validation_candles", lambda *args: candles())
    main()
    original = output.read_bytes()
    with pytest.raises(SystemExit):
        main()
    assert output.read_bytes() == original
    assert "private-connection-never-log" not in capsys.readouterr().err


def test_database_error_is_sanitized_and_creates_no_file(tmp_path, monkeypatch, capsys):
    output = tmp_path / "dataset.json"
    monkeypatch.setattr(sys, "argv", cli_args(output))
    monkeypatch.setenv("DATABASE_URL", "private-url")

    def fail(*args):
        raise psycopg.OperationalError("private-url with password")

    monkeypatch.setattr("mochex_radar.validation_export.stored_validation_candles", fail)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1 and not output.exists()
    assert "private-url" not in capsys.readouterr().err


def test_serialized_size_limit_creates_no_partial_dataset(tmp_path, monkeypatch):
    output = tmp_path / "dataset.json"
    monkeypatch.setattr(sys, "argv", cli_args(output))
    monkeypatch.setenv("DATABASE_URL", "private-url")
    monkeypatch.setattr("mochex_radar.validation_export.stored_validation_candles", lambda *args: candles())
    monkeypatch.setattr("mochex_radar.validation_export.MAX_BYTES", 10)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1 and not output.exists()


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires temporary PostgreSQL")
def test_postgres_export_filters_and_preserves_observations():
    dsn = os.environ["TEST_DATABASE_URL"]
    initialize_database(dsn)
    base = datetime(2094, 1, 1, tzinfo=UTC)
    rows = [replace(c, open_time=base + (c.open_time - START), close_time=base + (c.close_time - START),
                    retrieved_at=base + (c.retrieved_at - START)) for c in candles()]
    # Exclude a late retrieval, wrong interval, wrong pair and out-of-range candle.
    rows[0] = replace(rows[0], retrieved_at=base + 31 * STEP)
    rows += [replace(rows[1], asset_id="cex:mexc-usdt-futures:ADA_USDT"),
             replace(rows[2], interval="1h")]
    try:
        store_candles(dsn, rows)
        got = stored_validation_candles(dsn, SOL, "15m", base + STEP, base + 29 * STEP)
        expected = [c for c in rows if c.asset_id in (SOL, BTC) and c.interval == "15m"
                    and c.open_time >= base + STEP and c.close_time <= base + 29 * STEP
                    and c.retrieved_at <= base + 29 * STEP]
        assert got == sorted(expected, key=lambda c: (c.asset_id, c.open_time, c.retrieved_at))
        data = build_dataset(lambda *args: stored_validation_candles(dsn, *args), SOL, "15m",
                             base + 21 * STEP, base + 27 * STEP, base + 25 * STEP,
                             base + 30 * STEP, now=base + 31 * STEP)
        assert len(data["candles"]) == 59
        bounded = stored_validation_candles(dsn, SOL, "15m", base, base + 30 * STEP, open_end=base + 3 * STEP)
        assert len(bounded) == 5 and all(c.open_time < base + 3 * STEP for c in bounded)
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM market_candles WHERE venue=%s AND market_id IN (%s,%s,%s) AND open_time >= %s AND open_time < %s",
                         ("mexc-usdt-futures", "SOL_USDT", "BTC_USDT", "ADA_USDT", base, base + 31 * STEP))
