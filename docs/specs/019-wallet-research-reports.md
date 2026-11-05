# Spec 019 — Offline wallet evidence and provisional radar scores

Integrate preserved Cluster Radar wallet metrics, possible funding groups and
PRD-weighted research scoring through a bounded offline JSON report command.
No live wallet provider, database mutation, alert producer or trade execution.

`python -m mochex_radar.research_report --input <dataset.json> --output <report.json>`
uses a strict version-1 dataset with UTC as_of/window_end, mint, optional swaps,
funding, pump_features and dump_features. Monetary amounts and normalized feature
values are decimal strings. Max file size 5 MB, max 10000 swaps/funding rows,
max five features per radar. Existing output files are never overwritten. The
input SHA-256 and rule version make reports reproducible. Dataset is normalized
research input, not a claimed provider response schema or immutable source archive.

Swap identity is signature/instruction_path/swap_index. Preserve distinct inner
events; deduplicate provider repeats before mint/window filtering. First eligible
observations are retained, equal-time contradictions fail, later corrections are
counted but cannot rewrite that original evidence. Agreeing sources remain in
provenance. One owner trading across pools is one observed participant. Missing
USD coverage and zero sell denominator stay unknown, not zero/infinity. Independence
is UNVERIFIED; these metrics do not automatically yield independent-buyer features.

Funding groups need timely explicit NON_CEX labels and no conflicting first-funder
or label evidence. CEX/unknown/future labels cannot form links. Return source and
signature references with potential-shared-funding-only conclusions, never ownership
or maliciousness claims. Supplied first-funder assertions still require live history
validation; labels are external evidence, not inferred by this algorithm.

Research weights follow the original PRD. Each supplied normalized feature has
window_start/end, known_at, source, independence_group and references. Features
must share the selected window end; future knowledge, stale windows (>=15 minutes),
missing or mismatched features leave score null, with coverage and observed points
reported separately. A measured zero is valid. Missing confidence is not synthesized.

Dump research threshold requires score >=75 and >=2 warning groups with feature
strength >=0.5 after transitive correlation/shared-reference collapse. Group labels
and feature normalization are declared inputs, not validated independence. All
thresholds remain hypotheses. Every report keeps security UNKNOWN, approval false
and alerts disabled even if its research threshold is met. Full live signals,
state-change alerts, provider history and outcome validation remain unfinished.

Acceptance: offline swap dedup/window/knowledge cases, CEX/future/conflict exclusions,
missing vs measured-zero features, warning correlation collapse, strict CLI parsing,
reproducibility and output-file preservation, plus all existing CI checks.
