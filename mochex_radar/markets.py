"""Venue scoped market identities and the initial configured universe."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CexMarket:
    venue: str
    market_id: str
    base: str
    quote: str

    def __post_init__(self) -> None:
        if not all((self.venue, self.market_id, self.base, self.quote)):
            raise ValueError("market identity fields must be nonempty")
        if any(":" in value for value in (self.venue, self.market_id)):
            raise ValueError("venue and market ID must not contain ':'")

    @property
    def asset_id(self) -> str:
        return f"cex:{self.venue}:{self.market_id}"


CORE_BASES = ("SOL", "XRP", "DOGE", "LINK", "SUI", "AVAX", "ADA")


def core_markets(venue: str = "mexc-usdt-futures") -> tuple[CexMarket, ...]:
    """Configured MEXC USDT futures contracts, pending listing verification."""
    markets = tuple(
        CexMarket(venue=venue, market_id=f"{base}_USDT", base=base, quote="USDT")
        for base in CORE_BASES
    )
    if len({market.asset_id for market in markets}) != len(markets):
        raise ValueError("duplicate market identity")
    return markets
