# Spec 027 — Local immutable research-run registry

Create private filesystem run bundles from the bounded core-validation dataset.
Each bundle stores exact input bytes, deterministic computed report, source-file
fingerprints, report/config versions, caller-declared synthetic/observed data kind,
selection rationale and UTC registration time. No connection strings or absolute
input paths are recorded. Observed is a declaration, not provider authenticity.

Content-derived run IDs include dataset/report SHA256, source fingerprints, data
kind and rationale. Exclusive directory/file creation refuses duplicate/overwrite.
Write manifest last as the completion marker. Interrupted partial bundles remain
explicitly incomplete and are never reused or automatically deleted.

Verify fixed filenames, bounded file sizes, content hashes and run identity.
Optional replay requires matching current engine fingerprints and exact report
reproduction. A source mismatch never silently replays with different code.
Hashes establish consistency, not signed authenticity or market profitability.
Reject symlink artifacts. There is no provider call, database mutation, alert or
trading; registry defaults are caller-chosen private paths, normally ignored work/.

Acceptance: deterministic IDs, byte-preserving roundtrip, duplicate refusal,
modified/missing artifacts, interrupted bundles, source mismatch, invalid metadata,
bounded reads and CLI create/verify/replay. Existing validation/export tests and
full PostgreSQL/frontend CI must continue to pass.

Format-2 datasets with explicit cost scenarios use the same registry workflow.
Their assumptions participate in dataset/config and run hashes; source-matched
replay verifies both gross and cost-sensitivity results. Format-1 remains gross-only.
