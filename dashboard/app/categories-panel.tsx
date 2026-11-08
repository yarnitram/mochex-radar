"use client";

import { useState } from "react";
import type { Snapshot } from "@/lib/contracts";

type FilterMode = "all" | "meme" | "ai" | "unclassified" | "gaps";

const FILTERS: { id: FilterMode; label: string }[] = [
  { id: "all", label: "All registry" },
  { id: "meme", label: "Meme sector" },
  { id: "ai", label: "AI sector" },
  { id: "unclassified", label: "Unclassified" },
  { id: "gaps", label: "Coverage gaps" },
];

const date = (value: string | null) =>
  value
    ? new Date(value).toLocaleString(undefined, { hour12: false })
    : "No provenance timestamp";

export default function CategoriesPanel({
  snapshot,
  outdated,
}: {
  snapshot: Snapshot | null;
  outdated: boolean;
}) {
  const [filter, setFilter] = useState<FilterMode>("all");
  const service = snapshot?.categories;
  const data = service?.status === "available" ? service.data : null;
  const allAssets = data?.assets || [];
  const filtered = allAssets.filter((item) => {
    if (filter === "all") return true;
    if (filter === "gaps") return item.coverage_gap;
    return item.categories.includes(filter);
  });

  return (
    <section
      className="panel"
      id="categories"
      aria-labelledby="categories-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="categories-title">Meme and AI category coverage</h2>
          <p>
            Provenance-backed sector tags · Distinct CEX &amp; Solana risk
            models · Explicit coverage gaps
          </p>
        </div>
        <div className="filters" role="group" aria-label="Category registry filter">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      {data ? (
        <>
          <div className="panel-body">
            <p className="context-note">
              Catalog summary: {data.summary.total_assets} assets ·{" "}
              {data.summary.meme_count} meme · {data.summary.ai_count} AI ·{" "}
              {data.summary.overlapping_meme_ai_count} overlapping Meme+AI ·{" "}
              {data.summary.coverage_gap_count} coverage gaps
              {data.summary.conflict_count
                ? ` · ${data.summary.conflict_count} conflicts`
                : ""}
            </p>
          </div>
          {filtered.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Canonical asset</th>
                    <th>Venue / risk model</th>
                    <th>Categories</th>
                    <th>Provenance / rationale</th>
                    <th>Coverage status</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((asset) => (
                    <tr key={asset.asset_id}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span className="mint" title={asset.asset_id}>
                            {asset.asset_id}
                          </span>
                          {asset.asset_id.startsWith("solana:mint:") && (
                            <button
                              type="button"
                              className="badge"
                              style={{ cursor: "pointer", fontSize: "10px", padding: "2px 6px" }}
                              onClick={() => window.dispatchEvent(new CustomEvent("select-candidate-mint", { detail: asset.asset_id.replace(/^solana:mint:/, "") }))}
                              title={`Inspect candidate ${asset.asset_id.replace(/^solana:mint:/, "")}`}
                            >
                              Inspect
                            </button>
                          )}
                        </div>
                      </td>
                      <td>
                        <span>{asset.asset_class.replaceAll("_", " ")}</span>
                        <small className="provenance">
                          {asset.risk_model.replaceAll("_", " ")}
                        </small>
                      </td>
                      <td>{asset.categories.join(" · ")}</td>
                      <td>
                        {asset.category_sources.length ? (
                          <>
                            <span>{asset.category_sources.join(", ")}</span>
                            <small className="provenance">
                              {asset.rationale} ({date(asset.assigned_at)})
                            </small>
                          </>
                        ) : (
                          <span className="muted">
                            Uncataloged asset — no verified provenance
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            outdated
                              ? "outdated"
                              : asset.conflict
                                ? "blocked"
                                : asset.coverage_gap
                                  ? "caution"
                                  : "current"
                          }`}
                        >
                          {outdated
                            ? "outdated"
                            : asset.conflict
                              ? "conflict"
                              : asset.coverage_gap
                                ? "coverage gap"
                                : "cataloged"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">
              <h3>No matching category records</h3>
              <p>No assets match the selected category registry filter.</p>
            </div>
          )}
        </>
      ) : (
        <div className="empty">
          <h3>
            {snapshot
              ? "Category registry unavailable"
              : "Waiting for category registry"}
          </h3>
          <p>
            Provenance-backed Meme and AI classifications require the category
            registry service. Ticker symbols are never used to guess categories.
          </p>
        </div>
      )}
      <div className="panel-foot">
        Overlapping Meme and AI tags preserve separate CEX perpetual and Solana
        SPL token risk models. Conflicting or uncataloged assets remain
        unclassified coverage gaps.
      </div>
    </section>
  );
}
