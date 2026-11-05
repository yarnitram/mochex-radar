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
        env_file = Path(temporary) / "private.env"
        with env_file.open("x", encoding="utf-8") as handle:
            handle.write(f"POSTGRES_PASSWORD={password}\nDATABASE_URL=postgresql://radar:{password}@db:5432/radar\nRADAR_API_TOKEN={token}\nRADAR_API_PORT=0\nRADAR_DASHBOARD_PORT=0\nRADAR_APP_IMAGE={project}-api\nRADAR_DASHBOARD_IMAGE={project}-dashboard\n")
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
            assert all(snapshot[name]["status"] == "available" for name in ("btc", "collector", "scans", "outbox", "catalog", "profilePolls", "authorities"))
            assert compose("exec", "-T", "api", "id", "-u") == "10001"
            assert compose("exec", "-T", "dashboard", "id", "-u") != "0"
            assert compose("exec", "-T", "api", "python", "-c", "import os,stat;print(bool(os.statvfs('/app').f_flag & stat.ST_RDONLY))") == "True"
            try:
                compose("exec", "-T", "api", "python", "-c", "open('/app/write-test','w').write('x')")
                raise AssertionError("API root filesystem was writable")
            except RuntimeError:
                pass
            compose("stop", "redis")
            assert json.loads(get(api + "/health/ready"))["status"] == "degraded"
            assert len(json.loads(get(api + "/api/v1/dashboard/core", auth=True))["markets"]) == 7
            compose("start", "redis")
            print("Isolated stack passed: bootstrap, auth, dashboard forwarding, nonroot/read-only runtime, Redis outage.", flush=True)
        finally:
            compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
