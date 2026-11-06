# Mochex Radar — Proxmox private research pilot

Status: local tooling and isolated-stack tests prepared; no Proxmox host or guest
has been accessed or changed. This is the deployment gate for collecting durable
observations, not completion of the full product or proof of profitable signals.

## Verify before provisioning

Confirm the Proxmox node/address, intended guest ID/name, available storage/network,
SSH username/authentication route and backup destination. Verify that any existing
guest belongs to this project before changing it. Never install Docker or these
scripts on the Proxmox hypervisor. The deployment CLI refuses `/etc/pve` hosts and
targets Linux amd64 guests.

Use a dedicated QEMU VM for the pilot's Docker Compose stack. This is our isolation
choice; Proxmox documents QEMU nesting as recommended where stronger isolation/
live migration is needed: [official container documentation](https://github.com/proxmox/pve-docs/blob/master/pct.adoc).
Proposed starting allocation is 2 vCPU, 4GB RAM and 40GB disk; confirm against host
capacity, image-build peaks and actual data retention before creating it. No
specific guest ID, bridge, IP, datastore or existing path is assumed verified.

## Proposed guest layout — verify actual paths first

- Source checkout: `/srv/mochex-radar/source`, branch main, exact origin
  `git@github.com:yarnitram/mochex-radar.git` (HTTPS origin also supported).
- Private runtime config: `/etc/mochex-radar/runtime.env`, mode 0600, owned/readable
  by the dedicated deployment user. Keep it outside the checkout and out of chat.
- Dedicated deployment state: `/var/lib/mochex-radar`, private 0700; initially empty.
  Releases, active SHA, update lock, research files and local backups live here.
- Docker Compose project: `mochex-radar`; durable PostgreSQL volume is preserved.
  Existing containers/volumes with that project name require ownership review.

Create a dedicated guest user (template name `mochex`) with authorized Docker
access, Git and GitHub CLI. Docker daemon access is privileged; this belongs inside
the dedicated guest. Configure a read-only repository deploy key and verified host
keys, plus GitHub Actions read access for exact-commit CI checks. Do not bypass SSH
host-key verification. Authentication must work noninteractively for the timer.
Use a supported guest OS with Python 3.12+, Docker Engine and Compose v2 with
`--wait` support. The image/runtime versions are pinned in the source tree.

Generate independent random values privately for POSTGRES_PASSWORD (at least 24
characters) and RADAR_API_TOKEN (at least 32). Use URL-safe values or URL-encode the
database password in DATABASE_URL. Private config uses unquoted KEY=value lines:

```text
POSTGRES_PASSWORD=<GENERATED_DATABASE_PASSWORD>
DATABASE_URL=postgresql://radar:<URL_ENCODED_SAME_PASSWORD>@db:5432/radar
RADAR_API_TOKEN=<INDEPENDENT_GENERATED_API_TOKEN>
RADAR_API_PORT=8000
RADAR_DASHBOARD_BIND_HOST=127.0.0.1
RADAR_DASHBOARD_PORT=3000
```

No exchange account credentials are needed. Telegram, DEX provider checks and paper
profiles stay disabled by the pilot updater. Public CEX collector/streamer are the
only automatically started acquisition workers. Redis stores disposable intrabar
state; PostgreSQL stores durable closed observations. Authority/security unknowns
remain unknown. Research files use persistent state outside release worktrees.

## First deployment

After path/guest checks, use the actual verified values:

```text
python3 /srv/mochex-radar/source/scripts/deployment.py preflight --source /srv/mochex-radar/source --state /var/lib/mochex-radar --env-file /etc/mochex-radar/runtime.env
python3 /srv/mochex-radar/source/scripts/deployment.py update --source /srv/mochex-radar/source --state /var/lib/mochex-radar --env-file /etc/mochex-radar/runtime.env --apply
```

Preflight is read-only. Update fetches origin/main, verifies main ancestry and
successful complete tests.yml CI for the exact SHA, creates a clean detached release
worktree, builds per-commit images, initializes stores and checks API/dashboard.
Only successful deployment advances current.json and fast-forwards the source
checkout when possible. No reset, volume deletion or unverified blind pull occurs.
Readiness uses sanitized `/health/ready`; cache outage is degraded while durable
queries remain available. Compose waits for running/healthy services, as documented
by [Docker](https://docs.docker.com/reference/cli/docker/compose/up/).

Connect privately through SSH forwarding, for example forward local 3110 to the
guest's loopback 3000. For trusted-LAN access only, set
`RADAR_DASHBOARD_BIND_HOST=0.0.0.0`, restrict TCP/3000 in the guest firewall, and
use `http://<guest-ip>:3000`; do not expose it to the public internet. The
dashboard API token is forwarded by its server, never placed in a NEXT_PUBLIC
variable or browser response. No public proxy/login/TLS configuration is included
in this pilot. Verify seven registered pairs, initial
missing/stale states, collector health and then growing stored observations. Do
not treat an empty but healthy deployment as validated signals.

## Updates, backup and rollback

The updater pauses a running Telegram alert worker while writing the backup and
resumes it even when backup creation fails. Other optional workers still require
manual quiescence before deployment. Alert delivery can briefly pause during updates.

Each update builds first, backs up the existing database/research files with hash
manifest, starts the candidate and commits active state only after health succeeds.
If the candidate fails, previous app images/config are restarted and checked;
database volumes are never removed or restored over automatically. Failed SHAs are
not repeatedly retried by the timer; diagnose them, then explicitly use
`--retry-failed` if appropriate. If both candidate and recovery fail, preserve all
state, stop updates and follow manual recovery. PostgreSQL major changes and schema
marker changes require separate migration review.

Local backups are under `state/backups/<timestamp-id>` and contain `database.dump`,
`research.tar.gz`, and SHA256 manifest. Quiesce optional paper/alert/discovery workers
before deployment backup; tooling refuses active optional Compose services. Also
quiesce any manually launched research writers before archiving. Copy backups to
a verified off-guest destination; local files alone do not protect against guest/
datastore loss. Never put runtime secrets in a Markdown backup manifest.

Before enabling automatic updates, demonstrate restore into a separate disposable
database/guest and verify expected nonempty rows and research-file hashes. For
manual PostgreSQL restore, use createdb/pg_restore into a **new named target**, not
the running pilot database. Verify archive member paths before extracting research
files into a new directory; reject absolute paths, traversal and link escapes.
Keep the failed/current database and original backups untouched until recovery is
confirmed. Isolated-stack CI tests nonempty pg_dump/pg_restore and restart persistence;
actual guest restore/reboot/off-guest backup are still deployment acceptance checks.

To return to a known previously verified commit, disable the timer first and run:

```text
python3 /srv/mochex-radar/source/scripts/deployment.py rollback --source /srv/mochex-radar/source --state /var/lib/mochex-radar --env-file /etc/mochex-radar/runtime.env --revision <FULL_SUCCESSFUL_SHA> --apply
```

This is code rollback with the retained database, not a destructive schema downgrade.
Preserve prior images/worktrees; no automatic image/worktree/backup pruning is done.
Check free space/retention and manually review cleanup paths before deleting anything.

## Enable the optional timer only on the verified guest

Edit the templates under `deploy/` to match the verified user and paths. Install the
service/timer with normal guest administration after a successful manual deployment,
restart, restore and credentials check. The timer checks hourly with a small random
delay and uses a deployment lock. Waiting-for-CI and previously-failed candidates
do not change the current runtime. Keep it disabled during migrations, paper capture
maintenance or rollback investigations. Nothing installs/enables these templates
from the local Windows workspace.

## Outstanding product work remains visible

See REMAINING-ROADMAP.md: live wallet history/provider access, independently validated
Pump/Dump evidence, remaining token risk, broad provenance-backed Meme/AI coverage,
real-data threshold/outcome evidence, market depth/impact and a long-running forward
campaign remain incomplete. Deploying the private pilot enables data collection;
it does not activate unvalidated signals, trading or Telegram sending.
