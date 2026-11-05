"""Manual forward research plans and immutable observations; no order execution."""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, localcontext
from pathlib import Path

from mochex_radar.feature_validation import MAX_BYTES, _cost_estimate, _cost_scenarios, _timestamp, _validate, parse_candle_records
from mochex_radar.market_features import INTERVALS, compute_features
from mochex_radar.markets import core_markets
from mochex_radar.research_registry import _hash, _json, _read, engine_fingerprints

VERSION = "forward-paper-journal-v1"


def _now(value=None):
    return _timestamp((value or datetime.now(timezone.utc)).isoformat())


def _config(config):
    keys = {"format_version", "asset_id", "interval", "decision_start", "decision_end", "holdout_at",
            "capture_grace_seconds", "data_kind", "selection_rationale", "cost_scenarios"}
    if not isinstance(config, dict) or set(config) != keys or type(config["format_version"]) is not int or config["format_version"] != 1:
        raise ValueError("invalid paper plan schema")
    if config["asset_id"] not in {m.asset_id for m in core_markets()} or config["interval"] not in INTERVALS:
        raise ValueError("unsupported paper market")
    start, end, holdout = (_timestamp(config[k]) for k in ("decision_start", "decision_end", "holdout_at"))
    span, step = end - start, INTERVALS[config["interval"]]
    if span < step or span % step or span // step >= 1000 or not start < holdout <= end:
        raise ValueError("invalid schedule or holdout")
    grace = config["capture_grace_seconds"]
    rationale = config["selection_rationale"]
    if (type(grace) is not int or not 1 <= grace <= 300 or config["data_kind"] not in ("synthetic", "observed")
            or not isinstance(rationale, str) or not 1 <= len(rationale) <= 2000 or not rationale.strip()):
        raise ValueError("invalid paper plan metadata")
    costs = config["cost_scenarios"]
    if costs != []:
        costs = _cost_scenarios(costs)
        if costs is None:
            raise ValueError("cost_scenarios must be an explicit list")
    return {**config, "decision_start": start.isoformat(), "decision_end": end.isoformat(),
            "holdout_at": holdout.isoformat(), "cost_scenarios": costs}


def _sources():
    return {**engine_fingerprints(), "paper_journal.py": _hash(_read(Path(__file__), 1_000_000).replace(b"\r\n", b"\n"))}


def create_plan(registry: Path, config: dict, now=None) -> Path:
    config, now = _config(config), _now(now)
    if _timestamp(config["decision_start"]) <= now:
        raise ValueError("forward plan must be registered before its first decision")
    plan = {"version": VERSION, "config": config, "registered_at": now.isoformat(), "sources": _sources(),
            "research_only": True, "signals_enabled": False, "clock_status": "LOCAL_CLOCK_NOT_ATTESTED"}
    plan_id = _hash(_json(plan))
    encoded = _json({"plan_id": plan_id, "plan": plan})
    if len(encoded) > 64000:
        raise ValueError("plan size limit exceeded")
    registry.mkdir(parents=True, exist_ok=True)
    destination = registry / plan_id
    destination.mkdir()
    with (destination / "plan.json").open("xb") as handle:
        handle.write(encoded)
    return destination


def _load_plan(path, current_source=False):
    if path.is_symlink():
        raise ValueError("symlink journal unsupported")
    wrapper = json.loads(_read(path / "plan.json", 64000))
    plan = wrapper["plan"]
    if (wrapper["plan_id"] != path.name or _hash(_json(plan)) != path.name or plan["version"] != VERSION
            or plan.get("research_only") is not True or plan.get("signals_enabled") is not False):
        raise ValueError("paper plan identity mismatch")
    if _config(plan["config"]) != plan["config"] or _timestamp(plan["registered_at"]) >= _timestamp(plan["config"]["decision_start"]):
        raise ValueError("invalid registered plan")
    if current_source and plan["sources"] != _sources():
        raise ValueError("paper source mismatch")
    return plan


def _slot(plan, index):
    config = plan["config"]
    step = INTERVALS[config["interval"]]
    start, end = _timestamp(config["decision_start"]), _timestamp(config["decision_end"])
    if type(index) is not int or not 0 <= index <= (end - start) // step:
        raise ValueError("invalid decision slot")
    decision = start + index * step
    outcome_start = decision - timedelta(seconds=decision.timestamp() % step.total_seconds())
    if outcome_start < decision:
        outcome_start += step
    return decision, outcome_start, outcome_start + step


def _snapshot(raw, config, now):
    if len(raw) > MAX_BYTES:
        raise ValueError("snapshot exceeds 5MB")
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) != {"format_version", "candles"}
            or type(data["format_version"]) is not int or data["format_version"] != 1):
        raise ValueError("invalid paper snapshot")
    candles = parse_candle_records(data["candles"])
    _validate(candles, config["interval"], config["asset_id"])
    if any(not isinstance(c.source, str) or not 1 <= len(c.source) <= 200 for c in candles):
        raise ValueError("bounded snapshot source identifiers required")
    if any(c.close_time > now or c.retrieved_at > now for c in candles):
        raise ValueError("snapshot contains future observations")
    return candles


def _stage(path, stage, index):
    parent = path / stage
    if parent.is_symlink():
        raise ValueError("symlink stage unsupported")
    destination = parent / f"{index:04d}"
    if destination.is_symlink():
        raise ValueError("symlink record unsupported")
    return destination


def _write_record(path, stage, index, record, raw):
    payload = {**record, "plan_id": path.name, "stage": stage, "index": index, "snapshot_sha256": _hash(raw)}
    encoded = _json({"record_id": _hash(_json(payload)), "record": payload})
    if len(encoded) > 128000:
        raise ValueError("stage record exceeds limit")
    destination = _stage(path, stage, index)
    destination.parent.mkdir(exist_ok=True)
    destination.mkdir()
    with (destination / "snapshot.json").open("xb") as handle:
        handle.write(raw)
    with (destination / "record.json").open("xb") as handle:
        handle.write(encoded)
    return payload


def _load_record(path, stage, index):
    destination = _stage(path, stage, index)
    if destination.is_symlink():
        raise ValueError("symlink record unsupported")
    wrapper = json.loads(_read(destination / "record.json", 128000))
    record = wrapper["record"]
    if (wrapper["record_id"] != _hash(_json(record)) or record["plan_id"] != path.name
            or record["stage"] != stage or record["index"] != index
            or _hash(_read(destination / "snapshot.json", MAX_BYTES)) != record["snapshot_sha256"]):
        raise ValueError("paper record integrity mismatch")
    return record, wrapper["record_id"]


def capture(path: Path, index: int, raw: bytes, now=None) -> dict:
    plan, now = _load_plan(path, True), _now(now)
    decision, _, close = _slot(plan, index)
    if not decision <= now <= decision + timedelta(seconds=plan["config"]["capture_grace_seconds"]) or now >= close:
        raise ValueError("capture outside scheduled grace window")
    candles = _snapshot(raw, plan["config"], now)
    with localcontext() as context:
        context.prec, context.rounding = 50, ROUND_HALF_EVEN
        feature = compute_features(candles, candles, plan["config"]["asset_id"], plan["config"]["interval"], decision)
    return _write_record(path, "captures", index, {"decision_at": decision.isoformat(), "recorded_at": now.isoformat(), "features": feature}, raw)


def record_outcome(path: Path, index: int, raw: bytes, now=None) -> dict:
    plan, now = _load_plan(path, True), _now(now)
    decision, start, close = _slot(plan, index)
    captured, captured_id = _load_record(path, "captures", index)
    if now < close or now < _timestamp(captured["recorded_at"]):
        raise ValueError("outcome cannot be recorded before close or capture")
    config = plan["config"]
    candles = _snapshot(raw, config, now)
    labels = sorted((c for c in candles if c.asset_id == config["asset_id"] and c.open_time == start), key=lambda c: c.retrieved_at)
    if not labels:
        raise ValueError("outcome candle unavailable; preserve pending state")
    holdout = _timestamp(config["holdout_at"])
    reason = "split_boundary_crossing" if decision < holdout < close else captured["features"]["reason"]
    with localcontext() as context:
        context.prec, context.rounding = 100, ROUND_HALF_EVEN
        gross = str(labels[0].close / labels[0].open - 1) if reason is None else None
        estimates = {s["name"]: _cost_estimate(gross, s) for s in config["cost_scenarios"]}
    return _write_record(path, "outcomes", index, {"decision_at": decision.isoformat(), "recorded_at": now.isoformat(),
        "capture_record_id": captured_id, "outcome_open_at": start.isoformat(), "outcome_close_at": close.isoformat(),
        "outcome_retrieved_at": labels[0].retrieved_at.isoformat(), "outcome_source": labels[0].source,
        "gross_return": gross, "cost_estimates": estimates, "excluded_reason": reason,
        "split": "holdout" if decision >= holdout else "development"}, raw)


def summarize(path: Path, now=None) -> dict:
    plan, now = _load_plan(path), _now(now)
    if now < _timestamp(plan["registered_at"]):
        raise ValueError("summary clock precedes registration")
    config = plan["config"]
    count = (_timestamp(config["decision_end"]) - _timestamp(config["decision_start"])) // INTERVALS[config["interval"]] + 1
    rows = []
    for index in range(count):
        decision, _, close = _slot(plan, index)
        capture_path, outcome_path = _stage(path, "captures", index), _stage(path, "outcomes", index)
        capture_record = outcome_record = None
        if capture_path.exists():
            if not (capture_path / "record.json").exists():
                status = "incomplete_capture"
            else:
                capture_record, captured_id = _load_record(path, "captures", index)
                if _timestamp(capture_record["recorded_at"]) > now:
                    raise ValueError("summary clock precedes recorded capture")
                status = "pending_outcome"
                if outcome_path.exists():
                    if not (outcome_path / "record.json").exists():
                        status = "incomplete_outcome"
                    else:
                        outcome_record, _ = _load_record(path, "outcomes", index)
                        if outcome_record["capture_record_id"] != captured_id or _timestamp(outcome_record["recorded_at"]) > now:
                            raise ValueError("outcome capture linkage or clock mismatch")
                        status = "complete" if outcome_record["excluded_reason"] is None else "complete_excluded"
        else:
            if outcome_path.exists():
                raise ValueError("orphan outcome without capture")
            status = "scheduled" if now < decision else "awaiting_capture" if now <= decision + timedelta(seconds=config["capture_grace_seconds"]) and now < close else "missed_capture"
        rows.append({"index": index, "decision_at": decision.isoformat(), "status": status,
                     "core_feature_status": capture_record["features"]["status"] if capture_record else None,
                     "outcome": outcome_record})
    return {"version": VERSION, "plan_id": path.name, "as_of": now.isoformat(), "data_kind": config["data_kind"],
            "data_kind_verification": "CALLER_DECLARED", "clock_status": "LOCAL_CLOCK_NOT_ATTESTED",
            "status_counts": dict(Counter(r["status"] for r in rows)), "rows": rows,
            "research_only": True, "signals_enabled": False, "execution_simulated": False, "production_ready": False,
            "limitations": ["Manual snapshot journal; no authenticated provider history, attested clock or actual fills.",
                            "Missing scheduled observations remain visible; positive outcomes do not establish profitability."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--registry", type=Path, required=True)
    create.add_argument("--config", type=Path, required=True)
    for name in ("capture", "outcome"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--index", type=int, required=True)
        command.add_argument("--snapshot", type=Path, required=True)
    summary = commands.add_parser("summary")
    summary.add_argument("--plan", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        destination = create_plan(args.registry, json.loads(_read(args.config, 64000)))
        print(json.dumps({"plan_id": destination.name}))
    elif args.command == "summary":
        result = summarize(args.plan)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    else:
        operation = capture if args.command == "capture" else record_outcome
        operation(args.plan, args.index, _read(args.snapshot, MAX_BYTES))
        print(json.dumps({"status": "recorded", "stage": args.command, "index": args.index}))


if __name__ == "__main__":
    main()
