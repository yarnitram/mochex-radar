# Deployed pilot checkpoint — 2026-11-06

The user confirmed successful deployment of
`f15e2b627aaf368bd07040a0d86b916f2f1f1d24` on CT 110, mochexradar.
The dashboard is reachable at http://192.168.2.35:3000. Persistent Telegram
delivery is enabled. MEXC REST returned HTTP 200 with zero provider failures
after DNS repair. The hourly verified update timer is installed. Deployment
now pauses and resumes the alert worker during backup.

This supersedes the remaining roadmap's description of guest provisioning and
Telegram credentials as pending external inputs. Backup restore and reboot
recovery on the actual guest still need recorded evidence.

## Next gate: durable data coverage

Audit all seven registered futures instruments and BTC on 15m/1h intervals.
Record row counts, latest closed candle and retrieval timestamps, and gaps.
HTTP success and zero duplicate inserts alone do not prove adequate history.
Confirm WebSocket message freshness independently; absence of log errors is
insufficient. Export stored validation data only after reporting these gaps.

Acceptance: deterministic read-only coverage report; expected identities remain
visible when absent; stale, incomplete and late-retrieved observations cannot
approve signals. Preserve original ingestion timestamps for replay.

Wallet history provider access, broader risk evidence, real-data backtest
comparisons and forward paper evidence remain unfinished product work.
