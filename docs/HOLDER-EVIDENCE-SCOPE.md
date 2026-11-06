# Token account concentration scope

Parser v2 reports token_accounts_only, ownership_verified=false and
locks_verified=false. Small largest-account shares cannot yield PASS and no
typed HolderRiskEvidence is exported. High account concentration warnings remain
conservative account-level heuristics. Existing top_1_unlocked_pct and
top_10_unlocked_pct names remain compatibility aliases for raw token-account
shares of total supply, not evidence of unlocked wallet/controller ownership.

Consumers must not infer lock status or account ownership from these numbers.
Existing stored v1 rows remain immutable; candidate evaluation already suppresses
their account-only PASS. Full renamed-field migration remains a separate change.
