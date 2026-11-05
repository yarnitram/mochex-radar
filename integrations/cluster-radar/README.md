# Cluster Radar integration

The `cluster_radar/` package is a versioned source snapshot of the separately
preserved project at `C:\Users\Samjie\ProjectCenter\ClusterRadar`, upstream commit
`5c317e9cadb148885e4271e926a4be7eb740b927`. The original project and its Git history
remain independent. Its PRD is preserved verbatim in `ORIGINAL-PRD.md`.
Upstream declares proprietary/internal usage; retain that restriction.

`snapshot.json` records SHA-256 hashes for source files. Tests from that version
are included under `tests/cluster`. To update: create a feature branch, review
upstream changes, copy only tracked source and tests, regenerate hashes, run both
test suites, and commit the reviewed snapshot. Never copy `.env`, virtual environments,
caches, or `.git`. Changes to provider primitives should originate upstream.

The integrated slice exposes public Solana pool context, security gating and
funding evidence primitives. It does not implement the full original PRD.
Future provider entitlements, wallet history, alerting, and independent Pump/Dump
signals remain open milestones.
