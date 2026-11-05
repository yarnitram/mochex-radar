"""Provider-neutral Solana candidate identity and stage-aware measurements."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum


class MarketStage(str, Enum):
    CURVE = "CURVE"
    DEX = "DEX"


@dataclass(frozen=True)
class Candidate:
    mint: str
    stage: MarketStage
    pool_id: str | None
    token_created_at: datetime | None
    pool_created_at: datetime | None
    market_cap_usd: Decimal | None
    fdv_usd: Decimal | None
    dex_liquidity_usd: Decimal | None
    source: str
    known_at: datetime

    def __post_init__(self) -> None:
        if not self.mint or not self.source:
            raise ValueError("mint and source are required")
        for instant in (self.token_created_at, self.pool_created_at, self.known_at):
            if instant is not None and (instant.tzinfo is None or instant.utcoffset() != timedelta(0)):
                raise ValueError("timestamps must be UTC")
        if self.stage is MarketStage.DEX and not self.pool_id:
            raise ValueError("DEX candidate requires pool_id")
        if self.stage is MarketStage.CURVE and (self.pool_id or self.pool_created_at or self.dex_liquidity_usd is not None):
            raise ValueError("curve candidate cannot carry DEX pool measurements")
        for value in (self.market_cap_usd, self.fdv_usd, self.dex_liquidity_usd):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("measurements must be nonnegative finite decimals")

    @property
    def identity(self) -> tuple[str, MarketStage, str | None]:
        return self.mint, self.stage, self.pool_id

    def token_age(self, as_of: datetime) -> timedelta | None:
        return _age(self.token_created_at, as_of, self.known_at)

    def pool_age(self, as_of: datetime) -> timedelta | None:
        if self.stage is MarketStage.CURVE:
            return None
        return _age(self.pool_created_at, as_of, self.known_at)


def _age(created_at: datetime | None, as_of: datetime, known_at: datetime) -> timedelta | None:
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be UTC")
    if known_at > as_of or created_at is None or created_at > as_of:
        return None
    return as_of - created_at
