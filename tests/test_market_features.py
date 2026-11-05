from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mochex_radar.futures_feed import Candle
from mochex_radar.market_features import BTC_ASSET_ID, compute_features, replay_features

STEP = timedelta(minutes=15)
START = datetime(2026, 1, 1, tzinfo=UTC)
SOL = "cex:mexc-usdt-futures:SOL_USDT"


def series(asset=SOL, count=25, base=100, volume=10, **kw):
    out = []
    for i in range(count):
        open_time = START + i * STEP
        price = Decimal(base) + i
        out.append(Candle(asset, "15m", open_time, open_time + STEP, open_time + STEP + timedelta(seconds=1),
                          price, price + 2, price - 1, price + 1, Decimal(volume)))
    return out


def now_after(candles):
    return candles[-1].close_time + timedelta(seconds=5)


def test_features_values_on_known_series():
    candles = series()
    out = compute_features(candles, series(BTC_ASSET_ID, base=1000), SOL, "15m", now_after(candles))
    f = out["features"]
    assert out["status"] == "ok" and out["feature_version"] == "core-features-v1" and out["provisional"] is True
    # Every TR is 3 (range 3, prior close within range), so ATR is 3 and latest range/ATR is 1.
    assert Decimal(f["atr"]) == 3 and Decimal(f["range_atr"]) == 1 and f["volatility_state"] == "normal"
    assert Decimal(f["relative_volume"]) == 1
    assert f["structure_state"] == "range"  # close equals, not exceeds, the prior high
    up = candles[:-1] + [replace(candles[-1], close=candles[-1].close + 5, high=candles[-1].high + 5)]
    assert compute_features(up, [], SOL, "15m", now_after(up))["features"]["structure_state"] == "breakout_up"
    down = candles[:-1] + [replace(candles[-1], close=Decimal(1), low=Decimal(1))]
    assert compute_features(down, [], SOL, "15m", now_after(down))["features"]["structure_state"] == "breakdown"
    # Asset +4/103-ish vs BTC +4/1020-ish: asset outperforms.
    assert Decimal(f["relative_strength"]) > 0 and out["relative_strength_reason"] is None
    assert len(out["input_open_times"]) == 21


def test_volume_spike_and_compression_states():
    candles = series()
    spike = candles[:-1] + [replace(candles[-1], volume=Decimal(50))]
    assert Decimal(compute_features(spike, [], SOL, "15m", now_after(spike))["features"]["relative_volume"]) == 5
    tight = candles[:-1] + [replace(candles[-1], open=candles[-1].close, high=candles[-1].close + Decimal("0.2"), low=candles[-1].close - Decimal("0.2"))]
    assert compute_features(tight, [], SOL, "15m", now_after(tight))["features"]["volatility_state"] == "compressed"
    wide = candles[:-1] + [replace(candles[-1], high=candles[-1].close + 10, low=candles[-1].close - 10)]
    assert compute_features(wide, [], SOL, "15m", now_after(wide))["features"]["volatility_state"] == "expanding"


def test_fail_closed_on_gap_stale_lookback_and_invalid_data():
    candles = series()
    assert compute_features(candles[:20], [], SOL, "15m", now_after(candles[:20]))["reason"] == "insufficient_lookback"
    gapped = candles[:10] + candles[11:]
    out = compute_features(gapped, [], SOL, "15m", now_after(gapped))
    assert out["reason"] in ("gap_or_duplicate", "insufficient_lookback") and all(v is None for v in out["features"].values())
    gap21 = series(count=26)
    del gap21[12]
    assert compute_features(gap21, [], SOL, "15m", now_after(gap21))["reason"] == "gap_or_duplicate"
    stale = compute_features(candles, [], SOL, "15m", candles[-1].close_time + 3 * STEP)
    assert stale["reason"] == "stale_data" and stale["data_age_seconds"] == 3 * 900
    bad = candles[:-1] + [replace(candles[-1], high=Decimal(1))]
    assert compute_features(bad, [], SOL, "15m", now_after(bad))["reason"] == "invalid_price_or_volume"
    zero_volume = [replace(c, volume=Decimal(0)) for c in candles]
    assert compute_features(zero_volume, [], SOL, "15m", now_after(zero_volume))["features"]["relative_volume"] is None


def test_relative_strength_unavailable_without_aligned_btc_but_core_features_remain():
    candles = series()
    out = compute_features(candles, series(BTC_ASSET_ID, count=10), SOL, "15m", now_after(candles))
    assert out["status"] == "ok" and out["features"]["relative_strength"] is None
    assert out["relative_strength_reason"] == "btc_not_aligned" and out["features"]["atr"] is not None


def test_point_in_time_ignores_unretrieved_unclosed_and_later_revisions():
    candles = series()
    now = now_after(candles)
    late = replace(candles[-1], close=candles[-1].close + 500, high=candles[-1].high + 500,
                   retrieved_at=now + timedelta(hours=1))
    unseen = compute_features(candles + [late], [], SOL, "15m", now)
    assert unseen == compute_features(candles, [], SOL, "15m", now)
    future = replace(candles[-1], open_time=candles[-1].open_time + STEP, close_time=candles[-1].close_time + STEP,
                     retrieved_at=now)
    assert compute_features(candles + [future], [], SOL, "15m", now)["input_open_times"] == compute_features(candles, [], SOL, "15m", now)["input_open_times"]
    after = compute_features(candles + [late], [], SOL, "15m", now + timedelta(hours=1, minutes=1))
    assert after["data_as_of"] is not None


def test_replay_is_deterministic_and_other_assets_are_ignored():
    candles = series() + series("cex:mexc-usdt-futures:XRP_USDT", base=5000)
    decisions = [candles[19].close_time + timedelta(seconds=5), now_after(series())]
    first = replay_features(candles, [], SOL, "15m", decisions)
    assert first == replay_features(list(reversed(candles)), [], SOL, "15m", decisions)
    assert first[0]["reason"] == "insufficient_lookback" and first[1]["status"] == "ok"


def test_input_validation():
    with pytest.raises(ValueError, match="UTC"):
        compute_features([], [], SOL, "15m", datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="interval"):
        compute_features([], [], SOL, "5m", START)
    with pytest.raises(ValueError, match="UTC"):
        replay_features([], [], SOL, "15m", [datetime(2026, 1, 1)])
