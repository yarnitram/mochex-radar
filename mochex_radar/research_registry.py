"""Private local research bundles with hash verification and explicit replay."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mochex_radar.feature_validation import MAX_BYTES, _timestamp, report_from_bytes

VERSION = "research-run-v1"
ENGINE_FILES = ("feature_validation.py", "market_features.py", "markets.py", "futures_feed.py")
MAX_REPORT_BYTES = 20_000_000
MAX_MANIFEST_BYTES = 32000


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink():
        raise ValueError("symlink artifacts are unsupported")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("artifact size limit exceeded")
    return raw


def engine_fingerprints() -> dict[str, str]:
    # Normalize checkout line endings so Windows/Linux copies of the same source match.
    root = Path(__file__).parent
    return {name: _hash(_read(root / name, 1_000_000).replace(b"\r\n", b"\n")) for name in ENGINE_FILES}


def _identity(manifest: dict) -> dict:
    names = ("registry_version", "dataset_sha256", "report_sha256", "engine_fingerprints", "data_kind", "selection_rationale")
    identity = {name: manifest[name] for name in names}
    if (identity["registry_version"] != VERSION or identity["data_kind"] not in ("synthetic", "observed")
            or not isinstance(identity["selection_rationale"], str)
            or not 1 <= len(identity["selection_rationale"].strip()) <= 2000):
        raise ValueError("invalid registry metadata")
    fingerprints = identity["engine_fingerprints"]
    if not isinstance(fingerprints, dict) or set(fingerprints) != set(ENGINE_FILES):
        raise ValueError("invalid engine fingerprints")
    for digest in [identity["dataset_sha256"], identity["report_sha256"], *fingerprints.values()]:
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("invalid digest")
    return identity


def register_run(registry: Path, dataset: Path, data_kind: str, selection_rationale: str) -> Path:
    raw = _read(dataset, MAX_BYTES)
    report = report_from_bytes(raw)
    encoded = _json(report)
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("report size limit exceeded")
    identity = _identity({"registry_version": VERSION, "dataset_sha256": _hash(raw), "report_sha256": _hash(encoded),
                          "engine_fingerprints": engine_fingerprints(), "data_kind": data_kind,
                          "selection_rationale": selection_rationale})
    run_id = _hash(_json(identity))
    registry.mkdir(parents=True, exist_ok=True)
    destination = registry / run_id
    destination.mkdir()  # Exclusive; incomplete and completed bundles are both preserved.
    for name, value in (("dataset.json", raw), ("report.json", encoded)):
        with (destination / name).open("xb") as handle:
            handle.write(value)
    manifest = {**identity, "run_id": run_id, "registered_at": datetime.now(timezone.utc).isoformat(),
                "report_version": report["report_version"], "feature_version": report["feature_version"],
                "dataset_config_sha256": report["dataset_config_sha256"], "research_only": True,
                "signals_enabled": False, "data_kind_verification": "caller_declared"}
    with (destination / "manifest.json").open("xb") as handle:
        handle.write(_json(manifest))
    return destination


def verify_run(bundle: Path, replay: bool = False) -> dict:
    if bundle.is_symlink() or not re.fullmatch("[0-9a-f]{64}", bundle.name):
        raise ValueError("invalid bundle directory")
    manifest = json.loads(_read(bundle / "manifest.json", MAX_MANIFEST_BYTES))
    if not isinstance(manifest, dict):
        raise ValueError("invalid manifest")
    _timestamp(manifest.get("registered_at"))
    identity = _identity(manifest)
    if manifest.get("run_id") != bundle.name or _hash(_json(identity)) != bundle.name:
        raise ValueError("run identity mismatch")
    raw = _read(bundle / "dataset.json", MAX_BYTES)
    encoded = _read(bundle / "report.json", MAX_REPORT_BYTES)
    if _hash(raw) != identity["dataset_sha256"] or _hash(encoded) != identity["report_sha256"]:
        raise ValueError("artifact digest mismatch")
    report = json.loads(encoded)
    for name in ("report_version", "feature_version", "dataset_config_sha256"):
        if report[name] != manifest.get(name):
            raise ValueError("manifest report metadata mismatch")
    if (manifest.get("research_only") is not True or manifest.get("signals_enabled") is not False
            or report.get("research_only") is not True or report.get("signals_enabled") is not False
            or report.get("execution_simulated") is not False
            or manifest.get("data_kind_verification") != "caller_declared"):
        raise ValueError("invalid research guardrails")
    if replay:
        if identity["engine_fingerprints"] != engine_fingerprints():
            raise ValueError("engine source mismatch; replay requires matching source")
        if _json(report_from_bytes(raw)) != encoded:
            raise ValueError("replayed report mismatch")
    return {"status": "verified", "run_id": bundle.name, "replayed": replay,
            "data_kind": identity["data_kind"], "data_kind_verification": "caller_declared"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create")
    create.add_argument("--registry", type=Path, required=True)
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--data-kind", choices=("synthetic", "observed"), required=True)
    create.add_argument("--rationale", required=True)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if args.command == "create":
        destination = register_run(args.registry, args.input, args.data_kind, args.rationale)
        print(json.dumps({"status": "registered", "run_id": destination.name}))
    else:
        print(json.dumps(verify_run(args.bundle, args.replay)))


if __name__ == "__main__":
    main()
