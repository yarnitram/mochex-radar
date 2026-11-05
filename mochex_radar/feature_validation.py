"""Offline descriptive outcome comparisons; never an execution backtest."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from mochex_radar.futures_feed import Candle
from mochex_radar.market_features import BTC_ASSET_ID, FEATURE_VERSION, INTERVALS, compute_features
from mochex_radar.markets import core_markets

REPORT_VERSION = "core-feature-validation-v1"
MAX_BYTES = 5_000_000


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
                      decisions: list[datetime], holdout_at: datetime, evaluation_at: datetime) -> dict:
    """Split descriptive outcomes; future labels never enter feature calculations."""
    with localcontext() as context:
        context.prec = 50
        return _validation_report(candles, asset_id, interval, decisions, holdout_at, evaluation_at)


def _validation_report(candles, asset_id, interval, decisions, holdout_at, evaluation_at) -> dict:
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
    return {"report_version": REPORT_VERSION, "feature_version": FEATURE_VERSION, "dataset_config_sha256": digest,
            "asset_id": asset_id, "interval": interval, "holdout_at": holdout_at.isoformat(),
            "evaluation_at": evaluation_at.isoformat(), "research_only": True, "signals_enabled": False,
            "execution_simulated": False, "splits": splits, "rows": rows,
            "limitations": ["Gross descriptive returns only; no fees, spread, funding, slippage or execution latency.",
                            "User-supplied universe and holdout; no threshold optimization or statistical alpha validation.",
                            "Overlapping outcomes may be dependent; sample counts are not independent trial counts."]}


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("ISO timestamp strings required")
    result = datetime.fromisoformat(value)
    _utc(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("dataset exceeds 5MB")
    data = json.loads(raw)
    expected = {"format_version", "candles", "asset_id", "interval", "decisions", "holdout_at", "evaluation_at"}
    if not isinstance(data, dict) or set(data) != expected or type(data["format_version"]) is not int or data["format_version"] != 1:
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
    report = validation_report(candles, data["asset_id"], data["interval"],
                               [_timestamp(t) for t in data["decisions"]],
                               _timestamp(data["holdout_at"]), _timestamp(data["evaluation_at"]))
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
