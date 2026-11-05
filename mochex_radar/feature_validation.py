"""Offline descriptive outcome comparisons; never an execution backtest."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

from mochex_radar.futures_feed import Candle
from mochex_radar.market_features import BTC_ASSET_ID, FEATURE_VERSION, INTERVALS, compute_features
from mochex_radar.markets import core_markets

REPORT_VERSION = "core-feature-validation-v1"
COST_REPORT_VERSION = "core-feature-validation-v2"
MAX_BYTES = 5_000_000
COST_FIELDS = ("entry_fee_bps", "exit_fee_bps", "entry_half_spread_bps", "exit_half_spread_bps",
               "entry_slippage_bps", "exit_slippage_bps", "funding_cost_bps")


def _cost_scenarios(scenarios: list[dict] | None) -> list[dict] | None:
    if scenarios is None:
        return None
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 10:
        raise ValueError("require 1..10 cost scenarios")
    names = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != {"name", *COST_FIELDS}:
            raise ValueError("all cost fields are required; extra fields forbidden")
        name = scenario["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 40 or name != name.strip() or name in names:
            raise ValueError("cost scenario names must be bounded and unique")
        names.add(name)
        for field in COST_FIELDS:
            raw = scenario[field]
            if not isinstance(raw, str) or not 1 <= len(raw) <= 32:
                raise ValueError("costs require bounded decimal strings")
            try:
                value = Decimal(raw)
            except ArithmeticError as exc:
                raise ValueError("invalid cost decimal") from exc
            lower = -1000 if field == "funding_cost_bps" else 0
            if not value.is_finite() or not lower <= value <= 1000 or value.as_tuple().exponent < -8:
                raise ValueError("cost value or precision exceeds bounds")
    return [dict(scenario) for scenario in scenarios]


def _cost_estimate(gross: str | None, scenario: dict) -> dict:
    if gross is None:
        return {"net_return": None, "cost_drag": None}
    values = {field: Decimal(scenario[field]) / 10000 for field in COST_FIELDS}
    entry = 1 + values["entry_half_spread_bps"] + values["entry_slippage_bps"]
    exit_price = 1 - values["exit_half_spread_bps"] - values["exit_slippage_bps"]
    exit_value = (1 + Decimal(gross)) * exit_price / entry
    net = exit_value * (1 - values["exit_fee_bps"]) - 1 - values["entry_fee_bps"] - values["funding_cost_bps"]
    return {"net_return": str(net), "cost_drag": str(Decimal(gross) - net)}


def _cost_summary(rows: list[dict], name: str) -> dict:
    values = [Decimal(row["cost_estimates"][name]["net_return"]) for row in rows]
    drag = [Decimal(row["cost_estimates"][name]["cost_drag"]) for row in rows]
    return {"count": len(values), "mean_net_return": str(sum(values) / len(values)) if values else None,
            "positive_fraction": str(Decimal(sum(v > 0 for v in values)) / len(values)) if values else None,
            "mean_cost_drag": str(sum(drag) / len(drag)) if drag else None}


def _add_cost_sensitivity(report: dict, scenarios: list[dict]) -> None:
    for row in report["rows"]:
        row["cost_estimates"] = {s["name"]: _cost_estimate(row["gross_return"], s) for s in scenarios}
    splits = {}
    for split in ("development", "holdout"):
        rows = [r for r in report["rows"] if r["split"] == split and r["gross_return"] is not None]
        results = {}
        for scenario in scenarios:
            name = scenario["name"]
            groups = {}
            for field, states in (("volatility_state", ("compressed", "normal", "expanding")),
                                  ("structure_state", ("range", "breakout_up", "breakdown"))):
                groups[field] = {state: _cost_summary([r for r in rows if r["features"]["features"][field] == state], name)
                                 for state in states}
            results[name] = {"baseline": _cost_summary(rows, name), "groups": groups}
        splits[split] = results
    report["report_version"] = COST_REPORT_VERSION
    report["cost_sensitivity"] = {"model_version": "long-entry-notional-cost-v1",
        "assumptions_status": "USER_SUPPLIED_NOT_VERIFIED", "scenarios": scenarios, "splits": splits,
        "direction": "illustrative_long", "leverage": "1", "funding_basis": "assumed_total_interval_cost_bps"}
    report["limitations"][0] = (
        "Cost sensitivity uses assumed long reference prices, fees, adverse half-spread/slippage and total funding cost; "
        "no observed fills, depth, impact, margin, liquidation or latency simulation; no profitability validation.")


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC")


def _validate(candles: list[Candle], interval: str, asset_id: str) -> None:
    seen = {}
    for c in candles:
        for t in (c.open_time, c.close_time, c.retrieved_at):
            _utc(t)
        if c.asset_id not in (asset_id, BTC_ASSET_ID) or c.interval != interval:
            raise ValueError("unexpected candle identity")
        values = (c.open, c.high, c.low, c.close, c.volume)
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in values):
            raise ValueError("finite Decimal candles required")
        if any(v and (abs(v.adjusted()) > 18 or v.as_tuple().exponent < -18) for v in values):
            raise ValueError("candle magnitude or precision exceeds research bounds")
        if (min(values[:4]) <= 0 or c.volume < 0 or c.high < max(c.open, c.close, c.low)
                or c.low > min(c.open, c.close, c.high)
                or c.close_time - c.open_time != INTERVALS[interval]
                or c.retrieved_at < c.close_time
                or c.open_time.timestamp() % INTERVALS[interval].total_seconds()):
            raise ValueError("invalid candle prices or times")
        key = (c.asset_id, c.open_time, c.retrieved_at)
        if key in seen and seen[key] != c:
            raise ValueError("ambiguous equal-time revisions")
        seen[key] = c


def _summary(values: list[Decimal]) -> dict:
    return {"count": len(values),
            "mean_gross_return": str(sum(values) / len(values)) if values else None,
            "positive_fraction": str(Decimal(sum(v > 0 for v in values)) / len(values)) if values else None}


def validation_report(candles: list[Candle], asset_id: str, interval: str,
                      decisions: list[datetime], holdout_at: datetime, evaluation_at: datetime,
                      cost_scenarios: list[dict] | None = None) -> dict:
    """Split descriptive outcomes; future labels never enter feature calculations."""
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _validation_report(candles, asset_id, interval, decisions, holdout_at, evaluation_at, cost_scenarios)


def _validation_report(candles, asset_id, interval, decisions, holdout_at, evaluation_at, cost_scenarios=None) -> dict:
    scenarios = _cost_scenarios(cost_scenarios)
    if interval not in INTERVALS or asset_id not in {m.asset_id for m in core_markets()}:
        raise ValueError("unsupported market or interval")
    if len(candles) > 10000 or not 1 <= len(decisions) <= 1000:
        raise ValueError("dataset bounds exceeded")
    for t in [*decisions, holdout_at, evaluation_at]:
        _utc(t)
    if decisions != sorted(set(decisions)) or decisions[-1] > evaluation_at or holdout_at > evaluation_at:
        raise ValueError("invalid decision order or evaluation cutoff")
    _validate(candles, interval, asset_id)
    ordered = sorted(candles, key=lambda c: (c.asset_id, c.open_time, c.retrieved_at))
    canonical = {"candles": [c.to_dict() for c in ordered], "asset_id": asset_id, "interval": interval,
                 "decisions": [t.isoformat() for t in decisions], "holdout_at": holdout_at.isoformat(),
                 "evaluation_at": evaluation_at.isoformat()}
    if scenarios is not None:
        canonical["cost_scenarios"] = scenarios
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    # First observation known by the evaluation cutoff supplies labels only.
    labels = {}
    for c in ordered:
        if c.asset_id == asset_id and c.retrieved_at <= evaluation_at and c.close_time <= evaluation_at:
            labels.setdefault(c.open_time, c)
    step = INTERVALS[interval]
    rows = []
    for decision in decisions:
        feature = compute_features(candles, candles, asset_id, interval, decision)
        start = decision - timedelta(seconds=decision.timestamp() % step.total_seconds())
        if start < decision:
            start += step
        label = labels.get(start)
        reason = feature["reason"] if feature["status"] != "ok" else None
        if decision < holdout_at < start + step:
            reason = "split_boundary_crossing"
        elif reason is None and label is None:
            reason = "outcome_unavailable"
        value = label.close / label.open - 1 if label is not None and reason is None else None
        rows.append({"decision_at": decision.isoformat(), "split": "holdout" if decision >= holdout_at else "development",
                     "reason": reason, "features": feature, "outcome_open_at": start.isoformat(),
                     "outcome_close_at": (start + step).isoformat(),
                     "outcome_retrieved_at": label.retrieved_at.isoformat() if label else None,
                     "outcome_source": label.source if label else None,
                     "gross_return": str(value) if value is not None else None})
    splits = {}
    for split in ("development", "holdout"):
        population = [r for r in rows if r["split"] == split]
        eligible = [r for r in population if r["gross_return"] is not None]
        groups = {}
        for field, states in (("volatility_state", ("compressed", "normal", "expanding")),
                              ("structure_state", ("range", "breakout_up", "breakdown"))):
            groups[field] = {state: _summary([Decimal(r["gross_return"]) for r in eligible
                                             if r["features"]["features"][field] == state]) for state in states}
        splits[split] = {"baseline": _summary([Decimal(r["gross_return"]) for r in eligible]),
                         "excluded": dict(Counter(r["reason"] for r in population if r["reason"])), "groups": groups}
    report = {"report_version": REPORT_VERSION, "feature_version": FEATURE_VERSION, "dataset_config_sha256": digest,
            "asset_id": asset_id, "interval": interval, "holdout_at": holdout_at.isoformat(),
            "evaluation_at": evaluation_at.isoformat(), "research_only": True, "signals_enabled": False,
            "execution_simulated": False, "splits": splits, "rows": rows,
            "limitations": ["Gross descriptive returns only; no fees, spread, funding, slippage or execution latency.",
                            "User-supplied universe and holdout; no threshold optimization or statistical alpha validation.",
                            "Overlapping outcomes may be dependent; sample counts are not independent trial counts."]}
    if scenarios is not None:
        with localcontext() as context:
            context.prec = 100
            _add_cost_sensitivity(report, scenarios)
    return report


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("ISO timestamp strings required")
    result = datetime.fromisoformat(value)
    _utc(result)
    return result


def report_from_bytes(raw: bytes) -> dict:
    """Shared bounded dataset parser for the CLI and immutable research bundles."""
    if len(raw) > MAX_BYTES:
        raise ValueError("dataset exceeds 5MB")
    data = json.loads(raw)
    expected = {"format_version", "candles", "asset_id", "interval", "decisions", "holdout_at", "evaluation_at"}
    if not isinstance(data, dict) or type(data.get("format_version")) is not int or data["format_version"] not in (1, 2):
        raise ValueError("invalid dataset envelope")
    if data["format_version"] == 2:
        expected.add("cost_scenarios")
    if set(data) != expected or (data["format_version"] == 2 and data["cost_scenarios"] is None):
        raise ValueError("invalid dataset envelope")
    if not isinstance(data["candles"], list) or len(data["candles"]) > 10000:
        raise ValueError("invalid candle array")
    candles = []
    for row in data["candles"]:
        row = dict(row)
        for name in ("open", "high", "low", "close", "volume"):
            if not isinstance(row[name], str) or len(row[name]) > 80:
                raise ValueError("bounded decimal strings required")
            row[name] = Decimal(row[name])
        for name in ("open_time", "close_time", "retrieved_at"):
            row[name] = _timestamp(row[name])
        candles.append(Candle(**row))
    if not isinstance(data["decisions"], list) or len(data["decisions"]) > 1000:
        raise ValueError("invalid decision array")
    return validation_report(candles, data["asset_id"], data["interval"],
                               [_timestamp(t) for t in data["decisions"]],
                               _timestamp(data["holdout_at"]), _timestamp(data["evaluation_at"]), data.get("cost_scenarios"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    report = report_from_bytes(raw)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
