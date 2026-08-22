"""
test_cli_golden_scenarios.py — Subprocess-level golden CLI scenarios.

Real ``python -m mempalace_code.cli`` subprocess invocations proving core user
workflows end to end: init -> mine -> status -> search -> read -> export ->
import -> backup -> restore, plus at least one important guard/failure path.
This complements tests/test_cli.py (broad, in-process) with true subprocess
isolation, captured stdout/stderr, and explicit artifact-cleanup proof.

Environment isolation: every subprocess gets a disposable HOME/XDG tree plus
MEMPALACE_VERSION_CHECK=0, HF_HUB_OFFLINE=1, and TRANSFORMERS_OFFLINE=1.

In source mode (the default), a fake ``sentence_transformers`` package is
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
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
_INSTALLED_CLI = os.environ.get("MEMPALACE_TEST_INSTALLED_CLI")
_CLI = [_INSTALLED_CLI] if _INSTALLED_CLI else [sys.executable, "-m", "mempalace_code.cli"]

UNIQUE_SEARCH_TERM = "xylophonic_glyph_9182"

# Negative markers that must never leak into captured output for any subprocess
# in this file — a leaked prompt/network marker means the offline contract
# (AC-3) or the version-check opt-out (MEMPALACE_VERSION_CHECK=0) broke.
_FORBIDDEN_MARKERS = (
    "Traceback (most recent call last)",
    "Enable periodic new-version checks",
    "New version available",
    "The token has not been saved",
    "hf.co/settings/tokens",
)

_PY_LINES = [
    '"""Golden CLI scenario fixture module."""',
    "",
    "",
    "def compute_xylophonic_glyph_9182(value):",
    '    """Doubles value; unique marker xylophonic_glyph_9182 anchors this chunk '
    'for search/read proof."""',
    "    return value * 2",
    "",
    "",
    "def helper_offset(value):",
    '    """Adds one; keeps the fixture module above the chunker\'s minimum-size threshold."""',
    "    return value + 1",
    "",
]

# Read the whole fixture file by its known 1-indexed line range — this proves the
# read command reconstructs the exact stored source without depending on the
# miner's internal chunk-boundary line-numbering convention.
_READ_RANGE = (1, len(_PY_LINES))
_EXPECTED_READ_SNIPPETS = (
    "def compute_xylophonic_glyph_9182(value):",
    UNIQUE_SEARCH_TERM,
    "return value * 2",
    "def helper_offset(value):",
    "return value + 1",
)


# ── Fake offline embedder + socket guard, injected via PYTHONPATH ──────────────

_FAKE_SENTENCE_TRANSFORMERS = '''\
"""Fake sentence-transformers: deterministic, local-only, no model download."""

import hashlib
import math
import re

import numpy as _np

_DIM = 384


def _embed(text):
    vec = [0.0] * _DIM
    for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        idx = int.from_bytes(digest[:2], "little") % _DIM
        vec[idx] += 1.0 if digest[2] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class SentenceTransformer:
    def __init__(self, model_name_or_path, **kwargs):
        self._model_name = model_name_or_path

    def encode(self, texts, **kwargs):
        return _np.array([_embed(t) for t in texts], dtype=_np.float32)
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
    """A PYTHONPATH root providing a deterministic, offline sentence_transformers."""
    root = tmp_path_factory.mktemp("cli_golden_fake_pkgs")
    (root / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    st_dir = root / "sentence_transformers"
    st_dir.mkdir()
    (st_dir / "__init__.py").write_text(_FAKE_SENTENCE_TRANSFORMERS, encoding="utf-8")
    return root


# ── Subprocess env + fixture project helpers ────────────────────────────────────


def _make_env(tmp_path: Path, fake_pkg_root: Path) -> dict:
    """Disposable HOME/XDG tree, offline flags, and mode-appropriate embedder source.

    Source mode injects the fake offline ``sentence_transformers`` package and the
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
            "sentence_transformers injection never loads and a real, pre-cached model is "
            "required instead"
        )
        hf_home_path = Path(hf_home)
        assert hf_home_path.is_dir(), f"MEMPALACE_TEST_HF_HOME is not a directory: {hf_home_path}"
        env["HF_HOME"] = str(hf_home_path)
    else:
        # Source mode's ``python -m`` invocation needs ROOT on PYTHONPATH to import
        # mempalace_code from a neutral cwd, plus the fake offline embedder package.
        env["PYTHONPATH"] = os.pathsep.join([str(fake_pkg_root), str(ROOT)])

    return env


def _write_fixture_project(root: Path) -> Path:
    """A small, representative project: Python, Markdown, config, and Go source."""
    root.mkdir(parents=True, exist_ok=True)

    (root / "app.py").write_text("\n".join(_PY_LINES), encoding="utf-8")

    (root / "NOTES.md").write_text(
        textwrap.dedent(
            """\
            # Golden Scenario Notes

            This fixture project proves that the mempalace-code CLI works end to end
            as a real subprocess: init, mine, status, search, read, export, import,
            backup, and restore all operate on genuine files, not mocked internals.
            """
        ),
        encoding="utf-8",
    )

    (root / "settings.toml").write_text(
        textwrap.dedent(
            """\
            [fixture]
            name = "golden-scenario"
            purpose = "prove real CLI subprocess workflows end to end"
            version = 1
            """
        ),
        encoding="utf-8",
    )

    (root / "service.go").write_text(
        textwrap.dedent(
            """\
            package main

            import "fmt"

            // goldenScenarioMarker identifies this file inside the CLI golden-scenario fixture.
            func goldenScenarioMarker() string {
            \treturn "go-fixture-marker"
            }

            func main() {
            \tfmt.Println(goldenScenarioMarker())
            }
            """
        ),
        encoding="utf-8",
    )

    return root


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


def _run_cli(label: str, argv: list, env: dict, cwd: Path) -> StepResult:
    try:
        proc = subprocess.run(
            [*_CLI, *argv],
            capture_output=True,
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
        label=label, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
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


def _directory_bytes(path: Path) -> int:
    return (
        sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
        if path.exists()
        else 0
    )


def _palace_and_sibling_backups_bytes(palace: Path) -> int:
    return _directory_bytes(palace) + _directory_bytes(palace.parent / "backups")


def _backup_archives(palace: Path) -> set[Path]:
    backups = palace.parent / "backups"
    return set(backups.glob("*.tar.gz")) if backups.exists() else set()


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


def _search_and_read_prove_roundtrip(
    label_prefix: str, palace: Path, env: dict, cwd: Path, *, expect_read_success: bool
) -> None:
    """Prove a palace is searchable — and, when metadata survived the roundtrip,
    readable — after import/restore (AC-1).

    JSONL export/import (unlike a full tar.gz backup/restore) does not carry the
    ``line_start``/``line_end`` chunk-metadata columns, so a re-imported palace
    legitimately answers ``read`` with a stale-pointer error rather than content.
    That is real, existing CLI behaviour, not a scenario bug — the failure branch
    is asserted explicitly rather than papered over.
    """
    search_step = _run_cli(
        f"{label_prefix}:search",
        ["--palace", str(palace), "search", UNIQUE_SEARCH_TERM, "--results", "10"],
        env,
        cwd,
    )
    _assert_ok(search_step, "Results for:", UNIQUE_SEARCH_TERM)
    assert "app.py" in search_step.stdout

    read_step = _run_cli(
        f"{label_prefix}:read",
        [
            "--palace",
            str(palace),
            "read",
            "app.py",
            "--start",
            str(_READ_RANGE[0]),
            "--end",
            str(_READ_RANGE[1]),
        ],
        env,
        cwd,
    )
    if expect_read_success:
        _assert_ok(read_step)
        for snippet in _EXPECTED_READ_SNIPPETS:
            assert snippet in read_step.stdout, (
                f"{label_prefix}:read missing snippet {snippet!r}\nstdout={read_step.stdout!r}"
            )
    else:
        _assert_clean(read_step)
        assert read_step.returncode != 0, (
            f"{label_prefix}:read expected non-zero exit\nstdout={read_step.stdout!r}"
        )
        assert "Stale pointer:" in read_step.stderr
        assert "Next:" in read_step.stderr


def _assert_no_repo_artifacts(root: Path) -> None:
    """Scenario artifacts must stay inside disposable pytest temp paths (AC-7)."""
    leaked = [
        p.name
        for p in root.iterdir()
        if p.name.endswith(".tar.gz") or p.name in (".mempalace", "backups")
    ]
    assert not leaked, f"scenario artifacts leaked into repo root {root}: {leaked}"


def test_install_alias_explicit_target_containment_from_neutral_directory(tmp_path, fake_pkg_root):
    env = _make_env(tmp_path, fake_pkg_root)
    neutral_cwd = tmp_path / "neutral-cwd"
    source_bin = tmp_path / "source-bin"
    target_bin = tmp_path / "target-bin"
    user_bin = tmp_path / "user-bin"
    for bin_dir in (neutral_cwd, source_bin, target_bin, user_bin):
        bin_dir.mkdir()

    canonical = source_bin / "mempalace-code"
    canonical.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    canonical.chmod(0o755)
    preexisting_path_alias = user_bin / "mempalace"
    preexisting_path_alias.symlink_to(canonical)
    target_alias = target_bin / "mempalace"
    expected_target = Path(_INSTALLED_CLI).resolve() if _INSTALLED_CLI else canonical.resolve()
    user_bin_entries_before = sorted(entry.name for entry in user_bin.iterdir())
    preexisting_alias_target_before = os.readlink(preexisting_path_alias)
    env["PATH"] = os.pathsep.join([str(user_bin), str(source_bin)])

    step = _run_cli(
        "install-alias:explicit-target-containment",
        ["install-alias", "--target-dir", str(target_bin)],
        env,
        neutral_cwd,
    )

    _assert_ok(step, str(target_alias), "mempalace-code")
    assert target_alias.is_symlink()
    assert target_alias.resolve() == expected_target
    assert preexisting_path_alias.is_symlink()
    assert preexisting_path_alias.resolve() == canonical.resolve()
    assert os.readlink(preexisting_path_alias) == preexisting_alias_target_before
    assert sorted(entry.name for entry in user_bin.iterdir()) == user_bin_entries_before


# ── AC-1 / AC-4: full happy-path workflow ───────────────────────────────────────


def test_cli_golden_workflow_happy_path(tmp_path, fake_pkg_root):
    """init, mine, no-op, backup, restore, search, read, and watch — real subprocesses."""
    env = _make_env(tmp_path, fake_pkg_root)
    project = _write_fixture_project(tmp_path / "project")
    palace_a = tmp_path / "palace_a"
    palace_b = tmp_path / "palace_b"
    palace_c = tmp_path / "palace_c"
    export_file = tmp_path / "export.jsonl"
    backup_archive = tmp_path / "backup.tar.gz"

    steps: list[StepResult] = []

    _assert_installed_cli_provenance(env, tmp_path)

    init_step = _run_cli("init", ["init", str(project), "--skip-model-download"], env, tmp_path)
    steps.append(init_step)
    _assert_ok(init_step, "Config saved:")
    assert (project / "mempalace.yaml").exists()

    mine_step = _run_cli("mine", ["--palace", str(palace_a), "mine", str(project)], env, tmp_path)
    steps.append(mine_step)
    _assert_ok(mine_step, "Drawers filed:")
    drawers_filed = int(
        next(line for line in mine_step.stdout.splitlines() if "Drawers filed:" in line)
        .split(":")[1]
        .strip()
    )
    assert drawers_filed > 0, f"expected at least one drawer filed\nstdout={mine_step.stdout!r}"

    no_op_archives_before = _backup_archives(palace_a)
    no_op_bytes_before = _palace_and_sibling_backups_bytes(palace_a)
    no_op_step = _run_cli(
        "mine:no-op", ["--palace", str(palace_a), "mine", str(project)], env, tmp_path
    )
    steps.append(no_op_step)
    _assert_ok(no_op_step, "no changes detected")
    assert _backup_archives(palace_a) == no_op_archives_before, (
        "a no-op mine must not create a managed backup archive"
    )
    assert _palace_and_sibling_backups_bytes(palace_a) == no_op_bytes_before, (
        "a no-op mine must not grow the palace or its sibling managed backups"
    )

    status_step = _run_cli("status", ["--palace", str(palace_a), "status"], env, tmp_path)
    steps.append(status_step)
    _assert_ok(status_step, "MemPalace Status", "WING: project")

    search_step = _run_cli(
        "search",
        ["--palace", str(palace_a), "search", UNIQUE_SEARCH_TERM, "--results", "10"],
        env,
        tmp_path,
    )
    steps.append(search_step)
    _assert_ok(search_step, "Results for:", UNIQUE_SEARCH_TERM, "Source:", "Match:")
    assert "app.py" in search_step.stdout

    read_step = _run_cli(
        "read",
        [
            "--palace",
            str(palace_a),
            "read",
            "app.py",
            "--start",
            str(_READ_RANGE[0]),
            "--end",
            str(_READ_RANGE[1]),
        ],
        env,
        tmp_path,
    )
    steps.append(read_step)
    _assert_ok(read_step)
    for snippet in _EXPECTED_READ_SNIPPETS:
        assert snippet in read_step.stdout, (
            f"read missing snippet {snippet!r}\nstdout={read_step.stdout!r}"
        )

    export_step = _run_cli(
        "export",
        ["--palace", str(palace_a), "export", "--out", str(export_file)],
        env,
        tmp_path,
    )
    steps.append(export_step)
    assert export_step.returncode == 0, (
        f"export exited {export_step.returncode}\nstderr={export_step.stderr!r}"
    )
    _assert_clean(export_step)
    assert "Exported" in export_step.stderr
    assert export_file.exists()
    assert export_file.stat().st_size > 0

    import_step = _run_cli(
        "import",
        ["--palace", str(palace_b), "import", str(export_file)],
        env,
        tmp_path,
    )
    steps.append(import_step)
    _assert_ok(import_step, "Imported drawers:")
    imported = int(
        next(line for line in import_step.stdout.splitlines() if "Imported drawers:" in line)
        .split(":")[1]
        .strip()
    )
    assert imported > 0, f"expected at least one imported drawer\nstdout={import_step.stdout!r}"

    _search_and_read_prove_roundtrip("imported", palace_b, env, tmp_path, expect_read_success=False)

    backup_step = _run_cli(
        "backup",
        ["--palace", str(palace_a), "backup", "--out", str(backup_archive)],
        env,
        tmp_path,
    )
    steps.append(backup_step)
    _assert_ok(backup_step, "Backed up", "Archive:")
    assert backup_archive.exists()
    assert backup_archive.stat().st_size > 0

    restore_step = _run_cli(
        "restore",
        ["--palace", str(palace_c), "restore", str(backup_archive)],
        env,
        tmp_path,
    )
    steps.append(restore_step)
    _assert_ok(restore_step, "Restored palace to:")

    _search_and_read_prove_roundtrip("restored", palace_c, env, tmp_path, expect_read_success=True)

    watcher: subprocess.Popen[str] | None = None
    watcher_reader: threading.Thread | None = None
    watcher_lines: queue.Queue[str] | None = None
    watcher_output: list[str] = []
    try:
        watcher = subprocess.Popen(
            [*_CLI, "--palace", str(palace_a), "watch", str(project), "--on-save"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env,
            cwd=str(tmp_path),
            text=True,
        )
        assert watcher.stdout is not None
        watcher_lines = queue.Queue()
        watcher_reader = threading.Thread(
            target=_read_watcher_output, args=(watcher.stdout, watcher_lines), daemon=True
        )
        watcher_reader.start()
        _wait_for_watcher_output(
            watcher_lines, watcher_output, "state=watch-ready", _WATCH_READY_TIMEOUT_SECONDS
        )

        changed_source = project / "app.py"
        expected_cycle = f"[{project.name}: 1 change(s)]"
        _write_watched_source(changed_source, revision=1)
        if not _watcher_emitted(
            watcher_lines,
            watcher_output,
            expected_cycle,
            _WATCH_NATIVE_REGISTRATION_RETRY_SECONDS,
        ):
            # watch-ready is emitted before watchfiles finishes native registration.
            # One retry, after a complete debounce interval, bounds that startup race.
            _write_watched_source(changed_source, revision=2)
            _wait_for_watcher_output(
                watcher_lines, watcher_output, expected_cycle, _WATCH_CYCLE_TIMEOUT_SECONDS
            )
    finally:
        _stop_watcher(watcher, watcher_reader, watcher_lines, watcher_output)

    assert watcher is not None
    assert watcher.returncode == 0, "".join(watcher_output)
    watcher_summary = "".join(watcher_output)
    assert "1 re-mine cycle(s), 1 event(s)" in watcher_summary, watcher_summary
    steps.append(
        StepResult(
            label="watch:on-save", returncode=watcher.returncode, stdout=watcher_summary, stderr=""
        )
    )

    # Publishable scenario summary: labels and booleans only — never absolute temp
    # paths, so this shape stays safe even if a future caller logs/publishes it.
    summary = [{"step": s.label, "ok": s.returncode == 0} for s in steps]
    summary_text = json.dumps(summary)
    assert str(tmp_path) not in summary_text
    assert all(s["ok"] for s in summary), f"a golden-scenario step failed: {summary}"

    _assert_no_repo_artifacts(ROOT)


# ── AC-2: important guard/failure paths ─────────────────────────────────────────


def test_cli_golden_failure_contracts(tmp_path, fake_pkg_root):
    """Invalid read range and a missing palace both exit non-zero with actionable stderr."""
    env = _make_env(tmp_path, fake_pkg_root)
    project = _write_fixture_project(tmp_path / "project")
    palace = tmp_path / "palace"

    init_step = _run_cli("init", ["init", str(project), "--skip-model-download"], env, tmp_path)
    _assert_ok(init_step, "Config saved:")
    mine_step = _run_cli("mine", ["--palace", str(palace), "mine", str(project)], env, tmp_path)
    _assert_ok(mine_step, "Drawers filed:")

    invalid_range_step = _run_cli(
        "read:invalid-range",
        ["--palace", str(palace), "read", "app.py", "--start", "10", "--end", "1"],
        env,
        tmp_path,
    )
    _assert_clean(invalid_range_step)
    assert invalid_range_step.returncode != 0, (
        f"invalid range must exit non-zero\nstdout={invalid_range_step.stdout!r}"
        f"\nstderr={invalid_range_step.stderr!r}"
    )
    assert "Invalid range:" in invalid_range_step.stderr
    assert "start (10) must be <= end (1)" in invalid_range_step.stderr
    assert "Next:" in invalid_range_step.stderr

    missing_palace = tmp_path / "does_not_exist"
    missing_palace_step = _run_cli(
        "read:missing-palace",
        ["--palace", str(missing_palace), "read", "app.py", "--start", "1", "--end", "1"],
        env,
        tmp_path,
    )
    _assert_clean(missing_palace_step)
    assert missing_palace_step.returncode != 0, (
        f"missing palace must exit non-zero\nstdout={missing_palace_step.stdout!r}"
        f"\nstderr={missing_palace_step.stderr!r}"
    )
    assert "No palace found at" in missing_palace_step.stderr
    assert "Next:" in missing_palace_step.stderr


def test_cli_non_regular_source_guard(tmp_path, fake_pkg_root):
    """Project and conversation mining skip same-extension non-regular sources."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available on this platform")

    env = _make_env(tmp_path, fake_pkg_root)
    project = _write_fixture_project(tmp_path / "project")
    palace_project = tmp_path / "palace_project"
    palace_convos = tmp_path / "palace_convos"

    blocked_project = project / "blocked.py"
    os.mkfifo(blocked_project)
    project_socket: socket.socket | None = None
    try:
        if hasattr(socket, "AF_UNIX"):
            project_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            project_socket.bind(str(project / "blocked_socket.py"))
    except OSError:
        if project_socket is not None:
            project_socket.close()
        project_socket = None

    try:
        init_step = _run_cli(
            "init:non-regular-source-guard",
            ["init", str(project), "--skip-model-download"],
            env,
            tmp_path,
        )
        _assert_ok(init_step, "Config saved:")

        mine_step = _run_cli(
            "mine:non-regular-source-guard",
            ["--palace", str(palace_project), "mine", str(project)],
            env,
            tmp_path,
        )
        _assert_ok(mine_step, "Drawers filed:")
        assert "app.py" in mine_step.stdout
        assert "blocked.py" not in mine_step.stdout
        assert str(blocked_project) in mine_step.stderr
        assert "not a regular file" in mine_step.stderr
    finally:
        if project_socket is not None:
            project_socket.close()

    convos = tmp_path / "convos"
    convos.mkdir()
    (convos / "chat.txt").write_text(
        "\n".join(
            [
                "> User asks about the non-regular source guard",
                "Assistant answers with enough regular transcript content for indexing.",
                "",
                "> User asks about reliability",
                "Assistant explains filesystem checks and bounded diagnostics.",
                "",
                "> User asks about regression coverage",
                "Assistant confirms the regular conversation file is mined.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    blocked_convo = convos / "blocked.txt"
    os.mkfifo(blocked_convo)

    convo_step = _run_cli(
        "mine-convos:non-regular-source-guard",
        [
            "--palace",
            str(palace_convos),
            "mine",
            str(convos),
            "--mode",
            "convos",
            "--wing",
            "convos",
            "--no-spellcheck",
        ],
        env,
        tmp_path,
    )
    _assert_ok(convo_step, "Drawers filed:")
    assert "chat.txt" in convo_step.stdout
    assert "blocked.txt" not in convo_step.stdout
    assert str(blocked_convo) in convo_step.stderr
    assert "not a regular file" in convo_step.stderr


# ── AC-3: forced-offline environment ────────────────────────────────────────────


def test_cli_golden_environment_is_forced_offline(tmp_path, fake_pkg_root):
    """Every subprocess env carries HOME/XDG isolation and offline/version-check flags.

    Source mode additionally proves the fake embedder root is on PYTHONPATH.
    Installed mode's console script ignores PYTHONPATH (``python -E`` shebang), so it
    instead proves the fake package root is absent from PYTHONPATH and that HF_HOME
    points at the required real, pre-cached model directory.
    """
    env = _make_env(tmp_path, fake_pkg_root)

    assert env["HOME"] == str(tmp_path / "home")
    assert env["USERPROFILE"] == str(tmp_path / "home")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "xdg_cache")
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "xdg_config")
    assert env["XDG_DATA_HOME"] == str(tmp_path / "xdg_data")
    assert env["MEMPALACE_VERSION_CHECK"] == "0"
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    if _INSTALLED_CLI:
        # python -E ignores PYTHONPATH in installed mode, so the fake package must
        # never be injected there; the real cached model comes from HF_HOME instead.
        assert str(fake_pkg_root) not in env.get("PYTHONPATH", "")
        assert env["HF_HOME"] == os.environ["MEMPALACE_TEST_HF_HOME"]
    else:
        assert str(fake_pkg_root) in env["PYTHONPATH"]

    palace = tmp_path / "palace"
    status_step = _run_cli("status", ["--palace", str(palace), "status"], env, tmp_path)
    # An empty/missing palace still exits 0 for status — the point here is proving
    # no version-check prompt or network marker appears, not workflow success.
    assert status_step.returncode == 0
    _assert_clean(status_step)


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
    """--version exits 0 with the package version string and no traceback."""
    env = _make_env(tmp_path, fake_pkg_root)
    step = _run_cli("version", ["--version"], env, tmp_path)
    _assert_clean(step)
    assert step.returncode == 0, (
        f"--version exited {step.returncode}\nstdout={step.stdout!r}\nstderr={step.stderr!r}"
    )
    # The version string must appear somewhere in the combined output.
    combined = step.stdout + step.stderr
    assert any(c.isdigit() for c in combined), (
        f"--version produced no numeric version string\nstdout={step.stdout!r}"
    )


def test_degraded_help_subcommand(tmp_path, fake_pkg_root):
    """'help' subcommand exits 0 and emits usage text."""
    env = _make_env(tmp_path, fake_pkg_root)
    step = _run_cli("help", ["help"], env, tmp_path)
    _assert_clean(step)
    assert step.returncode == 0, (
        f"help exited {step.returncode}\nstdout={step.stdout!r}\nstderr={step.stderr!r}"
    )
    assert "usage" in step.stdout.lower(), f"help did not emit usage text\nstdout={step.stdout!r}"


def test_degraded_palace_after_subcommand(tmp_path, fake_pkg_root):
    """--palace VALUE after the subcommand is equivalent to --palace VALUE before it."""
    env = _make_env(tmp_path, fake_pkg_root)
    palace = tmp_path / "palace"

    step_before = _run_cli(
        "status:palace-before",
        ["--palace", str(palace), "status"],
        env,
        tmp_path,
    )
    _assert_clean(step_before)
    assert step_before.returncode == 0, (
        f"--palace before subcommand failed\nstderr={step_before.stderr!r}"
    )

    step_after = _run_cli(
        "status:palace-after",
        ["status", "--palace", str(palace)],
        env,
        tmp_path,
    )
    _assert_clean(step_after)
    assert step_after.returncode == 0, (
        f"--palace after subcommand failed\nstderr={step_after.stderr!r}"
    )
    assert step_before.stdout == step_after.stdout, (
        "output differs between --palace before and after the subcommand"
    )


def test_degraded_search_results_below_one_rejected(tmp_path, fake_pkg_root):
    """search --results 0 and --results -1 are rejected at the CLI boundary without storage access."""
    env = _make_env(tmp_path, fake_pkg_root)
    palace = tmp_path / "no_palace_here"

    for bad_value in ("0", "-1"):
        step = _run_cli(
            f"search:results={bad_value}",
            ["--palace", str(palace), "search", "query", "--results", bad_value],
            env,
            tmp_path,
        )
        _assert_clean(step)
        assert step.returncode == 2, (
            f"search --results {bad_value} should exit 2, got {step.returncode}\n"
            f"stdout={step.stdout!r}\nstderr={step.stderr!r}"
        )
        combined = step.stderr + step.stdout
        assert "repair" not in combined.lower(), (
            f"search --results {bad_value} leaked repair guidance; should fail before storage access\n"
            f"stderr={step.stderr!r}"
        )
        assert not palace.exists(), (
            f"search --results {bad_value} created the palace directory before validation"
        )


def test_degraded_palace_conflicting_values(tmp_path, fake_pkg_root):
    """Conflicting --palace values exit 2 with an error mentioning both paths; no palace created."""
    env = _make_env(tmp_path, fake_pkg_root)
    palace_a = tmp_path / "palace_a"
    palace_b = tmp_path / "palace_b"

    step = _run_cli(
        "palace-conflict",
        ["--palace", str(palace_a), "status", "--palace", str(palace_b)],
        env,
        tmp_path,
    )
    _assert_clean(step)
    assert step.returncode == 2, (
        f"conflicting --palace should exit 2, got {step.returncode}\n"
        f"stdout={step.stdout!r}\nstderr={step.stderr!r}"
    )
    assert str(palace_a) in step.stderr, (
        f"first palace path not named in error\nstderr={step.stderr!r}"
    )
    assert str(palace_b) in step.stderr, (
        f"second palace path not named in error\nstderr={step.stderr!r}"
    )
    assert not palace_a.exists(), "palace_a must not be created on conflict"
    assert not palace_b.exists(), "palace_b must not be created on conflict"


def test_degraded_palace_identical_duplicate_accepted(tmp_path, fake_pkg_root):
    """Identical --palace value given twice (before and after subcommand) is accepted."""
    env = _make_env(tmp_path, fake_pkg_root)
    palace = tmp_path / "palace"

    step = _run_cli(
        "palace-duplicate-identical",
        ["--palace", str(palace), "status", "--palace", str(palace)],
        env,
        tmp_path,
    )
    _assert_clean(step)
    assert step.returncode == 0, (
        f"identical duplicate --palace should exit 0, got {step.returncode}\n"
        f"stdout={step.stdout!r}\nstderr={step.stderr!r}"
    )


def test_degraded_palace_option_token_as_value(tmp_path, fake_pkg_root):
    """--palace followed by another option token exits 2; the option is never used as a path."""
    env = _make_env(tmp_path, fake_pkg_root)
    summary_flag_palace = tmp_path / "--summary"

    step = _run_cli(
        "palace-option-token-as-value",
        ["status", "--palace", "--summary"],
        env,
        tmp_path,
    )
    _assert_clean(step)
    assert step.returncode == 2, (
        f"--palace --summary should exit 2, got {step.returncode}\n"
        f"stdout={step.stdout!r}\nstderr={step.stderr!r}"
    )
    assert not summary_flag_palace.exists(), (
        "--summary must not be treated as a palace path and must not be created"
    )


def test_degraded_import_missing_file(tmp_path, fake_pkg_root):
    """import of a nonexistent file exits without traceback and names the path + one recovery action."""
    env = _make_env(tmp_path, fake_pkg_root)
    missing = tmp_path / "not_here.jsonl"
    palace = tmp_path / "palace"

    step = _run_cli(
        "import:missing-file",
        ["--palace", str(palace), "import", str(missing)],
        env,
        tmp_path,
    )
    _assert_clean(step)
    assert step.returncode != 0, (
        f"import with missing file should exit non-zero, got 0\nstdout={step.stdout!r}"
    )
    assert str(missing) in step.stderr, f"missing file path not mentioned\nstderr={step.stderr!r}"
    assert "Next:" in step.stderr or "export" in step.stderr.lower(), (
        f"no recovery action mentioned\nstderr={step.stderr!r}"
    )
    assert not palace.exists(), "import with missing file must not create the palace directory"
