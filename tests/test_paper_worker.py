from datetime import timedelta

import psycopg

from test_paper_journal import DECISION, STEP, config, plan, raw, snapshot
from mochex_radar.feature_validation import parse_candle_records
from mochex_radar.paper_journal import capture, create_plan, summarize
from mochex_radar.paper_worker import run_once


def test_due_capture_is_prioritized_and_outcome_is_separate(tmp_path):
    path = plan(tmp_path)
    capture(path, 0, raw(), now=DECISION)
    calls = []
    def load(*args):
        calls.append(args)
        return parse_candle_records(snapshot(22)["candles"])
    result = run_once(path, load, clock=lambda: DECISION + STEP)
    assert result["captured"] == result["outcomes"] == 1
    assert calls[0][2] == DECISION + STEP - 22 * STEP
    assert calls[1][-1] == DECISION + STEP
    assert summarize(path, now=DECISION + STEP)["rows"][0]["status"] == "complete"


def test_missed_and_future_slots_do_not_query_storage(tmp_path):
    path = plan(tmp_path)
    def forbidden(*args):
        raise AssertionError("unexpected query")
    result = run_once(path, forbidden, clock=lambda: DECISION + timedelta(seconds=31))
    assert not any(result.values())
    assert summarize(path, now=DECISION + timedelta(seconds=31))["rows"][0]["status"] == "missed_capture"


def test_slow_query_never_backdates_a_capture(tmp_path):
    path = plan(tmp_path)
    ticks = iter([DECISION, DECISION, DECISION + timedelta(seconds=31)])
    result = run_once(path, lambda *args: parse_candle_records(snapshot()["candles"]), clock=lambda: next(ticks))
    assert result["deadline_missed"] == 1 and not (path / "captures").exists()


def test_database_failure_leaves_capture_eligible_for_later_retry(tmp_path):
    path = plan(tmp_path)
    def failed(*args):
        raise psycopg.OperationalError("private connection must not be logged")
    assert run_once(path, failed, clock=lambda: DECISION)["unavailable"] == 1
    assert run_once(path, lambda *args: parse_candle_records(snapshot()["candles"]), clock=lambda: DECISION)["captured"] == 1


def test_cycle_is_bounded_with_capture_before_pending_backlog(tmp_path):
    settings = config()
    settings["decision_end"] = (DECISION + 8 * STEP).isoformat()
    path = create_plan(tmp_path, settings, now=DECISION - STEP)
    for i in range(7):
        capture(path, i, raw(snapshot(21 + i)), now=DECISION + i * STEP)
    result = run_once(path, lambda *args: parse_candle_records(snapshot(28)["candles"]), clock=lambda: DECISION + 7 * STEP)
    assert result["captured"] == 1 and result["outcomes"] == 4


def test_concurrent_capture_duplicate_is_preserved(tmp_path):
    path = plan(tmp_path)
    def raced(*args):
        capture(path, 0, raw(), now=DECISION)
        return parse_candle_records(snapshot()["candles"])
    result = run_once(path, raced, clock=lambda: DECISION)
    assert result["duplicates"] == 1
