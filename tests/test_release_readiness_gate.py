"""Tests for scripts/release_readiness_gate.py — release-readiness orchestration."""

from __future__ import annotations

import errno
import importlib.util
import io
import json
import os
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import mempalace_code.storage as storage_owner

ROOT = Path(__file__).parent.parent
SHA = "a" * 40


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


rrg = _load_module("release_readiness_gate", ROOT / "scripts" / "release_readiness_gate.py")
_RUN_INSTALLED_APPLICATION = rrg._run_installed_application
_RUN_INSTALLED_GOLDEN = rrg._run_installed_golden


@pytest.fixture(autouse=True)
def _complete_installed_application(monkeypatch):
    monkeypatch.setattr(
        rrg,
        "_run_installed_application",
        lambda dist_dir: [rrg._make_row("installed_venv", "installed smoke", "pass", "complete")],
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_golden",
        lambda dist_dir, root: [
            rrg._make_row("installed_golden_suite", "installed golden", "pass", "complete")
        ],
    )


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _mock_inventory_ok() -> list[dict]:
    return [
        rrg._make_row("gate_inventory", "python scripts/gate_inventory.py --check", "pass", "ok")
    ]


def _mock_inventory_fail() -> list[dict]:
    return [
        rrg._make_row(
            "gate_inventory", "python scripts/gate_inventory.py --check", "fail", "drift detected"
        )
    ]


def _mock_build_ok() -> tuple[bool, str]:
    return True, "built successfully"


def _mock_build_fail() -> tuple[bool, str]:
    return False, "hatchling error"


def _write_model_cache(
    root: Path, *, revision: str = storage_owner.CANONICAL_EMBED_MODEL_REVISION
) -> Path:
    model = root / storage_owner._FASTEMBED_CACHE_CHILD
    model.mkdir(parents=True, exist_ok=True)
    (model / ".mempalace-model.json").write_text(
        json.dumps(storage_owner.canonical_fastembed_provenance()), encoding="utf-8"
    )
    repository = model / storage_owner._FASTEMBED_REPOSITORY
    (repository / "refs").mkdir(parents=True)
    (repository / "refs" / "main").write_text(revision, encoding="utf-8")
    snapshot = repository / "snapshots" / revision
    snapshot.mkdir(parents=True)
    for name in storage_owner._FASTEMBED_REQUIRED_ARTIFACTS:
        (snapshot / name).write_bytes(b"fixture")
    (snapshot / "tokenizer_config.json").write_text(
        json.dumps({"max_length": 256, "model_max_length": 512}), encoding="utf-8"
    )
    return root


def _write_candidate_wheel(root: Path, *, version: str = "1.13.5") -> Path:
    wheel = root / f"mempalace_code-{version}-py3-none-any.whl"
    metadata = f"Metadata-Version: 2.1\nName: mempalace-code\nVersion: {version}\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"mempalace_code-{version}.dist-info/METADATA", metadata)
    return wheel


def _successful_golden_runner(calls: list[tuple[list[str], dict]]):
    def run(command, **kwargs):
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        if command[1:3] == ["-m", "venv"]:
            bin_dir = Path(command[3]) / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").write_text("python", encoding="utf-8")
            (bin_dir / "mempalace-code").write_text("console", encoding="utf-8")
            mcp_launcher = bin_dir / "mempalace-code-mcp"
            mcp_launcher.write_text("mcp", encoding="utf-8")
            mcp_launcher.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[1:4] == ["-m", "pip", "install"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if (
            command[-1]
            == rrg._load_sibling(
                "_release_install_metadata_golden", "release_install_metadata_smoke.py"
            )._SITE_PACKAGES_SCRIPT
        ):
            site_dir = Path(command[0]).parent.parent / "site-packages"
            site_dir.mkdir()
            return SimpleNamespace(returncode=0, stdout=json.dumps([str(site_dir)]), stderr="")
        if len(command) == 2 and command[1].endswith(rrg.INSTALLED_CLI_INVENTORY_PROBE_NAME):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"members": [["help"]]}),
                stderr="",
            )
        if len(command) == 2 and command[1].endswith(rrg.INSTALLED_MCP_INVENTORY_PROBE_NAME):
            site_dir = Path(command[0]).parent.parent / "site-packages"
            registry_module = site_dir / "mempalace_code" / "mcp" / "registry.py"
            profiles_module = site_dir / "mempalace_code" / "mcp_tool_profiles.py"
            registry_module.parent.mkdir(parents=True, exist_ok=True)
            registry_module.write_text("", encoding="utf-8")
            profiles_module.write_text("", encoding="utf-8")
            tools = list(rrg._installed_mcp_recipe(Path("/fixture")))
            profiles = [
                {"name": "minimal", "members": tools[:1]},
                {"name": "kg", "members": tools[:2]},
                {"name": "code", "members": tools[:3]},
                {"name": "notes", "members": tools[:4]},
                {"name": "full", "members": tools},
            ]
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "registry_module": str(registry_module),
                        "profiles_module": str(profiles_module),
                        "tools": tools,
                        "profiles": profiles,
                    }
                ),
                stderr="",
            )
        if len(command) == 3 and command[1].endswith(rrg.INSTALLED_CLI_INVENTORY_PROBE_NAME):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"executed": [["help"]]}),
                stderr="",
            )
        if len(command) > 2 and command[1:3] == ["-c", rrg.INSTALLED_MODEL_CACHE_PROBE]:
            cache_root = (
                Path(kwargs["env"]["HF_HOME"]) / storage_owner._FASTEMBED_CACHE_CHILD
            ).resolve()
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"owned": True, "root": str(cache_root), "error": None}),
                stderr="",
            )
        if len(command) > 2 and command[1] == "-c":
            env = kwargs["env"]
            Path(env["MEMPALACE_SOCKET_GUARD_LOADED"]).write_text("loaded\n", encoding="utf-8")
            module = (
                Path(command[0]).parent.parent / "site-packages" / "mempalace_code" / "__init__.py"
            )
            module.parent.mkdir()
            module.write_text("", encoding="utf-8")
            payload = {"metadata": "1.13.5", "module": str(module), "python": command[0]}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="golden passed", stderr="")

    return run


def _golden_runner_with_model_probe_diagnostic(
    calls: list[tuple[list[str], dict]], *, stderr: str, returncode: int = 0
):
    successful = _successful_golden_runner(calls)
    emitted = False

    def run(command, **kwargs):
        nonlocal emitted
        result = successful(command, **kwargs)
        normalized_command = [str(item) for item in command]
        if (
            not emitted
            and len(normalized_command) > 2
            and normalized_command[1:3] == ["-c", rrg.INSTALLED_MODEL_CACHE_PROBE]
        ):
            emitted = True
            return SimpleNamespace(
                returncode=returncode,
                stdout=result.stdout,
                stderr=stderr,
            )
        return result

    return run


def _compress_retry_runner(fault: str):
    state = {"compressed": False, "mixed": False, "exports": 0}

    def result(returncode=0, stdout="", stderr=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def run(command, **_kwargs):
        command = [str(item) for item in command]
        args = command[1:]
        if fault == "launch" and args[0] == "init":
            raise OSError("private launch path")
        if fault == "timeout" and args[0] == "init":
            raise subprocess.TimeoutExpired(command, 120)
        if args[0] == "init":
            if fault == "unexpected_exit":
                return result(1, stderr="init refused")
            stdout = "Config saved: fixture"
            if fault == "polluted_output":
                stdout += "\nTraceback (most recent call last)"
            stderr = "unexpected stderr" if fault == "normal_success_extra_stderr" else ""
            return result(stdout=stdout, stderr=stderr)

        palace = Path(args[1])
        palace.mkdir(parents=True, exist_ok=True)
        palace_marker = palace / "state.bin"
        if args[2] == "mine":
            if palace_marker.exists():
                state["mixed"] = True
                palace_marker.write_bytes(b"initial-mixed")
            else:
                palace_marker.write_bytes(b"initial")
            return result(stdout="Drawers filed: 2")

        if args[2] == "export":
            state["exports"] += 1
            export_path = Path(args[4])
            records: list[dict[str, object]] = [
                {"type": "drawer", "id": "one", "text": "first", "original_tokens": 0},
                {"type": "drawer", "id": "two", "text": "second", "original_tokens": 0},
            ]
            if state["compressed"]:
                records = [dict(record, original_tokens=10) for record in records]
            if state["mixed"]:
                records.append(
                    {
                        "type": "drawer",
                        "id": "three",
                        "text": "pending",
                        "original_tokens": 7 if state.get("mixed_compressed") else 0,
                    }
                )
            if fault == "null_original_tokens" and state["exports"] == 1:
                records[0]["original_tokens"] = None
            if fault == "string_original_tokens" and state["exports"] == 2:
                records[0]["original_tokens"] = "10"
            if fault == "boolean_original_tokens" and state["exports"] == 3:
                records[0]["original_tokens"] = True
            if fault == "negative_original_tokens" and state["exports"] == 4:
                records[-1]["original_tokens"] = -1
            if fault == "record_drift" and state["exports"] == 3:
                records[0]["text"] = "changed"
            header = {"type": "export_header", "drawer_count": len(records), "kg_count": 0}
            if fault == "count_mismatch" and state["exports"] == 1:
                header["drawer_count"] += 1
            if fault == "malformed_export" and state["exports"] == 1:
                export_path.write_text("{", encoding="utf-8")
            else:
                export_path.write_text(
                    "\n".join(json.dumps(value) for value in [header, *records]) + "\n",
                    encoding="utf-8",
                )
            stderr = (
                f"  Exporting from: {palace}\n"
                f"  Exported {len(records)} drawers, 0 KG triples → {export_path}\n"
            )
            if fault == "export_extra_stderr" and state["exports"] == 1:
                stderr += "unexpected stderr\n"
            return result(stderr=stderr)

        if args[2] == "compress":
            backup_root = palace.parent / "backups"
            if "--dry-run" in args:
                return result(stdout="Pending: 2\nskipped already compressed: 0\nTotal: 2")
            wing = args[args.index("--wing") + 1]
            if wing == "definitely-missing":
                stdout = "unexpected stdout" if fault == "unknown_wing_extra_stdout" else ""
                return result(
                    2,
                    stdout=stdout,
                    stderr=(
                        "\n  Unknown wing: 'definitely-missing'\n"
                        "  Next: run mempalace-code status, or check mempalace_list_wings / "
                        "mempalace_list_rooms / mempalace_get_taxonomy for valid taxonomy "
                        "identifiers — filters are validated against the palace taxonomy and "
                        "suggestions are advisory only.\n"
                    ),
                )
            backup_root.mkdir(exist_ok=True)
            if not state["compressed"]:
                archive = backup_root / "first.tar.gz"
                archive.write_bytes(b"first")
                state["compressed"] = True
                recovery_argv = [
                    "mempalace-code",
                    "--palace",
                    str(palace.resolve()),
                    "restore",
                    str(archive),
                    "--force",
                ]
                if fault == "recovery_wrong_order":
                    recovery_argv[3], recovery_argv[4] = recovery_argv[4], recovery_argv[3]
                elif fault == "recovery_wrong_flag":
                    recovery_argv[1] = "--palaces"
                elif fault == "recovery_different_palace":
                    different_palace = palace.parent / "different-palace"
                    different_palace.mkdir()
                    recovery_argv[2] = str(different_palace)
                elif fault == "recovery_different_archive":
                    different_archive = palace.parent / "different-archive"
                    different_archive.write_bytes(b"different")
                    recovery_argv[4] = str(different_archive)
                elif fault == "recovery_extra_tokens":
                    recovery_argv.append("extra")
                elif fault == "recovery_missing_palace":
                    recovery_argv[2] = str(palace.parent / "missing-palace")
                elif fault == "recovery_missing_archive":
                    recovery_argv[4] = str(palace.parent / "missing-archive")
                elif fault == "recovery_unresolvable_alias":
                    loop_a = palace.parent / "loop-a"
                    loop_b = palace.parent / "loop-b"
                    loop_a.symlink_to(loop_b)
                    loop_b.symlink_to(loop_a)
                    recovery_argv[2] = str(loop_a)
                elif fault == "canonical_recovery_alias":
                    palace_alias = palace.parent / "palace-alias"
                    archive_alias = palace.parent / "archive-alias"
                    palace_alias.symlink_to(palace, target_is_directory=True)
                    archive_alias.symlink_to(archive)
                    recovery_argv[2] = str(palace_alias)
                    recovery_argv[4] = str(archive_alias)
                return result(
                    stdout=(
                        f"Recovery archive: {archive}\n"
                        f"Recovery command: {shlex.join(recovery_argv)}\nStored and verified"
                    )
                )
            if state["mixed"]:
                (backup_root / "mixed.tar.gz").write_bytes(b"mixed")
                state["mixed_compressed"] = True
                return result(
                    stdout="Pending: 1\nskipped already compressed: 2\nStored and verified"
                )
            if fault == "backup_drift":
                (backup_root / "retry.tar.gz").write_bytes(b"retry")
            return result(stdout="Pending: 0\nskipped already compressed: 2")

        if args[2] == "search":
            stdout = "Results for: xylophonic_glyph_9182\nxylophonic_glyph_9182"
            if fault == "missing_search":
                stdout = "Results for: nothing"
            stderr = "unexpected stderr" if fault == "search_extra_stderr" else ""
            return result(stdout=stdout, stderr=stderr)
        raise AssertionError(f"unexpected command: {command}")

    return run


@pytest.mark.parametrize(
    "fault",
    [
        "unexpected_exit",
        "polluted_output",
        "normal_success_extra_stderr",
        "export_extra_stderr",
        "unknown_wing_extra_stdout",
        "search_extra_stderr",
        "null_original_tokens",
        "string_original_tokens",
        "boolean_original_tokens",
        "negative_original_tokens",
        "malformed_export",
        "count_mismatch",
        "record_drift",
        "recovery_wrong_order",
        "recovery_wrong_flag",
        "recovery_different_palace",
        "recovery_different_archive",
        "recovery_extra_tokens",
        "recovery_missing_palace",
        "recovery_missing_archive",
        "recovery_unresolvable_alias",
        "backup_drift",
        "missing_search",
        "launch",
        "timeout",
        "filesystem",
    ],
)
def test_installed_compress_retry_fails_closed(tmp_path, fault):
    repository_root = tmp_path / "missing-repository" if fault == "filesystem" else ROOT
    row = rrg._run_installed_compress_retry_scenario(
        ["mempalace-code"],
        {},
        tmp_path / "scenario",
        tmp_path / "neutral",
        repository_root=repository_root,
        run_subprocess=_compress_retry_runner(fault),
    )

    assert row["id"] == "installed_golden_compress_retry"
    assert row["status"] == "fail"
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == 1
    assert "Traceback (most recent call last)" not in row["detail"]
    assert str(tmp_path) not in row["detail"]


def test_installed_compress_retry_accepts_canonical_recovery_path_alias(tmp_path):
    row = rrg._run_installed_compress_retry_scenario(
        ["mempalace-code"],
        {},
        tmp_path / "scenario",
        tmp_path / "neutral",
        repository_root=ROOT,
        run_subprocess=_compress_retry_runner("canonical_recovery_alias"),
    )

    assert row == {
        "id": "installed_golden_compress_retry",
        "command": rrg.INSTALLED_COMPRESS_RETRY_COMMAND,
        "status": "pass",
        "detail": "dry-run, recovery, unchanged retry, refusal, mixed state, and search passed",
    }


@pytest.mark.parametrize(
    "fault",
    ["installed_owner_probe"],
)
def test_installed_fetch_model_scenario_fails_closed(tmp_path, fault, monkeypatch):
    if fault == "installed_owner_probe":
        hf_home = _write_model_cache(tmp_path / "hf")
        cache_root = hf_home / storage_owner._FASTEMBED_CACHE_CHILD
        env = {"HF_HOME": str(hf_home)}

        def probe(command, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"owned": True, "root": str(cache_root), "error": None}),
                stderr="",
            )

        root, detail = rrg._installed_model_cache_root(
            tmp_path / "venv" / "bin" / "python",
            env,
            tmp_path,
            run_subprocess=probe,
        )
        assert root == cache_root.resolve()
        assert "installed package validated" in detail
        return
    repository_root = tmp_path / "repository"
    if fault != "filesystem":
        repository_root.mkdir()
    source_hf_home = _write_model_cache(tmp_path / "source-hf")
    installed_faults = {
        "source_cache_drift",
        "source_cache_content_drift",
        "snapshot_race",
        "refs_main_named",
        "missing_named_snapshot",
        "escaping_named_snapshot",
        "symlink_snapshot",
        "symlink_swap",
        "escaping_symlink",
    }
    model_root = source_hf_home / rrg.MODEL_CACHE_RELATIVE
    named_snapshot = model_root / "snapshots" / "abc123"
    if fault == "refs_main_named":
        wrong_snapshot = model_root / "snapshots" / "000wrong"
        wrong_snapshot.mkdir()
        (wrong_snapshot / "config.json").write_text("wrong", encoding="utf-8")
    if fault == "missing_named_snapshot":
        (model_root / "refs" / "main").write_text("missing", encoding="utf-8")
    if fault == "escaping_named_snapshot":
        (model_root / "refs" / "main").write_text("../abc123", encoding="utf-8")
    if fault == "symlink_snapshot":
        (named_snapshot / "config-alias.json").symlink_to("config.json")
    if fault == "symlink_swap":
        (named_snapshot / "config-alias.json").symlink_to("config.json")
    if fault == "escaping_symlink":
        outside = tmp_path / "outside.json"
        outside.write_text("outside", encoding="utf-8")
        (named_snapshot / "escape.json").symlink_to(outside)
    if fault in {"repository_nested_drift", "repository_symlink"}:
        nested = repository_root / ".mempalace" / "nested"
        nested.mkdir(parents=True)
        (nested / "state.json").write_text("before", encoding="utf-8")
        if fault == "repository_symlink":
            (repository_root / ".mempalace" / "state-link.json").symlink_to("nested/state.json")
    env = (
        {
            "HF_HOME": str(source_hf_home),
            "MEMPALACE_TEST_INSTALLED_CLI": "mempalace-code",
        }
        if fault in installed_faults
        else {}
    )
    if fault == "socket":
        env["MEMPALACE_SOCKET_ATTEMPTS"] = str(tmp_path / "socket-attempts")
    calls = []
    original_copytree = shutil.copytree

    def copytree(source, target, *args, **kwargs):
        source = Path(source)
        target = Path(target)
        if fault == "symlink_swap" and target.name == "local-model":
            link = source / "config-alias.json"
            link.unlink()
            outside = tmp_path / "outside-race.json"
            outside.write_text("outside", encoding="utf-8")
            link.symlink_to(outside)
        return original_copytree(source, target, *args, **kwargs)

    monkeypatch.setattr(rrg.shutil, "copytree", copytree)

    def result(returncode=0, stdout="", stderr=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def run(command, **kwargs):
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        args = command[1:]
        model = Path(args[args.index("--model") + 1])
        is_default = model.name == "all-MiniLM-L6-v2"
        is_force = "--force" in args
        is_retry = model.name == "retry-model"

        if fault == "launch" and is_default:
            raise OSError("private launcher path")
        if fault == "path_exception" and is_default:
            raise OSError(f"cannot open {tmp_path / 'private-model'}")
        if fault == "timeout" and is_default:
            raise subprocess.TimeoutExpired(command, rrg.DEFAULT_TIMEOUT)
        if fault == "forbidden" and is_default:
            return result(stdout="Traceback (most recent call last)\nDone")
        if is_default:
            if fault == "cached":
                return result(stdout="Done")
            if fault == "source_cache_drift":
                source_file = next(path for path in source_hf_home.rglob("config.json"))
                source_file.write_text("changed", encoding="utf-8")
            if fault == "source_cache_content_drift":
                source_file = named_snapshot / "config.json"
                original = source_file.stat()
                source_file.write_text("[]", encoding="utf-8")
                os.utime(source_file, ns=(original.st_atime_ns, original.st_mtime_ns))
            return result(stdout="already available locally\nCached at: model\nDone\n")
        if is_force:
            if fault == "force":
                return result(returncode=1, stderr="force failed")
            return result(
                stdout=(
                    "Downloading model\nWaiting for model download\nLocal model path: model\nDone\n"
                )
            )
        if not is_retry:
            if fault == "local":
                return result(stdout="Done")
            if (
                fault == "refs_main_named"
                and (model / "config.json").read_text(encoding="utf-8") != "{}"
            ):
                return result(returncode=1, stderr="wrong snapshot selected")
            if fault == "symlink_snapshot" and (
                not (model / "config-alias.json").is_file()
                or (model / "config-alias.json").read_text(encoding="utf-8") != "{}"
            ):
                return result(returncode=1, stderr="snapshot symlink was not materialized safely")
            return result(stdout="already available locally\nLocal model path: model\nDone\n")
        if not model.exists():
            if fault == "offline":
                return result(stdout="Done\n")
            if fault == "target_residue":
                model.mkdir()
            return result(
                returncode=1,
                stdout="Downloading model\nWaiting for model download\n",
                stderr="Error preparing model: offline\n",
            )
        if fault == "retry":
            return result(returncode=1, stderr="retry failed")
        if fault == "retry_target_deleted":
            shutil.rmtree(model)
        if fault == "retry_target_content_drift":
            (model / "config.json").write_text("changed", encoding="utf-8")
        if fault == "repository_drift":
            (repository_root / ".mempalace").mkdir()
        if fault == "repository_nested_drift":
            (repository_root / ".mempalace" / "nested" / "state.json").write_text(
                "after!", encoding="utf-8"
            )
        if fault == "socket":
            Path(env["MEMPALACE_SOCKET_ATTEMPTS"]).write_text("blocked\n", encoding="utf-8")
        return result(stdout="already available locally\nLocal model path: model\nDone\n")

    stable_file_digest = rrg._stable_file_digest

    def race_aware_digest(path):
        if fault == "snapshot_race" and calls and path.is_relative_to(source_hf_home):
            raise OSError("tree entry changed while content was being hashed")
        return stable_file_digest(path)

    monkeypatch.setattr(rrg, "_stable_file_digest", race_aware_digest)

    row = rrg._run_installed_fetch_model_scenario(
        ["mempalace-code"],
        env,
        tmp_path / "scenario",
        tmp_path / "neutral",
        repository_root=repository_root,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_fetch_model"
    passing_faults = {"success", "refs_main_named", "symlink_snapshot", "repository_symlink"}
    assert row["status"] == ("pass" if fault in passing_faults else "fail")
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == (
        0 if fault in passing_faults else 1
    )
    assert "Traceback (most recent call last)" not in row["detail"]
    assert str(tmp_path) not in row["detail"]
    if fault in passing_faults:
        assert len(calls) == 5
        assert all(call[1]["cwd"] == str(tmp_path / "neutral") for call in calls)
        assert all(call[1]["timeout"] == rrg.DEFAULT_TIMEOUT for call in calls)
        assert all("PYTHONUNBUFFERED" not in call[1]["env"] for call in calls)


@pytest.mark.parametrize(
    "fault",
    [
        "success",
        "nonzero",
        "timeout",
        "wrong-counts",
        "nondeterministic-counts",
        "malformed-guidance",
        "missing-guidance",
        "accidental-summary-path",
        "byte-drift",
        "restore-guidance",
        "collision-sentinel",
        "collision-residue",
        "archive-mutation",
        "failed-version",
        "forbidden-output",
        "unbounded-output",
        "socket-attempt",
        "repository-drift",
        "filesystem-evaluation",
    ],
)
def test_installed_recovery_safety_scenario_fails_closed(tmp_path, monkeypatch, fault):
    if fault == "byte-drift":
        exercise = test_installed_recovery_safety_scenario_fails_closed
        for drift_fault in ("scenario-byte-drift", "neutral-cwd-drift", "environment-root-drift"):
            drift_root = tmp_path / drift_fault
            drift_root.mkdir()
            exercise(drift_root, monkeypatch, drift_fault)
        return
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    scenario_root, neutral_cwd = tmp_path / "scenario", tmp_path / "neutral"
    attempts = tmp_path / "socket-attempts.log"
    env_roots = {
        name: tmp_path / name.lower().replace("_", "-")
        for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
    }
    for root in env_roots.values():
        root.mkdir()
    console = tmp_path / "candidate-venv" / "bin" / "mempalace-code"
    calls = []
    dry_runs = 0

    def result(returncode=0, stdout="", stderr=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def run(command, **kwargs):
        nonlocal dry_runs
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        args = command[1:]
        if "import" in args and "--dry-run" in args:
            import_path = Path(args[args.index("import") + 1])
            if import_path.name == "malformed.jsonl":
                stderr = "Error: malformed JSONL input\n"
                if fault == "malformed-guidance":
                    stderr = "invalid input\n"
                return result(2, stderr=stderr)
            dry_runs += 1
            if dry_runs == 1 and fault == "timeout":
                raise subprocess.TimeoutExpired(command, 120)
            if dry_runs == 1 and fault == "nonzero":
                return result(1, stderr="import refused\n")
            drawers = 4 if fault == "wrong-counts" else 1
            if fault == "nondeterministic-counts" and dry_runs == 2:
                drawers = 2
            stdout = (
                f"Imported drawers:   {drawers}\nSkipped duplicates: 0\nImported KG triples:1\n"
            )
            if fault == "forbidden-output":
                stdout += "Traceback (most recent call last)\n"
            if fault == "unbounded-output":
                stdout += "x" * 4001
            if dry_runs == 1 and fault == "scenario-byte-drift":
                import_path.write_text("changed\n", encoding="utf-8")
            if dry_runs == 1 and fault == "neutral-cwd-drift":
                (neutral_cwd / "unexpected-state").write_text("changed\n", encoding="utf-8")
            if dry_runs == 1 and fault == "environment-root-drift":
                (env_roots["XDG_CONFIG_HOME"] / "unexpected-state").write_text(
                    "changed\n", encoding="utf-8"
                )
            if dry_runs == 1 and fault == "repository-drift":
                (repository_root / "unexpected.txt").write_text("changed\n", encoding="utf-8")
            return result(stdout=stdout)
        if args == ["status", "--palace", "--summary"]:
            if fault == "accidental-summary-path":
                (neutral_cwd / "--summary").write_text("unexpected\n", encoding="utf-8")
            stderr = "error: argument --palace: expected one argument\n"
            if fault == "missing-guidance":
                stderr = "usage error\n"
            return result(2, stderr=stderr)
        if "backup" in args:
            archive = Path(args[args.index("--out") + 1])
            archive.write_bytes(b"archive")
            return result(stdout=f"Backed up palace\nArchive: {archive}\n")
        if "restore" in args:
            archive = Path(args[-1])
            target = Path(args[args.index("--palace") + 1])
            if fault == "collision-sentinel":
                (target / "operator-state.txt").write_text("damaged", encoding="utf-8")
            if fault == "collision-residue":
                (target / "unexpected.txt").write_text("residue", encoding="utf-8")
            if fault == "archive-mutation":
                archive.write_bytes(b"changed")
            stderr = "Restore destination already contains state. Next: back up the reported destination state, then use --force.\n"
            if fault == "restore-guidance":
                stderr = "restore refused\n"
            return result(2, stderr=stderr)
        if args == ["--version"]:
            if fault == "socket-attempt":
                attempts.write_text("blocked connect\n", encoding="utf-8")
            if fault == "failed-version":
                return result(1, stderr="launcher failed\n")
            return result(stdout="mempalace-code 1.13.5\n")
        raise AssertionError(f"unexpected command: {command}")

    if fault == "filesystem-evaluation":
        monkeypatch.setattr(rrg, "_semantic_tree_snapshot", lambda _path: (_ for _ in ()).throw(OSError("snapshot unavailable")))  # fmt: skip
    env = {"SAFE": "1", **{name: str(root) for name, root in env_roots.items()}}
    row = rrg._run_installed_recovery_safety_scenario([str(console.resolve())], env, scenario_root, neutral_cwd, repository_root=repository_root, network_attempts=attempts, run_subprocess=run)  # fmt: skip
    assert row["id"] == "installed_golden_recovery_safety"
    assert row["status"] == ("pass" if fault == "success" else "fail")
    expected_recovery = 0 if fault == "success" else 1
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == expected_recovery
    assert str(tmp_path) not in row["detail"]
    assert len(row["detail"]) < 1400
    if fault == "success":
        assert len(calls) == 7
        assert all(command[0] == str(console.resolve()) for command, _kwargs in calls)
        assert all(kwargs["cwd"] == str(neutral_cwd) for _command, kwargs in calls)
        assert all(kwargs["env"] is env for _command, kwargs in calls)
        assert all(kwargs["timeout"] == rrg.DEFAULT_TIMEOUT for _command, kwargs in calls)


def test_installed_golden_env_disables_cuda_cache(tmp_path):
    temp_root = tmp_path / "installed-golden"
    temp_root.mkdir()

    env = rrg._installed_golden_env(
        {"PATH": os.environ.get("PATH", ""), "CUDA_CACHE_DISABLE": "0"},
        temp_root=temp_root,
        hf_home=tmp_path / "hf-home",
        console=tmp_path / "venv" / "bin" / "mempalace-code",
        marker=tmp_path / "socket-guard",
        attempts=tmp_path / "socket-attempts",
    )

    assert env["CUDA_CACHE_DISABLE"] == "1"


@pytest.mark.parametrize(
    "fault",
    [
        "success",
        "command-failure",
        "missing-diagnostic",
        "forbidden-output",
        "network-attempt",
        "repository-drift",
        "neutral-drift",
        "home-drift",
        "config-drift",
        "data-drift",
        "cache-drift",
        "nonzero-remine",
        "missing-owner",
        "malformed-owner",
        "retained-pid",
        "retained-token",
        "watcher-overflow",
        "watcher-exit",
        "watcher-stop",
    ],
)
def test_installed_non_regular_source_scenario(tmp_path, fault):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    scenario_root = tmp_path / "scenario"
    neutral_cwd = tmp_path / "neutral"
    neutral_cwd.mkdir()
    attempts = tmp_path / "socket-attempts.log"
    console = tmp_path / "candidate-venv" / "bin" / "mempalace-code"
    env_roots = {
        "HOME": tmp_path / "home",
        "USERPROFILE": tmp_path / "home",
        "XDG_CONFIG_HOME": tmp_path / "config",
        "XDG_DATA_HOME": tmp_path / "data",
        "XDG_CACHE_HOME": tmp_path / "cache",
    }
    for root in set(env_roots.values()):
        root.mkdir()
    env = {name: str(root) for name, root in env_roots.items()}
    pre_existing_lease_root = env_roots["HOME"] / ".mempalace"
    if fault == "success":
        pre_existing_lease_root.mkdir()
    calls = []
    project_mines = 0
    owners_path = env_roots["HOME"] / ".mempalace" / "operation.lock.owners.json"

    def diagnostics(source: Path) -> str:
        rows = []
        for path in sorted(source.iterdir()):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                kind = "symlink"
            elif stat.S_ISFIFO(mode):
                kind = "fifo"
            elif stat.S_ISSOCK(mode):
                kind = "socket"
            elif stat.S_ISDIR(mode) and path.suffix in {".py", ".txt"}:
                kind = "directory"
            else:
                continue
            rows.append(f"{path}: not a regular file ({kind})")
        return "\n".join(rows) + ("\n" if rows else "")

    def run(command, **kwargs):
        nonlocal project_mines
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        assert command[0] == str(console)
        assert kwargs["cwd"] == str(neutral_cwd)
        assert kwargs["env"] is env
        assert kwargs["timeout"] == rrg.DEFAULT_TIMEOUT
        args = command[1:]
        if args[0] == "init":
            if fault == "forbidden-output":
                return SimpleNamespace(
                    returncode=0,
                    stdout="Config saved:\nTraceback (most recent call last)\n",
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="Config saved:\n", stderr="")
        if "search" in args:
            term = args[args.index("search") + 1]
            if term == "xylophonic_glyph_9182":
                stdout = "Results for:\napp.py\n"
            elif term == "regular transcript remains searchable":
                stdout = "Results for:\nchat.txt\n"
                if fault == "network-attempt":
                    attempts.write_text("blocked connect\n", encoding="utf-8")
                if fault == "repository-drift":
                    (repository_root / "unexpected.txt").write_text("drift\n", encoding="utf-8")
                drift_roots = {
                    "neutral-drift": neutral_cwd,
                    "home-drift": env_roots["HOME"],
                    "config-drift": env_roots["XDG_CONFIG_HOME"],
                    "data-drift": env_roots["XDG_DATA_HOME"],
                    "cache-drift": env_roots["XDG_CACHE_HOME"],
                }
                if fault in drift_roots:
                    (drift_roots[fault] / "unexpected-state").write_text(
                        "drift\n", encoding="utf-8"
                    )
                if fault == "home-cache-drift":
                    (env_roots["HOME"] / ".nv" / "ComputeCache").mkdir(parents=True)
            else:
                stdout = ""
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if "mine-all" in args:
            project = scenario_root / "project"
            return SimpleNamespace(returncode=0, stdout="", stderr=diagnostics(project))
        if "mine" in args:
            source = Path(args[args.index("mine") + 1])
            control = "chat.txt" if "--mode" in args else "app.py"
            if "--mode" not in args:
                project_mines += 1
                if fault == "command-failure" and project_mines == 1:
                    return SimpleNamespace(returncode=2, stdout="", stderr="bounded failure\n")
            stderr = diagnostics(source)
            if fault == "missing-diagnostic" and project_mines == 1:
                stderr = "\n".join(
                    line for line in stderr.splitlines() if "blocked_symlink.py" not in line
                )
            drawers = 0 if "--mode" not in args and project_mines == 2 else 1
            if fault == "nonzero-remine" and project_mines == 2:
                drawers = 1
            return SimpleNamespace(
                returncode=0,
                stdout=f"Drawers filed: {drawers}\n{control}\n",
                stderr=stderr,
            )
        raise AssertionError(f"unexpected command: {command}")

    class Watcher:
        def __init__(self, command, **kwargs):
            project = Path(command[-2])
            summary = ["state=watch-ready\n"]
            if fault == "watcher-overflow":
                summary.append("x" * rrg.INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT + "\n")
            for path in sorted(project.iterdir()):
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    kind = "symlink"
                elif stat.S_ISFIFO(mode):
                    kind = "fifo"
                elif stat.S_ISSOCK(mode):
                    kind = "socket"
                elif stat.S_ISDIR(mode) and path.suffix == ".py":
                    kind = "directory"
                else:
                    continue
                summary.append(f"{path} ({kind})\n")
            summary.append("Watch stopped after 0 re-mine cycle(s), 0 event(s)\n")
            self.stdout = io.StringIO("".join(summary))
            self.pid = 4242
            self.returncode = 1 if fault == "watcher-exit" else None
            if fault != "missing-owner":
                owners_path.parent.mkdir(parents=True, exist_ok=True)
                if fault == "malformed-owner":
                    owners_path.write_text("not-json", encoding="utf-8")
                else:
                    owners_path.write_text(
                        json.dumps({"watcher-token": {"pid": self.pid}}), encoding="utf-8"
                    )

        def poll(self):
            return self.returncode

        def send_signal(self, _signal):
            self.returncode = 1 if fault == "watcher-stop" else 0
            if owners_path.exists() and fault != "malformed-owner":
                if fault == "retained-pid":
                    owners = {"watcher-token": {"pid": self.pid}}
                elif fault == "retained-token":
                    owners = {"watcher-token": {"pid": 9999}}
                else:
                    owners = {}
                owners_path.write_text(json.dumps(owners), encoding="utf-8")

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

        def kill(self):
            self.returncode = -9

    row = rrg._run_installed_non_regular_source_scenario(
        [str(console)],
        env,
        scenario_root,
        neutral_cwd,
        repository_root=repository_root,
        network_attempts=attempts,
        run_subprocess=run,
        popen=Watcher,
    )
    if fault == "success":
        assert row == rrg._make_row(
            "installed_golden_non_regular_sources",
            rrg.INSTALLED_NON_REGULAR_SOURCE_COMMAND,
            "pass",
            "project, remine, mine-all, watcher, and conversation paths rejected all supported "
            "non-regular source kinds",
        )
        assert any("mine-all" in command for command, _kwargs in calls)
        assert any("--mode" in command and "convos" in command for command, _kwargs in calls)
        assert pre_existing_lease_root.is_dir()

        failed = rrg._run_installed_non_regular_source_scenario(
            ["relative-console"],
            env,
            tmp_path / "unused-scenario",
            neutral_cwd,
            repository_root=repository_root,
        )
        assert failed["status"] == "fail"
        assert "absolute invoked launcher" in failed["detail"]
        assert failed["detail"].endswith(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}")
    else:
        assert row["status"] == "fail"
        assert str(tmp_path) not in row["detail"]
        assert row["detail"].endswith(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}")
        expected_marker = {
            "command-failure": "project mine failed",
            "missing-diagnostic": "omitted symlink diagnostic",
            "forbidden-output": "forbidden subprocess output detected",
            "network-attempt": "scenario attempted network access",
            "repository-drift": "repository-root artifact",
            "neutral-drift": "disposable root neutral cwd",
            "home-drift": "disposable root HOME",
            "home-cache-drift": "disposable root HOME at .nv",
            "config-drift": "disposable root XDG_CONFIG_HOME",
            "data-drift": "disposable root XDG_DATA_HOME",
            "cache-drift": "disposable root XDG_CACHE_HOME",
            "nonzero-remine": "project remine failed",
            "missing-owner": "watcher owner descriptor is missing",
            "malformed-owner": "watcher owner descriptor is malformed",
            "retained-pid": "watcher ownership survived clean exit",
            "retained-token": "watcher ownership survived clean exit",
            "watcher-overflow": "watcher output exceeded the bounded evidence limit",
            "watcher-exit": "watcher exited before state=watch-ready",
            "watcher-stop": "watcher did not stop cleanly",
        }[fault]
        assert expected_marker in row["detail"]
        if fault == "home-cache-drift":
            assert ".nv/ComputeCache" in row["detail"]

    if hasattr(socket, "AF_UNIX"):
        assert not any(
            stat.S_ISSOCK(path.lstat().st_mode)
            for path in scenario_root.rglob("*")
            if path.exists() or path.is_symlink()
        )


def test_non_regular_scenario_rejects_home_cache_drift(tmp_path):
    test_installed_non_regular_source_scenario(tmp_path, "home-cache-drift")


def _stub_direct_golden_scenarios(monkeypatch):
    monkeypatch.setattr(
        rrg,
        "_run_installed_extra_and_export_reconciliation",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_mcp_stdio_scenario",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_cli_inventory_gap_scenario",
        lambda *args, **kwargs: None,
    )
    recovery_safety = rrg._make_row(
        "installed_golden_recovery_safety", "installed recovery", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_recovery_safety_scenario",
        lambda *args, **kwargs: recovery_safety,
    )
    path_contracts = rrg._make_row(
        "installed_golden_path_contracts", "installed paths", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg, "_run_installed_path_contract_scenario", lambda *args, **kwargs: path_contracts
    )
    diary_blank = rrg._make_row(
        "installed_golden_diary_blank_required_fields",
        "installed diary blank fields",
        "pass",
        "complete",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_diary_blank_required_fields_scenario",
        lambda *args, **kwargs: diary_blank,
    )
    schedule_snippets = rrg._make_row(
        "installed_golden_schedule_snippets", "installed schedules", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_schedule_snippet_scenario",
        lambda *args, **kwargs: schedule_snippets,
    )
    alias_containment = rrg._make_row(
        "installed_golden_alias_containment", "installed alias containment", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_alias_target_containment_scenario",
        lambda *args, **kwargs: alias_containment,
    )
    watcher_signals = rrg._make_row(
        "installed_golden_watcher_signals", "installed watcher signals", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_watcher_signal_cleanup_scenario",
        lambda *args, **kwargs: watcher_signals,
    )
    workflow = rrg._make_row(
        "installed_golden_workflow_happy_path", "installed workflow", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_workflow_happy_path_scenario",
        lambda *args, **kwargs: workflow,
    )
    fetch_model = rrg._make_row(
        "installed_golden_fetch_model", "installed fetch model", "pass", "complete"
    )

    def run_fetch_model(*args, **kwargs):
        kwargs["run_subprocess"](
            [*args[0], "help"],
            capture_output=True,
            text=True,
            cwd=str(args[3]),
            env=args[1],
            timeout=rrg.DEFAULT_TIMEOUT,
        )
        return fetch_model

    monkeypatch.setattr(rrg, "_run_installed_fetch_model_scenario", run_fetch_model)
    read_failures = rrg._make_row(
        "installed_golden_read_failures", "installed read failures", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg, "_run_installed_read_failure_scenario", lambda *args, **kwargs: read_failures
    )
    convo = rrg._make_row(
        "installed_golden_convo_full_replace", "installed convo full", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg, "_run_installed_convo_full_replace_scenario", lambda *args, **kwargs: convo
    )
    cleanup = rrg._make_row(
        "installed_golden_cleanup_poststate", "installed cleanup", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg, "_run_installed_cleanup_poststate_scenario", lambda *args, **kwargs: cleanup
    )
    rollback = rrg._make_row(
        "installed_golden_rollback_no_candidate", "installed rollback", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg, "_run_installed_rollback_no_candidate_scenario", lambda *args, **kwargs: rollback
    )
    compress_retry = rrg._make_row(
        "installed_golden_compress_retry", "installed compress", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg, "_run_installed_compress_retry_scenario", lambda *args, **kwargs: compress_retry
    )
    split = rrg._make_row("installed_golden_split", "installed split", "pass", "complete")
    monkeypatch.setattr(rrg, "_run_installed_split_scenario", lambda *args, **kwargs: split)
    missing = rrg._make_row(
        "installed_golden_import_missing", "installed import", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg, "_run_installed_import_missing_scenario", lambda *args, **kwargs: missing
    )
    palace_rows = [
        rrg._make_row(f"installed_golden_palace_{case}", "installed palace", "pass", "complete")
        for case in ("order", "conflict", "duplicate", "option_value")
    ]
    monkeypatch.setattr(
        rrg, "_run_installed_palace_argument_scenarios", lambda *args, **kwargs: palace_rows
    )
    search_rows = [
        rrg._make_row(f"installed_golden_search_results_{case}", "search", "pass", "complete")
        for case in ("zero", "negative_one", "compact", "unknown_wing")
    ]
    monkeypatch.setattr(
        rrg, "_run_installed_search_results_scenarios", lambda *args, **kwargs: search_rows
    )
    version = rrg._make_row("installed_golden_version", "version", "pass", "complete")
    monkeypatch.setattr(rrg, "_run_installed_version_scenario", lambda *args, **kwargs: version)
    non_regular = rrg._make_row(
        "installed_golden_non_regular_sources", "non-regular sources", "pass", "complete"
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_non_regular_source_scenario",
        lambda *args, **kwargs: non_regular,
    )


def test_installed_search_results_scenario_covers_compact_success_and_unknown_wing(tmp_path):
    scenario_root = tmp_path / "scenario"
    project = scenario_root / "project"
    compact_source = project / "COMPACT.md"

    def completed(command, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    def successful_run(command, **_kwargs):
        args = command[1:]
        if args[-2:] in (["--results", "0"], ["--results", "-1"]):
            value = args[-1]
            return completed(
                command,
                2,
                stderr=f"mempalace-code search: error: argument --results: must be at least 1, got {value}\n",
            )
        if args[0] == "init":
            return completed(command, stdout="Config saved:\n")
        if "mine" in args:
            return completed(command, stdout="Drawers filed: 1\n")
        if "does-not-exist" in args:
            return completed(
                command,
                2,
                stderr="Unknown wing 'does-not-exist'.\nNext: choose an existing wing.\n",
            )
        preview = "compact_boundary_marker_9182 " + "v" * 267 + "..."
        source_arg = shlex.quote(str(compact_source))
        return completed(
            command,
            stdout=(
                "\n============================================================\n"
                '  Results for: "compact_boundary_marker_9182"\n'
                "  Wing: project\n"
                "============================================================\n\n"
                "  [1] project / documentation\n"
                f"      Source: {compact_source}\n"
                "      Match:  0.875\n"
                "      Lines:  1-4\n\n"
                f"      {preview}\n"
                f"      Recovery: mempalace-code read {source_arg} --start 1 --end 4 --wing project\n\n"
                "  ────────────────────────────────────────────────────────\n\n"
            ),
        )

    rows = rrg._run_installed_search_results_scenarios(
        ["mempalace-code"],
        {},
        scenario_root,
        tmp_path,
        run_subprocess=successful_run,
    )

    assert [row["id"] for row in rows] == [
        "installed_golden_search_results_zero",
        "installed_golden_search_results_negative_one",
        "installed_golden_search_results_compact",
        "installed_golden_search_results_unknown_wing",
    ]
    assert all(row["status"] == "pass" for row in rows)

    def oversized_unknown(command, **kwargs):
        result = successful_run(command, **kwargs)
        if "does-not-exist" in command:
            return completed(
                command, 2, stderr="Unknown wing does-not-exist. Next: retry. " + "x" * 3000
            )
        return result

    failed_rows = rrg._run_installed_search_results_scenarios(
        ["mempalace-code"],
        {},
        tmp_path / "failure-scenario",
        tmp_path,
        run_subprocess=oversized_unknown,
    )

    unknown_row = next(
        row for row in failed_rows if row["id"] == "installed_golden_search_results_unknown_wing"
    )
    assert unknown_row["status"] == "fail"
    assert len(unknown_row["detail"]) <= 1200


@pytest.mark.parametrize(
    "invalid_payload",
    [
        "not-json",
        json.dumps({"members": []}),
        json.dumps({"members": [["update"], ["update"]]}),
        json.dumps({"members": [["update", "apply"]]}),
        json.dumps({"members": [["unsafe/value"]]}),
        "x" * (rrg.INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT + 1),
    ],
    ids=(
        "malformed-json",
        "empty-members",
        "duplicate-members",
        "nested-command",
        "unsafe-command-segment",
        "oversized-output",
    ),
)
def test_installed_cli_inventory_reconciliation_fails_closed(tmp_path, invalid_payload):
    payload = json.dumps(
        {
            "members": [
                ["help"],
                ["fetch-model"],
                ["search"],
                ["update"],
                ["update", "scheduler"],
                ["update", "scheduler", "install"],
            ]
        }
    )
    members = rrg._parse_installed_cli_inventory(payload)
    assert members == (
        ("help",),
        ("fetch-model",),
        ("search",),
        ("update",),
        ("update", "scheduler"),
        ("update", "scheduler", "install"),
    )

    with pytest.raises(ValueError, match="installed CLI inventory"):
        rrg._parse_installed_cli_inventory(invalid_payload)
    with pytest.raises(ValueError, match="execution attribution"):
        rrg._parse_installed_cli_execution(json.dumps({"executed": [["unknown"]]}), members)

    console = tmp_path / "venv" / "bin" / "mempalace-code"
    console.parent.mkdir(parents=True)
    console.write_text("candidate", encoding="utf-8")
    recorder = rrg._InstalledCliExecutionRecorder(console)
    assert recorder.argv == []  # Discovery itself receives no execution credit.
    recorder.record([str(tmp_path / "ambient" / "mempalace-code"), "help"])
    recorder.record([str(console), "--version"])

    # The same recorder is used by ordinary subprocess and Popen launch wrappers.
    recorder.record([str(console), "help"])
    recorder.record([str(console), "fetch-model", "--model", "update"])
    recorder.record([str(console), "search", "update"])
    recorder.record(
        [str(console), "--palace", str(tmp_path / "palace"), "update", "scheduler", "install"]
    )
    assert json.loads(recorder.render()) == [
        ["--version"],
        ["help"],
        ["fetch-model", "--model", "update"],
        ["search", "update"],
        ["--palace", str(tmp_path / "palace"), "update", "scheduler", "install"],
    ]

    rows = [
        rrg._make_row(f"row-{index}", "command", "pass", f"detail-{index}") for index in range(25)
    ] + [
        rrg._make_row(
            "installed_golden_suite",
            rrg.INSTALLED_GOLDEN_COMMAND,
            "pass",
            "complete golden CLI suite passed offline from a neutral cwd",
        )
    ]
    covered = rrg._reconcile_installed_cli_inventory(rows, members, set(members))
    assert covered is rows
    assert len(covered) == 26
    assert covered[-1]["status"] == "pass"

    missing = rrg._reconcile_installed_cli_inventory(
        rows,
        members,
        {("help",), ("update",)},
    )
    assert len(missing) == 26
    assert missing[:-1] == rows[:-1]
    assert missing[-1]["id"] == "installed_golden_suite"
    assert missing[-1]["status"] == "fail"
    assert "update scheduler, update scheduler install" in missing[-1]["detail"]
    assert missing[-1]["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == 1
    assert str(tmp_path) not in missing[-1]["detail"]


def test_installed_cli_probe_attributes_only_recorded_parser_paths(tmp_path):
    probe_path = tmp_path / rrg.INSTALLED_CLI_INVENTORY_PROBE_NAME
    probe_path.write_text(rrg.INSTALLED_CLI_INVENTORY_PROBE, encoding="utf-8")
    inventory = subprocess.run(
        [sys.executable, str(probe_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    members = rrg._parse_installed_cli_inventory(inventory.stdout)
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            [
                ["fetch-model", "--model", "update"],
                ["search", "update"],
                ["--palace", str(tmp_path / "palace"), "update", "scheduler", "install"],
                ["watch", str(tmp_path / "project"), "schedule"],
                ["help"],
            ]
        ),
        encoding="utf-8",
    )
    attribution = subprocess.run(
        [sys.executable, str(probe_path), str(trace_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    executed = rrg._parse_installed_cli_execution(attribution.stdout, members)
    assert executed == {
        ("fetch-model",),
        ("search",),
        ("update",),
        ("update", "scheduler"),
        ("update", "scheduler", "install"),
        ("watch",),
        ("watch", "schedule"),
        ("help",),
    }


def test_installed_mcp_stdio_inventory_and_semantics(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    venv = tmp_path / "candidate-venv"
    launcher = venv / "bin" / "mempalace-code-mcp"
    console = venv / "bin" / "mempalace-code"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    console.write_text("#!/bin/sh\n", encoding="utf-8")
    console.chmod(0o755)
    registry_module = venv / "lib" / "mempalace_code" / "mcp" / "registry.py"
    profiles_module = venv / "lib" / "mempalace_code" / "mcp_tool_profiles.py"
    registry_module.parent.mkdir(parents=True)
    registry_module.write_text("", encoding="utf-8")
    profiles_module.write_text("", encoding="utf-8")

    tools = tuple(rrg._installed_mcp_recipe(tmp_path / "unused-project"))
    raw_profiles = [
        {"name": "minimal", "members": list(tools[:4])},
        {"name": "kg", "members": list(tools[:8])},
        {"name": "code", "members": list(tools[8:18])},
        {"name": "notes", "members": list(tools[18:])},
        {"name": "full", "members": list(tools)},
    ]
    inventory = json.dumps(
        {
            "registry_module": str(registry_module),
            "profiles_module": str(profiles_module),
            "tools": list(tools),
            "profiles": raw_profiles,
        }
    )
    discovered_tools, profiles = rrg._parse_installed_mcp_inventory(
        inventory, venv=venv, repository_root=repository
    )
    assert discovered_tools == tools
    assert [name for name, _members in profiles] == [
        "minimal",
        "kg",
        "code",
        "notes",
        "full",
    ]
    with pytest.raises(ValueError, match="exactly 29"):
        rrg._parse_installed_mcp_inventory(
            json.dumps(
                {
                    "registry_module": str(registry_module),
                    "profiles_module": str(profiles_module),
                    "tools": list(tools[:-1]),
                    "profiles": raw_profiles,
                }
            ),
            venv=venv,
            repository_root=repository,
        )

    profile_members = dict(profiles)
    calls = []

    def semantic_payload(name):
        marker = "xylophonic_mcp_inventory_9182"
        payloads = {
            "mempalace_status": {"total_drawers": 4, "wings": {"seed_main": 1}},
            "mempalace_list_wings": {"wings": {"seed_delete_wing": 1}},
            "mempalace_list_rooms": {"wing": "seed_main", "rooms": {"shared_room": 1}},
            "mempalace_get_taxonomy": {"taxonomy": {"seed_graph": {"shared_room": 1}}},
            "mempalace_kg_query": {
                "entity": "SeedEntity",
                "facts": [{"predicate": "preserves", "object": "SeedObject"}],
            },
            "mempalace_kg_add": {"success": True, "triple_id": "triple-1"},
            "mempalace_kg_invalidate": {"success": True, "ended": "2026-01-01"},
            "mempalace_kg_timeline": {"entity": "SeedEntity", "count": 1},
            "mempalace_kg_stats": {"triples": 3, "relationship_types": ["preserves"]},
            "mempalace_find_implementations": {"implementations": [{"type": "SeedService"}]},
            "mempalace_find_references": {
                "references": {"depends_on": [{"type": "SeedDependency"}]}
            },
            "mempalace_show_project_graph": {
                "graph": {"depends_on": [{"subject": "SeedProject", "object": "SeedDependency"}]}
            },
            "mempalace_show_type_dependencies": {
                "type": "SeedService",
                "ancestors": [{"type": "SeedInterface"}],
            },
            "mempalace_explain_subsystem": {"entry_points": [{"symbol_name": "SeedService"}]},
            "mempalace_extract_reusable": {"graph": {"core": [{"entity": "SeedDependency"}]}},
            "mempalace_traverse": [{"room": "shared_room", "wings": ["seed_main", "seed_graph"]}],
            "mempalace_find_tunnels": [{"room": "shared_room"}],
            "mempalace_graph_stats": {"tunnel_rooms": 1, "total_rooms": 2},
            "mempalace_search": {"results": [{"text": marker}]},
            "mempalace_code_search": {"results": [{"text": marker}]},
            "mempalace_file_context": {"total": 1, "chunks": [{"content": marker}]},
            "mempalace_check_duplicate": {
                "is_duplicate": True,
                "matches": [{"id": "mcp-seed-main"}],
            },
            "mempalace_read": {
                "source_file": "fixture.py",
                "lines": [{"text": marker}],
            },
            "mempalace_add_drawer": {"success": True, "wing": "added_wing"},
            "mempalace_delete_drawer": {"success": True, "drawer_id": "mcp-delete-drawer"},
            "mempalace_delete_wing": {"success": True, "deleted_count": 1},
            "mempalace_mine": {"success": True, "drawers_filed": 1},
            "mempalace_diary_write": {"success": True, "topic": "release"},
            "mempalace_diary_read": {"entries": [{"content": "mcp diary poststate marker 9182"}]},
        }
        return payloads[name]

    def tool_response(request, payload):
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }

    for tool_name in tools:
        rrg._validate_installed_mcp_semantics(tool_name, semantic_payload(tool_name))
        with pytest.raises(ValueError, match=tool_name):
            rrg._validate_installed_mcp_semantics(tool_name, {})

    def run_session(_launcher, profile, batches, _env, _cwd, **_kwargs):
        calls.append((profile, batches))
        responses = []
        primary_seen = set()
        for item in [entry for batch in batches for entry in batch]:
            if item == "":
                continue
            if item == "{malformed":
                responses.append({"jsonrpc": "2.0", "id": None, "error": {"code": -32700}})
                continue
            method = item["method"]
            if method == "initialize":
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": item["id"],
                        "result": {"serverInfo": {"name": "mempalace-code"}},
                    }
                )
            elif method == "tools/list":
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": item["id"],
                        "result": {"tools": [{"name": name} for name in profile_members[profile]]},
                    }
                )
            elif method == "unknown/method":
                responses.append({"jsonrpc": "2.0", "id": item["id"], "error": {"code": -32601}})
            else:
                name = item["params"]["name"]
                arguments = item["params"]["arguments"]
                if name not in primary_seen:
                    payload = semantic_payload(name)
                    primary_seen.add(name)
                elif name == "mempalace_check_duplicate":
                    payload = {"is_duplicate": arguments["content"].startswith("mcp added")}
                elif name == "mempalace_file_context":
                    payload = {"total": 0, "chunks": []}
                elif name == "mempalace_list_wings":
                    payload = {"wings": {"added_wing": 1}}
                elif name == "mempalace_kg_query" and arguments["entity"] == "AddedEntity":
                    payload = {"facts": [{"predicate": "verifies", "object": "AddedObject"}]}
                elif name == "mempalace_kg_query":
                    payload = {
                        "facts": [
                            {
                                "predicate": "preserves",
                                "object": "SeedObject",
                                "current": False,
                                "valid_to": "2026-01-01",
                            }
                        ]
                    }
                else:
                    payload = {"results": [{"text": "go-fixture-marker"}]}
                responses.append(tool_response(item, payload))
        return 0, "".join(json.dumps(response) + "\n" for response in responses), ""

    env_root = tmp_path / "env"
    env = {}
    for name, child in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        path = env_root / child
        path.mkdir(parents=True)
        env[name] = str(path)
    env["TMPDIR"] = str(env_root)
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    attempts = tmp_path / "network-attempts.log"

    def seed_runner(command, **_kwargs):
        if "import" in command:
            return SimpleNamespace(
                returncode=0,
                stdout="Imported drawers:   4\nImported KG triples:3\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="Config saved", stderr="")

    smoke = rrg._load_sibling(
        "_release_install_metadata_mcp_contract_test",
        "release_install_metadata_smoke.py",
    )

    failure = rrg._run_installed_mcp_stdio_scenario(
        launcher,
        console,
        discovered_tools,
        profiles,
        env,
        tmp_path / "scenario",
        neutral,
        repository_root=repository,
        venv=venv,
        network_attempts=attempts,
        smoke=smoke,
        run_subprocess=seed_runner,
        run_session=run_session,
    )
    assert failure is None
    assert [profile for profile, _batches in calls] == [name for name, _members in profiles]
    full_batches = calls[-1][1]
    requested = {
        item["params"]["name"]
        for batch in full_batches
        for item in batch
        if isinstance(item, dict) and item.get("method") == "tools/call"
    }
    assert requested == set(discovered_tools)
    assert len(discovered_tools) == 29

    def invalid_envelope_session(*args, **kwargs):
        returncode, stdout, stderr = run_session(*args, **kwargs)
        responses = [json.loads(line) for line in stdout.splitlines()]
        responses[0].pop("jsonrpc")
        return returncode, "".join(json.dumps(row) + "\n" for row in responses), stderr

    invalid_envelope = rrg._run_installed_mcp_stdio_scenario(
        launcher,
        console,
        discovered_tools,
        profiles,
        env,
        tmp_path / "scenario-invalid-envelope",
        neutral,
        repository_root=repository,
        venv=venv,
        network_attempts=attempts,
        smoke=smoke,
        run_subprocess=seed_runner,
        run_session=invalid_envelope_session,
    )
    assert invalid_envelope is not None
    assert "invalid jsonrpc" in invalid_envelope

    def protected_mutation_session(*args, **kwargs):
        returncode, stdout, stderr = run_session(*args, **kwargs)
        Path(args[3]["HOME"], "unexpected-marker").write_text("changed", encoding="utf-8")
        return returncode, stdout, stderr

    protected_mutation = rrg._run_installed_mcp_stdio_scenario(
        launcher,
        console,
        discovered_tools,
        profiles,
        env,
        tmp_path / "scenario-protected-mutation",
        neutral,
        repository_root=repository,
        venv=venv,
        network_attempts=attempts,
        smoke=smoke,
        run_subprocess=seed_runner,
        run_session=protected_mutation_session,
    )
    assert protected_mutation is not None
    assert "protected" in protected_mutation


@pytest.mark.parametrize(
    "fault",
    [
        "success",
        "wrong-exit",
        "stdout",
        "wrong-guidance",
        "forbidden-output",
        "unbounded-output",
        "palace-poststate",
        "repository-poststate",
        "network-attempt",
    ],
)
def test_installed_diary_blank_required_fields_scenario(tmp_path, monkeypatch, fault):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    scenario_root = tmp_path / "scenario"
    neutral_cwd = tmp_path / "neutral"
    network_attempts = tmp_path / "socket-attempts.log"
    console = tmp_path / "candidate-venv" / "bin" / "mempalace-code"
    calls = []

    def run(command, **kwargs):
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        option = command[5]
        stderr = (
            f"Error: {option} must not be blank.\n"
            "Try: mempalace-code diary write --agent agent-name "
            "--entry 'your diary entry'\n"
        )
        if len(calls) == 1:
            if fault == "wrong-exit":
                return SimpleNamespace(returncode=1, stdout="", stderr=stderr)
            if fault == "stdout":
                return SimpleNamespace(returncode=2, stdout="unexpected\n", stderr=stderr)
            if fault == "wrong-guidance":
                return SimpleNamespace(returncode=2, stdout="", stderr="wrong\n")
            if fault == "forbidden-output":
                return SimpleNamespace(
                    returncode=2, stdout="", stderr="Traceback (most recent call last)\n"
                )
            if fault == "unbounded-output":
                return SimpleNamespace(returncode=2, stdout="x" * 4001, stderr=stderr)
            if fault == "palace-poststate":
                Path(command[2]).mkdir(parents=True)
            if fault == "repository-poststate":
                (repository_root / "unexpected.txt").write_text("changed\n", encoding="utf-8")
            if fault == "network-attempt":
                network_attempts.write_text("blocked connect\n", encoding="utf-8")
        return SimpleNamespace(returncode=2, stdout="", stderr=stderr)

    env = {"SAFE": "1"}
    row = rrg._run_installed_diary_blank_required_fields_scenario(
        [str(console)],
        env,
        scenario_root,
        neutral_cwd,
        repository_root=repository_root,
        network_attempts=network_attempts,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_diary_blank_required_fields"
    if fault == "success":
        assert row["status"] == "pass", row["detail"]
        assert len(calls) == 8
        expected_cases = [
            ("--agent", "", "--entry", "valid entry"),
            ("--agent", "   ", "--entry", "valid entry"),
            ("--entry", "", "--agent", "valid-agent"),
            ("--entry", "   ", "--agent", "valid-agent"),
        ]
        assert [tuple(command[5:9]) for command, _kwargs in calls[::2]] == expected_cases
        assert all(command[9:] == ["--topic", ""] for command, _kwargs in calls)
        assert all(command[0] == str(console.resolve()) for command, _kwargs in calls)
        assert all(kwargs["cwd"] == str(neutral_cwd) for _command, kwargs in calls)
        assert all(kwargs["env"] is env for _command, kwargs in calls)
        assert all(kwargs["timeout"] == rrg.DEFAULT_TIMEOUT for _command, kwargs in calls)

        _stub_direct_golden_scenarios(monkeypatch)
        orchestrated_calls = []
        direct_row = rrg._make_row(
            "installed_golden_diary_blank_required_fields",
            rrg.INSTALLED_DIARY_BLANK_REQUIRED_FIELDS_COMMAND,
            "pass",
            "complete",
        )

        def run_direct(*args, **kwargs):
            orchestrated_calls.append((args, kwargs))
            return direct_row

        monkeypatch.setattr(rrg, "_run_installed_diary_blank_required_fields_scenario", run_direct)
        wheel = _write_candidate_wheel(tmp_path)
        cache = _write_model_cache(tmp_path / "hf")
        golden_calls = []
        rows = rrg._run_installed_golden_wheel(
            repository_root,
            wheel,
            base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
            run_subprocess=_successful_golden_runner(golden_calls),
        )

        assert [item["id"] for item in rows][2:5] == [
            "installed_golden_recovery_safety",
            "installed_golden_path_contracts",
            "installed_golden_diary_blank_required_fields",
        ]
        assert len(orchestrated_calls) == 1
        direct_args, direct_kwargs = orchestrated_calls[0]
        assert Path(direct_args[0][0]).is_absolute()
        assert Path(direct_args[3]).name == "neutral"
        assert direct_args[1]["MEMPALACE_TEST_INSTALLED_CLI"] == direct_args[0][0]
        assert direct_kwargs["repository_root"] == repository_root
        assert Path(direct_kwargs["network_attempts"]).name == "socket-attempts.log"
        assert all(Path(command[0]).name != "pytest" for command, _kwargs in golden_calls)
        assert all(command[1:3] != ["-m", "pytest"] for command, _kwargs in golden_calls)
        assert all(
            "test_cli_golden_scenarios" not in str(argument)
            for command, _kwargs in golden_calls
            for argument in command
        )
    else:
        assert row["status"] == "fail"
        assert row["detail"].endswith(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}")
        assert len(row["detail"]) < 1400


@pytest.mark.parametrize(
    "fault",
    [
        "success",
        "command-failure",
        "timeout",
        "malformed-refusal",
        "wrong-confirmation",
        "forbidden-output",
        "unbounded-output",
        "implicit-init-artifact",
        "dry-run-mutation",
        "diary-echo",
        "failed-recovery",
        "update-residue",
        "ambient-path-residue",
        "socket-attempt",
        "repository-drift",
        "filesystem-evaluation",
    ],
)
def test_installed_path_contract_scenario_fails_closed(tmp_path, monkeypatch, fault):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    scenario_root = tmp_path / "scenario"
    neutral = tmp_path / "neutral"
    attempts = tmp_path / "socket-attempts.log"
    home = tmp_path / "home"
    userprofile = tmp_path / "userprofile"
    xdg_config = tmp_path / "xdg-config"
    xdg_data = tmp_path / "xdg-data"
    xdg_cache = tmp_path / "xdg-cache"
    for root in (home, userprofile, xdg_config, xdg_data, xdg_cache):
        root.mkdir()
    console = tmp_path / "candidate" / "bin" / "mempalace-code"
    console.parent.mkdir(parents=True)
    console.write_text("console\n", encoding="utf-8")
    calls = []

    def result(returncode=0, stdout="", stderr=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    diary_entry = (
        "reconcilable diary poststate with a deliberately long body that must never be "
        "echoed in full by the mutation acknowledgement"
    )

    def run(command, **kwargs):
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        args = command[1:]
        if args[0] == "init":
            if fault == "timeout":
                raise subprocess.TimeoutExpired(command, rrg.DEFAULT_TIMEOUT)
            project = Path(args[1])
            (project / "mempalace.yaml").write_text("wing: initialized-only\n", encoding="utf-8")
            if fault == "implicit-init-artifact":
                (project / ".git").mkdir()
            if fault == "command-failure":
                return result(returncode=1, stderr="bounded init failure")
            if fault == "forbidden-output":
                return result(stdout="Config saved:\nTraceback (most recent call last)\n")
            if fault == "unbounded-output":
                return result(stdout="Config saved:\n" + "x" * 5000)
            return result(stdout="Config saved:\n")
        if "mine-all" in args:
            if fault == "dry-run-mutation":
                Path(args[args.index("--palace") + 1]).mkdir()
            return result(stdout="Dry run: discovered initialized-only\n")
        if "diary" in args and "write" in args:
            palace = Path(args[args.index("--palace") + 1])
            palace.mkdir()
            (palace / "diary-state.bin").write_bytes(b"stable diary")
            acknowledgement = (
                "Diary entry stored.\n"
                "ID: diary_wing_contract-agent_123\n"
                "Wing: wing_contract-agent\n"
                "Room: diary\n"
                "Topic: release-contract\n"
                "Verify before retry: search the entry\n"
            )
            if fault == "diary-echo":
                acknowledgement += diary_entry
            return result(stdout=acknowledgement)
        if "search" in args:
            if fault == "failed-recovery":
                return result(stdout="Results for: missing\n")
            return result(stdout=f"Results for: query\n{diary_entry}\n")
        if args[0] == "update":
            if fault == "update-residue":
                (scenario_root / "update-state.json").write_text("{}\n", encoding="utf-8")
            if fault == "ambient-path-residue":
                (xdg_config / "update-state.json").write_text("{}\n", encoding="utf-8")
            if fault == "socket-attempt":
                attempts.write_text("blocked socket\n", encoding="utf-8")
            if fault == "repository-drift":
                (repository_root / "unexpected.txt").write_text("changed\n", encoding="utf-8")
            if fault == "malformed-refusal":
                return result(returncode=2, stdout="{bad json")
            payload = {
                "ok": False,
                "stage": "wrong" if fault == "wrong-confirmation" else "confirmation",
                "exit_code": 2,
                "recovery_command": "mempalace-code update apply --yes --json",
            }
            return result(returncode=2, stdout=json.dumps(payload))
        raise AssertionError(f"unexpected command: {command}")

    if fault == "filesystem-evaluation":
        real_snapshot = rrg._semantic_tree_snapshot

        def failing_snapshot(path):
            if path == scenario_root:
                raise OSError("private snapshot path")
            return real_snapshot(path)

        monkeypatch.setattr(rrg, "_semantic_tree_snapshot", failing_snapshot)

    row = rrg._run_installed_path_contract_scenario(
        [str(console.resolve())],
        {
            "SAFE": "1",
            "HOME": str(home),
            "USERPROFILE": str(userprofile),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "XDG_CACHE_HOME": str(xdg_cache),
        },
        scenario_root,
        neutral,
        repository_root=repository_root,
        network_attempts=attempts,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_path_contracts"
    assert row["status"] == ("pass" if fault == "success" else "fail")
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == (
        0 if fault == "success" else 1
    )
    assert str(tmp_path) not in row["detail"]
    assert len(row["detail"]) <= 2000
    assert all(call[0][0] == str(console.resolve()) for call in calls)
    assert all(call[1]["cwd"] == str(neutral) for call in calls)
    assert all(call[1]["env"]["SAFE"] == "1" for call in calls)
    assert all(call[1]["timeout"] == rrg.DEFAULT_TIMEOUT for call in calls)
    if fault == "success":
        assert len(calls) == 7


@pytest.mark.parametrize(
    "fault",
    [
        "success",
        "wrong-provenance",
        "missing-alias",
        "ambient-mutation",
        "collision-overwrite",
        "collision-accepted",
        "retry-mutation",
        "polluted-output",
        "oversized-output",
        "launch-error",
        "timeout",
        "filesystem-error",
        "repository-drift",
        "cleanup-failure",
    ],
)
def test_installed_alias_target_containment_fails_closed(tmp_path, monkeypatch, fault):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    expected_canonical = tmp_path / "candidate" / "mempalace-code"
    expected_canonical.parent.mkdir()
    expected_canonical.write_text("console\n", encoding="utf-8")
    expected_canonical.chmod(0o755)
    calls = []
    target_calls = 0

    def result(returncode=0, stdout="", stderr=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def run(command, **kwargs):
        nonlocal target_calls
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        target_dir = Path(command[-1])
        alias = target_dir / "mempalace"
        ambient_bin = Path(kwargs["env"]["PATH"].split(os.pathsep)[0])
        if fault == "launch-error" and not calls[:-1]:
            raise OSError(f"private launch path {tmp_path}")
        if fault == "timeout" and not calls[:-1]:
            raise subprocess.TimeoutExpired(command, rrg.DEFAULT_TIMEOUT)
        if target_dir.name == "target-bin":
            target_calls += 1
            if target_calls == 1:
                if fault == "filesystem-error":

                    def fail_readlink(_path):
                        raise OSError("filesystem evaluation refused")

                    monkeypatch.setattr(rrg.os, "readlink", fail_readlink)
                elif fault != "missing-alias":
                    target = (
                        expected_canonical.parent / "wrong-console"
                        if fault == "wrong-provenance"
                        else expected_canonical
                    )
                    if target.name == "wrong-console":
                        target.write_text("wrong\n", encoding="utf-8")
                    alias.symlink_to(target)
                if fault == "ambient-mutation":
                    (ambient_bin / "mempalace").unlink()
                if fault == "repository-drift":
                    (repository_root / "unexpected.txt").write_text("drift\n", encoding="utf-8")
            elif fault == "retry-mutation":
                alias.unlink()
                alias.symlink_to(expected_canonical.parent / "wrong-console")
            stdout = f"  Alias ready: {alias} -> mempalace-code\n"
            if fault == "polluted-output" and target_calls == 1:
                stdout += "Traceback (most recent call last)\n"
            if fault == "oversized-output" and target_calls == 1:
                stdout += "x" * 1300
            return result(stdout=stdout)

        if fault == "collision-overwrite":
            alias.write_text("overwritten\n", encoding="utf-8")
        if fault == "collision-accepted":
            return result(stdout=f"  Alias ready: {alias} -> mempalace-code\n")
        return result(1, stderr=f"  Error: {alias} already exists; not overwriting\n")

    if fault == "cleanup-failure":
        real_temporary_directory = rrg.tempfile.TemporaryDirectory

        class CleanupFailure:
            def __init__(self, *args, **kwargs):
                self._manager = real_temporary_directory(*args, **kwargs)
                self.name = self._manager.name

            def cleanup(self):
                self._manager.cleanup()
                raise OSError("cleanup refused")

        monkeypatch.setattr(rrg.tempfile, "TemporaryDirectory", CleanupFailure)

    row = rrg._run_installed_alias_target_containment_scenario(
        [str(expected_canonical)],
        expected_canonical,
        {"PATH": "/usr/bin", "SAFE": "1"},
        tmp_path / "alias-containment-scenario",
        tmp_path / "neutral",
        repository_root=repository_root,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_alias_containment"
    assert row["status"] == ("pass" if fault == "success" else "fail")
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == (
        0 if fault == "success" else 1
    )
    assert len(row["detail"]) <= rrg._DETAIL_LIMIT
    assert str(tmp_path) not in row["detail"]
    assert "Traceback (most recent call last)" not in row["detail"]
    if calls:
        assert all(Path(command[0]).is_absolute() for command, _kwargs in calls)
        assert all(kwargs["cwd"] == str(tmp_path / "neutral") for _command, kwargs in calls)
        assert all(kwargs["timeout"] == rrg.DEFAULT_TIMEOUT for _command, kwargs in calls)
        assert all(kwargs["env"]["SAFE"] == "1" for _command, kwargs in calls)
    if fault == "success":
        assert [Path(command[-1]).name for command, _kwargs in calls] == [
            "target-bin",
            "target-bin",
            "collision-bin",
        ]


def _mock_artifact_rows_ok() -> list[dict]:
    return [
        rrg._make_row("artifact_wheel_present", "artifact-gate:wheel-present", "pass", "test.whl"),
        rrg._make_row(
            "artifact_sdist_present", "artifact-gate:sdist-present", "pass", "test.tar.gz"
        ),
        rrg._make_row("artifact_wheel_members", "artifact-gate:wheel-members", "pass", "test.whl"),
        rrg._make_row(
            "artifact_sdist_members", "artifact-gate:sdist-members", "pass", "test.tar.gz"
        ),
        rrg._make_row("artifact_twine_check", "artifact-gate:twine-check", "pass", "PASSED"),
    ]


def _mock_artifact_rows_fail() -> list[dict]:
    return [
        rrg._make_row("artifact_wheel_present", "artifact-gate:wheel-present", "pass", "test.whl"),
        rrg._make_row(
            "artifact_sdist_present", "artifact-gate:sdist-present", "fail", "no .tar.gz found"
        ),
    ]


def _admission_git_ok(args: list[str]) -> tuple[int, str, str]:
    if args[:3] == ["ls-remote", "--tags", "--refs"]:
        return 0, f"{SHA}\trefs/tags/v1.2.3\n", ""
    return 0, "", ""


def _admission_http_ok(_url: str) -> tuple[int, bytes, str]:
    data = {
        "releases": {
            "1.2.3": [
                {"packagetype": "bdist_wheel"},
                {"packagetype": "sdist"},
            ]
        }
    }
    return 200, json.dumps(data).encode(), ""


def _branch_rules_ok() -> list[dict[str, object]]:
    """Shape of GET /repos/{repo}/rules/branches/{branch}: effective rules only."""
    return [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "release-required"}]},
        },
    ]


def _ruleset_summaries_ok() -> list[dict[str, object]]:
    """Shape of GET /repos/{repo}/rulesets: summaries carry no rules or conditions."""
    return [
        {"id": 11, "name": "public-v-tags-restricted", "target": "tag", "enforcement": "active"}
    ]


def _ruleset_detail_ok() -> dict[str, object]:
    """Shape of GET /repos/{repo}/rulesets/{id}: rules and conditions are here."""
    return {
        "id": 11,
        "name": "public-v-tags-restricted",
        "target": "tag",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
        "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
    }


def _audit_run(conclusion: str = "success", age_hours: int = 1) -> dict[str, object]:
    """A dependency-audit run stamped relative to now, never to a fixed date.

    A hardcoded timestamp would age past the freshness window and silently turn
    this fixture into a time bomb.
    """
    stamp = datetime.now(UTC) - timedelta(hours=age_hours)
    return {
        "status": "completed",
        "conclusion": conclusion,
        "event": "schedule",
        "updatedAt": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _admission_github_ok(query) -> tuple[int, str, str]:
    if query.endpoint == "github_check_runs":
        data = {
            "total_count": 1,
            "check_runs": [
                {
                    "name": "release-required",
                    "head_sha": SHA,
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
        return 0, json.dumps(data), ""
    if query.endpoint == "github_branch_rules":
        return 0, json.dumps(_branch_rules_ok()), ""
    if query.endpoint == "github_ruleset":
        return 0, json.dumps(_ruleset_detail_ok()), ""
    if query.endpoint == "github_rulesets":
        return 0, json.dumps(_ruleset_summaries_ok()), ""
    if query.endpoint == "github_releases":
        return 0, json.dumps([{"tagName": "v1.2.3", "isDraft": False}]), ""
    if query.endpoint == "github_workflow_runs" and query.values[1] == "Dependency Audit":
        return 0, json.dumps([_audit_run()]), ""
    return 0, "[]", ""


def _admission_public_read(
    git_read=_admission_git_ok, github_read=_admission_github_ok, http_read=_admission_http_ok
):
    def read(query):
        if query.endpoint == "github_matching_tags":
            code, output, error = git_read(["ls-remote", "--tags", "--refs"])
            data = [
                {"ref": line.split()[1], "sha": line.split()[0], "type": "commit"}
                for line in output.splitlines()
                if len(line.split()) == 2
            ]
        elif query.endpoint == "pypi_metadata":
            code, body, error = http_read("https://pypi.org/pypi/mempalace-code/json")
            output = body.decode()
            data = json.loads(output) if code == 200 else None
            code = 0 if code == 200 else code
        else:
            code, output, error = github_read(query)
            data = json.loads(output) if code == 0 else None
        return SimpleNamespace(data=data, error="" if code == 0 else error or output)

    return read


# ── _make_row ─────────────────────────────────────────────────────────────────


def test_make_row_has_required_fields():
    row = rrg._make_row("test_id", "test command", "pass", "all good")
    assert row["id"] == "test_id"
    assert row["command"] == "test command"
    assert row["status"] == "pass"
    assert row["detail"] == "all good"


def test_make_row_sanitizes_urls_paths_and_bounds_detail(tmp_path):
    detail = f"url=https://user:pass@example.invalid/simple path={tmp_path}/artifact " + "x" * (
        rrg._DETAIL_LIMIT + 100
    )

    row = rrg._make_row("failure", "command", "fail", detail)

    assert "user:pass" not in row["detail"]
    assert str(tmp_path) not in row["detail"]
    assert len(row["detail"]) == rrg._DETAIL_LIMIT


def test_installed_application_forwards_exact_wheel_and_preserves_surfaces(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    wheel = dist_dir / "mempalace_code-1.13.5-py3-none-any.whl"
    wheel.write_bytes(b"candidate")
    captured = []
    smoke = SimpleNamespace(
        STATUS_OK="ok",
        _default_run_subprocess=object(),
        run_all_installers_smoke=lambda install_spec, package_name, runner: (
            captured.append((install_spec, package_name, runner))
            or SimpleNamespace(
                ok=False,
                diagnostics=["venv: failed"],
                results=[
                    SimpleNamespace(
                        installer="venv",
                        surfaces=[
                            SimpleNamespace(name="metadata", status="ok", detail="metadata ok"),
                            SimpleNamespace(name="version-check", status="fail", detail="failed"),
                        ],
                    )
                ],
            )
        ),
    )

    with patch.object(rrg, "_load_sibling", return_value=smoke):
        rows = _RUN_INSTALLED_APPLICATION(dist_dir)

    assert captured == [(str(wheel), rrg.PACKAGE_NAME, smoke._default_run_subprocess)]
    assert [row["status"] for row in rows] == ["pass", "fail", "fail"]
    assert [row["id"] for row in rows] == [
        "installed_venv_metadata",
        "installed_venv_version_check",
        "installed_application",
    ]


def test_installed_application_requires_exactly_one_wheel(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    rows = _RUN_INSTALLED_APPLICATION(dist_dir)
    assert rows[0]["status"] == "fail"
    assert rows[0]["detail"] == "expected one candidate wheel, found 0"


def test_installed_golden_requires_exactly_one_wheel(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    rows = _RUN_INSTALLED_GOLDEN(dist_dir, tmp_path)

    assert rows == [
        rrg._make_row(
            "installed_golden_wheel",
            rrg.INSTALLED_GOLDEN_COMMAND,
            "fail",
            "expected one candidate wheel, found 0",
        )
    ]


@pytest.mark.parametrize("configured", [None, "missing"])
def test_installed_golden_rejects_unusable_cache_before_subprocess(tmp_path, configured):
    wheel = _write_candidate_wheel(tmp_path)
    env = {}
    if configured is not None:
        cache = tmp_path / configured
        env["MEMPALACE_TEST_HF_HOME"] = str(cache)

    rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env=env,
        run_subprocess=lambda *args, **kwargs: pytest.fail("subprocess must not run"),
    )

    assert rows[0]["id"] == "installed_golden_cache"
    assert rows[0]["status"] == "fail"
    assert rrg._cache_recovery() in rows[0]["detail"]
    assert str(tmp_path) not in rows[0]["detail"]


def test_installed_cache_probe_rejects_owner_failure(tmp_path):
    hf_home = tmp_path / "hf"
    hf_home.mkdir()

    def rejected(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"owned": False, "root": str(hf_home / "partial"), "error": "partial"}
            ),
            stderr="",
        )

    root, detail = rrg._installed_model_cache_root(
        tmp_path / "venv" / "bin" / "python",
        {"HF_HOME": str(hf_home)},
        tmp_path,
        run_subprocess=rejected,
    )
    assert root is None
    assert detail == "installed package rejected the canonical FastEmbed cache"


def test_installed_split_rejects_polluted_output(tmp_path):
    def polluted_preview(_command, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "DRY RUN mega_part01_unknown_prompt.txt "
                "mega_part02_unknown_prompt-two.txt Traceback (most recent call last)"
            ),
            stderr="",
        )

    row = rrg._run_installed_split_scenario(
        ["mempalace-code"], {}, tmp_path / "scenario", tmp_path, run_subprocess=polluted_preview
    )

    assert row["status"] == "fail"
    assert row["id"] == "installed_golden_split"


def test_installed_version_scenario_binds_labels_to_command_prefix(tmp_path):
    def runner_for(result, calls):
        def run(command, **kwargs):
            calls.append((command, kwargs))
            return result

        return run

    installed = ["/candidate/bin/mempalace-code"]
    source = [sys.executable, "-m", "mempalace_code.cli"]
    cases = [
        (installed, "mempalace-code 1.13.5\n", 0, "", "pass"),
        (source, "cli.py 1.13.5\n", 0, "", "pass"),
        (source, "python -m mempalace_code.cli 1.13.5\n", 0, "", "pass"),
        (source, "python3 -m mempalace_code.cli 1.13.5\n", 0, "", "pass"),
        (installed, "cli.py 1.13.5\n", 0, "", "fail"),
        (installed, "python -m mempalace_code.cli 1.13.5\n", 0, "", "fail"),
        (installed, "python3 -m mempalace_code.cli 1.13.5\n", 0, "", "fail"),
        (source, "mempalace-code 1.13.5\n", 0, "", "fail"),
        (source, "python2 -m mempalace_code.cli 1.13.5\n", 0, "", "fail"),
        (source, "python3.14 -m mempalace_code.cli 1.13.5\n", 0, "", "fail"),
        (source, "python3 -m mempalace_code.cli 1.13.4\n", 0, "", "fail"),
        (
            source,
            "python3 -m mempalace_code.cli 1.13.5\nfake buffered stdout noise\n",
            0,
            "",
            "fail",
        ),
        (installed, "other 1.13.5\n", 0, "", "fail"),
        (installed, "mempalace-code 1.13.4\n", 0, "", "fail"),
        (installed, "mempalace-code 1.13.5\n", 1, "", "fail"),
        (installed, "mempalace-code 1.13.5\n", 0, "warning\n", "fail"),
        (installed, "prefix mempalace-code 1.13.5 suffix\n", 0, "", "fail"),
        (["arbitrary-launcher"], "mempalace-code 1.13.5\n", 0, "", "fail"),
        (
            ["arbitrary-launcher", "-m", "mempalace_code.cli"],
            "python -m mempalace_code.cli 1.13.5\n",
            0,
            "",
            "fail",
        ),
    ]

    for command_prefix, stdout, returncode, stderr, expected_status in cases:
        calls = []
        result = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        row = rrg._run_installed_version_scenario(
            command_prefix,
            {"SAFE": "1"},
            tmp_path,
            "1.13.5",
            run_subprocess=runner_for(result, calls),
        )

        assert row["id"] == "installed_golden_version"
        assert row["status"] == expected_status, (command_prefix, stdout, returncode, stderr)
        assert len(calls) == 1
        assert calls[0][0] == [*command_prefix, "--version"]
        assert calls[0][1] == {
            "capture_output": True,
            "text": True,
            "cwd": str(tmp_path),
            "env": {"SAFE": "1"},
            "timeout": rrg.DEFAULT_TIMEOUT,
        }


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "permuted-021",
        "permuted-201",
        "canonical-source-alias",
        "source-symlink-loop",
        "nonzero",
        "forbidden-output",
        "missing-marker",
        "wrong-counts",
        "mine-wrong-stream",
        "mine-extra-stderr",
        "export-wrong-stream",
        "export-extra-stderr",
        "malformed-export",
        "wrong-shape",
        "missing-header",
        "duplicate-header",
        "unexpected-record-type",
        "header-bool-drawer-count",
        "header-wrong-drawer-count",
        "header-nonzero-kg",
        "malformed-drawer",
        "missing-id",
        "empty-id",
        "duplicate-id",
        "changed-id",
        "missing-chunk-index",
        "bool-chunk-index",
        "negative-chunk-index",
        "string-chunk-index",
        "duplicate-chunk-index",
        "missing-record",
        "duplicate-records",
        "initial-wrong-text",
        "changed-wrong-text",
        "shorter-wrong-text",
        "wrong-source-first",
        "wrong-source",
        "wrong-wing-changed",
        "wrong-wing",
        "stale-original-records",
        "stale-changed-records",
        "health-wrong-stream",
        "health-extra-stderr",
        "health-false",
        "malformed-health",
        "health-bool-current-version",
        "health-bool-version-count",
        "health-wrong-shape",
        "health-wrong-rows",
        "launch",
        "timeout",
        "filesystem",
    ],
)
def test_installed_convo_full_replace_fails_closed(tmp_path, case):
    if case == "canonical-source-alias":
        canonical_root = tmp_path / "canonical"
        canonical_root.mkdir()
        alias_root = tmp_path / "alias"
        alias_root.symlink_to(canonical_root, target_is_directory=True)
        scenario = alias_root / "scenario"
    else:
        scenario = tmp_path / "scenario"
    source = scenario / "conversations" / "chat.txt"
    loop_source_file = None
    if case == "source-symlink-loop":
        loop_source_file = tmp_path / "source-loop"
        loop_source_file.symlink_to(loop_source_file)
    calls = []
    mine_count = 0
    export_count = 0

    def drawer(
        text: str,
        chunk_index: int,
        *,
        source_file: str | None = None,
        wing: str = "conversations",
    ):
        return {
            "type": "drawer",
            "id": f"drawer-{chunk_index}",
            "text": text,
            "source_file": (
                str(source.resolve())
                if source_file is None and case == "canonical-source-alias"
                else str(loop_source_file)
                if source_file is None and loop_source_file is not None
                else str(source)
                if source_file is None
                else source_file
            ),
            "wing": wing,
            "chunk_index": chunk_index,
        }

    initial = [
        drawer("> Original question one?\nOriginal answer one has enough content.", 0),
        drawer("> Original question two?\nOriginal answer two has enough content.", 1),
        drawer("> Stale tail question?\nStale tail answer must be removed.", 2),
    ]
    changed = [
        drawer("> Changed question one?\nChanged sentinel 84017 is authoritative.", 0),
        drawer("> Changed question two?\nChanged answer two remains current.", 1),
        drawer("> Changed question three?\nChanged answer three replaces the old tail.", 2),
    ]
    shorter = [
        drawer("> Short replacement?\nFinal sentinel 99173 is the only remaining exchange.", 0)
    ]

    def run(command, **kwargs):
        nonlocal mine_count, export_count
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        if case == "launch":
            raise OSError(f"launcher unavailable at {tmp_path}")
        if case == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if "mine" in command:
            mine_count += 1
            outputs = (
                "Files processed: 1\nFiles skipped (already filed): 0\nDrawers filed: 3\n",
                "Files processed: 0\nFiles skipped (already filed): 1\nDrawers filed: 0\n",
                "Mode:    FULL REBUILD (--full)\nFiles processed: 1\n"
                "Files skipped (already filed): 0\nDrawers filed: 3\n",
                "Mode:    FULL REBUILD (--full)\nFiles processed: 1\n"
                "Files skipped (already filed): 0\nDrawers filed: 1\n",
            )
            stdout = outputs[mine_count - 1]
            returncode = 0
            if mine_count == 1:
                if case == "nonzero":
                    returncode = 2
                elif case == "forbidden-output":
                    stdout += "Traceback (most recent call last)\n"
                elif case == "missing-marker":
                    stdout = stdout.replace("Files processed:", "Processed:")
                elif case == "wrong-counts":
                    stdout = stdout.replace("Drawers filed: 3", "Drawers filed: 2")
                elif case == "mine-wrong-stream":
                    return SimpleNamespace(returncode=0, stdout="", stderr=stdout)
                elif case == "mine-extra-stderr":
                    return SimpleNamespace(
                        returncode=0, stdout=stdout, stderr="unexpected stderr\n"
                    )
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
        if "export" in command:
            export_count += 1
            records = [initial, initial, changed, shorter][export_count - 1]
            records = [dict(record) for record in records]
            permutations = {
                "permuted-021": ((0, 2, 1), (2, 0, 1), (1, 2, 0)),
                "permuted-201": ((2, 0, 1), (1, 0, 2), (0, 2, 1)),
            }
            if case in permutations and len(records) == 3:
                records = [records[index] for index in permutations[case][export_count - 1]]
            if export_count == 1 and case == "malformed-export":
                payload = "{\n"
            elif export_count == 1 and case == "wrong-shape":
                payload = "[]\n"
            else:
                if export_count == 2 and case == "missing-record":
                    records.pop()
                elif export_count == 2 and case == "duplicate-records":
                    records.append(dict(records[-1]))
                elif export_count == 1 and case == "missing-id":
                    records[0].pop("id")
                elif export_count == 1 and case == "empty-id":
                    records[0]["id"] = ""
                elif export_count == 1 and case == "duplicate-id":
                    records[1]["id"] = records[0]["id"]
                elif export_count == 3 and case == "changed-id":
                    records[1]["id"] = "unexpected-id"
                elif export_count == 1 and case == "missing-chunk-index":
                    records[0].pop("chunk_index")
                elif export_count == 1 and case == "bool-chunk-index":
                    records[0]["chunk_index"] = True
                elif export_count == 1 and case == "negative-chunk-index":
                    records[0]["chunk_index"] = -1
                elif export_count == 1 and case == "string-chunk-index":
                    records[0]["chunk_index"] = "0"
                elif export_count == 1 and case == "duplicate-chunk-index":
                    records[1]["chunk_index"] = records[0]["chunk_index"]
                elif (
                    export_count == 1
                    and case == "initial-wrong-text"
                    or export_count == 3
                    and case == "changed-wrong-text"
                ):
                    records[1]["text"] += " changed"
                elif export_count == 4 and case == "shorter-wrong-text":
                    records[0]["text"] += " changed"
                elif export_count == 1 and case == "wrong-source-first":
                    records[1]["source_file"] = str(tmp_path / "wrong.txt")
                elif export_count == 4 and case == "wrong-source":
                    records[0]["source_file"] = str(tmp_path / "wrong.txt")
                elif export_count == 3 and case == "wrong-wing-changed":
                    records[1]["wing"] = "wrong"
                elif export_count == 4 and case == "wrong-wing":
                    records[0]["wing"] = "wrong"
                elif export_count == 3 and case == "stale-original-records":
                    records.append(dict(initial[0]))
                elif export_count == 4 and case == "stale-changed-records":
                    records.append(dict(changed[0]))
                elif export_count == 1 and case == "malformed-drawer":
                    records[0].pop("text")
                header = {
                    "type": "export_header",
                    "drawer_count": len(records),
                    "kg_count": 0,
                }
                if export_count == 1 and case == "missing-header":
                    export_records = records
                elif export_count == 1 and case == "duplicate-header":
                    export_records = [header, dict(header), *records]
                elif export_count == 1 and case == "unexpected-record-type":
                    export_records = [header, {"type": "kg_triple"}, *records]
                    header["drawer_count"] += 1
                else:
                    if export_count == 1 and case == "header-bool-drawer-count":
                        header["drawer_count"] = True
                    elif export_count == 1 and case == "header-wrong-drawer-count":
                        header["drawer_count"] += 1
                    elif export_count == 1 and case == "header-nonzero-kg":
                        header["kg_count"] = 1
                    export_records = [header, *records]
                payload = "".join(json.dumps(record) + "\n" for record in export_records)
            Path(command[command.index("--out") + 1]).write_text(payload, encoding="utf-8")
            out_path = command[command.index("--out") + 1]
            palace = command[command.index("--palace") + 1]
            stderr = (
                f"  Exporting from: {palace}\n"
                f"  Exported {len(records)} drawers, 0 KG triples → {out_path}\n"
            )
            if export_count == 1 and case == "export-wrong-stream":
                return SimpleNamespace(returncode=0, stdout=stderr, stderr="")
            if export_count == 1 and case == "export-extra-stderr":
                stderr += "unexpected stderr\n"
            return SimpleNamespace(returncode=0, stdout="", stderr=stderr)
        expected_rows = (3, 3, 3, 1)[export_count - 1]
        health = {
            "ok": case != "health-false" or export_count != 1,
            "total_rows": expected_rows,
            "current_version": 1,
            "storage": {"version_count": 1},
        }
        if export_count == 1:
            if case == "malformed-health":
                health["total_rows"] = True
            elif case == "health-bool-current-version":
                health["current_version"] = True
            elif case == "health-bool-version-count":
                health["storage"]["version_count"] = True
            elif case == "health-wrong-shape":
                health["storage"] = []
            elif case == "health-wrong-rows":
                health["total_rows"] = expected_rows + 1
        stdout = json.dumps(health)
        if export_count == 1 and case == "health-wrong-stream":
            return SimpleNamespace(returncode=0, stdout="", stderr=stdout)
        stderr = "unexpected stderr\n" if case == "health-extra-stderr" else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

    repository_root = tmp_path / "repo-file" if case == "filesystem" else tmp_path
    if case == "filesystem":
        repository_root.write_text("not a directory", encoding="utf-8")
    neutral = tmp_path / "neutral"
    row = rrg._run_installed_convo_full_replace_scenario(
        ["mempalace-code"],
        {"SAFE": "1"},
        scenario,
        neutral,
        repository_root=repository_root,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_convo_full_replace"
    passing_cases = {"success", "permuted-021", "permuted-201", "canonical-source-alias"}
    assert row["status"] == ("pass" if case in passing_cases else "fail")
    assert row["detail"].count(rrg.INSTALLED_GOLDEN_COMMAND) == (0 if case in passing_cases else 1)
    assert str(tmp_path) not in row["detail"]
    assert all(call[1]["cwd"] == str(neutral) for call in calls)
    assert all(call[1]["env"] == {"SAFE": "1"} for call in calls)
    assert all(call[1]["timeout"] == rrg.DEFAULT_TIMEOUT for call in calls)
    if case in passing_cases:
        assert len(calls) == 12
        assert sum("--full" in call[0] for call in calls) == 2


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "setup-nonzero",
        "setup-unexpected-zero",
        "read-zero",
        "health-nonzero",
        "wrong-stream",
        "forbidden-output",
        "missing-marker",
        "reordered-marker",
        "launch",
        "timeout",
        "malformed-health",
        "missing-path-created",
        "changed-health",
        "filesystem",
    ],
)
def test_installed_read_failure_contracts_fail_closed(tmp_path, case):
    health = '{"total_rows":1,"current_version":1,"storage":{"version_count":1}}'
    calls = []
    health_count = 0

    def run(command, **kwargs):
        nonlocal health_count
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        if case == "launch":
            raise OSError(f"launcher unavailable at {tmp_path}")
        if case == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if command[-1] == "--skip-model-download":
            if case == "setup-nonzero":
                return SimpleNamespace(returncode=2, stdout="", stderr="init failed")
            stdout = "ok\n" if case == "setup-unexpected-zero" else "Config saved: fixture\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if "mine" in command:
            return SimpleNamespace(returncode=0, stdout="Drawers filed: 1\n", stderr="")
        if command[-2:] == ["health", "--json"]:
            health_count += 1
            if case == "health-nonzero":
                return SimpleNamespace(returncode=2, stdout="", stderr="health failed")
            value = health
            if case == "malformed-health":
                value = "[]"
            elif case == "changed-health" and health_count == 2:
                value = '{"total_rows":2,"current_version":1,"storage":{"version_count":1}}'
            return SimpleNamespace(returncode=0, stdout=value, stderr="")
        if command[-4:] == ["--start", "10", "--end", "1"]:
            stderr = "Invalid range: start (10) must be <= end (1)\nNext: choose an ordered range\n"
            returncode = 1
            stdout = ""
            if case == "read-zero":
                returncode = 0
            elif case == "wrong-stream":
                stdout, stderr = stderr, ""
            elif case == "forbidden-output":
                stderr += "Traceback (most recent call last)\n"
            elif case == "missing-marker":
                stderr = stderr.replace("Next:", "Try:")
            elif case == "reordered-marker":
                stderr = (
                    "Next: choose an ordered range\nInvalid range: start (10) must be <= end (1)\n"
                )
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        missing_path = Path(command[command.index("--palace") + 1])
        if case == "missing-path-created":
            missing_path.mkdir(parents=True)
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f"No palace found at {missing_path}\nNext: initialize the palace\n",
        )

    repository_root = tmp_path / "repo-file" if case == "filesystem" else tmp_path
    if case == "filesystem":
        repository_root.write_text("not a directory", encoding="utf-8")
    scenario = tmp_path / "scenario"
    neutral = tmp_path / "neutral"
    row = rrg._run_installed_read_failure_scenario(
        ["mempalace-code"],
        {"SAFE": "1"},
        scenario,
        neutral,
        repository_root=repository_root,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_read_failures"
    assert row["status"] == ("pass" if case == "success" else "fail")
    assert row["detail"].count(rrg.INSTALLED_GOLDEN_COMMAND) == (0 if case == "success" else 1)
    assert str(tmp_path) not in row["detail"]
    assert all(call[1]["cwd"] == str(neutral) for call in calls)
    assert all(call[1]["env"] == {"SAFE": "1"} for call in calls)
    assert all(call[1]["timeout"] == rrg.DEFAULT_TIMEOUT for call in calls)
    if case == "success":
        assert len(calls) == 6
        assert calls[0][0] == [
            "mempalace-code",
            "init",
            str(scenario / "project"),
            "--skip-model-download",
        ]
        assert calls[1][0] == [
            "mempalace-code",
            "--palace",
            str(scenario / "palace"),
            "mine",
            str(scenario / "project"),
        ]
        assert [call[0][-2:] for call in calls[2::3]] == [
            ["health", "--json"],
            ["health", "--json"],
        ]


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "nonzero",
        "missing-init-evidence",
        "missing-mine-evidence",
        "stderr-init",
        "stderr-mine",
        "stderr-first-cleanup",
        "stderr-first-health",
        "stderr-second-cleanup",
        "stderr-second-health",
        "inconsistent-poststate",
        "malformed",
        "launch",
        "timeout",
        "wrong-shape",
        "filesystem",
    ],
)
def test_installed_cleanup_poststate_fails_closed(tmp_path, case):
    init_ok = SimpleNamespace(returncode=0, stdout="Config saved: fixture\n", stderr="")
    mine_ok = SimpleNamespace(returncode=0, stdout="Drawers filed: 1\n", stderr="")
    cleanup_json = '{"ok":true,"rows_before":1,"rows_after":1,"version_count_before":1,"version_count_after":1,"estimated_reclaimable_bytes_before":0,"estimated_reclaimable_bytes_after":0,"freed_bytes":0}'  # fmt: skip
    health_json = '{"total_rows":1,"storage":{"version_count":1,"estimated_reclaimable_bytes":0}}'
    payloads = [init_ok, mine_ok, *(SimpleNamespace(returncode=0, stdout=value, stderr="") for value in (cleanup_json, health_json) * 2)]  # fmt: skip
    if case == "nonzero":
        payloads[0] = SimpleNamespace(returncode=2, stdout="", stderr="init failed")
    elif case == "missing-init-evidence":
        payloads[0] = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
    elif case == "missing-mine-evidence":
        payloads[1] = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
    elif case.startswith("stderr-"):
        index = {
            "stderr-init": 0,
            "stderr-mine": 1,
            "stderr-first-cleanup": 2,
            "stderr-first-health": 3,
            "stderr-second-cleanup": 4,
            "stderr-second-health": 5,
        }[case]
        payloads[index] = SimpleNamespace(
            returncode=0, stdout=payloads[index].stdout, stderr="unexpected stderr\n"
        )
    elif case == "inconsistent-poststate":
        payloads[3] = SimpleNamespace(
            returncode=0,
            stdout='{"total_rows":2,"storage":{"version_count":1,"estimated_reclaimable_bytes":0}}',  # fmt: skip
            stderr="",
        )
    elif case in ("malformed", "wrong-shape"):
        invalid = "{" if case == "malformed" else "[]"
        payloads[2] = SimpleNamespace(returncode=0, stdout=invalid, stderr="")
    responses = iter(payloads)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if case == "launch":
            raise OSError("launcher unavailable")
        if case == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return next(responses)

    repository_root = tmp_path / "repo-file" if case == "filesystem" else tmp_path
    if case == "filesystem":
        repository_root.write_text("not a directory", encoding="utf-8")
    scenario, neutral = tmp_path / "scenario", tmp_path / "neutral"
    row = rrg._run_installed_cleanup_poststate_scenario(["mempalace-code"], {"SAFE": "1"}, scenario, neutral, repository_root=repository_root, run_subprocess=run)  # fmt: skip
    assert row["id"] == "installed_golden_cleanup_poststate"
    assert row["status"] == ("pass" if case == "success" else "fail")
    assert row["detail"].count(rrg.INSTALLED_GOLDEN_COMMAND) == (0 if case == "success" else 1)
    assert all(call[1]["cwd"] == str(tmp_path / "neutral") for call in calls)
    assert all(call[1]["env"] == {"SAFE": "1"} for call in calls)
    assert all(call[1]["timeout"] == rrg.DEFAULT_TIMEOUT for call in calls)
    expected_calls = {
        "nonzero": 1,
        "missing-init-evidence": 1,
        "missing-mine-evidence": 2,
        "stderr-init": 1,
        "stderr-mine": 2,
        "stderr-first-cleanup": 3,
        "stderr-first-health": 4,
        "stderr-second-cleanup": 5,
        "malformed": 3,
        "launch": 1,
        "timeout": 1,
        "wrong-shape": 3,
    }.get(case, 6)
    assert len(calls) == expected_calls
    assert calls[0][0][0] == "mempalace-code"
    assert calls[0][0][-1] == "--skip-model-download"
    assert calls[1][0][-2:] == ["mine", str(scenario / "project")] if len(calls) > 1 else True
    assert [call[0][-2:] for call in calls[2:]] == [["cleanup", "--json"], ["health", "--json"], ["cleanup", "--json"], ["health", "--json"]] if case in ("success", "filesystem") else True  # fmt: skip


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "nonzero",
        "nonzero-cleanup",
        "malformed-cleanup",
        "cleanup-ok-false",
        "cleanup-version-bool",
        "cleanup-version-wrong",
        "missing-marker",
        "reordered-marker",
        "inactive-stream",
        "forbidden-output",
        "malformed-health",
        "wrong-health",
        "launch",
        "timeout",
        "filesystem",
    ],
)
def test_installed_rollback_no_candidate_fails_closed(tmp_path, case):
    separator = "=" * 55

    def rollback_output(dry_run: bool) -> str:
        mutation = (
            "Mutation: preview completed; no changes were made; no restore or full rebuild "
            "occurred."
            if dry_run
            else "Mutation: rollback attempted; no restore or full rebuild occurred; palace "
            "remained unchanged."
        )
        exit_meaning = (
            "Exit status: 0 (completed non-mutating preview)."
            if dry_run
            else "Exit status: 1 (rollback failed because no candidate was found)."
        )
        markers = [
            "MemPalace Repair — Version Rollback",
            "Mode: dry-run" if dry_run else "Mode: live",
            "No candidate version: only one version is available.",
            mutation,
            exit_meaning,
            "Try: mempalace-code repair (full rebuild)",
        ]
        return "\n".join([separator, *markers, separator, "details", separator]) + "\n"

    health = '{"total_rows":1,"current_version":1,"storage":{"version_count":1}}'
    calls = []
    rollback_count = 0
    health_count = 0

    def run(command, **kwargs):
        nonlocal rollback_count, health_count
        calls.append((command, kwargs))
        if case == "launch":
            raise OSError("launcher unavailable")
        if case == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if command[-1] == "--skip-model-download":
            return SimpleNamespace(returncode=0, stdout="Config saved: fixture\n", stderr="")
        if "mine" in command:
            return SimpleNamespace(returncode=0, stdout="Drawers filed: 1\n", stderr="")
        if command[-3:] == ["cleanup", "--unsafe-now", "--json"]:
            returncode = 1 if case == "nonzero-cleanup" else 0
            value = '{"ok":true,"version_count_after":1}'
            if case == "malformed-cleanup":
                value = "{"
            elif case == "cleanup-ok-false":
                value = '{"ok":false,"version_count_after":1}'
            elif case == "cleanup-version-bool":
                value = '{"ok":true,"version_count_after":true}'
            elif case == "cleanup-version-wrong":
                value = '{"ok":true,"version_count_after":2}'
            return SimpleNamespace(returncode=returncode, stdout=value, stderr="")
        if command[-2:] == ["health", "--json"]:
            health_count += 1
            value = health
            if case == "malformed-health" and health_count == 1:
                value = "{"
            elif case == "wrong-health" and health_count == 2:
                value = '{"total_rows":2,"current_version":1,"storage":{"version_count":1}}'
            return SimpleNamespace(returncode=0, stdout=value, stderr="")

        rollback_count += 1
        dry_run = "--dry-run" in command
        merged = kwargs.get("stderr") is subprocess.STDOUT
        output = rollback_output(dry_run)
        returncode = 0 if dry_run else 1
        stdout = output if dry_run or merged else ""
        stderr = None if merged else ("" if dry_run else output)
        if rollback_count == 1:
            if case == "nonzero":
                returncode = 2
            elif case == "missing-marker":
                stdout = stdout.replace("No candidate version:", "Candidate absent:")
            elif case == "reordered-marker":
                stdout = stdout.replace(
                    "Mode: dry-run\nNo candidate version: only one version is available.",
                    "No candidate version: only one version is available.\nMode: dry-run",
                )
            elif case == "inactive-stream":
                stderr = "unexpected stderr"
            elif case == "forbidden-output":
                stdout += "Traceback (most recent call last)"
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    repository_root = tmp_path / "repo-file" if case == "filesystem" else tmp_path
    if case == "filesystem":
        repository_root.write_text("not a directory", encoding="utf-8")
    scenario = tmp_path / "scenario"
    neutral = tmp_path / "neutral"
    row = rrg._run_installed_rollback_no_candidate_scenario(
        ["mempalace-code"],
        {"SAFE": "1"},
        scenario,
        neutral,
        repository_root=repository_root,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_rollback_no_candidate"
    assert row["status"] == ("pass" if case == "success" else "fail")
    assert row["detail"].count(rrg.INSTALLED_GOLDEN_COMMAND) == (0 if case == "success" else 1)
    assert str(tmp_path) not in row["detail"]
    assert all(call[1]["cwd"] == str(neutral) for call in calls)
    assert all(call[1]["env"] == {"SAFE": "1"} for call in calls)
    assert all(call[1]["timeout"] == rrg.DEFAULT_TIMEOUT for call in calls)
    if case == "success":
        assert len(calls) == 12
        rollback_calls = [call for call in calls if "repair" in call[0]]
        assert [call[1].get("stderr") is subprocess.STDOUT for call in rollback_calls] == [
            False,
            True,
            False,
            True,
        ]


def test_installed_watcher_signal_cleanup_fails_closed(tmp_path):
    faults = (
        "success",
        "launch",
        "missing-stdout",
        "early-exit",
        "stop-timeout",
        "malformed-owner",
        "nonzero-exit",
        "surviving-owner",
        "network-attempt",
        "filesystem",
    )
    supported_signals = (signal.SIGTERM,) + ((signal.SIGHUP,) if hasattr(signal, "SIGHUP") else ())

    for fault in faults:
        case_root = tmp_path / fault
        home = case_root / "home"
        owners_path = home / ".mempalace" / "operation.lock.owners.json"
        owners_path.parent.mkdir(parents=True)
        owners_path.write_text("{}", encoding="utf-8")
        repository_root = case_root / "repo"
        if fault == "filesystem":
            repository_root.write_text("not a directory", encoding="utf-8")
        else:
            repository_root.mkdir()
        attempts = case_root / "socket-attempts.log"
        if fault == "network-attempt":
            attempts.write_text("blocked.example:443\n", encoding="utf-8")
        processes = []
        next_pid = 4100

        class FakeProcess:
            def __init__(self, active_fault=fault, active_owners_path=owners_path):
                nonlocal next_pid
                self.pid = next_pid
                next_pid += 1
                self.returncode = 2 if active_fault == "early-exit" else None
                self.stdout = io.StringIO("state=watch-ready\nWatch stopped after 0 changes\n")
                if active_fault == "missing-stdout":
                    self.stdout = None
                self.killed = False
                active_owners_path.write_text(
                    "{"
                    + json.dumps(f"token-{self.pid}")
                    + ":"
                    + json.dumps({"pid": self.pid})
                    + "}",
                    encoding="utf-8",
                )

            def poll(self):
                return self.returncode

            def send_signal(
                self,
                shutdown_signal,
                active_fault=fault,
                active_owners_path=owners_path,
            ):
                if active_fault == "stop-timeout" and shutdown_signal != signal.SIGINT:
                    return
                self.returncode = 2 if active_fault == "nonzero-exit" else 0
                if active_fault == "malformed-owner":
                    active_owners_path.write_text("{", encoding="utf-8")
                elif active_fault != "surviving-owner":
                    active_owners_path.write_text("{}", encoding="utf-8")

            def wait(self, timeout: float = 0.0, active_fault=fault):
                if active_fault == "stop-timeout" and not self.killed:
                    raise subprocess.TimeoutExpired(["watcher"], timeout)
                return self.returncode

            def kill(self, active_owners_path=owners_path):
                self.killed = True
                self.returncode = -9
                active_owners_path.write_text("{}", encoding="utf-8")

        def fake_popen(
            *_args,
            active_fault=fault,
            active_case_root=case_root,
            active_processes=processes,
            **_kwargs,
        ):
            if active_fault == "launch":
                raise OSError(f"launcher unavailable at {active_case_root}")
            process = FakeProcess()
            active_processes.append(process)
            return process

        def fake_run(command, **_kwargs):
            args = [str(item) for item in command]
            if len(args) > 1 and args[1] == "-c":
                return SimpleNamespace(returncode=0, stdout="exclusive-released\n", stderr="")
            if "init" in args:
                return SimpleNamespace(returncode=0, stdout="Config saved: fixture\n", stderr="")
            if "mine" in args:
                return SimpleNamespace(returncode=0, stdout="Drawers filed: 4\n", stderr="")
            if "health" in args:
                return SimpleNamespace(
                    returncode=0,
                    stdout='{"ok":true,"total_rows":4,"storage":{}}',
                    stderr="",
                )
            if "search" in args:
                return SimpleNamespace(
                    returncode=0,
                    stdout="Results for: xylophonic_glyph_9182\napp.py\n",
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {args}")

        row = rrg._run_installed_watcher_signal_cleanup_scenario(
            ["mempalace-code"],
            {"HOME": str(home)},
            case_root / "scenario",
            case_root / "neutral",
            repository_root=repository_root,
            supported_signals=supported_signals,
            network_attempts=attempts,
            run_subprocess=fake_run,
            popen=fake_popen,
        )

        assert row["id"] == "installed_golden_watcher_signals"
        assert row["status"] == ("pass" if fault == "success" else "fail")
        assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == (
            0 if fault == "success" else 1
        )
        assert str(case_root) not in row["detail"]
        if fault == "success":
            assert len(processes) == len(supported_signals) * 2
        if fault == "stop-timeout":
            assert processes[0].killed is True
        if fault == "missing-stdout":
            assert processes[0].poll() is not None


@pytest.mark.parametrize(
    "fault",
    [
        "success",
        "ambient-execution",
        "wrong-launcher",
        "missing-launcher",
        "unsafe-target",
        "missing-target",
        "backup-alternate-target",
        "watch-alternate-target",
        "nondeterministic-output",
        "backup-marker-preview-missing",
        "backup-marker-preview-wrong",
        "backup-marker-refusal-missing",
        "backup-marker-refusal-wrong",
        "watch-marker-preview-missing",
        "watch-marker-preview-wrong",
        "watch-marker-refusal-missing",
        "watch-marker-refusal-wrong",
        "install-success",
        "install-code",
        "state-drift",
        "polluted-output",
        "oversized-output",
        "launch-error",
        "timeout",
        "filesystem-error",
        "repository-drift",
        "cleanup-failure",
    ],
)
@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_installed_schedule_snippet_scenario_fails_closed(tmp_path, monkeypatch, fault, platform):
    monkeypatch.setattr(rrg.sys, "platform", platform)
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    candidate = tmp_path / "candidate bin" / "mempalace-code"
    candidate.parent.mkdir()
    candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    candidate.chmod(0o755)
    neutral = tmp_path / "neutral cwd"
    calls = []
    rendered_targets = []

    def run(command, **kwargs):
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        args = command[1:]
        install = args[-1] == "--install"
        if "backup" in args:
            label = "backup"
            target = Path(args[args.index("--palace") + 1])
            scheduler = "com.mempalace.backup.plist"
            raw_target = os.path.abspath(str(target))
            safe_target = shlex.quote(raw_target)
            alternate_target = shlex.quote(str(target.resolve()))
        else:
            label = "watch"
            target = Path(args[args.index("watch") + 1])
            scheduler = "com.mempalace.watch.plist"
            raw_target = str(target.resolve())
            safe_target = shlex.quote(raw_target)
            alternate_target = shlex.quote(os.path.abspath(str(target)))
        safe_launcher = shlex.quote(str(candidate.resolve()))
        platform_marker = scheduler if platform == "darwin" else "crontab -e"
        rendered_targets.append((label, safe_target, alternate_target))
        stdout = "" if install else f"preview {safe_launcher} {safe_target}\n"
        stderr = f"instructions {safe_launcher} {safe_target} {platform_marker}\n"
        returncode = 2 if install else 0

        marker_stage = "refusal" if install else "preview"
        marker_fault = f"{label}-marker-{marker_stage}"
        if fault == f"{marker_fault}-missing":
            stderr = stderr.replace(platform_marker, "")
        elif fault == f"{marker_fault}-wrong":
            stderr = stderr.replace(platform_marker, "wrong-platform-marker")

        if len(calls) == 1:
            if fault == "ambient-execution":
                ambient_bin = Path(kwargs["env"]["PATH"].split(os.pathsep)[0])
                (ambient_bin.parent / "ambient-launcher-executed").write_text(
                    "executed\n", encoding="utf-8"
                )
            elif fault == "wrong-launcher":
                stdout = stdout.replace(safe_launcher, "'/wrong launcher'")
                stderr = stderr.replace(safe_launcher, "'/wrong launcher'")
            elif fault == "missing-launcher":
                stdout = stdout.replace(safe_launcher, "")
                stderr = stderr.replace(safe_launcher, "")
            elif fault == "unsafe-target":
                stdout = stdout.replace(safe_target, raw_target)
                stderr = stderr.replace(safe_target, raw_target)
            elif fault == "missing-target":
                stdout = stdout.replace(safe_target, "")
                stderr = stderr.replace(safe_target, "")
            elif fault == "backup-alternate-target" and label == "backup":
                stdout = stdout.replace(safe_target, alternate_target)
                stderr = stderr.replace(safe_target, alternate_target)
            elif fault == "state-drift":
                (target.parent / "unexpected.txt").write_text("drift\n", encoding="utf-8")
            elif fault == "polluted-output":
                stdout += "Traceback (most recent call last)\n"
            elif fault == "oversized-output":
                stdout += "x" * 12001
            elif fault == "launch-error":
                raise OSError(f"private launcher path {tmp_path}")
            elif fault == "timeout":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            elif fault == "filesystem-error":
                os.mkfifo(target.parent / "unsupported-entry")
            elif fault == "repository-drift":
                (repository_root / "unexpected.txt").write_text("drift\n", encoding="utf-8")
        elif fault == "nondeterministic-output" and len(calls) == 2:
            stdout += "changed\n"
        elif fault == "watch-alternate-target" and label == "watch":
            stdout = stdout.replace(safe_target, alternate_target)
            stderr = stderr.replace(safe_target, alternate_target)

        if install and fault == "install-success":
            returncode = 0
        elif install and fault == "install-code":
            returncode = 1
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    if fault == "cleanup-failure":
        real_temporary_directory = rrg.tempfile.TemporaryDirectory

        class CleanupFailure:
            def __init__(self, *args, **kwargs):
                self._inner = real_temporary_directory(*args, **kwargs)
                self.name = self._inner.name

            def cleanup(self):
                self._inner.cleanup()
                raise OSError(f"private cleanup path {tmp_path}")

        monkeypatch.setattr(rrg.tempfile, "TemporaryDirectory", CleanupFailure)

    row = rrg._run_installed_schedule_snippet_scenario(
        [str(candidate.resolve())],
        {"PATH": "/usr/bin", "SAFE": "1"},
        tmp_path / "schedule-scenario",
        neutral,
        repository_root=repository_root,
        run_subprocess=run,
    )

    assert row["id"] == "installed_golden_schedule_snippets"
    assert row["status"] == ("pass" if fault == "success" else "fail")
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == (
        0 if fault == "success" else 1
    )
    assert str(tmp_path) not in row["detail"]
    assert len(row["detail"]) <= 2000
    assert all(call[0][0] == str(candidate.resolve()) for call in calls)
    assert all(call[1]["cwd"] == str(neutral) for call in calls)
    assert all(call[1]["timeout"] == rrg.DEFAULT_TIMEOUT for call in calls)
    if fault == "success":
        assert len(calls) == 6
        assert all(expected != alternate for _label, expected, alternate in rendered_targets)
        assert [label for label, _expected, _alternate in rendered_targets] == [
            "backup",
            "backup",
            "backup",
            "watch",
            "watch",
            "watch",
        ]
        assert [call[0][-1] == "--install" for call in calls] == [
            False,
            False,
            True,
            False,
            False,
            True,
        ]


def test_installed_schedule_snippet_scenario_rejects_unsupported_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(rrg.sys, "platform", "win32")
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    candidate = tmp_path / "candidate" / "mempalace-code"
    candidate.parent.mkdir()
    candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    candidate.chmod(0o755)
    calls = []

    row = rrg._run_installed_schedule_snippet_scenario(
        [str(candidate.resolve())],
        {"PATH": "/usr/bin"},
        tmp_path / "schedule-scenario",
        tmp_path / "neutral",
        repository_root=repository_root,
        run_subprocess=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert row["status"] == "fail"
    assert "schedule snippet platform is unsupported: win32" in row["detail"]
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == 1
    assert calls == []


@pytest.mark.parametrize(
    "fault",
    [
        "success",
        "command-failure",
        "malformed-totals",
        "no-op-growth",
        "wrong-health",
        "unsafe-residue",
        "forbidden-output",
        "network-attempt",
        "repository-drift",
        "watcher-launch",
        "watcher-exit",
        "watcher-stop",
    ],
)
def test_installed_workflow_happy_path_fails_closed(tmp_path, fault):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    scenario_root = tmp_path / "scenario"
    neutral = tmp_path / "neutral"
    attempts = tmp_path / "socket-attempts.log"
    console = tmp_path / "candidate" / "bin" / "mempalace-code"
    console.parent.mkdir(parents=True)
    console.write_text("console\n", encoding="utf-8")
    calls = []
    mine_calls = 0

    def result(returncode=0, stdout="", stderr=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def run(command, **kwargs):
        nonlocal mine_calls
        command = [str(item) for item in command]
        calls.append((command, kwargs))
        args = command[1:]
        if args[0] == "init":
            project = Path(args[1])
            (project / "mempalace.yaml").write_text("version: 1\n", encoding="utf-8")
            if fault == "command-failure":
                return result(returncode=2, stderr="bounded init failure")
            if fault == "forbidden-output":
                return result(stdout="Config saved:\nTraceback (most recent call last)\n")
            return result(stdout="Config saved:\n")
        if "mine" in args:
            mine_calls += 1
            palace = Path(args[args.index("--palace") + 1])
            palace.mkdir(parents=True, exist_ok=True)
            data = palace / "data.bin"
            if mine_calls == 1:
                data.write_bytes(b"stable palace")
                return result(stdout="Drawers filed: 4\n")
            if fault == "no-op-growth":
                data.write_bytes(b"stable palace plus growth")
            return result(stdout="no changes detected\n")
        if "compress" in args:
            total = "151" if fault == "malformed-totals" else "150"
            return result(
                stdout=(
                    "    100t -> 80t (20%)\n"
                    "    50t -> 40t (20%)\n"
                    f"  Total: {total}t -> 120t (20%)\n"
                    "dry run -- nothing stored\n"
                )
            )
        if args[-1] == "status":
            return result(stdout="MemPalace Status\nWING: project\n")
        if "search" in args:
            return result(stdout="Results for: xylophonic_glyph_9182\nSource: app.py\n")
        if "read" in args:
            return result(stdout="\n".join(rrg._PY_LINES))
        if "export" in args:
            output = Path(args[args.index("--out") + 1])
            output.write_text('{"drawer": 1}\n', encoding="utf-8")
            return result(stderr="Exported 4 drawers\n")
        if "import" in args:
            palace = Path(args[args.index("--palace") + 1])
            palace.mkdir(parents=True, exist_ok=True)
            (palace / "data.bin").write_bytes(b"imported")
            return result(stdout="Imported drawers: 4\n")
        if "backup" in args:
            output = Path(args[args.index("--out") + 1])
            output.write_bytes(b"archive")
            return result(stdout=f"Backed up palace\nArchive: {output}\n")
        if "restore" in args:
            archive = Path(args[-1])
            palace = Path(args[args.index("--palace") + 1])
            if archive.name == "nonbackup.tar.gz":
                if fault == "unsafe-residue":
                    (scenario_root.parent / "mempalace-direct-escaped.txt").write_text(
                        "escaped", encoding="utf-8"
                    )
                return result(returncode=2, stderr="use mempalace-code backup create\n")
            palace.mkdir(parents=True, exist_ok=True)
            (palace / "data.bin").write_bytes(b"restored")
            return result(stdout=f"Restored palace to: {palace}\n")
        if "health" in args:
            if fault == "network-attempt":
                attempts.write_text("blocked socket\n", encoding="utf-8")
            if fault == "repository-drift":
                (repository_root / ".mempalace").mkdir()
            return result(stdout=json.dumps({"ok": fault != "wrong-health"}))
        raise AssertionError(f"unexpected command: {command}")

    watchers = []

    class WatcherOutput:
        def __init__(self, *, exited=False):
            self._condition = threading.Condition()
            self._lines = [] if exited else ["state=watch-ready\n", "[project: 1 change(s)]\n"]
            self._closed = exited

        def readline(self):
            with self._condition:
                while not self._lines and not self._closed:
                    self._condition.wait()
                return self._lines.pop(0) if self._lines else ""

        def finish(self, summary):
            with self._condition:
                self._lines.append(summary)
                self._closed = True
                self._condition.notify_all()

        def close(self):
            with self._condition:
                self._closed = True
                self._condition.notify_all()

    class FakeWatcher:
        def __init__(self, *, exited=False, stop_failure=False):
            self.stdout = WatcherOutput(exited=exited)
            self.returncode = 1 if exited else None
            self.stop_failure = stop_failure
            self.killed = False
            self.signals = []

        def poll(self):
            return self.returncode

        def send_signal(self, shutdown_signal):
            self.signals.append(shutdown_signal)
            cycles = 1 if shutdown_signal == signal.SIGTERM else 0
            self.stdout.finish(
                f"Watch stopped after {cycles} re-mine cycle(s), {cycles} event(s)\n"
            )
            self.returncode = 1 if self.stop_failure else 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = 0

    def launch(command, **kwargs):
        calls.append(([str(item) for item in command], kwargs))
        if fault == "watcher-launch":
            raise OSError("watcher unavailable")
        watcher = FakeWatcher(exited=fault == "watcher-exit", stop_failure=fault == "watcher-stop")
        watchers.append(watcher)
        return watcher

    row = rrg._run_installed_workflow_happy_path_scenario(
        [str(console.resolve())],
        {"SAFE": "1"},
        scenario_root,
        neutral,
        repository_root=repository_root,
        network_attempts=attempts,
        run_subprocess=run,
        popen=launch,
    )

    assert row["id"] == "installed_golden_workflow_happy_path"
    assert row["status"] == ("pass" if fault == "success" else "fail")
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == (
        0 if fault == "success" else 1
    )
    assert str(tmp_path) not in row["detail"]
    assert all(command[0] == str(console.resolve()) for command, _kwargs in calls)
    assert all(kwargs["cwd"] == str(neutral) for _command, kwargs in calls)
    assert all(kwargs["env"] == {"SAFE": "1"} for _command, kwargs in calls)
    assert all(watcher.poll() is not None for watcher in watchers)
    assert all(
        watcher.signals == ([] if fault == "watcher-exit" else [signal.SIGTERM])
        for watcher in watchers
    )


def test_installed_golden_uses_watch_extra_provenance_neutral_cwd_and_safe_env(
    tmp_path, monkeypatch
):
    wheel = _write_candidate_wheel(tmp_path)
    cache = _write_model_cache(tmp_path / "hf")
    calls = []
    _stub_direct_golden_scenarios(monkeypatch)
    extra_calls = []

    def run_extras(**kwargs):
        extra_calls.append(kwargs)

    monkeypatch.setattr(rrg, "_run_installed_extra_and_export_reconciliation", run_extras)
    recovery_calls = []
    recovery_success = rrg._make_row(
        "installed_golden_recovery_safety",
        rrg.INSTALLED_RECOVERY_SAFETY_COMMAND,
        "pass",
        "complete",
    )

    def run_recovery(*args, **kwargs):
        recovery_calls.append((args, kwargs))
        return recovery_success

    monkeypatch.setattr(rrg, "_run_installed_recovery_safety_scenario", run_recovery)
    path_calls = []
    path_success = rrg._make_row(
        "installed_golden_path_contracts",
        rrg.INSTALLED_PATH_CONTRACT_COMMAND,
        "pass",
        "complete",
    )

    def run_paths(*args, **kwargs):
        path_calls.append((args, kwargs))
        return path_success

    monkeypatch.setattr(rrg, "_run_installed_path_contract_scenario", run_paths)
    schedule_calls = []
    schedule_success = rrg._make_row(
        "installed_golden_schedule_snippets",
        rrg.INSTALLED_SCHEDULE_SNIPPETS_COMMAND,
        "pass",
        "complete",
    )

    def run_schedules(*args, **kwargs):
        schedule_calls.append((args, kwargs))
        return schedule_success

    monkeypatch.setattr(rrg, "_run_installed_schedule_snippet_scenario", run_schedules)
    watcher_calls = []
    watcher_success = rrg._make_row(
        "installed_golden_watcher_signals",
        rrg.INSTALLED_WATCHER_SIGNALS_COMMAND,
        "pass",
        "complete",
    )

    def run_watcher(*args, **kwargs):
        watcher_calls.append((args, kwargs))
        return watcher_success

    monkeypatch.setattr(rrg, "_run_installed_watcher_signal_cleanup_scenario", run_watcher)
    workflow_calls = []
    workflow_success = rrg._make_row(
        "installed_golden_workflow_happy_path",
        rrg.INSTALLED_WORKFLOW_HAPPY_PATH_COMMAND,
        "pass",
        "complete",
    )

    def run_workflow(*args, **kwargs):
        workflow_calls.append((args, kwargs))
        return workflow_success

    monkeypatch.setattr(rrg, "_run_installed_workflow_happy_path_scenario", run_workflow)
    diary_calls = []
    diary_success = rrg._make_row(
        "installed_golden_diary_blank_required_fields",
        rrg.INSTALLED_DIARY_BLANK_REQUIRED_FIELDS_COMMAND,
        "pass",
        "complete",
    )

    def run_diary(*args, **kwargs):
        diary_calls.append((args, kwargs))
        return diary_success

    monkeypatch.setattr(rrg, "_run_installed_diary_blank_required_fields_scenario", run_diary)
    non_regular_calls = []
    non_regular_success = rrg._make_row(
        "installed_golden_non_regular_sources",
        rrg.INSTALLED_NON_REGULAR_SOURCE_COMMAND,
        "pass",
        "complete",
    )

    def run_non_regular(*args, **kwargs):
        non_regular_calls.append((args, kwargs))
        return non_regular_success

    monkeypatch.setattr(rrg, "_run_installed_non_regular_source_scenario", run_non_regular)

    rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={
            "PATH": "/usr/bin",
            "MEMPALACE_TEST_HF_HOME": str(cache),
            "GITHUB_TOKEN": "must-not-forward",
            "PYTHONPATH": "must-not-forward",
        },
        run_subprocess=_successful_golden_runner(calls),
    )

    assert [row["status"] for row in rows] == ["pass"] * 26
    assert [row["id"] for row in rows][2:16] == [
        "installed_golden_recovery_safety",
        "installed_golden_path_contracts",
        "installed_golden_diary_blank_required_fields",
        "installed_golden_schedule_snippets",
        "installed_golden_alias_containment",
        "installed_golden_watcher_signals",
        "installed_golden_workflow_happy_path",
        "installed_golden_fetch_model",
        "installed_golden_read_failures",
        "installed_golden_convo_full_replace",
        "installed_golden_cleanup_poststate",
        "installed_golden_rollback_no_candidate",
        "installed_golden_compress_retry",
        "installed_golden_split",
    ]
    install = next(
        command for command, _kwargs in calls if command[1:4] == ["-m", "pip", "install"]
    )
    assert install[-1] == f"{wheel.resolve()}[watch]"
    site_script = rrg._load_sibling(
        "_release_install_metadata_golden", "release_install_metadata_smoke.py"
    )._SITE_PACKAGES_SCRIPT
    _site_command, site_kwargs = next(
        (command, kwargs) for command, kwargs in calls if command[-1] == site_script
    )
    assert Path(site_kwargs["cwd"]).name == "neutral"
    assert site_kwargs["env"]["PIP_CONFIG_FILE"] == os.devnull
    assert site_kwargs["env"]["PIP_KEYRING_PROVIDER"] == "disabled"
    assert "GITHUB_TOKEN" not in site_kwargs["env"]
    assert "PYTHONPATH" not in site_kwargs["env"]
    provenance_command, golden_kwargs = next(
        (command, kwargs)
        for command, kwargs in calls
        if len(command) > 2 and command[1] == "-c" and "importlib.metadata" in command[2]
    )
    assert provenance_command[1] == "-c"
    assert all(Path(command[0]).name != "pytest" for command, _kwargs in calls)
    assert all(command[1:3] != ["-m", "pytest"] for command, _kwargs in calls)
    assert all(
        "test_cli_golden_scenarios" not in str(argument)
        for command, _kwargs in calls
        for argument in command
    )
    assert Path(golden_kwargs["cwd"]).name == "neutral"
    assert golden_kwargs["env"]["MEMPALACE_TEST_INSTALLED_CLI"].endswith("/bin/mempalace-code")
    assert golden_kwargs["env"]["HF_HOME"] != str(cache.resolve())
    assert golden_kwargs["env"]["PIP_CONFIG_FILE"] == os.devnull
    assert golden_kwargs["env"]["PIP_KEYRING_PROVIDER"] == "disabled"
    assert golden_kwargs["env"]["HF_HUB_OFFLINE"] == "1"
    assert "GITHUB_TOKEN" not in golden_kwargs["env"]
    assert "PYTHONPATH" not in golden_kwargs["env"]
    assert len(extra_calls) == 1
    assert extra_calls[0]["hf_home"] == Path(golden_kwargs["env"]["HF_HOME"])
    assert extra_calls[0]["platform_name"] == sys.platform
    assert len(recovery_calls) == 1
    recovery_args, recovery_kwargs = recovery_calls[0]
    assert Path(recovery_args[0][0]).is_absolute()
    assert Path(recovery_args[3]).name == "neutral"
    assert recovery_args[1] == golden_kwargs["env"]
    assert recovery_kwargs["repository_root"] == tmp_path
    assert Path(recovery_kwargs["network_attempts"]).name == "socket-attempts.log"
    assert len(path_calls) == 1
    path_args, path_kwargs = path_calls[0]
    assert Path(path_args[0][0]).is_absolute()
    assert Path(path_args[3]).name == "neutral"
    assert path_kwargs["repository_root"] == tmp_path
    assert Path(path_kwargs["network_attempts"]).name == "socket-attempts.log"
    assert len(diary_calls) == 1
    diary_args, diary_kwargs = diary_calls[0]
    assert Path(diary_args[0][0]).is_absolute()
    assert Path(diary_args[3]).name == "neutral"
    assert diary_args[1] == golden_kwargs["env"]
    assert diary_kwargs["repository_root"] == tmp_path
    assert Path(diary_kwargs["network_attempts"]).name == "socket-attempts.log"
    assert len(schedule_calls) == 1
    schedule_args, schedule_kwargs = schedule_calls[0]
    assert Path(schedule_args[0][0]).is_absolute()
    assert Path(schedule_args[3]).name == "neutral"
    assert schedule_kwargs["repository_root"] == tmp_path
    assert len(watcher_calls) == 1
    watcher_args, watcher_kwargs = watcher_calls[0]
    assert Path(watcher_args[0][0]).is_absolute()
    assert Path(watcher_args[3]).name == "neutral"
    assert watcher_kwargs["repository_root"] == tmp_path
    assert Path(watcher_kwargs["network_attempts"]).name == "socket-attempts.log"
    assert len(workflow_calls) == 1
    workflow_args, workflow_kwargs = workflow_calls[0]
    assert Path(workflow_args[0][0]).is_absolute()
    assert Path(workflow_args[3]).name == "neutral"
    assert workflow_kwargs["repository_root"] == tmp_path
    assert Path(workflow_kwargs["network_attempts"]).name == "socket-attempts.log"
    assert len(non_regular_calls) == 1
    non_regular_args, non_regular_kwargs = non_regular_calls[0]
    assert Path(non_regular_args[0][0]).is_absolute()
    assert Path(non_regular_args[3]).name == "neutral"
    assert non_regular_args[1] == golden_kwargs["env"]
    assert non_regular_kwargs["repository_root"] == tmp_path
    assert Path(non_regular_kwargs["network_attempts"]).name == "socket-attempts.log"
    for command, kwargs in calls[:2]:
        assert kwargs["cwd"] == golden_kwargs["cwd"]
        setup_home = Path(kwargs["env"]["HOME"])
        setup_cache = Path(kwargs["env"]["XDG_CACHE_HOME"])
        assert setup_home.name == "setup-home"
        assert setup_home.parent == Path(kwargs["cwd"]).parent
        assert setup_cache.parent.parent == setup_home.parent
        assert "GITHUB_TOKEN" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]

    recovery_failure = rrg._make_row(
        "installed_golden_recovery_safety",
        rrg.INSTALLED_RECOVERY_SAFETY_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_recovery_safety_scenario",
        lambda *args, **kwargs: recovery_failure,
    )
    recovery_failure_calls = []
    recovery_failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(recovery_failure_calls),
    )
    assert recovery_failed_rows == [recovery_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in recovery_failure_calls
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_recovery_safety_scenario",
        lambda *args, **kwargs: recovery_success,
    )

    path_failure = rrg._make_row(
        "installed_golden_path_contracts",
        rrg.INSTALLED_PATH_CONTRACT_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_path_contract_scenario",
        lambda *args, **kwargs: path_failure,
    )
    path_failure_calls = []
    path_failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(path_failure_calls),
    )
    assert path_failed_rows == [path_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in path_failure_calls
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_path_contract_scenario",
        lambda *args, **kwargs: path_success,
    )

    schedule_failure = rrg._make_row(
        "installed_golden_schedule_snippets",
        rrg.INSTALLED_SCHEDULE_SNIPPETS_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_schedule_snippet_scenario",
        lambda *args, **kwargs: schedule_failure,
    )
    schedule_failure_calls = []
    schedule_failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(schedule_failure_calls),
    )
    assert schedule_failed_rows == [schedule_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in schedule_failure_calls
    )

    monkeypatch.setattr(
        rrg,
        "_run_installed_schedule_snippet_scenario",
        lambda *args, **kwargs: schedule_success,
    )
    alias_failure = rrg._make_row(
        "installed_golden_alias_containment",
        rrg.INSTALLED_ALIAS_TARGET_CONTAINMENT_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_alias_target_containment_scenario",
        lambda *args, **kwargs: alias_failure,
    )
    alias_failure_calls = []
    alias_failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(alias_failure_calls),
    )
    assert alias_failed_rows == [alias_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in alias_failure_calls
    )

    alias_success = rrg._make_row(
        "installed_golden_alias_containment",
        rrg.INSTALLED_ALIAS_TARGET_CONTAINMENT_COMMAND,
        "pass",
        "complete",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_alias_target_containment_scenario",
        lambda *args, **kwargs: alias_success,
    )

    watcher_failure = rrg._make_row(
        "installed_golden_watcher_signals",
        rrg.INSTALLED_WATCHER_SIGNALS_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_watcher_signal_cleanup_scenario",
        lambda *args, **kwargs: watcher_failure,
    )
    watcher_failure_calls = []
    watcher_failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(watcher_failure_calls),
    )
    assert watcher_failed_rows == [watcher_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in watcher_failure_calls
    )

    monkeypatch.setattr(
        rrg,
        "_run_installed_watcher_signal_cleanup_scenario",
        lambda *args, **kwargs: watcher_success,
    )
    workflow_failure = rrg._make_row(
        "installed_golden_workflow_happy_path",
        rrg.INSTALLED_WORKFLOW_HAPPY_PATH_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_workflow_happy_path_scenario",
        lambda *args, **kwargs: workflow_failure,
    )
    workflow_failure_calls = []
    workflow_failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(workflow_failure_calls),
    )
    assert workflow_failed_rows == [workflow_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in workflow_failure_calls
    )

    monkeypatch.setattr(
        rrg,
        "_run_installed_workflow_happy_path_scenario",
        lambda *args, **kwargs: workflow_success,
    )
    non_regular_failure = rrg._make_row(
        "installed_golden_non_regular_sources",
        rrg.INSTALLED_NON_REGULAR_SOURCE_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_non_regular_source_scenario",
        lambda *args, **kwargs: non_regular_failure,
    )
    non_regular_failure_calls = []
    non_regular_failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(non_regular_failure_calls),
    )
    assert non_regular_failed_rows == [non_regular_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in non_regular_failure_calls
    )
    monkeypatch.setattr(
        rrg,
        "_run_installed_non_regular_source_scenario",
        lambda *args, **kwargs: non_regular_success,
    )
    fetch_failure = rrg._make_row(
        "installed_golden_fetch_model",
        rrg.INSTALLED_FETCH_MODEL_COMMAND,
        "fail",
        f"bounded failure; rerun: {rrg.INSTALLED_GOLDEN_COMMAND}",
    )
    monkeypatch.setattr(
        rrg, "_run_installed_fetch_model_scenario", lambda *args, **kwargs: fetch_failure
    )
    failure_calls = []
    failed_rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(failure_calls),
    )
    assert failed_rows == [fetch_failure]
    assert not any(
        str(tmp_path / "tests/test_cli_golden_scenarios.py") in command
        for command, _kwargs in failure_calls
    )


def test_installed_custom_models_platform_contours(tmp_path):
    python_bin = tmp_path / "venv" / "bin" / "python"
    wheel = tmp_path / "mempalace_code-1.13.5-py3-none-any.whl"

    linux = rrg._installed_extra_install_commands(python_bin, wheel, "custom-models", "linux")
    assert linux == [
        (
            "custom-models CPU prerequisite",
            [
                str(python_bin),
                "-m",
                "pip",
                "install",
                "torch",
                "--index-url",
                "https://download.pytorch.org/whl/cpu",
            ],
        ),
        (
            "custom-models candidate extra",
            [str(python_bin), "-m", "pip", "install", f"{wheel}[custom-models]"],
        ),
    ]
    assert rrg._installed_extra_install_commands(python_bin, wheel, "custom-models", "darwin") == [
        (
            "custom-models candidate extra",
            [str(python_bin), "-m", "pip", "install", f"{wheel}[custom-models]"],
        )
    ]
    assert rrg._installed_extra_install_commands(python_bin, wheel, "spellcheck", "linux") == [
        (
            "spellcheck candidate extra",
            [str(python_bin), "-m", "pip", "install", f"{wheel}[spellcheck]"],
        )
    ]


def test_installed_custom_models_install_failure_is_bounded_and_sanitized():
    result = SimpleNamespace(
        returncode=17,
        stdout="ignored stdout",
        stderr="/home/private-user/build/wheel " + "resolver detail " * 200,
    )
    failure = rrg._installed_extra_install_failure("custom-models candidate extra", result)
    row = rrg._make_row(
        "installed_golden_suite",
        rrg.INSTALLED_GOLDEN_COMMAND,
        "fail",
        rrg._installed_extra_suite_failure(failure),
    )

    assert row["status"] == "fail"
    assert "custom-models candidate extra failed with exit status 17" in row["detail"]
    assert "resolver detail" in row["detail"]
    assert "ignored stdout" not in row["detail"]
    assert "/home/private-user" not in row["detail"]
    assert len(row["detail"]) <= rrg._DETAIL_LIMIT
    assert row["detail"].count(f"rerun: {rrg.INSTALLED_GOLDEN_COMMAND}") == 1


def test_installed_custom_models_enospc_has_one_owned_tmpdir_retry(monkeypatch):
    monkeypatch.setattr(rrg.tempfile, "gettempdir", lambda: "/tmp")
    result = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="full " * 300 + "/tmp/private-build: [Errno 28] No space left on device",
    )
    failure = rrg._installed_extra_install_failure("custom-models CPU prerequisite", result)
    row = rrg._make_row(
        "installed_golden_suite",
        rrg.INSTALLED_GOLDEN_COMMAND,
        "fail",
        rrg._installed_extra_suite_failure(failure),
    )

    assert (
        "current status: custom-models CPU prerequisite failed with exit status 1" in row["detail"]
    )
    assert row["detail"].count("current status:") == 1
    assert "/tmp/private-build" not in row["detail"]
    assert row["detail"].count(rrg.INSTALLED_CUSTOM_MODELS_ENOSPC_RECOVERY) == 1
    assert row["detail"].count("TMPDIR=") == 1
    assert "error: No space left on device" in row["detail"]
    assert "rerun:" not in row["detail"]
    assert len(row["detail"]) <= rrg._DETAIL_LIMIT

    launch_failure = rrg._installed_extra_install_failure(
        "custom-models candidate extra", OSError(errno.ENOSPC, "disk full")
    )
    assert "exit status launch error" in launch_failure
    assert launch_failure.count(rrg.INSTALLED_CUSTOM_MODELS_ENOSPC_RECOVERY) == 1


_ONNX_PCI_FILENAME = "5620e0c7-8062-4dce-aeb7-520c7ef76171"
_ONNX_PCI_WARNING = (
    "\x1b[0;93m2026-08-31 13:57:08.504718570 "
    "[W:onnxruntime:Default, device_discovery.cc:146 GetPciBusId] "
    "Skipping pci_bus_id for PCI path at "
    '"/sys/devices/LNXSYSTM:00/LNXSYBUS:00/ACPI0004:00/MSFT1000:00/'
    f'{_ONNX_PCI_FILENAME}" because filename "{_ONNX_PCI_FILENAME}" did not match '
    "expected pattern of [0-9a-f]+:[0-9a-f]+:[0-9a-f]+[.][0-9a-f]+\x1b[m\n"
)


@pytest.mark.parametrize(
    ("machine", "warning"),
    [
        ("AARCH64", f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n"),
        ("arm64", f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n"),
        ("AARCH64", _ONNX_PCI_WARNING),
        (
            "arm64",
            _ONNX_PCI_WARNING.replace(_ONNX_PCI_FILENAME, "7a642fc3-c8af-4f1e-985c-71d5ee0f2c90"),
        ),
    ],
    ids=("cpuid-aarch64", "cpuid-arm64", "pci-aarch64", "pci-arm64"),
)
def test_installed_golden_accepts_exact_linux_arm_onnx_warning_and_completes_suite(
    tmp_path, monkeypatch, machine, warning
):
    wheel = _write_candidate_wheel(tmp_path)
    cache = _write_model_cache(tmp_path / "hf")
    calls = []
    _stub_direct_golden_scenarios(monkeypatch)
    rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_golden_runner_with_model_probe_diagnostic(calls, stderr=warning),
        platform_name="linux",
        machine=machine,
    )

    assert len(rows) == 26
    assert [row["status"] for row in rows] == ["pass"] * 26
    assert rows[-1] == {
        "id": "installed_golden_suite",
        "command": rrg.INSTALLED_GOLDEN_COMMAND,
        "status": "pass",
        "detail": "complete golden CLI suite, optional extras, and public exports passed offline",
    }
    assert any(
        len(command) > 2 and command[1:3] == ["-c", rrg.INSTALLED_MODEL_CACHE_PROBE]
        for command, _kwargs in calls
    )


@pytest.mark.parametrize(
    ("platform_name", "machine", "returncode", "stderr"),
    [
        ("linux", "x86_64", 0, _ONNX_PCI_WARNING),
        ("darwin", "arm64", 0, _ONNX_PCI_WARNING),
        ("linux", "unknown", 0, _ONNX_PCI_WARNING),
        ("linux", "arm64", 1, _ONNX_PCI_WARNING),
        ("linux", "arm64", 0, _ONNX_PCI_WARNING.removesuffix("\n")),
        ("linux", "arm64", 0, f" {_ONNX_PCI_WARNING}"),
        ("linux", "arm64", 0, f"{_ONNX_PCI_WARNING} "),
        ("linux", "arm64", 0, _ONNX_PCI_WARNING.replace("GetPciBusId", "getpcibusid")),
        ("linux", "arm64", 0, _ONNX_PCI_WARNING.replace("because filename", "because filename:")),
        ("linux", "arm64", 0, _ONNX_PCI_WARNING.removeprefix("\x1b[0;93m")),
        ("linux", "arm64", 0, _ONNX_PCI_WARNING.replace("\x1b[m", "\x1b[0m")),
        ("linux", "arm64", 0, _ONNX_PCI_WARNING.replace(_ONNX_PCI_FILENAME, "")),
        ("linux", "arm64", 0, _ONNX_PCI_WARNING.replace(_ONNX_PCI_FILENAME, "a" * 65)),
        (
            "linux",
            "arm64",
            0,
            _ONNX_PCI_WARNING.replace(_ONNX_PCI_FILENAME, "5620e0c7_8062-4dce-aeb7-520c7ef76171"),
        ),
        ("linux", "arm64", 0, f"{_ONNX_PCI_WARNING}{_ONNX_PCI_WARNING}"),
        ("linux", "arm64", 0, f"{_ONNX_PCI_WARNING}unexpected stderr\n"),
        ("linux", "x86_64", 0, f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n"),
        ("darwin", "arm64", 0, f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n"),
        ("linux", "unknown", 0, f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n"),
        ("linux", "arm64", 1, f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n"),
        ("linux", "arm64", 0, rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING),
        ("linux", "arm64", 0, f" {rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n"),
        ("linux", "arm64", 0, f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING.lower()}\n"),
        (
            "linux",
            "arm64",
            0,
            f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\n",
        ),
        (
            "linux",
            "arm64",
            0,
            f"{rrg.INSTALLED_GOLDEN_ONNX_CPU_WARNING}\nunexpected stderr\n",
        ),
    ],
    ids=(
        "pci-linux-x64",
        "pci-darwin-arm64",
        "pci-linux-unknown",
        "pci-nonzero-exit",
        "pci-missing-terminal-newline",
        "pci-leading-content",
        "pci-trailing-byte",
        "pci-case-drift",
        "pci-punctuation-drift",
        "pci-missing-ansi-prefix",
        "pci-malformed-ansi-reset",
        "pci-empty-path-filename",
        "pci-overlong-path-filename",
        "pci-invalid-path-character",
        "pci-duplicate",
        "pci-additional-stderr",
        "linux-x64",
        "darwin-arm64",
        "linux-unknown",
        "nonzero-exit",
        "missing-terminal-newline",
        "leading-content",
        "case-drift",
        "duplicate",
        "additional-stderr",
    ),
)
def test_installed_golden_onnx_warning_boundaries_fail_closed(
    tmp_path, monkeypatch, platform_name, machine, returncode, stderr
):
    wheel = _write_candidate_wheel(tmp_path)
    cache = _write_model_cache(tmp_path / "hf")
    calls = []
    _stub_direct_golden_scenarios(monkeypatch)

    rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_golden_runner_with_model_probe_diagnostic(
            calls, stderr=stderr, returncode=returncode
        ),
        platform_name=platform_name,
        machine=machine,
    )

    assert rows == [
        {
            "id": "installed_golden_cache",
            "command": rrg.INSTALLED_GOLDEN_COMMAND,
            "status": "fail",
            "detail": "installed package rejected the canonical FastEmbed cache; "
            + rrg._cache_recovery(),
        }
    ]


def test_installed_golden_propagates_network_failure_with_sanitized_detail(tmp_path, monkeypatch):
    wheel = _write_candidate_wheel(tmp_path)
    cache = _write_model_cache(tmp_path / "hf")
    calls = []
    _stub_direct_golden_scenarios(monkeypatch)
    attempts_paths: list[Path] = []
    non_regular_success = rrg._make_row(
        "installed_golden_non_regular_sources",
        rrg.INSTALLED_NON_REGULAR_SOURCE_COMMAND,
        "pass",
        "complete",
    )

    def record_network_attempt(*args, **kwargs):
        attempts = Path(kwargs["network_attempts"])
        attempts_paths.append(attempts)
        attempts.write_text(f"blocked connect from {attempts}\n", encoding="utf-8")
        return non_regular_success

    monkeypatch.setattr(
        rrg,
        "_run_installed_non_regular_source_scenario",
        record_network_attempt,
    )

    rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=_successful_golden_runner(calls),
    )

    assert len(rows) == 1
    assert rows[0]["id"] == "installed_golden_suite"
    assert rows[0]["status"] == "fail"
    assert "blocked connect" in rows[0]["detail"]
    assert len(attempts_paths) == 1
    assert str(attempts_paths[0]) not in rows[0]["detail"]
    assert not attempts_paths[0].parent.exists()


@pytest.mark.parametrize(
    ("failure", "detail"),
    [
        (OSError("launcher unavailable"), "subprocess failed: launcher unavailable"),
        (
            subprocess.TimeoutExpired(["python", "-m", "venv"], 120),
            "subprocess timed out after 120s",
        ),
    ],
)
def test_installed_golden_reports_subprocess_launch_failures_as_rows(tmp_path, failure, detail):
    wheel = _write_candidate_wheel(tmp_path)
    cache = _write_model_cache(tmp_path / "hf")

    def fail_launch(*args, **kwargs):
        raise failure

    rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=fail_launch,
    )

    assert rows[0]["id"] == "installed_golden_install"
    assert rows[0]["status"] == "fail"
    assert rows[0]["detail"] == detail


def test_installed_golden_refuses_site_guard_path_outside_candidate_venv(tmp_path):
    wheel = _write_candidate_wheel(tmp_path)
    cache = _write_model_cache(tmp_path / "hf")
    calls = []
    success = _successful_golden_runner(calls)

    def outside_site(command, **kwargs):
        result = success(command, **kwargs)
        if [str(item) for item in command][-1] == rrg._load_sibling(
            "_release_install_metadata_golden", "release_install_metadata_smoke.py"
        )._SITE_PACKAGES_SCRIPT:
            return SimpleNamespace(returncode=0, stdout=json.dumps([str(tmp_path)]), stderr="")
        return result

    rows = rrg._run_installed_golden_wheel(
        tmp_path,
        wheel,
        base_env={"PATH": "/usr/bin", "MEMPALACE_TEST_HF_HOME": str(cache)},
        run_subprocess=outside_site,
    )

    assert rows[0]["id"] == "installed_golden_guard"
    assert rows[0]["status"] == "fail"
    assert rows[0]["detail"] == "installed site-packages resolved outside the candidate venv"


@pytest.mark.parametrize("candidate_sha", [None, "", "abc", "g" * 40])
def test_run_readiness_rejects_missing_or_malformed_sha_before_build(tmp_path, candidate_sha):
    with patch.object(rrg, "_build_artifacts", side_effect=AssertionError("build must not run")):
        result = rrg.run_readiness(tmp_path, candidate_sha=candidate_sha)

    assert result["ok"] is False
    assert result["completion"] == "failed"
    assert result["rows"][0]["id"] == "candidate_sha"
    assert "explicit 40-hex candidate SHA" in result["rows"][0]["detail"]


def test_readiness_runs_installed_smoke_exactly_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        rrg,
        "_run_installed_application",
        lambda dist_dir: (
            calls.append(dist_dir)
            or [rrg._make_row("installed_venv", "installed smoke", "pass", "complete")]
        ),
    )
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)

    assert result["ok"] is True
    assert len(calls) == 1
    assert [row["id"] for row in result["rows"]].count("installed_venv") == 1


# ── all-green readiness ────────────────────────────────────────────────────────


def test_run_readiness_all_green(tmp_path):
    """When all sub-checks pass, run_readiness returns ok=True."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)

    assert result["ok"] is True
    assert len(result["rows"]) > 0
    statuses = {r["status"] for r in result["rows"]}
    assert "fail" not in statuses


def test_run_readiness_public_admission_rows_pass_with_read_only_fixtures(tmp_path):
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(
            tmp_path,
            public_admission=True,
            version="1.2.3",
            candidate_sha=SHA,
            public_read=_admission_public_read(),
        )

    assert result["ok"] is True
    ids = {row["id"] for row in result["rows"]}
    assert "aggregate_required_check" in ids
    assert "public_main_protection" in ids
    assert "public_v_tag_ruleset" in ids
    assert "public_orphan_tags" in ids
    assert "dependency_audit_freshness" in ids


def test_run_readiness_public_admission_failures_propagate_with_remediation(tmp_path):
    def github_failures(query) -> tuple[int, str, str]:
        if query.endpoint == "github_check_runs":
            data = {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "release-required",
                        "head_sha": SHA,
                        "status": "completed",
                        "conclusion": "cancelled",
                    }
                ],
            }
            return 0, json.dumps(data), ""
        if query.endpoint == "github_branch_rules":
            return 0, json.dumps([]), ""
        if query.endpoint in {"github_rulesets", "github_ruleset"}:
            return 0, json.dumps([]), ""
        if query.endpoint == "github_releases":
            return 0, json.dumps([]), ""
        if query.endpoint == "github_workflow_runs" and query.values[1] == "Dependency Audit":
            return 0, json.dumps([_audit_run(conclusion="failure")]), ""
        return 0, "[]", ""

    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(
            tmp_path,
            public_admission=True,
            version="1.2.3",
            candidate_sha=SHA,
            public_read=_admission_public_read(github_read=github_failures),
        )

    assert result["ok"] is False
    failing = {row["id"]: row for row in result["rows"] if row["status"] != "pass"}
    assert failing["aggregate_required_check"]["status"] == "fail"
    assert failing["public_main_protection"]["status"] == "fail"
    assert failing["public_v_tag_ruleset"]["status"] == "fail"
    assert failing["public_orphan_tags"]["status"] == "fail"
    assert failing["dependency_audit_freshness"]["status"] == "fail"
    assert all(row.get("remediation") for row in failing.values())


def test_run_readiness_inventory_failure_propagates(tmp_path):
    """A gate_inventory failure sets ok=False."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_fail()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)

    assert result["ok"] is False
    fail_rows = [r for r in result["rows"] if r["status"] == "fail"]
    assert any(r["id"] == "gate_inventory" for r in fail_rows)


def test_run_readiness_build_failure_stops_artifact_check(tmp_path):
    """When build fails, artifact inspection is skipped."""
    artifact_check_called = []

    def mock_artifact(_dist_dir):
        artifact_check_called.append(True)
        return _mock_artifact_rows_ok()

    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_fail()),
        patch.object(rrg, "_run_artifact_inspection", side_effect=mock_artifact),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)

    assert result["ok"] is False
    assert not artifact_check_called, "artifact inspection must not run when build fails"
    build_row = next(r for r in result["rows"] if r["id"] == "artifact_build")
    assert build_row["status"] == "fail"


def test_run_readiness_artifact_inspection_failure(tmp_path):
    """Artifact inspection failure sets ok=False."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_fail()),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)

    assert result["ok"] is False
    fail_ids = {r["id"] for r in result["rows"] if r["status"] == "fail"}
    assert any("sdist" in rid for rid in fail_ids)


# ── artifact_only mode ────────────────────────────────────────────────────────


def test_run_readiness_artifact_only_skips_inventory_and_installed_application(tmp_path):
    """In artifact_only mode, inventory and installed smoke are not called."""
    inventory_called = []
    installed_called = []

    def mock_inventory(_root):
        inventory_called.append(True)
        return _mock_inventory_ok()

    def mock_installed(_dist_dir):
        installed_called.append(True)
        return []

    with (
        patch.object(rrg, "_run_inventory_check", side_effect=mock_inventory),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_installed_application", side_effect=mock_installed),
    ):
        result = rrg.run_readiness(tmp_path, artifact_only=True)

    assert not inventory_called, "inventory should not be called in artifact_only mode"
    assert not installed_called, "installed smoke should not run in artifact_only mode"
    assert result["ok"] is True


# ── JSON output ────────────────────────────────────────────────────────────────


def test_result_is_json_serializable(tmp_path):
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)

    dumped = json.dumps(result)
    parsed = json.loads(dumped)
    assert parsed["ok"] is True
    assert isinstance(parsed["rows"], list)


def test_result_rows_have_required_fields(tmp_path):
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)

    for row in result["rows"]:
        assert "id" in row, f"row missing 'id': {row}"
        assert "command" in row, f"row missing 'command': {row}"
        assert "status" in row, f"row missing 'status': {row}"
        assert "detail" in row, f"row missing 'detail': {row}"


# ── CLI main() ────────────────────────────────────────────────────────────────


def test_main_requires_check_or_artifact_only(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        rrg.main([])
    assert exc_info.value.code != 0


def test_main_json_all_green(tmp_path, capsys):
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "Path", side_effect=lambda *a, **kw: tmp_path),
    ):
        rrg.main(["--check", "--candidate-sha", SHA, "--json"])

    out = capsys.readouterr().out
    if out.strip():
        data = json.loads(out)
        assert "ok" in data
        assert "rows" in data


def test_main_single_canonical_failure_exits_1(tmp_path):
    """Any canonical gate failure causes exit code 1."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_fail()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
    ):
        result = rrg.run_readiness(tmp_path, candidate_sha=SHA)
    assert result["ok"] is False


def test_installed_optional_extras_exclude_retired_chroma(tmp_path):
    venv = tmp_path / "venv"
    site = venv / "lib" / "python" / "site-packages" / "mempalace_code"
    site.mkdir(parents=True)
    payload = {
        "bindings": {
            "root_main_is_one_shot_main": True,
            "mcp_tools_is_registry_tools": True,
            "mcp_handle_request_is_dispatch": True,
            "mcp_main_is_dispatch": True,
        },
        "owners": [
            {
                "owner": owner,
                "file": str(site / ("__init__.py" if owner == "mempalace_code" else "owner.py")),
                "exports": list(exports),
            }
            for owner, exports in rrg.INSTALLED_PUBLIC_EXPORTS.items()
        ],
    }
    exports = rrg._parse_installed_public_exports(
        json.dumps(payload), venv=venv, repository_root=tmp_path / "repository"
    )
    extras = ("custom-models", "spellcheck", "treesitter", "watch")
    evidence = {f"extra:{extra}": True for extra in extras}
    evidence["chroma:retired"] = True
    evidence.update(
        {
            f"export:{owner}:{member}": True
            for owner, members in exports.items()
            for member in members
        }
    )

    assert (
        rrg._reconcile_installed_optional_extras_and_public_exports(extras, exports, evidence)
        is None
    )
    assert "chroma" not in extras
    assert "chroma-migration" not in extras

    binding_hostile_documents = [
        {
            **{
                key: value
                for key, value in payload["bindings"].items()
                if key != "root_main_is_one_shot_main"
            },
            "root_main_is_cli_main": True,
        },
        {**payload["bindings"], "root_main_is_one_shot_main": False},
        {
            key: value
            for key, value in payload["bindings"].items()
            if key != "root_main_is_one_shot_main"
        },
        {**payload["bindings"], "unexpected_binding": True},
        {**payload["bindings"], "mcp_tools_is_registry_tools": False},
        {**payload["bindings"], "mcp_handle_request_is_dispatch": False},
        {**payload["bindings"], "mcp_main_is_dispatch": False},
    ]
    for bindings in binding_hostile_documents:
        with pytest.raises(ValueError, match="not bound to their runtime owners"):
            rrg._parse_installed_public_exports(
                json.dumps({**payload, "bindings": bindings}),
                venv=venv,
                repository_root=tmp_path / "repository",
            )

    hostile = [
        ((*extras, "unknown"), exports, evidence),
        (extras[:-1], exports, evidence),
        (extras, {**exports, "mempalace_code": ("main",)}, evidence),
        (extras, exports, {**evidence, "extra:spellcheck": False}),
        (extras, exports, {**evidence, "export:unknown:claim": True}),
    ]
    for hostile_extras, hostile_exports, hostile_evidence in hostile:
        assert rrg._reconcile_installed_optional_extras_and_public_exports(
            hostile_extras, hostile_exports, hostile_evidence
        )

    malformed_documents = [
        "not-json",
        json.dumps({"owners": []}),
        json.dumps({**payload, "bindings": {**payload["bindings"], "mcp_main_is_dispatch": False}}),
        json.dumps({"owners": [*payload["owners"], payload["owners"][0]]}),
        json.dumps(
            {
                "owners": [
                    {**payload["owners"][0], "file": str(tmp_path / "repository" / "owner.py")},
                    *payload["owners"][1:],
                ]
            }
        ),
        json.dumps(
            {
                "owners": [
                    {**payload["owners"][0], "exports": ["main", "main"]},
                    *payload["owners"][1:],
                ]
            }
        ),
        "x" * (rrg.INSTALLED_EXPORT_OUTPUT_LIMIT + 1),
    ]
    for document in malformed_documents:
        with pytest.raises((json.JSONDecodeError, ValueError)):
            rrg._parse_installed_public_exports(
                document, venv=venv, repository_root=tmp_path / "repository"
            )


def test_installed_spellcheck_evidence_requires_exact_correction():
    source = "> mispelled quick brown fox\nassistant: unchanged\n"
    expected = "> misspelled quick brown fox\nassistant: unchanged\n"

    assert (
        rrg._installed_spellcheck_evidence_error(
            {"autocorrect": False, "output": source},
            {"autocorrect": True, "output": expected},
            source=source,
            expected=expected,
        )
        is None
    )
    assert rrg._installed_spellcheck_evidence_error(
        {"autocorrect": False, "output": source},
        {"autocorrect": True, "output": "> misspeled quick brown fox\nassistant: unchanged\n"},
        source=source,
        expected=expected,
    )


def test_installed_treesitter_evidence_requires_complete_ordered_chunks():
    chunks = [
        {
            "strategy": "treesitter_v1",
            "start": 0,
            "end": 100,
            "marker": "alpha",
            "exact": True,
        },
        {
            "strategy": "treesitter_v1",
            "start": 101,
            "end": 200,
            "marker": "beta",
            "exact": True,
        },
    ]
    evidence = {
        language: {"parser": True, "grammar": True, "chunks": chunks}
        for language in ("python", "typescript", "go", "rust")
    }

    assert rrg._installed_treesitter_evidence_error(evidence) is None
    evidence["python"] = {
        "parser": True,
        "grammar": True,
        "chunks": [{**chunk, "exact": False} for chunk in chunks],
    }
    assert rrg._installed_treesitter_evidence_error(evidence)
    evidence["python"] = {
        "parser": True,
        "grammar": True,
        "chunks": list(reversed(chunks)),
    }
    assert rrg._installed_treesitter_evidence_error(evidence)


def test_credential_free_build_env_disables_pip_config_and_keyring(tmp_path):
    env = rrg._credential_free_build_env(tmp_path / "home", tmp_path / "temp")

    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert env["PIP_KEYRING_PROVIDER"] == "disabled"


def test_materialized_model_cache_excludes_adjacent_state_and_resolves_symlinks(tmp_path):
    source_home = _write_model_cache(tmp_path / "source")
    (source_home / "token").write_text("must-not-copy", encoding="utf-8")
    source_root = source_home / storage_owner._FASTEMBED_CACHE_CHILD
    snapshot = (
        source_root
        / storage_owner._FASTEMBED_REPOSITORY
        / "snapshots"
        / storage_owner.CANONICAL_EMBED_MODEL_REVISION
    )
    (snapshot / "alias.bin").symlink_to("model.onnx")

    target_home = rrg._materialize_model_cache(source_root, source_home, tmp_path / "target")

    assert not (target_home / "token").exists()
    assert (
        not (
            target_home
            / storage_owner._FASTEMBED_CACHE_CHILD
            / storage_owner._FASTEMBED_REPOSITORY
            / "snapshots"
            / storage_owner.CANONICAL_EMBED_MODEL_REVISION
            / "alias.bin"
        )
        .resolve()
        .is_relative_to(source_home.resolve())
    )


def test_materialized_model_cache_rejects_restored_symlink_swap(tmp_path, monkeypatch):
    source_home = _write_model_cache(tmp_path / "source")
    model_root = source_home / storage_owner._FASTEMBED_CACHE_CHILD
    alias = (
        model_root
        / storage_owner._FASTEMBED_REPOSITORY
        / "snapshots"
        / storage_owner.CANONICAL_EMBED_MODEL_REVISION
        / "alias.bin"
    )
    alias.symlink_to("model.onnx")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"must-not-copy")
    original_copytree = shutil.copytree

    def swap_during_staging(source, target, *args, **kwargs):
        if Path(source) == model_root and kwargs.get("symlinks") is True:
            alias.unlink()
            alias.symlink_to(outside)
            try:
                return original_copytree(source, target, *args, **kwargs)
            finally:
                alias.unlink()
                alias.symlink_to("model.onnx")
        return original_copytree(source, target, *args, **kwargs)

    monkeypatch.setattr(rrg.shutil, "copytree", swap_during_staging)

    with pytest.raises(OSError, match="differs from validated source"):
        rrg._materialize_model_cache(model_root, source_home, tmp_path / "target")


def test_marked_migration_json_requires_one_evidence_document():
    marker = rrg.INSTALLED_MIGRATION_EVIDENCE_MARKER
    output = f"Migrating 1 drawer\n{marker}{json.dumps({'src': 1, 'dst': 1})}\n"

    assert rrg._parse_single_marked_json(output, marker, "migration") == {"src": 1, "dst": 1}
    with pytest.raises(ValueError, match="exactly one"):
        rrg._parse_single_marked_json(output + f"{marker}{{}}\n", marker, "migration")
    with pytest.raises(ValueError, match="invalid JSON"):
        rrg._parse_single_marked_json(f"{marker}not-json\n", marker, "migration")
