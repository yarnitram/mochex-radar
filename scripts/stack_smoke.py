"""Build and verify an isolated private stack; never starts provider/sending workers."""

import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = "mochex-smoke-" + uuid.uuid4().hex[:10]
    password, token = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
    with tempfile.TemporaryDirectory(prefix="mochex-smoke-") as temporary:
        paper_dir = Path(temporary) / "paper-plans"
        paper_dir.mkdir()
        env_file = Path(temporary) / "private.env"
        with env_file.open("x", encoding="utf-8") as handle:
            handle.write(f"POSTGRES_PASSWORD={password}\nDATABASE_URL=postgresql://radar:{password}@db:5432/radar\nRADAR_API_TOKEN={token}\nRADAR_API_PORT=0\nRADAR_DASHBOARD_PORT=0\nRADAR_APP_IMAGE={project}-api\nRADAR_DASHBOARD_IMAGE={project}-dashboard\nPAPER_JOURNAL_PATH={paper_dir}\n")
        if os.name != "nt":
            env_file.chmod(0o600)
        command = ["docker", "compose", "--project-name", project, "--env-file", str(env_file), "-f", str(ROOT / "compose.yaml")]
        def compose(*args):
            result = subprocess.run([*command, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode:
                safe = (result.stderr + result.stdout)[-6000:].replace(password, "[redacted]").replace(token, "[redacted]")
                raise RuntimeError("isolated Compose operation failed:\n" + safe)
            return result.stdout.strip()
        def get(url, auth=False):
            request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token} if auth else {})
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.read().decode()
        try:
            print("Building pinned API and dashboard images...", flush=True)
            compose("build", "api", "dashboard")
            print("Starting isolated database/cache/schema/API/dashboard only...", flush=True)
            compose("up", "-d", "db", "redis", "api", "dashboard")
            api = "http://" + compose("port", "api", "8000")
            dashboard = "http://" + compose("port", "dashboard", "3000")
            for _ in range(60):
                try:
                    if json.loads(get(api + "/health/ready"))["durable_store_ready"]:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("API did not become ready")
            try:
                get(api + "/api/v1/dashboard/core")
                raise AssertionError("unauthenticated data request succeeded")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            core = json.loads(get(api + "/api/v1/dashboard/core", auth=True))
            assert len(core["markets"]) == 7 and all(row["status"] == "missing" for row in core["markets"])
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    if "MOCHEX" in get(dashboard + "/"):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("dashboard did not become ready")
            payload = get(dashboard + "/api/dashboard")
            assert token not in payload and password not in payload
            snapshot = json.loads(payload)
            assert snapshot["core"]["status"] == "available"
            assert snapshot["features"]["status"] == "available"
            assert all(snapshot[name]["status"] == "available" for name in ("btc", "collector", "scans", "outbox", "catalog", "profilePolls", "authorities", "research"))
            assert compose("exec", "-T", "api", "id", "-u") == "10001"
            assert compose("exec", "-T", "dashboard", "id", "-u") != "0"
            assert compose("exec", "-T", "api", "python", "-c", "import os;print(bool(os.statvfs('/app').f_flag & os.ST_RDONLY))") == "True"
            try:
                compose("exec", "-T", "api", "python", "-c", "open('/app/write-test','w').write('x')")
                raise AssertionError("API root filesystem was writable")
            except RuntimeError:
                pass
            compose("stop", "redis")
            assert json.loads(get(api + "/health/ready"))["status"] == "degraded"
            assert len(json.loads(get(api + "/api/v1/dashboard/core", auth=True))["markets"]) == 7
            compose("start", "redis")
            compose("exec", "-T", "db", "psql", "-U", "radar", "-d", "radar", "-c",
                    "CREATE TABLE recovery_smoke (id integer PRIMARY KEY, value text); INSERT INTO recovery_smoke VALUES (1,'recovery-ok');")
            backup = Path(temporary) / "database.dump"
            with backup.open("xb") as handle:
                subprocess.run([*command, "exec", "-T", "db", "pg_dump", "-U", "radar", "-d", "radar", "-Fc"], cwd=ROOT,
                               stdout=handle, stderr=subprocess.PIPE, check=True)
            assert backup.stat().st_size > 0
            compose("exec", "-T", "db", "createdb", "-U", "radar", "radar_restore_smoke")
            with backup.open("rb") as handle:
                subprocess.run([*command, "exec", "-T", "db", "pg_restore", "-U", "radar", "-d", "radar_restore_smoke", "--no-owner", "--exit-on-error"],
                               cwd=ROOT, stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            assert compose("exec", "-T", "db", "psql", "-U", "radar", "-d", "radar_restore_smoke", "-Atc", "SELECT value FROM recovery_smoke WHERE id=1") == "recovery-ok"
            compose("restart", "db", "api", "dashboard")
            # Random host ports can be rebound on container restart; rediscover
            # the test endpoint instead of assuming the old mapping survived.
            api = "http://" + compose("port", "api", "8000")
            dashboard = "http://" + compose("port", "dashboard", "3000")
            deadline = time.monotonic() + 90
            last_failure = "unknown"
            while time.monotonic() < deadline:
                try:
                    if json.loads(get(api + "/health/ready"))["durable_store_ready"] and json.loads(get(dashboard + "/api/dashboard"))["core"]["status"] == "available":
                        break
                except (OSError, ValueError) as exc:
                    last_failure = type(exc).__name__
                time.sleep(1)
            else:
                raise RuntimeError("stack did not recover after restart (" + last_failure + ")")
            assert compose("exec", "-T", "db", "psql", "-U", "radar", "-d", "radar", "-Atc", "SELECT value FROM recovery_smoke WHERE id=1") == "recovery-ok"
            print("Isolated stack passed: bootstrap/auth/private runtime, Redis outage, nonempty backup/restore and restart persistence.", flush=True)
        finally:
            compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
