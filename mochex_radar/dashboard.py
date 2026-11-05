"""Dashboard snapshots use persisted candles, never trigger exchange requests."""

from datetime import datetime, timedelta, timezone

import psycopg

from mochex_radar.markets import core_markets


def core_snapshot(dsn: str | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = {}
    markets = core_markets()
    if dsn:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            stored = conn.execute(
                """SELECT DISTINCT ON (market_id) market_id, close_price, open_price,
                          close_time, retrieved_at
                   FROM market_candles WHERE venue=%s AND market_id=ANY(%s) AND interval=%s
                   ORDER BY market_id, open_time DESC""",
                ("mexc-usdt-futures", [m.market_id for m in markets], "15m"),
            ).fetchall()
        rows = {row[0]: row for row in stored}
    output = []
    for market in markets:
        row = rows.get(market.market_id)
        status = "missing"
        if row:
            age = now - row[3]
            status = "current" if timedelta(0) <= age <= timedelta(minutes=30) else "stale"
            if row[4] > now:
                status = "stale"
        output.append({
            "asset_id": market.asset_id, "base": market.base, "quote": market.quote,
            "market_id": market.market_id, "status": status,
            "close": str(row[1]) if row else None,
            "candle_return": str(row[1] / row[2] - 1) if row and row[2] > 0 else None,
            "close_time": row[3].isoformat() if row else None,
            "retrieved_at": row[4].isoformat() if row else None,
        })
    return {"data_status": "stored_observations" if dsn else "storage_disabled",
            "as_of": now.isoformat(), "interval": "15m", "markets": output}
