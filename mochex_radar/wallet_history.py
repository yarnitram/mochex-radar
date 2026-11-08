"""Persistent bounded adapter and querying for Solana wallet transaction histories."""

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
import logging

import httpx
import psycopg

from cluster_radar.providers.solana_authorities import decode_pubkey
from cluster_radar.intelligence.research import funding_groups, require_utc
from cluster_radar.providers.solana_history import (
    SolanaHistoryAdapter,
    normalize_enhanced_transactions,
)
from cluster_radar.providers.solana_holders import (
    BudgetExceeded,
    ProviderUnavailable,
)
from mochex_radar.funding_store import funding_history
from mochex_radar.history_batch_store import (
    canonical_raw_sha256,
    provenance_history,
    store_history_batch,
)
from mochex_radar.history_provenance import HistoryProvenance
from mochex_radar.provider_budget import reserve_request

log = logging.getLogger(__name__)

DEFAULT_HISTORY_SOURCE = "helius:enhanced-transactions:v0"
DEFAULT_PARSER_VERSION = "solana-wallet-history-v1"


class PersistentSolanaHistory:
    """Thread-safe persistent wrapper for SolanaHistoryAdapter with durable budget reservations."""

    def __init__(
        self,
        inner: SolanaHistoryAdapter,
        dsn: str,
        daily_limit: int = 100,
        source: str = DEFAULT_HISTORY_SOURCE,
    ) -> None:
        if daily_limit < 1:
            raise ValueError("daily_limit of at least 1 required")
        self.inner = inner
        self.dsn = dsn
        self.daily_limit = daily_limit
        self.source = source
        self._lock = asyncio.Lock()

    async def poll_wallet(
        self,
        wallet: str,
        *,
        target_mint: str = "So11111111111111111111111111111111111111112",
        default_pool: str = "So11111111111111111111111111111111111111112",
        limit: int = 50,
        as_of: datetime | None = None,
    ) -> dict:
        decode_pubkey(wallet)
        decode_pubkey(target_mint)
        decode_pubkey(default_pool)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        now = datetime.now(timezone.utc)
        cutoff = as_of or now
        if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
            raise ValueError("as_of must be UTC")

        async with self._lock:
            if self.inner.requests + 1 > self.inner.max_requests:
                raise BudgetExceeded("process history request ceiling exhausted")

            try:
                while delay := await asyncio.to_thread(
                    reserve_request,
                    self.dsn,
                    self.daily_limit,
                    provider="solana-history",
                    spacing_seconds=1.1,
                ):
                    await asyncio.sleep(delay)
            except psycopg.Error as exc:
                raise ProviderUnavailable("history request budget unavailable") from exc

            raw_payload = await self.inner.fetch_address_transactions(wallet, limit=limit)

        raw_sha = canonical_raw_sha256(raw_payload)

        # Derive coverage time bounds from observed transaction timestamps
        valid_ts = [
            tx["timestamp"]
            for tx in raw_payload
            if isinstance(tx, dict)
            and isinstance(tx.get("timestamp"), int)
            and tx["timestamp"] > 0
        ]
        if valid_ts:
            min_time = datetime.fromtimestamp(min(valid_ts), tz=timezone.utc)
            max_time = datetime.fromtimestamp(max(valid_ts), tz=timezone.utc)
            window_end = min(max_time, cutoff)
            window_start = min_time
            if window_start >= window_end:
                window_start = window_end - timedelta(seconds=1)
        else:
            window_end = cutoff
            window_start = cutoff - timedelta(hours=24)

        batch = normalize_enhanced_transactions(
            raw_payload,
            target_mint=target_mint,
            default_pool=default_pool,
            known_at=cutoff,
            as_of=cutoff,
            source=self.source,
        )

        provenance = HistoryProvenance(
            source=self.source,
            parser_version=DEFAULT_PARSER_VERSION,
            wallet=wallet,
            window_start=window_start,
            window_end=window_end,
            retrieved_at=cutoff,
            raw_sha256=raw_sha,
            pagination_exhausted=(len(raw_payload) < limit),
            coverage_verified=False,
        )

        batch_id = await asyncio.to_thread(
            store_history_batch,
            self.dsn,
            provenance,
            raw_payload=raw_payload,
            swaps=batch.swaps,
            funding=batch.funding,
        )

        return {
            "data_status": "observed",
            "batch_id": batch_id,
            "wallet": wallet,
            "retrieved_at": cutoff.isoformat(),
            "raw_sha256": raw_sha,
            "raw_tx_count": len(raw_payload),
            "swaps_count": len(batch.swaps),
            "funding_count": len(batch.funding),
            "skipped_failed": batch.skipped_failed_tx_count,
            "excluded_future": batch.excluded_future_count,
            "pagination_exhausted": len(raw_payload) < limit,
            "coverage_verified": False,
            "signals_enabled": False,
        }


def wallet_history_overview(
    dsn: str,
    wallet: str,
    as_of: datetime,
    limit: int = 10,
) -> dict:
    """Return stored provenance envelopes, funding evidence, and cluster groups for a wallet."""
    decode_pubkey(wallet)
    require_utc(as_of)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    batches = provenance_history(dsn, wallet, as_of, limit=limit)
    funding_rows = funding_history(dsn, [wallet], as_of, limit=100)
    fg = funding_groups(funding_rows, as_of)

    return {
        "data_status": "stored_history",
        "wallet": wallet,
        "as_of": as_of.isoformat(),
        "batches_count": len(batches),
        "batches": batches,
        "funding_count": len(funding_rows),
        "funding_groups": fg,
        "completeness": "unverified",
        "signals_enabled": False,
    }
