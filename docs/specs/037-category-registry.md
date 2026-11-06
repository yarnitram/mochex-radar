# Spec 037 — Provenance-backed Meme and AI category registry

Implements Roadmap Area 4 in `mochex_radar/categories.py`, `config/category-registry.json`,
and `GET /api/v1/categories/registry`.

- Preserves canonical venue-scoped identities and distinct risk models:
  `cex:mexc-usdt-futures:<PAIR>` (`cex_usdt_perpetual`) and `solana:mint:<MINT>`
  (`solana_spl_token`). Never infers categories from ticker symbols or substrings.
- Supports overlapping tags (`["meme", "ai"]`) with mandatory `category_source`, UTC
  `assigned_at`, and `rationale`, while prohibiting `"unclassified"` from combining with
  sector tags.
- Exposes coverage gaps (`coverage_gap: true`) for any uncataloged core pair or observed
  Solana mint, and resolves conflicting multi-source claims to `["unclassified"]` with
  `conflict: true` and `coverage_gap: true`.
