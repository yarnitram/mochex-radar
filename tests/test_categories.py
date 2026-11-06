import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from mochex_radar.api import app
from mochex_radar.categories import (
    CategoryRegistry,
    build_category_view,
    load_category_registry,
)

NOW = datetime(2026, 11, 5, tzinfo=UTC).isoformat()
MINT_OVERLAP = "So11111111111111111111111111111111111111112"
MINT_CONFLICT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MINT_UNLISTED = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"


def test_default_registry_preserves_seven_core_pairs_and_tags_doge_as_meme():
    registry = load_category_registry()
    view = build_category_view(registry)
    assert view["summary"]["total_assets"] == 7
    assert view["summary"]["meme_count"] == 1
    assert view["summary"]["coverage_gap_count"] == 0
    doge = next(a for a in view["assets"] if a["asset_id"].endswith(":DOGE_USDT"))
    assert doge["categories"] == ["meme"]
    assert doge["risk_model"] == "cex_usdt_perpetual"


def test_overlapping_categories_conflicting_sources_and_observed_coverage_gaps():
    registry = CategoryRegistry.model_validate({
        "version": 1,
        "entries": [
            {
                "asset_id": "cex:mexc-usdt-futures:DOGE_USDT",
                "categories": ["meme"],
                "category_source": "operator:core",
                "assigned_at": NOW,
                "rationale": "Curated meme perp",
            },
            {
                "asset_id": f"solana:mint:{MINT_OVERLAP}",
                "categories": ["meme", "ai"],
                "category_source": "operator:watchlist",
                "assigned_at": NOW,
                "rationale": "AI agent meme token",
            },
            {
                "asset_id": f"solana:mint:{MINT_CONFLICT}",
                "categories": ["meme"],
                "category_source": "source-a",
                "assigned_at": NOW,
                "rationale": "Claimed meme",
            },
            {
                "asset_id": f"solana:mint:{MINT_CONFLICT}",
                "categories": ["ai"],
                "category_source": "source-b",
                "assigned_at": NOW,
                "rationale": "Claimed AI",
            },
        ],
    })
    view = build_category_view(registry, observed_solana_mints=[MINT_UNLISTED])
    summary = view["summary"]
    assert summary["overlapping_meme_ai_count"] == 1
    assert summary["conflict_count"] == 1
    # 6 missing core pairs + 1 conflicting Solana mint + 1 unlisted observed Solana mint = 8 gaps
    assert summary["coverage_gap_count"] == 8

    overlap = next(a for a in view["assets"] if a["asset_id"] == f"solana:mint:{MINT_OVERLAP}")
    assert overlap["categories"] == ["ai", "meme"]
    assert overlap["risk_model"] == "solana_spl_token"
    assert overlap["coverage_gap"] is False

    conflict = next(a for a in view["assets"] if a["asset_id"] == f"solana:mint:{MINT_CONFLICT}")
    assert conflict["categories"] == ["unclassified"]
    assert conflict["conflict"] is True and conflict["coverage_gap"] is True

    unlisted = next(a for a in view["assets"] if a["asset_id"] == f"solana:mint:{MINT_UNLISTED}")
    assert unlisted["categories"] == ["unclassified"]
    assert unlisted["coverage_gap"] is True

    ai_only = build_category_view(registry, category_filter="ai")
    assert [a["asset_id"] for a in ai_only["assets"]] == [f"solana:mint:{MINT_OVERLAP}"]


def test_schema_rejects_unclassified_overlap_unknown_identity_and_duplicates():
    base = {
        "asset_id": "cex:mexc-usdt-futures:DOGE_USDT",
        "categories": ["meme"],
        "category_source": "operator:core",
        "assigned_at": NOW,
        "rationale": "Curated",
    }
    for invalid_entry in (
        {**base, "categories": ["unclassified", "meme"]},
        {**base, "asset_id": "cex:mexc-usdt-futures:UNKNOWN_USDT"},
        {**base, "asset_id": "solana:mint:not-base58"},
        {**base, "assigned_at": "2026-11-05T00:00:00"},
    ):
        with pytest.raises(ValueError):
            CategoryRegistry.model_validate({"version": 1, "entries": [invalid_entry]})

    with pytest.raises(ValueError, match="duplicate"):
        CategoryRegistry.model_validate({"version": 1, "entries": [base, base]})


def test_category_registry_api_filtering_and_error_handling(monkeypatch, tmp_path):
    monkeypatch.delenv("RADAR_API_TOKEN", raising=False)
    monkeypatch.delenv("CATEGORY_REGISTRY_PATH", raising=False)
    client = TestClient(app)

    all_res = client.get("/api/v1/categories/registry")
    assert all_res.status_code == 200
    assert all_res.json()["summary"]["total_assets"] == 7

    meme_res = client.get("/api/v1/categories/registry?category=meme")
    assert meme_res.status_code == 200
    assert [a["asset_id"] for a in meme_res.json()["assets"]] == ["cex:mexc-usdt-futures:DOGE_USDT"]

    assert client.get("/api/v1/categories/registry?category=invalid").status_code == 422

    bad_file = tmp_path / "bad-registry.json"
    bad_file.write_text(json.dumps({"version": 1, "entries": "invalid"}), encoding="utf-8")
    monkeypatch.setenv("CATEGORY_REGISTRY_PATH", str(bad_file))
    assert client.get("/api/v1/categories/registry").status_code == 503
