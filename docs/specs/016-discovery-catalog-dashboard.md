# Spec 016 — Discovery catalog visibility

Read the existing bounded mint catalog (100 newest records) and poll history
(10 newest polls) through independent no-cache server-side dashboard requests.
The catalog/poll services each have a five-second timeout. No provider HTTP
requests, schema changes, scanning, alerts or delivery actions are introduced.

Display full mint identity in text/title, fixed source provenance, first/last
profile observation times and recorded pool-lookup attempts. A lookup attempt may
fail or return no pools; it is not a security assessment. First observation is not
token creation time. All profile candidates remain unclassified and security
UNKNOWN; the runtime contract requires approved_pump_watch=false.

Search is case-sensitive because Solana mint identities are case-sensitive.
All / No attempt / Attempt recorded filters apply only to the loaded subset.
There is no claim that search covers the complete stored catalog or Solana universe.
Historical replay still requires immutable observations and ingestion cutoffs.

Poll history retains unknown counts as em dashes on failed/budget-exhausted polls;
successful empty polls show zero. Schema rejects inconsistent outcome/count/hash
combinations, bad timestamps, invalid identities or accidental safety approval.
Individual service failure keeps the other services visible. Browser refresh
failure retains the prior snapshot with an outdated label. Loading, disabled,
unavailable, empty and no-match states remain distinct.

Acceptance: production build/typecheck, runtime schema tests for conservative
security and poll integrity, browser tests for search/filters, partial outages,
refresh retention, disabled vs empty states, and mobile overflow. Actual FastAPI
smoke verifies disabled-state compatibility. Existing full CI must pass before merge.
