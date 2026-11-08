"""Point-in-time stored Solana candidate risk, wallet history, and state-machine evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from cluster_radar.discovery.identity import MarketStage
from cluster_radar.intelligence.research import funding_groups, swap_metrics
from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.solana_authorities import decode_pubkey
from cluster_radar.providers.solana_holders import (
    HOLDER_SOURCE,
    HolderSnapshotObservation,
    SolanaHolderConcentration,
)
from cluster_radar.security.token_risk import (
    FRESHNESS_WINDOW,
    RULE_VERSION as RISK_RULE_VERSION,
    HolderRiskEvidence,
    LiquidityRiskEvidence,
    SecurityStatus,
    evaluate_holder_concentration,
    evaluate_stage_liquidity,
)
from cluster_radar.signals.features import (
    FEATURE_VERSION as SWAP_FEATURE_VERSION,
    extract_swap_features,
)
from cluster_radar.signals.research import FeatureEvidence
from cluster_radar.signals.state_machine import evaluate_candidate_state
from mochex_radar.authority_checks import authority_history
from mochex_radar.dex_store import observation_history
from mochex_radar.funding_store import funding_history
from mochex_radar.history_batch_store import provenance_history
from mochex_radar.provider_budget import initialize_budget_store, reserve_request
from mochex_radar.swap_store import swap_history

DEFAULT_HISTORY_LOOKBACK = timedelta(minutes=15)

HOLDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS mint_holder_observations (
    mint text NOT NULL,
    source text NOT NULL,
    known_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    slot bigint NOT NULL CHECK (slot >= 0),
    content_hash text NOT NULL,
    payload jsonb NOT NULL CHECK (payload @> '{"security_status":"UNKNOWN","approved_pump_watch":false}'::jsonb),
    PRIMARY KEY (mint, source, known_at)
);
CREATE INDEX IF NOT EXISTS mint_holder_history_idx
ON mint_holder_observations (mint, known_at DESC);
"""


def initialize_holder_store(dsn: str) -> None:
    initialize_budget_store(dsn)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute(HOLDER_SCHEMA)


def store_holder_observation(dsn: str, observation: HolderSnapshotObservation) -> None:
    decode_pubkey(observation.mint)
    if observation.known_at.tzinfo is None or observation.known_at.utcoffset() != timedelta(0):
        raise ValueError("known_at must be UTC")
    raw_dict = asdict(observation)
    raw_dict.pop("holder_evidence", None)
    payload = jsonable_encoder(raw_dict, custom_encoder={Decimal: str})
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = (observation.mint, observation.source, observation.known_at)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        added = conn.execute(
            """INSERT INTO mint_holder_observations
            (mint, source, known_at, slot, content_hash, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING RETURNING mint""",
            (*key, observation.slot, digest, Jsonb(payload)),
        ).fetchone()
        if added is None:
            old = conn.execute(
                """SELECT content_hash FROM mint_holder_observations
                WHERE mint=%s AND source=%s AND known_at=%s""",
                key,
            ).fetchone()
            if old is None or old[0] != digest:
                raise ValueError("conflicting immutable holder concentration evidence")


def holder_history(dsn: str, mint: str, as_of: datetime, limit: int = 10) -> list[dict]:
    decode_pubkey(mint)
    if (
        as_of.tzinfo is None
        or as_of.utcoffset() != timedelta(0)
        or not 1 <= limit <= 100
    ):
        raise ValueError("UTC cutoff and limit 1..100 required")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(
            """SELECT payload, known_at, ingested_at FROM mint_holder_observations
            WHERE mint=%s AND known_at<=%s AND ingested_at<=%s
            ORDER BY known_at DESC, source LIMIT %s""",
            (mint, as_of, as_of, limit),
        ).fetchall()
    return [
        {
            "evidence": row[0],
            "ingested_at": row[2].isoformat(),
            "freshness": "current" if as_of - row[1] < FRESHNESS_WINDOW else "stale",
            "expires_at": (row[1] + FRESHNESS_WINDOW).isoformat(),
        }
        for row in rows
    ]


class PersistentHolderConcentration:
    def __init__(self, inner: SolanaHolderConcentration, dsn: str, daily_limit: int) -> None:
        if daily_limit < 2:
            raise ValueError("daily_limit of at least 2 requests required for holder checks")
        self.inner = inner
        self.dsn = dsn
        self.daily_limit = daily_limit
        self._lock = asyncio.Lock()

    async def check(self, mint: str) -> HolderSnapshotObservation:
        decode_pubkey(mint)
        async with self._lock:
            if self.inner.requests + 2 > self.inner.max_requests:
                raise BudgetExceeded("process holder request ceiling exhausted")
            try:
                for _ in range(2):
                    while delay := await asyncio.to_thread(
                        reserve_request,
                        self.dsn,
                        self.daily_limit,
                        provider=HOLDER_SOURCE,
                        spacing_seconds=1.1,
                    ):
                        await asyncio.sleep(delay)
            except psycopg.Error as exc:
                raise ProviderUnavailable("holder request budget unavailable") from exc
            return await self.inner.check(mint)


def _evaluate_stored_authority_check(
    authority_rows: list[dict],
    as_of: datetime,
) -> dict:
    if not authority_rows:
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "reason": "missing_mint_evidence",
            "flags": [],
        }
    latest = authority_rows[0]
    if latest.get("freshness") != "current":
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "reason": "stale_evidence",
            "flags": ["stale_evidence"],
        }
    ev = latest["evidence"]
    reason = ev.get("reason", "unknown")
    if reason != "partial_authority_evidence":
        return {
            "status": SecurityStatus.UNKNOWN.value,
            "reason": reason,
            "flags": [reason],
        }
    flags: list[str] = []
    if ev.get("mint_authority_status") == "PRESENT":
        flags.append("mint_authority_present")
    if ev.get("freeze_authority_status") == "PRESENT":
        flags.append("freeze_authority_present")
    status = SecurityStatus.CAUTION.value if flags else SecurityStatus.PASS.value
    return {
        "status": status,
        "program": "spl-token",
        "reason": "evaluated",
        "mint_authority_status": ev.get("mint_authority_status"),
        "freeze_authority_status": ev.get("freeze_authority_status"),
        "extensions": [],
        "flags": flags,
    }


def _build_liquidity_evidence(dex_rows: list[dict]) -> LiquidityRiskEvidence | None:
    if not dex_rows:
        return None
    cand = dex_rows[0]["candidate"]
    known_at = datetime.fromisoformat(cand["known_at"])
    liq_raw = cand.get("dex_liquidity_usd") if cand.get("dex_liquidity_usd") is not None else cand.get("liquidity_usd")
    liq_dec = Decimal(str(liq_raw)) if liq_raw is not None else None
    return LiquidityRiskEvidence(
        stage=MarketStage.DEX,
        known_at=known_at,
        source=cand.get("source", "dexscreener"),
        dex_liquidity_usd=liq_dec,
        sell_depth_2pct_usd=None,
    )


def _build_holder_evidence(holder_rows: list[dict]) -> HolderRiskEvidence | None:
    if not holder_rows:
        return None
    ev = holder_rows[0]["evidence"]
    top_1 = ev.get("top_1_account_pct") if ev.get("top_1_account_pct") is not None else ev.get("top_1_unlocked_pct")
    top_10 = ev.get("top_10_account_pct") if ev.get("top_10_account_pct") is not None else ev.get("top_10_unlocked_pct")
    if top_1 is None or top_10 is None:
        return None
    known_at = datetime.fromisoformat(ev["known_at"])
    return HolderRiskEvidence(
        known_at=known_at,
        source=ev.get("source", HOLDER_SOURCE),
        top_1_account_pct=Decimal(str(top_1)),
        top_10_account_pct=Decimal(str(top_10)),
        top_1_unlocked_pct=Decimal(str(top_1)),
        top_10_unlocked_pct=Decimal(str(top_10)),
    )


def evaluate_stored_history_features(
    dsn: str | None,
    mint: str,
    *,
    as_of: datetime,
    lookback: timedelta = DEFAULT_HISTORY_LOOKBACK,
    history_start: datetime | None = None,
) -> dict:
    """Derive point-in-time swap and funding features from immutable stored history.

    Missing history coverage, buyer independence, wallet quality, and market structure
    are never zero-filled. Pagination exhaustion in provenance batches remains
    unverified unless an explicit coverage `history_start` is supplied for replay.
    """
    decode_pubkey(mint)
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be UTC")
    if lookback <= timedelta(0):
        raise ValueError("lookback must be positive")
    if history_start is not None and (
        history_start.tzinfo is None or history_start.utcoffset() != timedelta(0)
    ):
        raise ValueError("history_start must be UTC")

    base_unverified_reasons = {
        "independent_buying": "buyer_independence_unverified",
        "compression_structure": "missing_market_structure_evidence",
        "wallet_quality": "missing_wallet_quality_evidence",
        "organic_volume": "missing_organic_volume_evidence",
        "holder_distribution": "token_account_only_ownership_unverified",
        "price_volume_divergence": "missing_divergence_evidence",
        "liquidity_deterioration": "missing_liquidity_series_evidence",
        "structure_weakness": "missing_structure_weakness_evidence",
    }

    if not dsn:
        return {
            "feature_version": SWAP_FEATURE_VERSION,
            "as_of": as_of,
            "lookback_seconds": lookback.total_seconds(),
            "history_start": None,
            "completeness": "unverified",
            "provenance_batches_count": 0,
            "pump_features": [],
            "dump_features": [],
            "unavailable_features": {
                "buyer_exhaustion": "storage_disabled",
                "new_owner_participation": "storage_disabled",
                **base_unverified_reasons,
            },
            "swap_metrics": None,
            "funding_groups": {
                "as_of": as_of,
                "groups": [],
                "ownership_verified": False,
                "conflicting_wallets": [],
            },
            "buyer_independence_verified": False,
        }

    try:
        swaps = swap_history(dsn, mint, as_of, limit=1000)
    except (psycopg.errors.UndefinedTable, psycopg.OperationalError):
        swaps = []

    metrics = swap_metrics(swaps, mint, as_of, lookback)
    owners = sorted({s.owner for s in swaps})

    funding_rows = []
    provenance_count = 0
    if owners:
        try:
            funding_rows = funding_history(dsn, owners[:500], as_of, limit=1000)
        except (psycopg.errors.UndefinedTable, psycopg.OperationalError):
            funding_rows = []
        for owner in owners[:25]:
            try:
                provenance_count += len(provenance_history(dsn, owner, as_of, limit=10))
            except (psycopg.errors.UndefinedTable, psycopg.OperationalError):
                break

    fg = funding_groups(funding_rows, as_of)
    effective_start = history_start if history_start is not None else as_of
    extracted = extract_swap_features(swaps, mint, as_of, lookback, effective_start)

    pump_features: list[FeatureEvidence] = []
    dump_features: list[FeatureEvidence] = []
    if "new_owner_participation" in extracted["features"]:
        pump_features.append(extracted["features"]["new_owner_participation"])
    if "buyer_exhaustion" in extracted["features"]:
        dump_features.append(extracted["features"]["buyer_exhaustion"])

    unavailable = {
        **extracted["unavailable"],
        **base_unverified_reasons,
    }

    return {
        "feature_version": SWAP_FEATURE_VERSION,
        "as_of": as_of,
        "lookback_seconds": lookback.total_seconds(),
        "history_start": history_start,
        "completeness": "unverified",
        "provenance_batches_count": provenance_count,
        "pump_features": pump_features,
        "dump_features": dump_features,
        "unavailable_features": unavailable,
        "swap_metrics": metrics,
        "funding_groups": fg,
        "buyer_independence_verified": False,
    }


def evaluate_stored_candidate(
    dsn: str | None,
    mint: str,
    *,
    as_of: datetime | None = None,
    history_start: datetime | None = None,
    lookback: timedelta = DEFAULT_HISTORY_LOOKBACK,
    extra_pump_features: Sequence[FeatureEvidence] = (),
    extra_dump_features: Sequence[FeatureEvidence] = (),
) -> dict:
    decode_pubkey(mint)
    cutoff = as_of or datetime.now(timezone.utc)
    if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
        raise ValueError("as_of must be UTC")

    if not dsn:
        empty_risk = {
            "rule_version": RISK_RULE_VERSION,
            "as_of": cutoff,
            "security_status": SecurityStatus.UNKNOWN.value,
            "checks": {
                "mint_and_extensions": {
                    "status": SecurityStatus.UNKNOWN.value,
                    "reason": "storage_disabled",
                    "flags": [],
                },
                "stage_liquidity": {
                    "status": SecurityStatus.UNKNOWN.value,
                    "reason": "storage_disabled",
                    "flags": [],
                },
                "holder_concentration": {
                    "status": SecurityStatus.UNKNOWN.value,
                    "reason": "storage_disabled",
                    "flags": [],
                },
            },
            "flags": [],
            "vendor_verdict_note": "vendor_score_never_sufficient_for_pass",
        }
        state_eval = evaluate_candidate_state(
            mint=mint,
            as_of=cutoff,
            window_end=cutoff,
            pump_features=list(extra_pump_features),
            dump_features=list(extra_dump_features),
            token_risk=empty_risk,
        )
        return jsonable_encoder(
            {
                "data_status": "storage_disabled",
                "mint": mint,
                "as_of": cutoff,
                "token_risk": empty_risk,
                "candidate_state": state_eval,
            },
            custom_encoder={Decimal: str},
        )

    try:
        auth_rows = authority_history(dsn, mint, cutoff, limit=1)
    except psycopg.errors.UndefinedTable:
        auth_rows = []
    try:
        dex_rows = observation_history(dsn, mint, cutoff, limit=1)
    except psycopg.errors.UndefinedTable:
        dex_rows = []
    try:
        hold_rows = holder_history(dsn, mint, cutoff, limit=1)
    except psycopg.errors.UndefinedTable:
        hold_rows = []

    mint_check = _evaluate_stored_authority_check(auth_rows, cutoff)
    liquidity_check = evaluate_stage_liquidity(_build_liquidity_evidence(dex_rows), as_of=cutoff)
    holder_check = evaluate_holder_concentration(_build_holder_evidence(hold_rows), as_of=cutoff)
    # Largest token accounts do not establish controller ownership or lock state.
    # Concentration warnings remain useful, but low account shares cannot certify
    # dispersed, unlocked wallet ownership.
    if holder_check["status"] == SecurityStatus.PASS.value:
        holder_check = {**holder_check, "status": SecurityStatus.UNKNOWN.value,
                        "reason": "token_account_only_ownership_and_locks_unverified",
                        "flags": [*holder_check.get("flags", []), "holder_ownership_unverified"]}

    checks = {
        "mint_and_extensions": mint_check,
        "stage_liquidity": liquidity_check,
        "holder_concentration": holder_check,
    }
    statuses = [c["status"] for c in checks.values()]
    flags = [flag for c in checks.values() for flag in c.get("flags", [])]

    if SecurityStatus.BLOCK.value in statuses:
        overall = SecurityStatus.BLOCK.value
    elif SecurityStatus.UNKNOWN.value in statuses:
        overall = SecurityStatus.UNKNOWN.value
    elif SecurityStatus.CAUTION.value in statuses:
        overall = SecurityStatus.CAUTION.value
    else:
        overall = SecurityStatus.PASS.value

    token_risk = {
        "rule_version": RISK_RULE_VERSION,
        "as_of": cutoff,
        "security_status": overall,
        "checks": checks,
        "flags": flags,
        "vendor_verdict_note": "vendor_score_never_sufficient_for_pass",
    }

    history_eval = evaluate_stored_history_features(
        dsn,
        mint,
        as_of=cutoff,
        lookback=lookback,
        history_start=history_start,
    )
    pump_features = [*history_eval["pump_features"], *extra_pump_features]
    dump_features = [*history_eval["dump_features"], *extra_dump_features]

    state_eval = evaluate_candidate_state(
        mint=mint,
        as_of=cutoff,
        window_end=cutoff,
        pump_features=pump_features,
        dump_features=dump_features,
        token_risk=token_risk,
        buyer_independence_verified=history_eval["buyer_independence_verified"],
    )
    return jsonable_encoder(
        {
            "data_status": "stored_evaluation",
            "mint": mint,
            "as_of": cutoff,
            "token_risk": token_risk,
            "candidate_state": state_eval,
        },
        custom_encoder={Decimal: str},
    )
