from datetime import datetime, timedelta, timezone

import httpx
import pytest

from mochex_radar.futures_feed import FeedUnavailable, fetch_latest_closed, parse_latest_closed
from mochex_radar.markets import core_markets

MARKET = core_markets()[0]
NOW = datetime(2026, 11, 5, 12, 7, tzinfo=timezone.utc)
OPEN = int(NOW.timestamp() // 900 * 900)


def data(times: list[int]) -> dict:
    return {"time": times, "open": [100] * len(times), "high": [110] * len(times), "low": [90] * len(times), "close": [105] * len(times), "vol": [12.5] * len(times)}


def test_selects_last_closed_contract_candle() -> None:
    candle = parse_latest_closed(data([OPEN - 900, OPEN]), MARKET, "15m", NOW)
    assert candle.asset_id == "cex:mexc-usdt-futures:SOL_USDT"
    assert candle.open_time.timestamp() == OPEN - 900
    assert candle.to_dict()["close"] == "105"


def test_rejects_misaligned_invalid_or_stale_data() -> None:
    broken = data([OPEN - 900])
    broken["high"] = []
    with pytest.raises(ValueError):
        parse_latest_closed(broken, MARKET, "15m", NOW)
    broken = data([OPEN - 900])
    broken["high"] = [80]
    with pytest.raises(ValueError):
        parse_latest_closed(broken, MARKET, "15m", NOW)
    with pytest.raises(ValueError):
        parse_latest_closed(data([OPEN - 900 * 5]), MARKET, "15m", NOW)


@pytest.mark.asyncio
async def test_fetch_uses_futures_endpoint_and_interval() -> None:
    current = int(datetime.now(timezone.utc).timestamp() // 3600 * 3600)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.mexc.com"
        assert request.url.path == "/api/v1/contract/kline/SOL_USDT"
        assert request.url.params["interval"] == "Min60"
        assert int(request.url.params["end"]) - int(request.url.params["start"]) == 14400
        return httpx.Response(200, json={"success": True, "code": 0, "data": data([current - 3600, current])})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        candle = await fetch_latest_closed(MARKET, "1h", client)
    assert candle.open_time.timestamp() == current - 3600


@pytest.mark.asyncio
async def test_provider_failure_is_unavailable() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        with pytest.raises(FeedUnavailable):
            await fetch_latest_closed(MARKET, "15m", client)
