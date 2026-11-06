# Spec 035 — Forward research progress status API and dashboard panel

`GET /api/v1/research/status` exposes bounded, read-only progress counts for explicitly
selected forward paper plans without revealing filesystem paths, raw candle snapshots, or
return figures.

Configuration:
- `RESEARCH_STATUS_ROOT`: optional journal root directory inside the API container (for
  example `/research` or `/research/forward-plans` when `${PAPER_JOURNAL_PATH}` is mounted
  read-only at `/research:ro`). When unset, the endpoint returns `status: "disabled"`,
  `research_only: true`, and `plans: []`.
- `RESEARCH_STATUS_PLAN_IDS`: comma-separated list of at most ten unique 64-character
  lowercase hex plan IDs. Invalid, duplicate, or excessive plan IDs, or a symlink journal
  root, return HTTP 503 with a sanitized message.

For each selected plan ID, `mochex_radar.research_status.research_status` verifies the plan
and stage records through `paper_journal._load_plan` and `paper_journal.summarize` without
modifying `paper_journal.py` or any engine source file, preserving exact SHA-256 source
fingerprints for active campaigns.

Available plans report:
- `plan_id`, `status: "available"`, `asset_id`, `interval`, `decision_start`, `decision_end`,
  `total_slots`, `as_of`,
- `status_counts` (`scheduled`, `awaiting_capture`, `pending_outcome`, `complete`,
  `complete_excluded`, `missed_capture`, `incomplete_capture`, `incomplete_outcome`), and
- `feature_status_counts` (`ok`, `unavailable` across captured slots).

Missing or corrupt plan directories report `status: "unavailable"` with null metadata/counts
for that plan only, without hiding other configured plans or dashboard sections.

Dashboard integration:
- `/api/dashboard` validates `/api/v1/research/status` with `researchSchema` (enforcing slot
  sum and captured-feature sum invariants and rejecting extra fields or duplicate plan IDs).
- `ResearchPanel` (`section#research`) renders the configured plan table, per-plan
  isolation, and distinct `disabled`, `unavailable`, and empty states with an explicit
  research-only disclaimer.
