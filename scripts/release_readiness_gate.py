#!/usr/bin/env python3
"""release_readiness_gate.py — Orchestrate the complete release-readiness check.

One command that runs the canonical gate inventory, builds artifacts in a
controlled output directory, runs twine check and artifact member inspection,
then installs the candidate wheel in a disposable environment and exits nonzero
on any failed row.

Usage:
    python scripts/release_readiness_gate.py --check --candidate-sha <sha> --json
    python scripts/release_readiness_gate.py --artifact-only --json
    python scripts/release_readiness_gate.py --check --candidate-sha <sha>
"""

from __future__ import annotations

import argparse
import email
import hashlib
import importlib.util
import json
import os
import queue
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import threading
import time
import zipfile
from pathlib import Path

PACKAGE_NAME = "mempalace-code"
DEFAULT_TIMEOUT = 120
DEFAULT_REPO = "rergards/mempalace-code"
DEFAULT_REMOTE = "publish"
DEFAULT_BRANCH = "main"
MODEL_CACHE_RELATIVE = Path("hub/models--sentence-transformers--all-MiniLM-L6-v2")
MODEL_CACHE_REQUIRED_FILES = (
    Path("config.json"),
    Path("modules.json"),
    Path("sentence_bert_config.json"),
    Path("tokenizer.json"),
    Path("tokenizer_config.json"),
    Path("1_Pooling/config.json"),
)
MODEL_CACHE_WEIGHT_FILES = (Path("model.safetensors"), Path("pytorch_model.bin"))
INSTALLED_GOLDEN_COMMAND = (
    'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
)
INSTALLED_CLI_INVENTORY_PROBE_NAME = "installed-cli-inventory-probe.py"
INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT = 64 * 1024
INSTALLED_CLI_INVENTORY_MEMBER_LIMIT = 128
INSTALLED_CLI_INVENTORY_DEPTH_LIMIT = 8
INSTALLED_CLI_INVENTORY_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,63}")
INSTALLED_CLI_TRACE_COMMAND_LIMIT = 512
INSTALLED_CLI_TRACE_TOKEN_LIMIT = 128
INSTALLED_CLI_TRACE_TOKEN_BYTES_LIMIT = 4096
INSTALLED_CLI_TRACE_BYTES_LIMIT = 256 * 1024
INSTALLED_CLI_INVENTORY_PROBE = r"""import argparse
import contextlib
import io
import json
import sys


class ParserCaptured(Exception):
    pass


captured = []
original_parse_args = argparse.ArgumentParser.parse_args
probe_argv = sys.argv[1:]


def capture_parser(parser, args=None, namespace=None):
    captured.append(parser)
    raise ParserCaptured


argparse.ArgumentParser.parse_args = capture_parser
try:
    from mempalace_code import cli

    sys.argv = ["mempalace-code"]
    try:
        cli.main()
    except ParserCaptured:
        pass
finally:
    argparse.ArgumentParser.parse_args = original_parse_args

if len(captured) != 1:
    raise SystemExit("parser capture failed")

members = []
active = set()
selectors = {}


def walk(parser, prefix, inherited_selectors):
    identity = id(parser)
    if identity in active:
        raise SystemExit("cyclic parser tree")
    active.add(identity)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                path = [*prefix, name]
                members.append(path)
                member_selectors = [*inherited_selectors, [action.dest, name]]
                selectors[tuple(path)] = member_selectors
                walk(child, path, member_selectors)
    active.remove(identity)


walk(captured[0], [], [])

if not probe_argv:
    payload = {"members": members}
elif len(probe_argv) == 1:
    with open(probe_argv[0], encoding="utf-8") as trace_file:
        trace = json.load(trace_file)
    if not isinstance(trace, list):
        raise SystemExit("invalid execution trace")
    executed = set()
    for raw_argv in trace:
        if not isinstance(raw_argv, list) or any(not isinstance(token, str) for token in raw_argv):
            raise SystemExit("invalid execution argv")
        try:
            normalized = cli._hoist_palace_before_subcommand(list(raw_argv))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                namespace = original_parse_args(captured[0], normalized)
        except SystemExit:
            continue
        selected = ()
        for member in members:
            path = tuple(member)
            if all(getattr(namespace, dest, None) == name for dest, name in selectors[path]):
                if len(path) > len(selected):
                    selected = path
        if selected:
            executed.add(selected)
    payload = {"executed": [member for member in members if tuple(member) in executed]}
else:
    raise SystemExit("unexpected probe arguments")

print(json.dumps(payload, separators=(",", ":")))
"""
INSTALLED_MCP_INVENTORY_PROBE_NAME = "installed-mcp-inventory-probe.py"
INSTALLED_MCP_OUTPUT_LIMIT = 512 * 1024
INSTALLED_MCP_LINE_LIMIT = 128 * 1024
INSTALLED_MCP_REQUEST_LIMIT = 96
INSTALLED_MCP_PROFILE_LIMIT = 8
INSTALLED_MCP_TOOL_LIMIT = 64
INSTALLED_MCP_TIMEOUT = 120
INSTALLED_MCP_INVENTORY_PROBE = r"""import json
from pathlib import Path

from mempalace_code.mcp import registry
from mempalace_code import mcp_tool_profiles

tool_names = list(registry.TOOLS)
profiles = []
for profile_name, selected in mcp_tool_profiles.PROFILES.items():
    active = set(tool_names) if profile_name == "full" else set(selected)
    profiles.append(
        {"name": profile_name, "members": [name for name in tool_names if name in active]}
    )

print(
    json.dumps(
        {
            "registry_module": str(Path(registry.__file__).resolve()),
            "profiles_module": str(Path(mcp_tool_profiles.__file__).resolve()),
            "tools": tool_names,
            "profiles": profiles,
        },
        separators=(",", ":"),
    )
)
"""
INSTALLED_EXPORT_OUTPUT_LIMIT = 32 * 1024
INSTALLED_EXPORT_OWNER_LIMIT = 3
INSTALLED_EXPORT_MEMBER_LIMIT = 16
INSTALLED_EXPORT_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
INSTALLED_EXPORT_PROBE = r"""import importlib
import json
from pathlib import Path

root = importlib.import_module("mempalace_code")
cli = importlib.import_module("mempalace_code.cli")
mcp = importlib.import_module("mempalace_code.mcp")
dispatch = importlib.import_module("mempalace_code.mcp.dispatch")
registry = importlib.import_module("mempalace_code.mcp.registry")
owners = []
for name, module in (("mempalace_code", root), ("mempalace_code.cli", cli), ("mempalace_code.mcp", mcp)):
    owners.append(
        {"owner": name, "file": str(Path(module.__file__).resolve()), "exports": module.__all__}
    )
print(json.dumps({
    "owners": owners,
    "bindings": {
        "root_main_is_one_shot_main": root.main is cli._one_shot_main,
        "mcp_tools_is_registry_tools": mcp.TOOLS is registry.TOOLS,
        "mcp_handle_request_is_dispatch": mcp.handle_request is dispatch.handle_request,
        "mcp_main_is_dispatch": mcp.main is dispatch.main,
    },
}, separators=(",", ":")))
"""
INSTALLED_SPELLCHECK_PROBE = r"""import json
import sys
from importlib.util import find_spec
from mempalace_code.normalize import normalize

output = normalize(sys.argv[1], spellcheck=True)
print(json.dumps({"autocorrect": find_spec("autocorrect") is not None, "output": output}))
"""
INSTALLED_TREESITTER_PROBE = r"""import json
from mempalace_code.mining.chunkers import chunk_file
from mempalace_code.treesitter import get_parser

fixtures = {
    "python": (".py", "def alpha():\n" + "    value = 1\n" * 120 + "\n\ndef beta():\n" + "    value = 2\n" * 120, "def beta"),
    "typescript": (".ts", "function alpha() {\n  let value = 0;\n" + "  value += 1;\n" * 120 + "}\n\nfunction beta() {\n  let value = 0;\n" + "  value += 2;\n" * 120 + "}\n", "function beta"),
    "go": (".go", "package main\n\nfunc alpha() {\n  value := 0\n" + "  value += 1\n" * 120 + "}\n\nfunc beta() {\n  value := 0\n" + "  value += 2\n" * 120 + "}\n", "func beta"),
    "rust": (".rs", "fn alpha() {\n  let mut value = 0;\n" + "  value += 1;\n" * 120 + "}\n\nfn beta() {\n  let mut value = 0;\n" + "  value += 2;\n" * 120 + "}\n", "fn beta"),
}
results = {}
for language, (ext, content, beta_declaration) in fixtures.items():
    parser = get_parser(language)
    chunks = chunk_file(content, ext, "fixture" + ext, language)
    beta_start = content.index(beta_declaration)
    expected_chunks = (content[:beta_start].rstrip(), content[beta_start:].rstrip())
    cursor = 0
    evidence = []
    for index, chunk in enumerate(chunks):
        chunk_content = chunk.get("content", "")
        start = content.find(chunk_content, cursor)
        end = start + len(chunk_content) if start >= 0 else -1
        cursor = max(cursor, end)
        marker = "alpha" if "alpha" in chunk_content else "beta" if "beta" in chunk_content else ""
        evidence.append({
            "strategy": chunk.get("chunker_strategy"),
            "start": start,
            "end": end,
            "marker": marker,
            "exact": index < len(expected_chunks) and chunk_content == expected_chunks[index],
        })
    results[language] = {
        "parser": parser is not None,
        "grammar": parser is not None and not parser.parse(content.encode("utf-8")).root_node.has_error,
        "chunks": evidence,
    }
print(json.dumps(results, separators=(",", ":")))
"""
INSTALLED_MIGRATION_PROBE = r"""import importlib.util
import importlib.metadata
import json
import re
import subprocess
import sys
from mempalace_code.storage import CHROMA_RUNTIME_RETIRED_MESSAGE

result = subprocess.run(
    [sys.executable, "-m", "mempalace_code.cli", "migrate-storage"],
    capture_output=True, text=True, check=False,
)
dependencies = sorted({
    re.split(r"[ <>=!~\[(;]", raw, maxsplit=1)[0].lower()
    for raw in (importlib.metadata.requires("mempalace-code") or [])
})
print("MEMPALACE-MIGRATION-EVIDENCE=" + json.dumps({
    "returncode": result.returncode,
    "stderr_exact": result.stderr == "Error: " + CHROMA_RUNTIME_RETIRED_MESSAGE + "\n",
    "bridge_modules_absent": all(
        importlib.util.find_spec(name) is None
        for name in ("mempalace_code.migrate", "mempalace_code._chroma_store")
    ),
    "chromadb_dependency_absent": "chromadb" not in dependencies,
}, separators=(",", ":")))
"""
INSTALLED_MIGRATION_EVIDENCE_MARKER = "MEMPALACE-MIGRATION-EVIDENCE="
INSTALLED_PUBLIC_EXPORTS = {
    "mempalace_code": ("main", "__version__"),
    "mempalace_code.cli": ("main", "main_alias", "install_legacy_alias", "fetch_model"),
    "mempalace_code.mcp": ("TOOLS", "handle_request", "main"),
}
INSTALLED_FETCH_MODEL_COMMAND = "mempalace-code fetch-model --model <model> [--force]"
INSTALLED_CONVO_FULL_REPLACE_COMMAND = (
    "mempalace-code --palace <palace> mine <conversations> --mode convos "
    "--wing conversations [--full]"
)
INSTALLED_SPLIT_COMMAND = "mempalace-code split <source-dir> --output-dir <output-dir>"
INSTALLED_IMPORT_MISSING_COMMAND = "mempalace-code --palace <palace> import <missing.jsonl>"
INSTALLED_PALACE_ARGUMENT_COMMAND = "mempalace-code [--palace <path>] status [--palace <path>]"
INSTALLED_SEARCH_RESULTS_COMMAND = "mempalace-code search <query> --results <count>"
INSTALLED_VERSION_COMMAND = "mempalace-code --version"
INSTALLED_RECOVERY_SAFETY_COMMAND = (
    "mempalace-code import --dry-run/backup/restore collision/--version"
)
INSTALLED_READ_FAILURES_COMMAND = (
    "mempalace-code --palace <palace> read app.py --start <start> --end <end>"
)
INSTALLED_DIARY_BLANK_REQUIRED_FIELDS_COMMAND = (
    "mempalace-code --palace <palace> diary write --agent <agent> --entry <entry> --topic ''"
)
INSTALLED_CLEANUP_POSTSTATE_COMMAND = "mempalace-code --palace <palace> cleanup --json"
INSTALLED_ROLLBACK_NO_CANDIDATE_COMMAND = (
    "mempalace-code --palace <palace> repair --rollback [--dry-run]"
)
INSTALLED_WATCHER_SIGNALS_COMMAND = (
    "mempalace-code --palace <palace> watch <project> --on-save; send SIGTERM [and SIGHUP]"
)
INSTALLED_COMPRESS_RETRY_COMMAND = (
    "mempalace-code --palace <palace> compress --wing <wing> [--dry-run]"
)
INSTALLED_ALIAS_TARGET_CONTAINMENT_COMMAND = (
    "mempalace-code install-alias --target-dir <target-dir>"
)
INSTALLED_SCHEDULE_SNIPPETS_COMMAND = (
    "mempalace-code --palace <palace> backup schedule --freq daily; "
    "mempalace-code watch <root> schedule; retry each with --install"
)
INSTALLED_PATH_CONTRACT_COMMAND = (
    "mempalace-code init/mine-all --dry-run/diary write/search; "
    "update apply/scheduler install/scheduler remove without --yes"
)
INSTALLED_WORKFLOW_HAPPY_PATH_COMMAND = (
    "mempalace-code init/mine/compress/status/search/read/export/import/backup/restore/health/watch"
)
INSTALLED_NON_REGULAR_SOURCE_COMMAND = (
    "mempalace-code init/mine/search/mine-all/watch and conversation mine with non-regular sources"
)
INSTALLED_GOLDEN_TIMEOUT = 900
INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT = 4000
INSTALLED_DIARY_BLANK_REQUIRED_FIELDS_CASES = (
    ("--agent", "", "--entry", "valid entry"),
    ("--agent", "   ", "--entry", "valid entry"),
    ("--entry", "", "--agent", "valid-agent"),
    ("--entry", "   ", "--agent", "valid-agent"),
)
INSTALLED_GOLDEN_FORBIDDEN_OUTPUT = (
    "Traceback (most recent call last)",
    "Enable periodic new-version checks",
    "New version available",
    "The token has not been saved",
    "hf.co/settings/tokens",
    "fake buffered stdout noise",
    "fake buffered stderr noise",
    "fake fd stdout noise",
    "fake fd stderr noise",
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

_ADMISSION_CHECKS_MODULE = None
_PUBLIC_READ_MODULE = None
_SANITIZER_MODULE = None
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_DETAIL_LIMIT = 2000


def _write_fixture_project(root: Path) -> Path:
    """Write the shared four-file project used by source and installed golden scenarios."""
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


# ── Loader helpers ─────────────────────────────────────────────────────────────


def _load_sibling(name: str, script_name: str):
    path = Path(__file__).resolve().parent / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_admission_checks():
    global _ADMISSION_CHECKS_MODULE
    if _ADMISSION_CHECKS_MODULE is None:
        _ADMISSION_CHECKS_MODULE = _load_sibling(
            "release_admission_checks", "release_admission_checks.py"
        )
    return _ADMISSION_CHECKS_MODULE


def _load_public_read():
    global _PUBLIC_READ_MODULE
    if _PUBLIC_READ_MODULE is None:
        _PUBLIC_READ_MODULE = _load_sibling("release_public_read", "release_public_read.py")
    return _PUBLIC_READ_MODULE


# ── Gate row ──────────────────────────────────────────────────────────────────


def _make_row(gate_id: str, command: str, status: str, detail: str) -> dict:
    global _SANITIZER_MODULE
    if _SANITIZER_MODULE is None:
        _SANITIZER_MODULE = _load_sibling(
            "_release_readiness_sanitizer", "release_install_metadata_smoke.py"
        )
    safe_detail = _SANITIZER_MODULE.sanitize(
        detail,
        local_paths=(Path.home(), tempfile.gettempdir()),
    )
    return {
        "id": gate_id,
        "command": command,
        "status": status,
        "detail": " ".join(safe_detail.split())[:_DETAIL_LIMIT],
    }


def _admission_row_to_gate_row(row, command: str) -> dict:
    status = "pass" if row.status == "ok" else row.status
    result = _make_row(row.name, command, status, row.detail)
    if row.remediation:
        result["remediation"] = row.remediation
    return result


def _run_public_admission_checks(
    *,
    version: str,
    repo: str,
    branch: str,
    package: str,
    candidate_sha: str | None,
    required_check_name: str,
    audit_max_age_hours: int,
    public_read,
) -> list[dict]:
    admission = _load_admission_checks()
    rows = [
        _admission_row_to_gate_row(
            admission.check_aggregate_required_check(
                candidate_sha,
                repo,
                public_read,
                check_name=required_check_name,
            ),
            "public GET check-runs",
        )
    ]
    rows.append(
        _admission_row_to_gate_row(
            admission.check_main_branch_rules(
                repo,
                branch,
                public_read,
                check_name=required_check_name,
            ),
            "public GET branch rules",
        )
    )
    rows.append(
        _admission_row_to_gate_row(
            admission.check_tag_ruleset(repo, public_read),
            "public GET rulesets",
        )
    )
    rows.append(
        _admission_row_to_gate_row(
            admission.check_public_orphan_tags(
                version,
                repo,
                package,
                public_read,
                # Pre-publication: v{version} does not exist publicly yet, so its
                # absence is the expected state rather than an orphan finding.
                require_expected_tag=False,
            ),
            "public GET matching refs",
        )
    )
    rows.append(
        _admission_row_to_gate_row(
            admission.check_dependency_audit_freshness(
                repo,
                public_read,
                max_age_hours=audit_max_age_hours,
            ),
            "public GET workflow runs",
        )
    )
    return rows


# ── Inventory check ───────────────────────────────────────────────────────────


def _run_inventory_check(root: Path) -> list[dict]:
    gate_inventory = _load_sibling("_gate_inventory_readiness", "gate_inventory.py")
    errors = gate_inventory.check_parity(root)
    if errors:
        return [
            _make_row(
                "gate_inventory",
                "python scripts/gate_inventory.py --check",
                "fail",
                "; ".join(errors[:5]),
            )
        ]
    return [
        _make_row(
            "gate_inventory",
            "python scripts/gate_inventory.py --check",
            "pass",
            f"{len(gate_inventory.CANONICAL_GATES)} gates, parity ok",
        )
    ]


# ── Artifact build ────────────────────────────────────────────────────────────


def _build_artifacts(
    root: Path, out_dir: Path, *, env: dict[str, str] | None = None
) -> tuple[bool, str]:
    """Build wheel and sdist into out_dir. Returns (ok, detail)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(out_dir), str(root)],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            cwd=str(root),
            env=env,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout)[:500]
        return True, f"built to {out_dir}"
    except FileNotFoundError:
        return False, "build tool not installed (pip install build)"
    except subprocess.TimeoutExpired:
        return False, "build timed out"


# ── Artifact inspection ───────────────────────────────────────────────────────


def _run_artifact_inspection(dist_dir: Path) -> list[dict]:
    rag = _load_sibling("_release_artifact_gate_readiness", "release_artifact_gate.py")
    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=True)
    rows = []
    for row in result["rows"]:
        rows.append(
            _make_row(
                f"artifact_{row['check'].replace('-', '_')}",
                f"artifact-gate:{row['check']}",
                row["status"],
                row["detail"],
            )
        )
    return rows


def _run_installed_application(dist_dir: Path) -> list[dict]:
    """Install the exact wheel and exercise its credential-free public surfaces."""
    wheels = sorted(dist_dir.glob("*.whl"))
    command = (
        "python scripts/release_install_metadata_smoke.py "
        "--all-installers --install-spec <wheel> --json"
    )
    if len(wheels) != 1:
        return [
            _make_row(
                "installed_application",
                command,
                "fail",
                f"expected one candidate wheel, found {len(wheels)}",
            )
        ]
    smoke = _load_sibling(
        "_release_install_metadata_readiness", "release_install_metadata_smoke.py"
    )
    result = smoke.run_all_installers_smoke(
        str(wheels[0]), PACKAGE_NAME, smoke._default_run_subprocess
    )
    rows = [
        _make_row(
            f"installed_{installer_result.installer.replace('-', '_')}_{surface.name.replace('-', '_')}",
            command,
            "pass" if surface.status == smoke.STATUS_OK else surface.status,
            surface.detail,
        )
        for installer_result in result.results
        for surface in installer_result.surfaces
    ]
    if not result.ok:
        detail = "; ".join(result.diagnostics) or "aggregate installed smoke failed"
        rows.append(_make_row("installed_application", command, "fail", detail))
    elif not rows:
        rows.append(_make_row("installed_application", command, "fail", "no smoke surfaces"))
    return rows


def _cache_recovery() -> str:
    return 'HF_HOME="$MEMPALACE_TEST_HF_HOME" mempalace-code fetch-model'


def _validated_model_cache(env: dict[str, str]) -> tuple[Path | None, str]:
    """Return a usable MiniLM HF_HOME before any candidate environment is created."""
    configured = env.get("MEMPALACE_TEST_HF_HOME", "").strip()
    if not configured:
        return None, ("MEMPALACE_TEST_HF_HOME is required; provision it with " + _cache_recovery())
    hf_home = Path(configured).expanduser()
    model_root = hf_home / MODEL_CACHE_RELATIVE
    refs_main = model_root / "refs" / "main"
    try:
        revision = refs_main.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        revision = ""
    snapshots_root = model_root / "snapshots"
    snapshot = snapshots_root / revision
    try:
        resolved_model_root = model_root.resolve()
        required_files = tuple(snapshot / relative for relative in MODEL_CACHE_REQUIRED_FILES)
        weight_files = tuple(snapshot / relative for relative in MODEL_CACHE_WEIGHT_FILES)
        populated = (
            bool(re.fullmatch(r"[A-Za-z0-9._-]+", revision))
            and revision not in (".", "..")
            and snapshot.is_dir()
            and snapshot.resolve().is_relative_to(snapshots_root.resolve())
            and all(
                path.is_file() and path.resolve().is_relative_to(resolved_model_root)
                for path in required_files
            )
            and any(
                path.is_file() and path.resolve().is_relative_to(resolved_model_root)
                for path in weight_files
            )
        )
    except OSError:
        populated = False
    if not revision or not populated:
        return None, (
            "MiniLM cache is missing, empty, or stale; provision it with " + _cache_recovery()
        )
    return hf_home.resolve(), f"validated MiniLM revision {revision[:12]}"


def _run_golden_subprocess(run_subprocess, command: list[str], **kwargs):
    """Convert subprocess launch and timeout failures into ordinary fail-closed results."""
    try:
        return run_subprocess(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=exc.stdout or "",
            stderr=f"subprocess timed out after {exc.timeout}s",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            command, 127, stdout="", stderr=f"subprocess failed: {exc}"
        )


def _run_installed_cli(
    run_subprocess,
    command_prefix: list[str],
    args: list[str],
    env: dict[str, str],
    cwd: Path,
    *,
    merge_stderr: bool = False,
    input_text: str | None = None,
):
    output_options = (
        {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
        if merge_stderr
        else {"capture_output": True}
    )
    input_option = {"input": input_text} if input_text is not None else {}
    return _run_golden_subprocess(
        run_subprocess,
        [*command_prefix, *args],
        **output_options,
        **input_option,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=DEFAULT_TIMEOUT,
    )


def _installed_output_is_clean(result) -> bool:
    output = (result.stdout or "") + (result.stderr or "")
    return not any(marker in output for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT)


def _stable_file_digest(path: Path) -> tuple[int, str]:
    """Hash one file without accepting a concurrent same-path mutation."""
    for _attempt in range(2):
        before = path.lstat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.lstat()
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before == identity_after and stat.S_ISREG(after.st_mode):
            return after.st_size, digest.hexdigest()
    raise OSError("tree entry changed while content was being hashed")


def _semantic_tree_snapshot(path: Path) -> tuple[tuple[str, str, int, str], ...]:
    """Capture path kind, file content, and literal symlink targets without traversal."""
    rows: list[tuple[str, str, int, str]] = []

    def visit(current: Path, relative: Path) -> None:
        current_stat = current.lstat()
        name = relative.as_posix() if relative.parts else "."
        if stat.S_ISLNK(current_stat.st_mode):
            rows.append((name, "symlink", current_stat.st_size, os.readlink(current)))
            return
        if stat.S_ISREG(current_stat.st_mode):
            size, digest = _stable_file_digest(current)
            rows.append((name, "file", size, digest))
            return
        if not stat.S_ISDIR(current_stat.st_mode):
            raise OSError(f"unsupported tree entry kind at {name}")

        rows.append((name, "dir", 0, ""))
        before_names = sorted(entry.name for entry in os.scandir(current))
        for child_name in before_names:
            visit(current / child_name, relative / child_name)
        after_names = sorted(entry.name for entry in os.scandir(current))
        if before_names != after_names:
            raise OSError(f"tree entries changed while snapshotting {name}")

    visit(path, Path())
    return tuple(rows)


def _installed_disposable_roots(
    env: dict[str, str], scenario_root: Path, neutral_cwd: Path
) -> tuple[Path, ...]:
    """Collect the complete deduplicated installed-scenario mutation boundary."""
    required_roots = [scenario_root, neutral_cwd]
    for name in (
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        value = env.get(name)
        if not value:
            raise ValueError(f"installed environment is missing {name}")
        root = Path(value)
        if not root.is_absolute():
            raise ValueError(f"installed environment has non-absolute {name}")
        required_roots.append(root)
    return tuple(dict.fromkeys(required_roots))


def _run_installed_recovery_safety_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    network_attempts: Path | None = None,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove recovery refusals and dry runs preserve state through one console."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
        return _make_row(
            "installed_golden_recovery_safety",
            INSTALLED_RECOVERY_SAFETY_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    def run(args: list[str]):
        result = _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            env,
            neutral_cwd,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not _installed_output_is_clean(result):
            raise RuntimeError("forbidden subprocess output detected")
        if len(output) > INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT:
            raise RuntimeError("subprocess output exceeded the bounded evidence limit")
        return result

    def dry_run_counts(result) -> tuple[int, int, int]:
        if result.returncode != 0:
            raise RuntimeError("import dry-run returned a nonzero status")
        matches = []
        for label in ("Imported drawers", "Skipped duplicates", "Imported KG triples"):
            match = re.search(rf"^\s*{re.escape(label)}:\s*(\d+)\s*$", result.stdout or "", re.M)
            if match is None:
                raise RuntimeError("import dry-run omitted deterministic counts")
            matches.append(int(match.group(1)))
        return tuple(matches)  # type: ignore[return-value]

    if not command_prefix or not Path(command_prefix[0]).is_absolute():
        return failure("recovery scenario requires an absolute invoked launcher")

    try:
        disposable_roots = _installed_disposable_roots(env, scenario_root, neutral_cwd)
        repository_before = _semantic_tree_snapshot(repository_root)
        attempts_before = (
            network_attempts.read_bytes()
            if network_attempts is not None and network_attempts.exists()
            else b""
        )
        if attempts_before:
            raise RuntimeError("recovery scenario inherited a network attempt")

        scenario_root.mkdir(parents=True, exist_ok=True)
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        palace = scenario_root / "absent-palace"
        import_file = scenario_root / "import.jsonl"
        import_file.write_text(
            "\n".join(
                [
                    json.dumps({"type": "export_header"}),
                    json.dumps(
                        {
                            "type": "drawer",
                            "id": "dry-run-drawer",
                            "text": "recovery dry run content",
                            "wing": "release",
                            "room": "acceptance",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "kg_triple",
                            "subject": "Recovery",
                            "predicate": "preserves",
                            "object": "absent state",
                        }
                    ),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        malformed_file = scenario_root / "malformed.jsonl"
        malformed_file.write_text('{"type": "drawer"\n', encoding="utf-8")
        baseline = {root: _semantic_tree_snapshot(root) for root in disposable_roots}

        observed_counts = []
        for _attempt in range(2):
            dry_run = run(["--palace", str(palace), "import", str(import_file), "--dry-run"])
            observed_counts.append(dry_run_counts(dry_run))
            if (
                any(
                    _semantic_tree_snapshot(root) != snapshot for root, snapshot in baseline.items()
                )
                or palace.exists()
            ):
                raise RuntimeError("import dry-run changed absent-palace state")
        if observed_counts != [(1, 0, 1), (1, 0, 1)]:
            raise RuntimeError("import dry-run counts were wrong or nondeterministic")

        malformed = run(["--palace", str(palace), "import", str(malformed_file), "--dry-run"])
        if malformed.returncode == 0 or "malformed JSONL input" not in (malformed.stderr or ""):
            raise RuntimeError("malformed import did not return bounded recovery guidance")
        if (
            any(_semantic_tree_snapshot(root) != snapshot for root, snapshot in baseline.items())
            or palace.exists()
        ):
            raise RuntimeError("malformed import changed absent-palace state")

        missing_value = run(["status", "--palace", "--summary"])
        if missing_value.returncode != 2 or "argument --palace: expected one argument" not in (
            missing_value.stderr or ""
        ):
            raise RuntimeError("missing --palace value did not return bounded argument guidance")
        if (neutral_cwd / "--summary").exists():
            raise RuntimeError("missing --palace value created an accidental --summary path")
        if (
            any(_semantic_tree_snapshot(root) != snapshot for root, snapshot in baseline.items())
            or palace.exists()
        ):
            raise RuntimeError("missing --palace value changed absent-palace state")

        source_palace = scenario_root / "backup-source"
        backup_archive = scenario_root / "candidate-backup.tar.gz"
        backup = run(["--palace", str(source_palace), "backup", "--out", str(backup_archive)])
        if (
            backup.returncode != 0
            or "Backed up" not in (backup.stdout or "")
            or "Archive:" not in (backup.stdout or "")
            or not backup_archive.is_file()
        ):
            raise RuntimeError("backup setup did not produce the recovery archive")

        restore_target = scenario_root / "restore-target"
        restore_target.mkdir()
        sentinel = restore_target / "operator-state.txt"
        sentinel.write_text("preserve me", encoding="utf-8")
        archive_before = backup_archive.read_bytes()
        post_setup = {root: _semantic_tree_snapshot(root) for root in disposable_roots}
        restore = run(["--palace", str(restore_target), "restore", str(backup_archive)])
        restore_stderr = restore.stderr or ""
        if (
            restore.returncode == 0
            or "Restore destination already contains state" not in restore_stderr
            or "back up the reported destination state" not in restore_stderr
            or "--force" not in restore_stderr
        ):
            raise RuntimeError("restore collision did not return bounded recovery guidance")
        if sentinel.read_text(encoding="utf-8") != "preserve me":
            raise RuntimeError("restore collision changed the operator sentinel")
        if tuple(sorted(entry.name for entry in restore_target.iterdir())) != (sentinel.name,):
            raise RuntimeError("restore collision added destination state")
        if backup_archive.read_bytes() != archive_before:
            raise RuntimeError("restore collision changed the backup archive")
        if any(_semantic_tree_snapshot(root) != snapshot for root, snapshot in post_setup.items()):
            raise RuntimeError("restore collision changed the disposable root boundary")

        version = run(["--version"])
        if version.returncode != 0 or not any(
            character.isdigit() for character in (version.stdout or "") + (version.stderr or "")
        ):
            raise RuntimeError("installed launcher did not recover after restore refusal")
        if any(_semantic_tree_snapshot(root) != snapshot for root, snapshot in post_setup.items()):
            raise RuntimeError("launcher recovery changed the disposable root boundary")

        attempts_after = (
            network_attempts.read_bytes()
            if network_attempts is not None and network_attempts.exists()
            else b""
        )
        if attempts_after != attempts_before:
            raise RuntimeError("recovery scenario attempted network access")
        if _semantic_tree_snapshot(repository_root) != repository_before:
            raise RuntimeError("recovery scenario changed repository state")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        return failure(f"recovery evidence could not be evaluated: {reason}")

    return _make_row(
        "installed_golden_recovery_safety",
        INSTALLED_RECOVERY_SAFETY_COMMAND,
        "pass",
        "two deterministic dry runs and hostile recovery refusals preserved exact state",
    )


def _run_installed_path_contract_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    network_attempts: Path | None = None,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove init, discovery, diary recovery, and update refusals through one console."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
        return _make_row(
            "installed_golden_path_contracts",
            INSTALLED_PATH_CONTRACT_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    def run(args: list[str]):
        result = _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            env,
            neutral_cwd,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not _installed_output_is_clean(result):
            raise RuntimeError("forbidden subprocess output detected")
        if len(output) > INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT:
            raise RuntimeError("subprocess output exceeded the bounded evidence limit")
        return result

    def require_ok(result, label: str, *markers: str) -> str:
        stdout = result.stdout or ""
        if result.returncode != 0 or any(marker not in stdout for marker in markers):
            raise RuntimeError(f"{label} failed its output contract")
        return stdout

    if not command_prefix or not Path(command_prefix[0]).is_absolute():
        return failure("path-contract scenario requires an absolute invoked launcher")

    try:
        distinct_roots = _installed_disposable_roots(env, scenario_root, neutral_cwd)
        repository_before = _semantic_tree_snapshot(repository_root)
        attempts_before = (
            network_attempts.read_bytes()
            if network_attempts is not None and network_attempts.exists()
            else b""
        )
        scenario_root.mkdir(parents=True, exist_ok=True)
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        parent = scenario_root / "projects"
        project = _write_fixture_project(parent / "initialized-only")
        palace = scenario_root / "palace"

        project_before_init = _semantic_tree_snapshot(project)
        init = run(["init", str(project), "--skip-model-download"])
        require_ok(init, "init", "Config saved:")
        config = project / "mempalace.yaml"
        expected_after_init = tuple(
            sorted(
                (
                    *project_before_init,
                    (
                        "mempalace.yaml",
                        "file",
                        config.stat().st_size,
                        _stable_file_digest(config)[1],
                    ),
                )
            )
        )
        if _semantic_tree_snapshot(project) != expected_after_init:
            raise RuntimeError("init created an implicit or unexpected project artifact")
        if (project / ".git").exists() or (project / "pyproject.toml").exists():
            raise RuntimeError("init created an implicit project owner")

        before_mine_all = _semantic_tree_snapshot(scenario_root)
        mine_all = run(["--palace", str(palace), "mine-all", str(parent), "--dry-run"])
        require_ok(mine_all, "mine-all dry-run", "initialized-only", "Dry run")
        if _semantic_tree_snapshot(scenario_root) != before_mine_all or palace.exists():
            raise RuntimeError("mine-all dry-run changed scenario state")

        diary_entry = (
            "reconcilable diary poststate with a deliberately long body that must never be "
            "echoed in full by the mutation acknowledgement"
        )
        diary = run(
            [
                "--palace",
                str(palace),
                "diary",
                "write",
                "--agent",
                "contract-agent",
                "--entry",
                diary_entry,
                "--topic",
                "release-contract",
            ]
        )
        diary_stdout = require_ok(
            diary,
            "diary write",
            "Diary entry stored.",
            "ID: diary_wing_contract-agent_",
            "Wing: wing_contract-agent",
            "Room: diary",
            "Topic: release-contract",
            "Verify before retry:",
        )
        if diary.stderr or diary_entry in diary_stdout:
            raise RuntimeError("diary acknowledgement was unbounded or used stderr")

        after_diary = _semantic_tree_snapshot(scenario_root)
        recovery_search = run(
            [
                "--palace",
                str(palace),
                "search",
                diary_entry[:48],
                "--wing",
                "wing_contract-agent",
                "--room",
                "diary",
                "--results",
                "10",
            ]
        )
        require_ok(recovery_search, "diary recovery", "Results for:", diary_entry)
        if _semantic_tree_snapshot(scenario_root) != after_diary:
            raise RuntimeError("diary recovery search changed scenario state")

        guarded_actions = (
            ["update", "apply", "--json"],
            ["update", "scheduler", "install", "--json"],
            ["update", "scheduler", "remove", "--json"],
        )
        for action in guarded_actions:
            before_refusal = {root: _semantic_tree_snapshot(root) for root in distinct_roots}
            refusal = run(action)
            if refusal.returncode != 2 or refusal.stderr:
                raise RuntimeError("update action did not refuse cleanly")
            try:
                payload = json.loads(refusal.stdout or "")
            except (json.JSONDecodeError, TypeError) as exc:
                raise RuntimeError("update refusal did not emit valid JSON") from exc
            if (
                not isinstance(payload, dict)
                or payload.get("ok") is not False
                or payload.get("stage") != "confirmation"
                or payload.get("exit_code") != 2
                or not isinstance(payload.get("recovery_command"), str)
                or not payload["recovery_command"].endswith("--yes --json")
            ):
                raise RuntimeError("update refusal violated the confirmation contract")
            if any(
                _semantic_tree_snapshot(root) != snapshot
                for root, snapshot in before_refusal.items()
            ):
                raise RuntimeError("update refusal changed scenario state")

        attempts_after = (
            network_attempts.read_bytes()
            if network_attempts is not None and network_attempts.exists()
            else b""
        )
        if attempts_before or attempts_after != attempts_before:
            raise RuntimeError("path-contract scenario attempted network access")
        if _semantic_tree_snapshot(repository_root) != repository_before:
            raise RuntimeError("path-contract scenario changed repository state")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"path-contract evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_path_contracts",
        INSTALLED_PATH_CONTRACT_COMMAND,
        "pass",
        "init, dry-run discovery, diary recovery, and three update refusals preserved state",
    )


def _run_installed_cli_inventory_gap_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    palace: Path,
    project: Path,
    repository_root: Path,
    network_attempts: Path,
    run_subprocess=subprocess.run,
) -> str | None:
    """Exercise safe installed commands not owned by a richer direct scenario."""

    def run(args: list[str], *, input_text: str | None = None):
        result = _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            env,
            neutral_cwd,
            input_text=input_text,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not _installed_output_is_clean(result):
            raise RuntimeError("forbidden subprocess output detected")
        if len(output.encode("utf-8")) > INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT:
            raise RuntimeError("inventory command output exceeded its bounded limit")
        return result

    def require(result, label: str, returncode: int, *markers: str) -> None:
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != returncode or any(marker not in output for marker in markers):
            raise RuntimeError(f"{label} failed its direct output contract")

    def require_json(result, label: str, returncode: int = 0) -> dict:
        require(result, label, returncode)
        try:
            payload = json.loads(result.stdout or "")
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"{label} did not emit valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"{label} emitted a non-object JSON document")
        return payload

    try:
        if not command_prefix or not Path(command_prefix[0]).is_absolute():
            raise RuntimeError("inventory scenario requires an absolute invoked launcher")
        if not palace.is_dir() or not project.is_dir():
            raise RuntimeError("inventory scenario requires the established disposable fixtures")
        scenario_root.mkdir(parents=True)
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        repository_before = _semantic_tree_snapshot(repository_root)
        palace_before = _semantic_tree_snapshot(palace)
        project_before = _semantic_tree_snapshot(project)
        protected_roots = tuple(
            root
            for root in _installed_disposable_roots(env, scenario_root, neutral_cwd)
            if root != scenario_root
        )
        protected_before = {root: _semantic_tree_snapshot(root) for root in protected_roots}
        attempts_before = network_attempts.read_bytes() if network_attempts.exists() else b""
        if attempts_before:
            raise RuntimeError("inventory scenario inherited a network attempt")

        require(run(["help"]), "help", 0, "usage:")

        onboarding_dir = scenario_root / "onboarding"
        onboarding_dir.mkdir()
        onboarding_before = _semantic_tree_snapshot(onboarding_dir)
        require(
            run(["onboarding", str(onboarding_dir)], input_text=""),
            "onboarding EOF recovery",
            1,
            "Onboarding aborted. No changes were saved.",
        )
        if _semantic_tree_snapshot(onboarding_dir) != onboarding_before:
            raise RuntimeError("onboarding EOF recovery changed state")

        require(
            run(["--palace", str(palace), "wake-up"]),
            "wake-up",
            0,
            "Wake-up text",
        )
        migration = run(
            [
                "migrate-storage",
                str(scenario_root / "missing-chroma"),
                str(scenario_root / "migration-target"),
            ]
        )
        require(migration, "optional ChromaDB migration refusal", 1, "Error:")
        if (scenario_root / "migration-target").exists():
            raise RuntimeError("optional ChromaDB migration refusal created a destination")

        require(run(["agent-plugin"]), "agent-plugin parent guidance", 2, "usage:")
        plugin_payload = require_json(run(["agent-plugin", "path", "--json"]), "agent-plugin path")
        plugin_path = Path(str(plugin_payload.get("path", "")))
        candidate_venv = Path(command_prefix[0]).resolve().parent.parent
        if not plugin_path.is_dir() or not plugin_path.resolve().is_relative_to(candidate_venv):
            raise RuntimeError("agent-plugin path escaped the candidate venv")

        require(
            run(["--palace", str(palace), "watch", str(project), "status"]),
            "watch status",
            0,
            "Palace:",
            "Runnable:",
        )

        explicit_backup = scenario_root / "explicit-create.tar.gz"
        require(
            run(
                [
                    "--palace",
                    str(palace),
                    "backup",
                    "create",
                    "--out",
                    str(explicit_backup),
                ]
            ),
            "backup create",
            0,
            "Archive:",
        )
        if not explicit_backup.is_file():
            raise RuntimeError("backup create omitted its archive")
        require(
            run(
                [
                    "--palace",
                    str(palace),
                    "backup",
                    "list",
                    "--dir",
                    str(scenario_root),
                ]
            ),
            "backup list",
            0,
            str(explicit_backup),
        )

        require(run(["preflight"]), "preflight parent guidance", 2, "usage:")
        safe_mirror = (
            "rsync -a --delete --exclude=palace/ --exclude=knowledge_graph.sqlite3 "
            "--exclude=config.json --exclude=backups/ ~/.mempalace/ user@host:.mempalace/"
        )
        mirror_payload = require_json(
            run(["preflight", "mirror", "--command", safe_mirror, "--json"]),
            "preflight mirror",
        )
        if mirror_payload.get("ok") is not True or mirror_payload.get("dangerous") is not False:
            raise RuntimeError("preflight mirror did not accept the canonical safe command")

        require(
            run(["version-check", "--status"]),
            "version-check status",
            0,
            "Version checks:",
            "Current version:",
        )
        update_status = require_json(run(["update", "status", "--json"]), "update status")
        if update_status.get("ok") is not True or update_status.get("stage") != "status":
            raise RuntimeError("update status violated its structured contract")

        update_check = require_json(run(["update", "check", "--json"]), "update check")
        if update_check.get("ok") is not True or update_check.get("stage") != "status":
            raise RuntimeError("update check violated its structured contract")
        attempts_after_check = network_attempts.read_bytes() if network_attempts.exists() else b""
        if not attempts_after_check.startswith(attempts_before):
            raise RuntimeError("update check replaced the socket-attempt ledger")
        expected_attempts = attempts_after_check[len(attempts_before) :].decode(
            "utf-8", errors="replace"
        )
        attempt_lines = expected_attempts.splitlines()
        if not 1 <= len(attempt_lines) <= 2 or any(
            "pypi.org" not in line or "443" not in line for line in attempt_lines
        ):
            raise RuntimeError(
                "update check denied socket attempts differed from the expected PyPI boundary: "
                f"{attempt_lines[:3]!r}"
            )
        network_attempts.write_bytes(attempts_before)

        scheduler_status = require_json(
            run(["update", "scheduler", "status", "--json"]),
            "update scheduler status",
        )
        if scheduler_status.get("stage") != "scheduler-status":
            raise RuntimeError("update scheduler status violated its structured contract")
        scheduler_render = require_json(
            run(["update", "scheduler", "render", "--json"]),
            "update scheduler render",
        )
        if set(scheduler_render) != {"mempalace-update.service", "mempalace-update.timer"}:
            raise RuntimeError("update scheduler render omitted deterministic units")

        if _semantic_tree_snapshot(repository_root) != repository_before:
            raise RuntimeError("inventory scenario changed repository state")
        if _semantic_tree_snapshot(palace) != palace_before:
            raise RuntimeError("inventory scenario changed the established palace")
        if _semantic_tree_snapshot(project) != project_before:
            raise RuntimeError("inventory scenario changed the established project")
        if any(
            _semantic_tree_snapshot(root) != snapshot for root, snapshot in protected_before.items()
        ):
            raise RuntimeError("inventory scenario changed a protected disposable root")
        attempts_final = network_attempts.read_bytes() if network_attempts.exists() else b""
        if attempts_final != attempts_before:
            raise RuntimeError("inventory scenario retained a socket attempt")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        detail = str(exc)
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        return detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
    return None


def _run_installed_schedule_snippet_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root_parent: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove schedule previews bind to the invoked console and refuse installation."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
        return _make_row(
            "installed_golden_schedule_snippets",
            INSTALLED_SCHEDULE_SNIPPETS_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    def run(args: list[str], run_env: dict[str, str]):
        return _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            run_env,
            neutral_cwd,
        )

    if not command_prefix or not Path(command_prefix[0]).is_absolute():
        return failure("schedule scenario requires an absolute invoked launcher")
    if sys.platform.startswith("linux"):
        platform_marker = "crontab -e"
    elif sys.platform.startswith("darwin"):
        platform_marker = None
    else:
        return failure(f"schedule snippet platform is unsupported: {sys.platform}")

    neutral_cwd.mkdir(parents=True, exist_ok=True)
    repository_before: tuple[tuple[str, str, int, str], ...] | None = None
    disposable_root: Path | None = None
    manager = None
    result: dict | None = None
    try:
        repository_before = _semantic_tree_snapshot(repository_root)
        manager = tempfile.TemporaryDirectory(
            prefix=f"{scenario_root_parent.name}-", dir=scenario_root_parent.parent
        )
        disposable_root = Path(manager.name)
        canonical_scenario_root = disposable_root / "canonical schedule scenario"
        scenario_root = disposable_root / "schedule scenario alias"
        ambient_bin = disposable_root / "ambient bin"
        marker = disposable_root / "ambient-launcher-executed"
        watch_root = scenario_root / "watch root ; quoted"
        palace = scenario_root / "palace root ; quoted"
        canonical_scenario_root.mkdir()
        scenario_root.symlink_to(canonical_scenario_root, target_is_directory=True)
        ambient_bin.mkdir(parents=True)
        watch_root.mkdir(parents=True)
        (watch_root / "mempalace.yaml").write_text("wing: installed_schedule\n", encoding="utf-8")
        ambient = ambient_bin / "mempalace-code"
        ambient.write_text(
            "#!/bin/sh\n"
            f"printf executed >> {shlex.quote(str(marker))}\n"
            "echo ambient-launcher-must-not-run >&2\n"
            "exit 97\n",
            encoding="utf-8",
        )
        ambient.chmod(0o755)

        run_env = dict(env)
        run_env["PATH"] = os.pathsep.join([str(ambient_bin), run_env.get("PATH", os.defpath)])
        run_env["PYTHONDONTWRITEBYTECODE"] = "1"
        scenario_before = _semantic_tree_snapshot(canonical_scenario_root)
        safe_launcher = shlex.quote(str(Path(command_prefix[0]).resolve()))
        cases = (
            (
                "backup",
                ["--palace", str(palace), "backup", "schedule", "--freq", "daily"],
                shlex.quote(os.path.abspath(str(palace))),
                shlex.quote(str(palace.resolve())),
                "com.mempalace.backup.plist",
            ),
            (
                "watch",
                ["watch", str(watch_root), "schedule"],
                shlex.quote(str(watch_root.resolve())),
                shlex.quote(os.path.abspath(str(watch_root))),
                "com.mempalace.watch.plist",
            ),
        )

        for label, args, expected_target, alternate_target, scheduler_name in cases:
            expected_guidance = scheduler_name if platform_marker is None else platform_marker
            outputs = []
            for attempt in ("first", "second"):
                invocation = run(args, run_env)
                outputs.append((invocation.stdout, invocation.stderr))
                combined = (invocation.stdout or "") + (invocation.stderr or "")
                if (
                    invocation.returncode != 0
                    or not invocation.stdout
                    or not invocation.stderr
                    or len(invocation.stdout) > 12000
                    or len(invocation.stderr) > 12000
                    or not _installed_output_is_clean(invocation)
                    or safe_launcher not in combined
                    or expected_target not in combined
                    or alternate_target in combined
                    or expected_guidance not in invocation.stderr
                    or str(ambient) in combined
                    or "ambient-launcher-must-not-run" in combined
                    or marker.exists()
                    or _semantic_tree_snapshot(canonical_scenario_root) != scenario_before
                    or _semantic_tree_snapshot(repository_root) != repository_before
                ):
                    detail = (
                        invocation.stderr
                        or invocation.stdout
                        or f"exit {invocation.returncode} or evidence mismatch"
                    )
                    result = failure(f"{label} {attempt} render failed qualification: {detail}")
                    break
            if result is not None:
                break
            if outputs[0] != outputs[1]:
                result = failure(f"{label} render output was not byte-deterministic")
                break

            refusal = run([*args, "--install"], run_env)
            if (
                refusal.returncode != 2
                or refusal.stdout != ""
                or not refusal.stderr
                or len(refusal.stderr) > 12000
                or not _installed_output_is_clean(refusal)
                or safe_launcher not in refusal.stderr
                or expected_target not in refusal.stderr
                or alternate_target in refusal.stderr
                or expected_guidance not in refusal.stderr
                or str(ambient) in refusal.stderr
                or "ambient-launcher-must-not-run" in refusal.stderr
                or marker.exists()
                or _semantic_tree_snapshot(canonical_scenario_root) != scenario_before
                or _semantic_tree_snapshot(repository_root) != repository_before
            ):
                detail = refusal.stderr or refusal.stdout or f"exit {refusal.returncode}"
                result = failure(f"{label} --install refusal failed qualification: {detail}")
                break
    except (
        AttributeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        result = failure(f"schedule snippet evidence could not be evaluated: {exc}")
    finally:
        if manager is not None:
            try:
                manager.cleanup()
            except OSError as exc:
                result = failure(f"schedule snippet cleanup failed: {exc}")

    try:
        if disposable_root is None or disposable_root.exists():
            return failure("schedule snippet disposable root was not removed")
        if (
            repository_before is None
            or _semantic_tree_snapshot(repository_root) != repository_before
        ):
            return failure("schedule snippet scenario changed the repository root")
    except OSError as exc:
        return failure(f"schedule snippet cleanup evidence could not be evaluated: {exc}")
    if result is not None:
        return result
    return _make_row(
        "installed_golden_schedule_snippets",
        INSTALLED_SCHEDULE_SNIPPETS_COMMAND,
        "pass",
        "absolute launcher bound both deterministic quoted previews; installation refused; "
        "state and cleanup preserved",
    )


def _materialized_copy_snapshots(
    path: Path, allowed_root: Path
) -> tuple[
    tuple[tuple[str, str, int, str], ...],
    tuple[tuple[str, str, int, str], ...],
]:
    """Return the stable source and expected materialized-copy snapshots."""
    allowed_root = allowed_root.resolve()
    source_snapshot = _semantic_tree_snapshot(path)
    materialized_snapshot = []
    for relative, kind, size, value in source_snapshot:
        if kind != "symlink":
            materialized_snapshot.append((relative, kind, size, value))
            continue
        link = path / relative
        target = (link.parent / value).resolve()
        if not target.is_relative_to(allowed_root) or not target.is_file():
            raise OSError(f"unsafe symlink target in local-model source at {relative}")
        target_size, target_digest = _stable_file_digest(target)
        materialized_snapshot.append((relative, "file", target_size, target_digest))
    return source_snapshot, tuple(materialized_snapshot)


def _materialize_model_cache(source_hf_home: Path, target_hf_home: Path) -> Path:
    """Copy only the validated model subtree into a disposable, symlink-free HF home."""
    source = source_hf_home / MODEL_CACHE_RELATIVE
    staging = target_hf_home / ".model-source"
    target = target_hf_home / MODEL_CACHE_RELATIVE
    source_before = _semantic_tree_snapshot(source)
    shutil.copytree(source, staging, symlinks=True)
    staging_before = _semantic_tree_snapshot(staging)
    if _semantic_tree_snapshot(source) != source_before or staging_before != source_before:
        raise OSError("source model cache changed during staging")
    _staged_source, target_expected = _materialized_copy_snapshots(staging, staging)
    target.parent.mkdir(parents=True)
    shutil.copytree(staging, target, symlinks=False)
    if (
        _semantic_tree_snapshot(staging) != staging_before
        or _semantic_tree_snapshot(target) != target_expected
    ):
        raise OSError("disposable model cache differs from validated source")
    shutil.rmtree(staging)
    if staging.exists():
        raise OSError("model cache staging cleanup failed")
    return target_hf_home


def _run_installed_alias_target_containment_scenario(
    command_prefix: list[str],
    expected_canonical: Path,
    env: dict[str, str],
    scenario_root_parent: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove explicit alias targets stay contained, refusing collisions and retrying safely."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
        return _make_row(
            "installed_golden_alias_containment",
            INSTALLED_ALIAS_TARGET_CONTAINMENT_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    def run(target_dir: Path, run_env: dict[str, str]):
        return _run_installed_cli(
            run_subprocess,
            command_prefix,
            ["install-alias", "--target-dir", str(target_dir)],
            run_env,
            neutral_cwd,
        )

    neutral_cwd.mkdir(parents=True, exist_ok=True)
    repository_before: tuple[tuple[str, str, int, str], ...] | None = None
    disposable_root: Path | None = None
    manager = None
    result: dict | None = None
    try:
        repository_before = _semantic_tree_snapshot(repository_root)
        manager = tempfile.TemporaryDirectory(
            prefix=f"{scenario_root_parent.name}-", dir=scenario_root_parent.parent
        )
        disposable_root = Path(manager.name)
        ambient_bin = disposable_root / "ambient-bin"
        target_bin = disposable_root / "target-bin"
        collision_bin = disposable_root / "collision-bin"
        for directory in (ambient_bin, target_bin, collision_bin):
            directory.mkdir()

        unrelated_canonical = ambient_bin / "unrelated-mempalace-code"
        unrelated_canonical.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        unrelated_canonical.chmod(0o755)
        ambient_alias = ambient_bin / "mempalace"
        ambient_alias.symlink_to(unrelated_canonical.name)
        ambient_before = _semantic_tree_snapshot(ambient_bin)

        run_env = dict(env)
        run_env["PATH"] = os.pathsep.join([str(ambient_bin), run_env.get("PATH", os.defpath)])
        run_env["PYTHONDONTWRITEBYTECODE"] = "1"

        target_alias = target_bin / "mempalace"
        expected_success = f"  Alias ready: {target_alias} -> mempalace-code\n"
        first = run(target_bin, run_env)
        target_link = os.readlink(target_alias) if target_alias.is_symlink() else ""
        first_ok = (
            first.returncode == 0
            and first.stdout == expected_success
            and first.stderr == ""
            and len(first.stdout) <= 1200
            and _installed_output_is_clean(first)
            and target_alias.is_symlink()
            and target_alias.resolve() == expected_canonical.resolve()
            and _semantic_tree_snapshot(target_bin)
            == ((".", "dir", 0, ""), ("mempalace", "symlink", len(target_link), target_link))
            and _semantic_tree_snapshot(ambient_bin) == ambient_before
        )
        if not first_ok:
            detail = first.stderr or first.stdout or f"exit {first.returncode} or target mismatch"
            result = failure(f"explicit target install failed containment or provenance: {detail}")
        else:
            target_before_retry = _semantic_tree_snapshot(target_bin)
            retry = run(target_bin, run_env)
            retry_ok = (
                retry.returncode == 0
                and retry.stdout == expected_success
                and retry.stderr == ""
                and len(retry.stdout) <= 1200
                and _installed_output_is_clean(retry)
                and _semantic_tree_snapshot(target_bin) == target_before_retry
                and target_alias.resolve() == expected_canonical.resolve()
                and _semantic_tree_snapshot(ambient_bin) == ambient_before
            )
            if not retry_ok:
                detail = retry.stderr or retry.stdout or f"exit {retry.returncode} or state changed"
                result = failure(f"explicit target retry was not idempotent: {detail}")

        if result is None:
            collision = collision_bin / "mempalace"
            collision.write_bytes(b"unrelated collision\n")
            collision_before = _semantic_tree_snapshot(collision_bin)
            refusal = run(collision_bin, run_env)
            expected_error = f"  Error: {collision} already exists; not overwriting\n"
            refusal_ok = (
                refusal.returncode == 1
                and refusal.stdout == ""
                and refusal.stderr == expected_error
                and len(refusal.stderr) <= 1200
                and _installed_output_is_clean(refusal)
                and _semantic_tree_snapshot(collision_bin) == collision_before
                and _semantic_tree_snapshot(target_bin) == target_before_retry
                and _semantic_tree_snapshot(ambient_bin) == ambient_before
            )
            if not refusal_ok:
                detail = (
                    refusal.stderr
                    or refusal.stdout
                    or f"exit {refusal.returncode} or state changed"
                )
                result = failure(f"conflicting target was not refused without mutation: {detail}")
    except (
        AttributeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        result = failure(f"alias containment evidence could not be evaluated: {exc}")
    finally:
        if manager is not None:
            try:
                manager.cleanup()
            except OSError as exc:
                result = failure(f"alias containment cleanup failed: {exc}")

    try:
        if disposable_root is None or disposable_root.exists():
            return failure("alias containment disposable root was not removed")
        if (
            repository_before is None
            or _semantic_tree_snapshot(repository_root) != repository_before
        ):
            return failure("alias containment scenario changed the repository root")
    except OSError as exc:
        return failure(f"alias containment cleanup evidence could not be evaluated: {exc}")
    if result is not None:
        return result
    return _make_row(
        "installed_golden_alias_containment",
        INSTALLED_ALIAS_TARGET_CONTAINMENT_COMMAND,
        "pass",
        "explicit target contained the candidate alias; ambient alias preserved; "
        "collision refused; retry idempotent; provenance and cleanup passed",
    )


def _run_installed_fetch_model_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove cached, local, force, offline failure, and retry fetch-model paths."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded_detail = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")
        bounded_detail = bounded_detail[:1200]
        return _make_row(
            "installed_golden_fetch_model",
            INSTALLED_FETCH_MODEL_COMMAND,
            "fail",
            f"{bounded_detail}; {recovery}",
        )

    def run(args: list[str], run_env: dict[str, str]):
        return _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            run_env,
            neutral_cwd,
        )

    def require_success(step: str, result, *markers: str) -> dict | None:
        if (
            result.returncode != 0
            or result.stderr != ""
            or not _installed_output_is_clean(result)
            or any(marker not in (result.stdout or "") for marker in markers)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        return None

    def boundary_snapshot() -> tuple[tuple[str, tuple], ...]:
        artifacts = sorted(
            path
            for path in repository_root.iterdir()
            if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
        )
        return tuple((path.name, _semantic_tree_snapshot(path)) for path in artifacts)

    try:
        repository_boundary = boundary_snapshot()
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        disposable_hf_home = scenario_root / "hf-home"
        disposable_cache = disposable_hf_home / MODEL_CACHE_RELATIVE
        local_model = scenario_root / "local-model"
        retry_model = scenario_root / "retry-model"
        source_cache = None
        source_cache_before = None
        installed_mode = bool(env.get("MEMPALACE_TEST_INSTALLED_CLI"))

        if installed_mode:
            source_cache = Path(env["HF_HOME"]) / MODEL_CACHE_RELATIVE
            if not source_cache.is_dir():
                return failure("validated source model cache is missing")
            source_cache_before = _semantic_tree_snapshot(source_cache)
            shutil.copytree(source_cache, disposable_cache, symlinks=True)
            revision = (disposable_cache / "refs" / "main").read_text(encoding="utf-8").strip()
            snapshots_root = disposable_cache / "snapshots"
            named_snapshot = snapshots_root / revision
            if (
                not re.fullmatch(r"[A-Za-z0-9._-]+", revision)
                or revision in (".", "..")
                or named_snapshot.is_symlink()
                or not named_snapshot.is_dir()
                or not named_snapshot.resolve().is_relative_to(snapshots_root.resolve())
            ):
                return failure("validated source model cache refs/main snapshot is unsafe")
            _semantic_tree_snapshot(disposable_cache)
            named_snapshot_before, local_model_expected = _materialized_copy_snapshots(
                named_snapshot, disposable_cache
            )
            shutil.copytree(named_snapshot, local_model, symlinks=False)
            if (
                _semantic_tree_snapshot(named_snapshot) != named_snapshot_before
                or _semantic_tree_snapshot(local_model) != local_model_expected
            ):
                return failure("local-model materialization changed during copy")
        else:
            disposable_cache.mkdir(parents=True)
            local_model.mkdir(parents=True)

        scenario_env = env.copy()
        scenario_env["HF_HOME"] = str(disposable_hf_home)
        scenario_env["MEMPALACE_TEST_HF_HOME"] = str(disposable_hf_home)
        scenario_env.pop("PYTHONUNBUFFERED", None)

        cached = run(
            ["fetch-model", "--model", "all-MiniLM-L6-v2"],
            scenario_env,
        )
        failed = require_success(
            "cached default model",
            cached,
            "already available locally",
            "Cached at:",
            "Done",
        )
        if failed:
            return failed

        local = run(["fetch-model", "--model", str(local_model)], scenario_env)
        failed = require_success(
            "explicit local model",
            local,
            "already available locally",
            "Local model path:",
            "Done",
        )
        if failed:
            return failed

        forced = run(
            ["fetch-model", "--model", str(local_model), "--force"],
            scenario_env,
        )
        failed = require_success(
            "forced local refresh",
            forced,
            "Downloading model",
            "Waiting for model download",
            "Local model path:",
            "Done",
        )
        if failed:
            return failed

        failing_env = scenario_env.copy()
        if not installed_mode:
            failing_env["MEMPALACE_FAKE_ST_FAIL"] = "1"
        offline_failure = run(["fetch-model", "--model", str(retry_model)], failing_env)
        offline_failure_ok = (
            offline_failure.returncode == 1
            and _installed_output_is_clean(offline_failure)
            and "Downloading model" in (offline_failure.stdout or "")
            and "Waiting for model download" in (offline_failure.stdout or "")
            and "Done" not in (offline_failure.stdout or "")
            and "Error preparing model:" in (offline_failure.stderr or "")
            and not retry_model.exists()
        )
        if not offline_failure_ok:
            detail = (
                offline_failure.stderr
                or offline_failure.stdout
                or f"exit {offline_failure.returncode}"
            )
            return failure(f"offline missing-model failure was unsafe: {detail}")

        shutil.copytree(local_model, retry_model, symlinks=True)
        retry_model_expected = _semantic_tree_snapshot(retry_model)
        retried = run(["fetch-model", "--model", str(retry_model)], scenario_env)
        failed = require_success(
            "successful retry",
            retried,
            "already available locally",
            "Local model path:",
            "Done",
        )
        if failed:
            return failed

        if not disposable_cache.is_dir():
            return failure("disposable cached default model is missing after retry")
        if not retry_model.is_dir() or _semantic_tree_snapshot(retry_model) != retry_model_expected:
            return failure("successful retry target changed or disappeared after retry")
        if (
            source_cache is not None
            and _semantic_tree_snapshot(source_cache) != source_cache_before
        ):
            return failure("validated source model cache changed during the scenario")
        if boundary_snapshot() != repository_boundary:
            return failure("fetch-model scenario created a repository-root artifact")
        attempts_path = env.get("MEMPALACE_SOCKET_ATTEMPTS")
        if (
            attempts_path
            and Path(attempts_path).is_file()
            and Path(attempts_path).read_text(encoding="utf-8")
        ):
            return failure("fetch-model scenario attempted network access")
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        return failure(f"fetch-model evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_fetch_model",
        INSTALLED_FETCH_MODEL_COMMAND,
        "pass",
        "cached default, local, force, offline failure, retry, and immutable source cache passed",
    )


def _wheel_identity(wheel: Path) -> tuple[str, str]:
    """Read distribution name and version from the exact wheel metadata."""
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ValueError(f"expected one METADATA member, found {len(metadata_names)}")
            metadata = email.message_from_bytes(archive.read(metadata_names[0]))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError(f"could not read candidate wheel metadata: {exc}") from exc
    name = str(metadata.get("Name", "")).strip()
    version = str(metadata.get("Version", "")).strip()
    if re.sub(r"[-_.]+", "-", name).lower() != PACKAGE_NAME or not version:
        raise ValueError("candidate wheel metadata does not identify mempalace-code with a version")
    return name, version


def _installed_golden_env(
    base_env: dict[str, str],
    *,
    temp_root: Path,
    hf_home: Path,
    console: Path,
    marker: Path,
    attempts: Path,
) -> dict[str, str]:
    """Build a credential-free, disposable, offline environment for the golden suite."""
    env = {
        key: base_env[key] for key in ("PATH", "SYSTEMROOT", "LANG", "LC_ALL") if base_env.get(key)
    }
    home = temp_root / "home"
    cache = temp_root / "xdg-cache"
    config = temp_root / "xdg-config"
    data = temp_root / "xdg-data"
    for path in (home, cache, config, data):
        path.mkdir()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TMPDIR": str(temp_root),
            "XDG_CACHE_HOME": str(cache),
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(data),
            "HF_HOME": str(hf_home),
            "MEMPALACE_TEST_HF_HOME": str(hf_home),
            "MEMPALACE_TEST_INSTALLED_CLI": str(console),
            "MEMPALACE_SOCKET_GUARD_LOADED": str(marker),
            "MEMPALACE_SOCKET_ATTEMPTS": str(attempts),
            "MEMPALACE_VERSION_CHECK": "0",
            "MEMPALACE_DISK_MIN_FREE_BYTES": "1",
            "CUDA_CACHE_DISABLE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_KEYRING_PROVIDER": "disabled",
        }
    )
    return env


def _run_installed_split_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    run_subprocess=subprocess.run,
) -> dict:
    """Exercise split dry-run, apply, and repeat refusal through a real CLI process."""
    source_dir = scenario_root / "transcripts"
    output_dir = scenario_root / "split-output"
    source = source_dir / "mega.txt"
    backup = source.with_suffix(".mega_backup")
    neutral_cwd.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True)
    first_session = "Claude Code v1\n" + "\n".join(["> prompt", *(["answer"] * 12)])
    second_session = "Claude Code v1\n" + "\n".join(["> prompt two", *(["answer"] * 12)])
    original = first_session + "\n" + second_session
    expected = {
        "mega_part01_unknown_prompt.txt": first_session + "\n",
        "mega_part02_unknown_prompt-two.txt": second_session,
    }
    source.write_text(original, encoding="utf-8")
    args = ["split", str(source_dir), "--output-dir", str(output_dir)]

    def run(extra: list[str] | None = None):
        return _run_installed_cli(
            run_subprocess,
            command_prefix,
            [*args, *(extra or [])],
            env,
            neutral_cwd,
        )

    def failure(step: str, result) -> dict:
        return _make_row(
            "installed_golden_split",
            INSTALLED_SPLIT_COMMAND,
            "fail",
            f"{step}: " + (result.stderr or result.stdout or f"exit {result.returncode}"),
        )

    preview = run(["--dry-run"])
    try:
        preview_ok = (
            preview.returncode == 0
            and _installed_output_is_clean(preview)
            and "DRY RUN" in preview.stdout
            and all(name in preview.stdout for name in expected)
            and not output_dir.exists()
            and source.read_text(encoding="utf-8") == original
            and not backup.exists()
        )
    except (OSError, UnicodeError):
        preview_ok = False
    if not preview_ok:
        return failure("dry-run changed state or omitted planned outputs", preview)

    applied = run()
    try:
        outputs = list(output_dir.iterdir())
        apply_ok = (
            applied.returncode == 0
            and _installed_output_is_clean(applied)
            and "Done — created 2 files" in applied.stdout
            and "Original renamed to mega.mega_backup" in applied.stdout
            and not source.exists()
            and backup.read_text(encoding="utf-8") == original
            and {path.name: path.read_text(encoding="utf-8") for path in outputs} == expected
            and all(path.is_file() and not path.is_symlink() for path in outputs)
        )
    except (OSError, UnicodeError):
        apply_ok = False
    if not apply_ok:
        return failure("apply did not produce exact output and backup post-state", applied)

    source.write_text(original, encoding="utf-8")
    before = {path.name: path.read_bytes() for path in output_dir.iterdir()}
    backup_before = backup.read_bytes()
    repeated = run()
    try:
        repeat_ok = (
            repeated.returncode == 1
            and _installed_output_is_clean(repeated)
            and source.read_text(encoding="utf-8") == original
            and {path.name: path.read_bytes() for path in output_dir.iterdir()} == before
            and backup.read_bytes() == backup_before
            and (repeated.stdout + repeated.stderr).count("retry with a new empty --output-dir")
            == 1
        )
    except (OSError, UnicodeError):
        repeat_ok = False
    if not repeat_ok:
        return failure(
            "repeat did not fail safely with one recovery command and unchanged state", repeated
        )
    return _make_row(
        "installed_golden_split",
        INSTALLED_SPLIT_COMMAND,
        "pass",
        "dry-run, exact output and backup post-state, and safe repeat refusal passed",
    )


def _run_installed_compress_retry_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove compression recovery, unchanged retry, refusal, and mixed state."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded_detail = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")
        return _make_row(
            "installed_golden_compress_retry",
            INSTALLED_COMPRESS_RETRY_COMMAND,
            "fail",
            f"{bounded_detail}; {recovery}",
        )

    def run(args: list[str]):
        return _run_installed_cli(run_subprocess, command_prefix, args, env, neutral_cwd)

    def require_success(step: str, result, *markers: str) -> dict | None:
        if (
            result.returncode != 0
            or result.stderr != ""
            or not _installed_output_is_clean(result)
            or any(marker not in (result.stdout or "") for marker in markers)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        return None

    def archives(palace: Path) -> set[Path]:
        backup_root = palace.parent / "backups"
        return set(backup_root.glob("*.tar.gz")) if backup_root.exists() else set()

    def directory_bytes(path: Path) -> int:
        return (
            sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
            if path.exists()
            else 0
        )

    def palace_and_backup_bytes(palace: Path) -> int:
        return directory_bytes(palace) + directory_bytes(palace.parent / "backups")

    def boundary_snapshot() -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name
                for path in repository_root.iterdir()
                if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
            )
        )

    export_index = 0

    def drawer_snapshot(label: str, palace: Path) -> tuple[dict[str, dict] | None, dict | None]:
        nonlocal export_index
        export_index += 1
        export_path = scenario_root / f"compress-snapshot-{export_index}.jsonl"
        result = run(["--palace", str(palace), "export", "--out", str(export_path)])
        if result.returncode != 0 or result.stdout != "" or not _installed_output_is_clean(result):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return None, failure(f"{label} failed: {detail}")
        try:
            records = [
                json.loads(line) for line in export_path.read_text(encoding="utf-8").splitlines()
            ]
        except (json.JSONDecodeError, OSError, TypeError, UnicodeError) as exc:
            return None, failure(f"{label} export could not be parsed: {exc}")
        if not records or any(not isinstance(record, dict) for record in records):
            return None, failure(f"{label} export has the wrong top-level shape")
        header = records[0]
        drawers = records[1:]
        if (
            header.get("type") != "export_header"
            or type(header.get("drawer_count")) is not int
            or type(header.get("kg_count")) is not int
            or header["drawer_count"] != len(drawers)
            or header["kg_count"] != 0
            or any(record.get("type") != "drawer" for record in drawers)
        ):
            return None, failure(f"{label} export has an invalid record sequence or counts")
        ids = [record.get("id") for record in drawers]
        if any(not isinstance(doc_id, str) or not doc_id for doc_id in ids) or len(set(ids)) != len(
            ids
        ):
            return None, failure(f"{label} export has missing or duplicate drawer IDs")
        expected_stderr = (
            f"  Exporting from: {palace}\n"
            f"  Exported {header['drawer_count']} drawers, 0 KG triples → {export_path}\n"
        )
        if result.stderr != expected_stderr:
            return None, failure(f"{label} export emitted unexpected stderr: {result.stderr}")
        if any(
            type(record.get("original_tokens")) is not int or record["original_tokens"] < 0
            for record in drawers
        ):
            return None, failure(f"{label} export has invalid original_tokens provenance")
        return {record["id"]: record for record in drawers}, None

    try:
        repository_boundary = boundary_snapshot()
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        project = _write_fixture_project(scenario_root / "project")
        palace = scenario_root / "palace root"

        for step, args, marker in (
            ("init", ["init", str(project), "--skip-model-download"], "Config saved:"),
            ("mine", ["--palace", str(palace), "mine", str(project)], "Drawers filed:"),
        ):
            failed = require_success(step, run(args), marker)
            if failed is not None:
                return failed

        dry_run_archives = archives(palace)
        dry_run_bytes = palace_and_backup_bytes(palace)
        dry_run = run(["--palace", str(palace), "compress", "--wing", project.name, "--dry-run"])
        failed = require_success(
            "dry-run", dry_run, "Pending:", "skipped already compressed: 0", "Total:"
        )
        if failed is not None:
            return failed
        if archives(palace) != dry_run_archives or palace_and_backup_bytes(palace) != dry_run_bytes:
            return failure("dry-run changed the palace or recovery archive set")

        before_first, failed = drawer_snapshot("pre-apply", palace)
        if failed is not None:
            return failed
        assert before_first is not None
        backups_before_first = archives(palace)
        first = run(["--palace", str(palace), "compress", "--wing", project.name])
        failed = require_success(
            "first apply", first, "Recovery archive:", "Recovery command:", "Stored and verified"
        )
        if failed is not None:
            return failed
        backups_after_first = archives(palace)
        created_backups = backups_after_first - backups_before_first
        if len(created_backups) != 1:
            return failure("first apply did not create exactly one recovery archive")
        recovery_archive = next(iter(created_backups))
        if str(recovery_archive) not in first.stdout:
            return failure("first apply did not name its recovery archive")
        recovery_lines = [
            line
            for line in first.stdout.splitlines()
            if line.strip().startswith("Recovery command:")
        ]
        if len(recovery_lines) != 1:
            return failure("first apply did not emit exactly one recovery command")
        recovery_argv = shlex.split(recovery_lines[0].split("Recovery command:", 1)[1].strip())
        if (
            len(recovery_argv) != 6
            or recovery_argv[0] != "mempalace-code"
            or recovery_argv[1] != "--palace"
            or recovery_argv[3] != "restore"
            or recovery_argv[5] != "--force"
            or Path(recovery_argv[2]).resolve(strict=True) != palace.resolve(strict=True)
            or Path(recovery_argv[4]).resolve(strict=True) != recovery_archive.resolve(strict=True)
        ):
            return failure("first apply emitted the wrong recovery command")

        after_first, failed = drawer_snapshot("post-first", palace)
        if failed is not None:
            return failed
        assert after_first is not None
        if set(after_first) != set(before_first):
            return failure("first apply changed drawer IDs")
        if any(
            type(record.get("original_tokens")) is not int or record["original_tokens"] <= 0
            for record in after_first.values()
        ):
            return failure("first apply left invalid original_tokens provenance")

        retry = run(["--palace", str(palace), "compress", "--wing", project.name])
        failed = require_success(
            "unchanged retry",
            retry,
            "Pending: 0",
            f"skipped already compressed: {len(after_first)}",
        )
        if failed is not None:
            return failed
        after_retry, failed = drawer_snapshot("post-retry", palace)
        if failed is not None:
            return failed
        if after_retry != after_first or archives(palace) != backups_after_first:
            return failure("unchanged retry changed exported records or recovery archives")

        bytes_before_unknown = palace_and_backup_bytes(palace)
        unknown = run(["--palace", str(palace), "compress", "--wing", "definitely-missing"])
        expected_unknown_stderr = (
            "\n  Unknown wing: 'definitely-missing'\n"
            "  Next: run mempalace-code status, or check mempalace_list_wings / "
            "mempalace_list_rooms / mempalace_get_taxonomy for valid taxonomy identifiers "
            "— filters are validated against the palace taxonomy and suggestions are advisory only.\n"
        )
        if (
            unknown.returncode != 2
            or unknown.stdout != ""
            or unknown.stderr != expected_unknown_stderr
            or not _installed_output_is_clean(unknown)
            or palace_and_backup_bytes(palace) != bytes_before_unknown
            or archives(palace) != backups_after_first
        ):
            detail = unknown.stderr or unknown.stdout or f"exit {unknown.returncode}"
            return failure(f"unknown-wing refusal was not exact: {detail}")

        (project / "new_source.py").write_text(
            textwrap.dedent(
                '''\
                def newly_mined_compression_candidate(value):
                    """A new ordinary source drawer for mixed compression state."""
                    adjusted = value + 10
                    return adjusted * 3
                '''
            ),
            encoding="utf-8",
        )
        mixed_mine = run(["--palace", str(palace), "mine", str(project)])
        failed = require_success("mixed-state mine", mixed_mine, "Drawers filed:")
        if failed is not None:
            return failed
        mixed_before, failed = drawer_snapshot("mixed-before", palace)
        if failed is not None:
            return failed
        assert mixed_before is not None
        pending_ids = {
            doc_id for doc_id, record in mixed_before.items() if record["original_tokens"] == 0
        }
        completed_ids = {
            doc_id for doc_id, record in mixed_before.items() if record["original_tokens"] > 0
        }
        if (
            not pending_ids
            or not set(after_first).issubset(mixed_before)
            or any(mixed_before.get(doc_id) != record for doc_id, record in after_first.items())
        ):
            return failure("mixed-state export did not contain completed and pending drawers")
        backups_before_mixed = archives(palace)
        mixed = run(["--palace", str(palace), "compress", "--wing", project.name])
        failed = require_success(
            "mixed-state apply",
            mixed,
            f"Pending: {len(pending_ids)}",
            f"skipped already compressed: {len(completed_ids)}",
            "Stored and verified",
        )
        if failed is not None:
            return failed
        mixed_after, failed = drawer_snapshot("mixed-after", palace)
        if failed is not None:
            return failed
        assert mixed_after is not None
        if any(mixed_after.get(doc_id) != mixed_before[doc_id] for doc_id in completed_ids):
            return failure("mixed-state apply changed an already-compressed drawer")
        if set(mixed_after) != set(mixed_before):
            return failure("mixed-state apply changed the drawer ID set")
        if any(
            type(mixed_after.get(doc_id, {}).get("original_tokens")) is not int
            or mixed_after[doc_id]["original_tokens"] <= 0
            for doc_id in pending_ids
        ):
            return failure("mixed-state apply left pending drawers uncompressed")
        if len(archives(palace) - backups_before_mixed) != 1:
            return failure("mixed-state apply did not create exactly one recovery archive")

        search = run(
            [
                "--palace",
                str(palace),
                "search",
                "xylophonic_glyph_9182",
                "--results",
                "10",
            ]
        )
        failed = require_success(
            "post-compression search", search, "Results for:", "xylophonic_glyph_9182"
        )
        if failed is not None:
            return failed
        if boundary_snapshot() != repository_boundary:
            return failure("compression scenario changed the repository-root artifact boundary")
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"compression retry evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_compress_retry",
        INSTALLED_COMPRESS_RETRY_COMMAND,
        "pass",
        "dry-run, recovery, unchanged retry, refusal, mixed state, and search passed",
    )


def _run_installed_import_missing_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove a missing import fails with recovery guidance and no palace mutation."""
    scenario_root.mkdir(parents=True)
    missing = scenario_root / "not_here.jsonl"
    palace = scenario_root / "palace"
    result = _run_installed_cli(
        run_subprocess,
        command_prefix,
        ["--palace", str(palace), "import", str(missing)],
        env,
        neutral_cwd,
    )
    passed = (
        result.returncode != 0
        and str(missing) in result.stderr
        and ("Next:" in result.stderr or "export" in result.stderr.lower())
        and not palace.exists()
        and _installed_output_is_clean(result)
    )
    if not passed:
        return _make_row(
            "installed_golden_import_missing",
            INSTALLED_IMPORT_MISSING_COMMAND,
            "fail",
            "missing import did not fail safely with recovery guidance and unchanged state: "
            + (result.stderr or result.stdout or f"exit {result.returncode}"),
        )
    return _make_row(
        "installed_golden_import_missing",
        INSTALLED_IMPORT_MISSING_COMMAND,
        "pass",
        "missing input failed with a named path, recovery guidance, and no palace state",
    )


def _run_installed_palace_argument_scenarios(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    run_subprocess=subprocess.run,
) -> list[dict]:
    """Exercise reordered, contradictory, duplicate, and malformed --palace input."""
    scenario_root.mkdir(parents=True)
    palace = scenario_root / "palace"
    palace_a = scenario_root / "palace_a"
    palace_b = scenario_root / "palace_b"

    def run(args: list[str]):
        return _run_installed_cli(run_subprocess, command_prefix, args, env, neutral_cwd)

    def row(case: str, passed: bool, results: tuple, success: str) -> dict:
        failure = next(
            (item.stderr or item.stdout for item in results if item.stderr or item.stdout), ""
        )
        return _make_row(
            f"installed_golden_palace_{case}",
            INSTALLED_PALACE_ARGUMENT_COMMAND,
            "pass" if passed else "fail",
            success if passed else (failure or f"{case} contract mismatch"),
        )

    before = run(["--palace", str(palace), "status"])
    after = run(["status", "--palace", str(palace)])
    order_ok = (
        before.returncode == after.returncode == 0
        and _installed_output_is_clean(before)
        and _installed_output_is_clean(after)
        and before.stdout == after.stdout
    )
    rows = [row("order", order_ok, (before, after), "before/after-subcommand forms matched")]

    conflict = run(["--palace", str(palace_a), "status", "--palace", str(palace_b)])
    conflict_ok = (
        conflict.returncode == 2
        and _installed_output_is_clean(conflict)
        and str(palace_a) in conflict.stderr
        and str(palace_b) in conflict.stderr
        and not palace_a.exists()
        and not palace_b.exists()
    )
    rows.append(
        row(
            "conflict",
            conflict_ok,
            (conflict,),
            "contradictory values were named and rejected without state",
        )
    )

    duplicate = run(["--palace", str(palace), "status", "--palace", str(palace)])
    duplicate_ok = duplicate.returncode == 0 and _installed_output_is_clean(duplicate)
    rows.append(
        row("duplicate", duplicate_ok, (duplicate,), "identical duplicate value was accepted")
    )

    option_value = run(["status", "--palace", "--summary"])
    option_ok = (
        option_value.returncode == 2
        and _installed_output_is_clean(option_value)
        and not (neutral_cwd / "--summary").exists()
    )
    rows.append(
        row(
            "option_value",
            option_ok,
            (option_value,),
            "option token was rejected as a palace value without state",
        )
    )
    return rows


def _run_installed_search_results_scenarios(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    run_subprocess=subprocess.run,
) -> list[dict]:
    """Prove non-positive search result counts fail before storage access."""
    scenario_root.mkdir(parents=True)
    palace = scenario_root / "palace"
    rows = []
    for case, value in (("zero", "0"), ("negative_one", "-1")):
        result = _run_installed_cli(
            run_subprocess,
            command_prefix,
            ["--palace", str(palace), "search", "query", "--results", value],
            env,
            neutral_cwd,
        )
        output = result.stderr + result.stdout
        passed = (
            result.returncode == 2
            and _installed_output_is_clean(result)
            and f"argument --results: must be at least 1, got {value}" in result.stderr
            and "repair" not in output.lower()
            and not palace.exists()
        )
        rows.append(
            _make_row(
                f"installed_golden_search_results_{case}",
                INSTALLED_SEARCH_RESULTS_COMMAND,
                "pass" if passed else "fail",
                f"--results {value} was rejected before storage access"
                if passed
                else (result.stderr or result.stdout or f"exit {result.returncode}"),
            )
        )
    return rows


def _run_installed_version_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    neutral_cwd: Path,
    expected_version: str,
    *,
    run_subprocess=subprocess.run,
) -> dict:
    """Exercise the installed --version flag without package-source imports."""
    result = _run_installed_cli(run_subprocess, command_prefix, ["--version"], env, neutral_cwd)
    source_launcher = command_prefix == [sys.executable, "-m", "mempalace_code.cli"]
    installed_launcher = (
        len(command_prefix) == 1 and Path(command_prefix[0]).name == "mempalace-code"
    )
    if source_launcher:
        python_module_label = rf"python{sys.version_info.major} -m mempalace_code\.cli"
        launcher_pattern = rf"(?:cli\.py|python -m mempalace_code\.cli|{python_module_label})"
    elif installed_launcher:
        launcher_pattern = r"mempalace-code"
    else:
        launcher_pattern = None
    version_output = (
        re.fullmatch(
            rf"{launcher_pattern} {re.escape(expected_version)}\n?",
            result.stdout,
        )
        if launcher_pattern is not None
        else None
    )
    passed = (
        result.returncode == 0
        and _installed_output_is_clean(result)
        and not result.stderr
        and version_output is not None
    )
    return _make_row(
        "installed_golden_version",
        INSTALLED_VERSION_COMMAND,
        "pass" if passed else "fail",
        f"installed --version matched candidate {expected_version}"
        if passed
        else (result.stderr or result.stdout or f"exit {result.returncode}"),
    )


def _run_installed_diary_blank_required_fields_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    cases=INSTALLED_DIARY_BLANK_REQUIRED_FIELDS_CASES,
    *,
    repository_root: Path,
    network_attempts: Path | None = None,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove blank diary required fields are rejected twice without post-state."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
        return _make_row(
            "installed_golden_diary_blank_required_fields",
            INSTALLED_DIARY_BLANK_REQUIRED_FIELDS_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    if not command_prefix or not Path(command_prefix[0]).is_absolute():
        return failure("diary blank-field scenario requires an absolute invoked launcher")

    try:
        repository_before = _semantic_tree_snapshot(repository_root)
        attempts_before = (
            network_attempts.read_bytes()
            if network_attempts is not None and network_attempts.exists()
            else b""
        )
        scenario_root.mkdir(parents=True, exist_ok=True)
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        scenario_before = _semantic_tree_snapshot(scenario_root)
        palace = scenario_root / "absent-palace"

        for option, value, other_option, other_value in cases:
            expected_stderr = (
                f"Error: {option} must not be blank.\n"
                "Try: mempalace-code diary write --agent agent-name "
                "--entry 'your diary entry'\n"
            )
            args = [
                "--palace",
                str(palace),
                "diary",
                "write",
                option,
                value,
                other_option,
                other_value,
                "--topic",
                "",
            ]
            for attempt in range(2):
                result = _run_installed_cli(run_subprocess, command_prefix, args, env, neutral_cwd)
                output = (result.stdout or "") + (result.stderr or "")
                if not _installed_output_is_clean(result):
                    raise RuntimeError("forbidden subprocess output detected")
                if len(output) > INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT:
                    raise RuntimeError("subprocess output exceeded the bounded evidence limit")
                if result.returncode != 2:
                    raise RuntimeError(
                        f"{option} attempt {attempt} returned exit {result.returncode}"
                    )
                if result.stdout != "":
                    raise RuntimeError(f"{option} attempt {attempt} emitted stdout")
                if result.stderr != expected_stderr:
                    raise RuntimeError(f"{option} attempt {attempt} emitted non-canonical guidance")
                if palace.exists() or _semantic_tree_snapshot(scenario_root) != scenario_before:
                    raise RuntimeError(f"{option} attempt {attempt} created palace post-state")
                attempts_after = (
                    network_attempts.read_bytes()
                    if network_attempts is not None and network_attempts.exists()
                    else b""
                )
                if attempts_before or attempts_after != attempts_before:
                    raise RuntimeError("diary blank-field scenario attempted network access")
                if _semantic_tree_snapshot(repository_root) != repository_before:
                    raise RuntimeError("diary blank-field scenario changed repository state")
    except (
        AttributeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"diary blank-field evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_diary_blank_required_fields",
        INSTALLED_DIARY_BLANK_REQUIRED_FIELDS_COMMAND,
        "pass",
        "four blank required-field refusals repeated with exact guidance and no post-state",
    )


def _run_installed_read_failure_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove invalid-range and missing-palace reads fail cleanly without mutation."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        bounded_detail = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")
        return _make_row(
            "installed_golden_read_failures",
            INSTALLED_READ_FAILURES_COMMAND,
            "fail",
            f"{bounded_detail}; {recovery}",
        )

    def run(args: list[str]):
        return _run_installed_cli(run_subprocess, command_prefix, args, env, neutral_cwd)

    def require_success(step: str, result, success_marker: str | None = None) -> dict | None:
        if (
            result.returncode != 0
            or not result.stdout
            or result.stderr
            or not _installed_output_is_clean(result)
            or (success_marker is not None and success_marker not in result.stdout)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        return None

    def health_tuple(step: str) -> tuple[tuple[int, int, int] | None, dict | None]:
        result = run(["--palace", str(palace), "health", "--json"])
        failed = require_success(step, result)
        if failed is not None:
            return None, failed
        value = json.loads(result.stdout)
        storage = value.get("storage") if isinstance(value, dict) else None
        if not (
            isinstance(value, dict)
            and type(value.get("total_rows")) is int
            and type(value.get("current_version")) is int
            and isinstance(storage, dict)
            and type(storage.get("version_count")) is int
        ):
            return None, failure(f"{step} returned malformed health JSON")
        return (value["total_rows"], value["current_version"], storage["version_count"]), None

    def boundary_snapshot() -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name
                for path in repository_root.iterdir()
                if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
            )
        )

    def require_failure_output(
        step: str,
        result,
        markers: tuple[str, ...],
    ) -> dict | None:
        positions = [result.stderr.find(marker) for marker in markers]
        if (
            result.returncode == 0
            or result.stdout
            or not result.stderr
            or not _installed_output_is_clean(result)
            or any(position < 0 for position in positions)
            or positions != sorted(positions)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} output contract failed: {detail}")
        return None

    try:
        repository_boundary = boundary_snapshot()
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        project = scenario_root / "project"
        palace = scenario_root / "palace"
        project.mkdir(parents=True)
        (project / "app.py").write_text(
            '"""Read-failure fixture with enough source for one mined drawer."""\n\n'
            "def preserve_read_state(value: int) -> int:\n"
            '    """Return a stable value used by the installed read scenario."""\n'
            "    return value + 1\n",
            encoding="utf-8",
        )

        for step, args, success_marker in (
            ("init", ["init", str(project), "--skip-model-download"], "Config saved:"),
            ("mine", ["--palace", str(palace), "mine", str(project)], "Drawers filed:"),
        ):
            failed = require_success(step, run(args), success_marker)
            if failed is not None:
                return failed

        baseline, failed = health_tuple("baseline health")
        if failed is not None:
            return failed

        invalid_range = run(
            ["--palace", str(palace), "read", "app.py", "--start", "10", "--end", "1"]
        )
        failed = require_failure_output(
            "invalid range",
            invalid_range,
            ("Invalid range:", "start (10) must be <= end (1)", "Next:"),
        )
        if failed is not None:
            return failed

        missing_palace = scenario_root / "does-not-exist"
        missing = run(
            [
                "--palace",
                str(missing_palace),
                "read",
                "app.py",
                "--start",
                "1",
                "--end",
                "1",
            ]
        )
        failed = require_failure_output(
            "missing palace",
            missing,
            ("No palace found at", str(missing_palace), "Next:"),
        )
        if failed is not None:
            return failed
        if missing_palace.exists() or missing_palace.is_symlink():
            return failure("missing-palace read created the supplied palace path")

        current, failed = health_tuple("final health")
        if failed is not None:
            return failed
        if current != baseline:
            return failure("read failures changed palace health state")
        if boundary_snapshot() != repository_boundary:
            return failure("read-failure scenario changed a repository-root artifact")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"read-failure evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_read_failures",
        INSTALLED_READ_FAILURES_COMMAND,
        "pass",
        "invalid-range and missing-palace reads preserved output, health, and filesystem state",
    )


def _run_installed_convo_full_replace_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove incremental conversation mining and destructive full replacement."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        bounded_detail = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")
        return _make_row(
            "installed_golden_convo_full_replace",
            INSTALLED_CONVO_FULL_REPLACE_COMMAND,
            "fail",
            f"{bounded_detail}; {recovery}",
        )

    def run(args: list[str]):
        return _run_installed_cli(run_subprocess, command_prefix, args, env, neutral_cwd)

    def require_mine_success(step: str, result, markers: tuple[str, ...]) -> dict | None:
        if (
            result.returncode != 0
            or not result.stdout
            or result.stderr
            or not _installed_output_is_clean(result)
            or any(marker not in result.stdout for marker in markers)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        return None

    def require_export_success(
        step: str, result, palace: Path, export_path: Path, expected_rows: int
    ) -> dict | None:
        expected_stderr = (
            f"  Exporting from: {palace}\n"
            f"  Exported {expected_rows} drawers, 0 KG triples → {export_path}\n"
        )
        if (
            result.returncode != 0
            or result.stdout != ""
            or result.stderr != expected_stderr
            or not _installed_output_is_clean(result)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        return None

    def read_drawers(step: str, export_path: Path) -> tuple[list[dict] | None, dict | None]:
        try:
            lines = export_path.read_text(encoding="utf-8").splitlines()
            records = [json.loads(line) for line in lines]
        except (json.JSONDecodeError, OSError, TypeError, UnicodeError) as exc:
            return None, failure(f"{step} export could not be parsed: {exc}")
        if not records or any(not isinstance(record, dict) for record in records):
            return None, failure(f"{step} export has the wrong top-level shape")
        header = records[0]
        drawers = records[1:]
        if (
            header.get("type") != "export_header"
            or type(header.get("drawer_count")) is not int
            or type(header.get("kg_count")) is not int
            or header["drawer_count"] != len(drawers)
            or header["kg_count"] != 0
            or any(record.get("type") != "drawer" for record in drawers)
        ):
            return None, failure(f"{step} export has an invalid record sequence or counts")
        if any(
            not isinstance(record.get("id"), str)
            or not record["id"]
            or not isinstance(record.get("text"), str)
            or not isinstance(record.get("source_file"), str)
            or not isinstance(record.get("wing"), str)
            or type(record.get("chunk_index")) is not int
            or record["chunk_index"] < 0
            for record in drawers
        ):
            return None, failure(f"{step} export has a malformed drawer record")
        ids = [record["id"] for record in drawers]
        chunk_indexes = [record["chunk_index"] for record in drawers]
        if len(set(ids)) != len(ids) or len(set(chunk_indexes)) != len(chunk_indexes):
            return None, failure(f"{step} export has duplicate drawer metadata")
        return sorted(drawers, key=lambda record: record["chunk_index"]), None

    def require_health(step: str, palace: Path, expected_rows: int) -> dict | None:
        result = run(["--palace", str(palace), "health", "--json"])
        if (
            result.returncode != 0
            or not result.stdout
            or result.stderr
            or not _installed_output_is_clean(result)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            return failure(f"{step} returned malformed health JSON: {exc}")
        storage = value.get("storage") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("ok") is not True
            or type(value.get("total_rows")) is not int
            or type(value.get("current_version")) is not int
            or not isinstance(storage, dict)
            or type(storage.get("version_count")) is not int
        ):
            return failure(f"{step} returned malformed health JSON")
        if value["total_rows"] != expected_rows:
            return failure(f"{step} reported {value['total_rows']} rows; expected {expected_rows}")
        return None

    def boundary_snapshot() -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name
                for path in repository_root.iterdir()
                if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
            )
        )

    try:
        repository_boundary = boundary_snapshot()
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        source_dir = scenario_root / "conversations"
        source_dir.mkdir(parents=True)
        source = source_dir / "chat.txt"
        palace = scenario_root / "palace"
        exports = {
            name: scenario_root / f"{name}.jsonl"
            for name in ("first", "retry", "changed", "shorter")
        }
        source.write_text(
            "> Original question one?\nOriginal answer one has enough content.\n\n"
            "> Original question two?\nOriginal answer two has enough content.\n\n"
            "> Stale tail question?\nStale tail answer must be removed.\n",
            encoding="utf-8",
        )
        mine_args = [
            "--palace",
            str(palace),
            "mine",
            str(source_dir),
            "--mode",
            "convos",
            "--wing",
            "conversations",
            "--no-spellcheck",
        ]
        states = (
            (
                "first",
                mine_args,
                (
                    "Files processed: 1",
                    "Files skipped (already filed): 0",
                    "Drawers filed: 3",
                ),
                3,
            ),
            (
                "retry",
                mine_args,
                (
                    "Files processed: 0",
                    "Files skipped (already filed): 1",
                    "Drawers filed: 0",
                ),
                3,
            ),
        )
        parsed: dict[str, list[dict]] = {}
        for name, args, markers, expected_rows in states:
            failed = require_mine_success(name, run(args), markers)
            if failed is not None:
                return failed
            export_result = run(["--palace", str(palace), "export", "--out", str(exports[name])])
            failed = require_export_success(
                f"{name} export",
                export_result,
                palace,
                exports[name],
                expected_rows,
            )
            if failed is not None:
                return failed
            parsed[name], failed = read_drawers(name, exports[name])
            if failed is not None:
                return failed
            if len(parsed[name]) != expected_rows:
                return failure(f"{name} export contained {len(parsed[name])} drawers")
            failed = require_health(f"{name} health", palace, expected_rows)
            if failed is not None:
                return failed
        expected_initial = [
            "> Original question one?\nOriginal answer one has enough content.",
            "> Original question two?\nOriginal answer two has enough content.",
            "> Stale tail question?\nStale tail answer must be removed.",
        ]
        if [record["text"] for record in parsed["first"]] != expected_initial or any(
            Path(record["source_file"]).resolve() != source.resolve()
            or record["wing"] != "conversations"
            for record in parsed["first"]
        ):
            return failure("initial export has wrong ordered text or provenance")
        if parsed["retry"] != parsed["first"]:
            return failure("incremental retry changed, duplicated, or reordered drawer records")
        initial_ids = [record["id"] for record in parsed["first"]]

        source.write_text(
            "> Changed question one?\nChanged sentinel 84017 is authoritative.\n\n"
            "> Changed question two?\nChanged answer two remains current.\n\n"
            "> Changed question three?\nChanged answer three replaces the old tail.\n",
            encoding="utf-8",
        )
        failed = require_mine_success(
            "changed full replacement",
            run([*mine_args, "--full"]),
            (
                "Mode:    FULL REBUILD (--full)",
                "Files processed: 1",
                "Files skipped (already filed): 0",
                "Drawers filed: 3",
            ),
        )
        if failed is not None:
            return failed
        changed_export_result = run(
            ["--palace", str(palace), "export", "--out", str(exports["changed"])]
        )
        failed = require_export_success(
            "changed export",
            changed_export_result,
            palace,
            exports["changed"],
            3,
        )
        if failed is not None:
            return failed
        changed, failed = read_drawers("changed", exports["changed"])
        if failed is not None:
            return failed
        expected_changed = [
            "> Changed question one?\nChanged sentinel 84017 is authoritative.",
            "> Changed question two?\nChanged answer two remains current.",
            "> Changed question three?\nChanged answer three replaces the old tail.",
        ]
        if (
            [record["id"] for record in changed] != initial_ids
            or [record["text"] for record in changed] != expected_changed
            or any(
                Path(record["source_file"]).resolve() != source.resolve()
                or record["wing"] != "conversations"
                for record in changed
            )
        ):
            return failure("changed full replacement has wrong ordered text or provenance")
        failed = require_health("changed health", palace, 3)
        if failed is not None:
            return failed

        source.write_text(
            "> Short replacement?\nFinal sentinel 99173 is the only remaining exchange.\n",
            encoding="utf-8",
        )
        failed = require_mine_success(
            "shorter full replacement",
            run([*mine_args, "--full"]),
            (
                "Mode:    FULL REBUILD (--full)",
                "Files processed: 1",
                "Files skipped (already filed): 0",
                "Drawers filed: 1",
            ),
        )
        if failed is not None:
            return failed
        shorter_export_result = run(
            ["--palace", str(palace), "export", "--out", str(exports["shorter"])]
        )
        failed = require_export_success(
            "shorter export",
            shorter_export_result,
            palace,
            exports["shorter"],
            1,
        )
        if failed is not None:
            return failed
        shorter, failed = read_drawers("shorter", exports["shorter"])
        if failed is not None:
            return failed
        expected_shorter = [
            "> Short replacement?\nFinal sentinel 99173 is the only remaining exchange."
        ]
        if (
            [record["id"] for record in shorter] != initial_ids[:1]
            or [record["text"] for record in shorter] != expected_shorter
            or any(
                Path(record["source_file"]).resolve() != source.resolve()
                or record["wing"] != "conversations"
                for record in shorter
            )
        ):
            return failure("shorter full replacement has stale content or wrong provenance")
        failed = require_health("shorter health", palace, 1)
        if failed is not None:
            return failed
        if boundary_snapshot() != repository_boundary:
            return failure("conversation scenario changed a repository-root artifact")
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"conversation full-replacement evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_convo_full_replace",
        INSTALLED_CONVO_FULL_REPLACE_COMMAND,
        "pass",
        "incremental retry and two full replacements preserved exact exported conversation state",
    )


def _run_installed_cleanup_poststate_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove default cleanup leaves exact, repeatable storage post-state."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        return _make_row(
            "installed_golden_cleanup_poststate",
            INSTALLED_CLEANUP_POSTSTATE_COMMAND,
            "fail",
            f"{detail}; {recovery}",
        )

    def run(args: list[str]):
        return _run_installed_cli(run_subprocess, command_prefix, args, env, neutral_cwd)

    def require_success(step: str, result, success_marker: str | None = None) -> dict | None:
        if (
            result.returncode != 0
            or not result.stdout
            or result.stderr
            or not _installed_output_is_clean(result)
            or (success_marker is not None and success_marker not in result.stdout)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        return None

    def parse_object(step: str, result) -> tuple[dict | None, dict | None]:
        failed = require_success(step, result)
        if failed is not None:
            return None, failed
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            return None, failure(f"{step} returned a non-object JSON value")
        return value, None

    try:
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        project = scenario_root / "project"
        palace = scenario_root / "palace"
        project.mkdir(parents=True)
        (project / "app.py").write_text(
            '"""Cleanup post-state fixture with enough source for one mined drawer."""\n\n'
            "def preserve_cleanup_state(value: int) -> int:\n"
            '    """Return a stable value used by the installed cleanup scenario."""\n'
            "    return value + 1\n",
            encoding="utf-8",
        )

        for step, args, success_marker in (
            ("init", ["init", str(project), "--skip-model-download"], "Config saved:"),
            ("mine", ["--palace", str(palace), "mine", str(project)], "Drawers filed:"),
        ):
            failed = require_success(step, run(args), success_marker)
            if failed is not None:
                return failed

        cleanup_results = []
        health_results = []
        for attempt in ("first", "second"):
            cleanup, failed = parse_object(
                f"{attempt} cleanup",
                run(["--palace", str(palace), "cleanup", "--json"]),
            )
            if failed is not None:
                return failed
            health, failed = parse_object(
                f"{attempt} health",
                run(["--palace", str(palace), "health", "--json"]),
            )
            if failed is not None:
                return failed
            cleanup_results.append(cleanup)
            health_results.append(health)

        integer_cleanup_keys = (
            "rows_before",
            "rows_after",
            "version_count_before",
            "version_count_after",
            "estimated_reclaimable_bytes_before",
            "estimated_reclaimable_bytes_after",
            "freed_bytes",
        )
        for cleanup, health in zip(cleanup_results, health_results, strict=True):
            storage = health.get("storage")
            schema_ok = (
                cleanup.get("ok") is True
                and all(type(cleanup.get(key)) is int for key in integer_cleanup_keys)
                and type(health.get("total_rows")) is int
                and isinstance(storage, dict)
                and type(storage.get("version_count")) is int
                and type(storage.get("estimated_reclaimable_bytes")) is int
            )
            if not schema_ok:
                return failure("cleanup or health JSON had missing keys or wrong value types")
            if not (
                cleanup["rows_before"] == cleanup["rows_after"] == health["total_rows"]
                and cleanup["version_count_after"] == storage["version_count"]
                and cleanup["estimated_reclaimable_bytes_after"]
                == storage["estimated_reclaimable_bytes"]
            ):
                return failure("cleanup and health JSON disagreed on storage post-state")

        first, second = cleanup_results
        repeated_ok = (
            first["freed_bytes"] == second["freed_bytes"] == 0
            and first["version_count_before"] == first["version_count_after"]
            and second["version_count_before"] == second["version_count_after"]
            and first["estimated_reclaimable_bytes_before"]
            == first["estimated_reclaimable_bytes_after"]
            and second["estimated_reclaimable_bytes_before"]
            == second["estimated_reclaimable_bytes_after"]
            and first == second
            and health_results[0]["storage"] == health_results[1]["storage"]
        )
        if not repeated_ok:
            return failure("repeated cleanup or health post-state was not identical")

        leaked = [
            path.name
            for path in repository_root.iterdir()
            if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
        ]
        if leaked:
            return failure("cleanup scenario created a repository-root artifact")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"cleanup post-state evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_cleanup_poststate",
        INSTALLED_CLEANUP_POSTSTATE_COMMAND,
        "pass",
        "default and repeated cleanup matched health and left exact disposable post-state",
    )


def _run_installed_rollback_no_candidate_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    run_subprocess=subprocess.run,
) -> dict:
    """Prove rollback without a candidate is ordered, bounded, and non-mutating."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        return _make_row(
            "installed_golden_rollback_no_candidate",
            INSTALLED_ROLLBACK_NO_CANDIDATE_COMMAND,
            "fail",
            f"{detail}; {recovery}",
        )

    def run(args: list[str], *, merge_stderr: bool = False):
        return _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            env,
            neutral_cwd,
            merge_stderr=merge_stderr,
        )

    def require_success(step: str, result, success_marker: str | None = None) -> dict | None:
        if (
            result.returncode != 0
            or not result.stdout
            or result.stderr
            or not _installed_output_is_clean(result)
            or (success_marker is not None and success_marker not in result.stdout)
        ):
            detail = result.stderr or result.stdout or f"exit {result.returncode}"
            return failure(f"{step} failed: {detail}")
        return None

    def health_tuple(step: str) -> tuple[tuple[int, int, int] | None, dict | None]:
        result = run(["--palace", str(palace), "health", "--json"])
        failed = require_success(step, result)
        if failed is not None:
            return None, failed
        value = json.loads(result.stdout)
        storage = value.get("storage") if isinstance(value, dict) else None
        if not (
            isinstance(value, dict)
            and type(value.get("total_rows")) is int
            and type(value.get("current_version")) is int
            and isinstance(storage, dict)
            and type(storage.get("version_count")) is int
        ):
            return None, failure(f"{step} returned malformed health JSON")
        return (value["total_rows"], value["current_version"], storage["version_count"]), None

    try:
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        project = scenario_root / "project"
        palace = scenario_root / "palace"
        project.mkdir(parents=True)
        (project / "app.py").write_text(
            '"""Rollback no-candidate fixture with one stable mined drawer."""\n\n'
            "def preserve_rollback_state(value: int) -> int:\n"
            '    """Return the value used by the installed rollback scenario."""\n'
            "    return value + 1\n",
            encoding="utf-8",
        )

        for step, args, success_marker in (
            ("init", ["init", str(project), "--skip-model-download"], "Config saved:"),
            ("mine", ["--palace", str(palace), "mine", str(project)], "Drawers filed:"),
        ):
            failed = require_success(step, run(args), success_marker)
            if failed is not None:
                return failed

        cleanup = run(["--palace", str(palace), "cleanup", "--unsafe-now", "--json"])
        failed = require_success("cleanup", cleanup)
        if failed is not None:
            return failed
        cleanup_value = json.loads(cleanup.stdout)
        if not (
            isinstance(cleanup_value, dict)
            and cleanup_value.get("ok") is True
            and type(cleanup_value.get("version_count_after")) is int
            and cleanup_value["version_count_after"] == 1
        ):
            return failure("cleanup did not leave exactly one rollback version")

        baseline, failed = health_tuple("baseline health")
        if failed is not None:
            return failed

        cases = (
            ("dry-run separate", True, False),
            ("dry-run merged", True, True),
            ("live separate", False, False),
            ("live merged", False, True),
        )
        separator = "=" * 55
        for label, dry_run, merge_stderr in cases:
            args = ["--palace", str(palace), "repair", "--rollback"]
            if dry_run:
                args.append("--dry-run")
            result = run(args, merge_stderr=merge_stderr)
            active_output = result.stdout if dry_run or merge_stderr else result.stderr
            inactive_output = "" if merge_stderr else (result.stderr if dry_run else result.stdout)
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
            ordered_markers = (
                "MemPalace Repair — Version Rollback",
                "Mode: dry-run" if dry_run else "Mode: live",
                "No candidate version:",
                mutation,
                exit_meaning,
                "Try: mempalace-code repair (full rebuild)",
            )
            positions = [active_output.find(marker) for marker in ordered_markers]
            output_ok = (
                result.returncode == (0 if dry_run else 1)
                and bool(active_output)
                and inactive_output == ""
                and _installed_output_is_clean(result)
                and all(position >= 0 for position in positions)
                and positions == sorted(positions)
                and active_output.count(separator) == 3
                and re.search(rf"{separator}\s*{separator}", active_output) is None
                and active_output.rstrip().endswith(separator)
                and all(
                    marker not in active_output
                    for marker in ("Extracting drawers", "Backing up to", "Rebuilding palace")
                )
            )
            if not output_ok:
                detail = result.stderr or result.stdout or f"exit {result.returncode}"
                return failure(f"{label} output contract failed: {detail}")
            current, failed = health_tuple(f"{label} health")
            if failed is not None:
                return failed
            if current != baseline:
                return failure(f"{label} changed palace health state")

        leaked = [
            path.name
            for path in repository_root.iterdir()
            if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
        ]
        if leaked:
            return failure("rollback scenario created a repository-root artifact")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"rollback no-candidate evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_rollback_no_candidate",
        INSTALLED_ROLLBACK_NO_CANDIDATE_COMMAND,
        "pass",
        "four rollback no-candidate modes preserved output, health, and disposable state",
    )


def _run_installed_watcher_signal_cleanup_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    supported_signals: tuple[int, ...] | None = None,
    network_attempts: Path | None = None,
    run_subprocess=subprocess.run,
    popen=subprocess.Popen,
) -> dict:
    """Prove installed watchers release durable ownership for supported stop signals."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"
    ready_timeout = 30
    stop_timeout = 30
    signals = (
        (signal.SIGTERM,) + ((signal.SIGHUP,) if hasattr(signal, "SIGHUP") else ())
        if supported_signals is None
        else supported_signals
    )

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
        return _make_row(
            "installed_golden_watcher_signals",
            INSTALLED_WATCHER_SIGNALS_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    def artifact_snapshot() -> tuple[tuple[str, tuple], ...]:
        artifacts = sorted(
            path
            for path in repository_root.iterdir()
            if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
        )
        return tuple((path.name, _semantic_tree_snapshot(path)) for path in artifacts)

    def run(args: list[str]):
        return _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            env,
            neutral_cwd,
        )

    def read_output(stream, lines: queue.Queue[str]) -> None:
        for line in iter(stream.readline, ""):
            lines.put(line)
        stream.close()

    def drain(lines: queue.Queue[str] | None, output: list[str]) -> None:
        if lines is None:
            return
        while True:
            try:
                output.append(lines.get_nowait())
            except queue.Empty:
                return

    def wait_for_output(
        process,
        lines: queue.Queue[str],
        output: list[str],
        needle: str,
    ) -> None:
        deadline = time.monotonic() + ready_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                drain(lines, output)
                raise RuntimeError(
                    f"watcher exited {process.returncode} before {needle}: {''.join(output)}"
                )
            try:
                line = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            output.append(line)
            if needle in line:
                return
        drain(lines, output)
        raise TimeoutError(f"watcher did not emit {needle}: {''.join(output)}")

    def stop_process(process, reader, lines, output: list[str]) -> None:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=stop_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=stop_timeout)
        if reader is not None:
            reader.join(timeout=5)
        drain(lines, output)

    def launch(project: Path, palace: Path):
        process = popen(
            [*command_prefix, "--palace", str(palace), "watch", str(project), "--on-save"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env,
            cwd=str(neutral_cwd),
            text=True,
        )
        if process.stdout is None:
            stop_process(process, None, None, [])
            raise RuntimeError("watcher stdout pipe is unavailable")
        lines: queue.Queue[str] = queue.Queue()
        reader = threading.Thread(target=read_output, args=(process.stdout, lines), daemon=True)
        reader.start()
        output: list[str] = []
        return process, reader, lines, output

    try:
        if not signals or signal.SIGTERM not in signals:
            return failure("SIGTERM is missing from the supported signal matrix")
        repository_boundary = artifact_snapshot()
        scenario_root.mkdir(parents=True, exist_ok=True)
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        owners_path = Path(env["HOME"]) / ".mempalace" / "operation.lock.owners.json"
        signal_names: list[str] = []

        for shutdown_signal in signals:
            signal_name = signal.Signals(shutdown_signal).name
            signal_names.append(signal_name)
            case_root = scenario_root / signal_name.lower()
            project = _write_fixture_project(case_root / "project")
            palace = case_root / "palace"

            init = run(["init", str(project), "--skip-model-download"])
            if (
                init.returncode != 0
                or "Config saved:" not in (init.stdout or "")
                or not _installed_output_is_clean(init)
            ):
                return failure(f"{signal_name} init failed: {init.stderr or init.stdout}")
            mine = run(["--palace", str(palace), "mine", str(project)])
            if (
                mine.returncode != 0
                or "Drawers filed:" not in (mine.stdout or "")
                or not _installed_output_is_clean(mine)
            ):
                return failure(f"{signal_name} mine failed: {mine.stderr or mine.stdout}")

            watcher = watcher_reader = watcher_lines = None
            watcher_output: list[str] = []
            watcher_tokens: set[str] = set()
            try:
                watcher, watcher_reader, watcher_lines, watcher_output = launch(project, palace)
                wait_for_output(watcher, watcher_lines, watcher_output, "state=watch-ready")
                owners_before = json.loads(owners_path.read_text(encoding="utf-8"))
                watcher_tokens = {
                    token
                    for token, owner in owners_before.items()
                    if owner.get("pid") == watcher.pid
                }
                if not watcher_tokens:
                    raise RuntimeError(f"{signal_name} watcher PID missing from owner descriptor")
                watcher.send_signal(shutdown_signal)
                watcher.wait(timeout=stop_timeout)
            finally:
                stop_process(watcher, watcher_reader, watcher_lines, watcher_output)

            watcher_summary = "".join(watcher_output)
            if (
                watcher.returncode != 0
                or "Watch stopped after" not in watcher_summary
                or any(marker in watcher_summary for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT)
            ):
                return failure(
                    f"{signal_name} watcher did not stop cleanly: {''.join(watcher_output)}"
                )

            # Keep this read before another lock acquisition, which can prune stale owners.
            owners_after = json.loads(owners_path.read_text(encoding="utf-8"))
            if not watcher_tokens.isdisjoint(owners_after) or any(
                owner.get("pid") == watcher.pid for owner in owners_after.values()
            ):
                return failure(f"{signal_name} watcher ownership survived clean exit")

            lock_python = (
                str(Path(command_prefix[0]).resolve().with_name("python"))
                if len(command_prefix) == 1
                else command_prefix[0]
            )
            writer = _run_golden_subprocess(
                run_subprocess,
                [
                    lock_python,
                    "-c",
                    "from mempalace_code.operation_lock import OperationLock; "
                    "lease = OperationLock.default().acquire_exclusive('signal-test'); "
                    "lease.release(); print('exclusive-released')",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(neutral_cwd),
                timeout=DEFAULT_TIMEOUT,
            )
            if (
                writer.returncode != 0
                or (writer.stdout or "").strip() != "exclusive-released"
                or not _installed_output_is_clean(writer)
            ):
                return failure(
                    f"{signal_name} exclusive writer failed: {writer.stderr or writer.stdout}"
                )

            replacement = replacement_reader = replacement_lines = None
            replacement_output: list[str] = []
            replacement_tokens: set[str] = set()
            try:
                replacement, replacement_reader, replacement_lines, replacement_output = launch(
                    project, palace
                )
                wait_for_output(
                    replacement, replacement_lines, replacement_output, "state=watch-ready"
                )
                replacement_owners = json.loads(owners_path.read_text(encoding="utf-8"))
                replacement_tokens = {
                    token
                    for token, owner in replacement_owners.items()
                    if owner.get("pid") == replacement.pid
                }
                if not replacement_tokens:
                    raise RuntimeError(
                        f"{signal_name} replacement PID missing from owner descriptor"
                    )
                replacement.send_signal(shutdown_signal)
                replacement.wait(timeout=stop_timeout)
            finally:
                stop_process(
                    replacement,
                    replacement_reader,
                    replacement_lines,
                    replacement_output,
                )

            replacement_summary = "".join(replacement_output)
            if (
                replacement.returncode != 0
                or "Watch stopped after" not in replacement_summary
                or any(
                    marker in replacement_summary for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT
                )
            ):
                return failure(f"{signal_name} replacement watcher did not stop cleanly")
            owners_after_replacement = json.loads(owners_path.read_text(encoding="utf-8"))
            if not replacement_tokens.isdisjoint(owners_after_replacement) or any(
                owner.get("pid") == replacement.pid for owner in owners_after_replacement.values()
            ):
                return failure(f"{signal_name} replacement ownership survived clean exit")

            health = run(["--palace", str(palace), "health", "--json"])
            health_payload = json.loads(health.stdout or "")
            if (
                health.returncode != 0
                or health_payload.get("ok") is not True
                or health_payload.get("total_rows", 0) <= 0
                or not isinstance(health_payload.get("storage"), dict)
                or not _installed_output_is_clean(health)
            ):
                return failure(f"{signal_name} storage health failed")
            search = run(
                [
                    "--palace",
                    str(palace),
                    "search",
                    "xylophonic_glyph_9182",
                    "--results",
                    "10",
                ]
            )
            if (
                search.returncode != 0
                or any(
                    marker not in (search.stdout or "")
                    for marker in ("Results for:", "xylophonic_glyph_9182", "app.py")
                )
                or not _installed_output_is_clean(search)
            ):
                return failure(
                    f"{signal_name} semantic search failed: {search.stderr or search.stdout}"
                )

        if (
            network_attempts is not None
            and network_attempts.exists()
            and network_attempts.read_text(encoding="utf-8").strip()
        ):
            return failure("watcher signal scenario attempted network access")
        if artifact_snapshot() != repository_boundary:
            return failure("watcher signal scenario changed a repository-root artifact")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TimeoutError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        return failure(f"watcher signal evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_watcher_signals",
        INSTALLED_WATCHER_SIGNALS_COMMAND,
        "pass",
        f"{', '.join(signal_names)} released watcher and replacement leases with healthy search",
    )


def _run_installed_workflow_happy_path_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    network_attempts: Path | None = None,
    run_subprocess=subprocess.run,
    popen=subprocess.Popen,
) -> dict:
    """Run the composite CLI workflow through one supplied console."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(INSTALLED_GOLDEN_COMMAND, "<installed-golden-command>")[:1200]
        return _make_row(
            "installed_golden_workflow_happy_path",
            INSTALLED_WORKFLOW_HAPPY_PATH_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    def artifact_snapshot() -> tuple[tuple[str, tuple], ...]:
        artifacts = sorted(
            path
            for path in repository_root.iterdir()
            if path.name.endswith(".tar.gz") or path.name in (".mempalace", "backups")
        )
        return tuple((path.name, _semantic_tree_snapshot(path)) for path in artifacts)

    def run(args: list[str]):
        return _run_installed_cli(run_subprocess, command_prefix, args, env, neutral_cwd)

    def require_ok(result, label: str, *markers: str) -> str:
        stdout = result.stdout or ""
        if (
            result.returncode != 0
            or not _installed_output_is_clean(result)
            or any(marker not in stdout for marker in markers)
        ):
            raise RuntimeError(f"{label} failed: {result.stderr or stdout or result.returncode}")
        return stdout

    def directory_bytes(path: Path) -> int:
        return (
            sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
            if path.exists()
            else 0
        )

    def palace_bytes(palace: Path) -> int:
        return directory_bytes(palace) + directory_bytes(palace.parent / "backups")

    def backup_archives(palace: Path) -> set[Path]:
        backups = palace.parent / "backups"
        return set(backups.glob("*.tar.gz")) if backups.exists() else set()

    def prove_roundtrip(label: str, palace: Path) -> None:
        search = run(
            ["--palace", str(palace), "search", "xylophonic_glyph_9182", "--results", "10"]
        )
        search_stdout = require_ok(search, f"{label} search", "Results for:", "app.py")
        if "xylophonic_glyph_9182" not in search_stdout:
            raise RuntimeError(f"{label} search lost the unique marker")
        read = run(
            [
                "--palace",
                str(palace),
                "read",
                "app.py",
                "--start",
                "1",
                "--end",
                str(len(_PY_LINES)),
            ]
        )
        read_stdout = require_ok(read, f"{label} read")
        for snippet in (
            "def compute_xylophonic_glyph_9182(value):",
            "xylophonic_glyph_9182",
            "return value * 2",
            "def helper_offset(value):",
            "return value + 1",
        ):
            if snippet not in read_stdout:
                raise RuntimeError(f"{label} read lost expected fixture content")

    def read_output(stream, lines: queue.Queue[str]) -> None:
        for line in iter(stream.readline, ""):
            lines.put(line)
        stream.close()

    def drain(lines: queue.Queue[str] | None, output: list[str]) -> None:
        if lines is None:
            return
        while True:
            try:
                output.append(lines.get_nowait())
            except queue.Empty:
                return

    def wait_for_output(
        process, lines: queue.Queue[str], output: list[str], needle: str, timeout: float
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                drain(lines, output)
                raise RuntimeError(f"watcher exited before {needle}: {''.join(output)}")
            try:
                line = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            output.append(line)
            if needle in line:
                return True
        drain(lines, output)
        return False

    def stop_watcher(process, reader, lines, output: list[str]) -> None:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=30)
        if reader is not None:
            reader.join(timeout=5)
            if reader.is_alive():
                raise RuntimeError("watcher output reader did not stop")
        drain(lines, output)

    watcher = watcher_reader = watcher_lines = None
    watcher_output: list[str] = []
    try:
        repository_boundary = artifact_snapshot()
        scenario_root.mkdir(parents=True, exist_ok=True)
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        project = _write_fixture_project(scenario_root / "project")
        palace_a = scenario_root / "palace-a"
        palace_b = scenario_root / "palace-b"
        palace_c = scenario_root / "palace-c"
        export_file = scenario_root / "export.jsonl"
        backup_archive = scenario_root / "backup.tar.gz"

        init = run(["init", str(project), "--skip-model-download"])
        require_ok(init, "init", "Config saved:")
        if not (project / "mempalace.yaml").is_file():
            raise RuntimeError("init did not create mempalace.yaml")

        mine = run(["--palace", str(palace_a), "mine", str(project)])
        mine_stdout = require_ok(mine, "mine", "Drawers filed:")
        drawers_filed = int(
            next(line for line in mine_stdout.splitlines() if "Drawers filed:" in line)
            .split(":", 1)[1]
            .strip()
        )
        if drawers_filed <= 0:
            raise RuntimeError("mine filed no drawers")

        compress = run(["--palace", str(palace_a), "compress", "--dry-run"])
        compress_stdout = require_ok(
            compress, "compress dry-run", "Total:", "dry run -- nothing stored"
        )
        drawer_rows = [
            (int(match.group(1).replace(",", "")), int(match.group(2).replace(",", "")))
            for match in re.finditer(r"(?m)^    ([\d,]+)t -> ([\d,]+)t \(", compress_stdout)
        ]
        total_match = re.search(r"(?m)^  Total: ([\d,]+)t -> ([\d,]+)t \(", compress_stdout)
        if len(drawer_rows) < 2 or total_match is None:
            raise RuntimeError("compress dry-run omitted drawer or total rows")
        displayed_total = tuple(int(value.replace(",", "")) for value in total_match.groups())
        summed_total = (
            sum(original for original, _compressed in drawer_rows),
            sum(compressed for _original, compressed in drawer_rows),
        )
        if displayed_total != summed_total:
            raise RuntimeError("compress Total did not equal displayed drawer rows")

        archives_before = backup_archives(palace_a)
        bytes_before = palace_bytes(palace_a)
        no_op = run(["--palace", str(palace_a), "mine", str(project)])
        require_ok(no_op, "no-op mine", "no changes detected")
        if backup_archives(palace_a) != archives_before or palace_bytes(palace_a) != bytes_before:
            raise RuntimeError("no-op mine changed palace or backup storage")

        status = run(["--palace", str(palace_a), "status"])
        require_ok(status, "status", "MemPalace Status", "WING: project")
        prove_roundtrip("mined", palace_a)

        exported = run(["--palace", str(palace_a), "export", "--out", str(export_file)])
        if (
            exported.returncode != 0
            or "Exported" not in (exported.stderr or "")
            or not _installed_output_is_clean(exported)
            or not export_file.is_file()
            or export_file.stat().st_size <= 0
        ):
            raise RuntimeError(f"export failed: {exported.stderr or exported.stdout}")

        imported = run(["--palace", str(palace_b), "import", str(export_file)])
        imported_stdout = require_ok(imported, "import", "Imported drawers:")
        imported_count = int(
            next(line for line in imported_stdout.splitlines() if "Imported drawers:" in line)
            .split(":", 1)[1]
            .strip()
        )
        if imported_count <= 0:
            raise RuntimeError("import restored no drawers")
        prove_roundtrip("imported", palace_b)

        backup = run(["--palace", str(palace_a), "backup", "--out", str(backup_archive)])
        require_ok(backup, "backup", "Backed up", "Archive:")
        if not backup_archive.is_file() or backup_archive.stat().st_size <= 0:
            raise RuntimeError("backup did not create a non-empty archive")
        restore = run(["--palace", str(palace_c), "restore", str(backup_archive)])
        require_ok(restore, "restore", "Restored palace to:")
        prove_roundtrip("restored", palace_c)
        health = run(["--palace", str(palace_c), "health", "--json"])
        health_payload = json.loads(require_ok(health, "restored health"))
        if health_payload.get("ok") is not True:
            raise RuntimeError("restored palace health was not ok")

        unsafe_archive = scenario_root / "nonbackup.tar.gz"
        traversal_source = scenario_root / "traversal-source.txt"
        traversal_source.write_bytes(b"escaped")
        with tarfile.open(unsafe_archive, "w:gz") as archive:
            archive.add(traversal_source, arcname="../../mempalace-direct-escaped.txt")
        rejected_target = scenario_root / "rejected-restore"
        escaped_target = scenario_root.parent / "mempalace-direct-escaped.txt"
        rejected = run(["--palace", str(rejected_target), "restore", str(unsafe_archive)])
        if (
            rejected.returncode == 0
            or not _installed_output_is_clean(rejected)
            or "Restored palace to:" in (rejected.stdout or "")
            or (rejected.stderr or "").count("mempalace-code backup create") != 1
            or rejected_target.exists()
            or escaped_target.exists()
        ):
            raise RuntimeError("unsafe archive restore was not rejected without residue")

        watcher = popen(
            [*command_prefix, "--palace", str(palace_a), "watch", str(project), "--on-save"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env,
            cwd=str(neutral_cwd),
            text=True,
        )
        if watcher.stdout is None:
            raise RuntimeError("watcher stdout pipe is unavailable")
        watcher_lines = queue.Queue()
        watcher_reader = threading.Thread(
            target=read_output, args=(watcher.stdout, watcher_lines), daemon=True
        )
        watcher_reader.start()
        if not wait_for_output(watcher, watcher_lines, watcher_output, "state=watch-ready", 30):
            raise TimeoutError("watcher did not become ready")
        changed_source = project / "app.py"
        expected_cycle = f"[{project.name}: 1 change(s)]"
        for revision, timeout in ((1, 6), (2, 30)):
            changed_source.write_text(
                "\n".join(
                    [
                        *_PY_LINES,
                        "",
                        "def watched_substantive_change(value):",
                        f'    """Substantive watch revision {revision}."""',
                        f"    return value * {revision + 2}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            if wait_for_output(watcher, watcher_lines, watcher_output, expected_cycle, timeout):
                break
        else:
            raise TimeoutError("watcher did not report a re-mine cycle")
        stop_watcher(watcher, watcher_reader, watcher_lines, watcher_output)
        watcher_reader = watcher_lines = None
        watcher_summary = "".join(watcher_output)
        if (
            watcher.returncode != 0
            or "1 re-mine cycle(s), 1 event(s)" not in watcher_summary
            or any(marker in watcher_summary for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT)
        ):
            raise RuntimeError(f"watcher did not stop cleanly: {watcher_summary}")
        if (
            network_attempts is not None
            and network_attempts.exists()
            and network_attempts.read_text(encoding="utf-8").strip()
        ):
            raise RuntimeError("workflow attempted network access")
        if artifact_snapshot() != repository_boundary:
            raise RuntimeError("workflow changed a repository-root artifact")
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        StopIteration,
        subprocess.SubprocessError,
        tarfile.TarError,
        TimeoutError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        try:
            stop_watcher(watcher, watcher_reader, watcher_lines, watcher_output)
        except (OSError, RuntimeError, subprocess.SubprocessError) as cleanup_exc:
            return failure(f"workflow failed and watcher cleanup failed: {cleanup_exc}")
        return failure(f"workflow evidence could not be evaluated: {exc}")

    return _make_row(
        "installed_golden_workflow_happy_path",
        INSTALLED_WORKFLOW_HAPPY_PATH_COMMAND,
        "pass",
        "composite workflow preserved totals, no-op storage, round trips, unsafe restore refusal, health, and one watch cycle",
    )


def _run_installed_non_regular_source_scenario(
    command_prefix: list[str],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    network_attempts: Path | None = None,
    run_subprocess=subprocess.run,
    popen=subprocess.Popen,
) -> dict:
    """Prove every mining entry point rejects supported non-regular source nodes."""
    recovery = f"rerun: {INSTALLED_GOLDEN_COMMAND}"
    ready_timeout = 30
    stop_timeout = 30
    open_sockets: list[tuple[socket.socket, Path]] = []
    disposable_before: dict[Path, tuple[tuple[str, str, int, str], ...]] = {}
    disposable_labels: dict[Path, str] = {}
    repository_before: tuple[tuple[str, str, int, str], ...] | None = None
    lease_artifacts_existed: dict[Path, bool] = {}
    lease_root_existed_before: bool | None = None

    def failure(detail: str) -> dict:
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        bounded = detail.replace(str(repository_root), "<repository-root>")
        bounded = bounded.replace(str(scenario_root), "<scenario-root>")
        for raw_root in {
            str(neutral_cwd),
            *(
                value
                for name, value in env.items()
                if name
                in {
                    "HOME",
                    "USERPROFILE",
                    "XDG_CONFIG_HOME",
                    "XDG_DATA_HOME",
                    "XDG_CACHE_HOME",
                }
            ),
        }:
            bounded = bounded.replace(raw_root, "<disposable-root>")
        bounded = bounded[:1200]
        return _make_row(
            "installed_golden_non_regular_sources",
            INSTALLED_NON_REGULAR_SOURCE_COMMAND,
            "fail",
            f"{bounded}; {recovery}",
        )

    def run(args: list[str]):
        result = _run_installed_cli(
            run_subprocess,
            command_prefix,
            args,
            env,
            neutral_cwd,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not _installed_output_is_clean(result):
            raise RuntimeError("forbidden subprocess output detected")
        if len(output) > INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT:
            raise RuntimeError("subprocess output exceeded the bounded evidence limit")
        return result

    def require_ok(result, label: str, *markers: str) -> tuple[str, str]:
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        if result.returncode != 0 or any(marker not in stdout for marker in markers):
            raise RuntimeError(f"{label} failed: {stderr or stdout or result.returncode}")
        return stdout, stderr

    def create_node(path: Path, kind: str, target: Path) -> None:
        if kind == "symlink":
            path.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(path)
        elif kind == "directory":
            path.mkdir()
        elif kind == "socket":
            node_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                node_socket.bind(str(path))
            except BaseException:
                node_socket.close()
                raise
            open_sockets.append((node_socket, path))
        else:
            raise ValueError(f"unsupported test node kind: {kind}")

    def expected_diagnostic(path: Path, kind: str) -> str:
        return f"{path}: not a regular file ({kind})"

    def assert_diagnostics(stderr: str, nodes: dict[str, Path], label: str) -> None:
        for kind, path in nodes.items():
            diagnostic = expected_diagnostic(path, kind)
            if diagnostic not in stderr:
                raise RuntimeError(f"{label} omitted {kind} diagnostic: {diagnostic}")

    watcher_output_overflow = object()

    def read_output(stream, lines: queue.Queue[object]) -> None:
        collected = 0
        try:
            for line in iter(stream.readline, ""):
                collected += len(line)
                if collected > INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT:
                    lines.put(watcher_output_overflow)
                    return
                lines.put(line)
        finally:
            stream.close()

    def take_output(item: object, output: list[str]) -> str:
        if item is watcher_output_overflow:
            raise RuntimeError("watcher output exceeded the bounded evidence limit")
        if not isinstance(item, str):
            raise RuntimeError("watcher output contained an invalid item")
        output.append(item)
        return item

    def drain(lines: queue.Queue[object] | None, output: list[str]) -> None:
        if lines is None:
            return
        while True:
            try:
                take_output(lines.get_nowait(), output)
            except queue.Empty:
                return

    def wait_for_output(
        process, lines: queue.Queue[object], output: list[str], needle: str
    ) -> None:
        deadline = time.monotonic() + ready_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                drain(lines, output)
                raise RuntimeError(f"watcher exited before {needle}: {''.join(output)}")
            try:
                item = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            line = take_output(item, output)
            if needle in line:
                return
        drain(lines, output)
        raise TimeoutError(f"watcher did not emit {needle}: {''.join(output)}")

    def cleanup_owned_sockets() -> None:
        errors: list[str] = []
        while open_sockets:
            node_socket, path = open_sockets.pop()
            try:
                node_socket.close()
            except OSError as exc:
                errors.append(f"close {path}: {exc}")
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"unlink {path}: {exc}")
        if errors:
            raise RuntimeError("socket cleanup failed: " + "; ".join(errors))

    def cleanup_new_lease_artifacts() -> None:
        for path, existed in lease_artifacts_existed.items():
            if not existed:
                path.unlink(missing_ok=True)
        if lease_root_existed_before is False and lease_artifacts_existed:
            lease_root = next(iter(lease_artifacts_existed)).parent
            try:
                lease_root.rmdir()
            except OSError:
                pass

    def boundary_error() -> str | None:
        if repository_before is not None:
            try:
                if _semantic_tree_snapshot(repository_root) != repository_before:
                    return "scenario changed a repository-root artifact"
            except OSError as exc:
                return f"repository-root snapshot failed: {exc}"
        for root, before in disposable_before.items():
            label = disposable_labels[root]
            try:
                after = _semantic_tree_snapshot(root)
                if after != before:
                    before_by_name = {row[0]: row[1:] for row in before}
                    after_by_name = {row[0]: row[1:] for row in after}
                    changed = sorted(
                        name
                        for name in before_by_name.keys() | after_by_name.keys()
                        if before_by_name.get(name) != after_by_name.get(name)
                    )
                    entries = ", ".join(changed[:4]) if changed else "."
                    return f"scenario changed disposable root {label} at {entries}"
            except OSError as exc:
                return f"disposable-root snapshot failed for {label}: {exc}"
        return None

    def stop_watcher(process, reader, lines, output: list[str]) -> None:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=stop_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=stop_timeout)
        if reader is not None:
            reader.join(timeout=5)
            if reader.is_alive():
                raise RuntimeError("watcher output reader did not stop")
        drain(lines, output)

    if not command_prefix or not Path(command_prefix[0]).is_absolute():
        return failure("non-regular source scenario requires an absolute invoked launcher")

    watcher = watcher_reader = watcher_lines = None
    watcher_output: list[str] = []
    watcher_tokens: set[str] = set()
    try:
        neutral_cwd.mkdir(parents=True, exist_ok=True)
        disposable_roots = _installed_disposable_roots(env, scenario_root, neutral_cwd)
        repository_before = _semantic_tree_snapshot(repository_root)
        disposable_labels = {neutral_cwd: "neutral cwd"}
        for name in (
            "HOME",
            "USERPROFILE",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
        ):
            disposable_labels.setdefault(Path(env[name]), name)
        disposable_before = {
            root: _semantic_tree_snapshot(root)
            for root in disposable_roots
            if root != scenario_root
        }
        lease_root = Path(env["HOME"]) / ".mempalace"
        lease_root_existed_before = lease_root.exists()
        lease_artifacts = (
            lease_root / "operation.lock",
            lease_root / "operation.lock.metadata.lock",
            lease_root / "operation.lock.owners.json",
        )
        lease_artifacts_existed = {path: path.exists() for path in lease_artifacts}
        attempts_before = (
            network_attempts.read_bytes()
            if network_attempts is not None and network_attempts.exists()
            else b""
        )
        if attempts_before:
            raise RuntimeError("scenario inherited a network attempt")

        scenario_root.mkdir(parents=True, exist_ok=True)
        project = _write_fixture_project(scenario_root / "project")
        project_palace = scenario_root / "project-palace"
        convo_palace = scenario_root / "conversation-palace"

        kinds = ["symlink", "directory"]
        if hasattr(os, "mkfifo"):
            kinds.insert(1, "fifo")
        if hasattr(socket, "AF_UNIX"):
            probe_path = scenario_root / "socket-support-probe"
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.bind(str(probe_path))
            except OSError:
                probe.close()
                probe_path.unlink(missing_ok=True)
            else:
                open_sockets.append((probe, probe_path))
                cleanup_owned_sockets()
                kinds.append("socket")

        blocked_project: dict[str, Path] = {}
        legacy_project: dict[str, Path] = {}
        legacy_terms: dict[str, str] = {}
        for index, kind in enumerate(kinds):
            blocked = project / f"blocked_{kind}.py"
            create_node(blocked, kind, project / "app.py")
            blocked_project[kind] = blocked
            legacy = project / f"legacy_{kind}.py"
            term = f"legacy_nonregular_{kind}_742{index}"
            legacy.write_text(
                f'def legacy_{kind}():\n    """{term}"""\n    return {index + 1}\n',
                encoding="utf-8",
            )
            legacy_project[kind] = legacy
            legacy_terms[kind] = term

        init = run(["init", str(project), "--skip-model-download"])
        require_ok(init, "init", "Config saved:")
        mine = run(["--palace", str(project_palace), "mine", str(project)])
        mine_stdout, mine_stderr = require_ok(mine, "project mine", "Drawers filed:")
        if "app.py" not in mine_stdout:
            raise RuntimeError("project mine omitted the regular source control")
        assert_diagnostics(mine_stderr, blocked_project, "project mine")

        search = run(
            [
                "--palace",
                str(project_palace),
                "search",
                "xylophonic_glyph_9182",
                "--results",
                "10",
            ]
        )
        search_stdout, _ = require_ok(search, "regular project search", "app.py")
        if any(path.name in search_stdout for path in blocked_project.values()):
            raise RuntimeError("regular search returned a rejected source alias")

        for kind, path in legacy_project.items():
            path.unlink()
            create_node(path, kind, project / "app.py")
        remine = run(["--palace", str(project_palace), "mine", str(project)])
        remine_stdout, remine_stderr = require_ok(remine, "project remine", "Drawers filed: 0")
        remine_counts = [
            line.strip()
            for line in remine_stdout.splitlines()
            if line.strip().startswith("Drawers filed:")
        ]
        if remine_counts != ["Drawers filed: 0"]:
            raise RuntimeError(f"project remine returned unexpected drawer counts: {remine_counts}")
        assert_diagnostics(remine_stderr, blocked_project, "project remine")
        assert_diagnostics(remine_stderr, legacy_project, "project remine")
        for kind, term in legacy_terms.items():
            stale = run(["--palace", str(project_palace), "search", term, "--results", "10"])
            stale_stdout, _ = require_ok(stale, f"{kind} stale search")
            if legacy_project[kind].name in stale_stdout:
                raise RuntimeError(f"{kind} stale drawer survived remine")
        for path in legacy_project.values():
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()

        mine_all = run(["--palace", str(project_palace), "mine-all", str(scenario_root)])
        _, mine_all_stderr = require_ok(mine_all, "mine-all")
        assert_diagnostics(mine_all_stderr, blocked_project, "mine-all")

        watcher = popen(
            [*command_prefix, "--palace", str(project_palace), "watch", str(project), "--on-save"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env,
            cwd=str(neutral_cwd),
            text=True,
        )
        if watcher.stdout is None:
            raise RuntimeError("watcher stdout pipe is unavailable")
        watcher_lines = queue.Queue()
        watcher_reader = threading.Thread(
            target=read_output, args=(watcher.stdout, watcher_lines), daemon=True
        )
        watcher_reader.start()
        wait_for_output(watcher, watcher_lines, watcher_output, "state=watch-ready")
        owners_path = Path(env["HOME"]) / ".mempalace" / "operation.lock.owners.json"
        if not owners_path.is_file():
            raise RuntimeError("watcher owner descriptor is missing")
        try:
            owners_before = json.loads(owners_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("watcher owner descriptor is malformed") from exc
        if not isinstance(owners_before, dict):
            raise RuntimeError("watcher owner descriptor is malformed")
        watcher_tokens = {
            token
            for token, owner in owners_before.items()
            if isinstance(owner, dict) and owner.get("pid") == watcher.pid
        }
        if not watcher_tokens:
            raise RuntimeError("watcher PID missing from owner descriptor")
        stop_watcher(watcher, watcher_reader, watcher_lines, watcher_output)
        watcher_reader = watcher_lines = None
        watcher_summary = "".join(watcher_output)
        if watcher.returncode != 0 or "Watch stopped after" not in watcher_summary:
            raise RuntimeError(f"watcher did not stop cleanly: {watcher_summary}")
        for kind, path in blocked_project.items():
            if f"{path} ({kind})" not in watcher_summary:
                raise RuntimeError(f"watcher omitted {kind} rejection for {path}")
        if any(marker in watcher_summary for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            raise RuntimeError("forbidden subprocess output detected")
        if len(watcher_summary) > INSTALLED_PATH_CONTRACT_OUTPUT_LIMIT:
            raise RuntimeError("watcher output exceeded the bounded evidence limit")
        if owners_path.exists():
            try:
                owners_after = json.loads(owners_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("watcher owner descriptor is malformed after shutdown") from exc
            if not isinstance(owners_after, dict):
                raise RuntimeError("watcher owner descriptor is malformed after shutdown")
            if not watcher_tokens.isdisjoint(owners_after) or any(
                isinstance(owner, dict) and owner.get("pid") == watcher.pid
                for owner in owners_after.values()
            ):
                raise RuntimeError("watcher ownership survived clean exit")

        convos = scenario_root / "conversations"
        convos.mkdir()
        regular_convo = convos / "chat.txt"
        regular_convo.write_text(
            "\n".join(
                [
                    "> User asks about the direct release guard",
                    "Assistant records regular conversation content for indexing.",
                    "",
                    "> User asks about stale source cleanup",
                    "Assistant confirms bounded filesystem diagnostics and cleanup.",
                    "",
                    "> User asks about watcher shutdown",
                    "Assistant confirms the regular transcript remains searchable.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        blocked_convos: dict[str, Path] = {}
        for kind in kinds:
            path = convos / f"blocked_{kind}.txt"
            create_node(path, kind, regular_convo)
            blocked_convos[kind] = path
        convo = run(
            [
                "--palace",
                str(convo_palace),
                "mine",
                str(convos),
                "--mode",
                "convos",
                "--wing",
                "conversations",
                "--no-spellcheck",
            ]
        )
        convo_stdout, convo_stderr = require_ok(convo, "conversation mine", "Drawers filed:")
        if regular_convo.name not in convo_stdout:
            raise RuntimeError("conversation mine omitted the regular transcript control")
        assert_diagnostics(convo_stderr, blocked_convos, "conversation mine")
        convo_search = run(
            [
                "--palace",
                str(convo_palace),
                "search",
                "regular transcript remains searchable",
                "--results",
                "10",
            ]
        )
        convo_search_stdout, _ = require_ok(
            convo_search, "regular conversation search", regular_convo.name
        )
        if any(path.name in convo_search_stdout for path in blocked_convos.values()):
            raise RuntimeError("conversation search returned a rejected source alias")

        attempts_after = (
            network_attempts.read_bytes()
            if network_attempts is not None and network_attempts.exists()
            else b""
        )
        if attempts_after != attempts_before:
            raise RuntimeError("scenario attempted network access")
        cleanup_owned_sockets()
        cleanup_new_lease_artifacts()
        for path in (*blocked_project.values(), *blocked_convos.values()):
            if path.name.endswith("_socket.py") or path.name.endswith("_socket.txt"):
                if path.exists():
                    raise RuntimeError(f"owned socket path survived cleanup: {path}")
            elif not path.exists() and not path.is_symlink():
                raise RuntimeError(f"expected rejected node disappeared: {path}")
        boundaries = boundary_error()
        if boundaries:
            raise RuntimeError(boundaries)
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TimeoutError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        cleanup_errors: list[str] = []
        try:
            stop_watcher(watcher, watcher_reader, watcher_lines, watcher_output)
        except (OSError, RuntimeError, subprocess.SubprocessError) as cleanup_exc:
            cleanup_errors.append(f"watcher cleanup failed: {cleanup_exc}")
        try:
            cleanup_owned_sockets()
        except (OSError, RuntimeError) as cleanup_exc:
            cleanup_errors.append(str(cleanup_exc))
        try:
            cleanup_new_lease_artifacts()
        except OSError as cleanup_exc:
            cleanup_errors.append(f"lease cleanup failed: {cleanup_exc}")
        boundaries = boundary_error()
        if boundaries and boundaries not in str(exc):
            cleanup_errors.append(boundaries)
        detail = f"non-regular source evidence could not be evaluated: {exc}"
        if cleanup_errors:
            detail += "; " + "; ".join(cleanup_errors)
        return failure(detail)

    return _make_row(
        "installed_golden_non_regular_sources",
        INSTALLED_NON_REGULAR_SOURCE_COMMAND,
        "pass",
        "project, remine, mine-all, watcher, and conversation paths rejected all supported non-regular source kinds",
    )


def _parse_installed_cli_inventory(output: str) -> tuple[tuple[str, ...], ...]:
    """Validate the bounded parser inventory emitted by the installed probe."""
    if not output or len(output.encode("utf-8")) > INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT:
        raise ValueError("installed CLI inventory output is empty or oversized")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("installed CLI inventory is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"members"}:
        raise ValueError("installed CLI inventory has an invalid document shape")
    raw_members = payload["members"]
    if (
        not isinstance(raw_members, list)
        or not raw_members
        or len(raw_members) > INSTALLED_CLI_INVENTORY_MEMBER_LIMIT
    ):
        raise ValueError("installed CLI inventory has an invalid member count")

    members: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for raw_path in raw_members:
        if (
            not isinstance(raw_path, list)
            or not raw_path
            or len(raw_path) > INSTALLED_CLI_INVENTORY_DEPTH_LIMIT
            or any(
                not isinstance(token, str) or INSTALLED_CLI_INVENTORY_TOKEN.fullmatch(token) is None
                for token in raw_path
            )
        ):
            raise ValueError("installed CLI inventory contains an unsafe member")
        path = tuple(raw_path)
        if path in seen:
            raise ValueError("installed CLI inventory contains a duplicate member")
        if len(path) > 1 and path[:-1] not in seen:
            raise ValueError("installed CLI inventory is not in parser order")
        seen.add(path)
        members.append(path)
    return tuple(members)


def _parse_installed_cli_execution(
    output: str, discovered: tuple[tuple[str, ...], ...]
) -> set[tuple[str, ...]]:
    """Validate parser-attributed paths emitted for observed console argv."""
    if not output or len(output.encode("utf-8")) > INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT:
        raise ValueError("installed CLI execution attribution output is empty or oversized")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("installed CLI execution attribution is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"executed"}:
        raise ValueError("installed CLI execution attribution has an invalid document shape")
    raw_executed = payload["executed"]
    if not isinstance(raw_executed, list) or len(raw_executed) > len(discovered):
        raise ValueError("installed CLI execution attribution has an invalid member count")
    discovered_set = set(discovered)
    executed: set[tuple[str, ...]] = set()
    for raw_path in raw_executed:
        if not isinstance(raw_path, list) or any(not isinstance(token, str) for token in raw_path):
            raise ValueError("installed CLI execution attribution contains an invalid member")
        path = tuple(raw_path)
        if path not in discovered_set or path in executed:
            raise ValueError("installed CLI execution attribution contains an unknown member")
        executed.update(path[:depth] for depth in range(1, len(path) + 1))
    return executed


class _InstalledCliExecutionRecorder:
    """Record argv from exact candidate-console launches for parser attribution."""

    def __init__(self, console: Path):
        self._console = console.resolve()
        self.argv: list[list[str]] = []
        self.error: str | None = None

    def record(self, command) -> None:
        if not isinstance(command, (list, tuple)) or not command:
            return
        argv = [str(item) for item in command]
        try:
            launcher = Path(argv[0]).resolve()
        except OSError:
            return
        if launcher != self._console:
            return
        trace_argv = argv[1:]
        if (
            len(self.argv) >= INSTALLED_CLI_TRACE_COMMAND_LIMIT
            or len(trace_argv) > INSTALLED_CLI_TRACE_TOKEN_LIMIT
            or any(
                len(token.encode("utf-8")) > INSTALLED_CLI_TRACE_TOKEN_BYTES_LIMIT
                for token in trace_argv
            )
        ):
            self.error = "installed CLI execution trace exceeded its bounded shape"
            return
        self.argv.append(trace_argv)

    def render(self) -> str:
        if self.error:
            raise ValueError(self.error)
        payload = json.dumps(self.argv, separators=(",", ":"))
        if len(payload.encode("utf-8")) > INSTALLED_CLI_TRACE_BYTES_LIMIT:
            raise ValueError("installed CLI execution trace is oversized")
        return payload


def _reconcile_installed_cli_inventory(
    rows: list[dict],
    discovered: tuple[tuple[str, ...], ...],
    executed: set[tuple[str, ...]],
) -> list[dict]:
    """Fail the existing terminal suite row when direct execution is incomplete."""
    missing_members = [member for member in discovered if member not in executed]
    if not missing_members:
        return rows
    rendered: list[str] = []
    rendered_size = 0
    for member in missing_members:
        path = " ".join(member)
        added_size = len(path) + (2 if rendered else 0)
        if rendered_size + added_size > 1200:
            break
        rendered.append(path)
        rendered_size += added_size
    omitted = len(missing_members) - len(rendered)
    missing = ", ".join(rendered)
    if omitted:
        missing += f", ... (+{omitted} members)"
    reconciled = [*rows]
    reconciled[-1] = _make_row(
        "installed_golden_suite",
        INSTALLED_GOLDEN_COMMAND,
        "fail",
        f"missing direct candidate-console execution: {missing}; rerun: {INSTALLED_GOLDEN_COMMAND}",
    )
    return reconciled


def _parse_installed_mcp_inventory(
    output: str, *, venv: Path, repository_root: Path
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    """Validate registry/profile evidence emitted by the installed candidate interpreter."""
    if not output or len(output.encode("utf-8")) > INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT:
        raise ValueError("installed MCP inventory output is empty or oversized")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("installed MCP inventory is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "registry_module",
        "profiles_module",
        "tools",
        "profiles",
    }:
        raise ValueError("installed MCP inventory has an invalid document shape")

    resolved_venv = venv.resolve()
    resolved_repository = repository_root.resolve()
    module_paths: dict[str, Path] = {}
    expected_suffixes = {
        "registry_module": Path("mempalace_code/mcp/registry.py"),
        "profiles_module": Path("mempalace_code/mcp_tool_profiles.py"),
    }
    for key in ("registry_module", "profiles_module"):
        raw_path = payload[key]
        if not isinstance(raw_path, str):
            raise ValueError("installed MCP inventory has an invalid module path")
        module_path = Path(raw_path).resolve()
        if (
            not module_path.is_file()
            or not module_path.is_relative_to(resolved_venv)
            or module_path.is_relative_to(resolved_repository)
            or not module_path.as_posix().endswith(expected_suffixes[key].as_posix())
        ):
            raise ValueError("installed MCP inventory module provenance mismatch")
        module_paths[key] = module_path
    if len(set(module_paths.values())) != 2:
        raise ValueError("installed MCP inventory module owners are not distinct")

    raw_tools = payload["tools"]
    if not isinstance(raw_tools, list) or len(raw_tools) != 29:
        raise ValueError("installed MCP inventory must contain exactly 29 tools")
    tools = tuple(raw_tools)
    if any(
        not isinstance(name, str) or re.fullmatch(r"mempalace_[a-z][a-z0-9_]{0,79}", name) is None
        for name in tools
    ) or len(set(tools)) != len(tools):
        raise ValueError("installed MCP inventory contains invalid or duplicate tools")

    raw_profiles = payload["profiles"]
    if not isinstance(raw_profiles, list) or len(raw_profiles) != 5:
        raise ValueError("installed MCP inventory must contain exactly five profiles")
    profiles: list[tuple[str, tuple[str, ...]]] = []
    seen_profiles: set[str] = set()
    tool_set = set(tools)
    for raw_profile in raw_profiles:
        if not isinstance(raw_profile, dict) or set(raw_profile) != {"name", "members"}:
            raise ValueError("installed MCP profile has an invalid document shape")
        name = raw_profile["name"]
        raw_members = raw_profile["members"]
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name) is None
            or name in seen_profiles
            or not isinstance(raw_members, list)
            or not raw_members
            or len(raw_members) > INSTALLED_MCP_TOOL_LIMIT
        ):
            raise ValueError("installed MCP profile has an invalid name or member count")
        members = tuple(raw_members)
        if (
            any(not isinstance(member, str) for member in members)
            or len(set(members)) != len(members)
            or not set(members).issubset(tool_set)
            or members != tuple(tool for tool in tools if tool in set(members))
        ):
            raise ValueError("installed MCP profile members are invalid or out of registry order")
        seen_profiles.add(name)
        profiles.append((name, members))
    full_profiles = [members for name, members in profiles if name == "full"]
    if full_profiles != [tools]:
        raise ValueError("installed MCP full profile does not equal the installed registry")
    return tools, tuple(profiles)


def _installed_mcp_recipe(project: Path) -> dict[str, dict]:
    """Return semantic inputs only; installed discovery remains the inventory authority."""
    marker = "xylophonic_mcp_inventory_9182"
    return {
        "mempalace_status": {"arguments": {}},
        "mempalace_list_wings": {"arguments": {}},
        "mempalace_list_rooms": {"arguments": {"wing": "seed_main"}},
        "mempalace_get_taxonomy": {"arguments": {}},
        "mempalace_kg_query": {"arguments": {"entity": "SeedEntity"}},
        "mempalace_kg_add": {
            "arguments": {
                "subject": "AddedEntity",
                "predicate": "verifies",
                "object": "AddedObject",
            }
        },
        "mempalace_kg_invalidate": {
            "arguments": {
                "subject": "SeedEntity",
                "predicate": "preserves",
                "object": "SeedObject",
                "ended": "2026-01-01",
            }
        },
        "mempalace_kg_timeline": {"arguments": {"entity": "SeedEntity"}},
        "mempalace_kg_stats": {"arguments": {}},
        "mempalace_find_implementations": {"arguments": {"interface": "SeedInterface"}},
        "mempalace_find_references": {"arguments": {"type_name": "SeedProject"}},
        "mempalace_show_project_graph": {"arguments": {}},
        "mempalace_show_type_dependencies": {"arguments": {"type_name": "SeedService"}},
        "mempalace_explain_subsystem": {"arguments": {"query": marker}},
        "mempalace_extract_reusable": {"arguments": {"entity": "SeedProject"}},
        "mempalace_traverse": {"arguments": {"start_room": "shared_room"}},
        "mempalace_find_tunnels": {"arguments": {"wing_a": "seed_main", "wing_b": "seed_graph"}},
        "mempalace_graph_stats": {"arguments": {}},
        "mempalace_search": {"arguments": {"query": marker, "wing": "seed_main"}},
        "mempalace_code_search": {
            "arguments": {"query": marker, "language": "python", "wing": "seed_main"}
        },
        "mempalace_file_context": {"arguments": {"source_file": "fixture.py", "wing": "seed_main"}},
        "mempalace_check_duplicate": {"arguments": {"content": f"{marker}\nsecond fixture line"}},
        "mempalace_read": {
            "arguments": {
                "source_file": "fixture.py",
                "start_line": 1,
                "end_line": 2,
                "wing": "seed_main",
            }
        },
        "mempalace_add_drawer": {
            "arguments": {
                "wing": "added_wing",
                "room": "added_room",
                "content": "mcp added drawer poststate marker 9182",
                "source_file": "added.txt",
            }
        },
        "mempalace_delete_drawer": {"arguments": {"drawer_id": "mcp-delete-drawer"}},
        "mempalace_delete_wing": {"arguments": {"wing": "seed_delete_wing"}},
        "mempalace_mine": {
            "arguments": {"directory": str(project), "wing": "mined_wing", "full": True}
        },
        "mempalace_diary_write": {
            "arguments": {
                "agent_name": "release-mcp",
                "entry": "mcp diary poststate marker 9182",
                "topic": "release",
            }
        },
        "mempalace_diary_read": {"arguments": {"agent_name": "release-mcp"}},
    }


def _installed_mcp_text_result(response: dict) -> dict | list:
    if not isinstance(response, dict) or set(response) != {"jsonrpc", "id", "result"}:
        raise ValueError("MCP tool response did not contain one successful JSON-RPC result")
    result = response["result"]
    if not isinstance(result, dict) or set(result) != {"content"}:
        raise ValueError("MCP tool response had an invalid result envelope")
    content = result["content"]
    if (
        not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], dict)
        or content[0].get("type") != "text"
        or not isinstance(content[0].get("text"), str)
    ):
        raise ValueError("MCP tool response had an invalid text content envelope")
    try:
        payload = json.loads(content[0]["text"])
    except json.JSONDecodeError as exc:
        raise ValueError("MCP tool response text was not JSON") from exc
    if not isinstance(payload, (dict, list)):
        raise ValueError("MCP tool response semantic payload was not an object or list")
    return payload


def _validate_installed_mcp_semantics(name: str, payload: dict | list) -> None:
    """Reject generic-success evidence; each tool must prove a fixture invariant."""
    marker = "xylophonic_mcp_inventory_9182"
    ok = False
    if name == "mempalace_status" and isinstance(payload, dict):
        ok = payload.get("total_drawers", 0) >= 4 and payload.get("wings", {}).get("seed_main") == 1
    elif name == "mempalace_list_wings" and isinstance(payload, dict):
        ok = payload.get("wings", {}).get("seed_delete_wing") == 1
    elif name == "mempalace_list_rooms" and isinstance(payload, dict):
        ok = payload.get("wing") == "seed_main" and payload.get("rooms", {}).get("shared_room") == 1
    elif name == "mempalace_get_taxonomy" and isinstance(payload, dict):
        ok = payload.get("taxonomy", {}).get("seed_graph", {}).get("shared_room") == 1
    elif name == "mempalace_kg_query" and isinstance(payload, dict):
        ok = payload.get("entity") == "SeedEntity" and any(
            fact.get("predicate") == "preserves" and fact.get("object") == "SeedObject"
            for fact in payload.get("facts", [])
            if isinstance(fact, dict)
        )
    elif name == "mempalace_kg_add" and isinstance(payload, dict):
        ok = payload.get("success") is True and isinstance(payload.get("triple_id"), str)
    elif name == "mempalace_kg_invalidate" and isinstance(payload, dict):
        ok = payload.get("success") is True and payload.get("ended") == "2026-01-01"
    elif name == "mempalace_kg_timeline" and isinstance(payload, dict):
        ok = payload.get("entity") == "SeedEntity" and payload.get("count", 0) >= 1
    elif name == "mempalace_kg_stats" and isinstance(payload, dict):
        ok = payload.get("triples", 0) >= 3 and "preserves" in payload.get("relationship_types", [])
    elif name == "mempalace_find_implementations" and isinstance(payload, dict):
        ok = any(row.get("type") == "SeedService" for row in payload.get("implementations", []))
    elif name == "mempalace_find_references" and isinstance(payload, dict):
        ok = any(
            row.get("type") == "SeedDependency"
            for row in payload.get("references", {}).get("depends_on", [])
        )
    elif name == "mempalace_show_project_graph" and isinstance(payload, dict):
        ok = any(
            row.get("subject") == "SeedProject" and row.get("object") == "SeedDependency"
            for row in payload.get("graph", {}).get("depends_on", [])
        )
    elif name == "mempalace_show_type_dependencies" and isinstance(payload, dict):
        ok = payload.get("type") == "SeedService" and any(
            row.get("type") == "SeedInterface" for row in payload.get("ancestors", [])
        )
    elif name == "mempalace_explain_subsystem" and isinstance(payload, dict):
        ok = any(row.get("symbol_name") == "SeedService" for row in payload.get("entry_points", []))
    elif name == "mempalace_extract_reusable" and isinstance(payload, dict):
        ok = any(
            row.get("entity") == "SeedDependency"
            for row in payload.get("graph", {}).get("core", [])
        )
    elif name == "mempalace_traverse" and isinstance(payload, list):
        ok = (
            bool(payload)
            and payload[0].get("room") == "shared_room"
            and set(payload[0].get("wings", [])) == {"seed_main", "seed_graph"}
        )
    elif name == "mempalace_find_tunnels" and isinstance(payload, list):
        ok = any(row.get("room") == "shared_room" for row in payload)
    elif name == "mempalace_graph_stats" and isinstance(payload, dict):
        ok = payload.get("tunnel_rooms", 0) >= 1 and payload.get("total_rooms", 0) >= 2
    elif name in {"mempalace_search", "mempalace_code_search"} and isinstance(payload, dict):
        ok = any(marker in row.get("text", "") for row in payload.get("results", []))
    elif name == "mempalace_file_context" and isinstance(payload, dict):
        ok = payload.get("total", 0) >= 1 and any(
            marker in row.get("content", "") for row in payload.get("chunks", [])
        )
    elif name == "mempalace_check_duplicate" and isinstance(payload, dict):
        ok = payload.get("is_duplicate") is True and any(
            row.get("id") == "mcp-seed-main" for row in payload.get("matches", [])
        )
    elif name == "mempalace_read" and isinstance(payload, dict):
        ok = payload.get("source_file") == "fixture.py" and any(
            marker in row.get("text", "") for row in payload.get("lines", [])
        )
    elif name == "mempalace_add_drawer" and isinstance(payload, dict):
        ok = payload.get("success") is True and payload.get("wing") == "added_wing"
    elif name == "mempalace_delete_drawer" and isinstance(payload, dict):
        ok = payload == {"success": True, "drawer_id": "mcp-delete-drawer"}
    elif name == "mempalace_delete_wing" and isinstance(payload, dict):
        ok = payload.get("success") is True and payload.get("deleted_count") == 1
    elif name == "mempalace_mine" and isinstance(payload, dict):
        ok = payload.get("success") is True and payload.get("drawers_filed", 0) >= 1
    elif name == "mempalace_diary_write" and isinstance(payload, dict):
        ok = payload.get("success") is True and payload.get("topic") == "release"
    elif name == "mempalace_diary_read" and isinstance(payload, dict):
        ok = any(
            row.get("content") == "mcp diary poststate marker 9182"
            for row in payload.get("entries", [])
        )
    if not ok:
        raise ValueError(f"installed MCP semantic predicate failed for {name}")


def _run_installed_mcp_session(
    launcher: Path,
    profile: str,
    batches: list[list[dict | str]],
    env: dict[str, str],
    cwd: Path,
    *,
    popen=subprocess.Popen,
) -> tuple[int, str, str]:
    """Run one bounded, continuation-capable MCP stdio process."""
    process = None
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    overflow: list[str] = []
    writer_errors: list[BaseException] = []

    def read_stream(stream, chunks: list[str], label: str) -> None:
        total = 0
        try:
            for line in iter(stream.readline, ""):
                size = len(line.encode("utf-8"))
                total += size
                if size > INSTALLED_MCP_LINE_LIMIT or total > INSTALLED_MCP_OUTPUT_LIMIT:
                    overflow.append(label)
                    break
                chunks.append(line)
        finally:
            stream.close()

    readers: list[threading.Thread] = []
    writer: threading.Thread | None = None
    try:
        process = popen(
            [str(launcher), f"--profile={profile}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(cwd),
            env=env,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("MCP launcher omitted required stdio pipes")
        process_stdin = process.stdin
        readers = [
            threading.Thread(
                target=read_stream, args=(process.stdout, stdout_chunks, "stdout"), daemon=True
            ),
            threading.Thread(
                target=read_stream, args=(process.stderr, stderr_chunks, "stderr"), daemon=True
            ),
        ]
        for reader in readers:
            reader.start()

        rendered_batches: list[list[str]] = []
        request_count = 0
        for batch in batches:
            if not batch:
                raise RuntimeError("MCP continuation batch was empty")
            rendered_batch: list[str] = []
            for item in batch:
                rendered = (
                    item if isinstance(item, str) else json.dumps(item, separators=(",", ":"))
                )
                if len(rendered.encode("utf-8")) > INSTALLED_MCP_LINE_LIMIT:
                    raise RuntimeError("MCP request line exceeded the bounded limit")
                rendered_batch.append(rendered + "\n")
                request_count += 1
            rendered_batches.append(rendered_batch)
            if request_count > INSTALLED_MCP_REQUEST_LIMIT:
                raise RuntimeError("MCP request count exceeded the bounded limit")

        def write_requests() -> None:
            try:
                for rendered_batch in rendered_batches:
                    for rendered in rendered_batch:
                        process_stdin.write(rendered)
                    process_stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                writer_errors.append(exc)
            finally:
                try:
                    process_stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

        deadline = time.monotonic() + INSTALLED_MCP_TIMEOUT
        writer = threading.Thread(target=write_requests, daemon=True)
        writer.start()
        writer.join(timeout=max(0.01, deadline - time.monotonic()))
        if writer.is_alive():
            raise TimeoutError("MCP stdin writer exceeded the bounded timeout")
        if writer_errors:
            raise RuntimeError("MCP stdin writer failed") from writer_errors[0]
        returncode = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        for reader in readers:
            reader.join(timeout=5)
        if any(reader.is_alive() for reader in readers):
            raise RuntimeError("MCP output reader did not terminate")
        if overflow:
            raise RuntimeError(f"MCP {overflow[0]} exceeded the bounded output limit")
        return returncode, "".join(stdout_chunks), "".join(stderr_chunks)
    finally:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
        if writer is not None:
            writer.join(timeout=5)
        for reader in readers:
            reader.join(timeout=5)


def _installed_mcp_seed_records() -> str:
    marker = "xylophonic_mcp_inventory_9182"
    records = [
        {"type": "export_header"},
        {
            "type": "drawer",
            "id": "mcp-seed-main",
            "text": f"{marker}\nsecond fixture line",
            "wing": "seed_main",
            "room": "shared_room",
            "source_file": "fixture.py",
            "language": "python",
            "symbol_name": "SeedService",
            "symbol_type": "class",
            "line_start": 1,
            "line_end": 2,
        },
        {
            "type": "drawer",
            "id": "mcp-seed-graph",
            "text": "shared graph fixture",
            "wing": "seed_graph",
            "room": "shared_room",
        },
        {
            "type": "drawer",
            "id": "mcp-delete-drawer",
            "text": "drawer deletion fixture",
            "wing": "seed_delete_drawer",
            "room": "delete_room",
            "source_file": "deleted.py",
        },
        {
            "type": "drawer",
            "id": "mcp-delete-wing",
            "text": "wing deletion fixture",
            "wing": "seed_delete_wing",
            "room": "delete_room",
        },
        {
            "type": "kg_triple",
            "subject": "SeedEntity",
            "predicate": "preserves",
            "object": "SeedObject",
        },
        {
            "type": "kg_triple",
            "subject": "SeedService",
            "predicate": "implements",
            "object": "SeedInterface",
        },
        {
            "type": "kg_triple",
            "subject": "SeedProject",
            "predicate": "depends_on",
            "object": "SeedDependency",
        },
    ]
    return "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n"


def _run_installed_mcp_stdio_scenario(
    launcher: Path,
    console: Path,
    tools: tuple[str, ...],
    profiles: tuple[tuple[str, tuple[str, ...]], ...],
    env: dict[str, str],
    scenario_root: Path,
    neutral_cwd: Path,
    *,
    repository_root: Path,
    venv: Path,
    network_attempts: Path,
    smoke,
    run_subprocess=subprocess.run,
    popen=subprocess.Popen,
    run_session=_run_installed_mcp_session,
) -> str | None:
    """Qualify every installed profile and tool without adding a release-gate row."""
    try:
        launcher_stat = launcher.lstat()
        if (
            stat.S_ISLNK(launcher_stat.st_mode)
            or not stat.S_ISREG(launcher_stat.st_mode)
            or not os.access(launcher, os.X_OK)
            or not launcher.resolve().is_relative_to(venv.resolve())
        ):
            raise RuntimeError("installed MCP launcher is not a regular in-venv executable")

        scenario_root.mkdir(parents=True)
        palace_root = scenario_root / "palace-fixture"
        palace = palace_root / "data"
        project = _write_fixture_project(scenario_root / "project")
        scenario_home = scenario_root / "protected-home"
        scenario_tmp = scenario_root / "protected-tmp"
        scenario_home.mkdir()
        scenario_tmp.mkdir()
        seed_file = scenario_root / "seed.jsonl"
        seed_file.write_text(_installed_mcp_seed_records(), encoding="utf-8")
        scenario_env = dict(env)
        scenario_env["MEMPALACE_PALACE_PATH"] = str(palace)
        scenario_env["HOME"] = str(scenario_home)
        scenario_env["USERPROFILE"] = scenario_env["HOME"]
        scenario_env["TMPDIR"] = str(scenario_tmp)
        init_result = _run_installed_cli(
            run_subprocess,
            [str(console)],
            ["init", str(project), "--yes", "--skip-model-download"],
            scenario_env,
            neutral_cwd,
        )
        import_result = _run_installed_cli(
            run_subprocess,
            [str(console)],
            ["--palace", str(palace), "import", str(seed_file), "--skip-dedup"],
            scenario_env,
            neutral_cwd,
        )
        if (
            init_result.returncode != 0
            or import_result.returncode != 0
            or "Imported drawers:   4" not in (import_result.stdout or "")
            or "Imported KG triples:3" not in (import_result.stdout or "")
        ):
            raise RuntimeError("installed MCP fixture setup failed")

        recipe = _installed_mcp_recipe(project)
        if set(recipe) != set(tools):
            raise RuntimeError("installed MCP semantic recipe does not equal discovered registry")

        protected_paths = {
            "repository": repository_root,
            "candidate venv": venv,
            "neutral cwd": neutral_cwd,
            "HOME/USERPROFILE": Path(scenario_env["HOME"]),
            "TMPDIR": Path(scenario_env["TMPDIR"]),
            "XDG config": Path(scenario_env["XDG_CONFIG_HOME"]),
            "XDG data": Path(scenario_env["XDG_DATA_HOME"]),
            "XDG cache": Path(scenario_env["XDG_CACHE_HOME"]),
        }
        protected = {
            label: (path, _semantic_tree_snapshot(path)) for label, path in protected_paths.items()
        }

        allowed_scenario_prefixes = {
            palace_root.relative_to(scenario_root).as_posix(),
            project.relative_to(scenario_root).as_posix(),
        }

        def protected_scenario_snapshot() -> tuple[tuple[str, str, int, str], ...]:
            return tuple(
                row
                for row in _semantic_tree_snapshot(scenario_root)
                if not any(
                    row[0] == prefix or row[0].startswith(prefix + "/")
                    for prefix in allowed_scenario_prefixes
                )
            )

        scenario_before = protected_scenario_snapshot()
        attempts_before = network_attempts.read_bytes() if network_attempts.exists() else b""
        if attempts_before:
            raise RuntimeError("installed MCP scenario inherited a network attempt")

        primary_validated: set[str] = set()
        for profile_index, (profile_name, expected_members) in enumerate(profiles):
            initialize = {"jsonrpc": "2.0", "id": 20, "method": "initialize", "params": {}}
            list_request = {"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}}
            batches: list[list[dict | str]] = [[initialize], [list_request]]
            expected_responses: list[tuple[int | None, str]] = [
                (20, "result"),
                (10, "result"),
            ]
            primary_names: list[str] = []
            if profile_name == "full":
                hostile: list[dict | str] = [
                    "{malformed",
                    {"jsonrpc": "2.0", "id": 10, "method": "unknown/method", "params": {}},
                    "",
                ]
                calls: list[dict | str] = [*hostile]
                expected_responses.extend([(None, "error"), (10, "error")])
                next_id = 100
                for tool_name in tools:
                    calls.append(
                        {
                            "jsonrpc": "2.0",
                            "id": next_id,
                            "method": "tools/call",
                            "params": {"name": tool_name, **recipe[tool_name]},
                        }
                    )
                    expected_responses.append((next_id, "result"))
                    primary_names.append(tool_name)
                    next_id += 1
                poststate_calls = [
                    (
                        "added_drawer",
                        "mempalace_check_duplicate",
                        {"content": "mcp added drawer poststate marker 9182"},
                    ),
                    (
                        "deleted_drawer",
                        "mempalace_file_context",
                        {"source_file": "deleted.py"},
                    ),
                    ("deleted_wing", "mempalace_list_wings", {}),
                    ("kg_added", "mempalace_kg_query", {"entity": "AddedEntity"}),
                    ("kg_invalidated", "mempalace_kg_query", {"entity": "SeedEntity"}),
                    (
                        "mined_project",
                        "mempalace_search",
                        {"query": "go-fixture-marker", "wing": "mined_wing"},
                    ),
                ]
                for _label, tool_name, arguments in poststate_calls:
                    calls.append(
                        {
                            "jsonrpc": "2.0",
                            "id": next_id,
                            "method": "tools/call",
                            "params": {"name": tool_name, "arguments": arguments},
                        }
                    )
                    expected_responses.append((next_id, "result"))
                    next_id += 1
                batches[1].extend(calls)
            returncode, stdout, stderr = run_session(
                launcher,
                profile_name,
                batches,
                scenario_env,
                neutral_cwd,
                popen=popen,
            )
            raw = stdout + stderr
            raw_for_scan = raw.replace(str(palace_root.resolve()), "<allowed-palace>").replace(
                str(project.resolve()), "<allowed-project>"
            )
            protected_markers = {
                str(repository_root.resolve()),
                str(venv.resolve()),
                str(neutral_cwd.resolve()),
                str(Path(scenario_env["HOME"]).resolve()),
                str(Path(scenario_env["TMPDIR"]).resolve()),
                str(Path(scenario_env["XDG_CONFIG_HOME"]).resolve()),
                str(Path(scenario_env["XDG_DATA_HOME"]).resolve()),
                str(Path(scenario_env["XDG_CACHE_HOME"]).resolve()),
            }
            if returncode != 0 or any(marker in raw_for_scan for marker in protected_markers):
                raise RuntimeError("installed MCP process failed or exposed a protected path")
            if any(marker in raw_for_scan for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
                raise RuntimeError("installed MCP process emitted forbidden output")
            responses, decode_error = smoke._decode_mcp_json_lines(
                stdout,
                label="installed MCP process",
                output_limit=INSTALLED_MCP_OUTPUT_LIMIT,
            )
            if decode_error is not None or responses is None:
                raise RuntimeError(decode_error or "installed MCP response decoding failed")
            envelope_error = smoke._validate_mcp_responses(
                responses,
                tuple(expected_responses),
                label="installed MCP process",
            )
            if envelope_error is not None:
                raise RuntimeError(envelope_error)
            initialize_result = responses[0].get("result", {})
            if initialize_result.get("serverInfo", {}).get("name") != "mempalace-code":
                raise RuntimeError("installed MCP initialize semantics failed")
            listed = responses[1].get("result", {}).get("tools", [])
            listed_names = tuple(
                tool.get("name") for tool in listed if isinstance(tool, dict) and "name" in tool
            )
            if listed_names != expected_members or len(listed) != len(expected_members):
                raise RuntimeError(
                    "installed MCP profile listing did not match installed authority"
                )
            if profile_name == "full":
                if responses[2].get("error", {}).get("code") != -32700:
                    raise RuntimeError(
                        "installed MCP malformed framing did not fail as parse error"
                    )
                if responses[3].get("error", {}).get("code") != -32601:
                    raise RuntimeError("installed MCP duplicate ID was not occurrence-attributed")
                tool_responses = responses[4 : 4 + len(primary_names)]
                if len(tool_responses) != len(primary_names):
                    raise RuntimeError("installed MCP tool response count did not reconcile")
                for tool_name, response in zip(primary_names, tool_responses, strict=True):
                    payload = _installed_mcp_text_result(response)
                    _validate_installed_mcp_semantics(tool_name, payload)
                    primary_validated.add(tool_name)
                post_payloads = [
                    _installed_mcp_text_result(response)
                    for response in responses[4 + len(primary_names) :]
                ]
                if len(post_payloads) != len(poststate_calls):
                    raise RuntimeError("installed MCP post-state response count did not reconcile")
                added, deleted_drawer, deleted_wing, kg_added, kg_invalidated, mined = post_payloads
                poststate_checks = {
                    "added drawer retrieval": isinstance(added, dict)
                    and added.get("is_duplicate") is True,
                    "deleted drawer absence": isinstance(deleted_drawer, dict)
                    and deleted_drawer.get("total") == 0,
                    "deleted wing absence": isinstance(deleted_wing, dict)
                    and "seed_delete_wing" not in deleted_wing.get("wings", {}),
                    "KG addition": isinstance(kg_added, dict)
                    and any(
                        fact.get("predicate") == "verifies" and fact.get("object") == "AddedObject"
                        for fact in kg_added.get("facts", [])
                        if isinstance(fact, dict)
                    ),
                    "KG invalidation": isinstance(kg_invalidated, dict)
                    and any(
                        fact.get("predicate") == "preserves"
                        and fact.get("object") == "SeedObject"
                        and fact.get("current") is False
                        and fact.get("valid_to") == "2026-01-01"
                        for fact in kg_invalidated.get("facts", [])
                        if isinstance(fact, dict)
                    ),
                    "mined project retrieval": isinstance(mined, dict)
                    and any(
                        "go-fixture-marker" in row.get("text", "")
                        for row in mined.get("results", [])
                    ),
                }
                failed_poststate = [
                    label for label, passed in poststate_checks.items() if not passed
                ]
                if failed_poststate:
                    raise RuntimeError(
                        "installed MCP mutation post-state evidence failed: "
                        + ", ".join(failed_poststate)
                    )
            if profile_index >= INSTALLED_MCP_PROFILE_LIMIT:
                raise RuntimeError("installed MCP profile count exceeded its bound")

        if primary_validated != set(tools):
            raise RuntimeError(
                "installed MCP requested/responded/validated tool sets did not reconcile"
            )
        attempts_after = network_attempts.read_bytes() if network_attempts.exists() else b""
        if attempts_after != attempts_before:
            raise RuntimeError("installed MCP scenario attempted network access")
        changed_protected: list[str] = []
        for label, (path, before) in protected.items():
            after = _semantic_tree_snapshot(path)
            if after == before:
                continue
            before_rows = {row[0]: row[1:] for row in before}
            after_rows = {row[0]: row[1:] for row in after}
            changed_names = sorted(
                name
                for name in set(before_rows) | set(after_rows)
                if before_rows.get(name) != after_rows.get(name)
            )
            rendered_names = ", ".join(changed_names[:8])
            if len(changed_names) > 8:
                rendered_names += f", ... (+{len(changed_names) - 8})"
            changed_protected.append(f"{label} [{rendered_names}]")
        if changed_protected:
            raise RuntimeError(
                "installed MCP scenario changed protected filesystem boundary: "
                + ", ".join(changed_protected)
            )
        if protected_scenario_snapshot() != scenario_before:
            raise RuntimeError("installed MCP scenario changed a protected scenario boundary")
        return None
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TimeoutError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        detail = str(exc)
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        for path in (repository_root, venv, neutral_cwd, scenario_root):
            detail = detail.replace(str(path), "<protected-path>")
        return detail[:1200]


def _parse_installed_public_exports(
    output: str, *, venv: Path, repository_root: Path
) -> dict[str, tuple[str, ...]]:
    if len(output.encode("utf-8")) > INSTALLED_EXPORT_OUTPUT_LIMIT:
        raise ValueError("installed public export output exceeded limit")
    payload = json.loads(output)
    if not isinstance(payload, dict) or set(payload) != {"owners", "bindings"}:
        raise ValueError("installed public export document has invalid shape")
    if payload["bindings"] != {
        "root_main_is_one_shot_main": True,
        "mcp_tools_is_registry_tools": True,
        "mcp_handle_request_is_dispatch": True,
        "mcp_main_is_dispatch": True,
    }:
        raise ValueError("installed public exports are not bound to their runtime owners")
    owners = payload["owners"]
    if not isinstance(owners, list) or len(owners) != INSTALLED_EXPORT_OWNER_LIMIT:
        raise ValueError("installed public export owner set is incomplete")
    parsed: dict[str, tuple[str, ...]] = {}
    for document in owners:
        if not isinstance(document, dict) or set(document) != {"owner", "file", "exports"}:
            raise ValueError("installed public export owner document is malformed")
        owner, module_file, raw_exports = (
            document["owner"],
            document["file"],
            document["exports"],
        )
        if owner not in INSTALLED_PUBLIC_EXPORTS or owner in parsed:
            raise ValueError("installed public export owner is unknown or duplicated")
        try:
            resolved = Path(module_file).resolve()
        except (OSError, TypeError):
            raise ValueError("installed public export provenance is malformed") from None
        if not resolved.is_relative_to(venv.resolve()) or resolved.is_relative_to(
            repository_root.resolve()
        ):
            raise ValueError("installed public export resolved outside candidate contour")
        if (
            not isinstance(raw_exports, list)
            or not raw_exports
            or len(raw_exports) > INSTALLED_EXPORT_MEMBER_LIMIT
            or any(
                not isinstance(member, str) or INSTALLED_EXPORT_TOKEN.fullmatch(member) is None
                for member in raw_exports
            )
            or len(set(raw_exports)) != len(raw_exports)
        ):
            raise ValueError("installed public export members are malformed or duplicated")
        parsed[owner] = tuple(raw_exports)
    return parsed


def _reconcile_installed_optional_extras_and_public_exports(
    runtime_extras: tuple[str, ...],
    exports: dict[str, tuple[str, ...]],
    evidence: dict[str, bool],
) -> str | None:
    """Fail closed unless every discovered claim has direct installed behavior evidence."""
    evidenced_extras = {
        claim.removeprefix("extra:")
        for claim, passed in evidence.items()
        if passed is True and claim.startswith("extra:")
    }
    if set(runtime_extras) != evidenced_extras or len(runtime_extras) != len(evidenced_extras):
        return "installed non-dev extras do not equal the direct evidence bindings"
    if exports != INSTALLED_PUBLIC_EXPORTS:
        return "installed public exports do not equal the direct evidence bindings"
    required = {"chroma:retired", *(f"extra:{extra}" for extra in runtime_extras)}
    required.update(
        f"export:{owner}:{member}" for owner, members in exports.items() for member in members
    )
    missing = sorted(claim for claim in required if evidence.get(claim) is not True)
    unknown = sorted(
        claim for claim, passed in evidence.items() if passed and claim not in required
    )
    if missing or unknown:
        return "installed claim evidence did not reconcile one-to-one"
    return None


def _installed_spellcheck_evidence_error(
    base: object, spellcheck: object, *, source: str, expected: str
) -> str | None:
    """Require the exact base fallback and one deterministic corrected transcript."""
    if base != {"autocorrect": False, "output": source}:
        return "base spellcheck contour did not preserve safe fallback"
    if spellcheck != {"autocorrect": True, "output": expected}:
        return "installed spellcheck behavior did not produce the expected correction"
    return None


def _installed_treesitter_evidence_error(tree: object) -> str | None:
    """Require complete ordered AST chunks for every supported installed grammar."""
    languages = ("python", "typescript", "go", "rust")
    if not isinstance(tree, dict) or set(tree) != set(languages):
        return "installed tree-sitter language evidence is incomplete"
    for language in languages:
        result = tree[language]
        chunks = result.get("chunks") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or result.get("parser") is not True
            or result.get("grammar") is not True
            or not isinstance(chunks, list)
            or len(chunks) != 2
        ):
            return f"installed tree-sitter parser evidence is incomplete for {language}"
        if [chunk.get("marker") for chunk in chunks if isinstance(chunk, dict)] != [
            "alpha",
            "beta",
        ]:
            return f"installed tree-sitter chunk order is invalid for {language}"
        previous_end = 0
        for chunk in chunks:
            start, end = chunk.get("start"), chunk.get("end")
            if (
                chunk.get("strategy") != "treesitter_v1"
                or chunk.get("exact") is not True
                or type(start) is not int
                or type(end) is not int
                or start < 0
                or end <= start
                or start < previous_end
            ):
                return f"installed tree-sitter chunk evidence is invalid for {language}"
            previous_end = end
    return None


def _parse_single_marked_json(output: str, marker: str, label: str) -> object:
    """Decode exactly one marked JSON line from bounded progress output."""
    if len(output.encode("utf-8")) > INSTALLED_EXPORT_OUTPUT_LIMIT:
        raise ValueError(f"{label} output exceeded limit")
    matches = [line.removeprefix(marker) for line in output.splitlines() if line.startswith(marker)]
    if len(matches) != 1:
        raise ValueError(f"{label} did not emit exactly one evidence document")
    try:
        return json.loads(matches[0])
    except (json.JSONDecodeError, TypeError, UnicodeError):
        raise ValueError(f"{label} returned invalid JSON") from None


def _run_installed_extra_and_export_reconciliation(
    *,
    root: Path,
    wheel: Path,
    expected_version: str,
    temp_root: Path,
    base_venv: Path,
    base_python: Path,
    base_env: dict[str, str],
    setup_env: dict[str, str],
    neutral_cwd: Path,
    hf_home: Path,
    watch_receipt: bool,
    export_receipts: dict[str, bool],
    smoke,
    run_subprocess,
) -> str | None:
    """Install and directly exercise every discovered optional extra and public export."""

    def completed(command: list[str], *, env: dict[str, str], timeout: int = DEFAULT_TIMEOUT):
        return _run_golden_subprocess(
            run_subprocess,
            command,
            capture_output=True,
            text=True,
            cwd=str(neutral_cwd),
            env=env,
            timeout=timeout,
        )

    def tuple_run(command, **kwargs):
        result = _run_golden_subprocess(
            run_subprocess,
            command,
            capture_output=True,
            text=True,
            timeout=kwargs.get("timeout"),
            cwd=kwargs.get("cwd"),
            env=kwargs.get("env"),
        )
        return result.returncode, result.stdout or "", result.stderr or ""

    def json_probe(
        python_bin: Path,
        code: str,
        args: list[str],
        env: dict[str, str],
        label: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        marker: str | None = None,
    ):
        result = completed([str(python_bin), "-c", code, *args], env=env, timeout=timeout)
        if result.returncode != 0 or not _installed_output_is_clean(result):
            raise RuntimeError(f"{label} failed")
        if marker is not None:
            return _parse_single_marked_json(result.stdout, marker, label)
        try:
            return json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError, UnicodeError):
            raise RuntimeError(f"{label} returned invalid JSON") from None

    def install_extra(extra: str) -> tuple[Path, dict[str, str], Path, Path]:
        contour = temp_root / f"extra-{extra}"
        contour_venv = contour / "venv"
        contour_cwd = contour / "neutral"
        contour_cwd.mkdir(parents=True)
        python_bin = contour_venv / "bin" / "python"
        create = completed([sys.executable, "-m", "venv", str(contour_venv)], env=setup_env)
        if create.returncode != 0:
            raise RuntimeError(f"{extra} contour creation failed")
        install = completed(
            [str(python_bin), "-m", "pip", "install", f"{wheel}[{extra}]"],
            env=setup_env,
            timeout=INSTALLED_GOLDEN_TIMEOUT,
        )
        if install.returncode != 0:
            raise RuntimeError(f"{extra} contour installation failed")
        site = completed([str(python_bin), "-c", smoke._SITE_PACKAGES_SCRIPT], env=setup_env)
        try:
            site_paths = json.loads(site.stdout)
            site_dir = Path(site_paths[0]).resolve()
        except (json.JSONDecodeError, IndexError, OSError, TypeError):
            raise RuntimeError(f"{extra} contour provenance failed") from None
        if (
            site.returncode != 0
            or not isinstance(site_paths, list)
            or len(site_paths) != 1
            or not site_dir.is_relative_to(contour_venv.resolve())
        ):
            raise RuntimeError(f"{extra} contour provenance failed")
        guard = site_dir / "sitecustomize.py"
        loader = site_dir / smoke._SITE_GUARD_PTH
        if guard.exists() or loader.exists() or guard.is_symlink() or loader.is_symlink():
            raise RuntimeError(f"{extra} contour socket guard collision")
        guard.write_text(smoke._SITE_GUARD, encoding="utf-8")
        loader.write_text(f"import runpy; runpy.run_path({str(guard)!r})\n", encoding="utf-8")
        marker = contour / "socket-guard-loaded"
        attempts = contour / "socket-attempts.log"
        env = _installed_golden_env(
            base_env,
            temp_root=contour,
            hf_home=hf_home,
            console=contour_venv / "bin" / "mempalace-code",
            marker=marker,
            attempts=attempts,
        )
        return python_bin, env, attempts, marker

    try:
        evidence = dict(export_receipts)
        metadata = smoke.probe_candidate_extra_metadata(
            str(base_python),
            str(neutral_cwd),
            tuple_run,
            env=base_env,
            expected_root=str(base_venv),
            expected_version=expected_version,
        )
        if not metadata.ok:
            raise RuntimeError(metadata.detail)

        export_payload = json_probe(
            base_python, INSTALLED_EXPORT_PROBE, [], base_env, "installed public export probe"
        )
        exports = _parse_installed_public_exports(
            json.dumps(export_payload, separators=(",", ":")),
            venv=base_venv,
            repository_root=root,
        )

        fixture = temp_root / "spellcheck-fixture.txt"
        fixture.write_text("> mispelled quick brown fox\nassistant: unchanged\n", encoding="utf-8")
        base_spell = json_probe(
            base_python,
            INSTALLED_SPELLCHECK_PROBE,
            [str(fixture)],
            base_env,
            "base spellcheck fallback probe",
        )
        spell_python, spell_env, spell_attempts, spell_marker = install_extra("spellcheck")
        spell = json_probe(
            spell_python,
            INSTALLED_SPELLCHECK_PROBE,
            [str(fixture)],
            spell_env,
            "installed spellcheck behavior probe",
        )
        spellcheck_error = _installed_spellcheck_evidence_error(
            base_spell,
            spell,
            source=fixture.read_text(encoding="utf-8"),
            expected="> misspelled quick brown fox\nassistant: unchanged\n",
        )
        if spellcheck_error:
            raise RuntimeError(spellcheck_error)
        evidence["extra:spellcheck"] = True

        tree_python, tree_env, tree_attempts, tree_marker = install_extra("treesitter")
        tree = json_probe(
            tree_python,
            INSTALLED_TREESITTER_PROBE,
            [],
            tree_env,
            "installed tree-sitter behavior probe",
        )
        treesitter_error = _installed_treesitter_evidence_error(tree)
        if treesitter_error:
            raise RuntimeError(treesitter_error)
        evidence["extra:treesitter"] = True

        migration = json_probe(
            base_python,
            INSTALLED_MIGRATION_PROBE,
            [],
            base_env,
            "installed Chroma retirement probe",
            timeout=INSTALLED_GOLDEN_TIMEOUT,
            marker=INSTALLED_MIGRATION_EVIDENCE_MARKER,
        )
        if migration.get("returncode") != 1 or any(
            migration.get(key) is not True
            for key in (
                "stderr_exact",
                "bridge_modules_absent",
                "chromadb_dependency_absent",
            )
        ):
            raise RuntimeError("installed Chroma retirement evidence is incomplete")
        evidence["chroma:retired"] = True

        alias_target = temp_root / "alias-launcher-target"
        alias_target.mkdir()
        alias_launcher = base_venv / "bin" / "mempalace-code-alias"
        alias = completed([str(alias_launcher), "--target-dir", str(alias_target)], env=base_env)
        alias_path = alias_target / "mempalace"
        if alias.returncode != 0 or not alias_path.is_symlink():
            raise RuntimeError("installed alias launcher behavior failed")
        evidence["export:mempalace_code.cli:main_alias"] = True

        checked_attempts = [spell_attempts, tree_attempts]
        checked_markers = [spell_marker, tree_marker]
        if not all(path.is_file() for path in checked_markers):
            raise RuntimeError("installed optional-extra socket guard did not load")
        if any(path.exists() and path.read_text(encoding="utf-8") for path in checked_attempts):
            raise RuntimeError("installed optional-extra runtime attempted network access")

        evidence["extra:watch"] = watch_receipt
        return _reconcile_installed_optional_extras_and_public_exports(
            metadata.runtime_extras, exports, evidence
        )
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TimeoutError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        detail = str(exc)
        if any(marker in detail for marker in INSTALLED_GOLDEN_FORBIDDEN_OUTPUT):
            detail = "forbidden subprocess output detected"
        for path in (root, wheel, temp_root, base_venv, neutral_cwd):
            detail = detail.replace(str(path), "<protected-path>")
        return detail[:1200]


def _run_installed_golden_wheel(
    root: Path,
    wheel: Path,
    *,
    base_env: dict[str, str] | None = None,
    run_subprocess=subprocess.run,
    popen=subprocess.Popen,
) -> list[dict]:
    """Run the complete golden suite through one exact installed wheel executable."""
    env_source = dict(os.environ if base_env is None else base_env)
    hf_home, cache_detail = _validated_model_cache(env_source)
    if hf_home is None:
        return [_make_row("installed_golden_cache", INSTALLED_GOLDEN_COMMAND, "fail", cache_detail)]

    wheel = wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        return [
            _make_row(
                "installed_golden_wheel",
                INSTALLED_GOLDEN_COMMAND,
                "fail",
                "the explicit candidate wheel is missing or is not a wheel",
            )
        ]
    try:
        _name, expected_version = _wheel_identity(wheel)
    except ValueError as exc:
        return [_make_row("installed_golden_wheel", INSTALLED_GOLDEN_COMMAND, "fail", str(exc))]

    smoke = _load_sibling("_release_install_metadata_golden", "release_install_metadata_smoke.py")
    with tempfile.TemporaryDirectory(prefix="mempalace-installed-golden-") as tmpdir:
        temp_root = Path(tmpdir)
        venv = temp_root / "venv"
        neutral_cwd = temp_root / "neutral"
        neutral_cwd.mkdir()
        python_bin = venv / "bin" / "python"
        console = venv / "bin" / "mempalace-code"
        mcp_launcher = venv / "bin" / "mempalace-code-mcp"
        marker = temp_root / "socket-guard-loaded"
        attempts = temp_root / "socket-attempts.log"
        setup_env = _credential_free_build_env(
            temp_root / "setup-home", temp_root / "setup-tmp", env_source
        )

        create = _run_golden_subprocess(
            run_subprocess,
            [sys.executable, "-m", "venv", str(venv)],
            capture_output=True,
            text=True,
            cwd=str(neutral_cwd),
            env=setup_env,
            timeout=DEFAULT_TIMEOUT,
        )
        if create.returncode != 0:
            return [
                _make_row(
                    "installed_golden_install",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    create.stderr or create.stdout or "venv creation failed",
                )
            ]
        install = _run_golden_subprocess(
            run_subprocess,
            [str(python_bin), "-m", "pip", "install", f"{wheel}[watch]"],
            capture_output=True,
            text=True,
            cwd=str(neutral_cwd),
            env=setup_env,
            timeout=INSTALLED_GOLDEN_TIMEOUT,
        )
        if install.returncode != 0 or not console.is_file() or not mcp_launcher.is_file():
            return [
                _make_row(
                    "installed_golden_install",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    install.stderr
                    or install.stdout
                    or "installed console or MCP executable is missing",
                )
            ]

        site_probe = _run_golden_subprocess(
            run_subprocess,
            [str(python_bin), "-c", smoke._SITE_PACKAGES_SCRIPT],
            capture_output=True,
            text=True,
            cwd=str(neutral_cwd),
            env=setup_env,
            timeout=DEFAULT_TIMEOUT,
        )
        try:
            site_paths = json.loads(site_probe.stdout)
        except (json.JSONDecodeError, TypeError):
            site_paths = None
        if (
            site_probe.returncode != 0
            or not isinstance(site_paths, list)
            or len(site_paths) != 1
            or not isinstance(site_paths[0], str)
        ):
            return [
                _make_row(
                    "installed_golden_guard",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    "installed site-packages discovery failed",
                )
            ]
        site_dir = Path(site_paths[0]).resolve()
        if not site_dir.is_relative_to(venv.resolve()):
            return [
                _make_row(
                    "installed_golden_guard",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    "installed site-packages resolved outside the candidate venv",
                )
            ]
        guard = site_dir / "sitecustomize.py"
        guard_loader = site_dir / smoke._SITE_GUARD_PTH
        if (
            guard.exists()
            or guard.is_symlink()
            or guard_loader.exists()
            or guard_loader.is_symlink()
        ):
            return [
                _make_row(
                    "installed_golden_guard",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    "refused to overwrite an existing installed socket guard",
                )
            ]
        guard.write_text(smoke._SITE_GUARD, encoding="utf-8")
        guard_loader.write_text(f"import runpy; runpy.run_path({str(guard)!r})\n", encoding="utf-8")

        try:
            disposable_hf_home = _materialize_model_cache(hf_home, temp_root / "model-home")
            golden_env = _installed_golden_env(
                env_source,
                temp_root=temp_root,
                hf_home=disposable_hf_home,
                console=console,
                marker=marker,
                attempts=attempts,
            )
        except OSError:
            return [
                _make_row(
                    "installed_golden_cache",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    "validated model cache could not be isolated; " + _cache_recovery(),
                )
            ]
        provenance_code = (
            "import importlib.metadata, json, mempalace_code, sys; "
            "print(json.dumps({'metadata': importlib.metadata.version('mempalace-code'), "
            "'module': mempalace_code.__file__, 'python': sys.executable}))"
        )
        provenance = _run_golden_subprocess(
            run_subprocess,
            [str(python_bin), "-c", provenance_code],
            capture_output=True,
            text=True,
            cwd=str(neutral_cwd),
            env=golden_env,
            timeout=DEFAULT_TIMEOUT,
        )
        try:
            identity = json.loads(provenance.stdout)
            module_path = Path(identity["module"]).resolve()
            reported_python = Path(identity["python"]).resolve()
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            identity = {}
            module_path = root.resolve()
            reported_python = root.resolve()
        ambient_console = shutil.which("mempalace-code", path=env_source.get("PATH", os.defpath))
        provenance_ok = (
            provenance.returncode == 0
            and identity.get("metadata") == expected_version
            and module_path.is_relative_to(venv.resolve())
            and not module_path.is_relative_to(root.resolve())
            and reported_python == python_bin.resolve()
            and console.resolve().is_relative_to(venv.resolve())
            and (ambient_console is None or Path(ambient_console).resolve() != console.resolve())
            and marker.is_file()
        )
        if not provenance_ok:
            return [
                _make_row(
                    "installed_golden_provenance",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    provenance.stderr or provenance.stdout or "installed provenance mismatch",
                )
            ]

        mcp_probe_path = temp_root / INSTALLED_MCP_INVENTORY_PROBE_NAME
        mcp_probe_path.write_text(INSTALLED_MCP_INVENTORY_PROBE, encoding="utf-8")
        mcp_inventory_probe = _run_golden_subprocess(
            run_subprocess,
            [str(python_bin), str(mcp_probe_path)],
            capture_output=True,
            text=True,
            cwd=str(neutral_cwd),
            env=golden_env,
            timeout=DEFAULT_TIMEOUT,
        )
        try:
            if mcp_inventory_probe.returncode != 0 or not _installed_output_is_clean(
                mcp_inventory_probe
            ):
                raise ValueError("installed MCP registry/profile introspection failed")
            discovered_mcp_tools, discovered_mcp_profiles = _parse_installed_mcp_inventory(
                mcp_inventory_probe.stdout or "", venv=venv, repository_root=root
            )
        except (OSError, TypeError, UnicodeError, ValueError) as exc:
            return [
                _make_row(
                    "installed_golden_suite",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    f"{exc}; rerun: {INSTALLED_GOLDEN_COMMAND}",
                )
            ]

        probe_path = temp_root / INSTALLED_CLI_INVENTORY_PROBE_NAME
        probe_path.write_text(INSTALLED_CLI_INVENTORY_PROBE, encoding="utf-8")
        inventory_probe = _run_golden_subprocess(
            run_subprocess,
            [str(python_bin), str(probe_path)],
            capture_output=True,
            text=True,
            cwd=str(neutral_cwd),
            env=golden_env,
            timeout=DEFAULT_TIMEOUT,
        )
        try:
            if inventory_probe.returncode != 0 or not _installed_output_is_clean(inventory_probe):
                raise ValueError("installed CLI parser introspection failed")
            discovered_members = _parse_installed_cli_inventory(inventory_probe.stdout or "")
        except (TypeError, UnicodeError, ValueError) as exc:
            return [
                _make_row(
                    "installed_golden_suite",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    f"{exc}; rerun: {INSTALLED_GOLDEN_COMMAND}",
                )
            ]

        recorder = _InstalledCliExecutionRecorder(console)
        underlying_run_subprocess = run_subprocess
        underlying_popen = popen

        def recorded_run_subprocess(command, **kwargs):
            recorder.record(command)
            return underlying_run_subprocess(command, **kwargs)

        def recorded_popen(command, **kwargs):
            recorder.record(command)
            return underlying_popen(command, **kwargs)

        run_subprocess = recorded_run_subprocess

        recovery_safety_row = _run_installed_recovery_safety_scenario(
            [str(console)],
            golden_env,
            temp_root / "recovery-safety-scenario",
            neutral_cwd,
            repository_root=root,
            network_attempts=attempts,
            run_subprocess=run_subprocess,
        )
        if recovery_safety_row["status"] != "pass":
            return [recovery_safety_row]

        path_contracts_row = _run_installed_path_contract_scenario(
            [str(console)],
            golden_env,
            temp_root / "path-contract-scenario",
            neutral_cwd,
            repository_root=root,
            network_attempts=attempts,
            run_subprocess=run_subprocess,
        )
        if path_contracts_row["status"] != "pass":
            return [path_contracts_row]

        inventory_gap = _run_installed_cli_inventory_gap_scenario(
            [str(console)],
            golden_env,
            temp_root / "cli-inventory-scenario",
            neutral_cwd,
            palace=temp_root / "path-contract-scenario" / "palace",
            project=(temp_root / "path-contract-scenario" / "projects" / "initialized-only"),
            repository_root=root,
            network_attempts=attempts,
            run_subprocess=run_subprocess,
        )
        if inventory_gap is not None:
            return [
                _make_row(
                    "installed_golden_suite",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    f"{inventory_gap}; rerun: {INSTALLED_GOLDEN_COMMAND}",
                )
            ]

        diary_blank_required_fields_row = _run_installed_diary_blank_required_fields_scenario(
            [str(console)],
            golden_env,
            temp_root / "diary-blank-required-fields-scenario",
            neutral_cwd,
            repository_root=root,
            network_attempts=attempts,
            run_subprocess=run_subprocess,
        )
        if diary_blank_required_fields_row["status"] != "pass":
            return [diary_blank_required_fields_row]

        schedule_snippets_row = _run_installed_schedule_snippet_scenario(
            [str(console)],
            golden_env,
            temp_root / "schedule-snippet-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if schedule_snippets_row["status"] != "pass":
            return [schedule_snippets_row]

        alias_containment_row = _run_installed_alias_target_containment_scenario(
            [str(console)],
            console,
            golden_env,
            temp_root / "alias-containment-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if alias_containment_row["status"] != "pass":
            return [alias_containment_row]

        watcher_signals_row = _run_installed_watcher_signal_cleanup_scenario(
            [str(console)],
            golden_env,
            temp_root / "watcher-signal-scenario",
            neutral_cwd,
            repository_root=root,
            network_attempts=attempts,
            run_subprocess=run_subprocess,
            popen=recorded_popen,
        )
        if watcher_signals_row["status"] != "pass":
            return [watcher_signals_row]

        workflow_happy_path_row = _run_installed_workflow_happy_path_scenario(
            [str(console)],
            golden_env,
            temp_root / "workflow-happy-path-scenario",
            neutral_cwd,
            repository_root=root,
            network_attempts=attempts,
            run_subprocess=run_subprocess,
            popen=recorded_popen,
        )
        if workflow_happy_path_row["status"] != "pass":
            return [workflow_happy_path_row]

        fetch_model_row = _run_installed_fetch_model_scenario(
            [str(console)],
            golden_env,
            temp_root / "fetch-model-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if fetch_model_row["status"] != "pass":
            return [fetch_model_row]

        read_failures_row = _run_installed_read_failure_scenario(
            [str(console)],
            golden_env,
            temp_root / "read-failure-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if read_failures_row["status"] != "pass":
            return [read_failures_row]

        convo_full_replace_row = _run_installed_convo_full_replace_scenario(
            [str(console)],
            golden_env,
            temp_root / "convo-full-replace-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if convo_full_replace_row["status"] != "pass":
            return [convo_full_replace_row]

        cleanup_poststate_row = _run_installed_cleanup_poststate_scenario(
            [str(console)],
            golden_env,
            temp_root / "cleanup-poststate-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if cleanup_poststate_row["status"] != "pass":
            return [cleanup_poststate_row]

        rollback_no_candidate_row = _run_installed_rollback_no_candidate_scenario(
            [str(console)],
            golden_env,
            temp_root / "rollback-no-candidate-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if rollback_no_candidate_row["status"] != "pass":
            return [rollback_no_candidate_row]

        compress_retry_row = _run_installed_compress_retry_scenario(
            [str(console)],
            golden_env,
            temp_root / "compress-retry-scenario",
            neutral_cwd,
            repository_root=root,
            run_subprocess=run_subprocess,
        )
        if compress_retry_row["status"] != "pass":
            return [compress_retry_row]

        split_row = _run_installed_split_scenario(
            [str(console)],
            golden_env,
            temp_root / "split-scenario",
            neutral_cwd,
            run_subprocess=run_subprocess,
        )
        if split_row["status"] != "pass":
            return [split_row]

        import_missing_row = _run_installed_import_missing_scenario(
            [str(console)],
            golden_env,
            temp_root / "import-missing-scenario",
            neutral_cwd,
            run_subprocess=run_subprocess,
        )
        if import_missing_row["status"] != "pass":
            return [import_missing_row]

        palace_rows = _run_installed_palace_argument_scenarios(
            [str(console)],
            golden_env,
            temp_root / "palace-argument-scenarios",
            neutral_cwd,
            run_subprocess=run_subprocess,
        )
        if any(row["status"] != "pass" for row in palace_rows):
            return palace_rows

        search_result_rows = _run_installed_search_results_scenarios(
            [str(console)],
            golden_env,
            temp_root / "search-results-scenarios",
            neutral_cwd,
            run_subprocess=run_subprocess,
        )
        if any(row["status"] != "pass" for row in search_result_rows):
            return search_result_rows

        version_row = _run_installed_version_scenario(
            [str(console)],
            golden_env,
            neutral_cwd,
            expected_version,
            run_subprocess=run_subprocess,
        )
        if version_row["status"] != "pass":
            return [version_row]

        non_regular_source_row = _run_installed_non_regular_source_scenario(
            [str(console)],
            golden_env,
            temp_root / "non-regular-source-scenario",
            neutral_cwd,
            repository_root=root,
            network_attempts=attempts,
            run_subprocess=run_subprocess,
            popen=recorded_popen,
        )
        if non_regular_source_row["status"] != "pass":
            return [non_regular_source_row]

        mcp_failure = _run_installed_mcp_stdio_scenario(
            mcp_launcher,
            console,
            discovered_mcp_tools,
            discovered_mcp_profiles,
            golden_env,
            temp_root / "mcp-stdio-scenario",
            neutral_cwd,
            repository_root=root,
            venv=venv,
            network_attempts=attempts,
            smoke=smoke,
            run_subprocess=run_subprocess,
            popen=recorded_popen,
        )
        if mcp_failure is not None:
            return [
                _make_row(
                    "installed_golden_suite",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    f"{mcp_failure}; rerun: {INSTALLED_GOLDEN_COMMAND}",
                )
            ]

        direct_claim_failure = _run_installed_extra_and_export_reconciliation(
            root=root,
            wheel=wheel,
            expected_version=expected_version,
            temp_root=temp_root,
            base_venv=venv,
            base_python=python_bin,
            base_env=golden_env,
            setup_env=setup_env,
            neutral_cwd=neutral_cwd,
            hf_home=disposable_hf_home,
            watch_receipt=all(
                row["status"] == "pass"
                for row in (
                    watcher_signals_row,
                    workflow_happy_path_row,
                    non_regular_source_row,
                )
            ),
            export_receipts={
                "export:mempalace_code:main": version_row["status"] == "pass",
                "export:mempalace_code:__version__": version_row["status"] == "pass",
                "export:mempalace_code.cli:main": version_row["status"] == "pass",
                "export:mempalace_code.cli:install_legacy_alias": (
                    alias_containment_row["status"] == "pass"
                ),
                "export:mempalace_code.cli:fetch_model": fetch_model_row["status"] == "pass",
                "export:mempalace_code.mcp:TOOLS": mcp_failure is None,
                "export:mempalace_code.mcp:handle_request": mcp_failure is None,
                "export:mempalace_code.mcp:main": mcp_failure is None,
            },
            smoke=smoke,
            run_subprocess=underlying_run_subprocess,
        )
        if direct_claim_failure is not None:
            return [
                _make_row(
                    "installed_golden_suite",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    f"{direct_claim_failure}; rerun: {INSTALLED_GOLDEN_COMMAND}",
                )
            ]

        attempts_text = attempts.read_text(encoding="utf-8") if attempts.exists() else ""
        if attempts_text:
            return [
                _make_row(
                    "installed_golden_suite",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    attempts_text,
                )
            ]
        rows = [
            _make_row("installed_golden_cache", INSTALLED_GOLDEN_COMMAND, "pass", cache_detail),
            _make_row(
                "installed_golden_provenance",
                INSTALLED_GOLDEN_COMMAND,
                "pass",
                f"wheel metadata {expected_version}, module and executable matched candidate venv",
            ),
            recovery_safety_row,
            path_contracts_row,
            diary_blank_required_fields_row,
            schedule_snippets_row,
            alias_containment_row,
            watcher_signals_row,
            workflow_happy_path_row,
            fetch_model_row,
            read_failures_row,
            convo_full_replace_row,
            cleanup_poststate_row,
            rollback_no_candidate_row,
            compress_retry_row,
            split_row,
            import_missing_row,
            *palace_rows,
            *search_result_rows,
            version_row,
            non_regular_source_row,
            _make_row(
                "installed_golden_suite",
                INSTALLED_GOLDEN_COMMAND,
                "pass",
                "complete golden CLI suite, optional extras, and public exports passed offline",
            ),
        ]
        trace_path = temp_root / "installed-cli-execution-trace.json"
        try:
            trace_path.write_text(recorder.render(), encoding="utf-8")
            execution_probe = _run_golden_subprocess(
                underlying_run_subprocess,
                [str(python_bin), str(probe_path), str(trace_path)],
                capture_output=True,
                text=True,
                cwd=str(neutral_cwd),
                env=golden_env,
                timeout=DEFAULT_TIMEOUT,
            )
            if execution_probe.returncode != 0 or not _installed_output_is_clean(execution_probe):
                raise ValueError("installed CLI execution attribution failed")
            executed_members = _parse_installed_cli_execution(
                execution_probe.stdout or "", discovered_members
            )
        except (OSError, TypeError, UnicodeError, ValueError) as exc:
            return [
                _make_row(
                    "installed_golden_suite",
                    INSTALLED_GOLDEN_COMMAND,
                    "fail",
                    f"{exc}; rerun: {INSTALLED_GOLDEN_COMMAND}",
                )
            ]
        return _reconcile_installed_cli_inventory(rows, discovered_members, executed_members)


def _run_installed_golden(dist_dir: Path, root: Path) -> list[dict]:
    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        return [
            _make_row(
                "installed_golden_wheel",
                INSTALLED_GOLDEN_COMMAND,
                "fail",
                f"expected one candidate wheel, found {len(wheels)}",
            )
        ]
    return _run_installed_golden_wheel(root, wheels[0])


def _credential_free_build_env(
    home: Path, temp: Path, base_env: dict[str, str] | None = None
) -> dict[str, str]:
    """Return the small environment needed to build without forwarding credentials."""
    source = os.environ if base_env is None else base_env
    xdg_cache = temp / "xdg-cache"
    xdg_config = temp / "xdg-config"
    xdg_data = temp / "xdg-data"
    for path in (home, temp, xdg_cache, xdg_config, xdg_data):
        path.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "TMPDIR": str(temp),
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(xdg_data),
        "PATH": source.get("PATH", os.defpath),
        "PYTHONNOUSERSITE": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_KEYRING_PROVIDER": "disabled",
        "MEMPALACE_VERSION_CHECK": "0",
    }
    for name in ("LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "SYSTEMROOT", "WINDIR"):
        if source.get(name):
            env[name] = source[name]
    return env


# ── Orchestration ──────────────────────────────────────────────────────────────


def run_readiness(
    root: Path,
    *,
    artifact_only: bool = False,
    public_admission: bool = False,
    version: str = "",
    repo: str = DEFAULT_REPO,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    package: str = PACKAGE_NAME,
    candidate_sha: str | None = None,
    required_check_name: str | None = None,
    audit_max_age_hours: int | None = None,
    public_read=None,
) -> dict:
    """Run the full release-readiness check and return a structured result dict."""
    del remote  # Public evidence is bound to the fixed repository, not a Git remote.
    all_rows: list[dict] = []
    ok = True

    normalized_sha = (candidate_sha or "").lower()
    if not artifact_only and not _SHA_RE.fullmatch(normalized_sha):
        return {
            "ok": False,
            "completion": "failed",
            "rows": [
                _make_row(
                    "candidate_sha",
                    "python scripts/release_readiness_gate.py --check --candidate-sha <sha> --json",
                    "fail",
                    "an explicit 40-hex candidate SHA is required before build",
                )
            ],
        }

    if not artifact_only:
        inventory_rows = _run_inventory_check(root)
        all_rows.extend(inventory_rows)
        if any(r["status"] == "fail" for r in inventory_rows):
            ok = False

    if public_admission:
        admission = _load_admission_checks()
        public = _load_public_read()
        admission_rows = _run_public_admission_checks(
            version=version or "unknown",
            repo=repo,
            branch=branch,
            package=package,
            candidate_sha=candidate_sha,
            required_check_name=required_check_name or admission.AGGREGATE_REQUIRED_CHECK,
            audit_max_age_hours=audit_max_age_hours or admission.DEFAULT_AUDIT_MAX_AGE_HOURS,
            public_read=public_read or public.DEFAULT_READER,
        )
        all_rows.extend(admission_rows)
        if any(r["status"] not in ("pass", "skip") for r in admission_rows):
            ok = False

    with tempfile.TemporaryDirectory(prefix="mempalace-readiness-") as tmpdir:
        temp_root = Path(tmpdir)
        dist_dir = temp_root / "dist"
        build_home = temp_root / "home"
        build_temp = temp_root / "tmp"
        dist_dir.mkdir()
        build_home.mkdir()
        build_temp.mkdir()
        build_env = _credential_free_build_env(build_home, build_temp)

        build_ok, build_detail = _build_artifacts(root, dist_dir, env=build_env)
        all_rows.append(
            _make_row(
                "artifact_build",
                "python -m build",
                "pass" if build_ok else "fail",
                build_detail,
            )
        )
        if not build_ok:
            ok = False
        else:
            artifact_rows = _run_artifact_inspection(dist_dir)
            all_rows.extend(artifact_rows)
            if any(r["status"] == "fail" for r in artifact_rows):
                ok = False

            if not artifact_only:
                installed_rows = _run_installed_application(dist_dir)
                all_rows.extend(installed_rows)
                if any(r["status"] != "pass" for r in installed_rows):
                    ok = False
                golden_rows = _run_installed_golden(dist_dir, root)
                all_rows.extend(golden_rows)
                if any(r["status"] != "pass" for r in golden_rows):
                    ok = False

    return {
        "ok": ok,
        "completion": "complete" if ok else "failed",
        "rows": all_rows,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orchestrate the complete release-readiness check."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the full release-readiness gate (inventory + build + artifact + installed application).",
    )
    parser.add_argument(
        "--artifact-only",
        action="store_true",
        help="Only build artifacts and run artifact inspection.",
    )
    parser.add_argument(
        "--installed-golden-wheel",
        type=Path,
        help="Run the complete offline golden CLI suite against one explicit candidate wheel.",
    )
    parser.add_argument(
        "--public-admission",
        action="store_true",
        help="Add read-only public release admission rows for candidate SHA, refs, tags, and audit freshness.",
    )
    parser.add_argument("--version", help="Release version used for public orphan-tag checks.")
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help=f"GitHub repo (default: {DEFAULT_REPO})."
    )
    parser.add_argument(
        "--remote", default=DEFAULT_REMOTE, help=f"Public git remote (default: {DEFAULT_REMOTE})."
    )
    parser.add_argument(
        "--branch", default=DEFAULT_BRANCH, help=f"Public branch (default: {DEFAULT_BRANCH})."
    )
    parser.add_argument(
        "--package", default=PACKAGE_NAME, help=f"PyPI package (default: {PACKAGE_NAME})."
    )
    parser.add_argument("--candidate-sha", help="Operator-reviewed 40-hex candidate SHA.")
    parser.add_argument(
        "--required-check-name",
        default=None,
        help="Aggregate required check name. Defaults to release-required.",
    )
    parser.add_argument(
        "--audit-max-age-hours",
        type=int,
        default=None,
        help="Maximum age for the latest successful dependency-audit run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )
    args = parser.parse_args(argv)

    selected_modes = sum(
        bool(value) for value in (args.check, args.artifact_only, args.installed_golden_wheel)
    )
    if selected_modes != 1:
        parser.error("specify exactly one of --check, --artifact-only, or --installed-golden-wheel")
    if args.check and not _SHA_RE.fullmatch(args.candidate_sha or ""):
        parser.error("--check requires --candidate-sha with one 40-hex SHA")

    root = Path(__file__).resolve().parent.parent

    if args.installed_golden_wheel:
        rows = _run_installed_golden_wheel(root, args.installed_golden_wheel)
        ok = bool(rows) and all(row["status"] == "pass" for row in rows)
        result = {"ok": ok, "completion": "complete" if ok else "failed", "rows": rows}
    else:
        result = run_readiness(
            root,
            artifact_only=args.artifact_only,
            public_admission=args.public_admission,
            version=args.version or "",
            repo=args.repo,
            remote=args.remote,
            branch=args.branch,
            package=args.package,
            candidate_sha=args.candidate_sha,
            required_check_name=args.required_check_name,
            audit_max_age_hours=args.audit_max_age_hours,
        )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for row in result["rows"]:
            mark = (
                "PASS" if row["status"] == "pass" else "SKIP" if row["status"] == "skip" else "FAIL"
            )
            print(f"  [{mark}] {row['id']}: {row['detail']}")
        if result["ok"]:
            passing = sum(1 for r in result["rows"] if r["status"] == "pass")
            print(f"release-readiness-gate: OK ({passing}/{len(result['rows'])} checks passed)")
        else:
            failing = [r["id"] for r in result["rows"] if r["status"] not in ("pass", "skip")]
            print(f"release-readiness-gate: FAIL ({failing})", file=sys.stderr)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
