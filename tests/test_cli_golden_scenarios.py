"""
test_cli_golden_scenarios.py — Subprocess-level golden CLI scenarios.

Real ``python -m mempalace_code.cli`` subprocess invocations proving core user
workflows end to end: init -> mine -> status -> search -> read -> export ->
import -> backup -> restore, plus at least one important guard/failure path.
This complements tests/test_cli.py (broad, in-process) with true subprocess
isolation, captured stdout/stderr, and explicit artifact-cleanup proof.

Environment isolation: every subprocess gets a disposable HOME/XDG tree plus
MEMPALACE_VERSION_CHECK=0, HF_HUB_OFFLINE=1, and TRANSFORMERS_OFFLINE=1.

In source mode (the default), a fake ``fastembed`` package is
injected via PYTHONPATH so no ~80MB model download is ever needed. Its
embedder is deterministic (token-hash based — the same scheme as
tests/conftest.py's ``_DeterministicTestEmbedder``) so mine, search, and read
against real fixture content stay meaningful without network access. A
``sitecustomize.py`` socket guard additionally turns any accidental network
attempt into a loud subprocess failure.

In installed mode (``MEMPALACE_TEST_INSTALLED_CLI`` set), the pipx-installed
``mempalace-code`` console script carries a ``python -E`` shebang, which
ignores PYTHONPATH entirely — so the fake embedder and socket guard are never
injected onto PYTHONPATH in this mode; doing so would be dead weight at best
and misleading at worst. Installed mode therefore requires
``MEMPALACE_TEST_HF_HOME`` to be set to an existing, pre-populated Hugging
Face cache directory — the test asserts the directory exists before running
any subprocess — and sets ``HF_HOME`` to it for every subprocess, relying on
the real cached embedding model running fully offline (``HF_HUB_OFFLINE=1``,
``TRANSFORMERS_OFFLINE=1``).
"""

from __future__ import annotations

import json
import os
import queue
import runpy
import signal
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import threading

ROOT = Path(__file__).parent.parent
_SOURCE_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
    "version"
]
_RELEASE_GATE = runpy.run_path(str(ROOT / "scripts" / "release_readiness_gate.py"))
_FORBIDDEN_MARKERS = _RELEASE_GATE["INSTALLED_GOLDEN_FORBIDDEN_OUTPUT"]
_run_installed_split_scenario = _RELEASE_GATE["_run_installed_split_scenario"]
_run_installed_import_missing_scenario = _RELEASE_GATE["_run_installed_import_missing_scenario"]
_run_installed_palace_argument_scenarios = _RELEASE_GATE["_run_installed_palace_argument_scenarios"]
_run_installed_search_results_scenarios = _RELEASE_GATE["_run_installed_search_results_scenarios"]
_run_installed_version_scenario = _RELEASE_GATE["_run_installed_version_scenario"]
_run_installed_cleanup_poststate_scenario = _RELEASE_GATE[
    "_run_installed_cleanup_poststate_scenario"
]
_run_installed_rollback_no_candidate_scenario = _RELEASE_GATE[
    "_run_installed_rollback_no_candidate_scenario"
]
_run_installed_read_failure_scenario = _RELEASE_GATE["_run_installed_read_failure_scenario"]
_run_installed_convo_full_replace_scenario = _RELEASE_GATE[
    "_run_installed_convo_full_replace_scenario"
]
_run_installed_compress_retry_scenario = _RELEASE_GATE["_run_installed_compress_retry_scenario"]
_run_installed_fetch_model_scenario = _RELEASE_GATE["_run_installed_fetch_model_scenario"]
_run_installed_watcher_signal_cleanup_scenario = _RELEASE_GATE[
    "_run_installed_watcher_signal_cleanup_scenario"
]
_run_installed_alias_target_containment_scenario = _RELEASE_GATE[
    "_run_installed_alias_target_containment_scenario"
]
_run_installed_schedule_snippet_scenario = _RELEASE_GATE["_run_installed_schedule_snippet_scenario"]
_run_installed_workflow_happy_path_scenario = _RELEASE_GATE[
    "_run_installed_workflow_happy_path_scenario"
]
_run_installed_path_contract_scenario = _RELEASE_GATE["_run_installed_path_contract_scenario"]
_run_installed_diary_blank_required_fields_scenario = _RELEASE_GATE[
    "_run_installed_diary_blank_required_fields_scenario"
]
_run_installed_recovery_safety_scenario = _RELEASE_GATE["_run_installed_recovery_safety_scenario"]
_run_installed_non_regular_source_scenario = _RELEASE_GATE[
    "_run_installed_non_regular_source_scenario"
]
_PY_LINES = _RELEASE_GATE["_PY_LINES"]
_write_fixture_project = _RELEASE_GATE["_write_fixture_project"]
_INSTALLED_CLI = os.environ.get("MEMPALACE_TEST_INSTALLED_CLI")
_CLI = [_INSTALLED_CLI] if _INSTALLED_CLI else [sys.executable, "-m", "mempalace_code.cli"]

UNIQUE_SEARCH_TERM = "xylophonic_glyph_9182"
_WATCHER_SHUTDOWN_SIGNALS = (signal.SIGTERM,) + (
    (signal.SIGHUP,) if hasattr(signal, "SIGHUP") else ()
)

# ── Fake offline embedder + socket guard, injected via PYTHONPATH ──────────────

_FAKE_FASTEMBED = '''\
"""Fake FastEmbed: deterministic, local-only, no model download."""

import hashlib
import math
import re
import types

_DIM = 384


class _Tokenizer:
    def __init__(self):
        self.padding = {"length": 128, "direction": "right", "pad_id": 0,
                        "pad_type_id": 0, "pad_token": "[PAD]", "pad_to_multiple_of": None}

    def enable_padding(self, **kwargs):
        self.padding = kwargs


def _embed(text):
    vec = [0.0] * _DIM
    for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        idx = int.from_bytes(digest[:2], "little") % _DIM
        vec[idx] += 1.0 if digest[2] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class TextEmbedding:
    def __init__(self, model_name, **kwargs):
        self._model_name = model_name
        self.model = types.SimpleNamespace(tokenizer=_Tokenizer())
        import os
        import sys

        sys.stdout.write("fake buffered stdout noise\\n")
        sys.stderr.write("fake buffered stderr noise\\n")
        os.write(1, b"fake fd stdout noise\\n")
        os.write(2, b"fake fd stderr noise\\n")
        if os.environ.get("MEMPALACE_FAKE_FASTEMBED_FAIL") == "1":
            raise RuntimeError("fake model load failed")

    def embed(self, texts, **kwargs):
        return iter([_embed(t) for t in texts])
'''

_SITECUSTOMIZE = '''\
"""Socket guard: any accidental network attempt fails loudly instead of hanging."""

import socket as _socket


def _blocked_create_connection(address, *args, **kwargs):
    raise OSError(f"cli-golden-scenario guard: network blocked (connect to {address})")


_socket.create_connection = _blocked_create_connection

_OrigSocket = _socket.socket


def _blocked_connect(self, address):
    raise OSError(f"cli-golden-scenario guard: network blocked (connect to {address})")


_OrigSocket.connect = _blocked_connect
'''


@pytest.fixture(scope="session")
def fake_pkg_root(tmp_path_factory) -> Path:
    """A PYTHONPATH root providing deterministic, offline FastEmbed."""
    root = tmp_path_factory.mktemp("cli_golden_fake_pkgs")
    (root / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    fastembed_dir = root / "fastembed"
    fastembed_dir.mkdir()
    (fastembed_dir / "__init__.py").write_text(_FAKE_FASTEMBED, encoding="utf-8")
    return root


def _write_fake_fastembed_cache(hf_home: Path) -> None:
    """Write the minimum owned layout consumed by the FastEmbed-compatible fake."""
    from mempalace_code.storage import (
        CANONICAL_EMBED_MODEL_REVISION,
        canonical_fastembed_provenance,
    )

    root = hf_home / "mempalace-fastembed" / "all-MiniLM-L6-v2-v1"
    repository = root / "models--qdrant--all-MiniLM-L6-v2-onnx"
    snapshot = repository / "snapshots" / CANONICAL_EMBED_MODEL_REVISION
    snapshot.mkdir(parents=True)
    refs = repository / "refs"
    refs.mkdir()
    (refs / "main").write_text(CANONICAL_EMBED_MODEL_REVISION, encoding="utf-8")
    for name in (
        "config.json",
        "model.onnx",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ):
        (snapshot / name).write_bytes(b"fixture")
    (snapshot / "tokenizer_config.json").write_text(
        json.dumps({"max_length": 256, "model_max_length": 512}), encoding="utf-8"
    )
    (root / ".mempalace-model.json").write_text(
        json.dumps(canonical_fastembed_provenance()), encoding="utf-8"
    )


# ── Subprocess env + fixture project helpers ────────────────────────────────────


def _make_env(tmp_path: Path, fake_pkg_root: Path) -> dict:
    """Disposable HOME/XDG tree, offline flags, and mode-appropriate embedder source.

    Source mode injects the fake offline ``fastembed`` package and the
    ``sitecustomize`` socket guard via PYTHONPATH. Installed mode's console script
    has a ``python -E`` shebang that ignores PYTHONPATH, so no fake package is put
    there; it instead requires ``MEMPALACE_TEST_HF_HOME`` to already exist and points
    ``HF_HOME`` at it to use a real, pre-cached model fully offline.
    """
    home = tmp_path / "home"
    xdg_cache = tmp_path / "xdg_cache"
    xdg_config = tmp_path / "xdg_config"
    xdg_data = tmp_path / "xdg_data"
    for d in (home, xdg_cache, xdg_config, xdg_data):
        d.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["XDG_DATA_HOME"] = str(xdg_data)
    env["MEMPALACE_VERSION_CHECK"] = "0"
    env["CUDA_CACHE_DISABLE"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["MEMPALACE_DISK_MIN_FREE_BYTES"] = "1"

    if _INSTALLED_CLI:
        # The installed console script's ``python -E`` shebang ignores PYTHONPATH
        # entirely, so injecting the fake offline sentence_transformers package or
        # the sitecustomize socket guard here would be dead code — neither would
        # ever load. Installed mode instead needs a real, pre-cached model.
        hf_home = os.environ.get("MEMPALACE_TEST_HF_HOME")
        assert hf_home, (
            "MEMPALACE_TEST_INSTALLED_CLI requires MEMPALACE_TEST_HF_HOME: the installed "
            "console script's python -E shebang ignores PYTHONPATH, so the fake offline "
            "FastEmbed injection never loads and a real, pre-cached model is "
            "required instead"
        )
        hf_home_path = Path(hf_home)
        assert hf_home_path.is_dir(), f"MEMPALACE_TEST_HF_HOME is not a directory: {hf_home_path}"
        env["HF_HOME"] = str(hf_home_path)
    else:
        # Source mode's ``python -m`` invocation needs ROOT on PYTHONPATH to import
        # mempalace_code from a neutral cwd, plus the fake offline embedder package.
        hf_home = xdg_cache / "huggingface"
        _write_fake_fastembed_cache(hf_home)
        env["HF_HOME"] = str(hf_home)
        env["PYTHONPATH"] = os.pathsep.join([str(fake_pkg_root), str(ROOT)])

    return env


@dataclass
class StepResult:
    label: str
    returncode: int
    stdout: str
    stderr: str


# Every step here runs in well under a few seconds against the fake embedder;
# this margin exists to turn a hang (e.g. a future accidental confirmation
# prompt reading stdin, or a lock-file deadlock) into a loud, fast test
# failure instead of a stuck CI job — the same goal the socket guard serves
# for accidental network calls.
_STEP_TIMEOUT_SECONDS = 60
_WATCH_READY_TIMEOUT_SECONDS = 30
_WATCH_CYCLE_TIMEOUT_SECONDS = 30
_WATCH_NATIVE_REGISTRATION_RETRY_SECONDS = 6
_WATCH_STOP_TIMEOUT_SECONDS = 30


def _run_cli(
    label: str, argv: list, env: dict, cwd: Path, *, merge_stderr: bool = False
) -> StepResult:
    try:
        proc = subprocess.run(
            [*_CLI, *argv],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(cwd),
            timeout=_STEP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"{label}: hung past {_STEP_TIMEOUT_SECONDS}s instead of exiting "
            f"(check for an unexpected interactive prompt or network stall)\n"
            f"stdout={exc.stdout!r}\nstderr={exc.stderr!r}"
        )
    return StepResult(
        label=label, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr or ""
    )


def _assert_installed_cli_provenance(env: dict, cwd: Path) -> None:
    """Installed-mode imports must resolve from its wheel environment, never this checkout."""
    if not _INSTALLED_CLI:
        return

    installed_python = Path(_INSTALLED_CLI).resolve().with_name("python")
    assert installed_python.is_file(), (
        "MEMPALACE_TEST_INSTALLED_CLI must be a venv console executable with a sibling python: "
        f"{installed_python}"
    )
    result = subprocess.run(
        [
            str(installed_python),
            "-c",
            "import json, mempalace_code; print(json.dumps({'file': mempalace_code.__file__}))",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=_STEP_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"installed-cli provenance check failed\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    module_file = Path(json.loads(result.stdout)["file"]).resolve()
    assert not module_file.is_relative_to(ROOT.resolve()), (
        f"installed CLI imported mempalace_code from the source checkout: {module_file}"
    )


def _read_watcher_output(stream, lines: queue.Queue[str]) -> None:
    for line in iter(stream.readline, ""):
        lines.put(line)
    stream.close()


def _drain_watcher_output(lines: queue.Queue[str], output: list[str]) -> None:
    while True:
        try:
            output.append(lines.get_nowait())
        except queue.Empty:
            return


def _watcher_emitted(
    lines: queue.Queue[str], output: list[str], needle: str, timeout_seconds: float
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=min(1, deadline - time.monotonic()))
        except queue.Empty:
            continue
        output.append(line)
        if needle in line:
            return True
    return False


def _wait_for_watcher_output(
    lines: queue.Queue[str], output: list[str], needle: str, timeout_seconds: float
) -> None:
    if _watcher_emitted(lines, output, needle, timeout_seconds):
        return
    _drain_watcher_output(lines, output)
    pytest.fail(f"watcher did not emit {needle!r} before timeout; output:\n{''.join(output)}")


def _stop_watcher(
    process: subprocess.Popen[str] | None,
    reader: threading.Thread | None,
    lines: queue.Queue[str] | None,
    output: list[str],
) -> None:
    if process is not None and process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=_WATCH_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if reader is not None:
        reader.join(timeout=5)
    if lines is not None:
        _drain_watcher_output(lines, output)


def _write_watched_source(source: Path, revision: int) -> None:
    source.write_text(
        "\n".join(
            [
                *_PY_LINES,
                "",
                "def watched_substantive_change(value):",
                f'    """Substantive watch revision {revision} for real re-mine coverage."""',
                f"    return value * {revision + 2}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _assert_clean(step: StepResult) -> None:
    """No traceback, no version-check prompt/network text, no HF token warnings."""
    combined = step.stdout + step.stderr
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in combined, (
            f"{step.label}: forbidden marker {marker!r} leaked into output\n"
            f"stdout={step.stdout!r}\nstderr={step.stderr!r}"
        )


def _assert_ok(step: StepResult, *stdout_markers: str) -> None:
    assert step.returncode == 0, (
        f"{step.label} exited {step.returncode}\nstdout={step.stdout!r}\nstderr={step.stderr!r}"
    )
    _assert_clean(step)
    for marker in stdout_markers:
        assert marker in step.stdout, (
            f"{step.label}: expected marker {marker!r} not in stdout\nstdout={step.stdout!r}"
        )


def _assert_no_repo_artifacts(root: Path) -> None:
    """Scenario artifacts must stay inside disposable pytest temp paths (AC-7)."""
    leaked = [
        p.name
        for p in root.iterdir()
        if p.name.endswith(".tar.gz") or p.name in (".mempalace", "backups")
    ]
    assert not leaked, f"scenario artifacts leaked into repo root {root}: {leaked}"


def test_cli_golden_fetch_model_buffering_failure_and_retry(tmp_path, fake_pkg_root):
    """Direct fetch-model paths preserve progress and leave the source cache untouched."""
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)
    if not _INSTALLED_CLI:
        result = subprocess.run(_CLI + ["fetch-model"], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "already available locally" in result.stdout
        return
    row = _run_installed_fetch_model_scenario(
        _CLI,
        env,
        tmp_path / "fetch-model-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
    )

    assert row["status"] == "pass", row["detail"]


def test_cli_golden_split_creates_explicit_output_dir(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)

    row = _run_installed_split_scenario(
        _CLI,
        env,
        tmp_path / "split-scenario",
        tmp_path / "neutral-cwd",
    )

    assert row["status"] == "pass", row["detail"]


def test_cli_golden_cleanup_poststate(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)
    row = _run_installed_cleanup_poststate_scenario(
        _CLI,
        env,
        tmp_path / "cleanup-poststate-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
    )
    assert row["status"] == "pass", row["detail"]


def test_cli_golden_rollback_no_candidate_output(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)
    row = _run_installed_rollback_no_candidate_scenario(
        _CLI,
        env,
        tmp_path / "rollback-no-candidate-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
    )
    assert row["status"] == "pass", row["detail"]


def test_cli_golden_watcher_signal_cleanup(tmp_path, fake_pkg_root):
    """The source golden consumes the release-gate-owned watcher signal scenario."""
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)
    row = _run_installed_watcher_signal_cleanup_scenario(
        _CLI,
        env,
        tmp_path / "watcher-signal-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
        supported_signals=_WATCHER_SHUTDOWN_SIGNALS,
    )
    assert row["status"] == "pass", row["detail"]


def test_install_alias_explicit_target_containment_from_neutral_directory(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    source_bin = tmp_path / "source-bin"
    source_bin.mkdir()
    canonical = source_bin / "mempalace-code"
    canonical.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    canonical.chmod(0o755)
    expected_target = Path(_INSTALLED_CLI).resolve() if _INSTALLED_CLI else canonical.resolve()
    env["PATH"] = os.pathsep.join([str(source_bin), env.get("PATH", os.defpath)])
    row = _run_installed_alias_target_containment_scenario(
        _CLI,
        expected_target,
        env,
        tmp_path / "alias-containment-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
    )
    assert row["status"] == "pass", row["detail"]


def test_installed_schedule_snippets_bind_to_invoked_launcher(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    neutral_cwd = tmp_path / "neutral cwd"
    neutral_cwd.mkdir()
    _assert_installed_cli_provenance(env, neutral_cwd)
    command_prefix = _CLI
    if not _INSTALLED_CLI:
        source_console = tmp_path / "source console" / "mempalace-code"
        source_console.parent.mkdir()
        source_console.write_text(
            f"#!{sys.executable}\nfrom mempalace_code.cli import main\nmain()\n",
            encoding="utf-8",
        )
        source_console.chmod(0o755)
        command_prefix = [str(source_console)]

    row = _run_installed_schedule_snippet_scenario(
        command_prefix,
        env,
        tmp_path / "schedule-snippet-scenario",
        neutral_cwd,
        repository_root=ROOT,
    )

    assert row["id"] == "installed_golden_schedule_snippets"
    assert row["status"] == "pass", row["detail"]


# ── AC-1 / AC-4: full happy-path workflow ───────────────────────────────────────


def test_cli_golden_convo_full_replaces_exact_source(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)
    row = _run_installed_convo_full_replace_scenario(
        _CLI,
        env,
        tmp_path / "convo-full-replace-scenario",
        tmp_path,
        repository_root=ROOT,
    )

    assert row["id"] == "installed_golden_convo_full_replace"
    assert row["status"] == "pass", row


def test_cli_golden_workflow_happy_path(tmp_path, fake_pkg_root):
    """Consume the release-gate-owned composite workflow in source mode."""
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)
    row = _run_installed_workflow_happy_path_scenario(
        _CLI,
        env,
        tmp_path / "workflow-happy-path-scenario",
        tmp_path,
        repository_root=ROOT,
    )

    assert row["id"] == "installed_golden_workflow_happy_path"
    assert row["status"] == "pass", row["detail"]


def test_cli_golden_compress_retry_idempotent_recovery(tmp_path, fake_pkg_root):
    """Consume the release-gate-owned compression retry scenario in source mode."""
    env = _make_env(tmp_path, fake_pkg_root)
    row = _run_installed_compress_retry_scenario(
        _CLI,
        env,
        tmp_path / "compress-retry-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
    )
    assert row["status"] == "pass", row["detail"]
    assert row["id"] == "installed_golden_compress_retry"


# ── AC-2: important guard/failure paths ─────────────────────────────────────────


def test_cli_golden_failure_contracts(tmp_path, fake_pkg_root):
    """Consume the release-gate-owned read-failure contracts in source mode."""
    env = _make_env(tmp_path, fake_pkg_root)
    row = _run_installed_read_failure_scenario(
        _CLI,
        env,
        tmp_path / "read-failure-scenario",
        tmp_path / "neutral-read-failure-cwd",
        repository_root=ROOT,
    )
    assert row["status"] == "pass", row["detail"]


def test_installed_cli_paths_are_self_consistent_and_reconcilable(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    row = _run_installed_path_contract_scenario(
        _CLI,
        env,
        tmp_path / "path-contract-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
    )
    assert row["id"] == "installed_golden_path_contracts"
    assert row["status"] == "pass", row["detail"]
    assert row["detail"].count("rerun:") == 0


@pytest.mark.parametrize(
    ("option", "value", "other_option", "other_value"),
    [
        ("--agent", "", "--entry", "valid entry"),
        ("--agent", "   ", "--entry", "valid entry"),
        ("--entry", "", "--agent", "valid-agent"),
        ("--entry", "   ", "--agent", "valid-agent"),
    ],
)
def test_diary_write_rejects_blank_required_fields_without_poststate(
    tmp_path, fake_pkg_root, option, value, other_option, other_value
):
    env = _make_env(tmp_path, fake_pkg_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    row = _run_installed_diary_blank_required_fields_scenario(
        _CLI,
        env,
        tmp_path / "diary-blank-required-fields-scenario",
        tmp_path / "neutral-cwd",
        ((option, value, other_option, other_value),),
        repository_root=ROOT,
    )
    assert row["id"] == "installed_golden_diary_blank_required_fields"
    assert row["status"] == "pass", row["detail"]


def test_cli_recovery_safety_matrix(tmp_path, fake_pkg_root):
    """The source console consumes the release-owned recovery scenario."""
    env = _make_env(tmp_path, fake_pkg_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    row = _run_installed_recovery_safety_scenario(
        _CLI,
        env,
        tmp_path / "recovery-safety-scenario",
        tmp_path / "neutral-cwd",
        repository_root=ROOT,
    )
    assert row["id"] == "installed_golden_recovery_safety"
    assert row["status"] == "pass", row["detail"]
    assert row["detail"] == (
        "two deterministic dry runs and hostile recovery refusals preserved exact state"
    )


def test_cli_non_regular_source_guard(tmp_path, fake_pkg_root):
    """The source console consumes the release-owned non-regular source scenario."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available on this platform")

    env = _make_env(tmp_path, fake_pkg_root)
    assert env["CUDA_CACHE_DISABLE"] == "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    config_root = Path(env["HOME"]) / ".mempalace"
    config_root.mkdir()
    (config_root / "config.json").write_text("{}\n", encoding="utf-8")
    neutral_cwd = tmp_path / "neutral-cwd"
    neutral_cwd.mkdir()
    repository_sentinel = tmp_path / "repository-sentinel"
    repository_sentinel.mkdir()
    (repository_sentinel / "immutable.txt").write_text("stable\n", encoding="utf-8")
    row = _run_installed_non_regular_source_scenario(
        _CLI,
        env,
        tmp_path / "non-regular-source-scenario",
        neutral_cwd,
        repository_root=repository_sentinel,
    )
    assert row["id"] == "installed_golden_non_regular_sources"
    assert row["status"] == "pass", row["detail"]
    assert row["detail"] == (
        "project, remine, mine-all, watcher, and conversation paths rejected all supported "
        "non-regular source kinds"
    )
    assert not (Path(env["HOME"]) / ".nv" / "ComputeCache").exists()


# ── AC-5: fixture shape ──────────────────────────────────────────────────────────


def test_cli_golden_fixture_shape(tmp_path):
    """The generated fixture project is small but representative of a real repo."""
    project = _write_fixture_project(tmp_path / "project")

    files = {p.name: p for p in project.iterdir() if p.is_file()}
    assert "app.py" in files, "fixture must include a Python source file"
    assert "NOTES.md" in files, "fixture must include Markdown documentation"
    assert "settings.toml" in files, "fixture must include a config file"
    assert "service.go" in files, "fixture must include a non-Python source file"

    total_bytes = sum(p.stat().st_size for p in files.values())
    assert total_bytes < 20_000, f"fixture project too large for default CI: {total_bytes} bytes"


# ── CLI-DEGRADED-INPUT-RECOVERY: neutral-directory subprocess coverage ───────────


def test_degraded_version_flag(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)

    row = _run_installed_version_scenario(_CLI, env, tmp_path, _SOURCE_VERSION)

    assert row["status"] == "pass", row["detail"]


def test_degraded_palace_argument_contracts(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)

    rows = _run_installed_palace_argument_scenarios(
        _CLI,
        env,
        tmp_path / "palace-argument-scenarios",
        tmp_path,
    )

    assert all(row["status"] == "pass" for row in rows), rows


def test_degraded_search_results_below_one_rejected(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)

    rows = _run_installed_search_results_scenarios(
        _CLI,
        env,
        tmp_path / "search-results-scenarios",
        tmp_path,
    )

    assert all(row["status"] == "pass" for row in rows), rows
    assert [row["id"] for row in rows] == [
        "installed_golden_search_results_zero",
        "installed_golden_search_results_negative_one",
    ]


def test_degraded_import_missing_file(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    _assert_installed_cli_provenance(env, tmp_path)

    row = _run_installed_import_missing_scenario(
        _CLI,
        env,
        tmp_path / "import-missing-scenario",
        tmp_path,
    )

    assert row["status"] == "pass", row["detail"]
