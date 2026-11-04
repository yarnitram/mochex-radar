# Cluster Radar starter audit — 2026-11-05

Source archive: `ClusterRadar_Codex_Starter.zip` supplied in the CryptoRadar checkout. SHA-256: `DF37FD2F34A7C7EB9AF828FAF6DAC461D1037D66D2C19898FB4A3C7C8B39CA7A`.

The archive was inspected and extracted for audit. Its `ClusterRadar/` source was preserved as a sibling project at `C:\Users\Samjie\ProjectCenter\ClusterRadar`; its canonical PRD is `docs/PRD.md` in that project. The package identifies itself as a starter scaffold. It has one Pump Watch eligibility rule in `src/cluster_radar/signals/rules.py`, a CLI demo/doctor, and two tests. Those tests pass unchanged. The provider, discovery, security, storage, notification, backtest, Pump Radar, and Dump Radar packages are placeholders. No live scanner or wallet-cluster engine exists in the starter.

Integration boundary: keep the sibling project intact. Implement its planned capabilities in that project on dedicated branches, then expose read-only results through a versioned adapter to Mochex Radar. The inherited score 75 and four-wallet/two-evidence screening concepts remain unvalidated research thresholds. Do not present the starter demo as live intelligence.

The original ZIP remains in the CryptoRadar folder until the preserved copy and subsequent integration are verified; the user requested deletion after use.
