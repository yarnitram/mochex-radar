import pytest

from mochex_radar.markets import CexMarket, CORE_BASES, core_markets


def test_core_universe_has_unique_venue_scoped_ids() -> None:
    markets = core_markets()
    assert tuple(market.base for market in markets) == CORE_BASES
    assert len({market.asset_id for market in markets}) == 7
    assert all(market.quote == "USDT" for market in markets)
    assert "BTC" not in CORE_BASES


def test_identical_symbol_on_other_venue_is_distinct() -> None:
    first = CexMarket("venue-a", "SOLUSDT", "SOL", "USDT")
    second = CexMarket("venue-b", "SOLUSDT", "SOL", "USDT")
    assert first.asset_id != second.asset_id


@pytest.mark.parametrize("venue,market_id", [("", "SOLUSDT"), ("venue-a", ""), ("bad:venue", "SOLUSDT")])
def test_invalid_market_identity_is_rejected(venue: str, market_id: str) -> None:
    with pytest.raises(ValueError):
        CexMarket(venue, market_id, "SOL", "USDT")
