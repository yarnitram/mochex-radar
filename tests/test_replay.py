from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mochex_radar.futures_feed import Candle
from mochex_radar.replay import replay_btc_context


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def candle(index: int, *, retrieved_lag: int = 0, close: str = "100") -> Candle:
    opened = START + timedelta(minutes=15 * index)
    closed = opened + timedelta(minutes=15)
    price = Decimal(close)
    return Candle(
        "cex:mexc-usdt-futures:BTC_USDT", "15m", opened, closed,
        closed + timedelta(minutes=retrieved_lag), Decimal("100"),
        max(price, Decimal("100")), min(price, Decimal("100")), price, Decimal("1"),
    )


def test_replay_hides_future_retrieval_and_future_closure():
    candles = [candle(i) for i in range(3)] + [candle(3, retrieved_lag=5, close="97")]
    early = START + timedelta(hours=1)
    results = replay_btc_context(candles, [early, early + timedelta(minutes=5)])
    assert results[0].state == "unknown"
    assert results[0].reason == "insufficient_data"
    assert results[1].state == "blocked"
    assert len(results[1].input_open_times) == 4


def test_replay_uses_first_seen_revision():
    candles = [candle(i) for i in range(4)]
    revision = candle(3, retrieved_lag=2, close="50")
    result = replay_btc_context(candles + [revision], [START + timedelta(hours=1, minutes=3)])[0]
    assert result.state == "neutral"


def test_replay_rejects_naive_decision_time():
    with pytest.raises(ValueError):
        replay_btc_context([], [datetime(2026, 1, 1)])
