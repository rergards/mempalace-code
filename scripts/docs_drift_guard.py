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
import json
import re
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
# a key in scripts/quality_scorecard.py's _VERIFICATION_COMMANDS. A surface is
# only required to carry the subset of canonical commands relevant to it —
# e.g. the release skill only repeats lint/format/typecheck, not the full table
# that .claude/skills/verify/INSTRUCTIONS.md is the verbatim source for.
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
    "CLAUDE.md": ("lint", "format", "tests", "typecheck"),
    ".claude/skills/release/SKILL.md": ("lint", "format", "typecheck"),
    "docs/quality/README.md": ("scorecard", "public_safety"),
}

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

# The Python API's EntityRegistry.research() is the only method that reaches out to
# a third-party network service on its own; docs/OFFLINE_USAGE.md must disclose it
# explicitly so airgapped/offline users know it exists and that nothing else calls it.
OFFLINE_USAGE_DISCLOSURE_MARKERS: tuple[str, ...] = (
    "EntityRegistry.research()",
    "English Wikipedia REST API",
    "flows never call this method",
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


def _profile_block(text: str, profile: str) -> str | None:
    pattern = re.compile(
        rf"<!-- mcp-profile:{re.escape(profile)} start -->(.*?)<!-- mcp-profile:{re.escape(profile)} end -->",
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _first_release_version(changelog: str) -> str | None:
    match = re.search(r"^## v([^\s]+)\s+—", changelog, re.MULTILINE)
    return match.group(1) if match else None


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
    return set(re.findall(r"mempalace-code\[([a-z]+)\]", match.group(1)))


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
        "README.md": _text(root, "README.md"),
        "CHANGELOG.md": _text(root, "CHANGELOG.md"),
        "CLAUDE.md": _text(root, "CLAUDE.md"),
        "docs/AGENT_INSTALL.md": _text(root, "docs/AGENT_INSTALL.md"),
        "docs/LLM_USAGE_RULES.md": _text(root, "docs/LLM_USAGE_RULES.md"),
        "docs/RELEASING.md": _text(root, "docs/RELEASING.md"),
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
    }

    readme = docs["README.md"]
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
    _require(errors, docs["docs/RELEASING.md"], expected_about, "docs/RELEASING.md")

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

    claude_extras = set(re.findall(r"\.\[([a-z]+)\]", docs["CLAUDE.md"]))
    stale_claude_extras = sorted(claude_extras - set(extras))
    if stale_claude_extras:
        errors.append(
            "CLAUDE.md: 'Optional extras' section: references unknown extras: "
            + ", ".join(stale_claude_extras)
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
    for script_name in ("release_preflight.py", "release_status_gate.py"):
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
