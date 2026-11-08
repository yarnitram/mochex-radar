import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cluster_radar.discovery.identity import MarketStage
from cluster_radar.providers.solana_authorities import (
    TOKEN_2022,
    TOKEN_PROGRAM,
    decode_pubkey,
)
from cluster_radar.security.token_risk import (
    EXT_DEFAULT_ACCOUNT_STATE,
    EXT_NON_TRANSFERABLE,
    EXT_PERMANENT_DELEGATE,
    EXT_TRANSFER_FEE_CONFIG,
    EXT_TRANSFER_HOOK,
    HolderRiskEvidence,
    LiquidityRiskEvidence,
    MintRiskEvidence,
    evaluate_holder_concentration,
    evaluate_stage_liquidity,
    evaluate_token_risk,
    parse_mint_and_extensions,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
KEY_A = "So11111111111111111111111111111111111111112"
KEY_BYTES = decode_pubkey(KEY_A)


def _coption(pubkey: bytes | None) -> bytes:
    if pubkey is None:
        return (0).to_bytes(4, "little") + b"\x00" * 32
    return (1).to_bytes(4, "little") + pubkey


def _base_mint(mint_auth: bytes | None = None, freeze_auth: bytes | None = None, initialized: int = 1) -> bytes:
    out = bytearray(82)
    out[0:36] = _coption(mint_auth)
    out[36:44] = (1_000_000).to_bytes(8, "little")
    out[44] = 6
    out[45] = initialized
    out[46:82] = _coption(freeze_auth)
    return bytes(out)


def _tlv(ext_type: int, body: bytes) -> bytes:
    return ext_type.to_bytes(2, "little") + len(body).to_bytes(2, "little") + body


def _token_2022_mint(*tlvs: bytes, mint_auth: bytes | None = None, freeze_auth: bytes | None = None) -> bytes:
    header = bytearray(166)
    header[0:82] = _base_mint(mint_auth=mint_auth, freeze_auth=freeze_auth)
    header[165] = 1  # AccountType::Mint
    return bytes(header) + b"".join(tlvs)


def _transfer_fee_body(bps: int, cfg_auth: bytes | None = None, withdraw_auth: bytes | None = None) -> bytes:
    body = bytearray(108)
    body[0:36] = _coption(cfg_auth)
    body[36:72] = _coption(withdraw_auth)
    body[88:90] = bps.to_bytes(2, "little")
    body[106:108] = bps.to_bytes(2, "little")
    return bytes(body)


def test_spl_and_token_2022_extensions_classify_pass_caution_block_and_unknown():
    clean_spl = parse_mint_and_extensions(TOKEN_PROGRAM, _base_mint())
    assert clean_spl["status"] == "PASS" and clean_spl["flags"] == []

    present_spl = parse_mint_and_extensions(TOKEN_PROGRAM, _base_mint(mint_auth=KEY_BYTES))
    assert present_spl["status"] == "CAUTION"
    assert "mint_authority_present" in present_spl["flags"]

    zero_fee = _tlv(EXT_TRANSFER_FEE_CONFIG, _transfer_fee_body(0))
    clean_2022 = parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(zero_fee))
    assert clean_2022["status"] == "PASS"
    assert clean_2022["extensions"][0]["type"] == "TransferFeeConfig"

    mutable_fee = _tlv(EXT_TRANSFER_FEE_CONFIG, _transfer_fee_body(0, cfg_auth=KEY_BYTES))
    assert parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(mutable_fee))["status"] == "CAUTION"

    high_fee = _tlv(EXT_TRANSFER_FEE_CONFIG, _transfer_fee_body(600))
    blocked_fee = parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(high_fee))
    assert blocked_fee["status"] == "BLOCK"
    assert "excessive_transfer_fee" in blocked_fee["flags"]

    delegate = _tlv(EXT_PERMANENT_DELEGATE, KEY_BYTES)
    assert parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(delegate))["status"] == "BLOCK"

    hook_caution = _tlv(EXT_TRANSFER_HOOK, KEY_BYTES + b"\x00" * 32)
    assert parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(hook_caution))["status"] == "CAUTION"

    hook_block = _tlv(EXT_TRANSFER_HOOK, b"\x00" * 32 + KEY_BYTES)
    assert parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(hook_block))["status"] == "BLOCK"

    non_transferable = _tlv(EXT_NON_TRANSFERABLE, b"")
    assert parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(non_transferable))["status"] == "BLOCK"

    frozen_default = _tlv(EXT_DEFAULT_ACCOUNT_STATE, b"\x02")
    assert parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(frozen_default))["status"] == "BLOCK"

    unsupported_ext = _tlv(99, b"\x01\x02")
    unknown_2022 = parse_mint_and_extensions(TOKEN_2022, _token_2022_mint(unsupported_ext))
    assert unknown_2022["status"] == "UNKNOWN"
    assert "unsupported_token_2022_extension:99" in unknown_2022["flags"]


def test_stage_liquidity_and_holder_concentration_fail_closed():
    dex_ok = LiquidityRiskEvidence(
        MarketStage.DEX,
        NOW,
        "fixture",
        dex_liquidity_usd=Decimal(15000),
        sell_depth_2pct_usd=Decimal(3000),
    )
    assert evaluate_stage_liquidity(dex_ok, as_of=NOW)["status"] == "PASS"

    missing_depth = LiquidityRiskEvidence(
        MarketStage.DEX,
        NOW,
        "fixture",
        dex_liquidity_usd=Decimal(15000),
        sell_depth_2pct_usd=None,
    )
    assert evaluate_stage_liquidity(missing_depth, as_of=NOW)["status"] == "UNKNOWN"

    curve_ok = LiquidityRiskEvidence(
        MarketStage.CURVE,
        NOW,
        "fixture",
        curve_quote_reserve_usd=Decimal(4000),
        graduation_progress=Decimal("0.6"),
    )
    curve_res = evaluate_stage_liquidity(curve_ok, as_of=NOW)
    assert curve_res["status"] == "PASS" and curve_res["dex_liquidity_status"] == "NOT_APPLICABLE"

    with pytest.raises(ValueError, match="curve"):
        LiquidityRiskEvidence(MarketStage.CURVE, NOW, "fixture", dex_liquidity_usd=Decimal(100))

    holders_ok = HolderRiskEvidence(NOW, "fixture", Decimal(8), Decimal(35))
    assert holders_ok.top_1_account_pct == Decimal(8)
    assert holders_ok.top_1_unlocked_pct == Decimal(8)
    assert holders_ok.top_10_account_pct == Decimal(35)
    assert holders_ok.top_10_unlocked_pct == Decimal(35)
    eval_ok = evaluate_holder_concentration(holders_ok, as_of=NOW)
    assert eval_ok["status"] == "PASS"
    assert eval_ok["top_1_account_pct"] == Decimal(8)
    assert eval_ok["top_1_unlocked_pct"] == Decimal(8)
    assert eval_ok["top_10_account_pct"] == Decimal(35)
    assert eval_ok["top_10_unlocked_pct"] == Decimal(35)

    # Keyword constructor with account_pct and unlocked_pct aliases
    kw_account = HolderRiskEvidence(known_at=NOW, source="fixture", top_1_account_pct=Decimal(8), top_10_account_pct=Decimal(35))
    assert kw_account.top_1_unlocked_pct == Decimal(8)
    kw_unlocked = HolderRiskEvidence(known_at=NOW, source="fixture", top_1_unlocked_pct=Decimal(8), top_10_unlocked_pct=Decimal(35))
    assert kw_unlocked.top_1_account_pct == Decimal(8)

    with pytest.raises(ValueError, match="match"):
        HolderRiskEvidence(known_at=NOW, source="fixture", top_1_account_pct=Decimal(8), top_1_unlocked_pct=Decimal(9), top_10_account_pct=Decimal(35))

    holders_caution = HolderRiskEvidence(NOW, "fixture", Decimal(18), Decimal(40))
    assert evaluate_holder_concentration(holders_caution, as_of=NOW)["status"] == "CAUTION"

    holders_block = HolderRiskEvidence(NOW, "fixture", Decimal(32), Decimal(75))
    assert evaluate_holder_concentration(holders_block, as_of=NOW)["status"] == "BLOCK"


def test_unified_token_risk_requires_all_checks_and_never_trusts_vendor_safe_alone():
    mint_ok = MintRiskEvidence(
        TOKEN_2022,
        base64.b64encode(_token_2022_mint(_tlv(EXT_TRANSFER_FEE_CONFIG, _transfer_fee_body(0)))).decode(),
        NOW - timedelta(minutes=1),
        "fixture",
    )
    liq_ok = LiquidityRiskEvidence(
        MarketStage.DEX,
        NOW - timedelta(minutes=1),
        "fixture",
        dex_liquidity_usd=Decimal(20000),
        sell_depth_2pct_usd=Decimal(4000),
    )
    hold_ok = HolderRiskEvidence(NOW - timedelta(minutes=1), "fixture", Decimal(5), Decimal(25))

    full = evaluate_token_risk(
        as_of=NOW,
        mint_evidence=mint_ok,
        liquidity_evidence=liq_ok,
        holder_evidence=hold_ok,
    )
    assert full["security_status"] == "PASS"

    # Missing holder check stays UNKNOWN even if vendor says SAFE.
    missing_holders = evaluate_token_risk(
        as_of=NOW,
        mint_evidence=mint_ok,
        liquidity_evidence=liq_ok,
        holder_evidence=None,
        vendor_verdict="SAFE",
    )
    assert missing_holders["security_status"] == "UNKNOWN"

    # Vendor DANGER downgrades PASS to CAUTION.
    vendor_danger = evaluate_token_risk(
        as_of=NOW,
        mint_evidence=mint_ok,
        liquidity_evidence=liq_ok,
        holder_evidence=hold_ok,
        vendor_verdict="DANGER",
    )
    assert vendor_danger["security_status"] == "CAUTION"
    assert "vendor_flagged_danger" in vendor_danger["flags"]
