#!/usr/bin/env python3
"""gate_inventory.py — Canonical quality and release gate inventory.

Single source of truth for every tracked quality/release command. Downstream
scripts (quality_scorecard.py, docs_drift_guard.py, release_readiness_gate.py)
import from this module so command strings never drift between surfaces.

Usage:
    python scripts/gate_inventory.py              # print inventory as JSON
    python scripts/gate_inventory.py --check      # parity-check public surfaces
    python scripts/gate_inventory.py --list       # list all gate IDs and commands
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

# Workflow security gate commands. actionlint and zizmor are pinned dev dependencies,
# so `pip install -e ".[dev]"` (or `uv sync --extra dev`) is the only setup they need.
# zizmor runs offline and blocks at medium severity and above, which covers the immutable
# `uses:` pins, expression injection, excessive job permissions, and credential-persisting
# checkouts this repository's release path depends on. The audit covers repository-local
# composite actions too, because a workflow's security posture is only as good as the
# actions it calls. The single inline suppression there names one audit on one line and
# documents why; no audit is disabled repository-wide.
ACTIONLINT_COMMAND = "actionlint .github/workflows/*.yml"
ZIZMOR_COMMAND = "zizmor --offline --min-severity=medium .github/workflows/ .github/actions/"
RELEASE_READINESS_COMMAND = (
    'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
)
INSTALLED_GOLDEN_COMMAND = (
    'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
)
# The Gitleaks CLI version is declared in exactly one place — the checksum-locked
# tool module at tools/gitleaks/go.mod — so Dependabot's gomod ecosystem owns the
# upgrade and no workflow ever names a mutable `@tag`. Workflows install it through
# the repository-local composite action, which runs `go install` from that module.
GITLEAKS_GO_MODULE = "github.com/zricethezav/gitleaks/v8"
GITLEAKS_TOOL_MODULE_PATH = "tools/gitleaks/go.mod"
GITLEAKS_SETUP_ACTION = "./.github/actions/gitleaks-gate"
GITLEAKS_INSTALL_COMMAND = f"uses: {GITLEAKS_SETUP_ACTION}"
GITLEAKS_CHANGED_RANGE_COMMAND = (
    "python scripts/gitleaks_scan.py changed-range --base-ref BASE --head-ref HEAD"
)
GITLEAKS_FULL_HISTORY_COMMAND = "python scripts/gitleaks_scan.py full-history"

_GITLEAKS_REQUIRE_RE = re.compile(
    rf"^\s*(?:require\s+)?{re.escape(GITLEAKS_GO_MODULE)}\s+(?P<version>v\S+?)\s*(?://.*)?$",
    re.MULTILINE,
)

# ── Gate definitions ───────────────────────────────────────────────────────────

# Each gate row:
#   id:       stable snake_case identifier used by scorecard and drift guard
#   name:     human-readable label
#   command:  exact shell command string (must be copy-pasted verbatim into surfaces)
#   category: "quality" | "release" | "artifact" | "install"
#   surfaces: list of (path, context) pairs; context is a regex or substring that
#             must appear near the command in that surface file.
#             Empty list means the gate is not required in tracked public surfaces.

CANONICAL_GATES: list[dict] = [
    {
        "id": "lint",
        "name": "Ruff lint",
        "command": "ruff check mempalace_code/ tests/ scripts/",
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "format",
        "name": "Ruff format check",
        "command": "ruff format --check mempalace_code/ tests/ scripts/",
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "tests",
        "name": "pytest non-network suite",
        "command": 'python -m pytest tests/ -x -q -m "not needs_network"',
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
        ],
    },
    {
        "id": "typecheck",
        "name": "Pyright basic typecheck",
        "command": "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\"",
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "typecheck_strict_slice",
        "name": "Pyright strict slice",
        "command": "python -m pyright -p pyrightconfig.strict.json",
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "public_safety",
        "name": "Public-safety scan (pre-commit)",
        "command": "python scripts/public_safety_scan.py --tracked --staged",
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "public_safety_committed",
        "name": "Public-safety scan (committed/release)",
        "command": "python scripts/public_safety_scan.py --committed --tracked --staged",
        "category": "release",
        "surfaces": [],
    },
    {
        "id": "gitleaks_changed_range",
        "name": "Gitleaks changed-range scan",
        "command": GITLEAKS_CHANGED_RANGE_COMMAND,
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "gitleaks_full_history",
        "name": "Gitleaks full-history scan",
        "command": GITLEAKS_FULL_HISTORY_COMMAND,
        "category": "release",
        "surfaces": [
            ".github/workflows/publish.yml",
            ".github/workflows/gitleaks-history.yml",
        ],
    },
    {
        "id": "gitleaks_install",
        "name": "Gitleaks CLI install (checksum-locked tool module)",
        "command": GITLEAKS_INSTALL_COMMAND,
        "category": "install",
        "surfaces": [
            ".github/workflows/ci.yml",
            ".github/workflows/publish.yml",
            ".github/workflows/gitleaks-history.yml",
        ],
    },
    {
        "id": "scorecard",
        "name": "Quality scorecard check",
        "command": "python scripts/quality_scorecard.py --check",
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "architecture_guard",
        "name": "Architecture boundary guard",
        "command": "python scripts/architecture_guard.py --root .",
        "category": "quality",
        "surfaces": [
            ".claude/skills/verify/INSTRUCTIONS.md",
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "workflow_lint",
        "name": "GitHub Actions syntax lint",
        "command": ACTIONLINT_COMMAND,
        "category": "quality",
        "surfaces": [
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "workflow_audit",
        "name": "GitHub Actions security audit",
        "command": ZIZMOR_COMMAND,
        "category": "quality",
        "surfaces": [
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "docs_drift",
        "name": "Docs drift guard",
        "command": "python scripts/docs_drift_guard.py",
        "category": "quality",
        "surfaces": [
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "performance_budgets",
        "name": "Performance budgets (hard CI gate)",
        "command": "python benchmarks/demo_perf_budgets.py --check --ci",
        "category": "quality",
        "surfaces": [
            ".github/workflows/ci.yml",
        ],
    },
    {
        "id": "artifact_gate",
        "name": "Release artifact member inspection",
        "command": "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist",
        "category": "artifact",
        "surfaces": [],
    },
    {
        "id": "release_readiness",
        "name": "Release readiness gate",
        "command": RELEASE_READINESS_COMMAND,
        "category": "release",
        "surfaces": ["docs/RELEASING.md", ".claude/skills/release/SKILL.md"],
    },
    {
        "id": "installed_golden",
        "name": "Exact-wheel installed golden CLI suite",
        "command": INSTALLED_GOLDEN_COMMAND,
        "category": "install",
        "surfaces": ["docs/RELEASING.md", ".github/workflows/ci.yml"],
    },
    {
        "id": "install_smoke",
        "name": "Install metadata smoke (checkout)",
        "command": "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json",
        "category": "install",
        "surfaces": [],
    },
]


# ── Verify-surface subset ─────────────────────────────────────────────────────
# Which gate IDs should appear in INSTRUCTIONS.md as the /verify surface.
# This matches _VERIFICATION_COMMANDS in quality_scorecard.py.
VERIFY_SURFACE_IDS: tuple[str, ...] = (
    "lint",
    "format",
    "tests",
    "typecheck",
    "typecheck_strict_slice",
    "public_safety",
    "gitleaks_changed_range",
    "scorecard",
    "architecture_guard",
)

RUFF_PRE_COMMIT_REPO = "https://github.com/astral-sh/ruff-pre-commit"
RUFF_HOOK_IDS: tuple[str, ...] = ("ruff", "ruff-format")
CANONICAL_RUFF_PRECOMMIT_FILES = r"^(mempalace_code|tests|scripts)/.*\.py$"
RUFF_CI_DEV_INSTALL_COMMAND = 'pip install -e ".[dev]"'


def gates_by_id() -> dict[str, dict]:
    """Return a dict mapping gate id → gate row."""
    return {g["id"]: g for g in CANONICAL_GATES}


def verify_surface_gates() -> list[dict]:
    """Return gates for the /verify surface (INSTRUCTIONS.md + scorecard table)."""
    by_id = gates_by_id()
    return [by_id[gid] for gid in VERIFY_SURFACE_IDS if gid in by_id]


def all_commands() -> dict[str, str]:
    """Return a dict mapping gate id → command string."""
    return {g["id"]: g["command"] for g in CANONICAL_GATES}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def gitleaks_cli_version(root: Path | None = None) -> str:
    """Return the Gitleaks version pinned by the checksum-locked tool module.

    Reading it here — instead of duplicating a literal into workflows, docs and
    this inventory — means a Dependabot bump to ``tools/gitleaks/go.mod`` is the
    single edit that moves the CLI version, and ``tools/gitleaks/go.sum`` keeps
    the module checksums locked.
    """
    path = (root or repo_root()) / GITLEAKS_TOOL_MODULE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{GITLEAKS_TOOL_MODULE_PATH} is unreadable: {exc}") from exc
    match = _GITLEAKS_REQUIRE_RE.search(text)
    if match is None:
        raise ValueError(
            f"{GITLEAKS_TOOL_MODULE_PATH} does not require {GITLEAKS_GO_MODULE} at a pinned version"
        )
    return match.group("version")


# ── Parity checker ─────────────────────────────────────────────────────────────


def _surface_text(root: Path, rel_path: str) -> str | None:
    path = root / rel_path
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _precommit_ruff_contract(root: Path) -> tuple[str | None, dict[str, str]]:
    text = _surface_text(root, ".pre-commit-config.yaml")
    if text is None:
        return None, {}

    rev: str | None = None
    hook_files: dict[str, str] = {}
    in_ruff_repo = False
    current_hook: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("- repo:"):
            repo = _unquote_yaml_scalar(line.split(":", 1)[1])
            if in_ruff_repo and repo != RUFF_PRE_COMMIT_REPO:
                break
            in_ruff_repo = repo == RUFF_PRE_COMMIT_REPO
            current_hook = None
            continue
        if not in_ruff_repo:
            continue
        if line.startswith("rev:"):
            rev = _unquote_yaml_scalar(line.split(":", 1)[1])
            continue
        if line.startswith("- id:"):
            current_hook = _unquote_yaml_scalar(line.split(":", 1)[1])
            continue
        if current_hook and line.startswith("files:"):
            hook_files[current_hook] = _unquote_yaml_scalar(line.split(":", 1)[1])

    return rev, hook_files


def _read_toml(root: Path, rel_path: str) -> tuple[dict | None, list[str]]:
    path = root / rel_path
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh), []
    except FileNotFoundError:
        return None, [f"MISSING-SURFACE: {rel_path} (required by Ruff version contract)"]
    except tomllib.TOMLDecodeError as exc:
        return None, [f"PARSE-ERROR: {rel_path}: {exc}"]


def _ruff_dep_string(deps: object) -> str | None:
    if not isinstance(deps, list):
        return None
    for dep in deps:
        if isinstance(dep, str) and re.match(r"(?i)^\s*ruff(?:\s|[<>=!~;].*)?$", dep):
            return dep.strip()
    return None


def _exact_ruff_version(dep: str | None) -> str | None:
    if dep is None:
        return None
    match = re.match(r"(?i)^\s*ruff\s*==\s*([^,;\s]+)\s*(?:;.*)?$", dep)
    if match is None:
        return None
    return match.group(1)


def _ruff_pyproject_deps(pyproject: dict) -> dict[str, str | None]:
    return {
        "[project.optional-dependencies].dev": _ruff_dep_string(
            pyproject.get("project", {}).get("optional-dependencies", {}).get("dev", [])
        ),
        "[dependency-groups].dev": _ruff_dep_string(
            pyproject.get("dependency-groups", {}).get("dev", [])
        ),
    }


def _lock_package(lock: dict, package_name: str) -> dict | None:
    packages = lock.get("package", [])
    if not isinstance(packages, list):
        return None
    for package in packages:
        if isinstance(package, dict) and package.get("name") == package_name:
            return package
    return None


def _lock_dep_specifier(entries: object, dep_name: str) -> str | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == dep_name:
            specifier = entry.get("specifier")
            return specifier if isinstance(specifier, str) else None
    return None


def _ci_lint_job_text(root: Path) -> str | None:
    text = _surface_text(root, ".github/workflows/ci.yml")
    if text is None:
        return None

    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == "  lint:"), None)
    if start is None:
        return ""

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def check_ruff_contract(root: Path) -> list[str]:
    errors: list[str] = []

    pyproject, pyproject_errors = _read_toml(root, "pyproject.toml")
    errors.extend(pyproject_errors)
    lock, lock_errors = _read_toml(root, "uv.lock")
    errors.extend(lock_errors)

    pyproject_version: str | None = None
    project_name = "mempalace-code"
    if pyproject is not None:
        project_name = str(pyproject.get("project", {}).get("name", project_name))
        pyproject_deps = _ruff_pyproject_deps(pyproject)
        exact_versions = {
            surface: _exact_ruff_version(dep) for surface, dep in pyproject_deps.items()
        }
        for surface, dep in pyproject_deps.items():
            if exact_versions[surface] is None:
                found = dep if dep is not None else "missing"
                errors.append(
                    "RUFF-PYPROJECT-VERSION-DRIFT: "
                    f"{surface} must pin Ruff exactly; found {found!r}"
                )
        versions = {version for version in exact_versions.values() if version is not None}
        if len(versions) == 1 and all(version is not None for version in exact_versions.values()):
            pyproject_version = versions.pop()
        elif len(versions) > 1:
            errors.append(
                "RUFF-PYPROJECT-VERSION-DRIFT: Ruff pins differ across pyproject dev "
                f"surfaces: {exact_versions!r}"
            )

    lock_ruff_version: str | None = None
    lock_ruff_metadata_specs: dict[str, str | None] = {}
    if lock is not None:
        ruff_package = _lock_package(lock, "ruff")
        if ruff_package is None:
            errors.append("RUFF-LOCK-VERSION-DRIFT: uv.lock is missing package 'ruff'")
        else:
            version = ruff_package.get("version")
            lock_ruff_version = version if isinstance(version, str) else None

        project_package = _lock_package(lock, project_name)
        if project_package is None:
            errors.append(f"RUFF-LOCK-VERSION-DRIFT: uv.lock is missing package {project_name!r}")
        else:
            metadata = project_package.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            requires_dev = metadata.get("requires-dev", {})
            if not isinstance(requires_dev, dict):
                requires_dev = {}
            lock_ruff_metadata_specs = {
                "uv.lock [package.metadata].requires-dist": _lock_dep_specifier(
                    metadata.get("requires-dist", []), "ruff"
                ),
                "uv.lock [package.metadata.requires-dev].dev": _lock_dep_specifier(
                    requires_dev.get("dev", []), "ruff"
                ),
            }

    expected_version = pyproject_version or lock_ruff_version
    if expected_version is not None:
        expected_specifier = f"=={expected_version}"
        if lock_ruff_version != expected_version:
            errors.append(
                "RUFF-LOCK-VERSION-DRIFT: "
                f"uv.lock package 'ruff' version {lock_ruff_version!r} != {expected_version!r}"
            )
        for surface, specifier in lock_ruff_metadata_specs.items():
            if specifier != expected_specifier:
                errors.append(
                    "RUFF-LOCK-VERSION-DRIFT: "
                    f"{surface} must use {expected_specifier!r}; found {specifier!r}"
                )

        rev, hook_files = _precommit_ruff_contract(root)
        expected_rev = f"v{expected_version}"
        if rev != expected_rev:
            errors.append(
                "RUFF-HOOK-REV-DRIFT: "
                f".pre-commit-config.yaml Ruff rev must be {expected_rev!r}; found {rev!r}"
            )
        for hook_id in RUFF_HOOK_IDS:
            files = hook_files.get(hook_id)
            if files != CANONICAL_RUFF_PRECOMMIT_FILES:
                errors.append(
                    "RUFF-HOOK-SCOPE-DRIFT: "
                    f"hook {hook_id!r} files must be {CANONICAL_RUFF_PRECOMMIT_FILES!r}; "
                    f"found {files!r}"
                )

    lint_job = _ci_lint_job_text(root)
    if lint_job is None:
        errors.append("MISSING-SURFACE: .github/workflows/ci.yml (required by Ruff CI contract)")
    elif not lint_job.strip():
        errors.append("RUFF-CI-DIRECT-GATE-DRIFT: .github/workflows/ci.yml lint job not found")
    else:
        if RUFF_CI_DEV_INSTALL_COMMAND not in lint_job:
            errors.append(
                "RUFF-CI-INSTALL-DRIFT: lint job must install the project dev dependency "
                f"contract with {RUFF_CI_DEV_INSTALL_COMMAND!r}"
            )
        for gate_id in ("lint", "format"):
            command = gates_by_id()[gate_id]["command"]
            if command not in lint_job:
                errors.append(
                    "RUFF-CI-DIRECT-GATE-DRIFT: "
                    f"lint job must keep direct Ruff gate {gate_id!r}: {command!r}"
                )

    return errors


def _check_surface_contains_command(
    surface_text: str, gate_id: str, command: str, surface_path: str
) -> list[str]:
    """Return error lines if the surface does not contain the command."""
    if command in surface_text:
        return []
    # Try partial match: the command may be split across lines in YAML or wrapped.
    # Check that a significant fragment (first 30 chars) appears.
    fragment = command[:40].rstrip()
    if fragment and fragment in surface_text:
        return []
    return [f"DRIFT: {surface_path}: gate '{gate_id}' command not found.\n  Expected: {command!r}"]


def check_parity(root: Path, gates: list[dict] | None = None) -> list[str]:
    """Check that all tracked public surfaces contain their required commands.

    Returns a list of error strings; empty means all surfaces are in parity.
    ``gates`` defaults to CANONICAL_GATES when not provided.
    """
    using_default_gates = gates is None
    if gates is None:
        gates = CANONICAL_GATES
    errors: list[str] = []

    # Load surface texts once.
    surface_cache: dict[str, str | None] = {}

    for gate in gates:
        gate_id = gate["id"]
        command = gate["command"]
        for surface_path in gate.get("surfaces", []):
            if surface_path not in surface_cache:
                surface_cache[surface_path] = _surface_text(root, surface_path)
            text = surface_cache[surface_path]
            if text is None:
                errors.append(f"MISSING-SURFACE: {surface_path} (required by gate '{gate_id}')")
                continue
            errors.extend(_check_surface_contains_command(text, gate_id, command, surface_path))

    # Also check that the scorecard's _VERIFICATION_COMMANDS matches the verify-surface gates.
    scorecard_path = root / "scripts" / "quality_scorecard.py"
    if scorecard_path.exists():
        scorecard_text = scorecard_path.read_text(encoding="utf-8")
        # Find _VERIFICATION_COMMANDS tuple to verify command strings.
        verify_gates = [g for g in gates if g["id"] in set(VERIFY_SURFACE_IDS)]
        for gate in verify_gates:
            cmd = gate["command"]
            # The command may appear either verbatim (in markdown) or Python-escaped
            # (inside a string literal in quality_scorecard.py, where " → \").
            escaped_cmd = cmd.replace('"', '\\"')
            if cmd in scorecard_text or escaped_cmd in scorecard_text:
                continue
            # Partial match: first 40 chars of command (use escaped form for Python src).
            fragment = cmd[:40].rstrip()
            escaped_fragment = escaped_cmd[:40].rstrip()
            if (fragment and fragment in scorecard_text) or (
                escaped_fragment and escaped_fragment in scorecard_text
            ):
                continue
            errors.append(
                f"SCORECARD-DRIFT: gate '{gate['id']}' command not found in "
                f"scripts/quality_scorecard.py _VERIFICATION_COMMANDS"
            )

    if using_default_gates:
        errors.extend(check_ruff_contract(root))

    return errors


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Canonical quality/release gate inventory and parity checker."
    )
    parser.add_argument("--check", action="store_true", help="Check parity of tracked surfaces.")
    parser.add_argument("--list", action="store_true", help="List gates as id: command pairs.")
    parser.add_argument("--json", action="store_true", help="Output gates as JSON.")
    args = parser.parse_args(argv)
    root = repo_root()

    if args.check:
        errors = check_parity(root)
        if errors:
            print("gate-inventory: FAIL", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        print(
            f"gate-inventory: OK ({len(CANONICAL_GATES)} gates, "
            f"{len(VERIFY_SURFACE_IDS)} in verify-surface)"
        )
        return 0

    if args.list:
        for gate in CANONICAL_GATES:
            print(f"{gate['id']}: {gate['command']}")
        return 0

    output = {
        "schema_version": 1,
        "gates": CANONICAL_GATES,
        "verify_surface_ids": list(VERIFY_SURFACE_IDS),
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
