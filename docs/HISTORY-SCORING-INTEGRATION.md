# Wallet history to candidate scoring: next integration gate

Current state: normalized swaps/funding and swap_metrics exist; candidate
evaluation still passes empty feature arrays. The scorer expects bounded 0..1
features with window, known_at, source, independence group and references.

Implement immutable normalized-history storage before connecting scores. Preserve
transaction identity, observation/ingestion times, parser version, wallet/mint,
raw evidence hash and completeness status. Read with both knowledge and ingestion
cutoffs. Conflicting duplicates must be rejected, not silently replaced.

Do not equate unique wallets with independent buyers. CEX/unknown funding labels
cannot establish independence. Incomplete pagination/history must remain visible.
Predeclare feature normalization/version and thresholds; missing history,
controller identity, liquidity depth or wallet quality cannot be zero-filled.
Do not map raw swap counts directly to all five weighted score dimensions.

Acceptance: future ingestion exclusion, conflicting duplicates, incomplete history,
shared references collapsing warning groups, and missing feature gates. Candidate
responses must retain provisional status, signals disabled and independent token
risk gates. Provider activation and guest rollout follow offline contract tests.
