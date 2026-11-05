"""Explain incomplete collection without treating duplicate rows as provider failure."""

import asyncio
import logging
from datetime import timedelta

from mochex_radar.alert_store import enqueue
from mochex_radar.alerts import ResearchNotice
from mochex_radar.futures_feed import INTERVALS
from mochex_radar.markets import core_markets
from mochex_radar.storage import CycleResult

log = logging.getLogger(__name__)


def collection_notice(cycle: CycleResult) -> ResearchNotice | None:
    targets = len(core_markets()) * len(INTERVALS) + 1
    if not 0 <= cycle.provider_failures <= targets or cycle.stored_count < 0 or cycle.finished_at < cycle.started_at:
        raise ValueError("invalid collection result")
    if cycle.provider_failures == 0:
        return None
    return ResearchNotice(
        asset_id="system:mexc-usdt-futures-collector", kind="DATA_QUALITY",
        rule_version="collector-provider-failures-v1", known_at=cycle.finished_at,
        expires_at=cycle.finished_at + timedelta(hours=1),
        summary="The latest MEXC futures collection cycle has incomplete provider coverage.",
        evidence=[f"Provider failures: {cycle.provider_failures} of {targets} targets.",
                  f"New stored candle rows: {cycle.stored_count}; duplicates do not add rows.",
                  f"Cycle started at {cycle.started_at.isoformat()} and finished at {cycle.finished_at.isoformat()}."])


async def report_cycle_quality(dsn: str, cycle: CycleResult) -> str:
    """Collection is already committed; optional notification failure must not undo it."""
    try:
        notice = collection_notice(cycle)
        if notice is None:
            return "healthy"
        identity = await asyncio.to_thread(enqueue, dsn, notice)
        return "queued_or_existing" if identity else "cooldown"
    except Exception as exc:
        log.error("quality notice queue unavailable (%s)", type(exc).__name__)
        return "queue_unavailable"
