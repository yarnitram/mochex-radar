"use client";

import { useState } from "react";
import type { Snapshot } from "@/lib/contracts";

const formatTime = (value: string) =>
  new Date(value).toLocaleString(undefined, { hour12: false });

export default function DiscoveryPanel({
  snapshot,
  outdated,
}: {
  snapshot: Snapshot | null;
  outdated: boolean;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const catalog = snapshot?.catalog?.data;
  const history = snapshot?.profilePolls?.data;
  const loaded = catalog?.status === "current_catalog" ? catalog.mints : [];
  const matching = loaded.filter(
    (item) =>
      item.mint.includes(query.trim()) &&
      (filter === "all" ||
        (filter === "unscanned" ? !item.last_scan_at : !!item.last_scan_at)),
  );
  const polls = history?.status === "stored_polls" ? history.polls : [];
  const unavailable = catalog?.status !== "current_catalog";
  return (
    <section className="panel" id="discovery" aria-labelledby="discovery-title">
      <div className="panel-heading">
        <div>
          <h2 id="discovery-title">Observed Solana profiles</h2>
          <p>Source observations · Up to 100 newest records</p>
        </div>
        <span className={`badge ${outdated ? "outdated" : ""}`}>
          {outdated
            ? "outdated"
            : catalog?.status === "current_catalog"
              ? `${loaded.length} loaded`
              : catalog?.status === "storage_disabled"
                ? "storage disabled"
                : snapshot
                  ? "unavailable"
                  : "loading"}
        </span>
      </div>
      <p className="discovery-note">
        Profile appearance does not establish token age or safety. Candidates
        are unclassified, security is UNKNOWN, and Pump Watch is not approved.
      </p>
      <div className="discovery-controls">
        <label>
          Search loaded records
          <input
            aria-label="Search observed mint"
            type="search"
            placeholder="Case-sensitive mint address"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="filters" role="group" aria-label="Pool lookup filter">
          {[
            ["all", "All"],
            ["unscanned", "No attempt"],
            ["scanned", "Attempt recorded"],
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
      {!unavailable && matching.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Solana mint / source</th>
                <th>First observed</th>
                <th>Last observed</th>
                <th>Pool lookup</th>
              </tr>
            </thead>
            <tbody>
              {matching.map((item) => (
                <tr key={`${item.source}:${item.mint}`}>
                  <td>
                    <span className="mint" title={item.mint}>
                      {item.mint}
                    </span>
                    <small className="provenance" title={item.source}>
                      {item.source}
                    </small>
                  </td>
                  <td className="time">{formatTime(item.first_known_at)}</td>
                  <td className="time">{formatTime(item.last_known_at)}</td>
                  <td>
                    {item.last_scan_at ? (
                      <>
                        <span className="badge">attempt recorded</span>
                        <small className="provenance">
                          {formatTime(item.last_scan_at)}
                        </small>
                      </>
                    ) : (
                      <span className="badge">no attempt</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">
          <h3>
            {catalog?.status === "storage_disabled"
              ? "Discovery storage is not configured"
              : unavailable
                ? snapshot
                  ? "Discovery catalog unavailable"
                  : "Waiting for discovery records"
                : loaded.length
                  ? "No matching loaded records"
                  : "No profiles observed yet"}
          </h3>
          <p>
            {!unavailable && loaded.length
              ? "Search and filters apply to this loaded subset only."
              : "Observed profiles appear after the optional discovery worker records a valid window."}
          </p>
        </div>
      )}
      <div className="panel-foot">
        First observed is when this platform saw a profile, not when a token was
        created. An attempted pool lookup can fail or find no pools; it does not
        indicate a passed risk check. Filtering searches only the loaded
        records.
      </div>
      <div className="panel-heading">
        <div>
          <h2>Discovery poll history</h2>
          <p>10 most recent recorded polls · Bounded profile-window coverage</p>
        </div>
      </div>
      {history?.status === "stored_polls" && polls.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Completed at</th>
                <th>Outcome</th>
                <th>Input profiles</th>
                <th>Solana mints</th>
                <th>Source response hash</th>
              </tr>
            </thead>
            <tbody>
              {polls.map((poll) => (
                <tr key={poll.id}>
                  <td className="time">{formatTime(poll.finished_at)}</td>
                  <td>
                    <span className={`badge ${poll.status}`}>
                      {poll.status.replaceAll("_", " ")}
                    </span>
                  </td>
                  <td className="numeric">{poll.input_count ?? "—"}</td>
                  <td className="numeric">{poll.discovered_count ?? "—"}</td>
                  <td>
                    <span
                      className="mint"
                      title={poll.response_hash || undefined}
                    >
                      {poll.response_hash || "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">
          <h3>
            {history?.status === "storage_disabled"
              ? "Poll storage is not configured"
              : history?.status === "stored_polls"
                ? "No discovery polls recorded"
                : snapshot
                  ? "Discovery poll history unavailable"
                  : "Waiting for poll history"}
          </h3>
        </div>
      )}
      <div className="panel-foot">
        Failed polls retain unknown counts (—); a successful empty window shows
        zero. This provider window has coverage bias and does not represent
        every new Solana token.
      </div>
    </section>
  );
}
