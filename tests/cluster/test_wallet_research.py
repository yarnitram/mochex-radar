from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cluster_radar.intelligence.research import FundingEvidence, Swap, funding_groups, swap_metrics
from cluster_radar.signals.research import WEIGHTS, FeatureEvidence, score_research

NOW = datetime(2026,1,1,12,tzinfo=UTC)


def swap(**changes):
    base = Swap("tx-a",(0,1),0,"mint-a","pool-a","wallet-a","BUY",Decimal(1),Decimal(100),
                NOW-timedelta(minutes=1),NOW,"fixture")
    return replace(base,**changes)


def test_swap_identity_preserves_inner_swaps_and_distinct_owner_count():
    first=swap()
    second=swap(instruction_path=(0,2),pool="pool-b")
    metrics=swap_metrics([first,replace(first,source="fixture-2"),second],"mint-a",NOW,timedelta(minutes=15))
    assert metrics["swap_count"] == 2
    assert metrics["observed_buyers"] == 1
    assert metrics["net_usd"] == 200
    assert metrics["sources"] == ["fixture","fixture-2"]
    assert metrics["buy_sell_ratio"] is None
    assert metrics["buyer_independence"] == "UNVERIFIED"


def test_point_in_time_revisions_missing_usd_and_conflicts():
    first=swap()
    correction=replace(first,usd_amount=Decimal(999),known_at=NOW+timedelta(minutes=1))
    assert swap_metrics([correction,first],"mint-a",NOW,timedelta(minutes=15))["net_usd"] == 100
    later=swap_metrics([correction,first],"mint-a",NOW+timedelta(minutes=1),timedelta(minutes=15))
    assert later["net_usd"] == 100
    assert later["ignored_later_revisions"] == 1
    unknown=swap(signature="tx-b",usd_amount=None)
    assert swap_metrics([first,unknown],"mint-a",NOW,timedelta(minutes=15))["buy_usd"] is None
    with pytest.raises(ValueError,match="conflicting"):
        swap_metrics([first,replace(first,owner="different")],"mint-a",NOW,timedelta(minutes=15))


def funding(wallet,label="NON_CEX",**changes):
    return replace(FundingEvidence(wallet,"funder-a","tx-"+wallet,NOW-timedelta(days=1),NOW,
                                   label,NOW,"fixture"),**changes)


def test_funding_groups_exclude_cex_future_unknown_and_conflicting_labels():
    left,right=funding("a"),funding("b")
    result=funding_groups([left,right],NOW)
    assert result["groups"][0]["wallets"] == ["a","b"]
    assert result["ownership_verified"] is False
    for bad in [funding("b","CEX"),funding("b","UNKNOWN"),funding("b",label_known_at=NOW+timedelta(days=1))]:
        assert funding_groups([left,bad],NOW)["groups"] == []
    conflict=replace(right,funder="funder-b")
    assert funding_groups([left,right,conflict],NOW)["conflicting_wallets"] == ["b"]
    assert funding_groups([left,right],NOW-timedelta(seconds=1))["groups"] == []


def features(mode,value=Decimal(1),group_prefix="independent-"):
    return [FeatureEvidence(name,value,NOW-timedelta(minutes=15),NOW,NOW,"fixture",group_prefix+name,("ref:"+name,)) for name in WEIGHTS[mode]]


def test_missing_features_are_unknown_not_zero_and_complete_zero_is_measured():
    partial=score_research("pump",features("pump")[:1],as_of=NOW,window_end=NOW)
    assert partial["score"] is None
    assert partial["observed_points"] == 25
    assert partial["coverage_fraction"] == Decimal("0.25")
    assert partial["approved_pump_watch"] is False
    complete=score_research("pump",features("pump",Decimal(0)),as_of=NOW,window_end=NOW)
    assert complete["score"] == 0 and complete["missing_features"] == []


def test_dump_correlations_and_shared_references_are_collapsed_transitively():
    independent=features("dump")
    assert score_research("dump",independent,as_of=NOW,window_end=NOW)["research_threshold_met"] is True
    correlated=[replace(f,independence_group="same") for f in independent]
    result=score_research("dump",correlated,as_of=NOW,window_end=NOW)
    assert result["score"] == 100 and result["warning_groups"] == 1
    assert result["research_threshold_met"] is False
    shared=[replace(f,references=("ref:shared",)) for f in independent]
    assert score_research("dump",shared,as_of=NOW,window_end=NOW)["warning_groups"] == 1
    chain=[replace(f,references=refs) for f,refs in zip(independent,[("a",),("a","b"),("b","c"),("c","d"),("d",)],strict=True)]
    assert score_research("dump",chain,as_of=NOW,window_end=NOW)["warning_groups"] == 1
    assert result["alerts_enabled"] is False


def test_future_stale_mismatched_and_duplicate_features_fail_closed():
    data=features("pump")
    data[0]=replace(data[0],known_at=NOW+timedelta(seconds=1))
    result=score_research("pump",data,as_of=NOW,window_end=NOW)
    assert result["score"] is None and result["excluded_features"][data[0].name] == "future_knowledge"
    assert score_research("pump",features("pump"),as_of=NOW+timedelta(minutes=15),window_end=NOW)["score"] is None
    assert score_research("pump",features("pump"),as_of=NOW,window_end=NOW-timedelta(seconds=1))["score"] is None
    with pytest.raises(ValueError,match="duplicate"):
        score_research("pump",data+[data[0]],as_of=NOW,window_end=NOW)
