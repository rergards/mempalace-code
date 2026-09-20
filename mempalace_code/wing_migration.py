#!/usr/bin/env python3
"""Installed copy-contained wing merge qualification operator.

The operator coordinates the existing LanceDB, SQLite, project-marker, and tiny-hash
owners without reconstructing records. Every mutating action requires a sealed receipt
created from an explicit disposable fixture or owner-authorized full-copy inventory.
"""

from __future__ import annotations

import argparse
import base64
import copy
import gc
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import sysconfig
import tempfile
import time
import venv
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.dont_write_bytecode = True

if TYPE_CHECKING:
    from collections.abc import Iterator

RECEIPT_VERSION = 17
INVENTORY_VERSION = 1
TABLE_NAME = "mempalace_drawers"
MAX_RECEIPT_BYTES = 256 * 1024 * 1024
PROCESS_OBSERVATION_TIMEOUT_SECONDS = 60
LANCE_SCAN_BATCH_SIZE = 256
LANCE_STATE_FORMAT = "row_witness_sha256_v1"
LANCE_EXPECTED_FORMAT = "wing_delta_v1"
SYNTHETIC_RUNTIME_MINE_TIMEOUT_SECONDS = 90
FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS = 15 * 60
MAX_RETAINED_SNAPSHOT_ROOTS = 1
UNRELATED_HASH_WORKERS = 16
LANCE_WITNESS_FIELDS = (
    "id",
    "wing",
    "source_file",
    "source_hash",
    "chunk_index",
    "ingest_mode",
    "chunker_strategy",
    "type",
)
HASH_RE = re.compile(r"^[0-9a-f]{32}$")
FIXTURE_MARKER = ".wing-migration-fixture.json"
MODEL_CACHE_RELATIVE = Path("mempalace-fastembed") / "all-MiniLM-L6-v2-v1"
RUNNER_PATH = Path(__file__).absolute()
STATE_KEYS = ("lance_rows", "lance_schema", "tiny_hashes", "marker", "configuration", "kg")
FULL_COPY_SCOPE = "isolated_full_copy_only"
FULL_COPY_PROCESS_AUTHORITY = "acquire fixture lock and stop only fixture-owned subprocesses"
FULL_COPY_RETENTION_RULE = "retain until verified recovery or owner disposition"
LIVE_SCOPE = "single_host_live_wing_merge"
LIVE_MAINTENANCE_NAME = "live-wing-migration.json"
LEGACY_FILE_CHUNKER_STRATEGIES = frozenset(
    {
        "dotnet_project_xml_v1",
        "regex_structural_v1",
        "treesitter_adaptive_v1",
        "treesitter_v1",
    }
)


class MigrationError(RuntimeError):
    """A fail-closed migration predicate."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class InjectedStop(MigrationError):
    """Synthetic interruption after a named durable boundary."""


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if hasattr(value, "as_py"):
        return value.as_py()
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError("duplicate_json_key", f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except MigrationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError("invalid_json", f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError("invalid_json", f"{path} must contain a JSON object")
    return value


def _serialized_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_json(
    path: Path,
    value: dict[str, Any],
    *,
    replace: bool = True,
    max_bytes: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = _serialized_json(value)
    if max_bytes is not None and len(serialized) > max_bytes:
        raise MigrationError("receipt_too_large", "sealed receipt exceeds the size limit")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
    except FileExistsError as exc:
        raise MigrationError("evidence_exists", "refusing to replace retained evidence") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _real(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return _lexical_absolute(str(candidate), "invalid_path")


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _overlaps(first: Path, second: Path) -> bool:
    return _inside(first, second) or _inside(second, first)


def _reject_symlink_chain(path: Path, root: Path | None = None) -> None:
    target = path
    trusted_root = root if root is not None else Path(path.anchor)
    if not trusted_root.is_absolute() or not _inside(target, trusted_root):
        raise MigrationError("fixture_path_invalid", "path is outside its trusted root")
    current = trusted_root
    components = target.relative_to(trusted_root).parts
    for component in (".", *components):
        if component == ".":
            current = trusted_root
        else:
            current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise MigrationError("fixture_path_unavailable", f"cannot inspect: {current}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError("fixture_symlink", f"symlink is forbidden: {current}")


def _reject_symlink_tree(root: Path) -> None:
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MigrationError("fixture_path_unavailable", f"cannot inspect: {current}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError("fixture_symlink", f"symlink is forbidden: {current}")
        if not stat.S_ISDIR(metadata.st_mode):
            continue
        try:
            entries = list(current.iterdir())
        except OSError as exc:
            raise MigrationError("fixture_path_unavailable", f"cannot inspect: {current}") from exc
        for path in entries:
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise MigrationError("fixture_path_unavailable", f"cannot inspect: {path}") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise MigrationError("fixture_symlink", f"symlink is forbidden: {path}")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)


def _reject_external_symlink_targets(root: Path) -> None:
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise MigrationError("fixture_path_unavailable", f"cannot inspect: {root}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        return
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            path = current_path / name
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise MigrationError("fixture_path_unavailable", f"cannot inspect: {path}") from exc
            if stat.S_ISLNK(metadata.st_mode):
                target = Path(os.path.abspath(str(path.parent / os.readlink(path))))
                if not _inside(target, root):
                    raise MigrationError("model_cache_link_escape", str(path))


def _path_identity(path: Path) -> dict[str, Any]:
    stat_result = path.lstat()
    if stat.S_ISLNK(stat_result.st_mode):
        raise MigrationError("fixture_symlink", f"symlink is forbidden: {path}")
    return {
        "path": str(path),
        "device": stat_result.st_dev,
        "inode": stat_result.st_ino,
    }


def _assert_regular_private(path: Path) -> None:
    stat_result = path.lstat()
    if not stat.S_ISREG(stat_result.st_mode):
        raise MigrationError("unsafe_private_file", f"not a regular private file: {path}")
    if stat_result.st_nlink != 1:
        raise MigrationError("hardlink_forbidden", f"hard-linked private file: {path}")


def _assert_private_tree(root: Path) -> None:
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            path = current_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise MigrationError("fixture_symlink", f"symlink is forbidden: {path}")
            if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
                raise MigrationError("hardlink_forbidden", f"hard-linked private file: {path}")


def _identity_value(path: Path) -> dict[str, int]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise MigrationError("fixture_symlink", f"symlink is forbidden: {path}")
    return {"device": metadata.st_dev, "inode": metadata.st_ino}


def _full_copy_requested(raw: dict[str, Any]) -> bool:
    return any(
        key in raw
        for key in ("authority", "copy_verification", "runtime_authority", "logical_source_root")
    )


def _private_mode_is_0600(path: Path) -> bool:
    return stat.S_IMODE(path.lstat().st_mode) == 0o600


def _copied_target_state(path: Path) -> dict[str, Any]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise MigrationError("fixture_symlink", f"symlink is forbidden: {path}")
    return {
        "path": str(path),
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
    }


def _lexical_absolute(value: Any, code: str) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise MigrationError(code, "an absolute lexical path is required")
    separators = {os.sep}
    if os.altsep:
        separators.add(os.altsep)
    components = [value]
    for separator in separators:
        components = [part for component in components for part in component.split(separator)]
    if any(component in {".", ".."} for component in components):
        raise MigrationError(code, "dot components are forbidden in a lexical path")
    normalized_components = [component for component in components if component]
    return Path(os.sep, *normalized_components)


def _copy_preimage(inventory: dict[str, Any]) -> dict[str, Any]:
    kg_state: list[dict[str, Any]] = []
    for value in inventory["kg_candidates"]:
        path = Path(value)
        kg_state.append(_sqlite_full_state(path))
    return {
        "state": _state_without_candidate_paths(_capture(inventory)),
        "lance_files": _tree_hashes(Path(inventory["palace"]) / "lance"),
        "kg_state": kg_state,
        "unrelated_files": _unrelated_file_hashes(inventory),
    }


def _copy_preimage_with_proved_lance(
    receipt: dict[str, Any], lance_files: dict[str, str]
) -> dict[str, Any]:
    """Observe non-Lance state while reusing snapshot-proved Lance witnesses."""
    inventory = receipt["inventory"]
    state = _capture_non_lance(inventory)
    state.update(
        {
            "lance_rows": receipt["pre"]["lance_rows"],
            "lance_schema": receipt["pre"]["lance_schema"],
        }
    )
    state = _state_without_candidate_paths(state)
    kg_state: list[dict[str, Any]] = []
    for value in inventory["kg_candidates"]:
        kg_state.append(_sqlite_full_state(Path(value)))
    return {
        "state": state,
        "lance_files": lance_files,
        "kg_state": kg_state,
        "unrelated_files": _unrelated_file_hashes(inventory),
    }


def _compact_copy_preimage(preimage: dict[str, Any]) -> dict[str, Any]:
    state = dict(preimage["state"])
    state["lance_rows"] = [_lance_row_witness(row) for row in state["lance_rows"]]
    return {**preimage, "state": state}


def _full_copy_runtime_identity(raw: dict[str, Any]) -> dict[str, Any]:
    authority = raw["runtime_authority"]
    runner_hash = authority.get("runner_sha256")
    if not isinstance(runner_hash, str) or runner_hash != _file_digest(RUNNER_PATH):
        raise MigrationError("runtime_runner_hash_drift", "runner differs from owner authority")

    source_commit = authority.get("qualification_source_commit")
    pyproject_hash = authority.get("pyproject_sha256")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", source_commit):
        raise MigrationError("runtime_authority_invalid", "source commit is invalid")
    if not isinstance(pyproject_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", pyproject_hash):
        raise MigrationError("runtime_authority_invalid", "pyproject hash is invalid")
    source_pyproject = subprocess.run(
        ["git", "show", f"{source_commit}:pyproject.toml"],
        cwd=RUNNER_PATH.parent.parent,
        capture_output=True,
        check=False,
    )
    if (
        source_pyproject.returncode != 0
        or hashlib.sha256(source_pyproject.stdout).hexdigest() != pyproject_hash
    ):
        raise MigrationError("runtime_source_drift", "authorized source commit is unavailable")

    interpreter_value = authority.get("qualification_interpreter")
    original_interpreter = authority.get("original_interpreter")
    expected_version = authority.get("original_version")
    if not all(
        isinstance(value, str) and value
        for value in (interpreter_value, original_interpreter, expected_version)
    ):
        raise MigrationError("runtime_authority_invalid", "runtime path or version is invalid")
    if not Path(interpreter_value).is_absolute():
        raise MigrationError(
            "runtime_authority_invalid", "qualification interpreter is not absolute"
        )
    interpreter = _real(interpreter_value)
    _reject_symlink_chain(interpreter)
    if not interpreter.is_file():
        raise MigrationError(
            "runtime_authority_invalid", "qualification interpreter is unavailable"
        )
    if not Path(original_interpreter).is_absolute():
        raise MigrationError("runtime_authority_invalid", "original interpreter must be absolute")

    identity = {
        "interpreter": str(interpreter),
        "runtime_prefix": authority.get("qualification_runtime_prefix"),
        "module_origin": authority.get("qualification_module_origin"),
        "distribution_origin": authority.get("qualification_distribution_origin"),
        "distribution_version": expected_version,
    }
    identity_paths = [
        identity[key] for key in ("runtime_prefix", "module_origin", "distribution_origin")
    ]
    if any(not isinstance(value, str) or not value for value in identity_paths):
        raise MigrationError("runtime_revalidation_failed", "runtime identity paths are invalid")
    prefix = _real(identity_paths[0])
    module_origin = _real(identity_paths[1])
    distribution_origin = _real(identity_paths[2])
    for path in (prefix, module_origin, distribution_origin):
        _reject_symlink_chain(path)
    if not _inside(module_origin, prefix) or not _inside(distribution_origin, prefix):
        raise MigrationError("runtime_provenance_invalid", "qualification package is editable")

    expected_package_hashes = authority.get("qualification_package_hashes")
    expected_distribution_hashes = authority.get("qualification_distribution_hashes")
    if not isinstance(expected_package_hashes, dict) or not isinstance(
        expected_distribution_hashes, dict
    ):
        raise MigrationError("runtime_authority_invalid", "installed hashes are required")
    _reject_symlink_tree(module_origin.parent)
    _reject_symlink_tree(distribution_origin)
    if _hash_regular_tree(module_origin.parent) != expected_package_hashes:
        raise MigrationError("runtime_package_hash_drift", "qualification package differs")
    if _hash_regular_tree(distribution_origin) != expected_distribution_hashes:
        raise MigrationError("runtime_package_hash_drift", "qualification distribution differs")
    model_cache_value = authority.get("model_cache_home")
    model_cache_seal = authority.get("model_cache_seal")
    if not isinstance(model_cache_value, str) or not isinstance(model_cache_seal, dict):
        raise MigrationError("runtime_authority_invalid", "model cache authority is required")
    model_cache_home = _real(model_cache_value)
    if _seal_model_cache_files(model_cache_home) != model_cache_seal:
        raise MigrationError("model_cache_source_drift", "authorized model cache differs")
    identity.update(
        {
            "isolated_non_editable": True,
            "package_hashes": expected_package_hashes,
            "distribution_hashes": expected_distribution_hashes,
            "model_cache_home": str(model_cache_home),
            "model_cache_seal": model_cache_seal,
            "model_cache_source_home": str(model_cache_home),
            "model_cache_source_seal": model_cache_seal,
            "qualification_source_commit": source_commit,
            "runner_sha256": runner_hash,
        }
    )
    return identity


def _validate_full_copy_authority(
    raw: dict[str, Any], paths: dict[str, Path], kg_paths: list[Path]
) -> dict[str, Any]:
    authority = raw.get("authority")
    required_authority = {
        "fixture_process_authority",
        "live_mutation",
        "original_host",
        "original_paths_excluded_from_mutation",
        "owner_approval",
        "qualification_host",
        "retention_rule",
        "scope",
        "watcher_restart",
    }
    if not isinstance(authority, dict) or set(authority) != required_authority:
        raise MigrationError("full_copy_authority_invalid", "copy-only owner authority is required")
    if (
        authority["scope"] != FULL_COPY_SCOPE
        or authority["live_mutation"] is not False
        or authority["watcher_restart"] is not False
        or authority["fixture_process_authority"] != FULL_COPY_PROCESS_AUTHORITY
        or authority["retention_rule"] != FULL_COPY_RETENTION_RULE
    ):
        raise MigrationError("full_copy_authority_invalid", "copy-only authority values differ")
    for key in ("owner_approval", "original_host", "qualification_host"):
        if not isinstance(authority[key], str) or not authority[key]:
            raise MigrationError("full_copy_authority_invalid", f"{key} is required")
    if authority["qualification_host"] != socket.gethostname():
        raise MigrationError("qualification_host_mismatch", "current host differs from authority")
    if authority["original_host"] == authority["qualification_host"]:
        raise MigrationError("full_copy_authority_invalid", "qualification host is not isolated")
    logical = raw.get("logical_source_root")
    logical_path = _lexical_absolute(logical, "logical_source_root_invalid")
    if logical_path == paths["project_root"]:
        raise MigrationError(
            "logical_source_root_invalid", "logical and physical roots must differ"
        )
    exclusions = authority["original_paths_excluded_from_mutation"]
    if (
        not isinstance(exclusions, list)
        or not exclusions
        or logical not in exclusions
        or any(
            not isinstance(value, str)
            or not value
            or not Path(value).is_absolute()
            or any(part in {".", ".."} for part in value.split(os.sep))
            for value in exclusions
        )
    ):
        raise MigrationError(
            "full_copy_authority_invalid", "original path exclusions are incomplete"
        )
    batch_size = raw.get("lance_batch_size")
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
        raise MigrationError(
            "lance_batch_size_invalid", "a positive integer batch size is required"
        )
    verification = raw.get("copy_verification")
    required_verification = {
        "checksum_dry_run_differences",
        "copied_targets",
        "method",
        "qualification_device",
        "source_filesystem_id",
        "source_host",
        "source_preimage_sha256",
        "source_device",
        "source_snapshot_id",
        "source_snapshot_root",
    }
    if not isinstance(verification, dict) or set(verification) != required_verification:
        raise MigrationError("copy_verification_invalid", "complete copy verification is required")
    source_device = verification["source_device"]
    qualification_device = verification["qualification_device"]
    if (
        not isinstance(source_device, int)
        or isinstance(source_device, bool)
        or not isinstance(qualification_device, int)
        or isinstance(qualification_device, bool)
        or verification["checksum_dry_run_differences"] != 0
        or not isinstance(verification["method"], str)
        or not verification["method"]
        or not isinstance(verification["source_snapshot_root"], str)
        or not Path(verification["source_snapshot_root"]).is_absolute()
        or not isinstance(verification["source_filesystem_id"], str)
        or not verification["source_filesystem_id"]
        or not isinstance(verification["source_snapshot_id"], str)
        or not verification["source_snapshot_id"]
        or verification["source_host"] != authority["original_host"]
        or not isinstance(verification["source_preimage_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", verification["source_preimage_sha256"])
    ):
        raise MigrationError("copy_verification_invalid", "copy proof is incomplete")
    targets = verification["copied_targets"]
    expected_targets = [
        _copied_target_state(paths["palace"]),
        _copied_target_state(paths["project_root"]),
    ]
    if not isinstance(targets, list) or targets != expected_targets:
        raise MigrationError("copy_identity_drift", "copied target inventory differs")
    if any(target["device"] != qualification_device for target in expected_targets):
        raise MigrationError("copy_identity_drift", "copied target device differs")
    if any(path.is_symlink() or not path.is_file() for path in kg_paths):
        raise MigrationError("copy_verification_invalid", "both KG candidates must exist")
    sealed_identities = {
        "palace": _identity_value(paths["palace"]),
        "project_root": _identity_value(paths["project_root"]),
    }
    if any(
        identity["device"] != qualification_device
        for identity in [
            sealed_identities["palace"],
            sealed_identities["project_root"],
            *[_identity_value(path) for path in kg_paths],
        ]
    ):
        raise MigrationError("copy_identity_drift", "a copied store is on the source device")

    copied_inventory = dict(raw)
    copied_inventory.update({key: str(value) for key, value in paths.items()})
    copied_inventory["kg_candidates"] = [str(value) for value in kg_paths]
    copied_preimage = _copy_preimage(copied_inventory)
    if _digest(copied_preimage) != verification["source_preimage_sha256"]:
        raise MigrationError("copy_preimage_mismatch", "copied state differs from owner preimage")
    compact_copy_preimage = _compact_copy_preimage(copied_preimage)

    runtime = raw.get("runtime_authority")
    required_runtime = {
        "model_cache_home",
        "model_cache_seal",
        "original_interpreter",
        "original_version",
        "pyproject_sha256",
        "qualification_distribution_hashes",
        "qualification_distribution_origin",
        "qualification_interpreter",
        "qualification_module_origin",
        "qualification_package_hashes",
        "qualification_runtime_prefix",
        "qualification_source_commit",
        "runner_sha256",
    }
    if not isinstance(runtime, dict) or set(runtime) != required_runtime:
        raise MigrationError("runtime_authority_invalid", "exact runtime authority is incomplete")
    identity = _full_copy_runtime_identity(raw)
    identity["copy_identities"] = sealed_identities
    identity["copy_preimage_sha256"] = _digest(compact_copy_preimage)
    identity["source_preimage_sha256"] = verification["source_preimage_sha256"]
    return identity


def _validate_inventory(raw: dict[str, Any], inventory_path: Path) -> dict[str, Any]:
    required = {
        "version",
        "fixture_id",
        "disposable",
        "fixture_root",
        "palace",
        "project_root",
        "marker",
        "tiny_hashes",
        "kg_candidates",
        "lock",
        "snapshot_root",
        "runtime_root",
        "evidence_root",
        "configuration",
        "source_wing",
        "destination_wing",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise MigrationError("inventory_missing_fields", ", ".join(missing))
    full_copy = _full_copy_requested(raw)
    if raw["version"] != INVENTORY_VERSION or raw["disposable"] is not True:
        raise MigrationError("fixture_authority_required", "inventory is not disposable version 1")
    source = raw["source_wing"]
    destination = raw["destination_wing"]
    if (
        not isinstance(source, str)
        or not source
        or not isinstance(destination, str)
        or not destination
    ):
        raise MigrationError(
            "invalid_wing", "source and destination wings must be non-empty strings"
        )
    if source == destination:
        raise MigrationError("source_equals_destination", "source wing already equals destination")

    root = _real(raw["fixture_root"])
    _reject_symlink_chain(root, None if full_copy else root)
    if not root.is_dir():
        raise MigrationError("fixture_root_invalid", f"fixture root is unavailable: {root}")
    marker = root / FIXTURE_MARKER
    _reject_symlink_chain(marker, root)
    try:
        _assert_regular_private(marker)
    except FileNotFoundError:
        pass
    marker_data = _load_json(marker)
    if marker_data != {"disposable": True, "fixture_id": raw["fixture_id"]}:
        raise MigrationError("fixture_identity_mismatch", f"invalid fixture marker: {marker}")
    _assert_regular_private(marker)

    paths: dict[str, Path] = {}
    for field in (
        "palace",
        "project_root",
        "marker",
        "tiny_hashes",
        "lock",
        "snapshot_root",
        "runtime_root",
        "evidence_root",
        "configuration",
    ):
        value = raw[field]
        if not isinstance(value, str) or not value:
            raise MigrationError("invalid_inventory_path", f"{field} must be a path string")
        path = _real(value)
        if not _inside(path, root):
            raise MigrationError("outside_fixture", f"{field} escapes fixture root: {path}")
        _reject_symlink_chain(path, None if full_copy else root)
        paths[field] = path
    if not full_copy and not _inside(inventory_path, root):
        raise MigrationError("outside_fixture", "inventory must be inside its fixture root")

    retained_snapshot_roots: dict[Path, Path] = {}
    if full_copy:
        retained_values = raw.get("retained_snapshot_roots")
        if not isinstance(retained_values, dict) or any(
            not isinstance(root_value, str)
            or not root_value
            or not isinstance(receipt_value, str)
            or not receipt_value
            for root_value, receipt_value in retained_values.items()
        ):
            raise MigrationError(
                "retained_snapshot_roots_invalid",
                "full-copy inventory requires a retained snapshot receipt map",
            )
        if len(retained_values) > MAX_RETAINED_SNAPSHOT_ROOTS:
            raise MigrationError(
                "retained_snapshot_limit_exceeded",
                "full-copy inventory may retain at most one prior snapshot",
            )
        for root_value, receipt_value in retained_values.items():
            path = _lexical_absolute(root_value, "retained_snapshot_root_invalid")
            if not _inside(path, root):
                raise MigrationError(
                    "outside_fixture", "retained snapshot root escapes fixture root"
                )
            _reject_symlink_chain(path)
            if not path.is_dir():
                raise MigrationError(
                    "retained_snapshot_root_invalid", "retained snapshot root is unavailable"
                )
            _assert_private_tree(path)
            manifest_path = path / "manifest.json"
            _reject_symlink_chain(manifest_path)
            try:
                _assert_regular_private(manifest_path)
                manifest = _load_json(manifest_path)
            except (FileNotFoundError, OSError, ValueError, TypeError, MigrationError) as exc:
                raise MigrationError(
                    "retained_snapshot_unproved", "retained snapshot manifest is unavailable"
                ) from exc
            receipt_path = _lexical_absolute(receipt_value, "retained_snapshot_receipt_invalid")
            if not _inside(receipt_path, paths["evidence_root"]):
                raise MigrationError(
                    "retained_snapshot_receipt_invalid",
                    "retained snapshot receipt is outside the evidence root",
                )
            _reject_symlink_chain(receipt_path)
            try:
                _assert_regular_private(receipt_path)
                if not _private_mode_is_0600(receipt_path):
                    raise MigrationError(
                        "retained_snapshot_receipt_invalid",
                        "retained snapshot receipt mode must be 0600",
                    )
                if receipt_path.stat().st_size > MAX_RECEIPT_BYTES:
                    raise MigrationError(
                        "retained_snapshot_receipt_invalid",
                        "retained snapshot receipt exceeds the size limit",
                    )
                retained_receipt = _load_json(receipt_path)
            except (FileNotFoundError, OSError, ValueError, TypeError, MigrationError) as exc:
                raise MigrationError(
                    "retained_snapshot_receipt_invalid",
                    "retained snapshot receipt is unavailable",
                ) from exc
            seal = retained_receipt.pop("seal", None)
            version = retained_receipt.get("version")
            sealed_snapshot = retained_receipt.get("snapshot")
            retained_inventory = retained_receipt.get("inventory")
            if (
                not isinstance(seal, str)
                or seal != _digest(retained_receipt)
                or not isinstance(version, int)
                or isinstance(version, bool)
                or version <= 0
                or version >= RECEIPT_VERSION
                or retained_receipt.get("receipt_path") != str(receipt_path)
                or retained_receipt.get("qualification_mode") != "full-copy"
                or not isinstance(retained_inventory, dict)
                or retained_inventory.get("fixture_root") != str(root)
                or retained_inventory.get("evidence_root") != str(paths["evidence_root"])
                or retained_inventory.get("snapshot_root") != str(path)
                or not isinstance(manifest, dict)
                or set(manifest)
                != {"files", "kg", "lance", "lance_hashes", "recovery_root", "root"}
                or manifest.get("root") != str(path)
                or sealed_snapshot != manifest
            ):
                raise MigrationError(
                    "retained_snapshot_unproved",
                    "retained snapshot does not match its sealed historical receipt",
                )
            if path in retained_snapshot_roots:
                raise MigrationError(
                    "target_overlap", "retained snapshot roots normalize to one path"
                )
            retained_snapshot_roots[path] = receipt_path

    candidates = raw["kg_candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise MigrationError(
            "kg_inventory_required", "kg_candidates must inventory every candidate"
        )
    kg_paths: list[Path] = []
    for value in candidates:
        if not isinstance(value, str) or not value:
            raise MigrationError("invalid_inventory_path", "each KG candidate must be a path")
        path = _real(value)
        if not _inside(path, root):
            raise MigrationError("outside_fixture", f"KG candidate escapes fixture root: {path}")
        _reject_symlink_chain(path, None if full_copy else root)
        kg_paths.append(path)

    required_candidates = {
        paths["palace"] / "knowledge_graph.sqlite3",
        root / "home" / ".mempalace" / "knowledge_graph.sqlite3",
    }
    missing_candidates = sorted(str(path) for path in required_candidates - set(kg_paths))
    if missing_candidates:
        raise MigrationError("kg_inventory_incomplete", ", ".join(missing_candidates))

    if _overlaps(paths["palace"], paths["project_root"]):
        raise MigrationError("target_overlap", "palace and project root must be disjoint")
    if not _inside(paths["marker"], paths["project_root"]):
        raise MigrationError("target_overlap", "marker must be inside project root")
    lance_root = paths["palace"] / "lance"
    if not _inside(paths["tiny_hashes"], paths["palace"]):
        raise MigrationError("target_overlap", "tiny hashes must be inside palace")
    if _overlaps(paths["tiny_hashes"], lance_root):
        raise MigrationError("target_overlap", "tiny hashes overlap Lance")

    # These ownership roots must be pairwise disjoint. Marker-in-project and
    # Lance/tiny/local-KG-in-palace are the only intentional containment edges.
    independent = {
        "evidence": paths["evidence_root"],
        "snapshot": paths["snapshot_root"],
        "lock": paths["lock"],
        "runtime": paths["runtime_root"],
        "palace": paths["palace"],
        "project": paths["project_root"],
        "configuration": paths["configuration"],
        **{
            f"retained_snapshot[{index}]": path
            for index, path in enumerate(retained_snapshot_roots)
        },
    }
    labels = list(independent)
    for index, first_label in enumerate(labels):
        for second_label in labels[index + 1 :]:
            if _overlaps(independent[first_label], independent[second_label]):
                raise MigrationError("target_overlap", f"{first_label} overlaps {second_label}")
    for index, kg_path in enumerate(kg_paths):
        if _inside(kg_path, paths["palace"]):
            if _overlaps(kg_path, lance_root) or _overlaps(kg_path, paths["tiny_hashes"]):
                raise MigrationError("target_overlap", f"kg[{index}] overlaps palace component")
            continue
        for label, path in independent.items():
            if label == "configuration":
                continue
            if _overlaps(kg_path, path):
                raise MigrationError("target_overlap", f"kg[{index}] overlaps {label}")
        if _overlaps(kg_path, paths["configuration"]):
            raise MigrationError("target_overlap", f"kg[{index}] overlaps configuration")
    if paths["runtime_root"].exists() and (
        not paths["runtime_root"].is_dir() or paths["runtime_root"].is_symlink()
    ):
        raise MigrationError("runtime_target_invalid", str(paths["runtime_root"]))
    if any(
        paths["runtime_root"] == path
        or _inside(paths["runtime_root"], path)
        or _inside(path, paths["runtime_root"])
        for path in [
            paths["palace"],
            paths["project_root"],
            paths["configuration"],
            paths["snapshot_root"],
            paths["evidence_root"],
        ]
    ):
        raise MigrationError("target_overlap", "runtime root overlaps inventoried data")

    if full_copy:
        _assert_private_tree(paths["palace"])
        _assert_private_tree(paths["project_root"])

    _require_lock_anchors(paths["lock"], root)

    private_files = [inventory_path, paths["marker"], paths["tiny_hashes"], paths["configuration"]]
    private_files.extend(path for path in kg_paths if path.exists())
    for private_file in private_files:
        if private_file.exists():
            _assert_regular_private(private_file)
    if lance_root.exists():
        for component in lance_root.rglob("*"):
            if component.is_file():
                _assert_regular_private(component)

    existing_identities: dict[tuple[int, int], str] = {}
    for label, path in [
        ("palace", paths["palace"]),
        ("project_root", paths["project_root"]),
        *[(f"kg[{index}]", path) for index, path in enumerate(kg_paths)],
    ]:
        if not path.exists():
            continue
        identity = (path.stat().st_dev, path.stat().st_ino)
        prior = existing_identities.get(identity)
        if prior is not None and not (prior.startswith("kg[") and label.startswith("kg[")):
            raise MigrationError("target_alias", f"{label} aliases {prior}")
        existing_identities[identity] = label

    full_copy_runtime = None
    if full_copy:
        full_copy_runtime = _validate_full_copy_authority(raw, paths, kg_paths)
    elif raw.get("qualification_mode", "synthetic") != "synthetic":
        raise MigrationError("qualification_mode_invalid", "unsupported inventory mode")

    inventory = dict(raw)
    inventory["inventory_path"] = str(inventory_path)
    inventory["fixture_root"] = str(root)
    inventory.update({key: str(value) for key, value in paths.items()})
    inventory["kg_candidates"] = [str(value) for value in kg_paths]
    if full_copy:
        inventory["retained_snapshot_roots"] = {
            str(root): str(receipt) for root, receipt in retained_snapshot_roots.items()
        }
    inventory["fixture_root_identity"] = _path_identity(root)
    if full_copy:
        inventory["qualification_mode"] = "full-copy"
        inventory["lance_state_format"] = LANCE_STATE_FORMAT
        inventory["retention_rule"] = raw["authority"]["retention_rule"]
        inventory["validated_runtime"] = full_copy_runtime
    return inventory


def _load_inventory(path: str | os.PathLike[str]) -> dict[str, Any]:
    inventory_path = _real(path)
    return _validate_inventory(_load_json(inventory_path), inventory_path)


def _check_fixture_identity(inventory: dict[str, Any]) -> None:
    root = Path(inventory["fixture_root"])
    if _path_identity(root) != inventory["fixture_root_identity"]:
        raise MigrationError("fixture_identity_changed", f"fixture root changed: {root}")
    if inventory.get("qualification_mode") == "live":
        if socket.gethostname() != inventory.get("approved_host"):
            raise MigrationError("live_host_mismatch", "current host differs from live authority")
        authority_path = Path(inventory["authority_path"])
        _assert_regular_private(authority_path)
        if not _private_mode_is_0600(authority_path):
            raise MigrationError("live_authority_permissions", "live authority must use mode 0600")
        if _digest(_load_json(authority_path)) != inventory.get("live_authority_seal"):
            raise MigrationError("live_authority_drift", "live authority changed")
        for label, value in inventory["live_target_identities"].items():
            path = Path(label)
            try:
                if _path_identity(path) != value:
                    raise MigrationError("live_target_drift", f"target identity changed: {path}")
            except OSError as exc:
                raise MigrationError("live_target_drift", f"target unavailable: {path}") from exc
        for value in inventory["live_mutable_paths"]:
            path = Path(value)
            _reject_symlink_chain(path)
            if path.exists():
                _assert_regular_private(path)
        lance_root = Path(inventory["palace"]) / "lance"
        _reject_symlink_chain(lance_root)
        _assert_private_tree(lance_root)
        recovery_runner = Path(inventory["recovery_runner"])
        _reject_symlink_chain(recovery_runner)
        _assert_regular_private(recovery_runner)
        if _file_digest(recovery_runner) != inventory["recovery_runner_sha256"]:
            raise MigrationError("runner_changed", "retained live recovery runner changed")
        return
    marker_path = root / FIXTURE_MARKER
    _reject_symlink_chain(marker_path, root)
    try:
        _assert_regular_private(marker_path)
    except FileNotFoundError:
        pass
    marker = _load_json(marker_path)
    if marker != {"disposable": True, "fixture_id": inventory["fixture_id"]}:
        raise MigrationError("fixture_identity_changed", "fixture authorization marker changed")


def _create_lock_anchors(lock_path: Path) -> None:
    for path in _lock_artifact_paths(lock_path)[:2]:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)


def _require_lock_anchors(lock_path: Path, root: Path) -> None:
    for path in _lock_artifact_paths(lock_path)[:2]:
        _reject_symlink_chain(path, root)
        try:
            _assert_regular_private(path)
        except (FileNotFoundError, OSError) as exc:
            raise MigrationError(
                "lock_anchor_invalid", "stable lock anchors must be regular private files"
            ) from exc
        if not _private_mode_is_0600(path):
            raise MigrationError("lock_anchor_invalid", "stable lock anchors must use mode 0600")


def _check_copy_separation(inventory: dict[str, Any], *, allow_missing_kg: bool = False) -> None:
    if inventory.get("qualification_mode") not in {"full-copy", "full-copy-trial"}:
        return
    allow_missing_kg = allow_missing_kg or inventory.get("construction_phase") in {
        "copying",
        "recovered",
    }
    expected = inventory["validated_runtime"]["copy_identities"]
    paths = {
        "palace": Path(inventory["palace"]),
        "project_root": Path(inventory["project_root"]),
        "kg_candidates": [Path(value) for value in inventory["kg_candidates"]],
    }
    try:
        observed = {
            "palace": _identity_value(paths["palace"]),
            "project_root": _identity_value(paths["project_root"]),
        }
    except OSError as exc:
        raise MigrationError("copy_identity_drift", "a copied target is unavailable") from exc
    if observed != expected:
        raise MigrationError("copy_identity_drift", "a copied target identity changed")
    qualification_device = inventory["copy_verification"]["qualification_device"]
    for path in paths["kg_candidates"]:
        if allow_missing_kg and not path.exists():
            continue
        try:
            _reject_symlink_chain(path)
            _assert_regular_private(path)
        except OSError as exc:
            raise MigrationError("copy_identity_drift", "a KG candidate is unavailable") from exc
        if _identity_value(path)["device"] != qualification_device:
            raise MigrationError("copy_identity_drift", "a KG candidate left the copy device")


def _fixture_observation_targets(inventory: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    kg_candidates = [Path(value) for value in inventory["kg_candidates"]]
    directories = [
        path
        for path in (
            Path(inventory["palace"]),
            Path(inventory["project_root"]),
            Path(inventory["snapshot_root"]),
        )
        if path.is_dir() and not path.is_symlink()
    ]
    lock = Path(inventory["lock"])
    files = [
        path
        for path in (
            Path(inventory["configuration"]),
            Path(inventory["tiny_hashes"]),
            Path(inventory["marker"]),
            lock,
            lock.with_name(f"{lock.name}.metadata.lock"),
            lock.with_name(f"{lock.name}.owners.json"),
            *kg_candidates,
            *(Path(f"{path}-wal") for path in kg_candidates),
            *(Path(f"{path}-shm") for path in kg_candidates),
        )
        if path.is_file() and not path.is_symlink()
    ]
    return sorted(set(directories)), sorted(set(files))


def _observe_fixture_clients(inventory: dict[str, Any]) -> None:
    """Fail closed when another process has an active migration target open."""
    directories, files = _fixture_observation_targets(inventory)
    lsof = shutil.which("lsof")
    if lsof is not None:
        command = [lsof, "-Fpn"]
        for directory in directories:
            command.extend(("+D", str(directory)))
        command.extend(str(path) for path in files)
        try:
            observed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=PROCESS_OBSERVATION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MigrationError("process_observation_unknown", "lsof observation failed") from exc
        if observed.returncode not in {0, 1}:
            raise MigrationError("process_observation_unknown", "lsof observation was incomplete")
        pids = {
            int(line[1:])
            for line in observed.stdout.splitlines()
            if line.startswith("p") and line[1:].isdigit()
        }
        foreign = sorted(pid for pid in pids if pid != os.getpid())
        if foreign:
            raise MigrationError("fixture_client_active", ",".join(map(str, foreign)))
        return

    proc = Path("/proc")
    if proc.is_dir():
        foreign: list[int] = []
        try:
            processes = list(proc.iterdir())
        except OSError as exc:
            raise MigrationError(
                "process_observation_unknown", "process list is unavailable"
            ) from exc
        for process in processes:
            if not process.name.isdigit() or int(process.name) == os.getpid():
                continue
            try:
                descriptors = list((process / "fd").iterdir())
                targets = [Path(os.readlink(fd)) for fd in descriptors]
            except OSError as exc:
                raise MigrationError(
                    "process_observation_unknown", "process descriptors are unavailable"
                ) from exc
            if any(
                any(_inside(target, directory) for directory in directories) or target in files
                for target in targets
            ):
                foreign.append(int(process.name))
        if foreign:
            raise MigrationError("fixture_client_active", ",".join(map(str, sorted(foreign))))
        return
    raise MigrationError(
        "process_observation_unknown", "neither lsof nor procfs observation is available"
    )


def _live_processes() -> dict[int, str]:
    """Return this user's installed MCP stdio processes, excluding this operator."""
    observed = subprocess.run(
        ["ps", "-axo", "pid=,uid=,command="],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if observed.returncode != 0:
        raise MigrationError("process_observation_unknown", "process inventory failed")
    result: dict[int, str] = {}
    for line in observed.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        pid, uid, command = int(fields[0]), int(fields[1]), fields[2]
        if pid == os.getpid() or uid != os.getuid():
            continue
        try:
            arguments = shlex.split(command)
        except ValueError:
            continue
        executable = Path(arguments[0]).name if arguments else ""
        python = executable.startswith("python")
        launcher = executable == "mempalace-code-mcp" or (
            python and len(arguments) > 1 and Path(arguments[1]).name == "mempalace-code-mcp"
        )
        try:
            module_index = arguments.index("-m")
        except ValueError:
            module = False
        else:
            module = (
                python
                and all(value.startswith("-") for value in arguments[1:module_index])
                and module_index + 1 < len(arguments)
                and arguments[module_index + 1]
                in {"mempalace_code.mcp_server", "mempalace.mcp_server"}
            )
        if launcher or module:
            result[pid] = command
    return result


def _stop_live_mcp_clients() -> list[int]:
    processes = _live_processes()
    for pid, command in processes.items():
        if _live_processes().get(pid) != command:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    remaining = processes
    while remaining and time.monotonic() < deadline:
        time.sleep(0.1)
        remaining = _live_processes()
    for pid, command in remaining.items():
        if _live_processes().get(pid) != command:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if remaining:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            alive = _live_processes()
            if not alive:
                break
            time.sleep(0.1)
        else:
            raise MigrationError("live_clients_active", ",".join(map(str, sorted(alive))))
    return sorted(processes)


def _observe_live_clients(inventory: dict[str, Any]) -> None:
    mcp = _live_processes()
    if mcp:
        raise MigrationError("live_clients_active", ",".join(map(str, sorted(mcp))))
    lsof = shutil.which("lsof")
    if lsof is None:
        raise MigrationError("process_observation_unknown", "lsof is required for live migration")
    targets = [
        Path(inventory["palace"]),
        Path(inventory["configuration"]),
        Path(inventory["tiny_hashes"]),
        Path(inventory["marker"]),
        *(Path(value) for value in inventory["kg_candidates"]),
    ]
    command = [lsof, "-Fpn", "+D", str(targets[0]), *map(str, targets[1:])]
    try:
        observed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=PROCESS_OBSERVATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MigrationError("process_observation_unknown", "live lsof observation failed") from exc
    if observed.returncode not in {0, 1}:
        raise MigrationError("process_observation_unknown", "live lsof observation was incomplete")
    pids = {
        int(line[1:])
        for line in observed.stdout.splitlines()
        if line.startswith("p") and line[1:].isdigit()
    }
    foreign = sorted(pid for pid in pids if pid != os.getpid())
    if foreign:
        raise MigrationError("live_client_active", ",".join(map(str, foreign)))


def _lock_artifact_paths(lock_path: Path) -> tuple[Path, ...]:
    return (
        lock_path,
        lock_path.with_name(f"{lock_path.name}.metadata.lock"),
        lock_path.with_name(f"{lock_path.name}.owners.json"),
    )


def _lock_artifact_snapshot(path: Path) -> tuple[bool, bytes | None, int | None, int | None]:
    if not path.exists() and not path.is_symlink():
        return False, None, None, None
    if path.is_symlink() or not path.is_file():
        return True, None, None, None
    metadata = path.stat()
    return True, path.read_bytes(), stat.S_IMODE(metadata.st_mode), metadata.st_mtime_ns


def _restore_failed_lock_artifact(
    path: Path,
    state: tuple[bool, bytes | None, int | None, int | None],
) -> None:
    existed, content, mode, mtime_ns = state
    if existed:
        if content is None or path.is_symlink() or (path.exists() and not path.is_file()):
            return
        if not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)
        if mode is not None:
            os.chmod(path, mode)
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        return
    if path.is_file() and not path.is_symlink():
        path.unlink()


def _cleanup_failed_lock_artifacts(
    lock: Any,
    paths: tuple[Path, ...],
    before: dict[Path, tuple[bool, bytes | None, int | None, int | None]],
) -> None:
    """Restore failed-fence metadata without crossing a lock inode race."""
    import fcntl

    lock_path, metadata_path, owners_path = paths
    try:
        descriptor = os.open(lock_path, os.O_RDWR)
    except OSError:
        return
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return
        try:
            metadata_descriptor = os.open(metadata_path, os.O_RDWR)
            try:
                fcntl.flock(metadata_descriptor, fcntl.LOCK_EX)
                owners = lock._read_owners()
                if any(lock._owner_is_alive(owner) for owner in owners.values()):
                    return
                # Stable main/metadata anchors are admission prerequisites. Never
                # replace or unlink their inodes while another opener may hold one.
                _restore_failed_lock_artifact(owners_path, before[owners_path])
            finally:
                fcntl.flock(metadata_descriptor, fcntl.LOCK_UN)
                os.close(metadata_descriptor)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@contextmanager
def _fence(
    inventory: dict[str, Any],
    *,
    allow_missing_kg: bool = False,
    live_phases: frozenset[str] = frozenset({"receipt"}),
) -> Iterator[None]:
    _check_fixture_identity(inventory)
    if inventory.get("qualification_mode") == "live":
        _assert_live_maintenance(inventory, live_phases)
    _check_copy_separation(inventory, allow_missing_kg=allow_missing_kg)
    lock_root = (
        Path(inventory["lock"]).parent
        if inventory.get("qualification_mode") == "live"
        else Path(inventory["fixture_root"])
    )
    _require_lock_anchors(Path(inventory["lock"]), lock_root)
    repo_root = RUNNER_PATH.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mempalace_code.operation_lock import OperationLock, OperationLockedError

    lock = OperationLock(inventory["lock"])
    lock_paths = _lock_artifact_paths(lock.path)
    lock_artifacts_before = {path: _lock_artifact_snapshot(path) for path in lock_paths}
    try:
        lease = lock.acquire_exclusive("fixture-wing-migration")
    except OperationLockedError as exc:
        raise MigrationError("writer_conflict", json.dumps(exc.owner, sort_keys=True)) from exc
    failed = False
    try:
        with lease:
            try:
                _check_fixture_identity(inventory)
                if inventory.get("qualification_mode") == "live":
                    _assert_live_maintenance(inventory, live_phases)
                _check_copy_separation(inventory, allow_missing_kg=allow_missing_kg)
                if inventory.get("qualification_mode") == "live":
                    _observe_live_clients(inventory)
                else:
                    _observe_fixture_clients(inventory)
                yield
            except BaseException:
                failed = True
                raise
    finally:
        if failed:
            _cleanup_failed_lock_artifacts(lock, lock_paths, lock_artifacts_before)


def _lance_row_witness(row: dict[str, Any]) -> dict[str, Any]:
    witness = {field: row.get(field) for field in LANCE_WITNESS_FIELDS}
    witness["payload_sha256"] = _digest(
        {key: value for key, value in row.items() if key not in {"id", "wing"}}
    )
    return witness


def _read_lance(palace: Path, *, compact: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    table_dir = palace / "lance" / f"{TABLE_NAME}.lance"
    if not table_dir.is_dir():
        return [], None
    import lancedb

    table = lancedb.connect(str(palace / "lance")).open_table(TABLE_NAME)
    if compact:
        reader = table.search().to_batches(batch_size=LANCE_SCAN_BATCH_SIZE)
        schema = base64.b64encode(reader.schema.serialize().to_pybytes()).decode("ascii")
        rows = [_lance_row_witness(row) for batch in reader for row in batch.to_pylist()]
        if len(rows) != table.count_rows():
            raise MigrationError("lance_scan_incomplete", "bounded scan did not cover the table")
    else:
        arrow = table.to_arrow()
        rows = arrow.to_pylist()
        schema = base64.b64encode(arrow.schema.serialize().to_pybytes()).decode("ascii")
    return sorted(rows, key=lambda row: (str(row.get("id")), _digest(row))), schema


def _read_lance_rows(palace: Path) -> list[dict[str, Any]]:
    return _read_lance(palace)[0]


def _read_lance_row(palace: Path, row_id: str) -> dict[str, Any]:
    import lancedb

    table = lancedb.connect(str(palace / "lance")).open_table(TABLE_NAME)
    quoted = row_id.replace("'", "''")
    rows = table.search().where(f"id = '{quoted}'").limit(2).to_arrow().to_pylist()
    if len(rows) != 1:
        raise MigrationError("row_identity_invalid", "sealed row ID is not unique")
    return rows[0]


def _sqlite_checksum(data: bytes, first: int, second: int, byteorder: str) -> tuple[int, int]:
    if len(data) % 8:
        raise MigrationError("kg_wal_invalid", "WAL checksum input is not word aligned")
    prefix = ">" if byteorder == "big" else "<"
    words = struct.unpack(f"{prefix}{len(data) // 4}I", data)
    for index in range(0, len(words), 2):
        first = (first + words[index] + second) & 0xFFFFFFFF
        second = (second + words[index + 1] + first) & 0xFFFFFFFF
    return first, second


def _assert_sqlite_artifacts_safe(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        _reject_symlink_chain(candidate)
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        _assert_regular_private(candidate)


def _sqlite_image(path: Path) -> bytes:
    _assert_sqlite_artifacts_safe(path)
    main_before = path.stat()
    image = path.read_bytes()
    main_after = path.stat()
    if (main_before.st_size, main_before.st_mtime_ns) != (
        main_after.st_size,
        main_after.st_mtime_ns,
    ):
        raise MigrationError("kg_changed_during_read", "SQLite main file changed")
    wal_path = Path(f"{path}-wal")
    if not wal_path.exists():
        return image
    wal_before = wal_path.stat()
    wal = wal_path.read_bytes()
    wal_after = wal_path.stat()
    if (wal_before.st_size, wal_before.st_mtime_ns) != (
        wal_after.st_size,
        wal_after.st_mtime_ns,
    ):
        raise MigrationError("kg_changed_during_read", "SQLite WAL changed")
    if not wal:
        return image
    if len(wal) < 32:
        raise MigrationError("kg_wal_invalid", "SQLite WAL header is truncated")
    magic, version, page_size, _, salt_first, salt_second, check_first, check_second = (
        struct.unpack(">8I", wal[:32])
    )
    if magic not in {0x377F0682, 0x377F0683} or version != 3007000:
        raise MigrationError("kg_wal_invalid", "SQLite WAL header is unsupported")
    if page_size == 1:
        page_size = 65536
    if page_size < 512 or page_size > 65536 or page_size & (page_size - 1):
        raise MigrationError("kg_wal_invalid", "SQLite WAL page size is invalid")
    checksum_order = "big" if magic == 0x377F0683 else "little"
    observed = _sqlite_checksum(wal[:24], 0, 0, checksum_order)
    if observed != (check_first, check_second):
        raise MigrationError("kg_wal_invalid", "SQLite WAL header checksum differs")
    frame_size = 24 + page_size
    frame_bytes = len(wal) - 32
    complete_frames, trailing_bytes = divmod(frame_bytes, frame_size)
    frames: list[tuple[int, int, bytes]] = []
    committed_count = 0
    committed_size = 0
    generation_boundary = False
    for frame_index in range(complete_frames):
        offset = 32 + frame_index * frame_size
        header = wal[offset : offset + 24]
        page = wal[offset + 24 : offset + frame_size]
        (
            page_number,
            database_size,
            frame_salt_first,
            frame_salt_second,
            stored_first,
            stored_second,
        ) = struct.unpack(">6I", header)
        if (frame_salt_first, frame_salt_second) != (salt_first, salt_second):
            # SQLite reuses a WAL after RESTART.  The new header and active
            # frames have fresh salts while the old generation may remain in
            # the file as valid trailing frames.  The first old-generation
            # frame is the current-generation boundary; SQLite ignores the
            # remainder of the file.
            generation_boundary = True
            break
        if page_number == 0:
            raise MigrationError("kg_wal_invalid", "SQLite WAL frame identity differs")
        check_first, check_second = _sqlite_checksum(
            header[:8] + page, check_first, check_second, checksum_order
        )
        if (check_first, check_second) != (stored_first, stored_second):
            raise MigrationError("kg_wal_invalid", "SQLite WAL frame checksum differs")
        frames.append((page_number, database_size, page))
        if database_size:
            committed_count = len(frames)
            committed_size = database_size
    if trailing_bytes and not generation_boundary:
        raise MigrationError("kg_wal_invalid", "SQLite WAL frame is truncated")
    if not committed_count:
        return image
    required = committed_size * page_size
    materialized = bytearray(image[:required])
    if len(materialized) < required:
        materialized.extend(b"\0" * (required - len(materialized)))
    for page_number, _, page in frames[:committed_count]:
        start = (page_number - 1) * page_size
        if start >= required:
            continue
        materialized[start : start + page_size] = page
    return bytes(materialized)


def _sqlite_read_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    try:
        image = bytearray(_sqlite_image(path))
        if len(image) < 100 or image[:16] != b"SQLite format 3\x00":
            raise MigrationError("kg_schema_invalid", "SQLite header is invalid")
        image[18:20] = b"\x01\x01"
        connection.deserialize(bytes(image))
    except Exception:
        connection.close()
        raise
    return connection


def _sqlite_rows(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "entities": [], "triples": []}
    connection = _sqlite_read_connection(path)
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"entities", "triples"} <= names:
            raise MigrationError("kg_schema_invalid", f"missing KG tables in {path}")
        entities = [
            dict(zip(("id", "name", "type", "properties", "created_at"), row, strict=True))
            for row in connection.execute(
                "SELECT id,name,type,properties,created_at FROM entities ORDER BY id"
            )
        ]
        triples = [
            dict(
                zip(
                    (
                        "id",
                        "subject",
                        "predicate",
                        "object",
                        "valid_from",
                        "valid_to",
                        "confidence",
                        "source_closet",
                        "source_file",
                        "extracted_at",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in connection.execute(
                "SELECT id,subject,predicate,object,valid_from,valid_to,confidence,"
                "source_closet,source_file,extracted_at FROM triples ORDER BY id"
            )
        ]
        return {"exists": True, "entities": entities, "triples": triples}
    finally:
        connection.close()


def _sqlite_full_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "schema": [], "tables": {}}
    connection = _sqlite_read_connection(path)
    try:
        schema = [
            list(row)
            for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name"
            )
        ]
        tables: dict[str, list[list[Any]]] = {}
        for object_type, name, _, _ in schema:
            if object_type != "table" or str(name).startswith("sqlite_"):
                continue
            quoted = '"' + str(name).replace('"', '""') + '"'
            rows = [list(row) for row in connection.execute(f"SELECT * FROM {quoted}")]
            tables[str(name)] = sorted(rows, key=_digest)
        return {"exists": True, "schema": schema, "tables": tables}
    finally:
        connection.close()


def _file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "bytes": None}
    if path.is_symlink() or not path.is_file():
        raise MigrationError("unsafe_component", f"expected regular file: {path}")
    return {"exists": True, "bytes": base64.b64encode(path.read_bytes()).decode("ascii")}


def _capture_non_lance(inventory: dict[str, Any]) -> dict[str, Any]:
    kg_states: list[dict[str, Any]] = []
    aliases: dict[tuple[int, int], int] = {}
    for index, value in enumerate(inventory["kg_candidates"]):
        path = Path(value)
        if path.exists():
            identity = (path.stat().st_dev, path.stat().st_ino)
            if identity in aliases:
                kg_states.append({"path": str(path), "alias_of": aliases[identity]})
                continue
            aliases[identity] = index
        kg_states.append({"path": str(path), "state": _sqlite_rows(path)})
    return {
        "tiny_hashes": _file_state(Path(inventory["tiny_hashes"])),
        "marker": _file_state(Path(inventory["marker"])),
        "configuration": _file_state(Path(inventory["configuration"])),
        "kg": kg_states,
    }


def _capture(inventory: dict[str, Any]) -> dict[str, Any]:
    palace = Path(inventory["palace"])
    compact_lance = inventory.get("lance_state_format") == LANCE_STATE_FORMAT
    lance_rows, lance_schema = _read_lance(palace, compact=compact_lance)
    return {
        "lance_rows": lance_rows,
        "lance_schema": lance_schema,
        **_capture_non_lance(inventory),
    }


def _row_without_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"id", "wing"}}


def _path_scoped(source_file: Any, project_root: Path) -> bool:
    if not isinstance(source_file, str) or not source_file:
        return False
    try:
        candidate = _lexical_absolute(source_file, "source_path_invalid")
        root = _lexical_absolute(str(project_root), "logical_source_root_invalid")
    except MigrationError:
        return False
    return candidate == root or root in candidate.parents


def _parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _in_window(valid_from: Any, valid_to: Any, frozen: datetime) -> bool:
    def lower(value: Any) -> datetime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def upper(value: Any) -> datetime | None:
        if value is None:
            return None
        text = str(value)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            text += "T23:59:59+00:00"
        return lower(text)

    start = lower(valid_from)
    end = upper(valid_to)
    return (start is None or start <= frozen) and (end is None or frozen <= end)


def _decode_json_state(state: dict[str, Any], label: str) -> dict[str, Any]:
    if not state["exists"]:
        return {}
    raw = base64.b64decode(state["bytes"])
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError("tiny_hashes_invalid", f"{label}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError("tiny_hashes_invalid", f"{label} must be an object")
    return value


def _encode_file_state(value: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"exists": True, "bytes": base64.b64encode(raw).decode("ascii")}


def _migrate_tiny_hashes(state: dict[str, Any], source: str, destination: str) -> dict[str, Any]:
    data = _decode_json_state(state, "tiny hashes")
    for wing, hashes in data.items():
        if not isinstance(wing, str) or not isinstance(hashes, dict):
            raise MigrationError("tiny_hashes_invalid", "every wing value must be an object")
        for source_file, source_hash in hashes.items():
            if not isinstance(source_file, str) or not HASH_RE.fullmatch(str(source_hash)):
                raise MigrationError("tiny_hashes_invalid", f"invalid hash for {source_file!r}")
    source_hashes = data.get(source, {})
    destination_hashes = data.get(destination, {})
    merged = dict(destination_hashes)
    for source_file, source_hash in source_hashes.items():
        existing = merged.get(source_file)
        if existing is not None and existing != source_hash:
            raise MigrationError("tiny_hash_collision", source_file)
        merged[source_file] = source_hash
    migrated = dict(data)
    migrated.pop(source, None)
    if merged or destination in data:
        migrated[destination] = merged
    return _encode_file_state(migrated)


def _migrate_marker(state: dict[str, Any], source: str, destination: str) -> dict[str, Any]:
    if not state["exists"]:
        raise MigrationError("marker_missing", "project wing marker is absent")
    raw = base64.b64decode(state["bytes"])
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise MigrationError("marker_invalid", "project marker must be UTF-8") from exc
    pattern = re.compile(rf"(?m)^(\s*wing\s*:\s*){re.escape(source)}(\s*(?:#.*)?)$")
    migrated, count = pattern.subn(rf"\g<1>{destination}\g<2>", text)
    if count != 1:
        raise MigrationError("marker_source_mismatch", "marker must contain one exact source wing")
    return {
        "exists": True,
        "bytes": base64.b64encode(migrated.encode("utf-8")).decode("ascii"),
    }


def _eligible_triple(
    row: dict[str, Any], source_id: str, source: str, project_root: Path, frozen: datetime
) -> bool:
    if row["predicate"] != "in_project" or row["object"] != source_id:
        return False
    if not _in_window(row["valid_from"], row["valid_to"], frozen):
        return False
    source_file = row["source_file"]
    sentinels = {f"__arch_ns_project__:{source}", "__arch_ns_project__"}
    return source_file in sentinels or _path_scoped(source_file, project_root)


def _expected_state(
    inventory: dict[str, Any], pre: dict[str, Any], frozen_at: str
) -> dict[str, Any]:
    source = inventory["source_wing"]
    destination = inventory["destination_wing"]
    rows = copy.deepcopy(pre["lance_rows"])
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)):
        raise MigrationError("duplicate_drawer_id", "drawer IDs must be globally unique")

    project_root = Path(inventory.get("logical_source_root", inventory["project_root"]))
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        wing = row.get("wing")
        source_file = row.get("source_file")
        if wing not in {source, destination} or not _path_scoped(source_file, project_root):
            continue
        canonical_source_file = _lexical_absolute(source_file, "source_path_invalid")
        grouped.setdefault(str(canonical_source_file), {}).setdefault(str(wing), []).append(row)
        ingest_mode = row.get("ingest_mode")
        file_provenance = ingest_mode == "file" or (
            ingest_mode == "" and row.get("chunker_strategy") in LEGACY_FILE_CHUNKER_STRATEGIES
        )
        regenerable = (
            file_provenance
            and row.get("type", "") == ""
            and HASH_RE.fullmatch(str(row.get("source_hash", ""))) is not None
        )
        if not regenerable:
            raise MigrationError("protected_replacement_exposure", str(source_file))
    for source_file, wings in grouped.items():
        for wing, wing_rows in wings.items():
            by_chunk: dict[Any, list[dict[str, Any]]] = {}
            for row in wing_rows:
                by_chunk.setdefault(row.get("chunk_index"), []).append(row)
            source_hashes = {row.get("source_hash") for row in wing_rows}
            if len(source_hashes) != 1:
                raise MigrationError(
                    "file_identity_collision",
                    f"{source_file} has inconsistent {wing} source hashes",
                )
            for chunk_rows in by_chunk.values():
                identities = {_digest(_row_without_identity(row)) for row in chunk_rows}
                if len(identities) > 1:
                    raise MigrationError(
                        "file_identity_collision", f"{source_file} has conflicting {wing} chunks"
                    )
    for source_file, wings in grouped.items():
        if source in wings and destination in wings:
            source_rows = sorted((_row_without_identity(row) for row in wings[source]), key=_digest)
            destination_rows = sorted(
                (_row_without_identity(row) for row in wings[destination]), key=_digest
            )
            if source_rows != destination_rows:
                raise MigrationError("file_identity_collision", source_file)
    for row in rows:
        if row.get("wing") == source:
            row["wing"] = destination
    lance_expected: list[dict[str, Any]] | dict[str, Any] = rows
    if inventory.get("lance_state_format") == LANCE_STATE_FORMAT:
        lance_expected = {
            "format": LANCE_EXPECTED_FORMAT,
            "destination_wing": destination,
            "updated_ids": [
                after["id"]
                for before, after in zip(pre["lance_rows"], rows, strict=True)
                if before.get("wing") != after.get("wing")
            ],
        }

    frozen = _parse_instant(frozen_at)
    source_id = source.lower().replace(" ", "_").replace("'", "")
    destination_id = destination.lower().replace(" ", "_").replace("'", "")
    kg_states = copy.deepcopy(pre["kg"])
    eligible_total = 0
    eligible_by_path: dict[str, list[str]] = {}
    for candidate in kg_states:
        if "alias_of" in candidate:
            continue
        state = candidate["state"]
        if not state["exists"]:
            eligible_by_path[candidate["path"]] = []
            continue
        entities = state["entities"]
        triples = state["triples"]
        entity_ids = [entity["id"] for entity in entities]
        triple_ids = [triple["id"] for triple in triples]
        if len(entity_ids) != len(set(entity_ids)) or len(triple_ids) != len(set(triple_ids)):
            raise MigrationError("duplicate_kg_id", candidate["path"])
        source_entities = [entity for entity in entities if entity["name"] == source]
        if source_entities and any(entity["id"] != source_id for entity in source_entities):
            raise MigrationError("source_entity_conflict", candidate["path"])
        destination_entities = [entity for entity in entities if entity["name"] == destination]
        by_destination_id = [entity for entity in entities if entity["id"] == destination_id]
        if any(entity["id"] != destination_id for entity in destination_entities) or (
            by_destination_id and by_destination_id[0]["name"] != destination
        ):
            raise MigrationError("destination_entity_conflict", candidate["path"])
        eligible = [
            triple
            for triple in triples
            if _eligible_triple(triple, source_id, source, project_root, frozen)
        ]
        eligible_by_path[candidate["path"]] = [triple["id"] for triple in eligible]
        eligible_total += len(eligible)
        if eligible and not destination_entities:
            template = next((entity for entity in entities if entity["id"] == source_id), None)
            created_at = frozen_at if template is None else template["created_at"]
            entities.append(
                {
                    "id": destination_id,
                    "name": destination,
                    "type": "unknown",
                    "properties": "{}",
                    "created_at": created_at,
                }
            )
            entities.sort(key=lambda entity: entity["id"])
        for triple in eligible:
            triple["object"] = destination_id
            if triple["source_file"] in {
                f"__arch_ns_project__:{source}",
                "__arch_ns_project__",
            }:
                triple["source_file"] = f"__arch_ns_project__:{destination}"
    marker_state = _migrate_marker(pre["marker"], source, destination)
    tiny_state = _migrate_tiny_hashes(pre["tiny_hashes"], source, destination)
    expected = {
        "lance_rows": lance_expected,
        "lance_schema": pre["lance_schema"],
        "tiny_hashes": tiny_state,
        "marker": marker_state,
        "configuration": pre["configuration"],
        "kg": kg_states,
    }
    expected["eligible_total"] = eligible_total
    expected["kg_eligible"] = eligible_by_path
    return expected


def _receipt_path(receipt: dict[str, Any]) -> Path:
    return Path(receipt["receipt_path"])


def _load_receipt(path: str | os.PathLike[str]) -> dict[str, Any]:
    receipt_path = _real(path)
    _assert_regular_private(receipt_path)
    if receipt_path.stat().st_size > MAX_RECEIPT_BYTES:
        raise MigrationError("receipt_too_large", "sealed receipt exceeds the size limit")
    receipt = _load_json(receipt_path)
    if receipt.get("version") != RECEIPT_VERSION:
        raise MigrationError("receipt_version_invalid", str(receipt.get("version")))
    if receipt.get("receipt_path") != str(receipt_path):
        raise MigrationError("wrong_target_receipt", "receipt path binding changed")
    seal = receipt.pop("seal", None)
    if not isinstance(seal, str) or seal != _digest(receipt):
        raise MigrationError("receipt_seal_invalid", "receipt contents changed")
    receipt["seal"] = seal
    _check_fixture_identity(receipt["inventory"])
    if receipt["runner_hash"] != _file_digest(RUNNER_PATH):
        raise MigrationError("runner_changed", "runner hash differs from sealed receipt")
    return receipt


def _save_receipt(receipt: dict[str, Any], *, initial: bool = False) -> None:
    value = copy.deepcopy(receipt)
    value.pop("seal", None)
    value["seal"] = _digest(value)
    try:
        _atomic_json(
            _receipt_path(value),
            value,
            replace=not initial,
            max_bytes=MAX_RECEIPT_BYTES,
        )
    except MigrationError as exc:
        if initial and exc.code == "evidence_exists":
            raise MigrationError(
                "receipt_exists", "refusing to replace an existing receipt"
            ) from exc
        raise
    receipt.clear()
    receipt.update(value)


def _recovery_working_set_bytes(inventory: dict[str, Any]) -> int:
    root = Path(inventory["fixture_root"])
    excluded = {
        Path(inventory["evidence_root"]),
        Path(inventory["runtime_root"]),
        *(Path(value) for value in inventory.get("retained_snapshot_roots", {})),
    }
    total = 0
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(name for name in directories if current_path / name not in excluded)
        for name in files:
            path = current_path / name
            if not path.is_symlink() and path.is_file():
                total += path.stat().st_size
    return total


def _assert_recovery_capacity(inventory: dict[str, Any]) -> None:
    root = Path(inventory["fixture_root"])
    required = int(inventory.get("required_free_bytes", 0))
    estimated = _recovery_working_set_bytes(inventory)
    available = shutil.disk_usage(root).free
    if available < max(required, estimated * 2 + 1024 * 1024):
        raise MigrationError("insufficient_disk", "insufficient recovery capacity")


def inventory(
    inventory_path: str,
    receipt_path: str,
    *,
    frozen_at: str | None = None,
    reserved_paths: tuple[Path, ...] = (),
) -> dict:
    inv = _load_inventory(inventory_path)
    full_copy = inv.get("qualification_mode") == "full-copy"
    if full_copy:
        _full_copy_inventory_path(inventory_path)
    if not full_copy and Path(inv["runtime_root"]).exists():
        raise MigrationError("runtime_target_exists", inv["runtime_root"])
    receipt_target = _real(receipt_path)
    if not _inside(receipt_target, Path(inv["fixture_root"])):
        raise MigrationError("outside_fixture", "receipt must be inside fixture root")
    evidence_root = Path(inv["evidence_root"])
    if not _inside(receipt_target, evidence_root):
        raise MigrationError("receipt_binding_invalid", "receipt must be inside evidence root")
    forbidden_receipt_roots = [
        Path(inv["snapshot_root"]),
        *(Path(value) for value in inv.get("retained_snapshot_roots", {})),
        Path(inv["runtime_root"]),
        Path(inv["palace"]),
        Path(inv["project_root"]),
    ]
    if any(_inside(receipt_target, root) for root in forbidden_receipt_roots):
        raise MigrationError("target_overlap", "receipt overlaps a migration target")
    _reject_symlink_chain(
        receipt_target,
        None if inv.get("qualification_mode") == "full-copy" else Path(inv["fixture_root"]),
    )
    if receipt_target.exists():
        raise MigrationError("receipt_exists", "refusing to replace an existing receipt")
    if any(path.exists() or path.is_symlink() for path in reserved_paths):
        raise MigrationError("full_copy_evidence_exists", "refusing to replace retained evidence")
    _check_fixture_identity(inv)
    _check_copy_separation(inv)
    _observe_fixture_clients(inv)
    pre = _capture(inv)
    frozen = frozen_at or datetime.now(UTC).isoformat()
    expected = _expected_state(inv, pre, frozen)
    _assert_recovery_capacity(inv)
    runtime = copy.deepcopy(inv["validated_runtime"]) if full_copy else _runtime_identity()
    unrelated_preimage = _digest(_unrelated_file_hashes(inv)) if full_copy else None
    if full_copy:
        # Execute the owner-selected installed interpreter after admission's
        # read-only checks and before the fence can create owner metadata.
        _validate_runtime({"inventory": inv, "runtime": runtime})
    with _fence(inv):
        if receipt_target.exists() or any(
            path.exists() or path.is_symlink() for path in reserved_paths
        ):
            raise MigrationError("full_copy_evidence_exists", "retained evidence appeared")
        if _capture(inv) != pre:
            raise MigrationError("preimage_drift", "state changed during admission")
        _assert_recovery_capacity(inv)
        if full_copy:
            # Repeat the executable and package checks while the admission fence
            # is held so a preflight result cannot be reused across a TOCTOU gap.
            _validate_runtime({"inventory": inv, "runtime": runtime})
        receipt = {
            "version": RECEIPT_VERSION,
            "receipt_path": str(receipt_target),
            "inventory": inv,
            "runner_hash": _file_digest(RUNNER_PATH),
            "runtime": runtime,
            "frozen_at": frozen,
            "pre": pre,
            "expected": expected,
            "snapshot": None,
            "phase": "inventoried",
            "writes": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "qualification_mode": inv.get("qualification_mode", "synthetic"),
            "retention_rule": inv.get("retention_rule"),
            "inventory_authority_seal": _digest(_load_json(Path(inv["inventory_path"]))),
            "unrelated_preimage": unrelated_preimage,
        }
        if full_copy:
            receipt["recovery_command"] = _recovery_command(receipt)
        _save_receipt(receipt, initial=True)
    if not full_copy:
        _prepare_isolated_runtime(receipt)
    return receipt


def _sqlite_backup(source: Path, destination: Path) -> None:
    _assert_sqlite_artifacts_safe(source)
    source_connection = sqlite3.connect(str(source))
    destination_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise MigrationError("snapshot_integrity_failed", str(destination))
    finally:
        destination_connection.close()
        source_connection.close()


def _tree_hashes(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        str(component.relative_to(path)): _file_digest(component)
        for component in sorted(path.rglob("*"))
        if not component.is_symlink() and component.is_file()
    }


def _stable_private_tree_hashes(path: Path) -> dict[str, str]:
    """Hash one private regular-file tree and refuse unsafe or concurrent drift."""

    def root_identity(*, missing_allowed: bool = False) -> tuple[int, ...] | None:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if missing_allowed:
                return None
            raise MigrationError(
                "lance_changed_during_hash", "Lance root changed during hashing"
            ) from None
        except OSError as exc:
            raise MigrationError("fixture_path_unavailable", f"cannot inspect: {path}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError("fixture_symlink", f"symlink is forbidden: {path}")
        if not stat.S_ISDIR(metadata.st_mode):
            raise MigrationError("unsafe_component", f"expected private directory: {path}")
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    sealed_root = root_identity(missing_allowed=True)
    if sealed_root is None:
        return {}

    def inventory() -> dict[str, tuple[int, ...]]:
        files: dict[str, tuple[int, ...]] = {}
        pending = [path]
        while pending:
            current = pending.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError as exc:
                raise MigrationError(
                    "fixture_path_unavailable", f"cannot inspect: {current}"
                ) from exc
            for component in entries:
                try:
                    metadata = component.lstat()
                except OSError as exc:
                    raise MigrationError(
                        "fixture_path_unavailable", f"cannot inspect: {component}"
                    ) from exc
                if stat.S_ISLNK(metadata.st_mode):
                    raise MigrationError("fixture_symlink", f"symlink is forbidden: {component}")
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(component)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise MigrationError("unsafe_component", f"not a regular file: {component}")
                if metadata.st_nlink != 1:
                    raise MigrationError("hardlink_forbidden", f"hard-linked file: {component}")
                files[str(component.relative_to(path))] = (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    metadata.st_nlink,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                )
        return files

    before = inventory()
    if root_identity() != sealed_root:
        raise MigrationError("lance_changed_during_hash", "Lance root changed during hashing")
    hashes: dict[str, str] = {}
    for relative, identity in before.items():
        component = path / relative
        hashes[relative] = _file_digest(component)
        metadata = component.lstat()
        after_identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        if after_identity != identity:
            raise MigrationError("lance_changed_during_hash", "Lance file changed during hashing")
    if inventory() != before or root_identity() != sealed_root:
        raise MigrationError("lance_changed_during_hash", "Lance tree changed during hashing")
    return hashes


def _validate_snapshot(receipt: dict[str, Any]) -> None:
    manifest = receipt.get("snapshot")
    if not isinstance(manifest, dict):
        raise MigrationError("snapshot_required", "receipt has no verified snapshot")
    root = Path(manifest["root"])
    if root != Path(receipt["inventory"]["snapshot_root"]) or not root.is_dir():
        raise MigrationError("snapshot_binding_invalid", str(root))
    expected_lance = manifest.get("lance_hashes", {})
    lance = manifest.get("lance")
    if lance and not Path(lance).is_dir():
        raise MigrationError("snapshot_corrupt", "Lance snapshot is unavailable")
    observed_lance = _stable_private_tree_hashes(Path(lance)) if lance else {}
    if observed_lance != expected_lance:
        raise MigrationError("snapshot_corrupt", "Lance snapshot hashes differ")
    for kg in manifest["kg"]:
        if not kg.get("exists") or "alias" in kg:
            continue
        backup = Path(kg["backup"])
        if not backup.is_file() or _file_digest(backup) != kg.get("sha256"):
            raise MigrationError("snapshot_corrupt", f"KG snapshot hash differs: {backup}")
        result = _sqlite_read_connection(backup)
        try:
            if result.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise MigrationError("snapshot_corrupt", f"KG snapshot is invalid: {backup}")
        finally:
            result.close()


def snapshot(receipt_path: str) -> dict:
    receipt = _load_receipt(receipt_path)
    _assert_trial_parent_binding(receipt)
    if receipt.get("qualification_mode") == "full-copy":
        _assert_inventory_binding(receipt, receipt["inventory"]["inventory_path"])
        _assert_full_copy_unrelated_unchanged(receipt)
    if receipt["snapshot"] is not None:
        _validate_snapshot(receipt)
        return receipt
    inv = receipt["inventory"]
    with _fence(inv):
        if _capture(inv) != receipt["pre"]:
            raise MigrationError("preimage_drift", "state changed after inventory")
        target = Path(inv["snapshot_root"])
        if target.exists():
            raise MigrationError("snapshot_exists", f"refusing to replace {target}")
        target.mkdir(parents=True, mode=0o700)
        palace = Path(inv["palace"])
        lance_source = palace / "lance"
        lance_snapshot = target / "lance"
        if lance_source.exists():
            shutil.copytree(lance_source, lance_snapshot)
        kg_manifest: list[dict[str, Any]] = []
        copied: dict[tuple[int, int], str] = {}
        for index, value in enumerate(inv["kg_candidates"]):
            source = Path(value)
            if not source.exists():
                kg_manifest.append({"path": str(source), "exists": False})
                continue
            identity = (source.stat().st_dev, source.stat().st_ino)
            if identity in copied:
                kg_manifest.append({"path": str(source), "alias": copied[identity]})
                continue
            destination = target / f"kg-{index}.sqlite3"
            _sqlite_backup(source, destination)
            copied[identity] = str(destination)
            kg_manifest.append(
                {
                    "path": str(source),
                    "exists": True,
                    "backup": str(destination),
                    "sha256": _file_digest(destination),
                }
            )
        files = {name: receipt["pre"][name] for name in ("tiny_hashes", "marker", "configuration")}
        manifest = {
            "root": str(target),
            "lance": str(lance_snapshot) if lance_snapshot.exists() else None,
            "lance_hashes": _tree_hashes(lance_snapshot),
            "kg": kg_manifest,
            "files": files,
            "recovery_root": str(target / "recovery-staging"),
        }
        _atomic_json(target / "manifest.json", manifest)
        receipt["snapshot"] = manifest
        receipt["phase"] = "snapshotted"
        _prove_snapshot_restore(receipt)
        _validate_snapshot(receipt)
        _save_receipt(receipt)
        return receipt


def _write_file_state(path: Path, state: dict[str, Any]) -> None:
    if not state["exists"]:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(base64.b64decode(state["bytes"]))
    os.replace(temporary, path)


def _prove_snapshot_restore(receipt: dict[str, Any]) -> None:
    manifest = receipt["snapshot"]
    with tempfile.TemporaryDirectory(dir=receipt["inventory"]["fixture_root"]) as raw:
        root = Path(raw)
        lance = manifest["lance"]
        if lance:
            shutil.copytree(lance, root / "palace" / "lance")
            restored_rows, restored_schema = _read_lance(
                root / "palace",
                compact=receipt["inventory"].get("lance_state_format") == LANCE_STATE_FORMAT,
            )
            if (
                restored_rows != receipt["pre"]["lance_rows"]
                or restored_schema != receipt["pre"]["lance_schema"]
            ):
                raise MigrationError("snapshot_restore_failed", "Lance logical preimage differs")
        for index, kg in enumerate(manifest["kg"]):
            if kg.get("exists"):
                destination = root / f"kg-{index}.sqlite3"
                shutil.copy2(kg["backup"], destination)
                expected = next(
                    row["state"]
                    for row in receipt["pre"]["kg"]
                    if row["path"] == kg["path"] and "state" in row
                )
                if _sqlite_rows(destination) != expected:
                    raise MigrationError("snapshot_restore_failed", kg["path"])


def _component_equal(observed: Any, expected: Any) -> bool:
    return _canonical_bytes(observed) == _canonical_bytes(expected)


def _expanded_expected_state(receipt: dict[str, Any]) -> dict[str, Any]:
    expected = {key: receipt["expected"][key] for key in STATE_KEYS}
    delta = expected["lance_rows"]
    if not isinstance(delta, dict):
        return expected
    if (
        delta.get("format") != LANCE_EXPECTED_FORMAT
        or not isinstance(delta.get("destination_wing"), str)
        or not isinstance(delta.get("updated_ids"), list)
    ):
        raise MigrationError("receipt_lance_state_invalid", "expected Lance delta is malformed")
    updated_ids = delta["updated_ids"]
    if len(updated_ids) != len(set(updated_ids)):
        raise MigrationError("receipt_lance_state_invalid", "expected Lance IDs are duplicated")
    rows = copy.deepcopy(receipt["pre"]["lance_rows"])
    by_id = {row.get("id"): row for row in rows}
    if len(by_id) != len(rows) or any(row_id not in by_id for row_id in updated_ids):
        raise MigrationError("receipt_lance_state_invalid", "expected Lance IDs are invalid")
    for row_id in updated_ids:
        by_id[row_id]["wing"] = delta["destination_wing"]
    expected["lance_rows"] = rows
    return expected


def _classify_observed(receipt: dict[str, Any], observed: dict[str, Any]) -> str:
    pre = receipt["pre"]
    expected = _expanded_expected_state(receipt)
    observed = {key: observed[key] for key in STATE_KEYS}
    if _component_equal(observed, pre):
        return "original"
    if _component_equal(observed, expected):
        return "merged"

    partial = True
    before_list = pre["lance_rows"]
    after_list = expected["lance_rows"]
    observed_list = observed["lance_rows"]
    before_ids = [row.get("id") for row in before_list]
    after_ids = [row.get("id") for row in after_list]
    observed_ids = [row.get("id") for row in observed_list]
    if (
        observed["lance_schema"] != pre["lance_schema"]
        or observed["lance_schema"] != expected["lance_schema"]
        or len(observed_list) != len(before_list)
        or len(observed_ids) != len(set(observed_ids))
        or len(before_ids) != len(set(before_ids))
        or before_ids != after_ids
        or set(observed_ids) != set(before_ids)
    ):
        partial = False
    else:
        pre_rows = {row["id"]: row for row in before_list}
        post_rows = {row["id"]: row for row in after_list}
        for row in observed_list:
            row_id = row["id"]
            if not (
                _component_equal(row, pre_rows[row_id]) or _component_equal(row, post_rows[row_id])
            ):
                partial = False
                break
    for key in ("tiny_hashes", "marker", "configuration"):
        if not (
            _component_equal(observed[key], pre[key])
            or _component_equal(observed[key], expected[key])
        ):
            partial = False
    if not _kg_partial(observed["kg"], pre["kg"], expected["kg"]):
        partial = False
    return "partial" if partial else "unknown"


def _substitute_recovery_staging(
    receipt: dict[str, Any], observed: dict[str, Any]
) -> dict[str, Any]:
    """Substitute only receipt-bound removed components with their proven staged state."""
    manifest = receipt.get("snapshot")
    if not isinstance(manifest, dict):
        return observed
    recovery_root = Path(manifest["recovery_root"])
    candidate = copy.deepcopy(observed)
    live_lance = Path(receipt["inventory"]["palace"]) / "lance"
    removed_lance = recovery_root / "removed-palace" / "lance"
    if not live_lance.exists() and removed_lance.exists():
        rows, schema = _read_lance(
            recovery_root / "removed-palace",
            compact=receipt["inventory"].get("lance_state_format") == LANCE_STATE_FORMAT,
        )
        candidate["lance_rows"] = rows
        candidate["lance_schema"] = schema

    for index, kg in enumerate(candidate["kg"]):
        if "state" not in kg or kg["state"]["exists"]:
            continue
        removed = recovery_root / f"kg-{index}-removed.sqlite3"
        if removed.exists():
            kg["state"] = _sqlite_rows(removed)
    return candidate


def _classify_receipt(receipt: dict[str, Any]) -> str:
    observed = _capture(receipt["inventory"])
    state = _classify_observed(receipt, observed)
    if state != "unknown":
        return state
    normalized = _normalize_live_runtime_state(receipt, observed)
    if normalized is not None and _classify_observed(receipt, normalized) != "unknown":
        return "partial"
    staged = _substitute_recovery_staging(receipt, observed)
    if staged != observed and _classify_observed(receipt, staged) in {
        "original",
        "partial",
        "merged",
    }:
        return "partial"
    normalized_staged = _normalize_live_runtime_state(receipt, staged)
    if (
        staged != observed
        and normalized_staged is not None
        and _classify_observed(receipt, normalized_staged) != "unknown"
    ):
        return "partial"
    return "unknown"


def _normalize_live_runtime_state(
    receipt: dict[str, Any], observed: dict[str, Any]
) -> dict[str, Any] | None:
    if receipt.get("qualification_mode") != "live" or receipt.get("phase") != "marker":
        return None
    expected = _expanded_expected_state(receipt)
    normalized = copy.deepcopy(observed)
    changed = False
    if not (
        _component_equal(observed["tiny_hashes"], receipt["pre"]["tiny_hashes"])
        or _component_equal(observed["tiny_hashes"], expected["tiny_hashes"])
    ):
        probe = copy.deepcopy(expected)
        probe["tiny_hashes"] = observed["tiny_hashes"]
        if _runtime_delta_allowed(expected, probe, receipt):
            return None
        normalized["tiny_hashes"] = expected["tiny_hashes"]
        changed = True
    for index, candidate in enumerate(observed["kg"]):
        if _component_equal(candidate, receipt["pre"]["kg"][index]) or _component_equal(
            candidate, expected["kg"][index]
        ):
            continue
        probe = copy.deepcopy(expected)
        probe["kg"][index] = candidate
        if _runtime_delta_allowed(expected, probe, receipt):
            return None
        normalized["kg"][index] = expected["kg"][index]
        changed = True
    return normalized if changed else None


def classify(receipt_path: str) -> str:
    receipt = _load_receipt(receipt_path)
    _assert_trial_parent_binding(receipt)
    with _fence(receipt["inventory"]):
        return _classify_receipt(receipt)


def _kg_partial(observed: list[dict], pre: list[dict], expected: list[dict]) -> bool:
    if len(observed) != len(pre) or len(pre) != len(expected):
        return False
    for current, before, after in zip(observed, pre, expected, strict=True):
        if "alias_of" in current:
            if current != before or current != after:
                return False
            continue
        if not (
            _component_equal(current["state"], before["state"])
            or _component_equal(current["state"], after["state"])
        ):
            return False
    return True


def _lance_update(
    inventory: dict[str, Any], receipt: dict[str, Any], stop_after: str | None
) -> int:
    source_ids = [
        row["id"]
        for row in receipt["pre"]["lance_rows"]
        if row.get("wing") == inventory["source_wing"]
    ]
    if not source_ids:
        return 0
    import lancedb

    table = lancedb.connect(str(Path(inventory["palace"]) / "lance")).open_table(TABLE_NAME)
    writes = 0
    batch_size = max(1, int(inventory.get("lance_batch_size", 2)))
    for batch_number, start in enumerate(range(0, len(source_ids), batch_size), 1):
        batch = source_ids[start : start + batch_size]
        quoted = ",".join("'" + str(row_id).replace("'", "''") + "'" for row_id in batch)
        table.update(where=f"id IN ({quoted})", values={"wing": inventory["destination_wing"]})
        writes += len(batch)
        _inject(stop_after, f"lance:{batch_number}:data")
        receipt["phase"] = f"lance:{batch_number}"
        receipt["writes"] += len(batch)
        _save_receipt(receipt)
        _inject(stop_after, receipt["phase"])
    return writes


def _apply_kg(receipt: dict[str, Any], stop_after: str | None) -> int:
    writes = 0
    expected_by_path = {row["path"]: row for row in receipt["expected"]["kg"] if "state" in row}
    for index, candidate in enumerate(receipt["pre"]["kg"]):
        if "state" not in candidate or not candidate["state"]["exists"]:
            continue
        expected = expected_by_path[candidate["path"]]["state"]
        eligible = receipt["expected"]["kg_eligible"].get(candidate["path"], [])
        if not eligible:
            continue
        destination_id = (
            receipt["inventory"]["destination_wing"].lower().replace(" ", "_").replace("'", "")
        )
        destination_entity = next(
            entity for entity in expected["entities"] if entity["id"] == destination_id
        )
        expected_triples = {row["id"]: row for row in expected["triples"]}
        connection = sqlite3.connect(candidate["path"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO entities(id,name,type,properties,created_at) VALUES(?,?,?,?,?)",
                tuple(
                    destination_entity[key]
                    for key in ("id", "name", "type", "properties", "created_at")
                ),
            )
            for triple_id in eligible:
                triple = expected_triples[triple_id]
                connection.execute(
                    "UPDATE triples SET object=?,source_file=? WHERE id=?",
                    (triple["object"], triple["source_file"], triple_id),
                )
            connection.commit()
        finally:
            connection.close()
        writes += len(eligible)
        _inject(stop_after, f"kg:{index}:data")
        receipt["phase"] = f"kg:{index}"
        receipt["writes"] += len(eligible)
        _save_receipt(receipt)
        _inject(stop_after, receipt["phase"])
    return writes


def _inject(requested: str | None, stage: str) -> None:
    if requested == stage:
        raise InjectedStop("injected_stop", stage)


def _assert_inventory_binding(receipt: dict[str, Any], inventory_path: str | None) -> None:
    if receipt.get("qualification_mode") == "full-copy":
        if inventory_path is None:
            raise MigrationError(
                "inventory_binding_required", "full-copy action requires its authority file"
            )
        path = _real(inventory_path)
        if path != Path(receipt["inventory"]["inventory_path"]):
            raise MigrationError("inventory_binding_invalid", "inventory path differs")
        _assert_regular_private(path)
        if not _private_mode_is_0600(path):
            raise MigrationError("inventory_permissions_invalid", "inventory mode must be 0600")
        if _digest(_load_json(path)) != receipt.get("inventory_authority_seal"):
            raise MigrationError("inventory_binding_invalid", "inventory authority differs")
        return
    if inventory_path is None:
        return
    observed = _load_inventory(inventory_path)
    if observed != receipt["inventory"]:
        raise MigrationError("inventory_binding_invalid", "inventory differs from sealed receipt")


def _assert_sealed_configuration(receipt: dict[str, Any]) -> None:
    observed = _file_state(Path(receipt["inventory"]["configuration"]))
    if not _component_equal(observed, receipt["pre"]["configuration"]):
        raise MigrationError("configuration_drift", "configuration differs from sealed preimage")


def _assert_pre_marker_postimage(receipt: dict[str, Any]) -> None:
    observed = _capture(receipt["inventory"])
    expected = _expanded_expected_state(receipt)
    expected["marker"] = receipt["pre"]["marker"]
    if not _component_equal(observed, expected):
        raise MigrationError(
            "data_postcondition_failed",
            "data stores differ from the sealed postimage before marker activation",
        )


def _discard_incomplete_trial(receipt: dict[str, Any]) -> None:
    inventory = receipt["inventory"]
    for directory in (Path(inventory["palace"]), Path(inventory["project_root"])):
        if not directory.is_dir() or directory.is_symlink():
            continue
        for child in directory.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    for value in inventory["kg_candidates"]:
        path = Path(value)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            if candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
    configuration = Path(inventory["configuration"])
    if configuration.is_file() and not configuration.is_symlink():
        configuration.unlink()


def apply(
    receipt_path: str, *, inventory_path: str | None = None, stop_after: str | None = None
) -> dict[str, Any]:
    receipt = _load_receipt(receipt_path)
    with _trial_parent_protection(receipt):
        return _apply_receipt(receipt_path, inventory_path=inventory_path, stop_after=stop_after)


def _apply_receipt(
    receipt_path: str, *, inventory_path: str | None = None, stop_after: str | None = None
) -> dict[str, Any]:
    receipt = _load_receipt(receipt_path)
    _assert_inventory_binding(receipt, inventory_path)
    _validate_snapshot(receipt)
    inv = receipt["inventory"]
    with _fence(inv):
        _assert_trial_parent_binding(receipt)
        _assert_full_copy_unrelated_unchanged(receipt)
        _assert_sealed_configuration(receipt)
        state = _classify_receipt(receipt)
        if state == "merged":
            _clear_live_maintenance(receipt)
            return {"state": "merged", "writes": 0, "retry": True}
        if state != "original":
            raise MigrationError(
                f"apply_{state}_refused",
                f"run {_recovery_command(receipt)}",
            )
        _validate_runtime(receipt)
        _lance_update(inv, receipt, stop_after)
        _apply_kg(receipt, stop_after)
        _write_file_state(Path(inv["tiny_hashes"]), receipt["expected"]["tiny_hashes"])
        _inject(stop_after, "tiny_hashes:data")
        receipt["phase"] = "tiny_hashes"
        receipt["writes"] += 1
        _save_receipt(receipt)
        _inject(stop_after, "tiny_hashes")
        _assert_pre_marker_postimage(receipt)
        runtime_proof = _runtime_probe(receipt)
        _validate_runtime_measurements(runtime_proof.get("measurements"))
        _assert_sealed_configuration(receipt)
        _assert_pre_marker_postimage(receipt)
        receipt["runtime_proof"] = runtime_proof
        receipt["phase"] = "runtime_proved"
        _save_receipt(receipt)
        _inject(stop_after, "runtime_proved")
        _assert_model_cache_unchanged(receipt)
        _write_file_state(Path(inv["marker"]), receipt["expected"]["marker"])
        _inject(stop_after, "marker:data")
        receipt["phase"] = "marker"
        receipt["writes"] += 1
        _save_receipt(receipt)
        _inject(stop_after, "marker")
        observed = _capture(inv)
        expected = _expanded_expected_state(receipt)
        if observed != expected:
            raise MigrationError("postcondition_failed", "observed state differs from sealed union")
        if receipt.get("qualification_mode") == "live":
            before_runtime = observed
            receipt["phase"] = "runtime_activating"
            _save_receipt(receipt)
            receipt["runtime_proof"]["post_activation"] = _runtime_live_noop(receipt)
            after_runtime = _capture(inv)
            reasons = _runtime_delta_allowed(before_runtime, after_runtime, receipt)
            if reasons:
                raise MigrationError(
                    "runtime_probe_mutated_state",
                    "installed incremental mine changed state outside the architecture refresh envelope: "
                    + "; ".join(reasons),
                )
            receipt["expected"]["tiny_hashes"] = after_runtime["tiny_hashes"]
            receipt["expected"]["kg"] = after_runtime["kg"]
            expected = _expanded_expected_state(receipt)
            if after_runtime != expected:
                raise MigrationError("runtime_probe_mutated_state", "live postimage seal failed")
        receipt["phase"] = "merged"
        _save_receipt(receipt)
        _clear_live_maintenance(receipt)
        return {"state": "merged", "writes": receipt["writes"], "retry": False}


def recover(
    receipt_path: str, *, inventory_path: str | None = None, stop_after: str | None = None
) -> dict[str, Any]:
    receipt = _load_receipt(receipt_path)
    with _trial_parent_protection(receipt):
        return _recover_receipt(receipt_path, inventory_path=inventory_path, stop_after=stop_after)


def _recover_receipt(
    receipt_path: str, *, inventory_path: str | None = None, stop_after: str | None = None
) -> dict[str, Any]:
    receipt = _load_receipt(receipt_path)
    _assert_inventory_binding(receipt, inventory_path)
    inv = receipt["inventory"]
    no_snapshot_live = (
        receipt.get("qualification_mode") == "live" and receipt.get("snapshot") is None
    )
    if no_snapshot_live:
        with _fence(inv, live_phases=frozenset({"receipt", "recovering"})):
            if _capture(inv) != receipt["pre"]:
                raise MigrationError(
                    "live_unsnapshotted_state_drift",
                    "live state differs from the sealed zero-write preimage",
                )
            receipt["phase"] = "recovered"
            _save_receipt(receipt)
            _clear_live_maintenance(receipt)
            return {"state": "original", "restored": False}
    no_snapshot_trial = (
        receipt.get("qualification_mode") == "full-copy-trial" and receipt.get("snapshot") is None
    )
    if inv.get("construction_phase") in {"copying", "recovered"} or no_snapshot_trial:
        with _fence(inv, allow_missing_kg=True):
            _assert_trial_parent_binding(receipt)
            if inv.get("construction_phase") != "recovered":
                _discard_incomplete_trial(receipt)
                inv["construction_phase"] = "recovered"
                receipt["phase"] = "recovered"
                _save_receipt(receipt)
                return {"state": "original", "restored": True}
            return {"state": "original", "restored": False}
    _validate_snapshot(receipt)
    manifest = receipt["snapshot"]
    with _fence(
        inv,
        allow_missing_kg=True,
        live_phases=frozenset({"receipt", "recovering"}),
    ):
        _assert_trial_parent_binding(receipt)
        _assert_full_copy_unrelated_unchanged(receipt)
        _assert_sealed_configuration(receipt)
        state = _classify_receipt(receipt)
        recovery_root = Path(manifest["recovery_root"])
        if state == "original" and not recovery_root.exists():
            _clear_live_maintenance(receipt)
            return {"state": "original", "restored": False}
        if state == "unknown":
            observed = _capture(inv)
            if not _live_runtime_recovery_owned(receipt, observed):
                raise MigrationError(
                    "unknown_state_refused", "state is outside the sealed transition envelope"
                )
            state = "partial"
        recovery_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        palace = Path(inv["palace"])
        live_lance = palace / "lance"
        snapshot_lance = manifest["lance"]
        removed_palace = recovery_root / "removed-palace"
        removed_lance = removed_palace / "lance"
        install_palace = recovery_root / "install-palace"
        install_lance = install_palace / "lance"
        live_rows, live_schema = _read_lance(
            palace,
            compact=receipt["inventory"].get("lance_state_format") == LANCE_STATE_FORMAT,
        )
        lance_is_preimage = (
            live_rows == receipt["pre"]["lance_rows"]
            and live_schema == receipt["pre"]["lance_schema"]
        )
        if not lance_is_preimage:
            if snapshot_lance and not install_lance.exists():
                install_palace.mkdir(parents=True, exist_ok=True)
                shutil.copytree(snapshot_lance, install_lance)
                if _tree_hashes(install_lance) != manifest["lance_hashes"]:
                    raise MigrationError("snapshot_corrupt", "Lance recovery staging differs")
            if live_lance.exists() and not removed_lance.exists():
                removed_palace.mkdir(parents=True, exist_ok=True)
                os.replace(live_lance, removed_lance)
                _inject(stop_after, "recover:lance:removed")
            if snapshot_lance and not live_lance.exists():
                live_lance.parent.mkdir(parents=True, exist_ok=True)
                os.replace(install_lance, live_lance)
                _inject(stop_after, "recover:lance:installed")
            elif not snapshot_lance and live_lance.exists():
                raise MigrationError("recovery_failed", "unexpected Lance preimage")
        _inject(stop_after, "recover:lance")
        for index, kg in enumerate(manifest["kg"]):
            if "alias" in kg:
                continue
            destination = Path(kg["path"])
            if kg["exists"]:
                expected_state = receipt["pre"]["kg"][index]["state"]
                if _sqlite_rows(destination) != expected_state:
                    removed = recovery_root / f"kg-{index}-removed.sqlite3"
                    if destination.exists() and not removed.exists():
                        _sqlite_backup(destination, removed)
                        _inject(stop_after, f"recover:kg:{index}:backup")
                    if destination.exists():
                        for suffix in ("", "-wal", "-shm"):
                            candidate = Path(str(destination) + suffix)
                            if candidate.exists():
                                candidate.unlink()
                        _inject(stop_after, f"recover:kg:{index}:removed")
                    if not destination.exists():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        temporary = recovery_root / f"kg-{index}-install.sqlite3"
                        _sqlite_backup(Path(kg["backup"]), temporary)
                        os.replace(temporary, destination)
                        _inject(stop_after, f"recover:kg:{index}:installed")
            else:
                for suffix in ("", "-wal", "-shm"):
                    candidate = Path(str(destination) + suffix)
                    if candidate.exists():
                        candidate.unlink()
            _inject(stop_after, f"recover:kg:{index}")
        _write_file_state(Path(inv["tiny_hashes"]), receipt["pre"]["tiny_hashes"])
        _inject(stop_after, "recover:tiny_hashes")
        _write_file_state(Path(inv["marker"]), receipt["pre"]["marker"])
        _inject(stop_after, "recover:marker")
        if _capture(inv) != receipt["pre"]:
            raise MigrationError(
                "recovery_failed", "restored state differs from canonical preimage"
            )
        if snapshot_lance and _tree_hashes(live_lance) != manifest["lance_hashes"]:
            raise MigrationError("recovery_failed", "restored Lance bytes differ from snapshot")
        receipt["phase"] = "recovered"
        _save_receipt(receipt)
        shutil.rmtree(recovery_root)
        _clear_live_maintenance(receipt)
        return {"state": "original", "restored": True}


def _runtime_identity() -> dict[str, Any]:
    repo_root = RUNNER_PATH.parent.parent
    prefix = Path(sys.prefix).absolute()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        distribution = importlib.metadata.distribution("mempalace-code")
        distribution_version = distribution.version
    except importlib.metadata.PackageNotFoundError as exc:
        raise MigrationError(
            "installed_runtime_required", "mempalace-code is not installed"
        ) from exc
    metadata_file = next(
        (
            entry
            for entry in distribution.files or ()
            if entry.name == "METADATA" and entry.parent.name.endswith(".dist-info")
        ),
        None,
    )
    if metadata_file is None:
        raise MigrationError(
            "runtime_provenance_invalid", "installed distribution metadata is unavailable"
        )
    package_spec = importlib.util.find_spec("mempalace_code")
    if package_spec is None or package_spec.origin is None:
        raise MigrationError(
            "runtime_provenance_invalid", "installed package origin is unavailable"
        )
    module_origin = _real(package_spec.origin)
    distribution_origin = _real(Path(str(distribution.locate_file(metadata_file))).parent)
    if _inside(module_origin, prefix):
        module_root = prefix
    elif _inside(module_origin, repo_root):
        module_root = repo_root
    else:
        raise MigrationError(
            "runtime_provenance_invalid", "package origin is outside its runtime owner"
        )
    if not _inside(distribution_origin, prefix):
        raise MigrationError(
            "runtime_provenance_invalid", "distribution metadata is outside the runtime prefix"
        )
    _reject_symlink_chain(module_origin, module_root)
    _reject_symlink_chain(distribution_origin, prefix)
    model_cache_source_home = _model_cache_home()
    return {
        # Preserve the virtual-environment launcher. Resolving its symlink would select
        # the base interpreter and lose the installed distribution being qualified.
        "interpreter": str(Path(sys.executable).absolute()),
        "module_origin": str(module_origin),
        "distribution_origin": str(distribution_origin),
        "distribution_version": distribution_version,
        "model_cache_source_home": str(model_cache_source_home),
        "model_cache_source_seal": _seal_model_cache(model_cache_source_home),
        "isolated_non_editable": False,
    }


def _installed_runtime_identity() -> dict[str, Any]:
    """Seal the installed, non-editable package selected for a live operation."""
    identity = _runtime_identity()
    module_origin = Path(identity["module_origin"])
    distribution_origin = Path(identity["distribution_origin"])
    prefix = Path(sys.prefix).absolute()
    if not _inside(module_origin, prefix) or not _inside(distribution_origin, prefix):
        raise MigrationError("runtime_provenance_invalid", "live package is editable")
    identity.update(
        {
            "runtime_prefix": str(prefix),
            "isolated_non_editable": True,
            "package_hashes": _hash_regular_tree(module_origin.parent),
            "distribution_hashes": _hash_regular_tree(distribution_origin),
            "model_cache_home": identity["model_cache_source_home"],
            "model_cache_seal": identity["model_cache_source_seal"],
            "runner_sha256": _file_digest(RUNNER_PATH),
        }
    )
    interpreter = Path(identity["interpreter"])
    if interpreter.is_symlink():
        target = interpreter.resolve(strict=True)
        identity["interpreter_link"] = {
            "value": os.readlink(interpreter),
            "target": str(target),
            "target_sha256": _file_digest(target),
        }
    return identity


def _model_cache_home() -> Path:
    if os.environ.get("HF_HOME"):
        return _real(os.environ["HF_HOME"])
    candidates = []
    candidates.append(Path.home() / ".cache" / "huggingface")
    try:
        import pwd

        candidates.append(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache" / "huggingface")
    except (ImportError, KeyError):
        pass
    for candidate in candidates:
        resolved = _real(candidate)
        if (resolved / "mempalace-fastembed").is_dir():
            return resolved
    return _real(candidates[0])


def _prepared_model_cache_root(cache_home: Path) -> Path:
    root = cache_home / MODEL_CACHE_RELATIVE
    try:
        from mempalace_code.storage import _require_owned_canonical_fastembed_cache

        return _require_owned_canonical_fastembed_cache(root)
    except (OSError, RuntimeError) as exc:
        raise MigrationError(
            "prepared_model_cache_required",
            f"required model cache is absent or invalid: {root}; "
            f"run `HF_HOME={cache_home} mempalace-code fetch-model` while online",
        ) from exc


def _seal_model_cache(cache_home: Path) -> dict[str, Any]:
    _prepared_model_cache_root(cache_home)
    return _seal_model_cache_files(cache_home)


def _seal_model_cache_files(cache_home: Path) -> dict[str, Any]:
    root = cache_home / MODEL_CACHE_RELATIVE
    if not root.is_dir() or root.is_symlink():
        raise MigrationError("prepared_model_cache_required", "authorized model cache is absent")
    entries: dict[str, dict[str, Any]] = {}
    try:
        paths = [root, *sorted(root.rglob("*"))]
        for path in paths:
            metadata = path.lstat()
            relative = "." if path == root else str(path.relative_to(root))
            entry: dict[str, Any] = {
                "device": metadata.st_dev,
                "mode": metadata.st_mode,
                "links": metadata.st_nlink,
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "size": metadata.st_size,
            }
            if stat.S_ISREG(metadata.st_mode):
                entry["sha256"] = _file_digest(path)
            elif stat.S_ISLNK(metadata.st_mode):
                entry["target"] = os.readlink(path)
            entries[relative] = entry
    except OSError as exc:
        raise MigrationError("model_cache_seal_failed", str(root)) from exc
    return {"root": str(root), "entries": entries}


def _materialize_model_cache(source_home: Path, target_home: Path) -> Path:
    """Copy the validated canonical cache into fixture-owned storage."""
    source_root = _prepared_model_cache_root(source_home)
    source_seal = _seal_model_cache(source_home)
    target_root = target_home / MODEL_CACHE_RELATIVE
    if target_home.exists() or target_root.exists():
        raise MigrationError("model_cache_target_exists", str(target_home))
    try:
        _reject_external_symlink_targets(source_root)
        target_root.parent.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source_root, target_root, symlinks=False)
        _prepared_model_cache_root(target_home)
        if _seal_model_cache(source_home) != source_seal:
            raise MigrationError(
                "model_cache_source_drift",
                "external model cache changed while the fixture copy was created",
            )
    except Exception:
        shutil.rmtree(target_home, ignore_errors=True)
        raise
    return target_home


def _assert_model_cache_unchanged(receipt: dict[str, Any]) -> None:
    runtime = receipt["runtime"]
    source_observed = _seal_model_cache(Path(runtime["model_cache_source_home"]))
    if source_observed != runtime.get("model_cache_source_seal"):
        raise MigrationError(
            "model_cache_source_drift",
            "external model cache bytes or metadata changed",
        )
    cache_home = runtime.get("model_cache_home")
    if cache_home is not None:
        observed = _seal_model_cache(Path(cache_home))
        if observed != runtime.get("model_cache_seal"):
            raise MigrationError(
                "model_cache_drift",
                "fixture model cache bytes or metadata changed",
            )


def _hash_regular_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _file_digest(path)
        for path in sorted(root.rglob("*"))
        if not path.is_symlink() and path.is_file() and "__pycache__" not in path.parts
    }


def _runtime_environment(receipt: dict[str, Any], home: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["HOME"] = str(home)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["HF_HOME"] = receipt["runtime"]["model_cache_home"]
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    return environment


def _assert_runtime_files_unchanged(receipt: dict[str, Any]) -> None:
    runtime = receipt["runtime"]
    interpreter = _real(runtime["interpreter"])
    prefix = _real(runtime["runtime_prefix"])
    module_origin = _real(runtime["module_origin"])
    distribution_root = _real(runtime["distribution_origin"])
    if not _inside(module_origin, prefix) or not _inside(distribution_root, prefix):
        raise MigrationError("runtime_provenance_drift", "installed package left runtime prefix")
    _reject_symlink_chain(prefix, prefix)
    _reject_symlink_chain(module_origin, prefix)
    _reject_symlink_chain(distribution_root, prefix)
    try:
        interpreter_metadata = interpreter.lstat()
    except OSError as exc:
        raise MigrationError("runtime_package_hash_drift", str(interpreter)) from exc
    interpreter_link = runtime.get("interpreter_link")
    interpreter_root = prefix if _inside(interpreter, prefix) else Path(interpreter.anchor)
    if interpreter_link is None:
        _reject_symlink_chain(interpreter, interpreter_root)
        if not stat.S_ISREG(interpreter_metadata.st_mode):
            raise MigrationError("runtime_package_hash_drift", str(interpreter))
    else:
        _reject_symlink_chain(interpreter.parent, interpreter_root)
        if (
            not isinstance(interpreter_link, dict)
            or set(interpreter_link) != {"value", "target", "target_sha256"}
            or not stat.S_ISLNK(interpreter_metadata.st_mode)
            or os.readlink(interpreter) != interpreter_link["value"]
        ):
            raise MigrationError("runtime_package_hash_drift", str(interpreter))
        target = interpreter.resolve(strict=True)
        _reject_symlink_chain(target)
        if (
            str(target) != interpreter_link["target"]
            or not target.is_file()
            or _file_digest(target) != interpreter_link["target_sha256"]
        ):
            raise MigrationError("runtime_package_hash_drift", str(interpreter))
    package_root = module_origin.parent
    _reject_symlink_tree(package_root)
    _reject_symlink_tree(distribution_root)
    if _hash_regular_tree(package_root) != runtime.get("package_hashes"):
        raise MigrationError("runtime_package_hash_drift", str(package_root))
    if _hash_regular_tree(distribution_root) != runtime.get("distribution_hashes"):
        raise MigrationError("runtime_package_hash_drift", str(distribution_root))
    dependency_link_value = runtime.get("dependency_link")
    if dependency_link_value is not None:
        dependency_link = _real(dependency_link_value)
        if not _inside(dependency_link, prefix):
            raise MigrationError("runtime_provenance_drift", "dependency link left runtime prefix")
        _reject_symlink_chain(dependency_link, prefix)
        try:
            _assert_regular_private(dependency_link)
        except OSError as exc:
            raise MigrationError("runtime_package_hash_drift", str(dependency_link)) from exc
        if _file_digest(dependency_link) != runtime.get("dependency_link_hash"):
            raise MigrationError("runtime_package_hash_drift", str(dependency_link))


def _run_runtime_subprocess(
    receipt: dict[str, Any], command: list[str], *, home: Path, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    if receipt.get("runtime", {}).get("isolated_non_editable") is True:
        _assert_runtime_files_unchanged(receipt)
    _assert_model_cache_unchanged(receipt)
    try:
        return subprocess.run(
            command,
            env=_runtime_environment(receipt, home),
            **kwargs,
        )
    finally:
        _assert_model_cache_unchanged(receipt)


def _probe_runtime_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    runtime = receipt["runtime"]
    probe = _run_runtime_subprocess(
        receipt,
        [
            runtime["interpreter"],
            "-B",
            "-I",
            "-c",
            (
                "import importlib.metadata,json,pathlib,sys,mempalace_code;"
                "d=importlib.metadata.distribution('mempalace-code');"
                "m=next(f for f in d.files or () if f.name=='METADATA' "
                "and f.parent.name.endswith('.dist-info'));"
                "print(json.dumps({'interpreter':sys.executable,"
                "'runtime_prefix':sys.prefix,"
                "'module_origin':str(pathlib.Path(mempalace_code.__file__).absolute()),"
                "'distribution_origin':str(pathlib.Path(d.locate_file(m)).parent.absolute()),"
                "'distribution_version':d.version}))"
            ),
        ],
        home=Path(receipt["inventory"]["fixture_root"]) / "home",
        cwd=receipt["inventory"]["fixture_root"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if probe.returncode != 0:
        raise MigrationError("runtime_revalidation_failed", probe.stderr.strip())
    try:
        return json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        raise MigrationError("runtime_revalidation_failed", probe.stdout) from exc


def _validate_runtime(receipt: dict[str, Any]) -> dict[str, Any]:
    runtime = receipt["runtime"]
    if runtime.get("isolated_non_editable") is not True:
        raise MigrationError("runtime_provenance_invalid", "runtime is not sealed non-editable")
    _assert_runtime_files_unchanged(receipt)
    observed = _probe_runtime_identity(receipt)
    for key in (
        "interpreter",
        "runtime_prefix",
        "module_origin",
        "distribution_origin",
        "distribution_version",
    ):
        if observed.get(key) != runtime.get(key):
            raise MigrationError("runtime_provenance_drift", f"{key} changed")
    _assert_runtime_files_unchanged(receipt)
    _assert_model_cache_unchanged(receipt)
    return observed


def _validate_runtime_measurements(measurements: Any) -> None:
    if not isinstance(measurements, dict):
        raise MigrationError("runtime_measurements_invalid", "runtime counts are missing")
    keys = (
        "source_rows_before",
        "destination_rows_before",
        "source_rows_after",
        "destination_rows_after",
        "source_filed_drawers",
        "destination_filed_drawers",
    )
    if any(
        key not in measurements
        or isinstance(measurements[key], bool)
        or not isinstance(measurements[key], int)
        or measurements[key] < 0
        for key in keys
    ):
        raise MigrationError("runtime_measurements_invalid", "runtime counts are invalid")

    source_before = measurements["source_rows_before"]
    destination_before = measurements["destination_rows_before"]
    source_after = measurements["source_rows_after"]
    destination_after = measurements["destination_rows_after"]
    source_filed = measurements["source_filed_drawers"]
    destination_filed = measurements["destination_filed_drawers"]
    destination_delta = destination_after - destination_before - source_before
    if (
        source_before <= 0
        or source_after != 0
        or source_filed <= 0
        or source_filed > source_before
        or destination_delta < 0
        or (destination_filed == 0 and destination_delta != 0)
        or (destination_filed > 0 and destination_delta < destination_filed)
    ):
        raise MigrationError(
            "runtime_measurements_inconsistent", "row and filed-drawer counts disagree"
        )


def _prepare_isolated_runtime(receipt: dict[str, Any]) -> dict[str, Any]:
    """Create a network-free, non-editable package copy for synthetic qualification."""
    runtime_root = Path(receipt["inventory"]["runtime_root"])
    if runtime_root.exists():
        raise MigrationError("runtime_target_exists", str(runtime_root))
    venv.EnvBuilder(with_pip=False, system_site_packages=True, symlinks=False).create(runtime_root)
    source_home = Path(receipt["runtime"]["model_cache_source_home"])
    model_cache_home = _materialize_model_cache(source_home, runtime_root / "hf-home")
    receipt["runtime"]["model_cache_home"] = str(model_cache_home)
    receipt["runtime"]["model_cache_seal"] = _seal_model_cache(model_cache_home)
    _save_receipt(receipt)
    interpreter = runtime_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    purelib_probe = _run_runtime_subprocess(
        receipt,
        [
            str(interpreter),
            "-B",
            "-I",
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ],
        home=Path(receipt["inventory"]["fixture_root"]) / "home",
        cwd=receipt["inventory"]["fixture_root"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if purelib_probe.returncode != 0:
        raise MigrationError("runtime_install_failed", purelib_probe.stderr.strip())
    purelib = _real(purelib_probe.stdout.strip())
    if not _inside(purelib, runtime_root):
        raise MigrationError("runtime_install_failed", f"site-packages escapes runtime: {purelib}")
    _reject_symlink_chain(purelib, runtime_root)
    resolved_runtime_root = runtime_root.resolve()
    purelib = purelib.resolve()
    if not _inside(purelib, resolved_runtime_root):
        raise MigrationError("runtime_install_failed", f"site-packages escapes runtime: {purelib}")
    package_source = RUNNER_PATH.parent.parent / "mempalace_code"
    package_target = purelib / "mempalace_code"
    shutil.copytree(
        package_source,
        package_target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    version = receipt["runtime"]["distribution_version"]
    dist_info = purelib / f"mempalace_code-{version}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: mempalace-code\nVersion: {version}\n",
        encoding="utf-8",
    )
    (dist_info / "INSTALLER").write_text("wing-migration-synthetic\n", encoding="utf-8")
    relative_dist_info = dist_info.relative_to(purelib)
    (dist_info / "RECORD").write_text(
        "\n".join(f"{relative_dist_info / name},," for name in ("INSTALLER", "METADATA", "RECORD"))
        + "\n",
        encoding="utf-8",
    )
    dependency_link = purelib / "wing_migration_dependencies.pth"
    dependency_source = _real(sysconfig.get_path("purelib"))
    source_prefix = Path(sys.prefix).absolute()
    if not _inside(dependency_source, source_prefix):
        raise MigrationError(
            "runtime_provenance_invalid", "dependency source is outside the runtime prefix"
        )
    _reject_symlink_chain(dependency_source, source_prefix)
    dependency_link.write_text(f"{dependency_source}\n", encoding="utf-8")
    identity_probe = _run_runtime_subprocess(
        receipt,
        [
            str(interpreter),
            "-B",
            "-I",
            "-c",
            (
                "import importlib.metadata,json,mempalace_code;"
                "import sys;from pathlib import Path;"
                "d=importlib.metadata.distribution('mempalace-code');"
                "m=next(f for f in d.files or () if f.name=='METADATA' "
                "and f.parent.name.endswith('.dist-info'));"
                "print(json.dumps({'module_origin':str(Path(mempalace_code.__file__).absolute()),"
                "'distribution_origin':str(Path(d.locate_file(m)).parent.absolute()),"
                "'distribution_version':d.version,'runtime_prefix':sys.prefix}))"
            ),
        ],
        home=Path(receipt["inventory"]["fixture_root"]) / "home",
        cwd=receipt["inventory"]["fixture_root"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if identity_probe.returncode != 0:
        raise MigrationError("runtime_install_failed", identity_probe.stderr.strip())
    try:
        identity = json.loads(identity_probe.stdout)
    except json.JSONDecodeError as exc:
        raise MigrationError("runtime_install_failed", identity_probe.stdout) from exc
    origin = _real(identity["module_origin"])
    _reject_symlink_chain(origin, resolved_runtime_root)
    if not _inside(origin, resolved_runtime_root) or identity["distribution_version"] != version:
        raise MigrationError("runtime_provenance_invalid", json.dumps(identity, sort_keys=True))
    identity.update(
        {
            "interpreter": str(interpreter),
            "isolated_non_editable": True,
            "package_hashes": _hash_regular_tree(package_target),
            "distribution_hashes": _hash_regular_tree(dist_info),
            "dependency_link": str(dependency_link),
            "dependency_link_hash": _file_digest(dependency_link),
            "model_cache_home": receipt["runtime"]["model_cache_home"],
            "model_cache_seal": receipt["runtime"]["model_cache_seal"],
            "model_cache_source_home": receipt["runtime"]["model_cache_source_home"],
            "model_cache_source_seal": receipt["runtime"]["model_cache_source_seal"],
        }
    )
    receipt["runtime"] = identity
    _save_receipt(receipt)
    _validate_runtime(receipt)
    return identity


def _runtime_probe(receipt: dict[str, Any]) -> dict[str, Any]:
    inv = receipt["inventory"]
    _validate_runtime(receipt)
    destination = inv["destination_wing"]
    source = inv["source_wing"]
    with tempfile.TemporaryDirectory(dir=inv["evidence_root"]) as raw:
        root = Path(raw)
        project = root / "project"
        palace = root / "palace"
        home = root / "home"
        project.mkdir()
        _write_file_state(project / Path(inv["marker"]).name, receipt["pre"]["marker"])
        (project / "runtime_probe.py").write_text(
            "def mempalace_runtime_probe():\n    return 'bounded fixture'\n" * 8,
            encoding="utf-8",
        )
        _write_file_state(home / ".mempalace" / "config.json", receipt["pre"]["configuration"])
        command = [
            receipt["runtime"]["interpreter"],
            "-B",
            "-I",
            "-m",
            "mempalace_code.cli",
            "--palace",
            str(palace),
            "mine",
            str(project),
        ]
        mine_timeout = (
            FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS
            if receipt.get("qualification_mode") in {"full-copy", "full-copy-trial", "live"}
            else SYNTHETIC_RUNTIME_MINE_TIMEOUT_SECONDS
        )
        # Full-copy verification materializes large typed states before this probe.
        # Release unreachable Python and Arrow objects before the mine subprocess
        # competes with the long-lived qualifier for memory.
        gc.collect()
        try:
            baseline = _run_runtime_subprocess(
                receipt,
                command,
                home=home,
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                timeout=mine_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise MigrationError(
                "runtime_source_baseline_timeout", "source baseline exceeded its bounded timeout"
            ) from exc
        source_reported = f"Wing:    {source}" in baseline.stdout
        if baseline.returncode != 0 or not source_reported:
            detail = json.dumps(
                {
                    "expected_wing_reported": source_reported,
                    "returncode": baseline.returncode,
                    "stderr_tail": baseline.stderr[-8192:],
                    "stdout_tail": baseline.stdout[-8192:],
                },
                sort_keys=True,
            )
            raise MigrationError("runtime_source_baseline_failed", detail)
        import lancedb

        table = lancedb.connect(str(palace / "lance")).open_table(TABLE_NAME)
        quoted_source = source.replace("'", "''")
        quoted_destination = destination.replace("'", "''")
        source_rows_before = table.count_rows(f"wing = '{quoted_source}'")
        destination_rows_before = table.count_rows(f"wing = '{quoted_destination}'")
        if source_rows_before <= 0:
            raise MigrationError(
                "runtime_source_baseline_failed", "real mine produced no source rows"
            )
        table.update(
            where=f"wing = '{quoted_source}'",
            values={"wing": destination},
        )
        tiny_path = palace / ".mempalace" / "tiny_hashes.json"
        _write_file_state(
            tiny_path,
            _migrate_tiny_hashes(_file_state(tiny_path), source, destination),
        )
        _write_file_state(
            project / Path(inv["marker"]).name,
            receipt["expected"]["marker"],
        )
        resolver = _run_runtime_subprocess(
            receipt,
            [
                receipt["runtime"]["interpreter"],
                "-B",
                "-I",
                "-c",
                (
                    "import sys;from mempalace_code.mining.projects import "
                    "resolve_wing_for_project;print(resolve_wing_for_project(sys.argv[1]))"
                ),
                str(project),
            ],
            home=home,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        baseline_filed = re.search(r"Drawers filed:\s*(\d+)", baseline.stdout)
        source_filed_drawers = int(baseline_filed.group(1)) if baseline_filed else None
        del baseline, baseline_filed
        gc.collect()
        try:
            result = _run_runtime_subprocess(
                receipt,
                command,
                home=home,
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                timeout=mine_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise MigrationError(
                "runtime_destination_probe_timeout",
                "destination probe exceeded its bounded timeout",
            ) from exc
        if result.returncode != 0:
            detail = "\n".join(
                part for part in (result.stdout.strip(), result.stderr.strip()) if part
            )
            raise MigrationError("runtime_probe_failed", detail)
        table = lancedb.connect(str(palace / "lance")).open_table(TABLE_NAME)
        source_rows_after = table.count_rows(f"wing = '{quoted_source}'")
        destination_rows_after = table.count_rows(f"wing = '{quoted_destination}'")
    destination_filed = re.search(r"Drawers filed:\s*(\d+)", result.stdout)
    measurements = {
        "source_rows_before": source_rows_before,
        "destination_rows_before": destination_rows_before,
        "source_rows_after": source_rows_after,
        "destination_rows_after": destination_rows_after,
        "source_filed_drawers": source_filed_drawers,
        "destination_filed_drawers": (
            int(destination_filed.group(1)) if destination_filed else None
        ),
    }
    try:
        _validate_runtime_measurements(measurements)
    except MigrationError:
        measurements_consistent = False
    else:
        measurements_consistent = True
    synthetic_noop = receipt.get("qualification_mode") == "synthetic"
    predicates = {
        "source_baseline_real_mine": True,
        "resolver_destination": resolver.returncode == 0 and resolver.stdout.strip() == destination,
        "destination_reported": f"Wing:    {destination}" in result.stdout,
        "zero_drawer_writes": "Drawers filed: 0" in result.stdout,
        "incremental_noop": "Drawers filed: 0" in result.stdout,
        "measurements_consistent": measurements_consistent,
    }
    required_predicates = {
        key: value
        for key, value in predicates.items()
        if synthetic_noop or key not in {"zero_drawer_writes", "incremental_noop"}
    }
    if not all(required_predicates.values()):
        raise MigrationError("runtime_probe_failed", json.dumps(predicates, sort_keys=True))
    _validate_runtime(receipt)
    return {
        "command": command,
        "predicates": predicates,
        "measurements": measurements,
        "identity": receipt["runtime"],
    }


def _runtime_live_noop(receipt: dict[str, Any]) -> dict[str, Any]:
    _validate_runtime(receipt)
    inv = receipt["inventory"]
    command = [
        receipt["runtime"]["interpreter"],
        "-B",
        "-I",
        "-m",
        "mempalace_code.cli",
        "--palace",
        inv["palace"],
        "mine",
        inv["project_root"],
    ]
    result = _run_runtime_subprocess(
        receipt,
        command,
        home=(
            Path.home()
            if receipt.get("qualification_mode") == "live"
            else Path(inv["fixture_root"]) / "home"
        ),
        cwd=inv["fixture_root"],
        text=True,
        capture_output=True,
        check=False,
        timeout=(
            FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS
            if receipt.get("qualification_mode") == "live"
            else SYNTHETIC_RUNTIME_MINE_TIMEOUT_SECONDS
        ),
    )
    predicates = {
        "destination_reported": f"Wing:    {inv['destination_wing']}" in result.stdout,
        "zero_drawer_writes": "Drawers filed: 0" in result.stdout,
    }
    if result.returncode != 0 or not all(predicates.values()):
        detail = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        raise MigrationError(
            "runtime_live_noop_failed", f"{json.dumps(predicates, sort_keys=True)}\n{detail}"
        )
    _validate_runtime(receipt)
    return {"command": command, "predicates": predicates}


def _live_runtime_recovery_owned(receipt: dict[str, Any], observed: dict[str, Any]) -> bool:
    if receipt.get("qualification_mode") != "live" or receipt.get("phase") != "runtime_activating":
        return False
    expected = _expanded_expected_state(receipt)
    if any(
        not _component_equal(observed[key], expected[key])
        for key in ("configuration", "lance_schema", "marker")
    ):
        return False
    try:
        expected_tiny = _decode_json_state(expected["tiny_hashes"], "expected tiny hashes")
        observed_tiny = _decode_json_state(observed["tiny_hashes"], "observed tiny hashes")
    except (KeyError, TypeError, MigrationError):
        return False
    if any(
        not isinstance(value, dict) for value in (*expected_tiny.values(), *observed_tiny.values())
    ):
        return False
    destination = receipt["inventory"]["destination_wing"]
    expected_unrelated_tiny = {
        wing: hashes for wing, hashes in expected_tiny.items() if wing != destination
    }
    observed_unrelated_tiny = {
        wing: hashes for wing, hashes in observed_tiny.items() if wing != destination
    }
    if observed_unrelated_tiny != expected_unrelated_tiny:
        return False
    expected_unrelated = {
        row["id"]: row for row in expected["lance_rows"] if row["wing"] != destination
    }
    observed_unrelated = {
        row["id"]: row for row in observed["lance_rows"] if row["wing"] != destination
    }
    return observed_unrelated == expected_unrelated


def _runtime_delta_allowed(
    before: dict[str, Any], after: dict[str, Any], receipt: dict[str, Any]
) -> list[str]:
    reasons: list[str] = []
    if before["lance_rows"] != after["lance_rows"] or before["marker"] != after["marker"]:
        reasons.append("lance_or_marker")
    if _decode_json_state(before["tiny_hashes"], "before runtime") != _decode_json_state(
        after["tiny_hashes"], "after runtime"
    ):
        before_tiny = _decode_json_state(before["tiny_hashes"], "before runtime")
        after_tiny = _decode_json_state(after["tiny_hashes"], "after runtime")
        summary = {
            "before": {
                wing: {Path(path).name: digest for path, digest in hashes.items()}
                for wing, hashes in before_tiny.items()
            },
            "after": {
                wing: {Path(path).name: digest for path, digest in hashes.items()}
                for wing, hashes in after_tiny.items()
            },
        }
        reasons.append(f"tiny_hash_semantics:{json.dumps(summary, sort_keys=True)}")
    eligible = receipt["expected"]["kg_eligible"]
    for before_candidate, after_candidate in zip(before["kg"], after["kg"], strict=True):
        if "alias_of" in before_candidate:
            if before_candidate != after_candidate:
                reasons.append(f"kg_alias:{before_candidate['path']}")
            continue
        before_state = before_candidate["state"]
        after_state = after_candidate["state"]
        if before_state["entities"] != after_state["entities"]:
            reasons.append(f"kg_entities:{before_candidate['path']}")
        before_triples = {row["id"]: row for row in before_state["triples"]}
        after_triples = {row["id"]: row for row in after_state["triples"]}
        if set(before_triples) != set(after_triples):
            reasons.append(
                f"kg_ids:{before_candidate['path']}:"
                f"{sorted(set(after_triples) - set(before_triples))}"
            )
            continue
        eligible_ids = set(eligible.get(before_candidate["path"], []))
        for triple_id, before_triple in before_triples.items():
            after_triple = after_triples[triple_id]
            if before_triple == after_triple:
                continue
            changed = {key for key in before_triple if before_triple[key] != after_triple[key]}
            if (
                triple_id not in eligible_ids
                or changed != {"valid_to"}
                or before_triple["valid_to"] is not None
                or not after_triple["valid_to"]
            ):
                reasons.append(
                    f"kg_triple:{before_candidate['path']}:{triple_id}:{sorted(changed)}"
                )
    return reasons


def _unrelated_file_hashes(inventory: dict[str, Any]) -> dict[str, str]:
    root = Path(inventory["fixture_root"])
    lock = Path(inventory["lock"])
    directory_exclusions = {
        Path(inventory["evidence_root"]),
        Path(inventory["snapshot_root"]),
        *(Path(value) for value in inventory.get("retained_snapshot_roots", {})),
        Path(inventory["runtime_root"]),
        Path(inventory["palace"]) / "lance",
    }
    file_exclusions = {
        Path(inventory["inventory_path"]) if inventory.get("inventory_path") else root / "__none__",
        lock,
        lock.with_name(f"{lock.name}.owners.json"),
        lock.with_name(f"{lock.name}.metadata.lock"),
        Path(inventory["tiny_hashes"]),
        Path(inventory["marker"]),
        Path(inventory["configuration"]),
    }
    for value in inventory["kg_candidates"]:
        path = Path(value)
        file_exclusions.update((path, Path(f"{path}-wal"), Path(f"{path}-shm")))

    candidates: list[tuple[Path, int]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories if current_path / name not in directory_exclusions
        )
        for name in sorted(files):
            path = current_path / name
            if path in file_exclusions or path.is_symlink() or not path.is_file():
                continue
            candidates.append((path, path.stat().st_size))

    def hash_batch(batch: list[Path]) -> list[tuple[str, str]]:
        return [(str(path.relative_to(root)), _file_digest(path)) for path in batch]

    workers = min(UNRELATED_HASH_WORKERS, max(1, os.cpu_count() or 1))
    batches: list[list[Path]] = [[] for _ in range(workers)]
    batch_sizes = [0] * workers
    for path, size in sorted(candidates, key=lambda item: item[1], reverse=True):
        batch_index = min(range(workers), key=batch_sizes.__getitem__)
        batches[batch_index].append(path)
        batch_sizes[batch_index] += size
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pair for batch in pool.map(hash_batch, batches) for pair in batch)


def _assert_full_copy_restored(receipt: dict[str, Any]) -> None:
    if _capture(receipt["inventory"]) != receipt["pre"]:
        raise MigrationError("full_copy_restore_failed", "logical preimage differs")
    if _digest(_unrelated_file_hashes(receipt["inventory"])) != receipt["unrelated_preimage"]:
        raise MigrationError("full_copy_unrelated_drift", "unrelated copied files differ")


def _assert_full_copy_unrelated_unchanged(receipt: dict[str, Any]) -> None:
    if receipt.get("qualification_mode") not in {"full-copy", "full-copy-trial"}:
        return
    expected = receipt.get("unrelated_preimage")
    if (
        not isinstance(expected, str)
        or _digest(_unrelated_file_hashes(receipt["inventory"])) != expected
    ):
        raise MigrationError("full_copy_unrelated_drift", "unrelated copied files differ")


def _prove_collision_refusal(receipt: dict[str, Any]) -> bool:
    _assert_trial_parent_binding(receipt)
    if _capture(receipt["inventory"]) != receipt["pre"]:
        raise MigrationError("collision_challenge_drift", "challenged descendant changed")
    try:
        _expected_state(receipt["inventory"], receipt["pre"], receipt["frozen_at"])
    except MigrationError as exc:
        if exc.code == "file_identity_collision":
            return True
        raise
    raise MigrationError("collision_challenge_failed", "conflicting copied row was admitted")


def _apply_interruption_stages(receipt: dict[str, Any]) -> list[str]:
    inv = receipt["inventory"]
    source_rows = [
        row for row in receipt["pre"]["lance_rows"] if row.get("wing") == inv["source_wing"]
    ]
    batches = (len(source_rows) + inv["lance_batch_size"] - 1) // inv["lance_batch_size"]
    stages: list[str] = []
    for number in range(1, batches + 1):
        stages.extend((f"lance:{number}:data", f"lance:{number}"))
    for index, candidate in enumerate(receipt["pre"]["kg"]):
        if "state" in candidate and receipt["expected"]["kg_eligible"].get(candidate["path"]):
            stages.extend((f"kg:{index}:data", f"kg:{index}"))
    stages.extend(
        (
            "tiny_hashes:data",
            "tiny_hashes",
            "runtime_proved",
            "marker:data",
            "marker",
        )
    )
    return stages


def _recovery_interruption_stages(receipt: dict[str, Any]) -> list[str]:
    stages = ["recover:lance:removed", "recover:lance:installed", "recover:lance"]
    for index, candidate in enumerate(receipt["pre"]["kg"]):
        if "state" in candidate and receipt["expected"]["kg_eligible"].get(candidate["path"]):
            stages.extend(
                (
                    f"recover:kg:{index}:backup",
                    f"recover:kg:{index}:removed",
                    f"recover:kg:{index}:installed",
                    f"recover:kg:{index}",
                )
            )
    stages.extend(("recover:tiny_hashes", "recover:marker"))
    return stages


def _assert_distinct_regular_tree(
    source: Path, copied: Path, *, excluded: set[Path] | None = None
) -> None:
    excluded = excluded or set()
    for source_file in sorted(source.rglob("*")):
        if source_file.is_symlink() or not source_file.is_file():
            continue
        relative = source_file.relative_to(source)
        if relative in excluded:
            continue
        copied_file = copied / relative
        if copied_file.is_symlink() or not copied_file.is_file():
            raise MigrationError("trial_copy_incomplete", "a copied regular file is absent")
        if _identity_value(source_file) == _identity_value(copied_file):
            raise MigrationError("trial_copy_alias", "a challenge file aliases the baseline")


def _copytree_without_sqlite(source: Path, copied: Path, sqlite_paths: list[Path]) -> None:
    _reject_symlink_tree(source)
    excluded = {
        str(candidate.relative_to(source)) + suffix
        for candidate in sqlite_paths
        if _inside(candidate, source)
        for suffix in ("", "-wal", "-shm")
    }

    if not excluded and _clone_tree_if_supported(source, copied):
        return

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).relative_to(source)
        return {
            name
            for name in names
            if str((relative / name) if relative != Path(".") else Path(name)) in excluded
        }

    shutil.copytree(source, copied, symlinks=True, ignore=ignore, dirs_exist_ok=True)


def _clone_tree_if_supported(source: Path, copied: Path) -> bool:
    """Make an independent APFS copy-on-write tree when the host supports it."""
    if sys.platform != "darwin":
        return False
    completed = subprocess.run(
        ("/bin/cp", "-cR", f"{source}{os.sep}.", str(copied)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _state_without_candidate_paths(state: dict[str, Any]) -> dict[str, Any]:
    value = dict(state)
    value["kg"] = [
        {key: component for key, component in candidate.items() if key != "path"}
        for candidate in state["kg"]
    ]
    return value


def _create_full_copy_trial(
    receipt: dict[str, Any], trial_name: str, *, collision_challenge: bool = False
) -> tuple[Path, dict[str, Any]]:
    baseline = receipt["inventory"]
    with _fence(baseline):
        _assert_baseline_unchanged(receipt)
        _assert_recovery_capacity(baseline)
        return _create_full_copy_trial_under_fence(
            receipt, trial_name, collision_challenge=collision_challenge
        )


def _full_copy_trial_root(receipt: dict[str, Any], trial_name: str) -> Path:
    return (
        Path(receipt["inventory"]["evidence_root"])
        / "trials"
        / f"v{receipt['version']}"
        / trial_name
    )


def _full_copy_trial_receipt_path(receipt: dict[str, Any], trial_name: str) -> Path:
    return _full_copy_trial_root(receipt, trial_name) / "evidence" / "receipt.json"


def _create_full_copy_trial_under_fence(
    receipt: dict[str, Any], trial_name: str, *, collision_challenge: bool = False
) -> tuple[Path, dict[str, Any]]:
    baseline = receipt["inventory"]
    root = _full_copy_trial_root(receipt, trial_name)
    if root.exists():
        raise MigrationError("trial_evidence_exists", "refusing to replace challenge evidence")
    root.mkdir(parents=True, mode=0o700)
    trial_palace = root / "palace"
    trial_project = root / "project"
    trial_palace.mkdir()
    trial_project.mkdir()
    _create_lock_anchors(root / "operation.lock")
    _atomic_json(root / FIXTURE_MARKER, {"disposable": True, "fixture_id": f"trial-{trial_name}"})
    baseline_kg_paths = [Path(value) for value in baseline["kg_candidates"]]
    configuration = root / "configuration.json"

    def relocate(value: str) -> Path | None:
        source = Path(value)
        for old_root, new_root in (
            (Path(baseline["palace"]), trial_palace),
            (Path(baseline["project_root"]), trial_project),
        ):
            try:
                return new_root / source.relative_to(old_root)
            except ValueError:
                continue
        return None

    kg_paths: list[str] = []
    external_copies: dict[tuple[int, int], Path] = {}
    for index, value in enumerate(baseline["kg_candidates"]):
        source = Path(value)
        target = relocate(value)
        identity = (source.stat().st_dev, source.stat().st_ino)
        aliased_target = external_copies.get(identity)
        if aliased_target is not None:
            target = aliased_target
        else:
            if target is None:
                target = root / "kg" / f"candidate-{index}.sqlite3"
            external_copies[identity] = target
        kg_paths.append(str(target))

    trial_inventory = copy.deepcopy(baseline)
    trial_inventory.update(
        {
            "fixture_id": f"trial-{trial_name}",
            "fixture_root": str(root),
            "palace": str(trial_palace),
            "project_root": str(trial_project),
            "marker": str(relocate(baseline["marker"])),
            "tiny_hashes": str(relocate(baseline["tiny_hashes"])),
            "kg_candidates": kg_paths,
            "lock": str(root / "operation.lock"),
            "snapshot_root": str(root / "snapshot"),
            "retained_snapshot_roots": {},
            "runtime_root": str(root / "runtime"),
            "evidence_root": str(root / "evidence"),
            "configuration": str(configuration),
            "fixture_root_identity": _path_identity(root),
            "qualification_mode": "full-copy-trial",
            "construction_phase": "copying",
        }
    )
    trial_inventory["validated_runtime"]["copy_identities"] = {
        "palace": _identity_value(trial_palace),
        "project_root": _identity_value(trial_project),
    }
    trial_inventory["copy_verification"]["qualification_device"] = root.stat().st_dev
    trial_receipt = copy.deepcopy(receipt)
    trial_receipt.update(
        {
            "receipt_path": str(_full_copy_trial_receipt_path(receipt, trial_name)),
            "inventory": trial_inventory,
            "pre": None,
            "expected": None,
            "snapshot": None,
            "phase": "inventoried",
            "writes": 0,
            "qualification_mode": "full-copy-trial",
            "parent_authority": {
                "inventory_authority_seal": receipt["inventory_authority_seal"],
                "inventory_path": receipt["inventory"]["inventory_path"],
                "preimage_sha256": _digest(receipt["pre"]),
                "receipt_path": receipt["receipt_path"],
                "receipt_seal": receipt["seal"],
            },
        }
    )
    trial_receipt["unrelated_preimage"] = _digest(_unrelated_file_hashes(trial_inventory))
    trial_receipt["recovery_command"] = _recovery_command(trial_receipt)
    _save_receipt(trial_receipt, initial=True)

    _copytree_without_sqlite(Path(baseline["palace"]), trial_palace, baseline_kg_paths)
    _copytree_without_sqlite(Path(baseline["project_root"]), trial_project, baseline_kg_paths)
    excluded_by_root: dict[Path, set[Path]] = {}
    for source in baseline_kg_paths:
        for owner_root in (Path(baseline["palace"]), Path(baseline["project_root"])):
            if _inside(source, owner_root):
                relatives = excluded_by_root.setdefault(owner_root, set())
                relative = source.relative_to(owner_root)
                relatives.update(Path(str(relative) + suffix) for suffix in ("", "-wal", "-shm"))
    _assert_distinct_regular_tree(
        Path(baseline["palace"]),
        trial_palace,
        excluded=excluded_by_root.get(Path(baseline["palace"])),
    )
    _assert_distinct_regular_tree(
        Path(baseline["project_root"]),
        trial_project,
        excluded=excluded_by_root.get(Path(baseline["project_root"])),
    )
    shutil.copy2(baseline["configuration"], configuration)
    for index, value in enumerate(baseline["kg_candidates"]):
        source = Path(value)
        target = Path(kg_paths[index])
        identity = (source.stat().st_dev, source.stat().st_ino)
        if external_copies.get(identity) == target and target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _sqlite_backup(source, target)
        external_copies[identity] = target
        if _identity_value(source) == _identity_value(target):
            raise MigrationError("trial_copy_alias", "a challenge KG aliases the baseline")

    trial_pre = _capture(trial_inventory)
    if _state_without_candidate_paths(trial_pre) != _state_without_candidate_paths(receipt["pre"]):
        raise MigrationError("trial_copy_incomplete", "challenge state differs from the baseline")
    if collision_challenge:
        sealed_source = next(
            row
            for row in trial_pre["lance_rows"]
            if row.get("wing") == trial_inventory["source_wing"]
            and _path_scoped(row.get("source_file"), Path(trial_inventory["logical_source_root"]))
        )
        source = _read_lance_row(trial_palace, str(sealed_source["id"]))
        if _lance_row_witness(source) != sealed_source:
            raise MigrationError("trial_copy_incomplete", "collision source differs from its seal")
        conflict = copy.deepcopy(source)
        conflict["id"] = f"{source['id']}-collision-challenge"
        conflict["wing"] = trial_inventory["destination_wing"]
        conflict["text"] = f"{source.get('text', '')}\ncollision challenge"
        import lancedb

        lancedb.connect(str(trial_palace / "lance")).open_table(TABLE_NAME).add([conflict])
        trial_pre = _capture(trial_inventory)
    trial_inventory.pop("construction_phase", None)
    trial_receipt["inventory"] = trial_inventory
    trial_receipt["pre"] = trial_pre
    trial_receipt["expected"] = (
        None
        if collision_challenge
        else _expected_state(trial_inventory, trial_pre, receipt["frozen_at"])
    )
    trial_receipt["unrelated_preimage"] = _digest(_unrelated_file_hashes(trial_inventory))
    _save_receipt(trial_receipt)
    if not collision_challenge:
        snapshot(trial_receipt["receipt_path"])
    return Path(trial_receipt["receipt_path"]), trial_receipt


def _assert_baseline_unchanged(receipt: dict[str, Any]) -> None:
    manifest = receipt.get("snapshot")
    if receipt.get("qualification_mode") != "full-copy" or not isinstance(manifest, dict):
        observed = _copy_preimage(receipt["inventory"])
    else:
        # Snapshot creation proved these sealed witnesses against the copied Lance bytes.
        # Fresh complete hashes therefore prove the same logical state without decoding rows.
        _validate_snapshot(receipt)
        live_lance = Path(receipt["inventory"]["palace"]) / "lance"
        lance_files = _stable_private_tree_hashes(live_lance)
        if bool(manifest.get("lance")) != live_lance.exists() or lance_files != manifest.get(
            "lance_hashes"
        ):
            raise MigrationError("full_copy_baseline_drift", "copied Lance bytes changed")
        observed = _copy_preimage_with_proved_lance(receipt, lance_files)
    if observed["state"] != _state_without_candidate_paths(receipt["pre"]):
        raise MigrationError("full_copy_restore_failed", "logical preimage differs")
    if _digest(observed["unrelated_files"]) != receipt["unrelated_preimage"]:
        raise MigrationError("full_copy_unrelated_drift", "unrelated copied files differ")
    if _digest(observed) != receipt["inventory"]["validated_runtime"]["copy_preimage_sha256"]:
        raise MigrationError("full_copy_baseline_drift", "admitted baseline seal changed")


def _assert_trial_parent_binding(receipt: dict[str, Any]) -> None:
    if receipt.get("qualification_mode") != "full-copy-trial":
        return
    binding = receipt.get("parent_authority")
    required = {
        "inventory_authority_seal",
        "inventory_path",
        "preimage_sha256",
        "receipt_path",
        "receipt_seal",
    }
    if not isinstance(binding, dict) or set(binding) != required:
        raise MigrationError("parent_binding_invalid", "descendant parent authority is incomplete")
    parent = _load_receipt(binding["receipt_path"])
    if (
        parent.get("qualification_mode") != "full-copy"
        or parent["seal"] != binding["receipt_seal"]
        or parent["inventory_authority_seal"] != binding["inventory_authority_seal"]
        or parent["inventory"]["inventory_path"] != binding["inventory_path"]
        or _digest(parent["pre"]) != binding["preimage_sha256"]
    ):
        raise MigrationError("parent_binding_invalid", "descendant parent authority changed")
    _assert_inventory_binding(parent, binding["inventory_path"])
    _assert_baseline_unchanged(parent)


@contextmanager
def _trial_parent_protection(receipt: dict[str, Any]) -> Iterator[None]:
    if receipt.get("qualification_mode") != "full-copy-trial":
        yield
        return
    binding = receipt.get("parent_authority")
    required = {
        "inventory_authority_seal",
        "inventory_path",
        "preimage_sha256",
        "receipt_path",
        "receipt_seal",
    }
    if not isinstance(binding, dict) or set(binding) != required:
        raise MigrationError("parent_binding_invalid", "descendant parent authority is incomplete")
    parent = _load_receipt(binding["receipt_path"])
    _assert_inventory_binding(parent, binding["inventory_path"])
    with _fence(parent["inventory"]):
        _assert_trial_parent_binding(receipt)
        yield


def _full_copy_inventory_path(argument: str | None) -> Path:
    selected = os.environ.get("WING_MIGRATION_INVENTORY_PATH")
    if not selected:
        raise MigrationError("full_copy_inventory_required", "private inventory is not selected")
    selected_path = _real(selected)
    if argument is not None and _real(argument) != selected_path:
        raise MigrationError("full_copy_inventory_mismatch", "inventory argument differs")
    if selected_path.is_symlink() or not selected_path.is_file():
        raise MigrationError("full_copy_inventory_unavailable", "selected inventory is unavailable")
    _assert_regular_private(selected_path)
    if not _private_mode_is_0600(selected_path):
        raise MigrationError("inventory_permissions_invalid", "inventory mode must be 0600")
    return selected_path


def _full_copy_evidence_paths(raw: dict[str, Any]) -> tuple[Path, Path]:
    fixture_value = raw.get("fixture_root")
    evidence_value = raw.get("evidence_root")
    if not isinstance(fixture_value, str) or not isinstance(evidence_value, str):
        raise MigrationError("inventory_missing_fields", "fixture_root and evidence_root required")
    fixture_root = _real(_lexical_absolute(fixture_value, "invalid_inventory_path"))
    evidence_root = _real(_lexical_absolute(evidence_value, "invalid_inventory_path"))
    if not _inside(evidence_root, fixture_root):
        raise MigrationError("outside_fixture", "evidence root escapes fixture root")
    return (
        evidence_root / f"full-copy-receipt-v{RECEIPT_VERSION}.json",
        evidence_root / f"full-copy-qualification-v{RECEIPT_VERSION}.json",
    )


def _assert_fresh_full_copy_workspace(raw: dict[str, Any]) -> None:
    fixture_value = raw.get("fixture_root")
    evidence_value = raw.get("evidence_root")
    snapshot_value = raw.get("snapshot_root")
    retained_values = raw.get("retained_snapshot_roots")
    if (
        not isinstance(fixture_value, str)
        or not isinstance(evidence_value, str)
        or not isinstance(snapshot_value, str)
        or not isinstance(retained_values, dict)
    ):
        return
    fixture_root = _real(_lexical_absolute(fixture_value, "invalid_inventory_path"))
    evidence_root = _real(_lexical_absolute(evidence_value, "invalid_inventory_path"))
    snapshot_root = _real(_lexical_absolute(snapshot_value, "invalid_inventory_path"))
    _reject_symlink_chain(fixture_root)
    _reject_symlink_chain(evidence_root)
    if not _inside(evidence_root, fixture_root):
        raise MigrationError("outside_fixture", "evidence root escapes fixture root")
    retained_roots = {
        _real(_lexical_absolute(value, "retained_snapshot_root_invalid"))
        for value in retained_values
        if isinstance(value, str)
    }
    allowed_snapshots = {snapshot_root, *retained_roots}
    try:
        stale_snapshots = [
            path
            for path in fixture_root.iterdir()
            if path.name.startswith("snapshot-") and path not in allowed_snapshots
        ]
    except OSError as exc:
        raise MigrationError(
            "fixture_path_unavailable", "cannot inspect full-copy generations"
        ) from exc
    if stale_snapshots:
        raise MigrationError(
            "stale_fixture_generation",
            "dispose superseded full-copy snapshots before another qualification",
        )
    trials_root = evidence_root / "trials"
    if trials_root.is_symlink():
        raise MigrationError("fixture_symlink", "full-copy trials root is a symlink")
    try:
        has_trials = trials_root.exists() and next(trials_root.iterdir(), None) is not None
    except OSError as exc:
        raise MigrationError("fixture_path_unavailable", "cannot inspect full-copy trials") from exc
    if has_trials:
        raise MigrationError(
            "stale_trial_evidence",
            "dispose recovered full-copy trial copies before another qualification",
        )


def _dispose_verified_full_copy_trial(parent: dict[str, Any], trial_path: Path) -> dict[str, str]:
    trial = _load_receipt(trial_path)
    root = Path(trial["inventory"]["fixture_root"])
    expected_parent = (
        Path(parent["inventory"]["evidence_root"]) / "trials" / f"v{parent['version']}"
    )
    if (
        trial.get("qualification_mode") != "full-copy-trial"
        or root.parent != expected_parent
        or trial_path != root / "evidence" / "receipt.json"
        or trial.get("phase") not in {"inventoried", "recovered"}
    ):
        raise MigrationError("trial_cleanup_refused", "trial is not verified disposable evidence")
    _assert_trial_parent_binding(trial)
    _assert_full_copy_restored(trial)
    summary = {
        "evidence_disposition": "verified_and_removed",
        "preimage_sha256": _digest(trial["pre"]),
        "receipt_seal": trial["seal"],
    }
    try:
        shutil.rmtree(root)
    except OSError as exc:
        raise MigrationError("trial_cleanup_failed", "cannot remove verified trial copy") from exc
    if root.exists() or root.is_symlink():
        raise MigrationError("trial_cleanup_failed", "verified trial copy remains")
    for empty_parent in (expected_parent, expected_parent.parent):
        try:
            empty_parent.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            # Another active or retained entry owns the non-empty parent.
            break
    return summary


def _qualify_full_copy(inventory_argument: str | None) -> dict[str, Any]:
    inventory_path = _full_copy_inventory_path(inventory_argument)
    raw_inventory = _load_json(inventory_path)
    receipt_path, report_path = _full_copy_evidence_paths(raw_inventory)
    if any(path.exists() or path.is_symlink() for path in (receipt_path, report_path)):
        raise MigrationError("full_copy_evidence_exists", "refusing to replace retained evidence")
    _assert_fresh_full_copy_workspace(raw_inventory)
    admitted = _load_inventory(inventory_path)
    if admitted.get("qualification_mode") != "full-copy":
        raise MigrationError("full_copy_inventory_invalid", "inventory mode is not full-copy")
    inventory(
        str(inventory_path),
        str(receipt_path),
        frozen_at=datetime.now(UTC).isoformat(),
        reserved_paths=(report_path,),
    )
    outcomes: list[dict[str, Any]] = []
    active_receipt_path = receipt_path

    def create_trial(
        parent: dict[str, Any], trial_name: str, *, collision_challenge: bool = False
    ) -> tuple[Path, dict[str, Any]]:
        nonlocal active_receipt_path
        active_receipt_path = Path(parent["receipt_path"])
        candidate = _full_copy_trial_receipt_path(parent, trial_name)
        try:
            created = _create_full_copy_trial(
                parent, trial_name, collision_challenge=collision_challenge
            )
        except Exception:
            if candidate.is_file() and not candidate.is_symlink():
                child = _load_receipt(candidate)
                binding = child.get("parent_authority", {})
                if (
                    binding.get("receipt_path") == parent["receipt_path"]
                    and binding.get("receipt_seal") == parent["seal"]
                ):
                    active_receipt_path = candidate
            raise
        active_receipt_path = created[0]
        return created

    def assert_parent_unchanged(parent: dict[str, Any]) -> None:
        nonlocal active_receipt_path
        active_receipt_path = Path(parent["receipt_path"])
        _assert_baseline_unchanged(parent)

    try:
        snapshot(str(receipt_path))
        baseline_receipt = _load_receipt(receipt_path)
        rehearsal_path, rehearsal_created = create_trial(baseline_receipt, "rehearsal")
        del rehearsal_created
        applied = apply(str(rehearsal_path))
        merged_receipt = rehearsal_path.read_bytes()
        retry = apply(str(rehearsal_path))
        if retry != {"state": "merged", "writes": 0, "retry": True}:
            raise MigrationError("qualification_state_invalid", "merged retry wrote data")
        if rehearsal_path.read_bytes() != merged_receipt:
            raise MigrationError("retry_wrote_receipt", "merged retry changed receipt")
        del merged_receipt
        recover(str(rehearsal_path))
        rehearsal_receipt = _load_receipt(rehearsal_path)
        _assert_full_copy_restored(rehearsal_receipt)
        rehearsal_measurements = rehearsal_receipt["runtime_proof"]["measurements"]
        del rehearsal_receipt
        assert_parent_unchanged(baseline_receipt)
        rehearsal_summary = _dispose_verified_full_copy_trial(baseline_receipt, rehearsal_path)
        active_receipt_path = receipt_path
        outcomes.append(
            {
                "trial": "rehearsal",
                "apply": applied,
                "recovered": True,
                **rehearsal_summary,
            }
        )

        collision_path, collision_receipt = create_trial(
            baseline_receipt, "collision", collision_challenge=True
        )
        collision_refused = _prove_collision_refusal(collision_receipt)
        del collision_receipt
        _assert_full_copy_restored(_load_receipt(collision_path))
        assert_parent_unchanged(baseline_receipt)
        collision_summary = _dispose_verified_full_copy_trial(baseline_receipt, collision_path)
        active_receipt_path = receipt_path
        outcomes.append({"trial": "collision", "refused": True, **collision_summary})

        for index, stage in enumerate(_apply_interruption_stages(baseline_receipt), 1):
            trial_name = f"apply-{index:03d}"
            trial_path, trial_receipt = create_trial(baseline_receipt, trial_name)
            del trial_receipt
            try:
                apply(str(trial_path), stop_after=stage)
            except InjectedStop:
                pass
            else:
                raise MigrationError("interruption_stage_missing", stage)
            recover(str(trial_path))
            _assert_full_copy_restored(_load_receipt(trial_path))
            assert_parent_unchanged(baseline_receipt)
            trial_summary = _dispose_verified_full_copy_trial(baseline_receipt, trial_path)
            active_receipt_path = receipt_path
            outcomes.append(
                {
                    "trial": "apply-interruption",
                    "stage": stage,
                    "recovered": True,
                    **trial_summary,
                }
            )

        for index, stage in enumerate(_recovery_interruption_stages(baseline_receipt), 1):
            trial_name = f"recover-{index:03d}"
            trial_path, trial_receipt = create_trial(baseline_receipt, trial_name)
            del trial_receipt
            apply(str(trial_path))
            try:
                recover(str(trial_path), stop_after=stage)
            except InjectedStop:
                pass
            else:
                raise MigrationError("interruption_stage_missing", stage)
            recover(str(trial_path))
            _assert_full_copy_restored(_load_receipt(trial_path))
            assert_parent_unchanged(baseline_receipt)
            trial_summary = _dispose_verified_full_copy_trial(baseline_receipt, trial_path)
            active_receipt_path = receipt_path
            outcomes.append(
                {
                    "trial": "recovery-interruption",
                    "stage": stage,
                    "recovered": True,
                    **trial_summary,
                }
            )

        active_receipt_path = receipt_path
        final_receipt = _load_receipt(receipt_path)
        private_report = {
            "status": "qualified",
            "mode": "full-copy",
            "inventory_seal": _digest(final_receipt["inventory"]),
            "receipt": str(receipt_path),
            "recovery_command": final_receipt["recovery_command"],
            "retention_rule": final_receipt["retention_rule"],
            "runtime_identity": final_receipt["runtime"],
            "runtime_measurements": rehearsal_measurements,
            "resume": {"runner_sha256": final_receipt["runner_hash"]},
            "outcomes": outcomes,
            "predicates": {
                "copy_only_authority": True,
                "copy_identity_separate": True,
                "collision_refused": collision_refused,
                "exact_union": True,
                "merged_retry_zero_writes": True,
                "all_interruptions_recovered": True,
                "full_preimage_restored": True,
                "unrelated_state_preserved": True,
                "original_path_noop_unproved": True,
                "live_authority_absent": True,
            },
        }
        _atomic_json(report_path, private_report, replace=False)
        return {
            "status": "qualified",
            "mode": "full-copy",
            "predicates": private_report["predicates"],
            "private_evidence": "retained at the owner-selected evidence destination",
            "authority_boundary": "all original-path and live rollout gates remain pending",
        }
    except (
        MigrationError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as exc:
        try:
            recovery_command = _recovery_command(_load_receipt(active_receipt_path))
        except (
            MigrationError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            sqlite3.Error,
        ):
            arguments = [
                admitted["validated_runtime"]["interpreter"],
                str(RUNNER_PATH),
                "recover",
            ]
            if active_receipt_path == receipt_path:
                arguments.extend(("--inventory", str(inventory_path)))
            arguments.extend(("--receipt", str(active_receipt_path)))
            recovery_command = shlex.join(arguments)
        failure = {
            "status": "refused",
            "mode": "full-copy",
            "failed_predicate": (
                exc.code if isinstance(exc, MigrationError) else "full_copy_operation_failed"
            ),
            "receipt": str(active_receipt_path),
            "recovery_command": recovery_command,
            "retention_rule": admitted["retention_rule"],
            "outcomes": outcomes,
        }
        if isinstance(exc, MigrationError) and exc.code.startswith("runtime_"):
            failure["failure_detail"] = exc.detail
        if not report_path.exists() and not report_path.is_symlink():
            _atomic_json(report_path, failure, replace=False)
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError("full_copy_operation_failed", "private operation failed") from exc


def _raw_row(row_id: str, wing: str, source_file: str, source_hash: str, text: str) -> dict:
    repo_root = RUNNER_PATH.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mempalace_code.storage import _META_FIELD_SPEC

    defaults = {name: default for name, _, default in _META_FIELD_SPEC}
    defaults.update(
        {
            "wing": wing,
            "room": "general",
            "source_file": source_file,
            "chunk_index": 0,
            "added_by": "synthetic-qualification",
            "filed_at": "2026-01-01T00:00:00+00:00",
            "ingest_mode": "file",
            "source_hash": source_hash,
            "language": "python",
            "symbol_name": "synthetic",
            "line_start": 1,
            "line_end": 8,
        }
    )
    return {"id": row_id, "text": text, "vector": [0.1, 0.2, 0.3], **defaults}


def _create_synthetic_fixture(root: Path, *, real_source_mine: bool = False) -> tuple[Path, Path]:
    fixture_id = hashlib.sha256(os.urandom(32)).hexdigest()[:24]
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    _create_lock_anchors(root / "operation.lock")
    _atomic_json(root / FIXTURE_MARKER, {"disposable": True, "fixture_id": fixture_id})
    project = root / "repository"
    project.mkdir()
    (project / ".git").mkdir()
    source = project / "app.py"
    source.write_text("def synthetic_value():\n    return 'wing migration fixture'\n" * 8)
    marker = project / "mempalace.yaml"
    marker.write_text("wing: old-wing\nrooms:\n  - name: general\n")
    configuration = root / "home" / ".mempalace" / "config.json"
    configuration.parent.mkdir(parents=True)
    configuration.write_text("{}\n", encoding="utf-8")
    tiny_source = project / "tiny.txt"
    tiny_source.write_text("tiny\n")
    palace = root / "palace"
    repo_root = RUNNER_PATH.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import lancedb

    from mempalace_code.storage import _target_drawer_schema

    tiny_path = palace / ".mempalace" / "tiny_hashes.json"
    if real_source_mine:
        model_cache_source_home = _model_cache_home()
        model_cache_home = _materialize_model_cache(
            model_cache_source_home, root / "baseline-hf-home"
        )
        runtime_authority = {
            "runtime": {
                "model_cache_home": str(model_cache_home),
                "model_cache_seal": _seal_model_cache(model_cache_home),
                "model_cache_source_home": str(model_cache_source_home),
                "model_cache_source_seal": _seal_model_cache(model_cache_source_home),
            }
        }
        try:
            baseline = _run_runtime_subprocess(
                runtime_authority,
                [
                    sys.executable,
                    "-B",
                    "-I",
                    "-m",
                    "mempalace_code.cli",
                    "--palace",
                    str(palace),
                    "mine",
                    str(project),
                ],
                home=root / "home",
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                timeout=90,
            )
        finally:
            shutil.rmtree(model_cache_home, ignore_errors=True)
        if baseline.returncode != 0 or "Wing:    old-wing" not in baseline.stdout:
            detail = "\n".join(
                part for part in (baseline.stdout.strip(), baseline.stderr.strip()) if part
            )
            raise MigrationError("synthetic_source_baseline_failed", detail)
        table = lancedb.connect(str(palace / "lance")).open_table(TABLE_NAME)
        mined_rows = table.to_arrow().to_pylist()
        source_rows = [row for row in mined_rows if row.get("wing") == "old-wing"]
        if not source_rows:
            raise MigrationError("synthetic_source_baseline_failed", "mine produced no source rows")
        dimension = len(source_rows[0]["vector"])
    else:
        from mempalace_code.source_io import hash_regular_bytes

        (palace / "lance").mkdir(parents=True)
        source_hash = hash_regular_bytes(source, digest_size=16)
        table = lancedb.connect(str(palace / "lance")).create_table(
            TABLE_NAME, schema=_target_drawer_schema(3)
        )
        source_row = _raw_row(
            "source-file", "old-wing", str(source), source_hash, source.read_text()
        )
        table.add([source_row])
        tiny_path.parent.mkdir()
        tiny_hash = hash_regular_bytes(tiny_source, digest_size=16)
        tiny_path.write_text(json.dumps({"old-wing": {str(tiny_source): tiny_hash}}))
        dimension = 3
    destination_diary = _raw_row("destination-diary", "new-wing", "", "", "keep diary")
    destination_diary.update({"ingest_mode": "diary", "type": "diary", "vector": [0.4] * dimension})
    unrelated = _raw_row("unrelated", "other-wing", "/other/file.py", "f" * 32, "other")
    unrelated["vector"] = [0.6] * dimension
    table.add([destination_diary, unrelated])

    from mempalace_code.knowledge_graph import KnowledgeGraph

    kg_paths = [
        palace / "knowledge_graph.sqlite3",
        root / "home" / ".mempalace" / "knowledge_graph.sqlite3",
    ]
    for index, kg_path in enumerate(kg_paths):
        graph = KnowledgeGraph(str(kg_path))
        connection = sqlite3.connect(str(kg_path))
        connection.execute(
            "INSERT OR REPLACE INTO entities(id,name,type,properties) VALUES(?,?,?,?)",
            ("old-wing", "old-wing", "project", "{}"),
        )
        connection.execute(
            "INSERT INTO entities(id,name,type,properties) VALUES(?,?,?,?)",
            (f"subject-{index}", f"Subject {index}", "type", "{}"),
        )
        connection.execute(
            "INSERT INTO triples(id,subject,predicate,object,valid_from,valid_to,confidence,source_file) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                f"eligible-{index}",
                f"subject-{index}",
                "in_project",
                "old-wing",
                "2025-01-01",
                None,
                0.75,
                str(source) if index == 0 else "__arch_ns_project__:old-wing",
            ),
        )
        connection.execute(
            "INSERT INTO triples(id,subject,predicate,object,valid_from,valid_to,confidence,source_file) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                f"historical-{index}",
                f"subject-{index}",
                "in_project",
                "old-wing",
                "2020-01-01",
                "2020-12-31",
                0.5,
                str(source),
            ),
        )
        connection.commit()
        connection.close()
        del graph

    inventory_path = root / "inventory.json"
    evidence_root = root / "evidence"
    evidence_root.mkdir()
    receipt_path = evidence_root / "receipt.json"
    inventory_value = {
        "version": INVENTORY_VERSION,
        "fixture_id": fixture_id,
        "disposable": True,
        "fixture_root": str(root),
        "palace": str(palace),
        "project_root": str(project),
        "marker": str(marker),
        "tiny_hashes": str(tiny_path),
        "kg_candidates": [str(path) for path in kg_paths],
        "lock": str(root / "operation.lock"),
        "snapshot_root": str(root / "snapshot"),
        "runtime_root": str(root / "runtime"),
        "evidence_root": str(evidence_root),
        "configuration": str(configuration),
        "source_wing": "old-wing",
        "destination_wing": "new-wing",
        "lance_batch_size": 1,
    }
    _atomic_json(inventory_path, inventory_value)
    return inventory_path, receipt_path


def _live_maintenance_path(lock_path: Path) -> Path:
    return lock_path.with_name(LIVE_MAINTENANCE_NAME)


def _assert_live_maintenance(inventory: dict[str, Any], phases: frozenset[str]) -> None:
    path = Path(inventory["maintenance_marker"])
    try:
        _assert_regular_private(path)
        value = _load_json(path)
    except (FileNotFoundError, OSError) as exc:
        raise MigrationError(
            "live_maintenance_required", "live maintenance marker is absent"
        ) from exc
    if (
        not _private_mode_is_0600(path)
        or value.get("receipt_path") != inventory["maintenance_receipt_path"]
        or value.get("approved_host") != inventory["approved_host"]
        or value.get("phase") not in phases
    ):
        raise MigrationError("maintenance_marker_drift", "live maintenance marker differs")


def _clear_live_maintenance(receipt: dict[str, Any]) -> None:
    if receipt.get("qualification_mode") != "live":
        return
    path = Path(receipt["inventory"]["maintenance_marker"])
    try:
        _assert_regular_private(path)
        value = _load_json(path)
    except FileNotFoundError:
        return
    if value.get("receipt_path") != receipt["receipt_path"]:
        raise MigrationError("maintenance_marker_drift", "live marker belongs to another receipt")
    path.unlink()


def _validate_live_authority(
    path: str, *, allow_existing_evidence: bool = False
) -> tuple[dict[str, Any], Path]:
    authority_path = _real(path)
    _assert_regular_private(authority_path)
    if not _private_mode_is_0600(authority_path):
        raise MigrationError("live_authority_permissions", "live authority must use mode 0600")
    authority = _load_json(authority_path)
    required = {
        "version",
        "scope",
        "approved_host",
        "approved_operation",
        "owner_approval",
        "live_mutation",
        "mcp_downtime",
        "source_wing",
        "destination_wing",
        "palace",
        "project_root",
        "marker",
        "tiny_hashes",
        "kg_candidates",
        "configuration",
        "lock",
        "evidence_root",
        "retention_rule",
        "qualification_report",
        "qualification_report_sha256",
        "qualification_inventory_seal",
        "qualified_runner_sha256",
    }
    if set(authority) != required:
        raise MigrationError("live_authority_invalid", "live authority fields differ")
    source = authority["source_wing"]
    destination = authority["destination_wing"]
    if (
        authority["version"] != 1
        or authority["scope"] != LIVE_SCOPE
        or authority["live_mutation"] is not True
        or authority["mcp_downtime"] is not True
        or authority["retention_rule"] != FULL_COPY_RETENTION_RULE
        or authority["approved_host"] != socket.gethostname()
        or not isinstance(authority["owner_approval"], str)
        or not authority["owner_approval"]
        or authority["approved_operation"] != f"merge wing {source} into {destination}"
        or not isinstance(source, str)
        or not source
        or not isinstance(destination, str)
        or not destination
        or source == destination
    ):
        raise MigrationError("live_authority_invalid", "live authority values differ")
    home = Path.home()
    canonical = {
        "palace": home / ".mempalace" / "palace",
        "configuration": home / ".mempalace" / "config.json",
        "lock": home / ".mempalace" / "operation.lock",
    }
    paths: dict[str, Path] = {}
    for key in (
        "palace",
        "project_root",
        "marker",
        "tiny_hashes",
        "configuration",
        "lock",
        "evidence_root",
        "qualification_report",
    ):
        paths[key] = _lexical_absolute(authority[key], "live_authority_invalid")
        _reject_symlink_chain(paths[key])
    if any(paths[key] != value for key, value in canonical.items()):
        raise MigrationError("live_path_invalid", "canonical MemPalace paths differ")
    if paths["marker"] != paths["project_root"] / "mempalace.yaml":
        raise MigrationError("live_path_invalid", "project marker path differs")
    if paths["tiny_hashes"] != paths["palace"] / ".mempalace" / "tiny_hashes.json":
        raise MigrationError("live_path_invalid", "tiny hashes path differs")
    state_root = home / ".local" / "state" / "mempalace"
    if not _inside(paths["evidence_root"], state_root):
        raise MigrationError("live_path_invalid", "evidence root is outside local state")
    if paths["evidence_root"].exists() or paths["evidence_root"].is_symlink():
        if not allow_existing_evidence:
            raise MigrationError("live_evidence_exists", "refusing to replace live evidence")
        _reject_symlink_chain(paths["evidence_root"])
        if not paths["evidence_root"].is_dir():
            raise MigrationError("live_evidence_invalid", "live evidence is not a directory")
    for key in ("palace", "project_root"):
        if not paths[key].is_dir():
            raise MigrationError("live_path_invalid", f"required directory is absent: {key}")
    for key in ("marker", "tiny_hashes", "configuration", "lock", "qualification_report"):
        _assert_regular_private(paths[key])

    raw_candidates = authority["kg_candidates"]
    expected_candidates = [
        paths["palace"] / "knowledge_graph.sqlite3",
        home / ".mempalace" / "knowledge_graph.sqlite3",
    ]
    if (
        not isinstance(raw_candidates, list)
        or [Path(value) for value in raw_candidates] != expected_candidates
    ):
        raise MigrationError("live_path_invalid", "KG candidate inventory differs")
    for candidate in expected_candidates:
        _reject_symlink_chain(candidate)
        _assert_regular_private(candidate)

    report = _load_json(paths["qualification_report"])
    report_hash = _file_digest(paths["qualification_report"])
    required_predicates = {
        "all_interruptions_recovered",
        "collision_refused",
        "copy_identity_separate",
        "copy_only_authority",
        "exact_union",
        "full_preimage_restored",
        "merged_retry_zero_writes",
        "unrelated_state_preserved",
    }
    predicates = report.get("predicates")
    resume = report.get("resume")
    if (
        report_hash != authority["qualification_report_sha256"]
        or report.get("status") != "qualified"
        or report.get("mode") != "full-copy"
        or report.get("inventory_seal") != authority["qualification_inventory_seal"]
        or not isinstance(predicates, dict)
        or not all(predicates.get(key) is True for key in required_predicates)
        or not isinstance(resume, dict)
        or resume.get("runner_sha256") != authority["qualified_runner_sha256"]
    ):
        raise MigrationError("qualification_report_invalid", "full-copy proof differs")
    return authority, authority_path


def _live_inventory(authority: dict[str, Any], authority_path: Path) -> dict[str, Any]:
    evidence_root = Path(authority["evidence_root"])
    evidence_root.mkdir(parents=True, mode=0o700)
    (evidence_root / "home").mkdir(mode=0o700)
    recovery_runner = evidence_root / "wing_migration_runner.py"
    shutil.copy2(RUNNER_PATH, recovery_runner)
    os.chmod(recovery_runner, 0o600)
    stable_paths = [
        Path(authority[key]) for key in ("palace", "project_root", "configuration", "lock")
    ]
    mutable_paths = [Path(authority["marker"]), Path(authority["tiny_hashes"])]
    mutable_paths.extend(Path(value) for value in authority["kg_candidates"])
    lance_bytes = sum(
        path.stat().st_size
        for path in (Path(authority["palace"]) / "lance").rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    inventory = {
        "version": INVENTORY_VERSION,
        "fixture_id": f"live-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "disposable": False,
        "fixture_root": str(evidence_root),
        "palace": authority["palace"],
        "project_root": authority["project_root"],
        "marker": authority["marker"],
        "tiny_hashes": authority["tiny_hashes"],
        "kg_candidates": authority["kg_candidates"],
        "lock": authority["lock"],
        "snapshot_root": str(evidence_root / "snapshot"),
        "runtime_root": str(evidence_root / "runtime-unused"),
        "evidence_root": str(evidence_root),
        "configuration": authority["configuration"],
        "source_wing": authority["source_wing"],
        "destination_wing": authority["destination_wing"],
        "logical_source_root": authority["project_root"],
        "lance_batch_size": 1024,
        "lance_state_format": LANCE_STATE_FORMAT,
        "qualification_mode": "live",
        "retention_rule": authority["retention_rule"],
        "authority_path": str(authority_path),
        "live_authority_seal": _digest(authority),
        "approved_host": authority["approved_host"],
        "maintenance_marker": str(_live_maintenance_path(Path(authority["lock"]))),
        "maintenance_receipt_path": str(evidence_root / "receipt.json"),
        "recovery_runner": str(recovery_runner),
        "recovery_runner_sha256": _file_digest(recovery_runner),
        "required_free_bytes": max(1024 * 1024 * 1024, lance_bytes * 2),
        "live_mutable_paths": [str(path) for path in mutable_paths],
    }
    inventory["fixture_root_identity"] = _path_identity(evidence_root)
    inventory["live_target_identities"] = {str(path): _path_identity(path) for path in stable_paths}
    return inventory


def live_run(authority_path: str) -> dict[str, Any]:
    authority, sealed_authority_path = _validate_live_authority(authority_path)
    receipt_path = Path(authority["evidence_root"]) / "receipt.json"
    maintenance = _live_maintenance_path(Path(authority["lock"]))
    admission_recovery = shlex.join(
        [
            sys.executable,
            "-B",
            "-I",
            "-m",
            "mempalace_code.cli",
            "wing-migration",
            "live-recover",
            "--authority",
            str(sealed_authority_path),
        ]
    )
    _atomic_json(
        maintenance,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "approved_host": authority["approved_host"],
            "receipt_path": str(receipt_path),
            "phase": "admission",
            "recovery_command": admission_recovery,
        },
        replace=False,
    )
    receipt_created = False
    stopped: list[int] = []
    try:
        stopped = _stop_live_mcp_clients()
        inventory_value = _live_inventory(authority, sealed_authority_path)
        pre = _capture(inventory_value)
        frozen = datetime.now(UTC).isoformat()
        expected = _expected_state(inventory_value, pre, frozen)
        runtime = _installed_runtime_identity()
        recovery_command = shlex.join(
            [
                runtime["interpreter"],
                inventory_value["recovery_runner"],
                "recover",
                "--receipt",
                str(receipt_path),
            ]
        )
        receipt = {
            "version": RECEIPT_VERSION,
            "receipt_path": str(receipt_path),
            "inventory": inventory_value,
            "runner_hash": _file_digest(RUNNER_PATH),
            "runtime": runtime,
            "frozen_at": frozen,
            "pre": pre,
            "expected": expected,
            "snapshot": None,
            "phase": "inventoried",
            "writes": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "qualification_mode": "live",
            "retention_rule": authority["retention_rule"],
            "inventory_authority_seal": _digest(authority),
            "unrelated_preimage": None,
            "recovery_command": recovery_command,
            "qualification_report_sha256": authority["qualification_report_sha256"],
        }
        with _fence(inventory_value, live_phases=frozenset({"admission"})):
            if _capture(inventory_value) != pre:
                raise MigrationError("preimage_drift", "live state changed during admission")
            _assert_recovery_capacity(inventory_value)
            _validate_runtime(receipt)
            _save_receipt(receipt, initial=True)
            receipt_created = True
            _atomic_json(
                maintenance,
                {
                    "created_at": receipt["created_at"],
                    "approved_host": authority["approved_host"],
                    "receipt_path": str(receipt_path),
                    "phase": "receipt",
                    "recovery_command": recovery_command,
                },
            )
        snapshot(str(receipt_path))
        result = apply(str(receipt_path))
        sealed = _load_receipt(receipt_path)
        if _classify_receipt(sealed) != "merged":
            raise MigrationError("postcondition_failed", "live receipt is not merged")
        return {
            "state": "merged",
            "writes": result["writes"],
            "stopped_mcp_clients": len(stopped),
            "runtime_noop": sealed["runtime_proof"]["post_activation"]["predicates"],
            "recovery_command": recovery_command,
            "retention_rule": sealed["retention_rule"],
        }
    except BaseException:
        if not receipt_created:
            if maintenance.exists() and not maintenance.is_symlink():
                maintenance.unlink()
            shutil.rmtree(Path(authority["evidence_root"]), ignore_errors=True)
        raise


def live_recover(authority_path: str) -> dict[str, Any]:
    authority, _ = _validate_live_authority(authority_path, allow_existing_evidence=True)
    receipt_path = Path(authority["evidence_root"]) / "receipt.json"
    maintenance = _live_maintenance_path(Path(authority["lock"]))
    _stop_live_mcp_clients()
    from mempalace_code.operation_lock import OperationLock, OperationLockedError

    try:
        lease = OperationLock(authority["lock"]).acquire_exclusive("live-wing-recovery-admission")
    except OperationLockedError as exc:
        raise MigrationError("writer_conflict", json.dumps(exc.owner, sort_keys=True)) from exc
    with lease:
        _assert_regular_private(maintenance)
        marker = _load_json(maintenance)
        if (
            not _private_mode_is_0600(maintenance)
            or marker.get("approved_host") != authority["approved_host"]
            or marker.get("receipt_path") != str(receipt_path)
            or marker.get("phase") not in {"admission", "receipt", "recovering"}
        ):
            raise MigrationError("maintenance_marker_drift", "live maintenance marker differs")
        if receipt_path.exists():
            marker["phase"] = "recovering"
            _atomic_json(maintenance, marker)
            receipt_exists = True
        else:
            receipt_exists = False
            if marker.get("phase") != "admission":
                raise MigrationError("live_receipt_missing", "retained live receipt is unavailable")
            maintenance.unlink()
            evidence_root = Path(authority["evidence_root"])
            if evidence_root.exists() and not evidence_root.is_symlink():
                shutil.rmtree(evidence_root)
    if receipt_exists:
        return recover(str(receipt_path))
    return {"state": "original", "restored": False, "admission_only": True}


def qualify(mode: str, inventory_path: str | None = None) -> dict[str, Any]:
    if mode == "full-copy":
        return _qualify_full_copy(inventory_path)
    if mode != "synthetic":
        raise MigrationError("live_authority_required", "live execution is outside this runner")
    if inventory_path is not None:
        raise MigrationError(
            "synthetic_inventory_forbidden", "synthetic mode creates its own fixture"
        )

    root = Path(tempfile.mkdtemp(prefix="mempalace-wing-migration-")).resolve()
    succeeded = False
    try:
        inventory_file, receipt_file = _create_synthetic_fixture(root, real_source_mine=True)
        receipt = inventory(
            str(inventory_file), str(receipt_file), frozen_at="2026-01-15T12:00:00+00:00"
        )
        primitive_row = next(
            row
            for row in receipt["pre"]["lance_rows"]
            if row.get("wing") == receipt["inventory"]["source_wing"]
        )
        before_non_wing = {key: value for key, value in primitive_row.items() if key != "wing"}
        snapshot(str(receipt_file))
        applied = apply(str(receipt_file), inventory_path=str(inventory_file))
        merged_receipt_bytes = receipt_file.read_bytes()
        retry = apply(str(receipt_file), inventory_path=str(inventory_file))
        if receipt_file.read_bytes() != merged_receipt_bytes:
            raise MigrationError("retry_wrote_receipt", "merged retry changed receipt bytes")
        observed = _capture(_load_receipt(receipt_file)["inventory"])
        migrated_row = next(
            row for row in observed["lance_rows"] if row["id"] == primitive_row["id"]
        )
        after_non_wing = {key: value for key, value in migrated_row.items() if key != "wing"}
        if before_non_wing != after_non_wing:
            raise MigrationError("primitive_row_changed", "native update changed a non-wing field")
        live_runtime = _runtime_live_noop(_load_receipt(receipt_file))
        after_runtime = _load_receipt(receipt_file)
        observed_after_runtime = _capture(after_runtime["inventory"])
        runtime_delta_reasons = _runtime_delta_allowed(
            observed, observed_after_runtime, after_runtime
        )
        if runtime_delta_reasons:
            raise MigrationError(
                "runtime_probe_mutated_state",
                "installed incremental mine changed state outside the architecture refresh envelope: "
                + "; ".join(runtime_delta_reasons),
            )
        if retry["writes"] != 0:
            raise MigrationError("qualification_state_invalid", "merged retry was not idempotent")
        report = {
            "status": "qualified",
            "mode": "synthetic",
            "synthetic_only": True,
            "predicates": {
                "exact_typed_union": True,
                "kg_candidates_complete": True,
                "native_wing_update": True,
                "snapshot_restore_proved": True,
                "merged_retry_zero_writes": True,
                "installed_runtime_incremental_noop": True,
                "fixture_contained": True,
            },
            "apply": applied,
            "runtime": {
                **after_runtime["runtime_proof"],
                "post_activation": live_runtime,
            },
            "removal_condition": "remove runner, focused tests, and operations note together",
            "authority_boundary": "synthetic proof does not authorize full-copy or live rollout",
            "recovery_command": _recovery_command(_load_receipt(receipt_file)),
            "fixture_retention": "successful synthetic fixture removed at command exit",
        }
        succeeded = True
        return report
    except MigrationError as exc:
        raise MigrationError(exc.code, f"{exc.detail}; retained_fixture={root}") from exc
    finally:
        if succeeded:
            shutil.rmtree(root, ignore_errors=True)


def _recovery_command(receipt: dict[str, Any]) -> str:
    arguments = [receipt["runtime"]["interpreter"], str(RUNNER_PATH), "recover"]
    if receipt.get("qualification_mode") in {"synthetic", "full-copy"}:
        arguments.extend(("--inventory", receipt["inventory"]["inventory_path"]))
    arguments.extend(("--receipt", receipt["receipt_path"]))
    return shlex.join(arguments)


def _recovery_command_from_paths(inventory: str | None, receipt: str) -> str:
    arguments = [sys.executable, str(RUNNER_PATH), "recover"]
    if inventory:
        arguments.extend(("--inventory", str(_real(inventory))))
    arguments.extend(("--receipt", str(_real(receipt))))
    return shlex.join(arguments)


def _result(action: str, state: str, **extra: Any) -> dict[str, Any]:
    return {
        "action": action,
        "state": state,
        "authority": "explicit disposable fixture only",
        **extra,
    }


def _public_full_copy_result(action: str, state: str) -> dict[str, Any]:
    next_actions = {
        "inventory": "snapshot",
        "snapshot": "apply",
        "apply": "inspect_private_evidence",
        "classify": "inspect_private_evidence",
        "recover": "inspect_private_evidence",
        "qualify": "inspect_private_evidence",
    }
    return {
        "action": action,
        "state": state,
        "status": state,
        "authority": "owner-authorized isolated full copy only",
        "allowed_next_action": next_actions[action],
    }


def _public_live_result(action: str, state: str) -> dict[str, Any]:
    return {
        "action": action,
        "state": state,
        "status": state,
        "authority": "owner-authorized exact-host live merge",
        "allowed_next_action": "inspect retained evidence",
    }


def _arguments_target_live(args: argparse.Namespace) -> bool:
    if getattr(args, "action", None) in {"live-run", "live-recover"}:
        return True
    receipt_path = getattr(args, "receipt", None)
    if not receipt_path:
        return False
    try:
        return _load_receipt(receipt_path).get("qualification_mode") == "live"
    except (MigrationError, OSError, ValueError, TypeError, KeyError):
        return False


def _arguments_target_full_copy(args: argparse.Namespace) -> bool:
    if getattr(args, "mode", None) == "full-copy":
        return True
    selected = os.environ.get("WING_MIGRATION_INVENTORY_PATH")
    inventory_path = getattr(args, "inventory", None)
    if selected:
        return True
    if getattr(args, "action", None) == "recover" and inventory_path is None:
        return True
    if inventory_path:
        try:
            return _full_copy_requested(_load_json(_real(inventory_path)))
        except (MigrationError, OSError, ValueError, TypeError):
            return bool(selected)
    receipt_path = getattr(args, "receipt", None)
    if receipt_path:
        try:
            return _load_receipt(receipt_path).get("qualification_mode") in {
                "full-copy",
                "full-copy-trial",
            }
        except (MigrationError, OSError, ValueError, TypeError, KeyError):
            # An unreadable receipt is private by default.  There is no sealed
            # mode from which to establish a safe public diagnostic boundary.
            return True
    return False


def _synthetic_recovery_command(receipt_path: str | None) -> str | None:
    if not receipt_path:
        return None
    try:
        receipt = _load_receipt(receipt_path)
    except (
        MigrationError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        sqlite3.Error,
    ):
        return None
    if receipt.get("qualification_mode") != "synthetic":
        return None
    return _recovery_command(receipt)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--inventory", required=True)
    inventory_parser.add_argument("--receipt", required=True)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--receipt", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--inventory", required=True)
    apply_parser.add_argument("--receipt", required=True)
    apply_parser.add_argument("--stop-after")
    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("--receipt", required=True)
    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("--inventory")
    recover_parser.add_argument("--receipt", required=True)
    recover_parser.add_argument("--stop-after")
    qualify_parser = subparsers.add_parser("qualify")
    qualify_parser.add_argument("--mode", choices=("synthetic", "full-copy", "live"), required=True)
    qualify_parser.add_argument("--inventory")
    live_parser = subparsers.add_parser("live-run")
    live_parser.add_argument("--authority", required=True)
    live_recover_parser = subparsers.add_parser("live-recover")
    live_recover_parser.add_argument("--authority", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        live = _arguments_target_live(args)
        full_copy = not live and _arguments_target_full_copy(args)
        if args.action == "inventory":
            receipt = inventory(args.inventory, args.receipt)
            output = (
                _public_full_copy_result("inventory", "original")
                if full_copy
                else _result("inventory", "original", receipt=receipt["receipt_path"])
            )
        elif args.action == "snapshot":
            receipt = snapshot(args.receipt)
            output = (
                _public_live_result("snapshot", "original")
                if live
                else _public_full_copy_result("snapshot", "original")
                if full_copy
                else _result("snapshot", "original", snapshot=receipt["snapshot"]["root"])
            )
        elif args.action == "apply":
            applied = apply(args.receipt, inventory_path=args.inventory, stop_after=args.stop_after)
            output = (
                _public_full_copy_result("apply", applied["state"])
                if full_copy
                else _result(
                    "apply",
                    applied["state"],
                    **{key: value for key, value in applied.items() if key != "state"},
                )
            )
        elif args.action == "classify":
            state = classify(args.receipt)
            output = (
                _public_live_result("classify", state)
                if live
                else _public_full_copy_result("classify", state)
                if full_copy
                else _result("classify", state)
            )
        elif args.action == "recover":
            recovered = recover(
                args.receipt, inventory_path=args.inventory, stop_after=args.stop_after
            )
            output = (
                _public_live_result("recover", recovered["state"])
                if live
                else _public_full_copy_result("recover", recovered["state"])
                if full_copy
                else _result(
                    "recover",
                    recovered["state"],
                    **{key: value for key, value in recovered.items() if key != "state"},
                )
            )
        elif args.action == "qualify":
            qualified = qualify(args.mode, args.inventory)
            output = (
                _public_full_copy_result("qualify", qualified["status"]) if full_copy else qualified
            )
        elif args.action == "live-run":
            output = live_run(args.authority)
        else:
            output = live_recover(args.authority)
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        MigrationError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as exc:
        receipt = getattr(args, "receipt", None)
        live = _arguments_target_live(args)
        full_copy = not live and _arguments_target_full_copy(args)
        recovery = "use the receipt-bound recovery action in private evidence"
        synthetic_recovery = None
        if live:
            try:
                if receipt:
                    recovery = _load_receipt(receipt)["recovery_command"]
                else:
                    authority = _load_json(_real(args.authority))
                    marker = _live_maintenance_path(Path(authority["lock"]))
                    recovery = _load_json(marker)["recovery_command"]
            except (MigrationError, OSError, ValueError, TypeError, KeyError):
                recovery = "rerun live-recover with the exact mode-0600 authority"
        elif not full_copy:
            synthetic_recovery = _synthetic_recovery_command(receipt)
            if synthetic_recovery is not None:
                recovery = synthetic_recovery
            elif receipt:
                full_copy = True
        if live:
            allowed_next_action = "live-recover"
        elif synthetic_recovery is not None:
            allowed_next_action = "recover"
        elif full_copy:
            allowed_next_action = "inspect_private_evidence"
        else:
            allowed_next_action = "inventory"
        output = {
            "status": "refused",
            "failed_predicate": (
                exc.code if isinstance(exc, MigrationError) else "operation_failed"
            ),
            "detail": "operation refused; inspect private evidence for diagnostics",
            "allowed_next_action": allowed_next_action,
            "authority_boundary": (
                "exact-host live authority"
                if live
                else "full-copy and live actions require separate owner authority"
            ),
            "recovery_command": recovery,
        }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
