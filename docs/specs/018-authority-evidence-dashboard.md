# Spec 018 — Stored authority evidence visibility

New read-only `/api/v1/security/authorities/snapshot?limit=100` reads the newest
stored observations, not a live RPC check. Applies both known-at and ingestion
cutoffs at server UTC time, with limit 1..100, a recent-observation index, and the
same 15-minute freshness formatter as per-mint history. Missing storage reports
disabled; unavailable schema/database reports 503. No enabled RPC provider is needed.

Dashboard adds case-sensitive loaded-mint search and observation-age filters.
Multiple rows may belong to one mint. Display mint/freeze permissions separately
from overall UNKNOWN security, plus source, parser version, RPC context slot,
known-at time and unsupported-case reason. DISABLED is labeled absent, without
green approval styling. Token-2022 and unsupported cases remain unknown. No check,
approve, send, retry, signing or trade controls are introduced.

The server aggregator validates the bounded snapshot independently with no cache
and its existing timeout. Runtime schema requires UNKNOWN/false approval, consistent
permission/address pairs, supported parser/source, cutoffs and 15-minute expiry.
An authority-service outage leaves other sections available. A browser refresh
failure retains rows with outdated labels. Disabled, unavailable, loading, empty
and no-match states are distinct. Freshness describes age at the snapshot cutoff,
not independent chain-head confirmation or security approval. It is not token age.

Acceptance: stored snapshot SQL excludes future observations; existing point-in-time
and DB approval constraints pass. Runtime tests reject approval, inconsistent
permission pairs or invalid freshness. Browser tests cover filtering, unsupported
cases, stale refresh, distinct storage states, partial outage and no live RPC calls.
Build/typecheck, actual API disabled-state smoke and full CI must pass before merge.
