#!/usr/bin/env python3
"""Verify public documentation against local package, MCP, and release metadata.

The guard is stdlib-only so it can run in lint CI without importing package
dependencies. It reads the MCP registry, the CLI argparse tree, packaging
metadata, release/dependency-gate workflows, and the canonical verification
command list as plain source text (AST/TOML/YAML-adjacent text parsing —
never `import mempalace_code` and never executes a workflow), then checks the
public files that repeat those facts.

Usage:
    python scripts/docs_drift_guard.py
    python scripts/docs_drift_guard.py --root /path/to/checkout --json
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


ABOUT_TEMPLATE = (
    "Offline-first AI memory for coding — {tool_count} MCP tools, temporal knowledge graph, "
    "and local vector search. No API keys, no cloud, no server."
)

# Documented verification-command coverage per public surface. Each name must be
# a key in scripts/quality_scorecard.py's _VERIFICATION_COMMANDS. Detailed
# release commands belong to docs/RELEASING.md; the release skill only routes to
# that canonical runbook and names its two entry-point gates.
VERIFICATION_COMMAND_SURFACES: dict[str, tuple[str, ...]] = {
    ".claude/skills/verify/INSTRUCTIONS.md": (
        "lint",
        "format",
        "tests",
        "typecheck",
        "typecheck_strict_slice",
        "public_safety",
        "scorecard",
        "architecture_guard",
    ),
    "AGENTS.md": ("lint", "format", "tests", "typecheck"),
    "docs/quality/README.md": ("scorecard", "public_safety"),
}

CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND = (
    "python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream"
)
LIVE_RELEASE_PREFLIGHT_COMMAND_SURFACES: tuple[str, ...] = (
    "docs/RELEASING.md",
    ".claude/skills/release-prep/SKILL.md",
    "docs/UPSTREAM_COMPARISON.md",
)
CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND = (
    "python scripts/release_preflight.py --tag vX.Y.Z --require-clean "
    "--expect-sha <40-hex-candidate-sha> --check-public-main "
    "--check-required-check --check-dependency-audit --check-branch-rules "
    "--check-tag-ruleset"
)
CANONICAL_RELEASE_STATUS_COMMAND = (
    "python scripts/release_status_gate.py --version X.Y.Z "
    "--repo rergards/mempalace-code --remote publish --branch main "
    "--expect-sha <40-hex-candidate-sha>"
)
CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND = (
    "gh run rerun <publish-workflow-run-id> --job <github-release-job-id> "
    "--repo rergards/mempalace-code"
)
EXACT_SHA_RELEASE_COMMAND_SURFACES: tuple[str, ...] = ("docs/RELEASING.md",)
PARTIAL_PUBLICATION_RECOVERY_SURFACES: tuple[str, ...] = (
    "docs/RELEASING.md",
    "docs/release-admission-rulesets.md",
)
# Prose markers that no code constant owns. Everything the admission library does
# define — check name, ref patterns, rule types, acknowledged orphan tags, audit
# window — is derived from that module instead, so the contract cannot drift.
RELEASE_ADMISSION_PROSE_MARKERS: tuple[str, ...] = (
    "refs/heads/main",
    "force-push",
    "break-glass",
    "audit log",
    "read-only",
)
PUBLIC_READ_BOUNDARY_MARKERS: tuple[str, ...] = (
    "credential-free public-read transport",
    "separate explicit authorization",
)
DEPENDENCY_AUDIT_PROSE_MARKERS: tuple[str, ...] = (
    "Dependency Audit",
    "Release admission",
    "scripts/release_admission_checks.py",
)

_ADMISSION_CHECKS_MODULE = None
_RELEASE_STATUS_GATE_MODULE = None


def _load_admission_checks():
    """Load the sibling release_admission_checks.py by path (not a project import).

    Loaded from this script's own directory, not from the inspected ``root``: the
    admission constants are the contract being enforced, so a fixture or a
    checkout under review must never be able to supply its own version of them.
    """
    global _ADMISSION_CHECKS_MODULE
    if _ADMISSION_CHECKS_MODULE is None:
        module_name = "release_admission_checks"
        path = Path(__file__).resolve().parent / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _ADMISSION_CHECKS_MODULE = module
    return _ADMISSION_CHECKS_MODULE


def release_admission_markers() -> tuple[str, ...]:
    """Literals docs/release-admission-rulesets.md must carry, derived from code."""
    admission = _load_admission_checks()
    return (
        *RELEASE_ADMISSION_PROSE_MARKERS,
        admission.AGGREGATE_REQUIRED_CHECK,
        admission.TAG_RULESET_REF,
        *admission.MAIN_BRANCH_REQUIRED_RULE_TYPES,
        *admission.TAG_RULESET_REQUIRED_RULE_TYPES,
        *admission.RELEASE_CRITICAL_CI_JOBS,
        # An exempt CI job must be named in the doc too, so no job can be excused
        # from the aggregate check without a publicly recorded reason.
        *admission.AGGREGATE_EXEMPT_CI_JOBS,
        *admission.ACKNOWLEDGED_ORPHAN_TAGS,
    )


def _load_release_status_gate():
    """Load the sibling release_status_gate.py by path (not a project import).

    Loaded from this script's own directory for the same reason as the admission
    constants: the required surface list is the contract being enforced, so an
    inspected checkout must never be able to supply a shorter one.
    """
    global _RELEASE_STATUS_GATE_MODULE
    if _RELEASE_STATUS_GATE_MODULE is None:
        module_name = "release_status_gate"
        path = Path(__file__).resolve().parent / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _RELEASE_STATUS_GATE_MODULE = module
    return _RELEASE_STATUS_GATE_MODULE


def release_status_surface_names() -> tuple[str, ...]:
    """Surface rows the release skill must document, derived from the gate."""
    return tuple(_load_release_status_gate().REQUIRED_SURFACES)


def dependency_audit_markers() -> tuple[str, ...]:
    """Literals docs/DEPENDENCY_UPGRADE_GATE.md must carry, derived from code."""
    admission = _load_admission_checks()
    return (
        *DEPENDENCY_AUDIT_PROSE_MARKERS,
        f"{admission.DEFAULT_AUDIT_MAX_AGE_HOURS} hours",
    )


# Public surfaces that repeat measured token-delta benchmark facts. Each surface is
# only required to carry the subset of facts relevant to it — the marketing-safe
# comparison snippet doesn't need retrieval precision, for example.
BENCHMARK_FIXTURE_FACTS_PATH = "benchmarks/token_delta_fixture_facts.json"
BENCHMARK_FACT_SURFACES: dict[str, tuple[str, ...]] = {
    "README.md": ("median_ratio", "peak_ratio"),
    "docs/BENCH_TOKEN_DELTA.md": (
        "median_ratio",
        "mean_ratio",
        "peak_ratio",
        "retrieval_precision_at_5",
    ),
    "docs/COMPARISON_GRAPHIFY.md": ("median_ratio", "peak_ratio"),
}

# Stale project-size/ratio claims from a superseded, unreproducible private fixture.
# Public docs must not repeat these regardless of what the current fixture measures.
STALE_BENCHMARK_MARKERS: tuple[str, ...] = ("19k chunk", "19k-chunk", "19,308", "595x")

# The AAAK Dialect compressor has no measured reduction-ratio benchmark. Public
# surfaces must describe it as lossy summarization/abbreviation, not repeat the
# unsupported "~30x" claim.
AAAK_SURFACES: tuple[str, ...] = ("README.md", "mempalace_code/cli.py")
UNSUPPORTED_AAAK_MARKERS: tuple[str, ...] = ("~30x", "30x reduction", "approximately 30x")

# Public-safe, machine-readable provenance for the four README retrieval-quality rows.
RETRIEVAL_QUALITY_FACTS_PATH = "benchmarks/retrieval_quality_facts.json"
RETRIEVAL_QUALITY_SCHEMA_VERSION = 1
_RETRIEVAL_CODE_STRING_FIELDS: tuple[str, ...] = ("source", "model", "date")
_RETRIEVAL_CODE_NUMERIC_FIELDS: tuple[str, ...] = (
    "query_count",
    "chunk_count",
    "r_at_5",
    "r_at_10",
)
_RETRIEVAL_DOTNET_STRING_FIELDS: tuple[str, ...] = (
    "source",
    "repo",
    "repo_commit",
    "measured_date",
    "reproduction_command",
)
_RETRIEVAL_DOTNET_NUMERIC_FIELDS: tuple[str, ...] = ("vector_r_at_5", "hybrid_r_at_5")

# The offline guide must keep every network-capable escape hatch and its recovery
# boundary explicit for airgapped users and degraded agents.
OFFLINE_USAGE_DISCLOSURE_MARKERS: tuple[str, ...] = (
    "With version checks disabled",
    "`update status` and `update check`",
    "refreshes canonical package metadata",
    "does not block updater PyPI requests",
    "While offline, do not run `update status`, `update check`, `update apply --yes`, or scheduled update execution.",
    "EntityRegistry.research()",
    "English Wikipedia REST API",
    "flows never call this method",
)

# Current public docs may mention ChromaDB only as migration input or historical
# upstream evidence. These markers identify the old current-runtime support claims.
CHROMA_RUNTIME_SUPPORT_MARKERS: dict[str, tuple[str, ...]] = {
    "CONTRIBUTING.md": ("deprecated legacy optional extra (`.[chroma]`)",),
    "README.md": (
        "ChromaDB only, as a deprecated optional",
        "ChromaDB legacy backend",
    ),
    "mempalace_code/README.md": ("ChromaDB is a deprecated optional legacy backend",),
    "AGENTS.md": (
        "ChromaDB legacy backend",
        "ChromaDB is a legacy optional backend",
    ),
    "docs/BACKUP_RESTORE.md": ("Install the `[chroma]` extra",),
    "docs/UPDATES.md": ("legacy `chroma` extras",),
    "docs/UPSTREAM_COMPARISON.md": ("backend-chromadb-optional-deprecated",),
    "docs/WHY_THIS_FORK.md": ("kept as an opt-in `.[chroma]` extra",),
    "docs/UPSTREAM_HARDENING.md": (
        "ChromaDB remains migration input through `.[chroma-migration]`",
        "one-way `migrate-storage` bridge installed through `.[chroma-migration]`",
        "one-way migration bridge",
    ),
    ".claude/skills/verify/INSTRUCTIONS.md": (
        "runtime compatibility",
        "ChromaStore compatibility",
    ),
}
CHROMA_RECOVERY_COMMAND = (
    "uvx --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify"
)

BACKUP_RESTORE_REBUILD_SEQUENCE: tuple[str, ...] = (
    'mempalace-code --palace "$PALACE" export --only-manual --with-kg --out "$EXPORT_JSONL"',
    'mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run',
    'mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"',
    'tar -tzf "$BACKUP_TAR"',
    'mv "$PALACE" "$QUARANTINE"',
    'mempalace-code --palace "$PALACE" mine "$SOURCE"',
    'mempalace-code --palace "$PALACE" import "$EXPORT_JSONL"',
    'mempalace-code --palace "$PALACE" health',
    'mempalace-code --palace "$PALACE" search "$KNOWN_QUERY" --limit 5',
)
BACKUP_RESTORE_RECOVERY_SEQUENCE: tuple[str, ...] = (
    'test -d "$QUARANTINE/lance"',
    'test ! -e "$FAILED_REBUILD"',
    'if test -e "$PALACE" || test -L "$PALACE"; then',
    'mv "$PALACE" "$FAILED_REBUILD"',
    "fi",
    'test ! -e "$PALACE"',
    'test ! -L "$PALACE"',
    'mv "$QUARANTINE" "$PALACE"',
    'mempalace-code --palace "$PALACE" health',
)
BACKUP_RESTORE_FORCE_SEQUENCE: tuple[str, ...] = (
    'test -f "$ARCHIVE"',
    'test -d "$RESTORE_TARGET/lance"',
    'test ! -e "$CURRENT_BACKUP"',
    "printf 'Restore target: %s\\n' \"$RESTORE_TARGET\"",
    "printf 'KG destination: %s\\n' \"$KG_DEST\"",
    'tar -tzf "$ARCHIVE"',
    'mempalace-code --palace "$RESTORE_TARGET" backup create --out "$CURRENT_BACKUP"',
    'tar -tzf "$CURRENT_BACKUP"',
    'mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE" --force',
    'mempalace-code --palace "$RESTORE_TARGET" health',
)
BACKUP_RESTORE_TARBALL_SEQUENCE: tuple[str, ...] = (
    'test -d "$PALACE/lance"',
    'test ! -e "$BACKUP_TAR"',
    'mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"',
    'tar -tzf "$BACKUP_TAR"',
    'test -f "$ARCHIVE"',
    'tar -tzf "$ARCHIVE"',
    'test ! -e "$RESTORE_TARGET"',
    'mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE"',
    'mempalace-code --palace "$RESTORE_TARGET" health',
)
BACKUP_RESTORE_RUNBOOK_MARKERS: tuple[str, ...] = (
    'PALACE="${HOME}/.mempalace/palace"',
    'EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"',
    'BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"',
    'QUARANTINE="${PALACE}.quarantine-$(date -u +%Y%m%dT%H%M%SZ)"',
    ': "${PALACE:?set PALACE to the inspected active palace}"',
    ': "${EXPORT_JSONL:?set EXPORT_JSONL to a new JSONL path}"',
    ': "${BACKUP_TAR:?set BACKUP_TAR to a new tar path}"',
    ': "${QUARANTINE:?set QUARANTINE to a new sibling path}"',
    'test ! -e "$EXPORT_JSONL"',
    'test ! -e "$BACKUP_TAR"',
    'test ! -e "$QUARANTINE"',
    'mv "$QUARANTINE" "$PALACE"',
    "Keep `$QUARANTINE`,",
    "Only then may you dispose of the",
    "separate global KG",
    "<palace>/knowledge_graph.sqlite3",
    'test ! -e "$RESTORE_TARGET"',
    "refuses when its checks find state in the selected palace or at the selected KG destination.",
    "real empty palace directory remains reusable.",
    "claims the exact `lance/` name exclusively",
    "creates the exact KG destination with an atomic no-replace hard link",
    "If either name is raced in, restore preserves it",
    "KG publication failure also removes the Lance root still owned by that invocation",
    "Unsupported hard links fail closed.",
    "does not make arbitrary concurrent edits elsewhere under the palace transactional and does not protect concurrent replacement of the palace root or its ancestors.",
    "preserves unrelated entries in a real palace directory",
    "Symlink objects found at the selected palace, Lance, or KG validation boundary are replaced without modifying their referents",
    "back up that file separately before adding `--force`",
    ': "${KG_DEST:?set KG_DEST to the selected KG destination}"',
    "repair --rollback --dry-run",
)
README_BACKUP_RESTORE_MARKERS: tuple[str, ...] = (
    'mempalace-code --palace "$PALACE" export --only-manual --with-kg --out "$EXPORT_JSONL"',
    'mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run',
    'mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"',
    "tar restore refuses state found at the selected palace or KG during its checks",
    "claims the exact `lance/` name exclusively",
    "publishes the KG with an atomic no-replace operation",
    "existing real empty palace directory is the only reusable initial state",
    "Unsupported no-replace KG publication fails closed.",
    "not a transaction for concurrent replacement of the palace root or its ancestors, or for arbitrary edits elsewhere in the palace.",
    "Back up every reported destination before an intentional `--force` restore",
    "docs/BACKUP_RESTORE.md",
    "separate global KG",
    "<palace>/knowledge_graph.sqlite3",
    "repair --rollback --dry-run",
)
README_ALLOWED_RESTORE_COMMANDS: frozenset[str] = frozenset({"mempalace-code restore <archive>"})
RUNBOOK_ALLOWED_RESTORE_COMMANDS: frozenset[str] = frozenset(
    {
        'mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE"',
        'mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE" --force',
        "mempalace-code --palace ~/my_palace restore ~/backup.tar.gz",
        "mempalace-code --palace ~/my_palace restore ~/backup.tar.gz --kg-path ~/shared_kg.sqlite3",
        "mempalace-code restore ~/backup.tar.gz",
    }
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _assignment(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is not None and any(
                isinstance(target, ast.Name) and target.id == name for target in targets
            ):
                return node.value
    raise ValueError(f"could not find assignment to {name}")


def _literal_tool_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    value = _assignment(tree, "TOOL_SPECS")
    if not isinstance(value, ast.Dict):
        raise ValueError(f"{path}: TOOL_SPECS is not a dict literal")
    names: list[str] = []
    for key in value.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise ValueError(f"{path}: TOOL_SPECS contains a non-string key")
        names.append(key.value)
    return names


def registry_tool_names(root: Path) -> list[str]:
    """Read registry families without importing runtime dependencies."""
    registry_path = root / "mempalace_code" / "mcp" / "registry.py"
    tree = ast.parse(registry_path.read_text(encoding="utf-8"), filename=str(registry_path))
    family_paths: list[Path] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level != 1 or not node.module:
            continue
        if not node.module.startswith("tools."):
            continue
        if not any(alias.name == "TOOL_SPECS" for alias in node.names):
            continue
        family_paths.append(root / "mempalace_code" / "mcp" / f"{node.module.replace('.', '/')}.py")

    if not family_paths:
        raise ValueError("MCP registry declares no TOOL_SPECS families")

    names: list[str] = []
    for family_path in family_paths:
        names.extend(_literal_tool_names(family_path))
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate MCP tool names in registry families: {', '.join(duplicates)}")
    return names


def _frozenset_literals(value: ast.AST, path: Path) -> set[str]:
    if (
        not isinstance(value, ast.Call)
        or not isinstance(value.func, ast.Name)
        or value.func.id != "frozenset"
    ):
        raise ValueError(f"{path}: profile value is not frozenset(...)")
    if not value.args:
        return set()
    try:
        members = ast.literal_eval(value.args[0])
    except ValueError as exc:
        raise ValueError(f"{path}: profile contains non-literal members") from exc
    if not isinstance(members, set) or not all(isinstance(name, str) for name in members):
        raise ValueError(f"{path}: profile members are not a string set")
    return set(members)


def profile_tools(root: Path, all_tools: Iterable[str]) -> dict[str, set[str]]:
    path = root / "mempalace_code" / "mcp_tool_profiles.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    value = _assignment(tree, "PROFILES")
    if not isinstance(value, ast.Dict):
        raise ValueError(f"{path}: PROFILES is not a dict literal")
    all_tool_set = set(all_tools)
    result: dict[str, set[str]] = {}
    for key, profile_value in zip(value.keys, value.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise ValueError(f"{path}: profile has a non-string name")
        name = key.value
        members = _frozenset_literals(profile_value, path)
        result[name] = all_tool_set if name == "full" else members

    unknown = sorted({member for members in result.values() for member in members} - all_tool_set)
    if unknown:
        raise ValueError(f"profile references unknown tools: {', '.join(unknown)}")
    return result


def package_metadata(root: Path) -> tuple[str, str]:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    version = project.get("version")
    requires_python = project.get("requires-python")
    if not isinstance(version, str) or not isinstance(requires_python, str):
        raise ValueError("pyproject.toml must define project.version and project.requires-python")
    return version, requires_python


def optional_extras(root: Path) -> list[str]:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    extras = data.get("project", {}).get("optional-dependencies", {})
    if not isinstance(extras, dict) or not extras:
        raise ValueError("pyproject.toml must define project.optional-dependencies")
    return sorted(extras.keys())


def cli_command_inventory(path: Path) -> tuple[list[str], int]:
    """Derive the top-level CLI command inventory from argparse add_parser() calls.

    Returns ``(top_level_commands, nested_command_count)``. Only the master
    ``parser.add_subparsers()`` group is validated against documentation;
    nested subcommands (``diary write``, ``backup create``, ...) are counted
    but not individually required in docs, keeping the check narrowly tied to
    the argparse call patterns actually present in cli.py.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parser_var: str | None = None
    subparsers_owner: dict[str, str] = {}
    add_parser_calls: list[tuple[str, str]] = []

    # add_subparsers() results are always assigned (the variable is needed to
    # add children later), so that half of the extraction only looks at
    # assignments. add_parser() results are frequently *not* assigned — e.g.
    # a nested subcommand with no further arguments/subcommands of its own —
    # so that half walks every Call node regardless of statement shape.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
        ):
            target_name = node.targets[0].id
            receiver = node.value.func.value.id
            if node.value.func.attr == "ArgumentParser" and parser_var is None:
                parser_var = target_name
            elif node.value.func.attr == "add_subparsers":
                subparsers_owner[target_name] = receiver
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.attr == "add_parser"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            add_parser_calls.append((node.func.value.id, node.args[0].value))

    if parser_var is None:
        raise ValueError(f"{path}: could not find a top-level argparse.ArgumentParser() assignment")
    master_sub_vars = sorted(
        {var for var, owner in subparsers_owner.items() if owner == parser_var}
    )
    if len(master_sub_vars) != 1:
        raise ValueError(
            f"{path}: expected exactly one top-level add_subparsers() call, "
            f"found {len(master_sub_vars)}"
        )
    master_sub_var = master_sub_vars[0]

    top_level = sorted({name for receiver, name in add_parser_calls if receiver == master_sub_var})
    if not top_level:
        raise ValueError(f"{path}: no top-level CLI commands found via add_parser()")
    nested_command_count = sum(1 for receiver, _ in add_parser_calls if receiver != master_sub_var)
    return top_level, nested_command_count


def canonical_verification_commands(root: Path) -> dict[str, str]:
    path = root / "scripts" / "quality_scorecard.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    value = _assignment(tree, "_VERIFICATION_COMMANDS")
    if not isinstance(value, ast.Tuple):
        raise ValueError(f"{path}: _VERIFICATION_COMMANDS is not a tuple literal")
    result: dict[str, str] = {}
    for item in value.elts:
        if not isinstance(item, ast.Tuple) or len(item.elts) != 2:
            raise ValueError(f"{path}: _VERIFICATION_COMMANDS entries must be 2-tuples")
        name_node, cmd_node = item.elts
        if not (
            isinstance(name_node, ast.Constant)
            and isinstance(name_node.value, str)
            and isinstance(cmd_node, ast.Constant)
            and isinstance(cmd_node.value, str)
        ):
            raise ValueError(f"{path}: _VERIFICATION_COMMANDS entries must be string literals")
        result[name_node.value] = cmd_node.value
    if not result:
        raise ValueError(f"{path}: _VERIFICATION_COMMANDS is empty")
    return result


def benchmark_fixture_facts(root: Path) -> dict:
    """Load the committed, sanitized token-delta benchmark fixture facts."""
    path = root / BENCHMARK_FIXTURE_FACTS_PATH
    if not path.exists():
        raise ValueError(
            f"required benchmark fixture facts file is missing: {BENCHMARK_FIXTURE_FACTS_PATH}"
        )
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{BENCHMARK_FIXTURE_FACTS_PATH}: must contain a JSON object")
    for field in ("median_ratio", "mean_ratio", "peak_ratio", "retrieval_precision_at_5"):
        if not isinstance(data.get(field), (int, float)):
            raise ValueError(
                f"{BENCHMARK_FIXTURE_FACTS_PATH}: missing or non-numeric field {field!r}"
            )
    return data


def benchmark_fact_label(name: str, value: float) -> str:
    """Render a fixture-facts numeric field the way public docs must quote it."""
    if name == "retrieval_precision_at_5":
        return f"{round(value * 100)}%"
    return f"{round(value, 1)}x"


def retrieval_quality_facts(root: Path) -> dict:
    """Load the committed retrieval-quality benchmark provenance facts."""
    path = root / RETRIEVAL_QUALITY_FACTS_PATH
    if not path.exists():
        raise ValueError(
            f"required retrieval quality facts file is missing: {RETRIEVAL_QUALITY_FACTS_PATH}"
        )
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{RETRIEVAL_QUALITY_FACTS_PATH}: must contain a JSON object")
    schema_version = data.get("schema_version")
    if schema_version != RETRIEVAL_QUALITY_SCHEMA_VERSION:
        raise ValueError(
            f"{RETRIEVAL_QUALITY_FACTS_PATH}: schema_version must be "
            f"{RETRIEVAL_QUALITY_SCHEMA_VERSION}, got {schema_version!r}"
        )
    code = data.get("code_minilm")
    dotnet = data.get("dotnet_cleanarchitecture")
    if not isinstance(code, dict) or not isinstance(dotnet, dict):
        raise ValueError(
            f"{RETRIEVAL_QUALITY_FACTS_PATH}: must contain 'code_minilm' and "
            "'dotnet_cleanarchitecture' objects"
        )
    for field in _RETRIEVAL_CODE_STRING_FIELDS:
        if not isinstance(code.get(field), str) or not code.get(field):
            raise ValueError(
                f"{RETRIEVAL_QUALITY_FACTS_PATH}: code_minilm.{field} missing or not a string"
            )
    for field in _RETRIEVAL_CODE_NUMERIC_FIELDS:
        if not isinstance(code.get(field), (int, float)) or isinstance(code.get(field), bool):
            raise ValueError(f"{RETRIEVAL_QUALITY_FACTS_PATH}: code_minilm.{field} missing")
    for field in _RETRIEVAL_DOTNET_STRING_FIELDS:
        if not isinstance(dotnet.get(field), str) or not dotnet.get(field):
            raise ValueError(
                f"{RETRIEVAL_QUALITY_FACTS_PATH}: dotnet_cleanarchitecture.{field} "
                "missing or not a string"
            )
    for field in _RETRIEVAL_DOTNET_NUMERIC_FIELDS:
        if not isinstance(dotnet.get(field), (int, float)) or isinstance(dotnet.get(field), bool):
            raise ValueError(
                f"{RETRIEVAL_QUALITY_FACTS_PATH}: dotnet_cleanarchitecture.{field} missing"
            )
    return data


def retrieval_quality_pct(value: float) -> str:
    """Render a retrieval-quality fraction the way README.md must quote it."""
    pct = round(value * 100, 1)
    if pct == 100:
        return "100%"
    return f"{pct:.1f}%"


def python_classifier_versions(root: Path) -> list[str]:
    """Derive explicit supported Python minor versions from pyproject.toml classifiers."""
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    classifiers = data.get("project", {}).get("classifiers", [])
    if not isinstance(classifiers, list) or not classifiers:
        raise ValueError("pyproject.toml must define project.classifiers")
    pattern = re.compile(r"^Programming Language :: Python :: (3\.\d+)$")
    versions: list[str] = []
    for classifier in classifiers:
        if not isinstance(classifier, str):
            raise ValueError("pyproject.toml: project.classifiers entries must be strings")
        match = pattern.match(classifier)
        if match:
            versions.append(match.group(1))
    if not versions:
        raise ValueError(
            "pyproject.toml: no 'Programming Language :: Python :: 3.NN' classifiers found"
        )
    return sorted(
        set(versions), key=lambda version: tuple(int(part) for part in version.split("."))
    )


def ci_test_matrix_python_versions(root: Path) -> list[str]:
    """Read the Tests workflow's test-job python-version matrix as plain text."""
    text = _text(root, ".github/workflows/ci.yml")
    match = re.search(r"python-version:\s*\[([^\]]*)\]", text)
    if match is None:
        raise ValueError(".github/workflows/ci.yml: test job python-version matrix not found")
    versions = re.findall(r'"(3\.\d+)"', match.group(1))
    if not versions:
        raise ValueError(".github/workflows/ci.yml: test job python-version matrix is empty")
    return versions


def workflow_name(root: Path, relative_path: str) -> str:
    path = root / relative_path
    if not path.exists():
        raise ValueError(f"required workflow file is missing: {relative_path}")
    match = re.search(r"^name:\s*(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise ValueError(f"{relative_path}: workflow 'name:' field not found")
    return match.group(1).strip()


def _text(root: Path, relative_path: str) -> str:
    path = root / relative_path
    if not path.exists():
        raise ValueError(f"required documentation file is missing: {relative_path}")
    return path.read_text(encoding="utf-8")


def _require(errors: list[str], text: str, needle: str, path: str) -> None:
    if needle not in text:
        errors.append(f"{path}: missing expected text: {needle!r}")


def _normalize_whitespace(text: str) -> str:
    """Collapse whitespace runs (including line-wrap newlines) to a single space."""
    return re.sub(r"\s+", " ", text)


def _require_wrap_tolerant(errors: list[str], text: str, needle: str, path: str) -> None:
    """Like _require, but matches across normal Markdown line-wrapping.

    A disclosure phrase spanning a wrapped line (e.g. "English Wikipedia" then
    "REST API" on the next line) is semantically present even though the raw
    substring check would miss the embedded newline.
    """
    if _normalize_whitespace(needle) not in _normalize_whitespace(text):
        errors.append(f"{path}: missing expected text: {needle!r}")


def _ordered_unique_errors(text: str, markers: tuple[str, ...], path: str) -> list[str]:
    """Require one copy of each marker in the declared order."""
    errors: list[str] = []
    lines = [line.strip() for line in text.splitlines()]
    positions: list[int] = []
    for marker in markers:
        count = lines.count(marker)
        if count != 1:
            errors.append(f"{path}: expected exactly one recovery step {marker!r}; found {count}")
        positions.append(lines.index(marker) if marker in lines else -1)
    present_positions = [position for position in positions if position >= 0]
    if len(present_positions) == len(markers) and present_positions != sorted(present_positions):
        errors.append(f"{path}: recovery steps are out of order")
    return errors


def backup_restore_contract_errors(readme: str, runbook: str) -> list[str]:
    """Validate the public backup and recovery command contract."""
    errors: list[str] = []

    for marker in README_BACKUP_RESTORE_MARKERS:
        _require_wrap_tolerant(errors, readme, marker, "README.md")
    for marker in BACKUP_RESTORE_RUNBOOK_MARKERS:
        _require_wrap_tolerant(errors, runbook, marker, "docs/BACKUP_RESTORE.md")

    rebuild_heading = "## Recommended Rebuild Workflow"
    recovery_heading = "### Failure recovery"
    restore_heading = "## Restore Procedure"
    if (
        rebuild_heading not in runbook
        or recovery_heading not in runbook
        or restore_heading not in runbook
    ):
        errors.append("docs/BACKUP_RESTORE.md: canonical rebuild section is missing")
    else:
        rebuild = runbook.split(rebuild_heading, 1)[1].split(recovery_heading, 1)[0]
        errors.extend(
            _ordered_unique_errors(
                rebuild, BACKUP_RESTORE_REBUILD_SEQUENCE, "docs/BACKUP_RESTORE.md"
            )
        )
        recovery = runbook.split(recovery_heading, 1)[1].split(restore_heading, 1)[0]
        errors.extend(
            _ordered_unique_errors(
                recovery, BACKUP_RESTORE_RECOVERY_SEQUENCE, "docs/BACKUP_RESTORE.md"
            )
        )

    force_heading = (
        "`--force` replaces the target's managed `lance/` data and atomically replaces the\n"
        "selected KG after archive validation."
    )
    kg_heading = "### Tarball Restore — KG Destination"
    if force_heading not in runbook or kg_heading not in runbook:
        errors.append("docs/BACKUP_RESTORE.md: inspected force-restore section is missing")
    else:
        force_restore = runbook.split(force_heading, 1)[1].split(kg_heading, 1)[0]
        errors.extend(
            _ordered_unique_errors(
                force_restore, BACKUP_RESTORE_FORCE_SEQUENCE, "docs/BACKUP_RESTORE.md"
            )
        )

    tarball_heading = "## Tarball Backup (Full Snapshot)"
    if tarball_heading not in runbook or force_heading not in runbook:
        errors.append("docs/BACKUP_RESTORE.md: safe tarball restore section is missing")
    else:
        tarball_restore = runbook.split(tarball_heading, 1)[1].split(force_heading, 1)[0]
        errors.extend(
            _ordered_unique_errors(
                tarball_restore,
                BACKUP_RESTORE_TARBALL_SEQUENCE,
                "docs/BACKUP_RESTORE.md",
            )
        )

    destructive_active_palace = re.compile(
        r"(?m)^\s*rm\s+-[^\n]*(?:r[^\n]*f|f[^\n]*r)[^\n]*(?:\$PALACE|\.mempalace/palace)"
    )
    documented_restore_commands = {
        "README.md": README_ALLOWED_RESTORE_COMMANDS,
        "docs/BACKUP_RESTORE.md": RUNBOOK_ALLOWED_RESTORE_COMMANDS,
    }
    for path, text in (("README.md", readme), ("docs/BACKUP_RESTORE.md", runbook)):
        if destructive_active_palace.search(text):
            errors.append(
                f"{path}: executable recursive deletion of the active palace is forbidden"
            )
        for line in text.splitlines():
            command = line.strip()
            if not command.startswith("mempalace-code "):
                continue
            normalized_command = command.split("#", 1)[0].rstrip()
            if (
                " restore " in f" {normalized_command} "
                and normalized_command not in documented_restore_commands[path]
            ):
                errors.append(
                    f"{path}: restore command is not an approved documented form: "
                    f"{normalized_command!r}"
                )
            if re.search(r"(?:^|\s)export(?:\s|$)", command) and "--out" not in command:
                errors.append(f"{path}: export command is missing required --out: {command!r}")
            if (
                " repair " in f" {command} "
                and "--dry-run" in command
                and "--rollback" not in command
            ):
                errors.append(f"{path}: repair --dry-run requires --rollback: {command!r}")
            if (
                " restore " in f" {command} "
                and "--force" in command
                and normalized_command
                != 'mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE" --force'
            ):
                errors.append(f"{path}: force restore bypasses the inspected recovery path")
        for unsafe_claim in ("prompts before overwrite", "overwrite without prompt"):
            if unsafe_claim in text.lower():
                errors.append(f"{path}: restore documentation promises a nonexistent prompt")

    if runbook.splitlines().count(BACKUP_RESTORE_FORCE_SEQUENCE[-2]) != 1:
        errors.append("docs/BACKUP_RESTORE.md: force restore must appear once in its gated path")

    return errors


def _marker_block(text: str, marker: str) -> str | None:
    """Return the body between ``<!-- marker start -->`` and ``<!-- marker end -->``."""
    pattern = re.compile(
        rf"<!-- {re.escape(marker)} start -->(.*?)<!-- {re.escape(marker)} end -->",
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _profile_block(text: str, profile: str) -> str | None:
    return _marker_block(text, f"mcp-profile:{profile}")


def _first_release_version(changelog: str) -> str | None:
    match = re.search(r"^## v([^\s]+)\s+—", changelog, re.MULTILINE)
    return match.group(1) if match else None


def changelog_shape_errors(changelog: str) -> list[str]:
    """Reject per-task changelog headers and duplicate release headers.

    Release-prep consolidates the ``## YYYY-MM-DD · TASK-SLUG`` entries that land
    with each task into one release header. Leaving both forms ships a changelog
    whose top reads as several releases.
    """
    errors: list[str] = []

    # Only the top of the file is governed. Entries below the newest release header
    # are published history from before per-release consolidation existed.
    first_release = re.search(r"^## v[^\s]+\s+—", changelog, re.MULTILINE)
    head = changelog[: first_release.start()] if first_release else changelog
    task_headers = re.findall(r"^## \d{4}-\d{2}-\d{2} · (\S+)", head, re.MULTILINE)
    if task_headers:
        errors.append(
            "CHANGELOG.md: per-task headers above the release header must be "
            f"consolidated into it: {', '.join(sorted(set(task_headers)))}"
        )

    versions = re.findall(r"^## v([^\s]+)\s+—", changelog, re.MULTILINE)
    duplicates = sorted({v for v in versions if versions.count(v) > 1})
    if duplicates:
        errors.append(
            f"CHANGELOG.md: duplicate release headers for {', '.join(duplicates)}; "
            "one release header per version"
        )
    return errors


AGENT_PLUGIN_RECOVERY_COMMAND = "mempalace-code agent-plugin path --json"
_MANAGED_START = "<!-- mempalace-rules:start -->"
_MANAGED_END = "<!-- mempalace-rules:end -->"
_INSTRUCTION_TARGET = re.compile(
    r"(?:CLAUDE\.md|AGENTS\.md|GEMINI\.md|\.cursorrules|system prompts?|"
    r"agent(?:'s)? instructions?|agent instruction files?|instruction[- ]files?|"
    r"authority files?)",
    re.I,
)
_USAGE_RULES_TARGET = re.compile(
    r"(?:docs/LLM_USAGE_RULES\.md|(?:canonical |mempalace )?usage[- ]rules?|"
    r"usage[- ]rules block|matching profile block)",
    re.I,
)
_INSTRUCTION_MUTATION = re.compile(
    r"\b(?:add(?:ed|ing|s)?|append(?:ed|ing|s)?|appl(?:y|ied|ies|ying)|"
    r"backup(?:ped|ping|s)?|chang(?:e|ed|es|ing)|chmod|"
    r"configure|cop(?:y|ied|ies|ying)|embed|"
    r"fsync(?:ed|ing|s)?|inject(?:ed|ing|s)?|insert(?:ed|ing|s)?|"
    r"load|manage|modif(?:y|ied|ies|ying)|mutat(?:e|ed|es|ing)|"
    r"past(?:e|ed|es|ing)|place|"
    r"renam(?:e|ed|es|ing)|replac(?:e|ed|es|ing)|"
    r"restor(?:e|ed|es|ing)|retr(?:y|ied|ies|ying)|symlink(?:ed|ing|s)?|"
    r"set|sync|update|"
    r"writ(?:e|es|ing)|wrote|written)\b",
    re.I,
)
_NEGATED_MUTATION_PREFIX = re.compile(
    r"(?:do not|does not|don't|must not|should not|will not|can not|cannot|never|"
    r"instead of|without|unsupported(?: route)?|no)\b.{0,80}$",
    re.I,
)
_HISTORICAL_MUTATION_PREFIX = re.compile(
    r"(?:previously|historically|formerly|in (?:version )?v?\d[\w.-]*)\b.{0,120}$",
    re.I,
)
_CURRENT_INJECTION_CLAIM = re.compile(
    r"\b(?:covers?|supports?|provides?|performs?)\b.{0,100}"
    r"\binstruction[- ](?:injection|mutation)\b",
    re.I,
)
_EXPLICIT_NO_INSTRUCTION_MUTATION = re.compile(
    r"(?:no instruction-file operation|instruction-file mutation is unsupported|"
    r"instruction files? (?:stay|remain) unchanged)",
    re.I,
)
_ADD_USAGE_RULES = re.compile(
    r"\badd(?:ed|ing|s)?\s+(?:the\s+)?(?:canonical\s+|mempalace\s+)?"
    r"usage[- ]rules?(?:\s+block)?\b",
    re.I,
)


def _canonical_rules_block(text: str) -> tuple[str, str] | None:
    """Return normalized full block and body for one ordered line-anchored pair."""
    starts = list(re.finditer(rf"^{re.escape(_MANAGED_START)}$", text, re.M))
    ends = list(re.finditer(rf"^{re.escape(_MANAGED_END)}$", text, re.M))
    if len(starts) != 1 or len(ends) != 1 or starts[0].start() >= ends[0].start():
        return None
    block = text[starts[0].start() : ends[0].end()]
    body = text[starts[0].end() : ends[0].start()].strip("\n")

    def normalize(value: str) -> str:
        return "\n".join(line.rstrip() for line in value.splitlines()).strip()

    return normalize(block), normalize(body)


def agent_instruction_mutation_errors(text: str, path: str) -> list[str]:
    """Reject current actionable instruction-file mutation guidance by semantics."""
    path_parts = Path(path).parts
    if Path(path).name.casefold() == "changelog.md" or path_parts[:2] == ("docs", "plans"):
        return []

    # Keep wrapped prose together, but separate list items, sentences, and table
    # cells so unrelated verbs cannot pair with an authority-file mention elsewhere
    # in a large Markdown block.
    segments = re.split(
        r"\n\s*\n|\n(?=\s*(?:[-*+]\s|\d+[.)]\s|\|))|"
        r"(?<=[.!?])\s+(?=[A-Z`])|\s*[;|]\s*",
        text,
    )
    for segment in segments:
        actionable = " ".join(segment.split())
        if not actionable:
            continue
        if _EXPLICIT_NO_INSTRUCTION_MUTATION.search(actionable):
            continue

        unsafe = False
        if _CURRENT_INJECTION_CLAIM.search(actionable):
            unsafe = True
        else:
            instruction_target = _INSTRUCTION_TARGET.search(actionable)
            rules_target = _USAGE_RULES_TARGET.search(actionable)
            if instruction_target is not None and re.search(
                r"\bnot\s+$", actionable[: instruction_target.start()], re.I
            ):
                instruction_target = None
            if instruction_target is None and rules_target is None:
                continue
            for mutation in _INSTRUCTION_MUTATION.finditer(actionable):
                prefix = actionable[max(0, mutation.start() - 120) : mutation.start()]
                if _NEGATED_MUTATION_PREFIX.search(prefix):
                    continue
                if _HISTORICAL_MUTATION_PREFIX.search(prefix):
                    continue
                if instruction_target is not None:
                    forward_gap = instruction_target.start() - mutation.end()
                    reverse_gap = mutation.start() - instruction_target.end()
                    if 0 <= forward_gap <= 60 or 0 <= reverse_gap <= 60:
                        unsafe = True
                        break
                if rules_target is not None and mutation.start() < rules_target.start():
                    # A past participle can describe old state ("injected usage rules")
                    # without telling the reader to perform that operation.
                    mutation_word = mutation.group(0).casefold()
                    if mutation_word.endswith(("ed", "ied")):
                        continue
                    if mutation_word.startswith(
                        ("cop", "inject", "insert", "append", "past", "writ")
                    ) or _ADD_USAGE_RULES.search(actionable):
                        unsafe = True
                        break

        if unsafe:
            return [
                f"{path}: unsupported instruction-file mutation route; stop and recover with "
                f"`{AGENT_PLUGIN_RECOVERY_COMMAND}`"
            ]
    return []


def _repository_documentation_paths(root: Path) -> list[Path]:
    """Return repository-authored Markdown while excluding generated environments."""
    excluded = {".git", ".tasks", ".venv", "venv", "build", "dist"}
    plugin_root = root / "mempalace_code" / "agent_plugin"
    in_worktree = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
        text=True,
    )
    if in_worktree.returncode == 0 and in_worktree.stdout.strip() == "true":
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "-z"],
            capture_output=True,
            check=True,
            text=True,
        )
        candidates = (root / relative for relative in tracked.stdout.split("\0") if relative)
    else:
        candidates = root.rglob("*.md")
    return sorted(
        path
        for path in candidates
        if path.is_file()
        and path.suffix == ".md"
        and not any(part in excluded for part in path.relative_to(root).parts)
        and plugin_root not in path.parents
    )


def agent_instruction_boundary_errors(root: Path, rules_text: str, install_text: str) -> list[str]:
    """Enforce one canonical full rules owner and the read-only Agent Plugin boundary."""
    errors: list[str] = []
    canonical = _canonical_rules_block(rules_text)
    if canonical is None:
        return [
            "docs/LLM_USAGE_RULES.md: needs exactly one ordered line-anchored "
            f"{_MANAGED_START} / {_MANAGED_END} pair"
        ]
    canonical_block, canonical_body = canonical

    section_start = install_text.find("## Section 7")
    section_end = install_text.find("\n## End State", section_start)
    if section_start < 0 or section_end < 0:
        errors.append("docs/AGENT_INSTALL.md: Agent Plugin instruction-loading section is missing")
    else:
        section = install_text[section_start:section_end]
        if "Agent Plugins 1.0" not in section or "read-only" not in section:
            errors.append(
                "docs/AGENT_INSTALL.md: Section 7 must use the read-only Agent Plugins 1.0 boundary"
            )
        if section.count(AGENT_PLUGIN_RECOVERY_COMMAND) != 1:
            errors.append(
                "docs/AGENT_INSTALL.md: Section 7 must contain exactly one recovery command "
                f"`{AGENT_PLUGIN_RECOVERY_COMMAND}`"
            )
        errors.extend(agent_instruction_mutation_errors(section, "docs/AGENT_INSTALL.md"))

    marker_pattern = re.compile(
        rf"^(?:{re.escape(_MANAGED_START)}|{re.escape(_MANAGED_END)})$", re.M
    )
    canonical_path = root / "docs" / "LLM_USAGE_RULES.md"
    for path in _repository_documentation_paths(root):
        if path == canonical_path:
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        errors.extend(agent_instruction_mutation_errors(text, relative))
        normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
        if (
            marker_pattern.search(text)
            or canonical_block in normalized
            or canonical_body in normalized
        ):
            errors.append(
                f"{relative}: duplicate or orphan canonical usage-rules content; "
                "keep the full block only in docs/LLM_USAGE_RULES.md"
            )

    plugin_root = root / "mempalace_code" / "agent_plugin"
    if not plugin_root.is_dir():
        errors.append("mempalace_code/agent_plugin: packaged Agent Plugin directory is missing")
    else:
        block_bytes = canonical_block.encode()
        body_bytes = canonical_body.encode()
        marker_bytes = (_MANAGED_START.encode(), _MANAGED_END.encode())
        members = sorted(candidate for candidate in plugin_root.rglob("*") if candidate.is_file())
        for path in members:
            content = path.read_bytes()
            if (
                any(marker in content for marker in marker_bytes)
                or block_bytes in content
                or body_bytes in content
            ):
                relative = path.relative_to(root).as_posix()
                errors.append(
                    f"{relative}: duplicate or orphan canonical usage-rules content; "
                    "the packaged skill must remain concise"
                )

    rules_preface = rules_text.split(_MANAGED_START, 1)[0]
    errors.extend(agent_instruction_mutation_errors(rules_preface, "docs/LLM_USAGE_RULES.md"))
    return errors


def runbook_consistency_errors(releasing_text: str, install_text: str) -> list[str]:
    """Reject ambiguous release identity and inconsistent install-question state."""
    errors: list[str] = []
    candidate_assignments = re.findall(
        r"^CANDIDATE_SHA=\$\(git commit-tree\b.*\)$", releasing_text, re.MULTILINE
    )
    if len(candidate_assignments) != 1:
        errors.append(
            "docs/RELEASING.md: expected exactly one line-anchored "
            "CANDIDATE_SHA git commit-tree assignment; "
            f"found {len(candidate_assignments)}"
        )

    section_match = re.search(
        r"^## Section 2 — Human-in-the-loop Questions\s*$"
        r"(?P<body>.*?)(?=^##\s|\Z)",
        install_text,
        re.MULTILINE | re.DOTALL,
    )
    if section_match is None:
        errors.append("docs/AGENT_INSTALL.md: Section 2 question block not found")
        return errors

    section = section_match.group("body")
    question_numbers = [
        int(value) for value in re.findall(r"^### Q(\d+) \u2014", section, re.MULTILINE)
    ]
    expected_numbers = list(range(1, 8))
    if question_numbers != expected_numbers:
        errors.append(
            "docs/AGENT_INSTALL.md: Section 2 question headings must be contiguous "
            f"Q1 through Q7; found {question_numbers}"
        )
    return errors


# The prohibition must sit next to the mention it governs — a "never" far away in
# another section does not stop a reader who only sees the flag. Windows are
# matched with Markdown emphasis stripped, so `--force` and **--force** and plain
# --force all read the same to the guard.
_FORCE_SENTINEL_WINDOW = 400
_FORCE_SENTINELS = ("never --force", "never use --force", "never rewrite")
_MARKDOWN_EMPHASIS_RE = re.compile(r"[`*_]")

# Ordered steps the public promotion sequence must keep. Pushing the candidate
# branch first means the SHA that later fast-forwards onto `main` already has its
# own green Tests and `release-required` results, so adding required checks to
# `main` later cannot deadlock the promotion. The branch is carried by one
# variable and every attempt gets its own immutable name, so a rejected candidate
# is rebuilt rather than force-updated.
_PROMOTION_MARKERS = (
    "git commit-tree",
    "publish/main",
    "CANDIDATE_BRANCH=release/vX.Y.Z",
    'git push publish "$CANDIDATE_BRANCH"',
    "release/vX.Y.Z-rc2",
    "release-required",
)


def release_promotion_errors(
    surfaces: dict[str, str], *, require_promotion_flow: bool = True
) -> list[str]:
    """Public `main` is fast-forward-only, so the docs must not tell you to push local main.

    Local `main` and public `main` are separate histories — public `main` carries
    one squashed commit per release. ``git push publish main`` from a development
    branch is rejected, and the only non-destructive fix is a candidate branch
    built with ``git commit-tree`` on top of ``publish/main``, pushed as its own
    public branch and proven green before it is fast-forwarded onto `main`.

    ``require_promotion_flow=False`` keeps the force-push and handoff safety
    checks but drops the flow markers, for a surface that hands off to the
    release procedure instead of performing publication itself. Requiring the
    markers there would push a doc into carrying commands it must never run.
    """
    errors: list[str] = []
    for path, text in surfaces.items():
        for match in re.finditer(r"^\s*git push publish main\s*$", text, re.M):
            line = text.count("\n", 0, match.start()) + 1
            errors.append(
                f"{path}:{line}: 'git push publish main' is not fast-forwardable; "
                "promote a commit-tree candidate branch to publish/main instead"
            )
        for match in re.finditer(r"--force", text):
            raw = text[
                max(0, match.start() - _FORCE_SENTINEL_WINDOW) : match.end()
                + _FORCE_SENTINEL_WINDOW
            ]
            # Strip emphasis and collapse wrapping so a sentence broken across
            # lines, or a flag in backticks, still reads as one phrase.
            window = " ".join(_MARKDOWN_EMPHASIS_RE.sub("", raw).lower().split())
            if not any(sentinel in window for sentinel in _FORCE_SENTINELS):
                line = text.count("\n", 0, match.start()) + 1
                errors.append(
                    f"{path}:{line}: '--force' has no prohibition within "
                    f"{_FORCE_SENTINEL_WINDOW} characters"
                )
        # A line-broken flag reads as guidance to run it; keep every flag on one line.
        for match in re.finditer(r"--[a-z][a-z-]*-\n", text):
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"{path}:{line}: flag name is split across lines; keep it unbroken")
        if require_promotion_flow:
            for needle in _PROMOTION_MARKERS:
                if needle not in text:
                    errors.append(f"{path}: missing the candidate-branch flow marker {needle!r}")
    return errors


def _readme_cli_commands(text: str) -> set[str] | None:
    match = re.search(
        r"<summary><strong>All CLI Commands</strong></summary>(.*?)</details>", text, re.DOTALL
    )
    if match is None:
        return None
    return set(re.findall(r"^mempalace-code ([a-z][a-z0-9-]*)", match.group(1), re.MULTILINE))


def _readme_optional_extras(text: str) -> set[str] | None:
    match = re.search(r"\*\*Optional extras:\*\*\s*```bash(.*?)```", text, re.DOTALL)
    if match is None:
        return None
    return set(re.findall(r"mempalace-code\[([a-z][a-z0-9-]*)\]", match.group(1)))


def _agents_optional_extras(text: str) -> set[str] | None:
    match = re.search(r"^Optional extras:\s*\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    if match is None:
        return None
    return set(
        re.findall(
            r"^[ \t]*-[ \t]+`\.\[([a-z][a-z0-9-]*)\]`",
            match.group(1),
            re.MULTILINE,
        )
    )


def evaluate(root: Path) -> tuple[dict[str, object], list[str]]:
    """Return public facts and any documentation drift errors."""
    errors: list[str] = []
    try:
        tools = registry_tool_names(root)
        profiles = profile_tools(root, tools)
        version, requires_python = package_metadata(root)
        extras = optional_extras(root)
        cli_top_level_commands, cli_nested_command_count = cli_command_inventory(
            root / "mempalace_code" / "cli.py"
        )
        canonical_commands = canonical_verification_commands(root)
        tests_workflow = workflow_name(root, ".github/workflows/ci.yml")
        publish_workflow = workflow_name(root, ".github/workflows/publish.yml")
        audit_workflow = workflow_name(root, ".github/workflows/dependency-audit.yml")
        bench_facts = benchmark_fixture_facts(root)
        retrieval_facts = retrieval_quality_facts(root)
        classifier_python_versions = python_classifier_versions(root)
        ci_python_versions = ci_test_matrix_python_versions(root)
    except (OSError, SyntaxError, ValueError) as exc:
        return {}, [str(exc)]

    tool_count = len(tools)
    profile_counts = {name: len(members) for name, members in sorted(profiles.items())}
    expected_about = ABOUT_TEMPLATE.format(tool_count=tool_count)
    docs = {
        "CONTRIBUTING.md": _text(root, "CONTRIBUTING.md"),
        "README.md": _text(root, "README.md"),
        "mempalace_code/README.md": _text(root, "mempalace_code/README.md"),
        "CHANGELOG.md": _text(root, "CHANGELOG.md"),
        "AGENTS.md": _text(root, "AGENTS.md"),
        "CLAUDE.md": _text(root, "CLAUDE.md"),
        "docs/AGENT_INSTALL.md": _text(root, "docs/AGENT_INSTALL.md"),
        "docs/LLM_USAGE_RULES.md": _text(root, "docs/LLM_USAGE_RULES.md"),
        "docs/RELEASING.md": _text(root, "docs/RELEASING.md"),
        "docs/release-admission-rulesets.md": _text(root, "docs/release-admission-rulesets.md"),
        "docs/BACKUP_RESTORE.md": _text(root, "docs/BACKUP_RESTORE.md"),
        "docs/UPDATES.md": _text(root, "docs/UPDATES.md"),
        "docs/DEPENDENCY_UPGRADE_GATE.md": _text(root, "docs/DEPENDENCY_UPGRADE_GATE.md"),
        "docs/quality/README.md": _text(root, "docs/quality/README.md"),
        "docs/BENCH_TOKEN_DELTA.md": _text(root, "docs/BENCH_TOKEN_DELTA.md"),
        "docs/COMPARISON_GRAPHIFY.md": _text(root, "docs/COMPARISON_GRAPHIFY.md"),
        "docs/OFFLINE_USAGE.md": _text(root, "docs/OFFLINE_USAGE.md"),
        "examples/mcp_setup.md": _text(root, "examples/mcp_setup.md"),
        "examples/gemini_cli_setup.md": _text(root, "examples/gemini_cli_setup.md"),
        ".claude/skills/verify/INSTRUCTIONS.md": _text(
            root, ".claude/skills/verify/INSTRUCTIONS.md"
        ),
        ".claude/skills/release/SKILL.md": _text(root, ".claude/skills/release/SKILL.md"),
        ".claude/skills/release-prep/SKILL.md": _text(root, ".claude/skills/release-prep/SKILL.md"),
        "docs/UPSTREAM_COMPARISON.md": _text(root, "docs/UPSTREAM_COMPARISON.md"),
        "docs/WHY_THIS_FORK.md": _text(root, "docs/WHY_THIS_FORK.md"),
        "docs/UPSTREAM_HARDENING.md": _text(root, "docs/UPSTREAM_HARDENING.md"),
    }

    if docs["CLAUDE.md"] != "@AGENTS.md\n":
        errors.append("CLAUDE.md: must contain exactly '@AGENTS.md' and one trailing newline")

    readme = docs["README.md"]
    errors.extend(backup_restore_contract_errors(readme, docs["docs/BACKUP_RESTORE.md"]))
    _require(errors, readme, f"<strong>{tool_count} MCP Tools</strong>", "README.md")
    _require(errors, readme, f"### MCP Server — {tool_count} Tools", "README.md")
    _require(errors, readme, f"| `full` _(default)_ | all {tool_count} |", "README.md")
    _require(
        errors,
        docs["docs/AGENT_INSTALL.md"],
        f"| MCP tools | {tool_count} tools",
        "docs/AGENT_INSTALL.md",
    )
    _require(
        errors,
        docs["docs/AGENT_INSTALL.md"],
        f"`full` — all {tool_count} tools",
        "docs/AGENT_INSTALL.md",
    )
    _require(
        errors,
        docs["docs/LLM_USAGE_RULES.md"],
        f"subset of the {tool_count} tools",
        "docs/LLM_USAGE_RULES.md",
    )
    _require(
        errors,
        docs["examples/mcp_setup.md"],
        f"full {tool_count}-tool default",
        "examples/mcp_setup.md",
    )
    _require(
        errors,
        docs["examples/mcp_setup.md"],
        f"| `full` _(default)_ | {tool_count} |",
        "examples/mcp_setup.md",
    )

    # --- Every live full-profile MCP tool name must appear in README.md -----
    missing_tool_names = sorted(name for name in tools if f"`{name}`" not in readme)
    if missing_tool_names:
        errors.append(
            "README.md: MCP tool tables missing documented tool names: "
            + ", ".join(missing_tool_names)
        )

    for profile, expected_tools in profiles.items():
        # The unscoped rules above are the full-profile guidance. Only reduced
        # profiles carry separate fenced blocks.
        if profile == "full":
            continue
        block = _profile_block(docs["docs/LLM_USAGE_RULES.md"], profile)
        if block is None:
            errors.append(f"docs/LLM_USAGE_RULES.md: missing profile block for {profile!r}")
            continue
        actual_tools = set(re.findall(r"\bmempalace_[a-z_]+\b", block))
        if actual_tools != expected_tools:
            missing = sorted(expected_tools - actual_tools)
            extra = sorted(actual_tools - expected_tools)
            detail = []
            if missing:
                detail.append(f"missing {', '.join(missing)}")
            if extra:
                detail.append(f"extra {', '.join(extra)}")
            errors.append(
                f"docs/LLM_USAGE_RULES.md: profile {profile!r} drift ({'; '.join(detail)})"
            )

    python_match = re.fullmatch(r">=([0-9]+\.[0-9]+)", requires_python)
    if python_match:
        python_label = f"Python {python_match.group(1)}+"
        _require(errors, docs["README.md"], python_label, "README.md")
        _require(errors, docs["docs/AGENT_INSTALL.md"], python_label, "docs/AGENT_INSTALL.md")
        _require(
            errors,
            docs["examples/gemini_cli_setup.md"],
            python_label,
            "examples/gemini_cli_setup.md",
        )
    else:
        errors.append(f"pyproject.toml: unsupported requires-python form {requires_python!r}")

    _require(errors, readme, f"version-{version}-", "README.md")
    if _first_release_version(docs["CHANGELOG.md"]) != version:
        errors.append(f"CHANGELOG.md: latest release heading must be v{version}")
    errors.extend(changelog_shape_errors(docs["CHANGELOG.md"]))
    _require(errors, docs["docs/RELEASING.md"], expected_about, "docs/RELEASING.md")

    errors.extend(
        agent_instruction_boundary_errors(
            root, docs["docs/LLM_USAGE_RULES.md"], docs["docs/AGENT_INSTALL.md"]
        )
    )
    errors.extend(
        runbook_consistency_errors(docs["docs/RELEASING.md"], docs["docs/AGENT_INSTALL.md"])
    )
    errors.extend(release_promotion_errors({"docs/RELEASING.md": docs["docs/RELEASING.md"]}))
    # Release-prep hands off to the release procedure; it must never publish. It
    # is still held to the same force-push and unbroken-flag safety, because it
    # is where a stuck maintainer first reads about the two diverged histories.
    errors.extend(
        release_promotion_errors(
            {
                ".claude/skills/release-prep/SKILL.md": docs[
                    ".claude/skills/release-prep/SKILL.md"
                ],
            },
            require_promotion_flow=False,
        )
    )

    # --- AAAK Dialect wording: no unsupported "~30x" claim, lossy qualifier required ---
    aaak_surfaces = {
        "README.md": readme,
        "mempalace_code/cli.py": _text(root, "mempalace_code/cli.py"),
    }
    for surface_label, text in aaak_surfaces.items():
        for marker in UNSUPPORTED_AAAK_MARKERS:
            if marker in text:
                errors.append(f"{surface_label}: unsupported AAAK claim still present: {marker!r}")
        if "AAAK" in text and "lossy" not in text.lower():
            errors.append(f"{surface_label}: AAAK mention is missing a 'lossy' qualifier")

    # --- CLI command inventory (AC-1) ---------------------------------------
    readme_commands = _readme_cli_commands(readme)
    if readme_commands is None:
        errors.append("README.md: 'All CLI Commands' section: section not found")
    else:
        missing_commands = sorted(set(cli_top_level_commands) - readme_commands)
        if missing_commands:
            errors.append(
                "README.md: 'All CLI Commands' section: missing documented commands: "
                + ", ".join(missing_commands)
            )
        stale_commands = sorted(readme_commands - set(cli_top_level_commands))
        if stale_commands:
            errors.append(
                "README.md: 'All CLI Commands' section: references commands no longer in "
                "argparse: " + ", ".join(stale_commands)
            )

    # --- Optional extras (AC-3) ---------------------------------------------
    readme_extras = _readme_optional_extras(readme)
    if readme_extras is None:
        errors.append("README.md: 'Optional extras' block: section not found")
    else:
        extras_set = set(extras)
        missing_extras = sorted(extras_set - readme_extras)
        stale_extras = sorted(readme_extras - extras_set)
        detail = []
        if missing_extras:
            detail.append(f"missing {', '.join(missing_extras)}")
        if stale_extras:
            detail.append(f"stale {', '.join(stale_extras)}")
        if detail:
            errors.append(f"README.md: 'Optional extras' block: drift ({'; '.join(detail)})")

    agent_extras = _agents_optional_extras(docs["AGENTS.md"])
    if agent_extras is None:
        errors.append("AGENTS.md: 'Optional extras' section: section not found")
    else:
        extras_set = set(extras)
        missing_agent_extras = sorted(extras_set - agent_extras)
        stale_agent_extras = sorted(agent_extras - extras_set)
        detail = []
        if missing_agent_extras:
            detail.append(f"missing {', '.join(missing_agent_extras)}")
        if stale_agent_extras:
            detail.append(f"stale {', '.join(stale_agent_extras)}")
        if detail:
            errors.append(f"AGENTS.md: 'Optional extras' section: drift ({'; '.join(detail)})")

    for relative_path, markers in CHROMA_RUNTIME_SUPPORT_MARKERS.items():
        text = docs[relative_path]
        for marker in markers:
            if marker in text:
                errors.append(
                    f"{relative_path}: current ChromaDB runtime support wording still present: "
                    f"{marker!r}"
                )
        if text.count(CHROMA_RECOVERY_COMMAND) > 1:
            errors.append(
                f"{relative_path}: duplicate ChromaDB recovery command; retain one recovery action"
            )

    # --- Release / dependency gate workflow names (AC-3) --------------------
    _require(errors, docs["docs/RELEASING.md"], publish_workflow, "docs/RELEASING.md")
    _require(errors, docs["docs/RELEASING.md"], tests_workflow, "docs/RELEASING.md")
    _require(
        errors,
        docs["docs/DEPENDENCY_UPGRADE_GATE.md"],
        audit_workflow,
        "docs/DEPENDENCY_UPGRADE_GATE.md",
    )
    _require(
        errors,
        docs["docs/DEPENDENCY_UPGRADE_GATE.md"],
        tests_workflow,
        "docs/DEPENDENCY_UPGRADE_GATE.md",
    )
    for script_name in (
        "release_admission_checks.py",
        "release_preflight.py",
        "release_readiness_gate.py",
        "release_status_gate.py",
    ):
        relative_script = f"scripts/{script_name}"
        if not (root / relative_script).exists():
            errors.append(f"docs/RELEASING.md: referenced script missing: {relative_script}")
        _require(errors, docs["docs/RELEASING.md"], relative_script, "docs/RELEASING.md")
    dependency_gate_script = "scripts/dependency_upgrade_gate.py"
    if not (root / dependency_gate_script).exists():
        errors.append(
            f"docs/DEPENDENCY_UPGRADE_GATE.md: referenced script missing: {dependency_gate_script}"
        )
    _require(
        errors,
        docs["docs/DEPENDENCY_UPGRADE_GATE.md"],
        dependency_gate_script,
        "docs/DEPENDENCY_UPGRADE_GATE.md",
    )
    for relative_path in EXACT_SHA_RELEASE_COMMAND_SURFACES:
        _require(
            errors,
            docs[relative_path],
            CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND,
            relative_path,
        )
        _require(
            errors,
            docs[relative_path],
            CANONICAL_RELEASE_STATUS_COMMAND,
            relative_path,
        )
    for relative_path in PARTIAL_PUBLICATION_RECOVERY_SURFACES:
        _require(
            errors,
            docs[relative_path],
            CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND,
            relative_path,
        )

    required_surfaces = release_status_surface_names()
    admission = _load_admission_checks()
    for marker in release_admission_markers():
        _require(
            errors,
            docs["docs/release-admission-rulesets.md"],
            marker,
            "docs/release-admission-rulesets.md",
        )
    for marker in PUBLIC_READ_BOUNDARY_MARKERS:
        for relative_path in ("docs/RELEASING.md", "docs/release-admission-rulesets.md"):
            _require(errors, docs[relative_path], marker, relative_path)
    for marker in dependency_audit_markers():
        _require(
            errors,
            docs["docs/DEPENDENCY_UPGRADE_GATE.md"],
            marker,
            "docs/DEPENDENCY_UPGRADE_GATE.md",
        )

    # --- Canonical verification commands (AC-4) ------------------------------
    for relative_path, required_names in VERIFICATION_COMMAND_SURFACES.items():
        text = docs.get(relative_path)
        if text is None:
            text = _text(root, relative_path)
            docs[relative_path] = text
        for name in required_names:
            command = canonical_commands.get(name)
            if command is None:
                errors.append(
                    f"scripts/quality_scorecard.py: canonical verification command missing: {name}"
                )
                continue
            if command not in text:
                errors.append(
                    f"{relative_path}: canonical verification command drift ({name}): "
                    f"missing {command!r}"
                )

    for relative_path in LIVE_RELEASE_PREFLIGHT_COMMAND_SURFACES:
        _require(
            errors,
            docs[relative_path],
            CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND,
            relative_path,
        )

    # --- Benchmark fixture facts (AC-2, AC-5) --------------------------------
    for relative_path, required_fields in BENCHMARK_FACT_SURFACES.items():
        text = docs[relative_path]
        for field in required_fields:
            label = benchmark_fact_label(field, bench_facts[field])
            if label not in text:
                errors.append(
                    f"{relative_path}: benchmark fixture facts drift ({field}): missing {label!r}"
                )
        for marker in STALE_BENCHMARK_MARKERS:
            if marker in text:
                errors.append(f"{relative_path}: stale benchmark wording still present: {marker!r}")

    # --- Retrieval quality facts (README "Retrieval quality" table) ---------
    code = retrieval_facts["code_minilm"]
    dotnet = retrieval_facts["dotnet_cleanarchitecture"]
    _require(
        errors,
        readme,
        RETRIEVAL_QUALITY_FACTS_PATH,
        "README.md",
    )
    retrieval_labels = {
        "code R@5": retrieval_quality_pct(code["r_at_5"]),
        "code R@10": retrieval_quality_pct(code["r_at_10"]),
        ".NET vector R@5": retrieval_quality_pct(dotnet["vector_r_at_5"]),
        ".NET hybrid R@5": retrieval_quality_pct(dotnet["hybrid_r_at_5"]),
    }
    for label, value in retrieval_labels.items():
        if value not in readme:
            errors.append(f"README.md: retrieval quality facts drift ({label}): missing {value!r}")
    chunk_label = f"{int(code['chunk_count'])} chunks"
    if chunk_label not in readme:
        errors.append(
            f"README.md: retrieval quality facts drift (chunk_count): missing {chunk_label!r}"
        )

    # --- Offline usage disclosure: EntityRegistry.research() network escape hatch ---
    for marker in OFFLINE_USAGE_DISCLOSURE_MARKERS:
        _require_wrap_tolerant(
            errors, docs["docs/OFFLINE_USAGE.md"], marker, "docs/OFFLINE_USAGE.md"
        )

    # --- Update-hint alignment: version_check.py must route through update commands ---
    # Only checked when the file exists (synthetic fixture repos omit it).
    vc_path = root / "mempalace_code" / "version_check.py"
    if vc_path.exists():
        vc_text = vc_path.read_text(encoding="utf-8")
        if "pip install --upgrade mempalace-code" in vc_text:
            errors.append(
                "mempalace_code/version_check.py: stale raw pip upgrade hint still present; "
                "use 'mempalace-code update status' and 'mempalace-code update apply --yes'"
            )

    # --- Python compatibility fitness: classifiers vs CI test matrix ---------
    missing_ci_versions = sorted(
        set(classifier_python_versions) - set(ci_python_versions),
        key=lambda version: tuple(int(part) for part in version.split(".")),
    )
    extra_ci_versions = sorted(
        set(ci_python_versions) - set(classifier_python_versions),
        key=lambda version: tuple(int(part) for part in version.split(".")),
    )
    if missing_ci_versions or extra_ci_versions:
        detail = []
        if missing_ci_versions:
            detail.append(f"missing {', '.join(missing_ci_versions)}")
        if extra_ci_versions:
            detail.append(f"extra {', '.join(extra_ci_versions)}")
        errors.append(f".github/workflows/ci.yml: python test matrix drift ({'; '.join(detail)})")

    facts: dict[str, object] = {
        "version": version,
        "requires_python": requires_python,
        "tool_count": tool_count,
        "profile_counts": profile_counts,
        "github_about": expected_about,
        "optional_extras": extras,
        "cli_top_level_commands": cli_top_level_commands,
        "cli_nested_command_count": cli_nested_command_count,
        "verification_commands": dict(sorted(canonical_commands.items())),
        "workflow_names": {
            "tests": tests_workflow,
            "publish": publish_workflow,
            "dependency_audit": audit_workflow,
        },
        # Derived from the admission constants, never restated: this block is the
        # machine-readable copy of the same contract the guard enforces above, so a
        # literal here would let the published fact drift from the enforced gate.
        "release_admission": {
            "aggregate_required_check": admission.AGGREGATE_REQUIRED_CHECK,
            "exact_sha_preflight": CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND,
            "status_gate": CANONICAL_RELEASE_STATUS_COMMAND,
            "partial_publication_recovery": CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND,
            "status_surfaces": list(required_surfaces),
            "ruleset_doc": admission.RULESET_DOC,
            "dependency_audit_max_age_hours": admission.DEFAULT_AUDIT_MAX_AGE_HOURS,
        },
        "benchmark_fixture_facts": bench_facts,
        "retrieval_quality_facts": retrieval_facts,
        "python_classifier_versions": classifier_python_versions,
        "ci_python_versions": ci_python_versions,
    }
    return facts, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify public documentation against local metadata."
    )
    parser.add_argument(
        "--root", type=Path, default=repo_root(), help="Repository root to inspect."
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON.")
    args = parser.parse_args(argv)

    facts, errors = evaluate(args.root.resolve())
    result = {"ok": not errors, "facts": facts, "errors": errors}
    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif errors:
        print("docs-drift-guard: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    else:
        profile_counts = facts["profile_counts"]
        assert isinstance(profile_counts, dict)
        counts = ", ".join(f"{name}:{count}" for name, count in profile_counts.items())
        print(
            "docs-drift-guard: OK "
            f"version={facts['version']} tools={facts['tool_count']} profiles={counts}"
        )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
