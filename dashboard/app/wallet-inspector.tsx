"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  Snapshot,
  WalletHistoryOverview,
} from "@/lib/contracts";

const PINNED_WALLETS_KEY = "mochex_radar_pinned_wallets";

const SAMPLE_WALLETS: Array<{ address: string; label: string }> = [
  { address: "11111111111111111111111111111111", label: "System Program" },
  { address: "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1", label: "Raydium Authority" },
  { address: "TSLvdd1pWpHVjahSpsvCXqbgdyJxLdUzp8LkWk2uwMr", label: "Pump.fun Authority" },
];

export default function WalletInspector({
  snapshot,
  outdated,
}: {
  snapshot: Snapshot | null;
  outdated: boolean;
}) {
  const [addressInput, setAddressInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WalletHistoryOverview | null>(null);
  const [inspectedAddress, setInspectedAddress] = useState<string | null>(null);
  const [pinnedWallets, setPinnedWallets] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);

  // Load pinned wallets from localStorage
  useEffect(() => {
    try {
      const raw = localStorage.getItem(PINNED_WALLETS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setPinnedWallets(parsed.filter((a) => typeof a === "string"));
        }
      }
    } catch {
      // Ignore localStorage read issues
    }
  }, []);

  function handleTogglePin(address: string) {
    let updated: string[];
    if (pinnedWallets.includes(address)) {
      updated = pinnedWallets.filter((a) => a !== address);
    } else {
      updated = [...pinnedWallets, address];
    }
    setPinnedWallets(updated);
    try {
      localStorage.setItem(PINNED_WALLETS_KEY, JSON.stringify(updated));
    } catch {
      // Ignore localStorage write issues
    }
  }

  const inspect = useCallback(
    async (targetAddress: string, pollOnChain: boolean = false) => {
      const trimmed = targetAddress.trim();
      if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(trimmed)) {
        setError("Invalid Solana wallet address (expected base58 public key, 32-44 chars)");
        return;
      }
      setBusy(true);
      setError(null);
      setCopied(false);
      try {
        const queryParams = new URLSearchParams({
          address: trimmed,
          ...(pollOnChain ? { poll: "true" } : {}),
        });
        const res = await fetch(`/api/wallet?${queryParams.toString()}`, {
          cache: "no-store",
        });
        if (!res.ok) {
          if (res.status === 400) {
            setError("Invalid Solana public key format.");
            return;
          }
          if (res.status === 503) {
            setError("Wallet history storage unavailable or disabled.");
            return;
          }
          throw new Error(`Upstream returned ${res.status}`);
        }
        const json = await res.json();
        if (json.status === "available" && json.data) {
          setResult(json.data);
          setInspectedAddress(trimmed);
        } else {
          setError(json.reason || "Wallet history unavailable");
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load wallet history");
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  // Global event listener for cross-panel inspection
  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<string>;
      if (custom.detail && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(custom.detail)) {
        setAddressInput(custom.detail);
        void inspect(custom.detail);
        const target = document.getElementById("wallet");
        if (target) {
          target.scrollIntoView({ behavior: "smooth" });
        }
      }
    };
    window.addEventListener("select-wallet-address", handler);
    return () => window.removeEventListener("select-wallet-address", handler);
  }, [inspect]);

  function handleFormSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (addressInput.trim()) {
      void inspect(addressInput.trim());
    }
  }

  const handleCopy = () => {
    if (!inspectedAddress) return;
    navigator.clipboard.writeText(inspectedAddress);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Collect dynamically discovered authority wallets from snapshot
  const dynamicWallets: Array<{ address: string; label: string }> = [];
  const seenAddresses = new Set<string>(SAMPLE_WALLETS.map((s) => s.address));
  const observations = snapshot?.authorities?.data?.observations || [];
  for (const obs of observations) {
    const ma = obs.evidence.mint_authority;
    if (ma && !seenAddresses.has(ma)) {
      seenAddresses.add(ma);
      dynamicWallets.push({
        address: ma,
        label: `Mint Auth (${ma.slice(0, 4)}…${ma.slice(-4)})`,
      });
    }
    const fa = obs.evidence.freeze_authority;
    if (fa && !seenAddresses.has(fa)) {
      seenAddresses.add(fa);
      dynamicWallets.push({
        address: fa,
        label: `Freeze Auth (${fa.slice(0, 4)}…${fa.slice(-4)})`,
      });
    }
    if (dynamicWallets.length >= 4) break;
  }

  const isCurrentPinned = inspectedAddress ? pinnedWallets.includes(inspectedAddress) : false;

  return (
    <section className="panel" id="wallet" aria-labelledby="wallet-title">
      <div className="panel-heading">
        <div>
          <h2 id="wallet-title">Wallet intelligence &amp; funding clusters</h2>
          <p>
            Solana wallet history · Bounded batch provenance · Potential shared-funding groups
          </p>
        </div>
        <span className={`badge ${outdated ? "outdated" : result ? "current" : ""}`}>
          {outdated
            ? "outdated"
            : busy
              ? "evaluating…"
              : result
                ? `${result.batches_count} batches`
                : "ready"}
        </span>
      </div>

      <p className="discovery-note">
        Funding clusters reflect potential shared-funding relations only. Common funding does not prove
        unified control or common intent. Transaction history batches are immutable, bounded, and
        point-in-time gated; signals remain disabled.
      </p>

      {/* Search Input & Controls */}
      <form onSubmit={handleFormSubmit} className="discovery-controls">
        <label style={{ flex: 1 }}>
          Inspect Solana wallet address
          <input
            type="search"
            aria-label="Solana wallet address"
            placeholder="Enter base58 wallet address..."
            value={addressInput}
            onChange={(e) => setAddressInput(e.target.value)}
            disabled={busy}
          />
        </label>
        <button
          type="submit"
          className="btn"
          disabled={busy || !addressInput.trim()}
          style={{ alignSelf: "flex-end" }}
        >
          {busy ? "Inspecting…" : "Inspect wallet"}
        </button>
      </form>

      {/* Quick-select toolbar */}
      <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
        {/* Pinned Wallets */}
        {pinnedWallets.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
            <span style={{ fontSize: "11px", color: "var(--color-muted)", fontWeight: 600 }}>
              ★ Pinned ({pinnedWallets.length}):
            </span>
            {pinnedWallets.map((addr) => (
              <span
                key={addr}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  background: "rgba(255, 215, 0, 0.08)",
                  border: "1px solid rgba(255, 215, 0, 0.2)",
                  borderRadius: "4px",
                  padding: "2px 4px 2px 8px",
                  fontSize: "11px",
                  gap: "4px",
                }}
              >
                <button
                  type="button"
                  style={{
                    background: "none",
                    border: "none",
                    color: "inherit",
                    cursor: "pointer",
                    padding: 0,
                    fontFamily: "monospace",
                  }}
                  onClick={() => {
                    setAddressInput(addr);
                    void inspect(addr);
                  }}
                  title={`Inspect pinned wallet ${addr}`}
                >
                  {addr.slice(0, 4)}…{addr.slice(-4)}
                </button>
                <button
                  type="button"
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--color-muted)",
                    cursor: "pointer",
                    fontSize: "12px",
                    lineHeight: 1,
                    padding: "0 2px",
                  }}
                  onClick={() => handleTogglePin(addr)}
                  title={`Unpin wallet ${addr}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Suggested Wallets */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
          <span style={{ fontSize: "11px", color: "var(--color-muted)", fontWeight: 600 }}>
            Quick select:
          </span>
          {SAMPLE_WALLETS.concat(dynamicWallets).map((item) => (
            <button
              key={item.address}
              type="button"
              className="badge"
              style={{
                cursor: "pointer",
                fontSize: "11px",
                padding: "3px 8px",
                background: "rgba(255, 255, 255, 0.05)",
              }}
              onClick={() => {
                setAddressInput(item.address);
                void inspect(item.address);
              }}
              title={item.address}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="alert caution" style={{ marginTop: "12px" }}>
          {error}
        </div>
      )}

      {/* Inspected Wallet Banner */}
      {inspectedAddress && result && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "rgba(255, 255, 255, 0.04)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "8px",
            padding: "10px 14px",
            marginTop: "16px",
            flexWrap: "wrap",
            gap: "10px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
            <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--color-muted)" }}>
              WALLET:
            </span>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "13px",
                color: "var(--color-text)",
                letterSpacing: "0.5px",
                wordBreak: "break-all",
              }}
            >
              {inspectedAddress}
            </span>
            <button
              type="button"
              className="badge"
              style={{
                cursor: "pointer",
                fontSize: "11px",
                padding: "2px 8px",
                background: copied ? "rgba(46, 204, 113, 0.2)" : "rgba(255, 255, 255, 0.08)",
                color: copied ? "#2ecc71" : "inherit",
                transition: "all 0.15s ease",
              }}
              onClick={handleCopy}
              title="Copy wallet address to clipboard"
            >
              {copied ? "✓ Copied" : "Copy"}
            </button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              type="button"
              className="badge"
              style={{
                cursor: "pointer",
                fontSize: "11px",
                padding: "3px 8px",
                background: isCurrentPinned
                  ? "rgba(255, 215, 0, 0.15)"
                  : "rgba(255, 255, 255, 0.08)",
                color: isCurrentPinned ? "#ffd700" : "inherit",
              }}
              onClick={() => handleTogglePin(inspectedAddress)}
            >
              {isCurrentPinned ? "★ Pinned" : "☆ Pin"}
            </button>
            <button
              type="button"
              className="badge"
              style={{
                cursor: "pointer",
                fontSize: "11px",
                padding: "3px 8px",
                background: "rgba(255, 255, 255, 0.08)",
              }}
              disabled={busy}
              onClick={() => void inspect(inspectedAddress, true)}
              title="Poll wallet on-chain if history provider configured"
            >
              Poll on-chain
            </button>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      {result && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "12px",
              marginTop: "16px",
            }}
          >
            {/* History Provenance */}
            <article className="stat" style={{ margin: 0, padding: "12px" }}>
              <span className="stat-label">HISTORY PROVENANCE</span>
              <span className="stat-value" style={{ fontSize: "1.4rem" }}>
                {result.batches_count} Batches
              </span>
              <span className="stat-delta">
                Completeness: {result.completeness} · Point-in-time safe
              </span>
            </article>

            {/* Funding Clusters */}
            <article className="stat" style={{ margin: 0, padding: "12px" }}>
              <span className="stat-label">FUNDING CLUSTERS</span>
              <span className="stat-value" style={{ fontSize: "1.4rem" }}>
                {result.funding_groups.groups.length} Groups
              </span>
              <span className="stat-delta">
                {result.funding_count} Evidence · {result.funding_groups.conflicting_wallets.length} conflicting sources
              </span>
            </article>

            {/* Signals Gate */}
            <article className="stat" style={{ margin: 0, padding: "12px" }}>
              <span className="stat-label">SIGNALS GATE</span>
              <span className="stat-value" style={{ fontSize: "1.4rem", color: "var(--color-caution)" }}>
                DISABLED
              </span>
              <span className="stat-delta">
                Provisional research weights · No live signals
              </span>
            </article>
          </div>

          {/* Funding Clusters Table */}
          <div style={{ marginTop: "20px" }}>
            <h3 style={{ fontSize: "14px", fontWeight: 700, marginBottom: "8px" }}>
              Connected Funding Clusters ({result.funding_groups.groups.length})
            </h3>
            {result.funding_groups.groups.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Funder Address</th>
                      <th>Connected Wallets</th>
                      <th>Evidence Signatures</th>
                      <th>Sources</th>
                      <th>Conclusion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.funding_groups.groups.map((group, idx) => (
                      <tr key={idx}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <span className="mint" title={group.funder}>
                              {group.funder}
                            </span>
                            <button
                              type="button"
                              className="badge"
                              style={{ cursor: "pointer", fontSize: "10px", padding: "2px 6px" }}
                              onClick={() => {
                                setAddressInput(group.funder);
                                void inspect(group.funder);
                              }}
                              title={`Inspect funder ${group.funder}`}
                            >
                              Inspect
                            </button>
                          </div>
                        </td>
                        <td>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                            {group.wallets.map((w) => (
                              <button
                                key={w}
                                type="button"
                                className="badge"
                                style={{
                                  cursor: "pointer",
                                  fontSize: "10px",
                                  padding: "2px 5px",
                                  background: w === inspectedAddress ? "rgba(46, 204, 113, 0.2)" : "rgba(255, 255, 255, 0.05)",
                                }}
                                onClick={() => {
                                  setAddressInput(w);
                                  void inspect(w);
                                }}
                                title={`Inspect wallet ${w}`}
                              >
                                {w.slice(0, 4)}…{w.slice(-4)}
                              </button>
                            ))}
                          </div>
                        </td>
                        <td className="numeric">{group.signatures.length}</td>
                        <td className="muted">{group.sources.join(", ")}</td>
                        <td>
                          <span className="badge caution">
                            {group.conclusion.replaceAll("_", " ")}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty" style={{ padding: "16px" }}>
                <p style={{ margin: 0 }}>
                  {result.funding_count > 0
                    ? `${result.funding_count} funding transaction(s) recorded, but no multi-wallet non-CEX clusters formed under current point-in-time constraints.`
                    : "No recorded funding transactions for this wallet in PostgreSQL."}
                </p>
              </div>
            )}
          </div>

          {/* Provenance Batches Table */}
          <div style={{ marginTop: "20px" }}>
            <h3 style={{ fontSize: "14px", fontWeight: 700, marginBottom: "8px" }}>
              Stored History Provenance Batches ({result.batches.length})
            </h3>
            {result.batches.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Batch ID</th>
                      <th>Coverage Window</th>
                      <th>Retrieved At</th>
                      <th>Source &amp; Parser</th>
                      <th>Exhausted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.batches.map((batch) => (
                      <tr key={batch.batch_id}>
                        <td>
                          <span className="mint" title={batch.batch_id}>
                            {batch.batch_id.slice(0, 16)}…
                          </span>
                        </td>
                        <td className="time">
                          {new Date(batch.provenance.window_start).toLocaleString()} →{" "}
                          {new Date(batch.provenance.window_end).toLocaleString()}
                        </td>
                        <td className="muted time">
                          {new Date(batch.provenance.retrieved_at).toLocaleString()}
                        </td>
                        <td>
                          <span className="badge">
                            {batch.provenance.source} ({batch.provenance.parser_version})
                          </span>
                        </td>
                        <td>
                          <span className={`badge ${batch.provenance.pagination_exhausted ? "current" : "caution"}`}>
                            {batch.provenance.pagination_exhausted ? "complete" : "partial"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty" style={{ padding: "16px" }}>
                <p style={{ margin: 0 }}>
                  No historical transaction batches stored for this wallet yet. Live polling requires credentialed provider configuration in runtime environment.
                </p>
              </div>
            )}
          </div>
        </>
      )}

      {/* Initial empty state */}
      {!result && !busy && !error && (
        <div className="empty" style={{ marginTop: "16px" }}>
          <span className="empty-icon">⎌</span>
          <h3>No wallet evaluated</h3>
          <p>
            Enter a Solana base58 wallet address above or click a quick-select chip to inspect stored transaction provenance, swap batches, and connected funding clusters.
          </p>
        </div>
      )}

      <div className="panel-foot">
        Point-in-time boundaries strictly enforced. Shared funding evidence does not prove common ownership. No signals are enabled.
      </div>
    </section>
  );
}
