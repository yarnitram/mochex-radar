"""Read-only Solana wallet swap and funding history normalizer and bounded adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Literal

import httpx

from cluster_radar.intelligence.research import FundingEvidence, Swap, require_utc
from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.solana_authorities import decode_pubkey

HISTORY_PARSER_VERSION = "solana-wallet-history-v1"
FunderLabel = Literal["CEX", "NON_CEX", "UNKNOWN"]


@dataclass(frozen=True)
class NormalizedHistoryBatch:
    as_of: datetime
    swaps: tuple[Swap, ...]
    funding: tuple[FundingEvidence, ...]
    skipped_failed_tx_count: int
    excluded_future_count: int
    parser_version: str = field(default=HISTORY_PARSER_VERSION, init=False)
    complete_history_verified: bool = False
    security_status: str = field(default="UNKNOWN", init=False)
    approved_pump_watch: bool = field(default=False, init=False)


def _parse_positive_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("numeric string or number required")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid decimal value") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("positive finite decimal required")
    return parsed


def _parse_nonnegative_decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("boolean not allowed for decimal")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid decimal value") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("non-negative finite decimal required")
    return parsed


def normalize_enhanced_transactions(
    transactions: list[dict],
    *,
    target_mint: str,
    default_pool: str,
    known_at: datetime,
    as_of: datetime,
    source: str = "helius:enhanced-transactions:v0",
    funder_labels: dict[str, tuple[FunderLabel, datetime]] | None = None,
    min_funding_lamports: int = 1_000_000,
    complete_history_verified: bool = False,
) -> NormalizedHistoryBatch:
    require_utc(known_at, as_of)
    decode_pubkey(target_mint)
    decode_pubkey(default_pool)
    labels = funder_labels or {}

    swaps: list[Swap] = []
    funding: list[FundingEvidence] = []
    skipped_failed = 0
    excluded_future = 0

    for tx in transactions:
        if not isinstance(tx, dict):
            raise TypeError("transaction entry must be a dict")
        if tx.get("transactionError") is not None:
            skipped_failed += 1
            continue

        signature = tx.get("signature")
        if not isinstance(signature, str) or not signature.strip():
            raise ValueError("transaction signature required")
        timestamp = tx.get("timestamp")
        if type(timestamp) is not int or timestamp <= 0:
            raise ValueError("positive integer unix timestamp required")
        event_at = datetime.fromtimestamp(timestamp, tz=UTC)
        effective_known_at = max(event_at, known_at)

        if event_at > as_of or effective_known_at > as_of:
            excluded_future += 1
            continue

        token_transfers = tx.get("tokenTransfers") or []
        if not isinstance(token_transfers, list):
            raise TypeError("tokenTransfers must be a list")

        for idx, transfer in enumerate(token_transfers):
            if not isinstance(transfer, dict):
                raise TypeError("tokenTransfer must be a dict")
            if transfer.get("mint") != target_mint:
                continue
            from_user = transfer.get("fromUserAccount")
            to_user = transfer.get("toUserAccount")
            amount = _parse_positive_decimal(transfer.get("tokenAmount"))
            usd_val = _parse_nonnegative_decimal_or_none(transfer.get("usdValue"))
            pool_addr = transfer.get("pool") or default_pool
            decode_pubkey(pool_addr)

            if isinstance(to_user, str) and to_user and to_user != pool_addr:
                decode_pubkey(to_user)
                swaps.append(
                    Swap(
                        signature=signature,
                        instruction_path=(idx,),
                        swap_index=idx,
                        mint=target_mint,
                        pool=pool_addr,
                        owner=to_user,
                        side="BUY",
                        token_amount=amount,
                        usd_amount=usd_val,
                        event_at=event_at,
                        known_at=effective_known_at,
                        source=source,
                    )
                )
            elif isinstance(from_user, str) and from_user and from_user != pool_addr:
                decode_pubkey(from_user)
                swaps.append(
                    Swap(
                        signature=signature,
                        instruction_path=(idx,),
                        swap_index=idx,
                        mint=target_mint,
                        pool=pool_addr,
                        owner=from_user,
                        side="SELL",
                        token_amount=amount,
                        usd_amount=usd_val,
                        event_at=event_at,
                        known_at=effective_known_at,
                        source=source,
                    )
                )

        native_transfers = tx.get("nativeTransfers") or []
        if not isinstance(native_transfers, list):
            raise TypeError("nativeTransfers must be a list")

        for native in native_transfers:
            if not isinstance(native, dict):
                raise TypeError("nativeTransfer must be a dict")
            lamports = native.get("amount")
            if type(lamports) is not int or lamports < min_funding_lamports:
                continue
            funder = native.get("fromUserAccount")
            wallet = native.get("toUserAccount")
            if not isinstance(funder, str) or not isinstance(wallet, str) or funder == wallet:
                continue
            decode_pubkey(funder)
            decode_pubkey(wallet)
            if funder in labels:
                label, label_known_at = labels[funder]
            else:
                label, label_known_at = "UNKNOWN", effective_known_at
            funding.append(
                FundingEvidence(
                    wallet=wallet,
                    funder=funder,
                    signature=signature,
                    event_at=event_at,
                    known_at=effective_known_at,
                    label=label,
                    label_known_at=label_known_at,
                    source=source,
                )
            )

    return NormalizedHistoryBatch(
        as_of=as_of,
        swaps=tuple(swaps),
        funding=tuple(funding),
        skipped_failed_tx_count=skipped_failed,
        excluded_future_count=excluded_future,
        complete_history_verified=complete_history_verified,
    )


class SolanaHistoryAdapter:
    """Bounded read-only adapter for enhanced Solana address transaction history."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint_template: str,
        max_requests: int = 50,
    ) -> None:
        if "{address}" not in endpoint_template:
            raise ValueError("endpoint_template must contain {address} placeholder")
        if max_requests < 1:
            raise ValueError("positive max_requests required")
        self.client = client
        self.endpoint_template = endpoint_template
        self.max_requests = max_requests
        self.requests = 0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def fetch_address_transactions(self, address: str, *, limit: int = 50) -> list[dict]:
        decode_pubkey(address)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        async with self._lock:
            if self.requests >= self.max_requests:
                raise BudgetExceeded("Solana history request budget exhausted")
            await asyncio.sleep(max(0.0, self._next_at - monotonic()))
            self.requests += 1
            self._next_at = monotonic() + 1.1
            url = self.endpoint_template.format(address=address)
            try:
                response = await self.client.get(
                    url,
                    params={"limit": str(limit), "commitment": "finalized"},
                    timeout=10,
                )
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError("oversized history response")
                payload = response.json()
                if not isinstance(payload, list):
                    raise TypeError("expected list of enhanced transactions")
                return payload
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise ProviderUnavailable("Solana transaction history unavailable") from exc
