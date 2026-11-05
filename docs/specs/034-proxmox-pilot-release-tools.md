# Spec 034 — Private Proxmox pilot deployment gate

## Controlled Telegram alert opt-in

The deployment updater keeps the `alerts` Compose profile, Telegram sending and
data-quality notice generation disabled by default. It may activate them only
when `RADAR_ALERTS_ENABLED=true`, `TELEGRAM_SEND_ENABLED=true`, a valid Telegram
bot token and a numeric chat ID are all present in the private runtime file.
Invalid or incomplete alert credentials fail preflight before any release starts.

Provide Linux guest tooling; never run on the Proxmox hypervisor or invent host/
guest IDs. Verify the source root/Git remote, clean checkout, external private env,
dedicated state path, required commands and private loopback configuration before
mutation. Require internal database identity/password consistency and a generated
API token. Unmanaged project/state paths must not be adopted silently.

Fetch origin/main noninteractively; require full SHA on main ancestry plus successful
completed tests.yml CI for that exact SHA. Use immutable detached Git worktrees and
per-commit application image tags. Do not reset user work or blindly git pull.
Build before touching current runtime, snapshot current PostgreSQL and research
files, start candidate and verify readiness/dashboard access. Persist active SHA
only after success. On failure recover previous app images/config and health;
never drop volumes or restore over production automatically. Pilot schema-v1 and
PostgreSQL major 17 compatibility are required; incompatible upgrades stop.

Serialize updates with a guest file lock. Backups are exclusive private files with
SHA256 manifest, streamed pg_dump and research tar; off-guest copies are still an
operator requirement. Keep research outside release worktrees. Optional/provider/
sending profiles remain disabled by tooling. Add disabled-by-default systemd
service/timer templates for verified Git updates after guest paths/access are checked.

Test selection/path/env guards and update/recovery ordering with isolated callbacks.
Real disposable stack must prove nonempty database dump/restore into a separate
test database, API restart persistence and cache-outage recovery. Actual guest SSH,
reboot, backup destination and timer installation remain deployment-gate inputs.
Do not mark the full product roadmap complete or assert actual alpha/forward results.
