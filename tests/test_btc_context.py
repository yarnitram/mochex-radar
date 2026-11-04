from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mochex_radar.btc_context import classify
from mochex_radar.futures_feed import Candle

NOW = datetime(2026, 11, 5, 12, 5, tzinfo=timezone.utc)


def candles(last_close: str = "100") -> list[Candle]:
    first_open = NOW - timedelta(hours=1, minutes=5)
    result = []
    for index in range(4):
        opened = first_open + timedelta(minutes=15 * index)
        close = Decimal(last_close) if index == 3 else Decimal("100")
        result.append(Candle("cex:mexc-usdt-futures:BTC_USDT", "15m", opened,
                             opened + timedelta(minutes=15), NOW, Decimal("100"),
                             max(Decimal("100"), close), min(Decimal("100"), close),
                             close, Decimal("10")))
    return result


@pytest.mark.parametrize("last_close,state", [
    ("97.99", "blocked"), ("98", "blocked"), ("98.5", "caution"),
    ("99", "caution"), ("100", "neutral"), ("101", "supportive"),
])
def test_provisional_return_states(last_close: str, state: str) -> None:
    result = classify(candles(last_close), NOW)
    assert result["state"] == state
    assert result["provisional"] is True
    assert len(result["input_open_times"]) == 4
    assert result["data_age_seconds"] == 300


def test_missing_gap_and_stale_are_unknown() -> None:
    assert classify([], NOW)["state"] == "unknown"
    broken = candles()
    broken[2] = replace(broken[2], open_time=broken[2].open_time + timedelta(minutes=1))
    assert classify(broken, NOW)["reason"] == "gap_or_duplicate"
    assert classify(candles(), NOW + timedelta(minutes=31))["reason"] == "stale_or_future_data"


def test_non_btc_identity_is_unknown() -> None:
    broken = candles()
    broken[0] = replace(broken[0], asset_id="cex:mexc-usdt-futures:SOL_USDT")
    assert classify(broken, NOW)["reason"] == "invalid_identity_or_time"
