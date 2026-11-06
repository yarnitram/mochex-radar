"""Read-only finalized Solana holder concentration evidence via getTokenSupply & getTokenLargestAccounts."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import monotonic

import httpx

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.solana_authorities import RPC_URL, decode_pubkey
from cluster_radar.security.token_risk import (
    HolderRiskEvidence,
    SecurityStatus,
    evaluate_holder_concentration,
)

HOLDER_SOURCE = "solana-public-mainnet:getTokenLargestAccounts:finalized"
HOLDER_PARSER_VERSION = "solana-token-account-concentration-v2"


@dataclass(frozen=True)
class HolderSnapshotObservation:
    mint: str
    known_at: datetime
    slot: int
    reason: str
    response_hash: str
    total_supply_raw: int | None
    top_1_unlocked_pct: Decimal | None
    top_10_unlocked_pct: Decimal | None
    concentration_status: str
    concentration_flags: tuple[str, ...]
    holder_evidence: HolderRiskEvidence | None
    excluded_accounts_count: int = 0
    source: str = field(default=HOLDER_SOURCE, init=False)
    parser_version: str = field(default=HOLDER_PARSER_VERSION, init=False)
    security_status: str = field(default="UNKNOWN", init=False)
    approved_pump_watch: bool = field(default=False, init=False)
    evidence_scope: str = field(default="token_accounts_only", init=False)
    ownership_verified: bool = field(default=False, init=False)
    locks_verified: bool = field(default=False, init=False)


def _validate_rpc_envelope(payload: dict, expected_id: int) -> tuple[int, object]:
    if (
        not isinstance(payload, dict)
        or payload.get("jsonrpc") != "2.0"
        or type(payload.get("id")) is not int
        or payload["id"] != expected_id
        or "error" in payload
    ):
        raise ValueError("invalid RPC envelope")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TypeError("missing RPC result")
    context = result.get("context")
    if not isinstance(context, dict):
        raise TypeError("missing RPC context")
    slot = context.get("slot")
    if type(slot) is not int or not 0 <= slot < 2**63:
        raise ValueError("invalid RPC slot")
    return slot, result.get("value")


def _parse_raw_amount(value: object) -> int:
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError("amount must be a base-10 integer string")
    return int(value)


def parse_holder_concentration(
    mint: str,
    supply_payload: dict,
    largest_payload: dict,
    *,
    response_hash: str,
    known_at: datetime,
    excluded_token_accounts: set[str] | frozenset[str] = frozenset(),
) -> HolderSnapshotObservation:
    decode_pubkey(mint)
    for account in excluded_token_accounts:
        decode_pubkey(account)

    supply_slot, supply_val = _validate_rpc_envelope(supply_payload, 1)
    largest_slot, largest_val = _validate_rpc_envelope(largest_payload, 2)

    if supply_slot != largest_slot:
        return HolderSnapshotObservation(
            mint=mint,
            known_at=known_at,
            slot=max(supply_slot, largest_slot),
            reason="holder_rpc_slot_mismatch",
            response_hash=response_hash,
            total_supply_raw=None,
            top_1_unlocked_pct=None,
            top_10_unlocked_pct=None,
            concentration_status=SecurityStatus.UNKNOWN.value,
            concentration_flags=("holder_rpc_slot_mismatch",),
            holder_evidence=None,
        )

    if not isinstance(supply_val, dict) or not isinstance(largest_val, list):
        raise TypeError("invalid supply or largest accounts value")

    total_supply_raw = _parse_raw_amount(supply_val.get("amount"))
    if total_supply_raw <= 0:
        return HolderSnapshotObservation(
            mint=mint,
            known_at=known_at,
            slot=supply_slot,
            reason="zero_token_supply",
            response_hash=response_hash,
            total_supply_raw=0,
            top_1_unlocked_pct=None,
            top_10_unlocked_pct=None,
            concentration_status=SecurityStatus.UNKNOWN.value,
            concentration_flags=("zero_token_supply",),
            holder_evidence=None,
        )

    unlocked_amounts: list[int] = []
    excluded_list: list[str] = []
    for entry in largest_val:
        if not isinstance(entry, dict):
            raise TypeError("invalid largest account entry")
        address = entry.get("address")
        if not isinstance(address, str):
            raise TypeError("missing token account address")
        decode_pubkey(address)
        amount_raw = _parse_raw_amount(entry.get("amount"))
        if address in excluded_token_accounts:
            excluded_list.append(address)
            continue
        unlocked_amounts.append(amount_raw)

    unlocked_amounts.sort(reverse=True)
    if not unlocked_amounts:
        return HolderSnapshotObservation(
            mint=mint,
            known_at=known_at,
            slot=supply_slot,
            reason="no_unlocked_holder_accounts",
            response_hash=response_hash,
            total_supply_raw=total_supply_raw,
            top_1_unlocked_pct=None,
            top_10_unlocked_pct=None,
            concentration_status=SecurityStatus.UNKNOWN.value,
            concentration_flags=("no_unlocked_holder_accounts",),
            holder_evidence=None,
            excluded_accounts_count=len(excluded_list),
        )

    try:
        supply_dec = Decimal(total_supply_raw)
        top_1_pct = (Decimal(unlocked_amounts[0]) * Decimal(100)) / supply_dec
        top_10_pct = (Decimal(sum(unlocked_amounts[:10])) * Decimal(100)) / supply_dec
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError("invalid holder percentage arithmetic") from exc

    if top_1_pct > Decimal(100) or top_10_pct > Decimal(100):
        return HolderSnapshotObservation(
            mint=mint,
            known_at=known_at,
            slot=supply_slot,
            reason="holder_sum_exceeds_supply",
            response_hash=response_hash,
            total_supply_raw=total_supply_raw,
            top_1_unlocked_pct=None,
            top_10_unlocked_pct=None,
            concentration_status=SecurityStatus.UNKNOWN.value,
            concentration_flags=("holder_sum_exceeds_supply",),
            holder_evidence=None,
            excluded_accounts_count=len(excluded_list),
        )

    evidence = HolderRiskEvidence(
        known_at=known_at,
        source=HOLDER_SOURCE,
        top_1_unlocked_pct=top_1_pct,
        top_10_unlocked_pct=top_10_pct,
        excluded_known_accounts=tuple(sorted(excluded_list)),
    )
    evaluated = evaluate_holder_concentration(evidence, as_of=known_at)
    if evaluated["status"] == SecurityStatus.PASS.value:
        evaluated = {**evaluated, "status": SecurityStatus.UNKNOWN.value,
                     "reason": "token_account_only_ownership_and_locks_unverified",
                     "flags": [*evaluated.get("flags", []), "holder_ownership_unverified"]}
    return HolderSnapshotObservation(
        mint=mint,
        known_at=known_at,
        slot=supply_slot,
        reason=evaluated["reason"],
        response_hash=response_hash,
        total_supply_raw=total_supply_raw,
        top_1_unlocked_pct=top_1_pct,
        top_10_unlocked_pct=top_10_pct,
        concentration_status=evaluated["status"],
        concentration_flags=tuple(evaluated["flags"]),
        # Raw account balances are not verified wallet/controller risk evidence.
        holder_evidence=None,
        excluded_accounts_count=len(excluded_list),
    )


class SolanaHolderConcentration:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        rpc_url: str = RPC_URL,
        max_requests: int = 100,
    ) -> None:
        if max_requests < 2:
            raise ValueError("at least 2 RPC requests required per holder check")
        self.client = client
        self.rpc_url = rpc_url
        self.max_requests = max_requests
        self.requests = 0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def _post_rpc(self, req_id: int, method: str, mint: str) -> tuple[dict, bytes]:
        if self.requests >= self.max_requests:
            raise BudgetExceeded("Solana holder request budget exhausted")
        await asyncio.sleep(max(0.0, self._next_at - monotonic()))
        self.requests += 1
        self._next_at = monotonic() + 1.1
        response = await self.client.post(
            self.rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": [mint, {"commitment": "finalized"}],
            },
            timeout=10,
        )
        response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise ValueError("oversized RPC response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("expected RPC object")
        return payload, response.content

    async def check(
        self,
        mint: str,
        *,
        excluded_token_accounts: set[str] | frozenset[str] = frozenset(),
    ) -> HolderSnapshotObservation:
        decode_pubkey(mint)
        async with self._lock:
            if self.requests + 2 > self.max_requests:
                raise BudgetExceeded("Solana holder request budget exhausted")
            try:
                supply_payload, supply_bytes = await self._post_rpc(1, "getTokenSupply", mint)
                largest_payload, largest_bytes = await self._post_rpc(
                    2, "getTokenLargestAccounts", mint
                )
                digest = hashlib.sha256(supply_bytes + b"\n" + largest_bytes).hexdigest()
                return parse_holder_concentration(
                    mint,
                    supply_payload,
                    largest_payload,
                    response_hash=digest,
                    known_at=datetime.now(UTC),
                    excluded_token_accounts=excluded_token_accounts,
                )
            except BudgetExceeded:
                raise
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
                raise ProviderUnavailable("Solana holder concentration unavailable") from exc
