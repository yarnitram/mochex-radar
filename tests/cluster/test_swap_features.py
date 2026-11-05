from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cluster_radar.intelligence.research import Swap
from cluster_radar.signals.features import extract_swap_features
from cluster_radar.signals.research import score_research

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
LOOK = timedelta(minutes=15)
START = NOW - timedelta(hours=1)


def swap(sig, minutes_ago, owner="w1", side="BUY", usd="100", **changes):
    event = NOW - timedelta(minutes=minutes_ago)
    base = Swap(sig, (0,), 0, "mint-a", "pool-a", owner, side, Decimal(1),
                None if usd is None else Decimal(usd), event, event + timedelta(seconds=1), "fixture")
    return replace(base, **changes)


def extract(swaps, **kw):
    return extract_swap_features(swaps, "mint-a", kw.get("as_of", NOW), LOOK, kw.get("history_start", START))


def test_buyer_exhaustion_is_relative_decline_clamped_and_attributed():
    result = extract([swap("p1", 20, usd="200"), swap("c1", 5, usd="50")])
    feature = result["features"]["buyer_exhaustion"]
    assert feature.value == Decimal("0.75") and feature.window_end == NOW
    assert "swap:p1/0/0" in feature.references and feature.independence_group == "swap-flow:mint-a"
    assert result["independence_status"] == "UNVERIFIED"
    growth = extract([swap("p1", 20, usd="100"), swap("c1", 5, usd="400")])
    assert growth["features"]["buyer_exhaustion"].value == 0
    silent = extract([swap("p1", 20, usd="100")])
    assert silent["features"]["buyer_exhaustion"].value == 1


def test_new_owner_participation_uses_only_observed_history():
    result = extract([swap("h1", 40, owner="old"), swap("c1", 5, owner="old"), swap("c2", 4, owner="new"),
                      swap("c3", 3, owner="new"), swap("p1", 20, owner="old", usd="10")])
    assert result["features"]["new_owner_participation"].value == Decimal("0.5")
    sellers_count_as_seen = extract([swap("h1", 40, owner="x", side="SELL"), swap("c1", 5, owner="x")])
    assert sellers_count_as_seen["features"]["new_owner_participation"].value == 0


def test_unavailable_never_becomes_zero():
    assert extract([], history_start=NOW - timedelta(minutes=10))["unavailable"]["buyer_exhaustion"] == "insufficient_history_coverage"
    assert extract([], history_start=NOW - timedelta(minutes=10))["features"] == {}
    missing_usd = extract([swap("p1", 20), swap("c1", 5, usd=None)])
    assert missing_usd["unavailable"]["buyer_exhaustion"] == "incomplete_usd_coverage"
    assert "buyer_exhaustion" not in missing_usd["features"]
    none = extract([swap("c1", 5, side="SELL")])
    assert none["unavailable"] == {"buyer_exhaustion": "no_prior_buying_baseline", "new_owner_participation": "no_current_buyers"}


def test_point_in_time_dedup_and_mint_filtering():
    base = [swap("p1", 20, usd="100"), swap("c1", 5, usd="50")]
    late = swap("c2", 4, usd="900", known_at=NOW + timedelta(seconds=1))
    other = swap("c3", 4, usd="900", mint="mint-b")
    dup = replace(base[1], source="fixture-2")
    result = extract(base + [late, other, dup])
    feature = result["features"]["buyer_exhaustion"]
    assert feature.value == Decimal("0.5") and feature.source == "derived:fixture+fixture-2"
    assert extract(base + [late], as_of=NOW + timedelta(minutes=1))["features"]["buyer_exhaustion"].value == 0


def test_features_feed_scoring_but_stay_incomplete_and_unapproved():
    result = extract([swap("p1", 20, usd="200"), swap("c1", 5, usd="50")])
    dump = score_research("dump", [result["features"]["buyer_exhaustion"]], as_of=NOW, window_end=NOW)
    assert dump["score"] is None and dump["observed_points"] == 15 and dump["approved_pump_watch"] is False
    with pytest.raises(ValueError, match="UTC"):
        extract_swap_features([], "mint-a", datetime(2026, 1, 1), LOOK, START)
