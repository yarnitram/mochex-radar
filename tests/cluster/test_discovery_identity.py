from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cluster_radar.discovery.identity import Candidate, MarketStage

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def candidate(**overrides):
    values = {
        "mint": "mint-a", "stage": MarketStage.DEX, "pool_id": "pool-a",
        "token_created_at": NOW - timedelta(days=2),
        "pool_created_at": NOW - timedelta(hours=1),
        "market_cap_usd": Decimal(10000), "fdv_usd": Decimal(30000),
        "dex_liquidity_usd": Decimal(5000), "source": "fixture", "known_at": NOW,
    }
    values.update(overrides)
    return Candidate(**values)


def test_token_and_pool_ages_and_values_are_distinct():
    item = candidate()
    assert item.token_age(NOW) == timedelta(days=2)
    assert item.pool_age(NOW) == timedelta(hours=1)
    assert item.market_cap_usd != item.fdv_usd


def test_curve_has_no_dex_pool_or_liquidity():
    item = candidate(stage=MarketStage.CURVE, pool_id=None, pool_created_at=None,
                     dex_liquidity_usd=None)
    assert item.identity == ("mint-a", MarketStage.CURVE, None)
    assert item.pool_age(NOW) is None
    with pytest.raises(ValueError):
        candidate(stage=MarketStage.CURVE, pool_id=None, pool_created_at=None)


def test_migration_keeps_mint_but_changes_stage_identity():
    curve = candidate(stage=MarketStage.CURVE, pool_id=None, pool_created_at=None,
                      dex_liquidity_usd=None)
    dex = candidate()
    assert curve.mint == dex.mint
    assert curve.identity != dex.identity


def test_unknown_and_future_information_do_not_create_age():
    item = candidate(known_at=NOW + timedelta(minutes=1))
    assert item.token_age(NOW) is None
    assert candidate(token_created_at=None).token_age(NOW) is None
    assert candidate(pool_created_at=None).pool_age(NOW) is None


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal(-1)])
def test_invalid_measurements_rejected(bad):
    with pytest.raises(ValueError):
        candidate(fdv_usd=bad)
