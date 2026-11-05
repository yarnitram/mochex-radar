"""PostgreSQL persistence for closed candles and collector cycle status."""

from dataclasses import dataclass
from datetime import datetime

import psycopg

from mochex_radar.futures_feed import Candle

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_candles (
    venue text NOT NULL,
    market_id text NOT NULL,
    interval text NOT NULL,
    open_time timestamptz NOT NULL,
    close_time timestamptz NOT NULL,
    retrieved_at timestamptz NOT NULL,
    open_price numeric NOT NULL,
    high_price numeric NOT NULL,
    low_price numeric NOT NULL,
    close_price numeric NOT NULL,
    volume numeric NOT NULL,
    source text NOT NULL,
    PRIMARY KEY (venue, market_id, interval, open_time),
    CHECK (close_time > open_time),
    CHECK (low_price > 0 AND low_price <= open_price AND low_price <= close_price),
    CHECK (high_price >= open_price AND high_price >= close_price),
    CHECK (volume >= 0)
);
CREATE INDEX IF NOT EXISTS market_candles_recent_idx ON market_candles (venue, market_id, interval, open_time DESC);
CREATE TABLE IF NOT EXISTS collector_cycles (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    stored_count integer NOT NULL,
    provider_failures integer NOT NULL,
    CHECK (finished_at >= started_at),
    CHECK (stored_count >= 0 AND provider_failures >= 0)
);
"""


@dataclass(frozen=True)
class CycleResult:
    started_at: datetime
    finished_at: datetime
    stored_count: int
    provider_failures: int


def initialize_database(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(SCHEMA)


def store_cycle(dsn: str, candles: list[Candle], started_at: datetime, finished_at: datetime, provider_failures: int) -> int:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        inserted = 0
        for candle in candles:
            _, venue, market_id = candle.asset_id.split(":", 2)
            cursor = conn.execute(
                """INSERT INTO market_candles
                (venue, market_id, interval, open_time, close_time, retrieved_at,
                 open_price, high_price, low_price, close_price, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (venue, market_id, interval, open_time) DO NOTHING""",
                (venue, market_id, candle.interval, candle.open_time, candle.close_time,
                 candle.retrieved_at, candle.open, candle.high, candle.low, candle.close,
                 candle.volume, candle.source),
            )
            inserted += cursor.rowcount
        conn.execute(
            "INSERT INTO collector_cycles (started_at, finished_at, stored_count, provider_failures) VALUES (%s, %s, %s, %s)",
            (started_at, finished_at, inserted, provider_failures),
        )
    return inserted


def latest_cycle(dsn: str) -> dict[str, object] | None:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        row = conn.execute(
            "SELECT started_at, finished_at, stored_count, provider_failures FROM collector_cycles ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return {"started_at": row[0].isoformat(), "finished_at": row[1].isoformat(),
            "stored_count": row[2], "provider_failures": row[3]}


def recent_btc_candles(dsn: str) -> list[Candle]:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(
            """SELECT open_time, close_time, retrieved_at, open_price, high_price,
                      low_price, close_price, volume, source
               FROM market_candles
               WHERE venue = %s AND market_id = %s AND interval = %s
               ORDER BY open_time DESC LIMIT 4""",
            ("mexc-usdt-futures", "BTC_USDT", "15m"),
        ).fetchall()
    return [Candle("cex:mexc-usdt-futures:BTC_USDT", "15m", *row) for row in reversed(rows)]


def store_stream_candle(dsn: str, candle: Candle) -> bool:
    _, venue, market_id = candle.asset_id.split(":", 2)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        cursor = conn.execute(
            """INSERT INTO market_candles
            (venue, market_id, interval, open_time, close_time, retrieved_at,
             open_price, high_price, low_price, close_price, volume, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (venue, market_id, interval, open_time) DO NOTHING""",
            (venue, market_id, candle.interval, candle.open_time, candle.close_time,
             candle.retrieved_at, candle.open, candle.high, candle.low, candle.close,
             candle.volume, candle.source),
        )
    return cursor.rowcount == 1

def recent_candles(dsn: str, market_id: str, interval: str, as_of: datetime, limit: int = 21,
                   venue: str = "mexc-usdt-futures") -> list[Candle]:
    """Stored candles closed and retrieved at or before as_of, oldest first."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(
            """SELECT open_time, close_time, retrieved_at, open_price, high_price,
                      low_price, close_price, volume, source
               FROM market_candles
               WHERE venue = %s AND market_id = %s AND interval = %s
                 AND close_time <= %s AND retrieved_at <= %s
               ORDER BY open_time DESC LIMIT %s""",
            (venue, market_id, interval, as_of, as_of, limit),
        ).fetchall()
    return [Candle(f"cex:{venue}:{market_id}", interval, *row) for row in reversed(rows)]


def store_candles(dsn: str, candles: list[Candle]) -> int:
    """Idempotently store candles without writing a collector cycle record; returns newly inserted rows."""
    inserted = 0
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        for candle in candles:
            _, venue, market_id = candle.asset_id.split(":", 2)
            cursor = conn.execute(
                """INSERT INTO market_candles
                (venue, market_id, interval, open_time, close_time, retrieved_at,
                 open_price, high_price, low_price, close_price, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (venue, market_id, interval, open_time) DO NOTHING""",
                (venue, market_id, candle.interval, candle.open_time, candle.close_time,
                 candle.retrieved_at, candle.open, candle.high, candle.low, candle.close,
                 candle.volume, candle.source),
            )
            inserted += cursor.rowcount
    return inserted