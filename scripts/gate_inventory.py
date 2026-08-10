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
import sys
from pathlib import Path

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
        "command": "python scripts/release_readiness_gate.py --check --json",
        "category": "release",
        "surfaces": [],
    },
    {
        "id": "install_smoke",
        "name": "Install metadata smoke (checkout)",
        "command": "python scripts/release_install_metadata_smoke.py --install-spec . --json",
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
    "scorecard",
    "architecture_guard",
)


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


# ── Parity checker ─────────────────────────────────────────────────────────────


def _surface_text(root: Path, rel_path: str) -> str | None:
    path = root / rel_path
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


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
