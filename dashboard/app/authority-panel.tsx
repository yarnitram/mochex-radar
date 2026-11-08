"use client";

import { useState } from "react";
import type { Snapshot } from "@/lib/contracts";
const date = (value: string) =>
  new Date(value).toLocaleString(undefined, { hour12: false });
const reasons: Record<string, string> = {
  partial_authority_evidence: "Original SPL permissions observed",
  account_missing: "Account not found",
  token_2022_extensions_not_evaluated: "Token-2022 extensions not evaluated",
  unsupported_owner: "Unsupported account owner",
  executable_account: "Executable account",
  unsupported_mint_layout: "Unsupported account layout",
  uninitialized_or_invalid_mint: "Uninitialized or invalid mint",
  invalid_authority_layout: "Invalid authority layout",
};
function Permission({
  state,
  address,
}: {
  state: string;
  address: string | null;
}) {
  return (
    <>
      <span
        className={`badge ${state === "PRESENT" ? "permission-present" : ""}`}
      >
        {state === "DISABLED" ? "absent" : state.toLowerCase()}
      </span>
      {address && (
        <div style={{ display: "flex", alignItems: "center", gap: "4px", marginTop: "2px" }}>
          <small className="provenance" title={address}>
            {address}
          </small>
          <button
            type="button"
            className="badge"
            style={{ cursor: "pointer", fontSize: "9px", padding: "1px 5px" }}
            onClick={() => window.dispatchEvent(new CustomEvent("select-wallet-address", { detail: address }))}
            title={`Inspect wallet history for ${address}`}
          >
            Inspect
          </button>
        </div>
      )}
    </>
  );
}
export default function AuthorityPanel({
  snapshot,
  outdated,
}: {
  snapshot: Snapshot | null;
  outdated: boolean;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const data = snapshot?.authorities?.data;
  const loaded =
    data?.status === "stored_partial_evidence" ? data.observations : [];
  const rows = loaded.filter(
    (row) =>
      row.evidence.mint.includes(query.trim()) &&
      (filter === "all" || row.freshness === filter),
  );
  return (
    <section
      className="panel"
      id="authorities"
      aria-labelledby="authorities-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="authorities-title">Mint authority evidence</h2>
          <p>Up to 100 newest stored readings · Multiple readings per mint</p>
        </div>
        <span className={`badge ${outdated ? "outdated" : ""}`}>
          {outdated
            ? "outdated"
            : data?.status === "stored_partial_evidence"
              ? `${loaded.length} readings`
              : data?.status === "storage_disabled"
                ? "storage disabled"
                : snapshot
                  ? "unavailable"
                  : "loading"}
        </span>
      </div>
      <p className="discovery-note">
        Overall security: UNKNOWN. Absent mint and freeze permissions do not
        establish safety. Liquidity, transfer restrictions, controller risk and
        Token-2022 extensions remain unevaluated.
      </p>
      <div className="discovery-controls">
        <label>
          Search loaded readings
          <input
            type="search"
            aria-label="Search authority mint"
            placeholder="Case-sensitive mint address"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div
          className="filters"
          role="group"
          aria-label="Authority freshness filter"
        >
          {[
            ["all", "All readings"],
            ["current", "Under 15m"],
            ["stale", "Stale"],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {data?.status === "stored_partial_evidence" && rows.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Mint / source</th>
                <th>Mint permission</th>
                <th>Freeze permission</th>
                <th>RPC slot / age</th>
                <th>Observed at / scope</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={`${row.evidence.mint}:${row.evidence.source}:${row.evidence.known_at}`}
                >
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span className="mint" title={row.evidence.mint}>
                        {row.evidence.mint}
                      </span>
                      <button
                        type="button"
                        className="badge"
                        style={{ cursor: "pointer", fontSize: "10px", padding: "2px 6px" }}
                        onClick={() => window.dispatchEvent(new CustomEvent("select-candidate-mint", { detail: row.evidence.mint }))}
                        title={`Inspect candidate ${row.evidence.mint}`}
                      >
                        Inspect
                      </button>
                    </div>
                    <small className="provenance" title={row.evidence.source}>
                      {row.evidence.source}
                    </small>
                    <small className="provenance">
                      {row.evidence.parser_version}
                    </small>
                  </td>
                  <td>
                    <Permission
                      state={row.evidence.mint_authority_status}
                      address={row.evidence.mint_authority}
                    />
                  </td>
                  <td>
                    <Permission
                      state={row.evidence.freeze_authority_status}
                      address={row.evidence.freeze_authority}
                    />
                  </td>
                  <td>
                    <div className="numeric">
                      {row.evidence.slot.toLocaleString()}
                    </div>
                    <span
                      className={`badge ${outdated ? "outdated" : row.freshness === "stale" ? "stale" : ""}`}
                    >
                      {outdated
                        ? "outdated"
                        : row.freshness === "stale"
                          ? "stale"
                          : "under 15m"}
                    </span>
                  </td>
                  <td>
                    <span className="time">{date(row.evidence.known_at)}</span>
                    <small
                      className="provenance"
                      title={`Ingested ${date(row.ingested_at)}; expires ${date(row.expires_at)}`}
                    >
                      {reasons[row.evidence.reason]}
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">
          <h3>
            {data?.status === "storage_disabled"
              ? "Authority storage is not configured"
              : data?.status !== "stored_partial_evidence"
                ? snapshot
                  ? "Authority evidence unavailable"
                  : "Waiting for authority evidence"
                : loaded.length
                  ? "No matching loaded readings"
                  : "No stored authority evidence"}
          </h3>
          <p>
            Only stored observations appear here. Dashboard refresh does not
            request new on-chain checks.
          </p>
        </div>
      )}
      <div className="panel-foot">
        {data?.status === "stored_partial_evidence"
          ? `Snapshot checked ${date(data.as_of)}. `
          : ""}
        Freshness describes observation age, not independent chain-head
        confirmation. Search/filter applies to this loaded subset. RPC slot is
        not token age. This view cannot approve Pump Watch or send alerts.
      </div>
    </section>
  );
}
