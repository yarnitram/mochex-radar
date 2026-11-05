"""Verified private-pilot release operations inside a dedicated Linux guest."""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tarfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO = "yarnitram/mochex-radar"
PROJECT = "mochex-radar"
SHA = re.compile(r"[0-9a-f]{40}")
SERVICES = ("api", "dashboard", "collector", "streamer")


def private_environment(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("private env must be an existing regular file")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise ValueError("private env permissions must be 0600 or stricter")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or value.startswith(("'", '"')) or key in values:
            raise ValueError("private env requires unique unquoted KEY=value lines")
        values[key] = value
    password, token = values.get("POSTGRES_PASSWORD", ""), values.get("RADAR_API_TOKEN", "")
    if len(password) < 24 or len(token) < 32 or "replace-with" in password:
        raise ValueError("generated database password and API token required")
    url = urllib.parse.urlsplit(values.get("DATABASE_URL", ""))
    if (url.scheme != "postgresql" or url.hostname != "db" or url.port != 5432 or url.path != "/radar"
            or url.username != "radar" or urllib.parse.unquote(url.password or "") != password):
        raise ValueError("DATABASE_URL must match the internal pilot database identity/password")
    for key, default in (("RADAR_API_PORT", "8000"), ("RADAR_DASHBOARD_PORT", "3000")):
        if not values.get(key, default).isdigit() or not 1024 <= int(values.get(key, default)) <= 65535:
            raise ValueError("pilot ports must be explicit unprivileged ports")
    return values


def validate_paths(source, state, env_file):
    for path in (source, state, env_file):
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("explicit absolute non-symlink paths required")
    source, state, env_file = source.resolve(), state.resolve(), env_file.resolve()
    if os.name == "posix" and state.exists() and state.stat().st_mode & 0o077:
        raise ValueError("deployment state permissions must be 0700 or stricter")
    if state == source or source in state.parents or state in source.parents or source in env_file.parents:
        raise ValueError("deployment state and secrets must be outside the source checkout")
    if state.exists() and any(state.iterdir()):
        marker = state / ".mochex-state"
        if marker.is_symlink() or not marker.is_file() or marker.read_text() != REPO:
            raise ValueError("refusing to adopt unmanaged state directory")
    if any((state / name).is_symlink() for name in ("releases", "research", "backups", "current.json", "failed.json", "deployment.lock")):
        raise ValueError("managed deployment paths must not be symlinks")
    return source, state, env_file


def successful_ci(runs, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("full commit SHA required")
    return any(row.get("headSha") == sha and row.get("status") == "completed" and row.get("conclusion") == "success" for row in runs)


def release_transaction(candidate, previous, build, backup, start, verify, persist):
    build(candidate)
    if previous:
        backup(previous)
    try:
        start(candidate)
        verify(candidate)
        persist(candidate, previous)
    except Exception:
        if previous:
            try:
                start(previous)
                verify(previous)
            except Exception:
                raise RuntimeError("candidate and previous runtime failed; preserve volumes for manual recovery") from None
            raise RuntimeError("candidate failed; previous runtime recovered; active state unchanged") from None
        raise RuntimeError("initial release failed; preserve state/volumes and inspect before retry") from None


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Runtime:
    def __init__(self, source, state, env_file):
        self.source, self.state, self.env_file = validate_paths(source, state, env_file)
        self.values = private_environment(self.env_file)
        self.environment = {**os.environ, **self.values, "GIT_TERMINAL_PROMPT": "0",
                            "GIT_SSH_COMMAND": "ssh -oBatchMode=yes -oStrictHostKeyChecking=yes",
                            "COMPOSE_PROFILES": "", "TELEGRAM_SEND_ENABLED": "false", "ALERT_DATA_QUALITY_ENABLED": "false",
                            "DEX_LOOKUP_ENABLED": "false", "SOLANA_AUTHORITIES_ENABLED": "false",
                            "PAPER_JOURNAL_PATH": str(self.state / "research")}

    def run(self, command, cwd=None, env=None, stdout=None):
        result = subprocess.run(command, cwd=cwd or self.source, env=env or self.environment,
                                stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError(f"{command[0]} operation failed; inspect private guest diagnostics")
        return result.stdout.decode("utf-8").strip() if stdout is None else ""

    def git(self, *args, root=None):
        return self.run(["git", "-C", str(root or self.source), *args])

    def preflight(self):
        if self.git("rev-parse", "--show-toplevel").replace("\\", "/") != str(self.source).replace("\\", "/"):
            raise ValueError("source root mismatch")
        if self.git("remote", "get-url", "origin") not in (f"git@github.com:{REPO}.git", f"https://github.com/{REPO}.git"):
            raise ValueError("unexpected Git origin")
        if self.git("status", "--porcelain"):
            raise ValueError("source checkout must be clean")
        if self.git("branch", "--show-current") != "main":
            raise ValueError("source checkout must track main")
        self.run(["docker", "info", "--format", "{{.ServerVersion}}"])
        self.run(["docker", "compose", "version", "--short"])
        self.run(["gh", "--version"])
        if not (self.state / ".mochex-state").exists():
            existing = self.run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"])
            if existing:
                raise ValueError("existing unmanaged pilot containers; verify ownership before adopting")
            if self.run(["docker", "volume", "ls", "-q", "--filter", f"name=^{PROJECT}_postgres_data$"]):
                raise ValueError("existing unmanaged pilot database volume; verify ownership before adopting")
        return {"status": "preflight_passed", "source": str(self.source), "state": str(self.state), "credentials": "not_displayed"}

    def release(self, sha):
        if not SHA.fullmatch(sha):
            raise ValueError("invalid release SHA")
        return self.state / "releases" / sha

    def compose(self, sha, *args, stdout=None):
        env = {**self.environment, "RADAR_APP_IMAGE": f"mochex-radar-api:{sha}", "RADAR_DASHBOARD_IMAGE": f"mochex-radar-dashboard:{sha}"}
        return self.run(["docker", "compose", "--project-name", PROJECT, "--env-file", str(self.env_file),
                         "-f", str(self.release(sha) / "compose.yaml"), *args], env=env, stdout=stdout)

    def build(self, sha):
        release = self.release(sha)
        if release.is_symlink():
            raise ValueError("release symlink unsupported")
        if not release.exists():
            release.parent.mkdir(parents=True, exist_ok=True)
            self.git("worktree", "add", "--detach", str(release), sha)
        if self.git("rev-parse", "HEAD", root=release) != sha or self.git("status", "--porcelain", root=release):
            raise ValueError("release worktree is not the exact clean commit")
        config = json.loads(self.compose(sha, "config", "--format", "json"))
        if not config["services"]["db"]["image"].startswith("postgres:17@sha256:"):
            raise ValueError("PostgreSQL major upgrade requires manual migration review")
        if 'SCHEMA_VERSION = "pilot-schema-v1"' not in (release / "mochex_radar" / "initialize.py").read_text():
            raise ValueError("schema upgrade requires manual migration review")
        for name in ("api", "dashboard"):
            if any(p.get("host_ip") != "127.0.0.1" for p in config["services"][name]["ports"]):
                raise ValueError("private pilot requires loopback host ports")
        self.compose(sha, "build", "api", "dashboard")

    def backup(self, sha):
        active = set(self.compose(sha, "ps", "--services", "--filter", "status=running").splitlines())
        if active - {*SERVICES, "db", "redis"}:
            raise ValueError("quiesce optional workers before backing up/updating the private pilot")
        destination = self.state / "backups" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
        destination.mkdir(parents=True, mode=0o700)
        with (destination / "database.dump").open("xb") as handle:
            self.compose(sha, "exec", "-T", "db", "pg_dump", "-U", "radar", "-d", "radar", "-Fc", stdout=handle)
        with tarfile.open(destination / "research.tar.gz", "x:gz", dereference=False) as archive:
            archive.add(self.state / "research", arcname="research")
        manifest = {"source_sha": sha, "database_sha256": digest_file(destination / "database.dump"),
                    "research_sha256": digest_file(destination / "research.tar.gz")}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    def start(self, sha):
        self.compose(sha, "up", "-d", "--no-build", "db", "redis")
        self.compose(sha, "run", "--rm", "initialize")
        self.compose(sha, "up", "-d", "--no-build", "--wait", "--wait-timeout", "120", *SERVICES)

    def verify(self, sha):
        api_port = self.values.get("RADAR_API_PORT", "8000")
        dashboard_port = self.values.get("RADAR_DASHBOARD_PORT", "3000")
        with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/health/ready", timeout=10) as response:
            if not json.load(response)["durable_store_ready"]:
                raise RuntimeError("candidate durable readiness failed")
        with urllib.request.urlopen(f"http://127.0.0.1:{dashboard_port}/api/dashboard", timeout=15) as response:
            if json.load(response)["core"]["status"] != "available":
                raise RuntimeError("candidate dashboard data unavailable")

    def persist(self, candidate, previous):
        # Update the source main branch only when it can fast-forward; rollback
        # releases keep the newer updater checkout while running older images.
        head = self.git("rev-parse", "HEAD")
        if head != candidate:
            ancestor = subprocess.run(["git", "-C", str(self.source), "merge-base", "--is-ancestor", head, candidate], env=self.environment, capture_output=True)
            if ancestor.returncode == 0:
                self.git("merge", "--ff-only", candidate)
        pending = self.state / (".current-" + uuid4().hex + ".tmp")
        pending.write_text(json.dumps({"sha": candidate, "previous_sha": previous, "updated_at": datetime.now(timezone.utc).isoformat()}) + "\n")
        os.replace(pending, self.state / "current.json")

    def update(self, rollback=None, retry_failed=False):
        self.preflight()
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker = self.state / ".mochex-state"
        if not marker.exists():
            with marker.open("x") as handle: handle.write(REPO)
        (self.state / "research").mkdir(mode=0o700, exist_ok=True)
        import fcntl
        with (self.state / "deployment.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = json.loads((self.state / "current.json").read_text())["sha"] if (self.state / "current.json").exists() else None
            self.git("fetch", "origin", "main")
            self.git("merge-base", "--is-ancestor", "HEAD", "origin/main")
            candidate = rollback or self.git("rev-parse", "origin/main")
            if not SHA.fullmatch(candidate): raise ValueError("full candidate SHA required")
            self.git("merge-base", "--is-ancestor", candidate, "origin/main")
            runs = json.loads(self.run(["gh", "run", "list", "--repo", REPO, "--commit", candidate, "--workflow", "tests.yml",
                                        "--limit", "20", "--json", "headSha,status,conclusion"]))
            if not successful_ci(runs, candidate):
                return {"status": "waiting_for_successful_ci", "sha": candidate}
            if candidate == current:
                self.verify(candidate)
                return {"status": "already_current", "sha": candidate}
            failed = self.state / "failed.json"
            if not retry_failed and failed.exists() and json.loads(failed.read_text()).get("sha") == candidate:
                return {"status": "previously_failed_candidate", "sha": candidate}
            try:
                release_transaction(candidate, current, self.build, self.backup, self.start, self.verify, self.persist)
            except (OSError, RuntimeError, ValueError):
                if current is None:
                    try:
                        self.compose(candidate, "stop", *SERVICES)
                    except RuntimeError:
                        pass
                failed.write_text(json.dumps({"sha": candidate, "failed_at": datetime.now(timezone.utc).isoformat()}) + "\n")
                raise
            return {"status": "deployed", "sha": candidate, "previous_sha": current}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "update", "rollback"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        parser.error("deployment tooling targets a verified Linux amd64 guest")
    if Path("/etc/pve").exists():
        parser.error("run inside a dedicated guest, never on the Proxmox hypervisor")
    if args.command != "preflight" and not args.apply:
        parser.error("update/rollback requires --apply")
    if args.command == "rollback" and (not args.revision or not SHA.fullmatch(args.revision)):
        parser.error("rollback requires a full --revision SHA")
    try:
        runtime = Runtime(args.source, args.state, args.env_file)
        result = runtime.preflight() if args.command == "preflight" else runtime.update(args.revision if args.command == "rollback" else None, args.retry_failed)
        print(json.dumps(result))
    except (OSError, ValueError, RuntimeError, KeyError):
        raise SystemExit("Pilot operation stopped; inspect private guest diagnostics, preserve data/state, and follow recovery runbook.") from None


if __name__ == "__main__":
    main()
