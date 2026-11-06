"""Bounded read-only status of explicitly selected forward plans."""

import re
from collections import Counter
from pathlib import Path

from mochex_radar.paper_journal import _load_plan, summarize

SLOT_STATES = (
    "scheduled",
    "awaiting_capture",
    "pending_outcome",
    "complete",
    "complete_excluded",
    "missed_capture",
    "incomplete_capture",
    "incomplete_outcome",
)


def research_status(root: Path | None, plan_ids: list[str]) -> dict:
    if root is None:
        return {"status": "disabled", "research_only": True, "plans": []}
    if (len(plan_ids) > 10 or len(set(plan_ids)) != len(plan_ids)
            or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in plan_ids)):
        raise ValueError("require at most ten unique explicit plan IDs")
    if root.is_symlink():
        raise ValueError("journal root must not be a symlink")
    rows = []
    for plan_id in plan_ids:
        try:
            plan_path = root / plan_id
            plan = _load_plan(plan_path)
            report = summarize(plan_path)
            config = plan["config"]
            raw_counts = report["status_counts"]
            status_counts = {state: int(raw_counts.get(state, 0)) for state in SLOT_STATES}
            features = Counter(
                row["core_feature_status"]
                for row in report["rows"]
                if row["core_feature_status"] in ("ok", "unavailable")
            )
            rows.append({
                "plan_id": plan_id,
                "status": "available",
                "asset_id": config["asset_id"],
                "interval": config["interval"],
                "decision_start": config["decision_start"],
                "decision_end": config["decision_end"],
                "total_slots": len(report["rows"]),
                "as_of": report["as_of"],
                "status_counts": status_counts,
                "feature_status_counts": {
                    "ok": int(features.get("ok", 0)),
                    "unavailable": int(features.get("unavailable", 0)),
                },
            })
        except (OSError, ValueError, KeyError, TypeError):
            rows.append({
                "plan_id": plan_id,
                "status": "unavailable",
                "asset_id": None,
                "interval": None,
                "decision_start": None,
                "decision_end": None,
                "total_slots": None,
                "as_of": None,
                "status_counts": None,
                "feature_status_counts": None,
            })
    return {"status": "configured", "research_only": True, "plans": rows}
