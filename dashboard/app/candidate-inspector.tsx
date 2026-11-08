"use client";

import { useEffect, useState } from "react";
import type { Snapshot } from "@/lib/contracts";

type EvaluationResult = {
  data_status: string;
  mint: string;
  as_of: string;
  token_risk: {
    rule_version: string;
    as_of: string;
    security_status: string;
    checks: {
      mint_and_extensions: {
        status: string;
        reason: string;
        mint_authority_status?: string;
        freeze_authority_status?: string;
        mint_authority?: string | null;
        freeze_authority?: string | null;
        flags: string[];
      };
      stage_liquidity: {
        status: string;
        stage?: string;
        reason: string;
        dex_liquidity_usd?: string | null;
        sell_depth_2pct_usd?: string | null;
        pool_id?: string | null;
        dex_id?: string | null;
        pool_created_at?: string | null;
        flags: string[];
      };
      holder_concentration: {
        status: string;
        reason: string;
        top_1_account_pct?: string | null;
        top_10_account_pct?: string | null;
        top_1_unlocked_pct?: string | null;
        top_10_unlocked_pct?: string | null;
        flags: string[];
      };
    };
    flags: string[];
  };
  candidate_state: {
    rule_version: string;
    mint: string;
    as_of: string;
    state: string;
    security_status: string;
    pump_score?: string | null;
    dump_score?: string | null;
    dump_warning_groups?: number | unknown[] | null;
    blocking_gates: string[];
    provisional: boolean;
    approved_live_signal: boolean;
    alerts_enabled: boolean;
  };
};

const date = (value: string) =>
  new Date(value).toLocaleString(undefined, { hour12: false });

const PINNED_STORAGE_KEY = "mochex_radar_pinned_mints";

interface PinnedToken {
  mint: string;
  symbol: string;
  label?: string;
}

const KNOWN_SYMBOLS: Record<string, { symbol: string; label?: string }> = {
  So11111111111111111111111111111111111111112: { symbol: "WSOL", label: "Wrapped SOL" },
  DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263: { symbol: "BONK", label: "Bonk" },
  EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm: { symbol: "WIF", label: "dogwifhat" },
  "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": { symbol: "POPCAT", label: "Popcat" },
  MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5: { symbol: "MEW", label: "cat in a dogs world" },
  CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump: { symbol: "GOAT", label: "Goatseus Maximus" },
  GJAFwWjJ3vnTsrQVabjBVK2TYB1YtRCQXRDfDgUnpump: { symbol: "ACT", label: "Act I: The AI Prophecy" },
  "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump": { symbol: "FARTCOIN", label: "Fartcoin" },
  ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY: { symbol: "MOODENG", label: "Moo Deng" },
  "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump": { symbol: "PNUT", label: "Peanut the Squirrel" },
};

const DEFAULT_WATCHLIST: Array<{ mint: string; symbol: string; label?: string }> = [
  { mint: "So11111111111111111111111111111111111111112", symbol: "WSOL", label: "Wrapped SOL" },
  { mint: "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", symbol: "BONK", label: "Bonk" },
  { mint: "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", symbol: "WIF", label: "dogwifhat" },
  { mint: "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", symbol: "POPCAT", label: "Popcat" },
  { mint: "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5", symbol: "MEW", label: "cat in a dogs world" },
  { mint: "CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump", symbol: "GOAT", label: "Goatseus Maximus" },
  { mint: "GJAFwWjJ3vnTsrQVabjBVK2TYB1YtRCQXRDfDgUnpump", symbol: "ACT", label: "Act I: The AI Prophecy" },
  { mint: "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump", symbol: "FARTCOIN", label: "Fartcoin" },
  { mint: "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY", symbol: "MOODENG", label: "Moo Deng" },
  { mint: "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump", symbol: "PNUT", label: "Peanut the Squirrel" },
];

export default function CandidateInspector({
  snapshot,
  outdated,
}: {
  snapshot: Snapshot | null;
  outdated: boolean;
}) {
  const [mintInput, setMintInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [pinnedTokens, setPinnedTokens] = useState<PinnedToken[]>([]);
  const [copied, setCopied] = useState(false);

  // Build watchlist tokens list from scans or fallback to default
  const watchlistTokens: Array<{ mint: string; symbol: string; label?: string }> = [];
  const seenMints = new Set<string>();
  const scans = snapshot?.scans?.data?.scans || [];
  for (const scan of scans) {
    if (seenMints.has(scan.mint)) continue;
    seenMints.add(scan.mint);
    const known = KNOWN_SYMBOLS[scan.mint];
    if (known) {
      watchlistTokens.push({ mint: scan.mint, ...known });
    } else {
      const derived =
        scan.category_source?.replace(/^operator:/, "").toUpperCase() ||
        `${scan.mint.slice(0, 4)}…`;
      watchlistTokens.push({ mint: scan.mint, symbol: derived });
    }
  }
  if (watchlistTokens.length === 0) {
    for (const item of DEFAULT_WATCHLIST) {
      watchlistTokens.push(item);
      seenMints.add(item.mint);
    }
  }

  // Extract up to 6 suggested discovered mints from loaded catalog
  const suggestedMints: string[] = [];
  const catalog = snapshot?.catalog?.data;
  if (catalog?.status === "current_catalog") {
    for (const item of catalog.mints) {
      if (!seenMints.has(item.mint) && !suggestedMints.includes(item.mint)) {
        suggestedMints.push(item.mint);
      }
      if (suggestedMints.length >= 6) break;
    }
  }

  useEffect(() => {
    try {
      const raw = localStorage.getItem(PINNED_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setPinnedTokens(parsed);
        }
      }
    } catch {
      // Ignore localStorage availability issues
    }
  }, []);

  function handleTogglePin(mint: string, symbolHint?: string) {
    const isPinned = pinnedTokens.some((p) => p.mint === mint);
    let updated: PinnedToken[];
    if (isPinned) {
      updated = pinnedTokens.filter((p) => p.mint !== mint);
    } else {
      const known = KNOWN_SYMBOLS[mint];
      const symbol = symbolHint || known?.symbol || `${mint.slice(0, 4)}…`;
      const label = known?.label;
      updated = [...pinnedTokens, { mint, symbol, label }];
    }
    setPinnedTokens(updated);
    try {
      localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(updated));
    } catch {
      // Ignore
    }
  }

  useEffect(() => {
    const handler = (e: Event) => {
      const custom = e as CustomEvent<string>;
      if (custom.detail) {
        const target = custom.detail.trim();
        setMintInput(target);
        void handleInspect(target, false);
        const el = document.getElementById("candidate");
        if (el) el.scrollIntoView({ behavior: "smooth" });
      }
    };
    window.addEventListener("select-candidate-mint", handler);
    return () => window.removeEventListener("select-candidate-mint", handler);
  }, []);

  async function handleInspect(targetMint?: string, refresh: boolean = false) {
    const mintToInspect = (targetMint || mintInput).trim();
    if (!mintToInspect) return;
    setMintInput(mintToInspect);
    setBusy(true);
    setError(null);
    try {
      const url = `/api/candidate?mint=${encodeURIComponent(mintToInspect)}${refresh ? "&refresh=true" : ""}`;
      let response = await fetch(url, { cache: "no-store" });
      if (!response.ok && !refresh && response.status === 503) {
        // Fall back to on-demand observation if stored evaluation not yet available
        response = await fetch(
          `/api/candidate?mint=${encodeURIComponent(mintToInspect)}&refresh=true`,
          { cache: "no-store" },
        );
      }
      if (!response.ok) {
        throw new Error(
          response.status === 400
            ? "Invalid Solana mint address"
            : "Candidate evaluation service unavailable",
        );
      }
      const json = await response.json();
      if (json.status !== "available") {
        throw new Error("Stored evaluation unavailable");
      }
      setResult(json.data);
    } catch (err: unknown) {
      setResult(null);
      setError(
        err instanceof Error ? err.message : "Failed to inspect candidate",
      );
    } finally {
      setBusy(false);
    }
  }

  function handleClear() {
    setMintInput("");
    setResult(null);
    setError(null);
  }

  return (
    <section
      className="panel"
      id="candidate"
      aria-labelledby="candidate-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="candidate-title">Solana candidate risk &amp; state inspector</h2>
          <p>
            Point-in-time state machine · Token-2022, liquidity &amp; holder risk
            checks · Fail-closed gating
          </p>
        </div>
        <span className={`badge ${outdated ? "outdated" : ""}`}>
          {outdated ? "outdated" : "provisional research"}
        </span>
      </div>

      <div
        className="discovery-note"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          padding: "12px 22px",
          borderBottom: "1px solid var(--line, #1f2d38)",
        }}
      >
        {pinnedTokens.length > 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontSize: "10px",
                color: "#f0c674",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.5px",
              }}
            >
              ★ Pinned ({pinnedTokens.length}):
            </span>
            {pinnedTokens.map((t) => {
              const isSelected =
                result?.mint === t.mint || mintInput.trim() === t.mint;
              return (
                <span
                  key={t.mint}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    borderRadius: "4px",
                    background: isSelected ? "#2a3d24" : "#1b252f",
                    border: isSelected ? "1px solid #4ade80" : "1px solid #2d3e4f",
                    padding: "2px 6px",
                    gap: "4px",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => void handleInspect(t.mint)}
                    style={{
                      background: "none",
                      border: "none",
                      color: isSelected ? "#a1e4b4" : "var(--foreground, #e2e8f0)",
                      cursor: "pointer",
                      fontSize: "10px",
                      fontWeight: 500,
                      padding: 0,
                    }}
                    title={`${t.label || t.symbol}: ${t.mint}`}
                  >
                    {t.symbol}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleTogglePin(t.mint);
                    }}
                    style={{
                      background: "none",
                      border: "none",
                      color: "var(--muted, #64748b)",
                      cursor: "pointer",
                      fontSize: "12px",
                      lineHeight: 1,
                      padding: "0 2px",
                    }}
                    title="Unpin token"
                    aria-label={`Unpin ${t.symbol}`}
                  >
                    ×
                  </button>
                </span>
              );
            })}
          </div>
        )}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontSize: "10px",
              color: "var(--muted)",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
            }}
          >
            Watchlist:
          </span>
          {watchlistTokens.map((t) => {
            const isSelected =
              result?.mint === t.mint || mintInput.trim() === t.mint;
            return (
              <button
                key={t.mint}
                type="button"
                className={`badge ${isSelected ? "current" : ""}`}
                style={{
                  cursor: "pointer",
                  border: isSelected
                    ? "1px solid #3c5145"
                    : "1px solid #23303b",
                  padding: "4px 8px",
                  fontSize: "10px",
                  background: isSelected ? "#1e3829" : undefined,
                  color: isSelected ? "#a1e4b4" : undefined,
                }}
                onClick={() => void handleInspect(t.mint)}
                title={`${t.label || t.symbol}: ${t.mint}`}
                aria-pressed={isSelected}
              >
                {t.symbol}
              </button>
            );
          })}
        </div>

        {suggestedMints.length > 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontSize: "10px",
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: "0.5px",
              }}
            >
              Discovered:
            </span>
            {suggestedMints.map((m) => {
              const isSelected =
                result?.mint === m || mintInput.trim() === m;
              return (
                <button
                  key={m}
                  type="button"
                  className={`badge ${isSelected ? "current" : ""}`}
                  style={{
                    cursor: "pointer",
                    border: isSelected
                      ? "1px solid #3c5145"
                      : "1px solid #23303b",
                    padding: "4px 8px",
                    fontSize: "10px",
                    background: isSelected ? "#1e3829" : undefined,
                    color: isSelected ? "#a1e4b4" : undefined,
                  }}
                  onClick={() => void handleInspect(m)}
                  title={m}
                  aria-pressed={isSelected}
                >
                  {m.slice(0, 6)}…{m.slice(-4)}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="discovery-controls">
        <label>
          Inspect candidate mint
          <input
            type="search"
            aria-label="Solana mint address to inspect"
            placeholder="Base58 Solana mint address"
            value={mintInput}
            onChange={(e) => setMintInput(e.target.value)}
          />
        </label>
        <div
          style={{
            display: "flex",
            gap: "8px",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <button
            onClick={() => void handleInspect()}
            disabled={busy || !mintInput.trim()}
          >
            {busy ? "Evaluating…" : "Inspect candidate"}
          </button>
          <button
            type="button"
            onClick={() => void handleInspect(undefined, true)}
            disabled={busy || !mintInput.trim()}
            title="Perform on-chain authority & pool observation check"
          >
            {busy ? "Querying…" : "Inspect & Refresh"}
          </button>
          {mintInput.trim() && (
            <button
              type="button"
              onClick={() =>
                handleTogglePin(
                  mintInput.trim(),
                  result ? KNOWN_SYMBOLS[mintInput.trim()]?.symbol : undefined,
                )
              }
              style={{
                background: pinnedTokens.some(
                  (p) => p.mint === mintInput.trim(),
                )
                  ? "#2b3a2f"
                  : "transparent",
                border: "1px solid #394b59",
                color: pinnedTokens.some((p) => p.mint === mintInput.trim())
                  ? "#f0c674"
                  : "var(--muted)",
                padding: "8px 12px",
                borderRadius: "4px",
                fontSize: "11px",
                cursor: "pointer",
              }}
              title={
                pinnedTokens.some((p) => p.mint === mintInput.trim())
                  ? "Remove from pinned watchlist"
                  : "Pin to my personal browser watchlist"
              }
            >
              {pinnedTokens.some((p) => p.mint === mintInput.trim())
                ? "★ Pinned"
                : "☆ Pin token"}
            </button>
          )}
          {(result || mintInput) && (
            <button
              type="button"
              onClick={handleClear}
              style={{
                background: "transparent",
                border: "1px solid #394b59",
                color: "var(--muted)",
                padding: "8px 12px",
                borderRadius: "4px",
                fontSize: "11px",
              }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="notice" role="alert">
          {error}
        </div>
      )}

      {result && (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginTop: "0.75rem",
              padding: "6px 12px",
              background: "rgba(255,255,255,0.03)",
              border: "1px solid var(--line, #1f2d38)",
              borderRadius: "4px",
              flexWrap: "wrap",
            }}
          >
            <span style={{ fontSize: "11px", color: "var(--muted)" }}>
              Inspecting:
            </span>
            <code style={{ fontSize: "12px", color: "var(--foreground)" }}>
              {result.mint}
            </code>
            {KNOWN_SYMBOLS[result.mint] && (
              <span className="badge">
                {KNOWN_SYMBOLS[result.mint].symbol}
              </span>
            )}
            <button
              type="button"
              onClick={() => {
                void navigator.clipboard.writeText(result.mint);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              style={{
                background: "transparent",
                border: "1px solid #394b59",
                color: copied ? "#4ade80" : "var(--muted)",
                padding: "2px 8px",
                borderRadius: "4px",
                fontSize: "10px",
                cursor: "pointer",
              }}
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <div className="summary-grid" style={{ marginTop: "1rem" }}>
            <article className="summary">
              <span className="label">CANDIDATE STATE</span>
              <div className="summary-value" style={{ marginTop: "0.5rem" }}>
                <span
                  className={`badge ${
                    result.candidate_state.state === "BLOCKED_SECURITY"
                      ? "blocked"
                      : result.candidate_state.state === "DUMP_WARNING"
                        ? "negative"
                        : result.candidate_state.state ===
                            "PUMP_WATCH_PROVISIONAL"
                          ? "current"
                          : ""
                  }`}
                >
                  {result.candidate_state.state.replaceAll("_", " ")}
                </span>
              </div>
              <p>
                Rule version: {result.candidate_state.rule_version}
                <br />
                As of {date(result.as_of)}
              </p>
            </article>

            <article className="summary">
              <span className="label">OVERALL SECURITY RISK</span>
              <div className="summary-value" style={{ marginTop: "0.5rem" }}>
                <span
                  className={`badge ${
                    result.token_risk.security_status === "BLOCK"
                      ? "blocked"
                      : result.token_risk.security_status === "CAUTION"
                        ? "caution"
                        : result.token_risk.security_status === "PASS"
                          ? "current"
                          : ""
                  }`}
                >
                  {result.token_risk.security_status}
                </span>
              </div>
              <p>
                {result.token_risk.rule_version}
                <br />
                Vendor score never sufficient for PASS
              </p>
            </article>

            <article className="summary">
              <span className="label">SIGNAL &amp; ALERT GUARDS</span>
              <div className="summary-value" style={{ marginTop: "0.5rem" }}>
                <span className="badge">LIVE SIGNALS OFF</span>
              </div>
              <p>
                Provisional research only. Alerts disabled. No trade execution.
              </p>
            </article>

            <article className="summary">
              <span className="label">RESEARCH SCORES</span>
              <div
                style={{
                  marginTop: "0.5rem",
                  display: "flex",
                  gap: "6px",
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <span
                  className={`badge ${
                    result.candidate_state.pump_score &&
                    Number(result.candidate_state.pump_score) >= 75
                      ? "current"
                      : ""
                  }`}
                  title="Pump research score (0-100)"
                >
                  Pump:{" "}
                  {result.candidate_state.pump_score
                    ? `${Number(result.candidate_state.pump_score).toFixed(0)}/100`
                    : "None"}
                </span>
                <span
                  className={`badge ${
                    result.candidate_state.dump_score &&
                    Number(result.candidate_state.dump_score) >= 75
                      ? "negative"
                      : ""
                  }`}
                  title="Dump warning score (0-100)"
                >
                  Dump:{" "}
                  {result.candidate_state.dump_score
                    ? `${Number(result.candidate_state.dump_score).toFixed(0)}/100`
                    : "None"}
                </span>
              </div>
              <p>
                Warnings:{" "}
                {Array.isArray(result.candidate_state.dump_warning_groups)
                  ? result.candidate_state.dump_warning_groups.length
                  : (result.candidate_state.dump_warning_groups ?? 0)}{" "}
                groups
                <br />
                Provisional research weights · No live signals
              </p>
            </article>
          </div>

          {result.candidate_state.blocking_gates.length > 0 && (
            <div className="panel-body" style={{ marginTop: "1rem" }}>
              <strong>Active Gating Conditions:</strong>
              <div
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  flexWrap: "wrap",
                  marginTop: "0.4rem",
                }}
              >
                {result.candidate_state.blocking_gates.map((gate) => (
                  <span key={gate} className="badge caution">
                    {gate.replaceAll("_", " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="table-wrap" style={{ marginTop: "1rem" }}>
            <table>
              <thead>
                <tr>
                  <th>Risk dimension</th>
                  <th>Verdict</th>
                  <th>Details &amp; flags</th>
                  <th>Reason / layout</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <strong>Mint &amp; Token-2022</strong>
                    <small className="provenance">Authorities &amp; TLV</small>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        result.token_risk.checks.mint_and_extensions.status ===
                        "BLOCK"
                          ? "blocked"
                          : result.token_risk.checks.mint_and_extensions
                                .status === "CAUTION"
                            ? "caution"
                            : result.token_risk.checks.mint_and_extensions
                                  .status === "PASS"
                              ? "current"
                              : ""
                      }`}
                    >
                      {result.token_risk.checks.mint_and_extensions.status}
                    </span>
                  </td>
                  <td>
                    <span>
                      Mint auth:{" "}
                      {result.token_risk.checks.mint_and_extensions
                        .mint_authority_status || "UNKNOWN"}
                      {result.token_risk.checks.mint_and_extensions.mint_authority && (
                        <button
                          type="button"
                          className="badge"
                          style={{ cursor: "pointer", fontSize: "9px", padding: "1px 5px", marginLeft: "4px" }}
                          onClick={() => window.dispatchEvent(new CustomEvent("select-wallet-address", { detail: result.token_risk.checks.mint_and_extensions.mint_authority }))}
                          title={`Inspect mint authority wallet ${result.token_risk.checks.mint_and_extensions.mint_authority}`}
                        >
                          Inspect {result.token_risk.checks.mint_and_extensions.mint_authority.slice(0, 4)}…
                        </button>
                      )}{" "}
                      · Freeze auth:{" "}
                      {result.token_risk.checks.mint_and_extensions
                        .freeze_authority_status || "UNKNOWN"}
                      {result.token_risk.checks.mint_and_extensions.freeze_authority && (
                        <button
                          type="button"
                          className="badge"
                          style={{ cursor: "pointer", fontSize: "9px", padding: "1px 5px", marginLeft: "4px" }}
                          onClick={() => window.dispatchEvent(new CustomEvent("select-wallet-address", { detail: result.token_risk.checks.mint_and_extensions.freeze_authority }))}
                          title={`Inspect freeze authority wallet ${result.token_risk.checks.mint_and_extensions.freeze_authority}`}
                        >
                          Inspect {result.token_risk.checks.mint_and_extensions.freeze_authority.slice(0, 4)}…
                        </button>
                      )}
                    </span>
                    {result.token_risk.checks.mint_and_extensions.flags
                      .length > 0 && (
                      <small className="provenance">
                        Flags:{" "}
                        {result.token_risk.checks.mint_and_extensions.flags.join(
                          ", ",
                        )}
                      </small>
                    )}
                  </td>
                  <td className="muted">
                    {result.token_risk.checks.mint_and_extensions.reason.replaceAll(
                      "_",
                      " ",
                    )}
                  </td>
                </tr>

                <tr>
                  <td>
                    <strong>Stage liquidity</strong>
                    <small className="provenance">
                      DEX pool vs 2% sell-depth
                    </small>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        result.token_risk.checks.stage_liquidity.status ===
                        "BLOCK"
                          ? "blocked"
                          : result.token_risk.checks.stage_liquidity.status ===
                              "CAUTION"
                            ? "caution"
                            : result.token_risk.checks.stage_liquidity
                                  .status === "PASS"
                              ? "current"
                              : ""
                      }`}
                    >
                      {result.token_risk.checks.stage_liquidity.status}
                    </span>
                  </td>
                  <td>
                    <span>
                      DEX liq:{" "}
                      {result.token_risk.checks.stage_liquidity
                        .dex_liquidity_usd
                        ? `$${Number(result.token_risk.checks.stage_liquidity.dex_liquidity_usd).toLocaleString()}`
                        : "missing"}{" "}
                      · Sell depth 2%:{" "}
                      {result.token_risk.checks.stage_liquidity
                        .sell_depth_2pct_usd
                        ? `$${Number(result.token_risk.checks.stage_liquidity.sell_depth_2pct_usd).toLocaleString()}`
                        : "missing"}
                    </span>
                    {result.token_risk.checks.stage_liquidity.pool_id && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          marginTop: "4px",
                          flexWrap: "wrap",
                        }}
                      >
                        <span
                          className="badge"
                          style={{
                            fontSize: "9px",
                            padding: "1px 6px",
                            textTransform: "uppercase",
                            background: "#1c2b36",
                            color: "#83a598",
                            border: "1px solid #283e4e",
                          }}
                        >
                          {result.token_risk.checks.stage_liquidity.dex_id
                            ? result.token_risk.checks.stage_liquidity.dex_id.toUpperCase()
                            : "DEX POOL"}
                        </span>
                        <code style={{ fontSize: "11px", color: "var(--foreground, #ebdbb2)" }}>
                          {result.token_risk.checks.stage_liquidity.pool_id.slice(0, 4)}…{result.token_risk.checks.stage_liquidity.pool_id.slice(-4)}
                        </code>
                        <button
                          type="button"
                          className="badge"
                          style={{ cursor: "pointer", fontSize: "9px", padding: "1px 5px" }}
                          onClick={() => {
                            if (result.token_risk.checks.stage_liquidity.pool_id) {
                              void navigator.clipboard.writeText(result.token_risk.checks.stage_liquidity.pool_id);
                            }
                          }}
                          title={`Copy pool address ${result.token_risk.checks.stage_liquidity.pool_id}`}
                        >
                          Copy
                        </button>
                        <a
                          href={`https://dexscreener.com/solana/${result.token_risk.checks.stage_liquidity.pool_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="badge"
                          style={{
                            fontSize: "9px",
                            padding: "1px 6px",
                            textDecoration: "none",
                            color: "#8ec07c",
                            border: "1px solid #3c5145",
                          }}
                          title="View pool on DexScreener"
                        >
                          DexScreener ↗
                        </a>
                      </div>
                    )}
                    {result.token_risk.checks.stage_liquidity.flags.length >
                      0 && (
                      <small className="provenance">
                        Flags:{" "}
                        {result.token_risk.checks.stage_liquidity.flags.join(
                          ", ",
                        )}
                      </small>
                    )}
                  </td>
                  <td className="muted">
                    {result.token_risk.checks.stage_liquidity.reason.replaceAll(
                      "_",
                      " ",
                    )}
                  </td>
                </tr>

                <tr>
                  <td>
                    <strong>Holder concentration</strong>
                    <small className="provenance">
                      Top token accounts (ownership and locks unverified)
                    </small>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        result.token_risk.checks.holder_concentration.status ===
                        "BLOCK"
                          ? "blocked"
                          : result.token_risk.checks.holder_concentration
                                .status === "CAUTION"
                            ? "caution"
                            : result.token_risk.checks.holder_concentration
                                  .status === "PASS"
                              ? "current"
                              : ""
                      }`}
                    >
                      {result.token_risk.checks.holder_concentration.status}
                    </span>
                  </td>
                  <td>
                    <span>
                      Top 1:{" "}
                      {(result.token_risk.checks.holder_concentration.top_1_account_pct ??
                        result.token_risk.checks.holder_concentration.top_1_unlocked_pct)
                        ? `${Number(result.token_risk.checks.holder_concentration.top_1_account_pct ?? result.token_risk.checks.holder_concentration.top_1_unlocked_pct).toFixed(2)}%`
                        : "missing"}{" "}
                      · Top 10:{" "}
                      {(result.token_risk.checks.holder_concentration.top_10_account_pct ??
                        result.token_risk.checks.holder_concentration.top_10_unlocked_pct)
                        ? `${Number(result.token_risk.checks.holder_concentration.top_10_account_pct ?? result.token_risk.checks.holder_concentration.top_10_unlocked_pct).toFixed(2)}%`
                        : "missing"}
                    </span>
                    {result.token_risk.checks.holder_concentration.flags
                      .length > 0 && (
                      <small className="provenance">
                        Flags:{" "}
                        {result.token_risk.checks.holder_concentration.flags.join(
                          ", ",
                        )}
                      </small>
                    )}
                  </td>
                  <td className="muted">
                    {result.token_risk.checks.holder_concentration.reason.replaceAll(
                      "_",
                      " ",
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="panel-foot">
        Point-in-time candidate state evaluation synthesizes stored SPL/Token-2022
        permissions, DEX depth, and holder concentration without executing
        live RPC calls. Vendor safety verdicts alone can never produce a PASS.
      </div>
    </section>
  );
}
