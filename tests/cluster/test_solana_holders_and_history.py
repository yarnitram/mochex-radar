from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from cluster_radar.intelligence.research import funding_groups
from cluster_radar.providers.dexscreener import BudgetExceeded
from cluster_radar.providers.solana_authorities import encode_pubkey
from cluster_radar.providers.solana_history import (
    SolanaHistoryAdapter,
    normalize_enhanced_transactions,
)
from cluster_radar.providers.solana_holders import (
    SolanaHolderConcentration,
    parse_holder_concentration,
)
from cluster_radar.security.token_risk import SecurityStatus

MINT = encode_pubkey(b"\x11" * 32)
POOL = encode_pubkey(b"\x22" * 32)
ACCT_LP = encode_pubkey(b"\x31" * 32)
ACCT_1 = encode_pubkey(b"\x32" * 32)
ACCT_2 = encode_pubkey(b"\x33" * 32)
WALLET_A = encode_pubkey(b"\x41" * 32)
WALLET_B = encode_pubkey(b"\x42" * 32)
FUNDER_SHARED = encode_pubkey(b"\x51" * 32)
FUNDER_CEX = encode_pubkey(b"\x52" * 32)


def test_parse_holder_concentration_and_exclusions() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    supply_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "context": {"slot": 465558000},
            "value": {"amount": "1000000", "decimals": 6, "uiAmountString": "1.0"},
        },
    }
    largest_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "context": {"slot": 465558000},
            "value": [
                {"address": ACCT_LP, "amount": "450000"},
                {"address": ACCT_1, "amount": "100000"},
                {"address": ACCT_2, "amount": "80000"},
            ],
        },
    }

    # Without excluding ACCT_LP (45% of supply), top_1 triggers BLOCK (>= 30%)
    unfiltered = parse_holder_concentration(
        MINT,
        supply_payload,
        largest_payload,
        response_hash="abc123",
        known_at=now,
    )
    assert unfiltered.concentration_status == SecurityStatus.BLOCK.value
    assert unfiltered.top_1_unlocked_pct == Decimal(45)
    assert unfiltered.security_status == "UNKNOWN"
    assert unfiltered.approved_pump_watch is False

    # Excluding verified LP account ACCT_LP leaves top_1 = 10%, top_10 = 18% -> PASS
    filtered = parse_holder_concentration(
        MINT,
        supply_payload,
        largest_payload,
        response_hash="abc123",
        known_at=now,
        excluded_token_accounts={ACCT_LP},
    )
    assert filtered.concentration_status == SecurityStatus.PASS.value
    assert filtered.top_1_unlocked_pct == Decimal(10)
    assert filtered.top_10_unlocked_pct == Decimal(18)
    assert filtered.excluded_accounts_count == 1
    assert filtered.holder_evidence is not None
    assert filtered.holder_evidence.excluded_known_accounts == (ACCT_LP,)
    assert filtered.security_status == "UNKNOWN"
    assert filtered.approved_pump_watch is False

    # Slot mismatch between supply and largest accounts fails closed as UNKNOWN
    mismatched_largest = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "context": {"slot": 465558001},
            "value": [{"address": ACCT_1, "amount": "100000"}],
        },
    }
    mismatch = parse_holder_concentration(
        MINT,
        supply_payload,
        mismatched_largest,
        response_hash="def456",
        known_at=now,
    )
    assert mismatch.concentration_status == SecurityStatus.UNKNOWN.value
    assert mismatch.reason == "holder_rpc_slot_mismatch"
    assert mismatch.holder_evidence is None


@pytest.mark.anyio
async def test_solana_holder_concentration_budget_and_transport(monkeypatch) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("cluster_radar.providers.solana_holders.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if body["method"] == "getTokenSupply":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "context": {"slot": 100},
                        "value": {"amount": "1000", "decimals": 0},
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "context": {"slot": 100},
                    "value": [{"address": ACCT_1, "amount": "200"}],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SolanaHolderConcentration(client, max_requests=2)
        obs = await adapter.check(MINT)
        assert obs.concentration_status == SecurityStatus.CAUTION.value
        assert obs.top_1_unlocked_pct == Decimal(20)
        with pytest.raises(BudgetExceeded):
            await adapter.check(MINT)


def test_normalize_enhanced_transactions_and_funding_groups() -> None:
    as_of = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    known_at = datetime(2026, 11, 6, 11, 55, tzinfo=UTC)
    t_valid = int(datetime(2026, 11, 6, 11, 50, tzinfo=UTC).timestamp())
    t_future = int(datetime(2026, 11, 6, 12, 5, tzinfo=UTC).timestamp())

    raw_txs = [
        {
            "signature": "sig-buy-a",
            "timestamp": t_valid,
            "transactionError": None,
            "tokenTransfers": [
                {
                    "mint": MINT,
                    "fromUserAccount": POOL,
                    "toUserAccount": WALLET_A,
                    "tokenAmount": "1250.5",
                    "usdValue": "50.25",
                }
            ],
            "nativeTransfers": [
                {
                    "fromUserAccount": FUNDER_SHARED,
                    "toUserAccount": WALLET_A,
                    "amount": 50_000_000,
                }
            ],
        },
        {
            "signature": "sig-sell-b",
            "timestamp": t_valid,
            "transactionError": None,
            "tokenTransfers": [
                {
                    "mint": MINT,
                    "fromUserAccount": WALLET_B,
                    "toUserAccount": POOL,
                    "tokenAmount": "400",
                    "usdValue": "16.0",
                }
            ],
            "nativeTransfers": [
                {
                    "fromUserAccount": FUNDER_SHARED,
                    "toUserAccount": WALLET_B,
                    "amount": 50_000_000,
                },
                {
                    "fromUserAccount": FUNDER_CEX,
                    "toUserAccount": WALLET_A,
                    "amount": 100_000_000,
                },
            ],
        },
        {
            "signature": "sig-failed",
            "timestamp": t_valid,
            "transactionError": {"InstructionError": [0, "Custom"]},
            "tokenTransfers": [
                {
                    "mint": MINT,
                    "fromUserAccount": POOL,
                    "toUserAccount": WALLET_A,
                    "tokenAmount": "9999",
                }
            ],
        },
        {
            "signature": "sig-future",
            "timestamp": t_future,
            "transactionError": None,
            "tokenTransfers": [
                {
                    "mint": MINT,
                    "fromUserAccount": POOL,
                    "toUserAccount": WALLET_A,
                    "tokenAmount": "500",
                }
            ],
        },
    ]

    # Without explicit NON_CEX label on FUNDER_SHARED, funding stays UNKNOWN and forms 0 groups
    unlabeled_batch = normalize_enhanced_transactions(
        raw_txs,
        target_mint=MINT,
        default_pool=POOL,
        known_at=known_at,
        as_of=as_of,
    )
    assert len(unlabeled_batch.swaps) == 2
    assert unlabeled_batch.swaps[0].side == "BUY"
    assert unlabeled_batch.swaps[0].owner == WALLET_A
    assert unlabeled_batch.swaps[1].side == "SELL"
    assert unlabeled_batch.swaps[1].owner == WALLET_B
    assert unlabeled_batch.skipped_failed_tx_count == 1
    assert unlabeled_batch.excluded_future_count == 1
    assert funding_groups(list(unlabeled_batch.funding), as_of)["groups"] == []

    # With verified NON_CEX label on FUNDER_SHARED (and single funder per wallet), forms a group
    single_funder_txs = [
        raw_txs[0],
        {**raw_txs[1], "nativeTransfers": [raw_txs[1]["nativeTransfers"][0]]},
    ]
    labeled_batch = normalize_enhanced_transactions(
        single_funder_txs,
        target_mint=MINT,
        default_pool=POOL,
        known_at=known_at,
        as_of=as_of,
        funder_labels={FUNDER_SHARED: ("NON_CEX", known_at)},
    )
    grouped = funding_groups(list(labeled_batch.funding), as_of)
    assert len(grouped["groups"]) == 1
    assert grouped["groups"][0]["funder"] == FUNDER_SHARED
    assert grouped["groups"][0]["wallets"] == sorted([WALLET_A, WALLET_B])


@pytest.mark.anyio
async def test_solana_history_adapter_budget(monkeypatch) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("cluster_radar.providers.solana_history.asyncio.sleep", no_sleep)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SolanaHistoryAdapter(
            client,
            endpoint_template="https://api.example.invalid/v0/addresses/{address}/transactions",
            max_requests=1,
        )
        res = await adapter.fetch_address_transactions(WALLET_A, limit=10)
        assert res == []
        with pytest.raises(BudgetExceeded):
            await adapter.fetch_address_transactions(WALLET_A, limit=10)
