"""Point-in-time normalized swap metrics and possible funding relationships."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal


def require_utc(*times: datetime) -> None:
    if any(value.tzinfo is None or value.utcoffset() != timedelta(0) for value in times):
        raise ValueError("UTC timestamps required")


@dataclass(frozen=True)
class Swap:
    signature: str
    instruction_path: tuple[int, ...]
    swap_index: int
    mint: str
    pool: str
    owner: str
    side: Literal["BUY", "SELL"]
    token_amount: Decimal
    usd_amount: Decimal | None
    event_at: datetime
    known_at: datetime
    source: str

    def __post_init__(self):
        require_utc(self.event_at, self.known_at)
        if self.known_at < self.event_at:
            raise ValueError("swap cannot be known before its event")
        if not all((self.signature, self.mint, self.pool, self.owner, self.source)):
            raise ValueError("identity and provenance required")
        if (not self.instruction_path or any(type(n) is not int or n < 0 for n in self.instruction_path)
                or type(self.swap_index) is not int or self.swap_index < 0 or self.side not in ("BUY", "SELL")):
            raise ValueError("invalid swap identity or side")
        if not self.token_amount.is_finite() or self.token_amount <= 0:
            raise ValueError("positive finite token amount required")
        if self.usd_amount is not None and (not self.usd_amount.is_finite() or self.usd_amount < 0):
            raise ValueError("USD amount must be finite and nonnegative")

    @property
    def identity(self):
        return self.signature, self.instruction_path, self.swap_index


@dataclass(frozen=True)
class FundingEvidence:
    wallet: str
    funder: str
    signature: str
    event_at: datetime
    known_at: datetime
    label: Literal["CEX", "NON_CEX", "UNKNOWN"]
    label_known_at: datetime
    source: str

    def __post_init__(self):
        require_utc(self.event_at, self.known_at, self.label_known_at)
        if self.known_at < self.event_at or not all((self.wallet,self.funder,self.signature,self.source)):
            raise ValueError("funding identity and causal timestamps required")
        if self.label not in ("CEX", "NON_CEX", "UNKNOWN"):
            raise ValueError("invalid funder classification")


def funding_groups(records: list[FundingEvidence], as_of: datetime) -> dict:
    """Only explicit, timely, non-conflicting NON_CEX labels can form a group."""
    require_utc(as_of)
    visible = [r for r in records if r.known_at <= as_of and r.event_at <= as_of]
    funders: dict[str, set[str]] = {}
    labels: dict[str, set[str]] = {}
    for row in visible:
        funders.setdefault(row.wallet,set()).add(row.funder)
        label = row.label if row.label_known_at <= as_of else "UNKNOWN"
        labels.setdefault(row.funder,set()).add(label)
    by_funder: dict[str, set[str]] = {}
    for row in visible:
        if len(funders[row.wallet]) == 1 and labels[row.funder] == {"NON_CEX"}:
            by_funder.setdefault(row.funder,set()).add(row.wallet)
    groups = []
    for funder, wallets in sorted(by_funder.items()):
        if len(wallets) < 2:
            continue
        evidence = [r for r in visible if r.funder == funder and r.wallet in wallets]
        groups.append({"funder":funder,"wallets":sorted(wallets),
            "signatures":sorted({r.signature for r in evidence}),
            "sources":sorted({r.source for r in evidence}),
            "conclusion":"potential_shared_funding_only"})
    return {"as_of":as_of,"groups":groups,"ownership_verified":False,
            "conflicting_wallets":sorted(w for w,f in funders.items() if len(f)>1)}


def swap_metrics(swaps: list[Swap], mint: str, as_of: datetime, lookback: timedelta) -> dict:
    require_utc(as_of)
    if not mint or lookback <= timedelta(0):
        raise ValueError("mint and positive lookback required")
    # Resolve first eligible observation per event before applying mint/window filters.
    # Later corrections cannot rewrite earlier knowledge; conflicting first records fail.
    first: dict[tuple, Swap] = {}
    sources: dict[tuple, set[str]] = {}
    revisions = 0
    for row in sorted((s for s in swaps if s.known_at <= as_of), key=lambda s:s.known_at):
        previous = first.get(row.identity)
        if previous is None:
            first[row.identity] = row
            sources[row.identity] = {row.source}
        else:
            content = (row.mint,row.pool,row.owner,row.side,row.token_amount,row.usd_amount,row.event_at)
            old = (previous.mint,previous.pool,previous.owner,previous.side,previous.token_amount,previous.usd_amount,previous.event_at)
            if content != old:
                if previous.known_at == row.known_at:
                    raise ValueError("conflicting swap observation")
                revisions += 1
            else:
                sources[row.identity].add(row.source)
    rows = [s for s in first.values() if s.mint == mint and as_of-lookback < s.event_at <= as_of]
    complete_usd = bool(rows) and all(s.usd_amount is not None for s in rows)
    buys = sum((s.usd_amount for s in rows if s.side == "BUY"), Decimal(0)) if complete_usd else None
    sells = sum((s.usd_amount for s in rows if s.side == "SELL"), Decimal(0)) if complete_usd else None
    return {"mint":mint,"as_of":as_of,"lookback_seconds":lookback.total_seconds(),
        "swap_count":len(rows),"observed_buyers":len({s.owner for s in rows if s.side=="BUY"}),
        "observed_sellers":len({s.owner for s in rows if s.side=="SELL"}),
        "buy_usd":buys,"sell_usd":sells,"net_usd":buys-sells if complete_usd else None,
        "buy_sell_ratio":buys/sells if complete_usd and sells else None,
        "usd_coverage_complete":complete_usd,"buyer_independence":"UNVERIFIED",
        "sources":sorted({source for row in rows for source in sources[row.identity]}),
        "ignored_later_revisions":revisions}
