"use client";

import type { Snapshot } from "@/lib/contracts";

const date = (value: string) =>
  new Date(value).toLocaleString(undefined, { hour12: false });

export default function ResearchPanel({
  snapshot,
  outdated,
}: {
  snapshot: Snapshot | null;
  outdated: boolean;
}) {
  const service = snapshot?.research;
  const data = service?.data;
  const plans = data?.status === "configured" ? data.plans : [];
  return (
    <section
      className="panel"
      id="research"
      aria-labelledby="research-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="research-title">Forward research progress</h2>
          <p>
            Predeclared observation schedules · Count-only journal status ·
            Signals disabled
          </p>
        </div>
        <span className={`badge ${outdated ? "outdated" : ""}`}>
          {outdated
            ? "outdated"
            : data?.status === "configured"
              ? `${plans.length} plans`
              : data?.status === "disabled"
                ? "disabled"
                : snapshot
                  ? "unavailable"
                  : "loading"}
        </span>
      </div>
      {data?.status === "configured" && plans.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Plan / market</th>
                <th>Schedule / slots</th>
                <th>Completed / pending</th>
                <th>Remaining / missed</th>
                <th>Captured features</th>
                <th>Evaluated at</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((plan) => {
                const incomplete =
                  plan.status === "available"
                    ? plan.status_counts.incomplete_capture +
                      plan.status_counts.incomplete_outcome
                    : 0;
                return (
                  <tr key={plan.plan_id}>
                    <td>
                      <span className="mint" title={plan.plan_id}>
                        {plan.plan_id.slice(0, 12)}…
                      </span>
                      <small className="provenance">
                        {plan.status === "available"
                          ? `${plan.asset_id.split(":").pop()} · ${plan.interval}`
                          : "Journal unavailable"}
                      </small>
                    </td>
                    <td>
                      {plan.status === "available" ? (
                        <>
                          <span className="time">
                            {date(plan.decision_start)} →{" "}
                            {date(plan.decision_end)}
                          </span>
                          <small className="provenance">
                            {plan.total_slots} total slots
                          </small>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {plan.status === "available" ? (
                        <span>
                          {plan.status_counts.complete} complete ·{" "}
                          {plan.status_counts.complete_excluded} excluded ·{" "}
                          {plan.status_counts.pending_outcome} pending
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {plan.status === "available" ? (
                        <span>
                          {plan.status_counts.scheduled} scheduled ·{" "}
                          {plan.status_counts.awaiting_capture} awaiting ·{" "}
                          {plan.status_counts.missed_capture} missed
                          {incomplete ? ` · ${incomplete} incomplete` : ""}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {plan.status === "available" ? (
                        <span>
                          {plan.feature_status_counts.ok} ok ·{" "}
                          {plan.feature_status_counts.unavailable} unavailable
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {plan.status === "available" && (
                        <span className="time">{date(plan.as_of)}</span>
                      )}
                      <span
                        className={`badge ${
                          outdated
                            ? "outdated"
                            : plan.status === "available"
                              ? "current"
                              : "blocked"
                        }`}
                      >
                        {outdated ? "outdated" : plan.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">
          <h3>
            {data?.status === "disabled"
              ? "Forward research status is not configured"
              : data?.status === "configured"
                ? "No forward research plans selected"
                : snapshot
                  ? "Forward research status unavailable"
                  : "Waiting for forward research status"}
          </h3>
          <p>
            Only explicitly configured plan IDs are summarized here. Raw
            snapshots, private paths and return figures are never exposed.
          </p>
        </div>
      )}
      <div className="panel-foot">
        Counts reflect hash-verified local journal records only. Completed slots
        do not imply profitability, execution feasibility, or signal approval.
      </div>
    </section>
  );
}
