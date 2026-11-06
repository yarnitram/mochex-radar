"""Explainable point-in-time Solana token risk checks: SPL/Token-2022, stage liquidity, and holders."""

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from cluster_radar.discovery.identity import MarketStage
from cluster_radar.intelligence.research import require_utc
from cluster_radar.providers.solana_authorities import (
    TOKEN_2022,
    TOKEN_PROGRAM,
    _authority,
    decode_pubkey,
    encode_pubkey,
)
from cluster_radar.signals.rules import SecurityStatus

RULE_VERSION = "solana-token-risk-v1"
FRESHNESS_WINDOW = timedelta(minutes=15)
ZERO_PUBKEY = b"\x00" * 32

# Token-2022 TLV ExtensionType discriminants (spl-token-2022 extension::ExtensionType).
EXT_TRANSFER_FEE_CONFIG = 1
EXT_DEFAULT_ACCOUNT_STATE = 6
EXT_NON_TRANSFERABLE = 9
EXT_PERMANENT_DELEGATE = 12
EXT_TRANSFER_HOOK = 14


def _fresh_check(known_at: datetime, as_of: datetime) -> str | None:
    require_utc(known_at, as_of)
    if known_at > as_of:
        return "future_evidence"
    if as_of - known_at >= FRESHNESS_WINDOW:
        return "stale_evidence"
    return None


def _parse_coption_pubkey(raw: bytes, offset: int) -> tuple[str, str | None]:
    return _authority(raw, offset)


def parse_mint_and_extensions(owner: str, raw: bytes) -> dict:
    """Parse finalized SPL Token or Token-2022 mint bytes and evaluate extension risk.

    Unsupported owners, malformed base mints, uninitialized mints, unknown Token-2022
    extensions, or malformed TLV headers fail closed as UNKNOWN, never PASS.
    """
    decode_pubkey(owner)
    if owner not in (TOKEN_PROGRAM, TOKEN_2022):
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "program": "unsupported",
            "reason": "unsupported_owner",
            "mint_authority_status": "UNKNOWN",
            "freeze_authority_status": "UNKNOWN",
            "mint_authority": None,
            "freeze_authority": None,
            "extensions": [],
            "flags": ["unsupported_owner"],
        }
    if len(raw) < 82:
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "program": "spl-token" if owner == TOKEN_PROGRAM else "token-2022",
            "reason": "unsupported_mint_layout",
            "mint_authority_status": "UNKNOWN",
            "freeze_authority_status": "UNKNOWN",
            "mint_authority": None,
            "freeze_authority": None,
            "extensions": [],
            "flags": ["unsupported_mint_layout"],
        }
    if owner == TOKEN_PROGRAM and len(raw) != 82:
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "program": "spl-token",
            "reason": "unsupported_mint_layout",
            "mint_authority_status": "UNKNOWN",
            "freeze_authority_status": "UNKNOWN",
            "mint_authority": None,
            "freeze_authority": None,
            "extensions": [],
            "flags": ["unsupported_mint_layout"],
        }
    if raw[45] != 1:
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "program": "spl-token" if owner == TOKEN_PROGRAM else "token-2022",
            "reason": "uninitialized_or_invalid_mint",
            "mint_authority_status": "UNKNOWN",
            "freeze_authority_status": "UNKNOWN",
            "mint_authority": None,
            "freeze_authority": None,
            "extensions": [],
            "flags": ["uninitialized_or_invalid_mint"],
        }
    try:
        mint_status, mint_key = _authority(raw, 0)
        freeze_status, freeze_key = _authority(raw, 46)
    except ValueError:
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "program": "spl-token" if owner == TOKEN_PROGRAM else "token-2022",
            "reason": "invalid_authority_layout",
            "mint_authority_status": "UNKNOWN",
            "freeze_authority_status": "UNKNOWN",
            "mint_authority": None,
            "freeze_authority": None,
            "extensions": [],
            "flags": ["invalid_authority_layout"],
        }

    flags: list[str] = []
    if mint_status == "PRESENT":
        flags.append("mint_authority_present")
    if freeze_status == "PRESENT":
        flags.append("freeze_authority_present")

    extensions: list[dict] = []
    blocked = False
    caution = bool(flags)
    unknown = False

    if owner == TOKEN_2022 and len(raw) > 82:
        # Token-2022 pads Mint to 165 bytes (Multisig length), sets byte 165 = AccountType::Mint (1),
        # and stores TLV entries from byte 166 onward.
        if len(raw) < 166 or any(b != 0 for b in raw[82:165]) or raw[165] != 1:
            return {
                "status": SecurityStatus.UNKNOWN.value,
                "program": "token-2022",
                "reason": "invalid_tlv_layout",
                "mint_authority_status": mint_status,
                "freeze_authority_status": freeze_status,
                "mint_authority": mint_key,
                "freeze_authority": freeze_key,
                "extensions": [],
                "flags": [*flags, "invalid_tlv_layout"],
            }
        cursor = 166
        while cursor < len(raw):
            if len(raw) - cursor < 4:
                unknown = True
                flags.append("invalid_tlv_layout")
                break
            ext_type = int.from_bytes(raw[cursor:cursor + 2], "little")
            ext_len = int.from_bytes(raw[cursor + 2:cursor + 4], "little")
            cursor += 4
            if ext_type == 0 and ext_len == 0 and all(b == 0 for b in raw[cursor:]):
                break
            if cursor + ext_len > len(raw):
                unknown = True
                flags.append("invalid_tlv_layout")
                break
            body = raw[cursor:cursor + ext_len]
            cursor += ext_len

            if ext_type == EXT_TRANSFER_FEE_CONFIG:
                if len(body) != 108:
                    unknown = True
                    flags.append("invalid_transfer_fee_layout")
                    continue
                try:
                    cfg_state, cfg_auth = _parse_coption_pubkey(body, 0)
                    withdraw_state, withdraw_auth = _parse_coption_pubkey(body, 36)
                except ValueError:
                    unknown = True
                    flags.append("invalid_transfer_fee_layout")
                    continue
                older_bps = int.from_bytes(body[88:90], "little")
                newer_bps = int.from_bytes(body[106:108], "little")
                max_bps = max(older_bps, newer_bps)
                if max_bps > 10_000:
                    unknown = True
                    flags.append("invalid_transfer_fee_bps")
                    continue
                ext_status = "PASS"
                if max_bps > 500:
                    blocked = True
                    ext_status = "BLOCK"
                    flags.append("excessive_transfer_fee")
                elif max_bps > 0 or cfg_state == "PRESENT":
                    caution = True
                    ext_status = "CAUTION"
                    flags.append("transfer_fee_active_or_mutable")
                extensions.append({
                    "type": "TransferFeeConfig",
                    "status": ext_status,
                    "max_fee_bps": max_bps,
                    "config_authority_status": cfg_state,
                    "config_authority": cfg_auth,
                    "withdraw_authority_status": withdraw_state,
                    "withdraw_authority": withdraw_auth,
                })
            elif ext_type == EXT_DEFAULT_ACCOUNT_STATE:
                if len(body) != 1 or body[0] not in (1, 2):
                    unknown = True
                    flags.append("invalid_default_account_state")
                    continue
                frozen = body[0] == 2
                if frozen:
                    blocked = True
                    flags.append("default_account_state_frozen")
                extensions.append({
                    "type": "DefaultAccountState",
                    "status": "BLOCK" if frozen else "PASS",
                    "default_state": "frozen" if frozen else "initialized",
                })
            elif ext_type == EXT_NON_TRANSFERABLE:
                if len(body) != 0:
                    unknown = True
                    flags.append("invalid_non_transferable_layout")
                    continue
                blocked = True
                flags.append("non_transferable_mint")
                extensions.append({"type": "NonTransferable", "status": "BLOCK"})
            elif ext_type == EXT_PERMANENT_DELEGATE:
                if len(body) == 32:
                    has_delegate = body != ZERO_PUBKEY
                    delegate = encode_pubkey(body) if has_delegate else None
                elif len(body) == 36:
                    try:
                        state, delegate = _parse_coption_pubkey(body, 0)
                        has_delegate = state == "PRESENT"
                    except ValueError:
                        unknown = True
                        flags.append("invalid_permanent_delegate_layout")
                        continue
                else:
                    unknown = True
                    flags.append("invalid_permanent_delegate_layout")
                    continue
                if has_delegate:
                    blocked = True
                    flags.append("permanent_delegate_present")
                extensions.append({
                    "type": "PermanentDelegate",
                    "status": "BLOCK" if has_delegate else "PASS",
                    "delegate": delegate,
                })
            elif ext_type == EXT_TRANSFER_HOOK:
                if len(body) != 64:
                    unknown = True
                    flags.append("invalid_transfer_hook_layout")
                    continue
                auth_bytes, prog_bytes = body[:32], body[32:64]
                has_auth = auth_bytes != ZERO_PUBKEY
                has_prog = prog_bytes != ZERO_PUBKEY
                if has_prog:
                    blocked = True
                    ext_status = "BLOCK"
                    flags.append("active_transfer_hook_program")
                elif has_auth:
                    caution = True
                    ext_status = "CAUTION"
                    flags.append("mutable_transfer_hook_authority")
                else:
                    ext_status = "PASS"
                extensions.append({
                    "type": "TransferHook",
                    "status": ext_status,
                    "authority": encode_pubkey(auth_bytes) if has_auth else None,
                    "program_id": encode_pubkey(prog_bytes) if has_prog else None,
                })
            else:
                unknown = True
                flags.append(f"unsupported_token_2022_extension:{ext_type}")
                extensions.append({
                    "type": f"Unsupported({ext_type})",
                    "status": "UNKNOWN",
                })

    status = (
        SecurityStatus.BLOCK.value
        if blocked
        else SecurityStatus.UNKNOWN.value
        if unknown
        else SecurityStatus.CAUTION.value
        if caution
        else SecurityStatus.PASS.value
    )
    return {
        "status": status,
        "program": "spl-token" if owner == TOKEN_PROGRAM else "token-2022",
        "reason": "evaluated",
        "mint_authority_status": mint_status,
        "freeze_authority_status": freeze_status,
        "mint_authority": mint_key,
        "freeze_authority": freeze_key,
        "extensions": extensions,
        "flags": flags,
    }


@dataclass(frozen=True)
class MintRiskEvidence:
    owner: str
    raw_base64: str
    known_at: datetime
    source: str

    def __post_init__(self) -> None:
        require_utc(self.known_at)
        if not self.owner or not self.source:
            raise ValueError("owner and source required")


@dataclass(frozen=True)
class LiquidityRiskEvidence:
    stage: MarketStage
    known_at: datetime
    source: str
    dex_liquidity_usd: Decimal | None = None
    sell_depth_2pct_usd: Decimal | None = None
    curve_quote_reserve_usd: Decimal | None = None
    graduation_progress: Decimal | None = None

    def __post_init__(self) -> None:
        require_utc(self.known_at)
        if not isinstance(self.stage, MarketStage) or not self.source:
            raise ValueError("valid stage and source required")
        if self.stage is MarketStage.CURVE and (
            self.dex_liquidity_usd is not None or self.sell_depth_2pct_usd is not None
        ):
            raise ValueError("curve liquidity evidence cannot carry DEX pool fields")
        if self.stage is MarketStage.DEX and (
            self.curve_quote_reserve_usd is not None or self.graduation_progress is not None
        ):
            raise ValueError("DEX liquidity evidence cannot carry bonding-curve fields")
        for value in (
            self.dex_liquidity_usd,
            self.sell_depth_2pct_usd,
            self.curve_quote_reserve_usd,
        ):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("USD liquidity measurements must be finite and nonnegative")
        if self.graduation_progress is not None and (
            not self.graduation_progress.is_finite()
            or not Decimal(0) <= self.graduation_progress <= Decimal(1)
        ):
            raise ValueError("graduation_progress must be in 0..1")


@dataclass(frozen=True)
class HolderRiskEvidence:
    known_at: datetime
    source: str
    top_1_unlocked_pct: Decimal
    top_10_unlocked_pct: Decimal
    excluded_known_accounts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.known_at)
        if not self.source:
            raise ValueError("holder source required")
        if (
            not self.top_1_unlocked_pct.is_finite()
            or not self.top_10_unlocked_pct.is_finite()
            or not Decimal(0) <= self.top_1_unlocked_pct <= self.top_10_unlocked_pct <= Decimal(100)
        ):
            raise ValueError("holder concentration percentages must satisfy 0 <= top_1 <= top_10 <= 100")


def evaluate_stage_liquidity(
    evidence: LiquidityRiskEvidence | None,
    *,
    as_of: datetime,
    min_dex_liquidity_usd: Decimal = Decimal(10000),
    block_dex_liquidity_usd: Decimal = Decimal(2500),
    min_sell_depth_2pct_usd: Decimal = Decimal(2000),
    block_sell_depth_2pct_usd: Decimal = Decimal(500),
    min_curve_reserve_usd: Decimal = Decimal(2500),
    block_curve_reserve_usd: Decimal = Decimal(500),
) -> dict:
    require_utc(as_of)
    if evidence is None:
        return {"status": SecurityStatus.UNKNOWN.value, "reason": "missing_liquidity_evidence", "flags": []}
    freshness_issue = _fresh_check(evidence.known_at, as_of)
    if freshness_issue:
        return {"status": SecurityStatus.UNKNOWN.value, "reason": freshness_issue, "flags": [freshness_issue]}

    flags: list[str] = []
    if evidence.stage is MarketStage.CURVE:
        if evidence.curve_quote_reserve_usd is None or evidence.graduation_progress is None:
            return {
                "status": SecurityStatus.UNKNOWN.value,
                "stage": "CURVE",
                "reason": "incomplete_curve_evidence",
                "flags": ["incomplete_curve_evidence"],
            }
        if evidence.curve_quote_reserve_usd < block_curve_reserve_usd:
            flags.append("critical_low_curve_reserve")
            status = SecurityStatus.BLOCK.value
        elif evidence.curve_quote_reserve_usd < min_curve_reserve_usd:
            flags.append("low_curve_reserve")
            status = SecurityStatus.CAUTION.value
        else:
            status = SecurityStatus.PASS.value
        return {
            "status": status,
            "stage": "CURVE",
            "reason": "evaluated",
            "curve_quote_reserve_usd": evidence.curve_quote_reserve_usd,
            "graduation_progress": evidence.graduation_progress,
            "dex_liquidity_status": "NOT_APPLICABLE",
            "flags": flags,
        }

    if evidence.dex_liquidity_usd is None or evidence.sell_depth_2pct_usd is None:
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "stage": "DEX",
            "reason": "incomplete_dex_liquidity_or_depth",
            "flags": ["incomplete_dex_liquidity_or_depth"],
        }
    blocked = False
    caution = False
    if evidence.dex_liquidity_usd < block_dex_liquidity_usd:
        blocked = True
        flags.append("critical_low_dex_liquidity")
    elif evidence.dex_liquidity_usd < min_dex_liquidity_usd:
        caution = True
        flags.append("low_dex_liquidity")
    if evidence.sell_depth_2pct_usd < block_sell_depth_2pct_usd:
        blocked = True
        flags.append("critical_low_sell_depth")
    elif evidence.sell_depth_2pct_usd < min_sell_depth_2pct_usd:
        caution = True
        flags.append("low_sell_depth")
    status = (
        SecurityStatus.BLOCK.value
        if blocked
        else SecurityStatus.CAUTION.value
        if caution
        else SecurityStatus.PASS.value
    )
    return {
        "status": status,
        "stage": "DEX",
        "reason": "evaluated",
        "dex_liquidity_usd": evidence.dex_liquidity_usd,
        "sell_depth_2pct_usd": evidence.sell_depth_2pct_usd,
        "flags": flags,
    }


def evaluate_holder_concentration(
    evidence: HolderRiskEvidence | None,
    *,
    as_of: datetime,
    block_top_1_pct: Decimal = Decimal(30),
    caution_top_1_pct: Decimal = Decimal(15),
    block_top_10_pct: Decimal = Decimal(70),
    caution_top_10_pct: Decimal = Decimal(50),
) -> dict:
    require_utc(as_of)
    if evidence is None:
        return {"status": SecurityStatus.UNKNOWN.value, "reason": "missing_holder_evidence", "flags": []}
    freshness_issue = _fresh_check(evidence.known_at, as_of)
    if freshness_issue:
        return {"status": SecurityStatus.UNKNOWN.value, "reason": freshness_issue, "flags": [freshness_issue]}
    flags: list[str] = []
    blocked = False
    caution = False
    if evidence.top_1_unlocked_pct >= block_top_1_pct:
        blocked = True
        flags.append("critical_top_1_concentration")
    elif evidence.top_1_unlocked_pct >= caution_top_1_pct:
        caution = True
        flags.append("elevated_top_1_concentration")
    if evidence.top_10_unlocked_pct >= block_top_10_pct:
        blocked = True
        flags.append("critical_top_10_concentration")
    elif evidence.top_10_unlocked_pct >= caution_top_10_pct:
        caution = True
        flags.append("elevated_top_10_concentration")
    status = (
        SecurityStatus.BLOCK.value
        if blocked
        else SecurityStatus.CAUTION.value
        if caution
        else SecurityStatus.PASS.value
    )
    return {
        "status": status,
        "reason": "evaluated",
        "top_1_unlocked_pct": evidence.top_1_unlocked_pct,
        "top_10_unlocked_pct": evidence.top_10_unlocked_pct,
        "excluded_known_accounts": list(evidence.excluded_known_accounts),
        "flags": flags,
    }


def evaluate_mint_risk(evidence: MintRiskEvidence | None, *, as_of: datetime) -> dict:
    require_utc(as_of)
    if evidence is None:
        return {"status": SecurityStatus.UNKNOWN.value, "reason": "missing_mint_evidence", "flags": []}
    freshness_issue = _fresh_check(evidence.known_at, as_of)
    if freshness_issue:
        return {"status": SecurityStatus.UNKNOWN.value, "reason": freshness_issue, "flags": [freshness_issue]}
    try:
        raw = base64.b64decode(evidence.raw_base64, validate=True)
        return parse_mint_and_extensions(evidence.owner, raw)
    except (ValueError, TypeError):
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "reason": "invalid_mint_encoding",
            "flags": ["invalid_mint_encoding"],
        }


def evaluate_token_risk(
    *,
    as_of: datetime,
    mint_evidence: MintRiskEvidence | None,
    liquidity_evidence: LiquidityRiskEvidence | None,
    holder_evidence: HolderRiskEvidence | None,
    vendor_verdict: Literal["SAFE", "WARN", "DANGER"] | None = None,
) -> dict:
    """Combine independent checks; a vendor verdict alone never produces PASS."""
    require_utc(as_of)
    mint_check = evaluate_mint_risk(mint_evidence, as_of=as_of)
    liquidity_check = evaluate_stage_liquidity(liquidity_evidence, as_of=as_of)
    holder_check = evaluate_holder_concentration(holder_evidence, as_of=as_of)

    checks = {
        "mint_and_extensions": mint_check,
        "stage_liquidity": liquidity_check,
        "holder_concentration": holder_check,
    }
    statuses = [c["status"] for c in checks.values()]
    flags = [flag for c in checks.values() for flag in c.get("flags", [])]
    if vendor_verdict == "DANGER":
        flags.append("vendor_flagged_danger")
    elif vendor_verdict == "WARN":
        flags.append("vendor_flagged_warn")

    if SecurityStatus.BLOCK.value in statuses:
        overall = SecurityStatus.BLOCK.value
    elif SecurityStatus.UNKNOWN.value in statuses:
        overall = SecurityStatus.UNKNOWN.value
    elif SecurityStatus.CAUTION.value in statuses or vendor_verdict in ("WARN", "DANGER"):
        overall = SecurityStatus.CAUTION.value
    else:
        overall = SecurityStatus.PASS.value

    return {
        "rule_version": RULE_VERSION,
        "as_of": as_of,
        "security_status": overall,
        "checks": checks,
        "flags": flags,
        "vendor_verdict_note": "vendor_score_never_sufficient_for_pass",
    }
