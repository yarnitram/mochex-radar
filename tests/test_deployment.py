import json
import os
from pathlib import Path

import pytest

from scripts.deployment import REPO, Runtime, private_environment, release_transaction, successful_ci, validate_paths


def private_env(path):
    path.write_text("POSTGRES_PASSWORD=" + "p" * 32 + "\nRADAR_API_TOKEN=" + "t" * 40 + "\nDATABASE_URL=postgresql://radar:" + "p" * 32 + "@db:5432/radar\n")
    path.chmod(0o600)
    return path


def test_private_env_requires_matching_internal_database_and_explicit_credentials(tmp_path):
    path = private_env(tmp_path / "private.env")
    assert len(private_environment(path)["RADAR_API_TOKEN"]) == 40
    path.write_text(path.read_text().replace("@db:", "@external:"))
    with pytest.raises(ValueError, match="internal"):
        private_environment(path)
    path.write_text("POSTGRES_PASSWORD=short\nRADAR_API_TOKEN=short\n")
    with pytest.raises(ValueError, match="generated"):
        private_environment(path)


def test_alert_profile_is_disabled_by_default_and_requires_valid_opt_in(tmp_path):
    path = private_env(tmp_path / "private.env")
    runtime = Runtime(tmp_path / "source", tmp_path / "state", path)
    assert runtime.environment["COMPOSE_PROFILES"] == ""
    assert runtime.environment["TELEGRAM_SEND_ENABLED"] == "false"
    path.write_text(path.read_text() + "RADAR_ALERTS_ENABLED=true\nTELEGRAM_SEND_ENABLED=true\nTELEGRAM_BOT_TOKEN=invalid token\nTELEGRAM_CHAT_ID=8720642900\n")
    with pytest.raises(ValueError, match="valid Telegram"):
        private_environment(path)
    path.write_text(path.read_text().replace("invalid token", "123456789:AAExampleToken_DoNotUse123"))
    enabled = Runtime(tmp_path / "source", tmp_path / "state2", path)
    assert enabled.environment["COMPOSE_PROFILES"] == "alerts"
    assert enabled.environment["TELEGRAM_SEND_ENABLED"] == "true"


def test_alert_profile_rejects_missing_credentials_when_enabled(tmp_path):
    path = private_env(tmp_path / "private.env")
    path.write_text(path.read_text() + "RADAR_ALERTS_ENABLED=true\nTELEGRAM_SEND_ENABLED=true\n")
    with pytest.raises(ValueError, match="valid Telegram"):
        private_environment(path)


def test_alert_profile_is_added_to_runtime_start_services(tmp_path):
    path = private_env(tmp_path / "private.env")
    path.write_text(path.read_text() + "RADAR_ALERTS_ENABLED=true\nTELEGRAM_SEND_ENABLED=true\nTELEGRAM_BOT_TOKEN=123456789:AAExampleToken_DoNotUse123\nTELEGRAM_CHAT_ID=8720642900\n")
    runtime = Runtime(tmp_path / "source", tmp_path / "state", path)
    calls = []
    runtime.compose = lambda sha, *args, **kwargs: calls.append(args) or ""
    runtime.start("a" * 40)
    assert calls[-1][-1] == "alert-worker"


def test_paths_refuse_secrets_state_inside_source_and_unmanaged_directories(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    env = private_env(tmp_path / "private.env")
    state = tmp_path / "state"
    assert validate_paths(source, state, env) == (source.resolve(), state.resolve(), env.resolve())
    for target in (source, source / "work", tmp_path):
        with pytest.raises(ValueError): validate_paths(source, target, env)
    state.mkdir(mode=0o700); (state / "unrelated-file").write_text("preserve")
    with pytest.raises(ValueError, match="unmanaged"):
        validate_paths(source, state, env)
    (state / ".mochex-state").write_text(REPO)
    assert validate_paths(source, state, env)[1] == state.resolve()


def test_only_completed_success_for_exact_full_sha_is_accepted():
    sha = "a" * 40
    assert successful_ci([{"headSha": sha, "status": "completed", "conclusion": "success"}], sha)
    assert not successful_ci([{"headSha": "b" * 40, "status": "completed", "conclusion": "success"}], sha)
    assert not successful_ci([{"headSha": sha, "status": "in_progress", "conclusion": None}], sha)
    with pytest.raises(ValueError): successful_ci([], "main")


def test_release_build_backup_health_and_commit_order():
    events = []
    def mark(name): return lambda *args: events.append((name, *args))
    release_transaction("new", "old", mark("build"), mark("backup"), mark("start"), mark("verify"), mark("persist"))
    assert events == [("build", "new"), ("backup", "old"), ("start", "new"), ("verify", "new"), ("persist", "new", "old")]


@pytest.mark.parametrize("failure", ["start", "verify", "persist"])
def test_failed_candidate_recovers_previous_without_committing_new_state(failure):
    events = []
    def callback(name):
        def action(*args):
            events.append((name, *args))
            if name == failure and args[0] == "new": raise RuntimeError("candidate failure")
        return action
    with pytest.raises(RuntimeError, match="previous runtime recovered"):
        release_transaction("new", "old", callback("build"), callback("backup"), callback("start"), callback("verify"), callback("persist"))
    assert events[-2:] == [("start", "old"), ("verify", "old")]


def test_build_failure_does_not_touch_existing_runtime():
    def forbidden(*args): pytest.fail("runtime should not be touched")
    def failed(*args): raise RuntimeError("build failed")
    with pytest.raises(RuntimeError, match="build failed"):
        release_transaction("new", "old", failed, forbidden, forbidden, forbidden, forbidden)


def test_real_backup_function_creates_private_dump_research_archive_and_hash_manifest(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    runtime = Runtime(source, tmp_path / "state", private_env(tmp_path / "private.env"))
    runtime.state.mkdir(mode=0o700); research = runtime.state / "research"; research.mkdir()
    (research / "evidence.json").write_text('{"synthetic":true}')
    def compose(sha, *args, stdout=None):
        if args[0] == "ps": return "db\napi\ndashboard\nredis\ncollector\nstreamer"
        assert "pg_dump" in args
        stdout.write(b"synthetic-dump-stream")
        return ""
    runtime.compose = compose
    runtime.backup("a" * 40)
    backup = next((runtime.state / "backups").iterdir())
    manifest = json.loads((backup / "manifest.json").read_text())
    assert manifest["source_sha"] == "a" * 40
    assert len(manifest["database_sha256"]) == 64 and (backup / "research.tar.gz").stat().st_size > 0


@pytest.mark.skipif(os.name != "posix", reason="guest deployment lock uses Linux flock")
def test_update_never_builds_or_starts_unverified_candidate(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    class Controlled(Runtime):
        def preflight(self): return {"status": "test_preflight"}
        def git(self, *args, root=None):
            return "a" * 40 if args[0] == "rev-parse" else ""
        def run(self, command, **kwargs): return "[]"
        def build(self, sha): pytest.fail("unverified commit reached build")
    runtime = Controlled(source, tmp_path / "state", private_env(tmp_path / "private.env"))
    assert runtime.update()["status"] == "waiting_for_successful_ci"
    assert not (runtime.state / "current.json").exists()
