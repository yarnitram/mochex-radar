# Cluster Radar integration

The `cluster_radar/` package is a versioned source snapshot of the separately
preserved project at `C:\Users\Samjie\ProjectCenter\ClusterRadar`, upstream commit
`20a9d5edce573b332d2e9049f284ad16dc989f12`. The original project and its Git history
remain independent. Its PRD is preserved verbatim in `ORIGINAL-PRD.md`.
Upstream declares proprietary/internal usage; retain that restriction.

`snapshot.json` records SHA-256 hashes for source files. Tests from that version
are included under `tests/cluster`. To update: create a feature branch, review
upstream changes, copy only tracked source and tests, regenerate hashes, run both
test suites, and commit the reviewed snapshot. Never copy `.env`, virtual environments,
caches, or `.git`. Changes to provider primitives should originate upstream.

The integrated slice exposes public Solana pool context, a bounded latest-profile feed, partial mint-authority evidence, security gating and
funding evidence, normalized swap metrics and provisional PRD-weighted research scores. It does not implement the full original PRD.
Future provider entitlements, wallet history, alerting, and independent Pump/Dump
signals remain open milestones.
