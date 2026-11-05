"""Read-only finalized mint authority evidence, never a complete security verdict."""

import asyncio
import base64
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic

import httpx

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable

RPC_URL = "https://api.mainnet.solana.com"
SOURCE = "solana-public-mainnet:getAccountInfo:finalized"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def decode_pubkey(value: str) -> bytes:
    if not isinstance(value, str) or not 32 <= len(value) <= 44:
        raise ValueError("invalid public key")
    number = 0
    for char in value:
        if char not in ALPHABET:
            raise ValueError("invalid public key")
        number = number * 58 + ALPHABET.index(char)
    result = b"\0" * (len(value) - len(value.lstrip("1")))
    result += number.to_bytes((number.bit_length() + 7) // 8, "big")
    if len(result) != 32:
        raise ValueError("public key must decode to 32 bytes")
    return result


def encode_pubkey(value: bytes) -> str:
    if len(value) != 32:
        raise ValueError("public key must contain 32 bytes")
    number = int.from_bytes(value, "big")
    output = ""
    while number:
        number, digit = divmod(number, 58)
        output = ALPHABET[digit] + output
    return "1" * (len(value) - len(value.lstrip(b"\0"))) + output


@dataclass(frozen=True)
class AuthorityObservation:
    mint: str
    known_at: datetime
    slot: int
    owner: str | None
    reason: str
    response_hash: str
    mint_authority_status: str = "UNKNOWN"
    freeze_authority_status: str = "UNKNOWN"
    mint_authority: str | None = None
    freeze_authority: str | None = None
    source: str = field(default=SOURCE, init=False)
    parser_version: str = field(default="spl-mint-authorities-v1", init=False)
    security_status: str = field(default="UNKNOWN", init=False)
    approved_pump_watch: bool = field(default=False, init=False)


def _authority(data: bytes, offset: int) -> tuple[str, str | None]:
    tag = int.from_bytes(data[offset:offset + 4], "little")
    if tag == 0:
        return "DISABLED", None
    if tag == 1:
        return "PRESENT", encode_pubkey(data[offset + 4:offset + 36])
    raise ValueError("invalid COption tag")


def parse_account(mint: str, payload: dict, response_hash: str, known_at: datetime) -> AuthorityObservation:
    if payload.get("jsonrpc") != "2.0" or type(payload.get("id")) is not int or payload["id"] != 1 or "error" in payload:
        raise ValueError("invalid RPC envelope")
    result = payload["result"]
    slot = result["context"]["slot"]
    if type(slot) is not int or not 0 <= slot < 2**63:
        raise ValueError("invalid RPC slot")
    value = result["value"]
    fields = {"mint": mint, "known_at": known_at, "slot": slot, "response_hash": response_hash}
    if value is None:
        return AuthorityObservation(**fields, owner=None, reason="account_missing")
    owner = value["owner"]
    decode_pubkey(owner)
    if type(value["executable"]) is not bool:
        raise ValueError("invalid executable flag")
    if owner != TOKEN_PROGRAM:
        reason = "token_2022_extensions_not_evaluated" if owner == TOKEN_2022 else "unsupported_owner"
        return AuthorityObservation(**fields, owner=owner, reason=reason)
    if value["executable"]:
        return AuthorityObservation(**fields, owner=owner, reason="executable_account")
    encoded = value["data"]
    if not isinstance(encoded, list) or len(encoded) != 2 or encoded[1] != "base64":
        raise ValueError("expected full base64 account")
    raw = base64.b64decode(encoded[0], validate=True)
    if len(raw) != 82:
        return AuthorityObservation(**fields, owner=owner, reason="unsupported_mint_layout")
    if raw[45] != 1:
        return AuthorityObservation(**fields, owner=owner, reason="uninitialized_or_invalid_mint")
    try:
        mint_status, mint_key = _authority(raw, 0)
        freeze_status, freeze_key = _authority(raw, 46)
    except ValueError:
        return AuthorityObservation(**fields, owner=owner, reason="invalid_authority_layout")
    return AuthorityObservation(**fields, owner=owner, reason="partial_authority_evidence",
        mint_authority_status=mint_status, freeze_authority_status=freeze_status,
        mint_authority=mint_key, freeze_authority=freeze_key)


class SolanaAuthorities:
    def __init__(self, client: httpx.AsyncClient, *, max_requests: int = 100):
        if max_requests < 1:
            raise ValueError("positive request ceiling required")
        self.client = client
        self.max_requests = max_requests
        self.requests = 0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def check(self, mint: str) -> AuthorityObservation:
        decode_pubkey(mint)
        async with self._lock:
            if self.requests >= self.max_requests:
                raise BudgetExceeded("Solana authority request budget exhausted")
            await asyncio.sleep(max(0, self._next_at - monotonic()))
            self.requests += 1
            self._next_at = monotonic() + 1.1
            try:
                response = await self.client.post(RPC_URL, json={"jsonrpc":"2.0", "id":1,
                    "method":"getAccountInfo", "params":[mint,{"encoding":"base64", "commitment":"finalized"}]}, timeout=10)
                response.raise_for_status()
                if len(response.content) > 1_000_000:
                    raise ValueError("oversized RPC response")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("expected RPC object")
                return parse_account(mint, payload, hashlib.sha256(response.content).hexdigest(), datetime.now(UTC))
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
                raise ProviderUnavailable("Solana authority evidence unavailable") from exc
