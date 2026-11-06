"""Provenance-backed Meme and AI category registry across CEX futures and Solana DEX assets."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cluster_radar.providers.solana_authorities import decode_pubkey
from mochex_radar.markets import core_markets

REGISTRY_VERSION = "category-registry-v1"
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "category-registry.json"
CategoryTag = Literal["meme", "ai", "unclassified"]
CORE_ASSET_IDS = {m.asset_id for m in core_markets()}


def classify_asset_identity(asset_id: str) -> tuple[str, str]:
    """Return (asset_class, risk_model) strictly from canonical asset_id; never guess from ticker."""
    if asset_id in CORE_ASSET_IDS:
        return "cex_futures", "cex_usdt_perpetual"
    if asset_id.startswith("solana:mint:"):
        mint = asset_id.removeprefix("solana:mint:")
        decode_pubkey(mint)
        return "solana_dex", "solana_spl_token"
    raise ValueError(f"unsupported category asset_id: {asset_id}")


class CategoryClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=120)
    categories: list[CategoryTag] = Field(min_length=1, max_length=2)
    category_source: str = Field(min_length=1, max_length=200)
    assigned_at: datetime
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_claim(self):
        classify_asset_identity(self.asset_id)
        if self.assigned_at.tzinfo is None or self.assigned_at.utcoffset() != timedelta(0):
            raise ValueError("assigned_at must be UTC")
        if not self.category_source.strip() or not self.rationale.strip():
            raise ValueError("category_source and rationale must be non-blank")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("duplicate category tag in claim")
        if "unclassified" in self.categories and len(self.categories) > 1:
            raise ValueError("unclassified cannot be combined with meme or ai")
        return self


class CategoryRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    entries: list[CategoryClaim] = Field(max_length=500)

    @model_validator(mode="after")
    def unique_asset_source_pairs(self):
        pairs = [(e.asset_id, e.category_source) for e in self.entries]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate (asset_id, category_source) in category registry")
        return self


def load_category_registry(path: Path = DEFAULT_REGISTRY_PATH) -> CategoryRegistry:
    if path.is_symlink():
        raise ValueError("category registry path must not be a symlink")
    raw = path.read_bytes()
    if len(raw) > 500_000:
        raise ValueError("category registry exceeds 500 KB")
    return CategoryRegistry.model_validate_json(raw)


def build_category_view(
    registry: CategoryRegistry,
    *,
    observed_solana_mints: list[str] | tuple[str, ...] = (),
    category_filter: Literal["all", "meme", "ai", "unclassified"] = "all",
) -> dict:
    """Resolve provenance-backed categories, preserving risk models and exposing coverage gaps."""
    if category_filter not in ("all", "meme", "ai", "unclassified"):
        raise ValueError("category_filter must be all, meme, ai, or unclassified")

    by_asset: dict[str, list[CategoryClaim]] = {}
    for entry in registry.entries:
        by_asset.setdefault(entry.asset_id, []).append(entry)

    universe: list[str] = [m.asset_id for m in core_markets()]
    for asset_id in by_asset:
        if asset_id not in universe:
            universe.append(asset_id)
    for mint in observed_solana_mints:
        decode_pubkey(mint)
        solana_id = f"solana:mint:{mint}"
        if solana_id not in universe:
            universe.append(solana_id)

    resolved: list[dict] = []
    for asset_id in universe:
        asset_class, risk_model = classify_asset_identity(asset_id)
        claims = by_asset.get(asset_id, [])
        if not claims:
            resolved.append({
                "asset_id": asset_id,
                "asset_class": asset_class,
                "risk_model": risk_model,
                "categories": ["unclassified"],
                "category_sources": [],
                "assigned_at": None,
                "rationale": None,
                "coverage_gap": True,
                "conflict": False,
            })
            continue

        distinct_tag_sets = {tuple(sorted(c.categories)) for c in claims}
        if len(distinct_tag_sets) > 1:
            resolved.append({
                "asset_id": asset_id,
                "asset_class": asset_class,
                "risk_model": risk_model,
                "categories": ["unclassified"],
                "category_sources": sorted({c.category_source for c in claims}),
                "assigned_at": None,
                "rationale": "Conflicting category claims across sources; left unclassified",
                "coverage_gap": True,
                "conflict": True,
            })
            continue

        canonical_tags = list(next(iter(distinct_tag_sets)))
        latest_assigned = max(c.assigned_at for c in claims).isoformat()
        resolved.append({
            "asset_id": asset_id,
            "asset_class": asset_class,
            "risk_model": risk_model,
            "categories": canonical_tags,
            "category_sources": sorted({c.category_source for c in claims}),
            "assigned_at": latest_assigned,
            "rationale": claims[0].rationale,
            "coverage_gap": False,
            "conflict": False,
        })

    summary = {
        "total_assets": len(resolved),
        "meme_count": sum(1 for r in resolved if "meme" in r["categories"]),
        "ai_count": sum(1 for r in resolved if "ai" in r["categories"]),
        "overlapping_meme_ai_count": sum(
            1 for r in resolved if "meme" in r["categories"] and "ai" in r["categories"]
        ),
        "unclassified_count": sum(1 for r in resolved if r["categories"] == ["unclassified"]),
        "coverage_gap_count": sum(1 for r in resolved if r["coverage_gap"]),
        "conflict_count": sum(1 for r in resolved if r["conflict"]),
    }

    filtered = (
        resolved
        if category_filter == "all"
        else [r for r in resolved if category_filter in r["categories"]]
    )
    return {
        "registry_version": REGISTRY_VERSION,
        "filter": category_filter,
        "research_only": True,
        "signals_enabled": False,
        "summary": summary,
        "assets": filtered,
    }
