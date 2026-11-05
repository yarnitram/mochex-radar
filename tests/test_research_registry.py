import json
import sys
from pathlib import Path

import pytest

from mochex_radar.research_registry import engine_fingerprints, main, register_run, verify_run

FIXTURE = Path(__file__).parent / "fixtures" / "core-feature-validation.json"


def register(root):
    return register_run(root, FIXTURE, "synthetic", "Predeclared synthetic regression cohort")


def test_bundle_roundtrip_byte_preservation_and_deterministic_identity(tmp_path):
    first = register(tmp_path / "a")
    second = register(tmp_path / "b")
    assert first.name == second.name
    assert (first / "dataset.json").read_bytes() == FIXTURE.read_bytes()
    assert verify_run(first, replay=True)["replayed"] is True
    with pytest.raises(FileExistsError):
        register(tmp_path / "a")
    observed = register_run(tmp_path / "a", FIXTURE, "observed", "Caller declares observed; not independently verified")
    assert observed.name != first.name
    assert verify_run(observed)["data_kind_verification"] == "caller_declared"


@pytest.mark.parametrize("name", ["dataset.json", "report.json"])
def test_artifact_modification_detected(tmp_path, name):
    bundle = register(tmp_path)
    with (bundle / name).open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="digest"):
        verify_run(bundle)


def test_identity_and_manifest_metadata_detected(tmp_path):
    bundle = register(tmp_path)
    path = bundle / "manifest.json"
    original = json.loads(path.read_text())
    for key, value in (("selection_rationale", "changed rationale"),
                       ("signals_enabled", True), ("feature_version", "incorrect"),
                       ("registered_at", "yesterday")):
        path.write_text(json.dumps({**original, key: value}))
        with pytest.raises(ValueError):
            verify_run(bundle)


def test_source_drift_permits_integrity_check_but_blocks_replay(tmp_path, monkeypatch):
    bundle = register(tmp_path)
    changed = {**engine_fingerprints(), "market_features.py": "0" * 64}
    monkeypatch.setattr("mochex_radar.research_registry.engine_fingerprints", lambda: changed)
    assert verify_run(bundle)["status"] == "verified"
    with pytest.raises(ValueError, match="source mismatch"):
        verify_run(bundle, replay=True)


def test_partial_bundle_and_existing_directory_not_reused(tmp_path, monkeypatch):
    original = Path.open

    def fail_manifest(path, *args, **kwargs):
        if path.name == "manifest.json" and args and args[0] == "xb":
            raise OSError("simulated interrupted registration")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_manifest)
    with pytest.raises(OSError):
        register(tmp_path)
    bundle = next(tmp_path.iterdir())
    assert (bundle / "dataset.json").exists() and not (bundle / "manifest.json").exists()
    with pytest.raises(FileNotFoundError):
        verify_run(bundle)
    with pytest.raises(FileExistsError):
        register(tmp_path)


def test_invalid_metadata_and_size_do_not_create_bundle(tmp_path, monkeypatch):
    for kind, rationale in (("unknown", "reason"), ("synthetic", " "), ("synthetic", "x" * 2001)):
        with pytest.raises(ValueError):
            register_run(tmp_path / "new", FIXTURE, kind, rationale)
    assert not (tmp_path / "new").exists()
    monkeypatch.setattr("mochex_radar.research_registry.MAX_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        register(tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_cli_registration_and_replay(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["registry", "create", "--registry", str(tmp_path),
                                    "--input", str(FIXTURE), "--data-kind", "synthetic", "--rationale", "CLI regression"])
    main()
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    monkeypatch.setattr(sys, "argv", ["registry", "verify", "--bundle", str(tmp_path / run_id), "--replay"])
    main()
    assert json.loads(capsys.readouterr().out)["replayed"] is True


def test_symlink_artifact_is_rejected(tmp_path, monkeypatch):
    bundle = register(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == bundle / "dataset.json" or original(path))
    with pytest.raises(ValueError, match="symlink"):
        verify_run(bundle)


def test_unicode_rationale_roundtrips_with_manifest_bound(tmp_path):
    bundle = register_run(tmp_path, FIXTURE, "synthetic", "\U0001f4c8" * 2000)
    assert verify_run(bundle, replay=True)["status"] == "verified"
