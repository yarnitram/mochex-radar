"""Point-in-time feature extraction from normalized swaps; no provider access or approval."""

from datetime import datetime, timedelta
from decimal import Decimal

from cluster_radar.intelligence.research import Swap, first_observations, require_utc
from cluster_radar.signals.research import FeatureEvidence

FEATURE_VERSION = "swap-features-v1"
ONE = Decimal(1)


def extract_swap_features(swaps: list[Swap], mint: str, as_of: datetime, lookback: timedelta,
                          history_start: datetime) -> dict:
    """Derive the swap-observable features from two adjacent windows.

    Current window is (as_of-lookback, as_of]; prior is (as_of-2*lookback, as_of-lookback].
    history_start declares the earliest time the supplied swap set is claimed complete for
    this mint. If it does not cover both windows, features are unavailable, never zero.
    Derived values are hypotheses over observed swaps only: "new" means not observed in the
    supplied history, and buyer independence remains unverified.

    Produces: dump `buyer_exhaustion` (relative decline in observed buy USD) and pump
    `new_owner_participation` (share of current buyers not previously observed).
    """
    require_utc(as_of, history_start)
    if not mint or lookback <= timedelta(0):
        raise ValueError("mint and positive lookback required")
    current_start, prior_start = as_of - lookback, as_of - 2 * lookback
    unavailable: dict[str, str] = {}
    if history_start > prior_start:
        reason = "insufficient_history_coverage"
        return {"version": FEATURE_VERSION, "as_of": as_of, "features": {},
                "unavailable": {"buyer_exhaustion": reason, "new_owner_participation": reason},
                "independence_status": "UNVERIFIED"}
    first, sources, _ = first_observations(swaps, as_of)
    rows = [s for s in first.values() if s.mint == mint and history_start <= s.event_at <= as_of]
    current = [s for s in rows if current_start < s.event_at <= as_of]
    prior = [s for s in rows if prior_start < s.event_at <= current_start]
    before = [s for s in rows if s.event_at <= current_start]
    features: dict[str, FeatureEvidence] = {}

    def evidence(name: str, value: Decimal, used: list[Swap], start: datetime) -> FeatureEvidence:
        refs = tuple(sorted({f"swap:{s.signature}/{'.'.join(map(str, s.instruction_path))}/{s.swap_index}" for s in used}))
        source = "derived:" + "+".join(sorted({src for s in used for src in sources[s.identity]}))
        return FeatureEvidence(name, value, start, as_of, as_of, source, f"swap-flow:{mint}", refs)

    prior_buys = [s for s in prior if s.side == "BUY"]
    current_buys = [s for s in current if s.side == "BUY"]
    if any(s.usd_amount is None for s in prior_buys + current_buys):
        unavailable["buyer_exhaustion"] = "incomplete_usd_coverage"
    elif not prior_buys or sum(s.usd_amount for s in prior_buys) <= 0:
        unavailable["buyer_exhaustion"] = "no_prior_buying_baseline"
    else:
        ratio = sum((s.usd_amount for s in current_buys), Decimal(0)) / sum(s.usd_amount for s in prior_buys)
        features["buyer_exhaustion"] = evidence("buyer_exhaustion", min(ONE, max(Decimal(0), ONE - ratio)),
                                                prior_buys + current_buys, prior_start)

    buyers = {s.owner for s in current_buys}
    if not buyers:
        unavailable["new_owner_participation"] = "no_current_buyers"
    else:
        seen = {s.owner for s in before}
        new_count = len(buyers - seen)
        features["new_owner_participation"] = evidence(
            "new_owner_participation", Decimal(new_count) / Decimal(len(buyers)), current_buys + before, current_start)
    return {"version": FEATURE_VERSION, "as_of": as_of, "features": features,
            "unavailable": unavailable, "independence_status": "UNVERIFIED"}
