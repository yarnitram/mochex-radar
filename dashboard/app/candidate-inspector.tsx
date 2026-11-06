"use client";

import { useState } from "react";
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
        flags: string[];
      };
      stage_liquidity: {
        status: string;
        reason: string;
        dex_liquidity_usd?: string | null;
        sell_depth_2pct_usd?: string | null;
        flags: string[];
      };
      holder_concentration: {
        status: string;
        reason: string;
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
    blocking_gates: string[];
    provisional: boolean;
    approved_live_signal: boolean;
    alerts_enabled: boolean;
  };
};

const date = (value: string) =>
  new Date(value).toLocaleString(undefined, { hour12: false });

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

  // Extract up to 3 suggested mints from loaded catalog / authorities
  const suggestedMints: string[] = [];
  const catalog = snapshot?.catalog?.data;
  if (catalog?.status === "current_catalog") {
    for (const item of catalog.mints) {
      if (!suggestedMints.includes(item.mint)) suggestedMints.push(item.mint);
      if (suggestedMints.length >= 3) break;
    }
  }

  async function handleInspect(targetMint?: string) {
    const mintToInspect = (targetMint || mintInput).trim();
    if (!mintToInspect) return;
    setMintInput(mintToInspect);
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/candidate?mint=${encodeURIComponent(mintToInspect)}`,
        { cache: "no-store" },
      );
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
        <button
          onClick={() => void handleInspect()}
          disabled={busy || !mintInput.trim()}
        >
          {busy ? "Evaluating…" : "Inspect candidate"}
        </button>
      </div>

      {suggestedMints.length > 0 && !result && (
        <div className="discovery-note">
          <span>Observed catalog suggestions: </span>
          {suggestedMints.map((m) => (
            <button
              key={m}
              className="badge"
              style={{ cursor: "pointer", marginRight: "6px", border: "none" }}
              onClick={() => void handleInspect(m)}
            >
              {m.slice(0, 8)}…{m.slice(-4)}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="notice" role="alert">
          {error}
        </div>
      )}

      {result && (
        <>
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
                        .mint_authority_status || "UNKNOWN"}{" "}
                      · Freeze auth:{" "}
                      {result.token_risk.checks.mint_and_extensions
                        .freeze_authority_status || "UNKNOWN"}
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
                      Top 1 &amp; Top 10 unlocked
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
                      {result.token_risk.checks.holder_concentration
                        .top_1_unlocked_pct
                        ? `${Number(result.token_risk.checks.holder_concentration.top_1_unlocked_pct).toFixed(2)}%`
                        : "missing"}{" "}
                      · Top 10:{" "}
                      {result.token_risk.checks.holder_concentration
                        .top_10_unlocked_pct
                        ? `${Number(result.token_risk.checks.holder_concentration.top_10_unlocked_pct).toFixed(2)}%`
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
