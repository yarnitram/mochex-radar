"""Versioned PRD-weighted research scores; no operational signal approval."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from cluster_radar.intelligence.research import require_utc

WEIGHTS = {
    "pump": {"independent_buying":25,"compression_structure":20,"new_owner_participation":20,
             "wallet_quality":20,"organic_volume":15},
    "dump": {"holder_distribution":30,"buyer_exhaustion":20,"price_volume_divergence":15,
             "liquidity_deterioration":20,"structure_weakness":15},
}
RULE_VERSION = "cluster-research-score-v1"
WARNING_THRESHOLD = Decimal("0.5")


@dataclass(frozen=True)
class FeatureEvidence:
    name: str
    value: Decimal
    window_start: datetime
    window_end: datetime
    known_at: datetime
    source: str
    independence_group: str
    references: tuple[str, ...]

    def __post_init__(self):
        require_utc(self.window_start,self.window_end,self.known_at)
        if not self.window_start < self.window_end <= self.known_at:
            raise ValueError("feature timestamps violate causality")
        if not self.value.is_finite() or not 0 <= self.value <= 1:
            raise ValueError("normalized feature must be 0..1")
        if not all((self.name,self.source,self.independence_group)) or not self.references or any(not r for r in self.references):
            raise ValueError("feature provenance and references required")


def _warning_groups(features: list[FeatureEvidence]) -> int:
    """Collapse supplied correlation groups and overlapping evidence transitively."""
    components: list[set[int]] = []
    for index, feature in enumerate(features):
        linked = {index}
        for other, prior in enumerate(features[:index]):
            if feature.independence_group == prior.independence_group or set(feature.references)&set(prior.references):
                linked.add(other)
        merged = [group for group in components if group&linked]
        for group in merged:
            linked |= group
            components.remove(group)
        components.append(linked)
    return len(components)


def score_research(mode: Literal["pump", "dump"], features: list[FeatureEvidence], *, as_of: datetime, window_end: datetime) -> dict:
    require_utc(as_of,window_end)
    if mode not in WEIGHTS or window_end > as_of:
        raise ValueError("invalid mode or future decision window")
    names = [f.name for f in features]
    if len(set(names)) != len(names) or any(name not in WEIGHTS[mode] for name in names):
        raise ValueError("duplicate or unsupported feature")
    usable = {}
    excluded = {}
    for feature in features:
        reason = "future_knowledge" if feature.known_at>as_of else "window_mismatch" if feature.window_end!=window_end else "stale" if as_of-feature.window_end>=timedelta(minutes=15) else None
        if reason:
            excluded[feature.name] = reason
        else:
            usable[feature.name] = feature
    missing = [name for name in WEIGHTS[mode] if name not in usable]
    coverage = sum(WEIGHTS[mode][name] for name in usable)
    points = sum((f.value*WEIGHTS[mode][name] for name,f in usable.items()),Decimal(0)) if usable else None
    warnings = [f for f in usable.values() if f.value>=WARNING_THRESHOLD]
    independent_groups = _warning_groups(warnings) if mode == "dump" else None
    complete = not missing
    threshold_met = complete and points>=75 and (mode!="dump" or independent_groups>=2)
    return {"mode":mode,"rule_version":RULE_VERSION,"as_of":as_of,"window_end":window_end,
        "score":points if complete else None,"observed_points":points,"coverage_fraction":Decimal(coverage)/100,
        "missing_features":missing,"excluded_features":excluded,"feature_values":{name:f.value for name,f in usable.items()},
        "warning_groups":independent_groups,"research_threshold_met":bool(threshold_met),
        "score_confidence":"PROVISIONAL" if complete else "INCOMPLETE",
        "independence_status":"DECLARED_NOT_VALIDATED","provisional":True,
        "approved_pump_watch":False,"alerts_enabled":False,
        "evidence_references":sorted({r for f in usable.values() for r in f.references})}
