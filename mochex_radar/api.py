"""Read only market data and collector status API."""

import asyncio
import os
import hmac
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import httpx
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from mochex_radar.readiness import database_ready

from cluster_radar.providers.dexscreener import BudgetExceeded, DexScreener, ProviderUnavailable

from mochex_radar.futures_feed import INTERVALS, FeedUnavailable, fetch_latest_closed
from mochex_radar.btc_context import classify

from mochex_radar.markets import core_markets
from mochex_radar.storage import latest_cycle, recent_btc_candles, recent_candles
from mochex_radar.feature_snapshot import core_feature_snapshot
from mochex_radar.dex_store import initialize_dex_store, observation_history, store_observations
from mochex_radar.provider_budget import initialize_budget_store, PersistentDexScreener
from mochex_radar.dex_worker import recent_scans
from mochex_radar.dashboard import core_snapshot
from mochex_radar.research_status import research_status
from mochex_radar.categories import DEFAULT_REGISTRY_PATH, build_category_view, load_category_registry
from mochex_radar.alert_store import outbox_status
from mochex_radar.profile_discovery import recent_polls, discovered_catalog
from mochex_radar.authority_checks import PersistentAuthorities, authority_history, authority_snapshot, initialize_authority_store, store_authority
from mochex_radar.candidate_evaluation import (
    PersistentHolderConcentration,
    evaluate_stored_candidate,
    holder_history,
    initialize_holder_store,
    store_holder_observation,
)
from cluster_radar.providers.solana_authorities import SolanaAuthorities
from cluster_radar.providers.solana_holders import SolanaHolderConcentration
from mochex_radar.live_state import LiveSnapshots, RedisError

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.live_store = LiveSnapshots.from_url(os.environ["REDIS_URL"]) if os.environ.get("REDIS_URL") else None
    app.state.dex_provider = None
    app.state.authority_provider = None
    app.state.holder_provider = None
    async with httpx.AsyncClient() as client:
        solana_rpc_url = os.environ.get("SOLANA_RPC_URL") or None
        if os.environ.get("SOLANA_AUTHORITIES_ENABLED", "false").lower() == "true":
            authority_dsn = os.environ.get("DATABASE_URL")
            if not authority_dsn:
                raise ValueError("authority checks require DATABASE_URL")
            await asyncio.to_thread(initialize_authority_store, authority_dsn)
            auth_kwargs = {"rpc_url": solana_rpc_url} if solana_rpc_url else {}
            app.state.authority_provider = PersistentAuthorities(
                SolanaAuthorities(client, max_requests=2**63-1, **auth_kwargs), authority_dsn,
                int(os.environ.get("SOLANA_AUTHORITY_DAILY_REQUESTS", "100")),
            )
        if os.environ.get("SOLANA_HOLDERS_ENABLED", "false").lower() == "true":
            holder_dsn = os.environ.get("DATABASE_URL")
            if not holder_dsn:
                raise ValueError("holder checks require DATABASE_URL")
            await asyncio.to_thread(initialize_holder_store, holder_dsn)
            holder_kwargs = {"rpc_url": solana_rpc_url} if solana_rpc_url else {}
            app.state.holder_provider = PersistentHolderConcentration(
                SolanaHolderConcentration(client, max_requests=2**63-1, **holder_kwargs),
                holder_dsn,
                int(os.environ.get("SOLANA_HOLDER_DAILY_REQUESTS", "100")),
            )
        if os.environ.get("DEX_LOOKUP_ENABLED", "false").lower() == "true":
            if dsn := os.environ.get("DATABASE_URL"):
                await asyncio.to_thread(initialize_dex_store, dsn)
                await asyncio.to_thread(initialize_budget_store, dsn)
            app.state.dex_provider = DexScreener(
                client, max_requests=int(os.environ.get("DEX_LOOKUP_MAX_REQUESTS", "100"))
            )
            if dsn:
                app.state.dex_provider = PersistentDexScreener(
                    app.state.dex_provider, dsn,
                    daily_limit=int(os.environ.get("DEX_LOOKUP_DAILY_REQUESTS", "100")),
                )
        try:
            yield
        finally:
            if app.state.live_store:
                await app.state.live_store.close()


app = FastAPI(title="Mochex Radar", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def private_api_access(request: Request, call_next):
    token = os.environ.get("RADAR_API_TOKEN")
    if token and (request.url.path.startswith(("/api/", "/docs", "/redoc")) or request.url.path == "/openapi.json"):
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            return JSONResponse({"detail": "API access token required"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return await call_next(request)


@app.get("/health/ready")
async def readiness(request: Request):
    durable = await asyncio.to_thread(database_ready, os.environ.get("DATABASE_URL"))
    live = getattr(request.app.state, "live_store", None)
    cache = "disabled"
    if live:
        try:
            await live.client.ping()
            cache = "ready"
        except RedisError:
            cache = "unavailable"
    return JSONResponse({"status": "not_ready" if not durable else "degraded" if cache == "unavailable" else "ready",
                         "durable_store_ready": durable, "live_cache": cache}, status_code=200 if durable else 503)


@app.get("/api/v1/live/core")
async def live_core(request: Request, interval: str = "15m"):
    if interval not in INTERVALS:
        raise HTTPException(status_code=422, detail="interval must be 15m or 1h")
    live = getattr(request.app.state, "live_store", None)
    if live is None:
        return {"data_status": "live_disabled", "provisional": True, "finalized": False, "signals_enabled": False}
    try:
        return await live.snapshot(interval)
    except RedisError:
        raise HTTPException(status_code=503, detail="ephemeral live snapshots unavailable") from None


def get_authority_provider(request: Request):
    provider = getattr(request.app.state, "authority_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Solana authority checks disabled")
    return provider


def get_holder_provider(request: Request):
    provider = getattr(request.app.state, "holder_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Solana holder checks disabled")
    return provider


@app.get("/api/v1/security/authorities/snapshot")
async def stored_authority_snapshot(limit: int = 100):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {"status":"storage_disabled", "observations":[]}
    try:
        return await asyncio.to_thread(authority_snapshot, dsn, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="limit must be 1..100") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="stored authority snapshot unavailable") from exc


@app.get("/api/v1/security/solana/{mint}/authorities")
async def solana_authorities(mint: str, provider: PersistentAuthorities = Depends(get_authority_provider)):
    try:
        observation = await provider.check(mint)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="authority request budget exhausted") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="authority evidence unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid Solana public key") from exc
    try:
        await asyncio.to_thread(store_authority, provider.dsn, observation)
    except (psycopg.Error, ValueError) as exc:
        raise HTTPException(status_code=503, detail="authority evidence storage unavailable") from exc
    return {"data_status":"observed", "partial":True, "persisted":True,
            "evidence":jsonable_encoder(asdict(observation)), "freshness_lifetime_seconds":900}


@app.get("/api/v1/security/solana/{mint}/authorities/history")
async def solana_authority_history(mint: str, as_of: datetime, limit: int = 10):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="authority evidence storage disabled")
    try:
        history = await asyncio.to_thread(authority_history, dsn, mint, as_of, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="valid public key, UTC cutoff and limit 1..100 required") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="authority history unavailable") from exc
    return {"data_status":"stored_partial_evidence", "observations":history,
            "security_status":"UNKNOWN", "approved_pump_watch":False}


@app.get("/api/v1/security/solana/{mint}/holders")
async def solana_holders(mint: str, provider: PersistentHolderConcentration = Depends(get_holder_provider)):
    try:
        observation = await provider.check(mint)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="holder request budget exhausted") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="holder concentration evidence unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid Solana public key") from exc
    try:
        await asyncio.to_thread(store_holder_observation, provider.dsn, observation)
    except (psycopg.Error, ValueError) as exc:
        raise HTTPException(status_code=503, detail="holder concentration storage unavailable") from exc
    raw_dict = asdict(observation)
    raw_dict.pop("holder_evidence", None)
    return {
        "data_status": "observed",
        "partial": True,
        "persisted": True,
        "evidence": jsonable_encoder(raw_dict, custom_encoder={Decimal: str}),
        "freshness_lifetime_seconds": 900,
    }


@app.get("/api/v1/security/solana/{mint}/holders/history")
async def solana_holder_history(mint: str, as_of: datetime, limit: int = 10):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="holder concentration storage disabled")
    try:
        history = await asyncio.to_thread(holder_history, dsn, mint, as_of, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="valid public key, UTC cutoff and limit 1..100 required") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="holder concentration history unavailable") from exc
    return {
        "data_status": "stored_partial_evidence",
        "observations": history,
        "security_status": "UNKNOWN",
        "approved_pump_watch": False,
    }


@app.get("/api/v1/candidates/solana/{mint}/evaluation")
async def solana_candidate_evaluation(mint: str, as_of: datetime | None = None):
    dsn = os.environ.get("DATABASE_URL")
    try:
        return await asyncio.to_thread(evaluate_stored_candidate, dsn, mint, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="valid Solana mint and UTC as_of required") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="stored candidate evaluation unavailable") from exc


def get_dex_provider(request: Request) -> DexScreener | PersistentDexScreener:
    provider = getattr(request.app.state, "dex_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="DEX lookup disabled")
    return provider


@app.get("/api/v1/dex/solana/{mint}/pools")
async def solana_pools(mint: str, provider: DexScreener = Depends(get_dex_provider)):
    try:
        pools = await provider.pools(mint)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="DEX lookup request budget exhausted") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="DEX pool data unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid Solana mint") from exc
    persisted = False
    if dsn := os.environ.get("DATABASE_URL"):
        try:
            await asyncio.to_thread(store_observations, dsn, pools)
            persisted = True
        except (psycopg.Error, ValueError) as exc:
            raise HTTPException(status_code=503, detail="DEX observation storage unavailable") from exc
    return {
        "data_status": "observed",
        "persisted": persisted,
        "security_status": "UNKNOWN",
        "approved_pump_watch": False,
        "pools": [jsonable_encoder(asdict(pool), custom_encoder={Decimal: str}) for pool in pools],
    }


@app.get("/api/v1/dex/solana/{mint}/history")
async def solana_pool_history(mint: str, as_of: datetime, limit: int = 100):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DEX observation storage disabled")
    try:
        observations = await asyncio.to_thread(observation_history, dsn, mint, as_of, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="UTC as_of and limit 1..1000 required") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="DEX observation history unavailable") from exc
    return {"data_status": "stored_observations", "observations": observations}


async def get_http_client():
    async with httpx.AsyncClient() as client:
        yield client


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/dashboard/core")
async def dashboard_core():
    try:
        return await asyncio.to_thread(core_snapshot, os.environ.get("DATABASE_URL"))
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="stored core observations unavailable") from exc


@app.get("/api/v1/categories/registry")
async def category_registry(category: str = "all"):
    if category not in ("all", "meme", "ai", "unclassified"):
        raise HTTPException(status_code=422, detail="category must be all, meme, ai, or unclassified")
    path = Path(os.environ.get("CATEGORY_REGISTRY_PATH") or DEFAULT_REGISTRY_PATH)
    try:
        registry = await asyncio.to_thread(load_category_registry, path)
        return build_category_view(registry, category_filter=category)
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="category registry unavailable") from None


@app.get("/api/v1/research/status")
async def forward_research_status():
    root = os.environ.get("RESEARCH_STATUS_ROOT")
    ids = os.environ.get("RESEARCH_STATUS_PLAN_IDS", "").split(",")
    try:
        return await asyncio.to_thread(research_status, Path(root) if root else None, [v for v in ids if v])
    except ValueError:
        raise HTTPException(status_code=503, detail="research status configuration unavailable") from None


@app.get("/api/v1/features/core")
async def core_features(interval: str = "15m"):
    if interval not in INTERVALS:
        raise HTTPException(status_code=422, detail="interval must be 15m or 1h")
    dsn = os.environ.get("DATABASE_URL")
    load = (lambda market_id, iv, as_of, limit: recent_candles(dsn, market_id, iv, as_of, limit)) if dsn else None
    try:
        return await asyncio.to_thread(core_feature_snapshot, load, interval)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="stored core features unavailable") from exc


@app.get("/api/v1/alerts/status")
async def alert_status():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {"status": "storage_disabled", "states": {}}
    try:
        status = await asyncio.to_thread(outbox_status, dsn)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="alert outbox status unavailable") from exc
    return {"status": "stored_outbox", **status}


@app.get("/api/v1/discovery/profiles/polls")
async def profile_polls(limit: int = 100):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {"status": "storage_disabled", "polls": []}
    try:
        polls = await asyncio.to_thread(recent_polls, dsn, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="limit must be 1..1000") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="profile poll history unavailable") from exc
    return {"status": "stored_polls", "polls": polls, "coverage": "profile_window_only"}


@app.get("/api/v1/discovery/profiles/mints")
async def profile_mints(limit: int = 100, offset: int = 0):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {"status": "storage_disabled", "mints": []}
    try:
        mints = await asyncio.to_thread(discovered_catalog, dsn, limit, offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="limit 1..1000 and offset 0..10000 required") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="discovered mint catalog unavailable") from exc
    return {"status": "current_catalog", "mints": mints, "coverage": "profile_window_only",
            "category": "unclassified", "security_status": "UNKNOWN", "approved_pump_watch": False}


@app.get("/api/v1/dex/scans")
async def dex_scans(limit: int = 100):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {"status": "disabled", "scans": []}
    try:
        scans = await asyncio.to_thread(recent_scans, dsn, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="limit must be 1..1000") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="DEX scan history unavailable") from exc
    return {"status": "stored_scans", "scans": scans}


@app.get("/api/v1/collector/status")
async def collector_status() -> dict[str, object]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {"status": "disabled", "last_cycle": None}
    try:
        cycle = await asyncio.to_thread(latest_cycle, dsn)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="collector status unavailable") from exc
    return {"status": "completed" if cycle else "pending", "last_cycle": cycle}


@app.get("/api/v1/market-context/btc")
async def btc_context() -> dict[str, object]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return classify([], datetime.now(timezone.utc))
    try:
        candles = await asyncio.to_thread(recent_btc_candles, dsn)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="BTC context unavailable") from exc
    return classify(candles, datetime.now(timezone.utc))


@app.get("/api/v1/markets/core")
def list_core_markets() -> dict[str, object]:
    markets = core_markets()
    return {
        "data_status": "configuration_only",
        "markets": [
            {
                "asset_id": market.asset_id,
                "venue": market.venue,
                "market_id": market.market_id,
                "base": market.base,
                "quote": market.quote,
            }
            for market in markets
        ],
    }


@app.get("/api/v1/market-data/{symbol}/{interval}")
async def latest_candle(symbol: str, interval: str, client: httpx.AsyncClient = Depends(get_http_client)) -> dict[str, object]:
    market = next((item for item in core_markets() if item.market_id == symbol.upper()), None)
    if market is None or interval not in INTERVALS:
        raise HTTPException(status_code=404, detail="unsupported market or interval")
    try:
        candle = await fetch_latest_closed(market, interval, client)
    except FeedUnavailable as exc:
        raise HTTPException(status_code=503, detail="market data unavailable") from exc
    return {"data_status": "observed", "candle": candle.to_dict()}
