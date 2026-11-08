import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cluster_radar.providers.solana_history import SolanaHistoryAdapter
from cluster_radar.providers.solana_holders import BudgetExceeded, ProviderUnavailable
from mochex_radar.api import app
from mochex_radar.wallet_history import (
    DEFAULT_HISTORY_SOURCE,
    DEFAULT_PARSER_VERSION,
    PersistentSolanaHistory,
    wallet_history_overview,
)

SAMPLE_WALLET = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
SAMPLE_MINT = "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY"
SAMPLE_POOL = "So11111111111111111111111111111111111111112"


def test_persistent_solana_history_validation():
    mock_adapter = MagicMock(spec=SolanaHistoryAdapter)
    mock_adapter.requests = 0
    mock_adapter.max_requests = 10

    provider = PersistentSolanaHistory(mock_adapter, dsn="mock://dsn", daily_limit=50)

    # Invalid wallet address
    with pytest.raises(ValueError):
        asyncio.run(provider.poll_wallet("invalid-address"))

    # Invalid limit
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(provider.poll_wallet(SAMPLE_WALLET, limit=0))
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(provider.poll_wallet(SAMPLE_WALLET, limit=101))

    # Process budget ceiling check
    mock_adapter.requests = 10
    with pytest.raises(BudgetExceeded, match="process history request ceiling"):
        asyncio.run(provider.poll_wallet(SAMPLE_WALLET))


@pytest.mark.asyncio
async def test_persistent_solana_history_poll_and_store():
    mock_adapter = MagicMock(spec=SolanaHistoryAdapter)
    mock_adapter.requests = 0
    mock_adapter.max_requests = 10

    # Mock raw enhanced transaction payload
    now_ts = int(datetime.now(timezone.utc).timestamp())
    mock_payload = [
        {
            "signature": "5HpvGZ2E8z8Vw2vN8z...",
            "timestamp": now_ts - 300,
            "description": "swap",
            "type": "SWAP",
            "source": "RAYDIUM",
            "tokenTransfers": [],
            "nativeTransfers": [],
        }
    ]
    mock_adapter.fetch_address_transactions = AsyncMock(return_value=mock_payload)

    provider = PersistentSolanaHistory(mock_adapter, dsn="mock://dsn", daily_limit=50)

    with patch("mochex_radar.wallet_history.reserve_request", return_value=0.0):
        with patch("mochex_radar.wallet_history.store_history_batch", return_value="mock-batch-123"):
            result = await provider.poll_wallet(
                SAMPLE_WALLET,
                target_mint=SAMPLE_MINT,
                default_pool=SAMPLE_POOL,
                limit=10,
            )

    assert result["data_status"] == "observed"
    assert result["batch_id"] == "mock-batch-123"
    assert result["wallet"] == SAMPLE_WALLET
    assert result["raw_tx_count"] == 1
    assert result["coverage_verified"] is False
    assert result["signals_enabled"] is False


def test_api_wallet_history_endpoints_disabled():
    client = TestClient(app)

    # Without history_provider configured on app.state
    response = client.post(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/poll")
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()


def test_api_wallet_history_endpoints_with_provider():
    client = TestClient(app)
    mock_provider = MagicMock(spec=PersistentSolanaHistory)
    mock_provider.poll_wallet = AsyncMock(
        return_value={
            "data_status": "observed",
            "batch_id": "test-batch-abc",
            "wallet": SAMPLE_WALLET,
            "raw_tx_count": 5,
            "swaps_count": 2,
            "funding_count": 1,
            "coverage_verified": False,
            "signals_enabled": False,
        }
    )

    app.state.history_provider = mock_provider
    try:
        # Invalid pubkey validation
        bad_resp = client.post("/api/v1/security/solana/wallets/bad-pubkey/poll")
        assert bad_resp.status_code == 422

        # Success poll
        resp = client.post(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/poll?limit=25")
        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_id"] == "test-batch-abc"
        assert data["swaps_count"] == 2
        assert data["funding_count"] == 1
    finally:
        app.state.history_provider = None


def test_api_stored_wallet_endpoints():
    client = TestClient(app)

    # Missing DATABASE_URL returns 503
    with patch.dict("os.environ", {}, clear=True):
        resp_hist = client.get(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/history")
        assert resp_hist.status_code == 503

        resp_prov = client.get(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/provenance")
        assert resp_prov.status_code == 503

        resp_fund = client.get(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/funding")
        assert resp_fund.status_code == 503

    # With DATABASE_URL and mocked stores
    with patch.dict("os.environ", {"DATABASE_URL": "postgresql://test"}):
        with patch("mochex_radar.api.provenance_history", return_value=[{"batch_id": "b1"}]):
            with patch("mochex_radar.api.funding_history", return_value=[]):
                # Provenance endpoint
                resp = client.get(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/provenance")
                assert resp.status_code == 200
                assert resp.json()["data_status"] == "stored_provenance"
                assert len(resp.json()["batches"]) == 1

                # Funding endpoint
                resp = client.get(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/funding")
                assert resp.status_code == 200
                assert resp.json()["data_status"] == "stored_funding"
                assert resp.json()["funding_count"] == 0

                # History overview endpoint
                with patch("mochex_radar.wallet_history.provenance_history", return_value=[{"batch_id": "b1"}]):
                    with patch("mochex_radar.wallet_history.funding_history", return_value=[]):
                        resp = client.get(f"/api/v1/security/solana/wallets/{SAMPLE_WALLET}/history")
                        assert resp.status_code == 200
                        assert resp.json()["data_status"] == "stored_history"
                        assert resp.json()["batches_count"] == 1
