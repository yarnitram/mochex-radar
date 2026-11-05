"""Offline observation coverage diagnostics; never production or statistical approval."""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from mochex_radar.feature_validation import MAX_BYTES, _timestamp, report_from_bytes
from mochex_radar.market_features import BTC_ASSET_ID, INTERVALS

VERSION = "validation-coverage-readiness-v1"


def _first_observations(rows: list[dict]) -> list[dict]:
    first = {}
    for row in sorted(rows, key=lambda r: (r["retrieved_at"], r["open_time"])):
        first.setdefault(row["open_time"], row)
    return sorted(first.values(), key=lambda r: r["open_time"])


def _inventory(rows: list[dict], evaluation: datetime, interval: str) -> dict:
    visible = _first_observations([r for r in rows if r["close_time"] <= evaluation and r["retrieved_at"] <= evaluation])
    step = INTERVALS[interval]
    gap_count, missing, largest = 0, 0, 0
    gaps = []
    for left, right in zip(visible, visible[1:]):
        skipped = (right["open_time"] - left["open_time"]) // step - 1
        if skipped > 0:
            gap_count += 1
            missing += skipped
            largest = max(largest, skipped)
            if len(gaps) < 20:
                gaps.append({"first_missing_open_at": (left["open_time"] + step).isoformat(),
                             "last_missing_open_at": (right["open_time"] - step).isoformat(), "missing_intervals": skipped})
    lags = [(r["retrieved_at"] - r["close_time"]).total_seconds() for r in visible]
    return {"input_observations": len(rows), "visible_unique_candles": len(visible),
            "future_close_observations": sum(r["close_time"] > evaluation for r in rows),
            "future_retrieval_observations": sum(r["retrieved_at"] > evaluation for r in rows),
            "first_visible_open_at": visible[0]["open_time"].isoformat() if visible else None,
            "last_visible_close_at": visible[-1]["close_time"].isoformat() if visible else None,
            "sources": sorted({r["source"] for r in visible}),
            "max_retrieval_lag_seconds": max(lags) if lags else None,
            "internal_missing_intervals": missing, "gap_run_count": gap_count,
            "largest_internal_gap_intervals": largest, "gap_details": gaps, "gap_details_truncated": gap_count > len(gaps)}


def readiness_from_bytes(raw: bytes) -> dict:
    comparison = report_from_bytes(raw)  # Shared identity, UTC, OHLCV, bounds and point-in-time validation.
    data = json.loads(raw)
    evaluation = _timestamp(data["evaluation_at"])
    parsed = []
    for candle in data["candles"]:
        source = candle.get("source", "mexc-usdt-futures")
        if not isinstance(source, str) or not 1 <= len(source) <= 200:
            raise ValueError("bounded source identifiers required")
        parsed.append({**candle, "source": source,
                       **{name: _timestamp(candle[name]) for name in ("open_time", "close_time", "retrieved_at")}})
    target = [r for r in parsed if r["asset_id"] == data["asset_id"]]
    btc = [r for r in parsed if r["asset_id"] == BTC_ASSET_ID]
    target_first = _first_observations(target)
    by_open = {r["open_time"]: r for r in target_first}
    rows = []
    for row in comparison["rows"]:
        decision = _timestamp(row["decision_at"])
        outcome_start, outcome_close = _timestamp(row["outcome_open_at"]), _timestamp(row["outcome_close_at"])
        outcome = by_open.get(outcome_start)
        if outcome_close > evaluation:
            outcome_status = "not_closed_by_evaluation"
        elif outcome is None:
            outcome_status = "missing_from_dataset"
        elif outcome["retrieved_at"] > evaluation:
            outcome_status = "not_retrieved_by_evaluation"
        else:
            outcome_status = "available"
        feature = row["features"]
        rs = feature["status"] == "ok" and feature["features"]["relative_strength"] is not None
        rows.append({"decision_at": row["decision_at"], "split": row["split"],
                     "core_feature_status": feature["status"], "core_feature_reason": feature["reason"],
                     "visible_target_history_count": sum(r["close_time"] <= decision and r["retrieved_at"] <= decision for r in target_first),
                     "closed_target_candles_not_yet_known": sum(r["close_time"] <= decision < r["retrieved_at"] for r in target_first),
                     "btc_relative_strength_available": rs,
                     "btc_relative_strength_reason": None if rs else feature["relative_strength_reason"] or "core_features_unavailable",
                     "outcome_status": outcome_status, "outcome_open_at": row["outcome_open_at"],
                     "outcome_close_at": row["outcome_close_at"],
                     "boundary_purged": row["reason"] == "split_boundary_crossing",
                     "eligible_for_comparison": row["gross_return"] is not None})
    splits = {}
    for split in ("development", "holdout"):
        population = [r for r in rows if r["split"] == split]
        included = [r for r in population if not r["boundary_purged"]]
        eligible = [r for r in included if r["eligible_for_comparison"]]
        windows = {r["outcome_open_at"] for r in eligible}
        splits[split] = {"decisions": len(population), "boundary_purged": len(population) - len(included),
                         "eligible_samples": len(eligible), "missing_samples": len(included) - len(eligible),
                         "core_feature_missing_reasons": dict(Counter(r["core_feature_reason"] for r in included if r["core_feature_status"] != "ok")),
                         "outcome_status_counts": dict(Counter(r["outcome_status"] for r in included)),
                         "btc_relative_strength_missing": sum(not r["btc_relative_strength_available"] for r in included),
                         "distinct_outcome_windows": len(windows), "repeated_outcome_windows": len(eligible) - len(windows)}
    both = all(s["eligible_samples"] > 0 for s in splits.values())
    complete = both and all(s["missing_samples"] == 0 and s["btc_relative_strength_missing"] == 0 for s in splits.values())
    any_eligible = any(s["eligible_samples"] > 0 for s in splits.values())
    return {"report_version": VERSION, "comparison_report_version": comparison["report_version"],
            "dataset_config_sha256": comparison["dataset_config_sha256"], "asset_id": data["asset_id"],
            "interval": data["interval"], "evaluation_at": data["evaluation_at"], "holdout_at": data["holdout_at"],
            "coverage_status": "coverage_complete" if complete else "partial_coverage" if any_eligible else "insufficient_coverage",
            "both_splits_have_comparison_samples": both, "dataset_origin": "NOT_VERIFIED",
            "production_ready": False, "research_only": True, "signals_enabled": False,
            "inventory": {"target": _inventory(target, evaluation, data["interval"]), "btc": _inventory(btc, evaluation, data["interval"])},
            "splits": splits, "rows": rows,
            "limitations": ["Coverage is not statistical sample adequacy, data authenticity, profitability or execution feasibility.",
                            "Inventory gaps cover only first-to-last visible candles; unseen leading/trailing history is not inferred complete.",
                            "Closed-but-not-known counts use first observations present in this dataset, not a complete exchange history.",
                            "Future-close/retrieval inventory counts may overlap; repeated outcome windows are not independent trials."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    report = readiness_from_bytes(raw)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
