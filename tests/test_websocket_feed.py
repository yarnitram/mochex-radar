import json
from datetime import datetime, timedelta, timezone

import pytest

from mochex_radar.websocket_feed import Rollover, TARGETS, consume, parse_update, subscriptions

NOW = datetime(2026, 11, 5, 12, 5, tzinfo=timezone.utc)
START = int((NOW - timedelta(minutes=5)).timestamp())


def update(start: int = START, symbol: str = "SOL_USDT", interval: str = "Min15", close: str = "101") -> str:
    return json.dumps({"channel": "push.kline", "symbol": symbol, "ts": int(NOW.timestamp() * 1000),
                       "data": {"symbol": symbol, "interval": interval, "t": start,
                                "o": "100", "h": "110", "l": "90", "c": close, "q": "12"}})


def test_subscriptions_cover_only_expected_targets() -> None:
    messages = [json.loads(item) for item in subscriptions()]
    assert len(messages) == len(TARGETS) == 15
    assert all(item["method"] == "sub.kline" for item in messages)
    assert sum(item["param"]["symbol"] == "BTC_USDT" for item in messages) == 1


def test_parse_and_rollover_finalization() -> None:
    current = parse_update(update(), NOW)
    assert current is not None and current.asset_id == "cex:mexc-usdt-futures:SOL_USDT"
    rollover = Rollover()
    assert rollover.accept(current) is None
    revised = parse_update(update(close="102"), NOW)
    assert rollover.accept(revised) is None
    later = parse_update(update(start=START + 900), NOW + timedelta(minutes=11))
    finalized = rollover.accept(later)
    assert finalized is not None and finalized.close == 102
    assert rollover.accept(current) is None


def test_invalid_unknown_and_gapped_events() -> None:
    assert parse_update(update(symbol="UNKNOWN_USDT"), NOW) is None
    assert parse_update(update(interval="Min1"), NOW) is None
    assert parse_update("not-json", NOW) is None
    assert parse_update(update(close="NaN"), NOW) is None
    rollover = Rollover()
    assert rollover.accept(parse_update(update(), NOW)) is None
    gap = parse_update(update(start=START + 1800), NOW + timedelta(minutes=31))
    assert rollover.accept(gap) is None


@pytest.mark.asyncio
async def test_consume_subscribes_and_saves_on_rollover() -> None:
    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send(self, message):
            self.sent.append(json.loads(message))

        def __aiter__(self):
            async def messages():
                current_start = int(datetime.now(timezone.utc).timestamp() // 900 * 900)
                yield update(start=current_start - 900)
                yield update(start=current_start)
            return messages()

    saved = []

    async def save(candle):
        saved.append(candle)

    socket = FakeSocket()
    await consume(socket, save)
    assert len(socket.sent) == 15
    assert len(saved) == 1
