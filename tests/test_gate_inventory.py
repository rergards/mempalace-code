"""Tests for scripts/gate_inventory.py — canonical gate inventory and parity checker."""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


gi = _load_module("gate_inventory", ROOT / "scripts" / "gate_inventory.py")


# ── Schema tests ───────────────────────────────────────────────────────────────


def test_canonical_gates_is_nonempty_list():
    assert isinstance(gi.CANONICAL_GATES, list)
    assert len(gi.CANONICAL_GATES) >= 12


def test_each_gate_has_required_fields():
    required = {"id", "name", "command", "category", "surfaces"}
    for gate in gi.CANONICAL_GATES:
        missing = required - gate.keys()
        assert not missing, f"gate {gate.get('id', '?')} missing fields: {missing}"


def test_gate_ids_are_unique():
    ids = [g["id"] for g in gi.CANONICAL_GATES]
    dupes = [x for x in ids if ids.count(x) > 1]
    assert not dupes, f"duplicate gate ids: {dupes}"


def test_gate_commands_are_nonempty_strings():
    for gate in gi.CANONICAL_GATES:
        assert isinstance(gate["command"], str), f"gate '{gate['id']}' command must be a string"
        assert gate["command"].strip(), f"gate '{gate['id']}' has empty command"


def test_gate_categories_are_known():
    valid = {"quality", "release", "artifact", "install"}
    for gate in gi.CANONICAL_GATES:
        assert gate["category"] in valid, (
            f"gate '{gate['id']}' has unknown category '{gate['category']}'"
        )


def test_gate_surfaces_are_lists_of_strings():
    for gate in gi.CANONICAL_GATES:
        assert isinstance(gate["surfaces"], list), f"gate '{gate['id']}' surfaces must be a list"
        for s in gate["surfaces"]:
            assert isinstance(s, str), f"gate '{gate['id']}' surface entry is not a str: {s!r}"


# ── Required gate coverage ─────────────────────────────────────────────────────


def test_required_quality_gates_present():
    required_ids = {
        "lint",
        "format",
        "tests",
        "typecheck",
        "typecheck_strict_slice",
        "public_safety",
        "scorecard",
        "architecture_guard",
    }
    present = {g["id"] for g in gi.CANONICAL_GATES}
    missing = required_ids - present
    assert not missing, f"missing required quality gates: {sorted(missing)}"


def test_required_release_artifact_gates_present():
    required_ids = {
        "performance_budgets",
        "artifact_gate",
        "release_readiness",
        "install_smoke",
        "public_safety_committed",
    }
    present = {g["id"] for g in gi.CANONICAL_GATES}
    missing = required_ids - present
    assert not missing, f"missing required release/artifact gates: {sorted(missing)}"


def test_verify_surface_ids_are_subset_of_canonical():
    canonical_ids = {g["id"] for g in gi.CANONICAL_GATES}
    for gid in gi.VERIFY_SURFACE_IDS:
        assert gid in canonical_ids, f"verify surface id '{gid}' not in CANONICAL_GATES"


def test_verify_surface_ids_cover_core_quality_gates():
    expected_in_verify = {
        "lint",
        "format",
        "tests",
        "typecheck",
        "typecheck_strict_slice",
        "public_safety",
        "scorecard",
        "architecture_guard",
    }
    missing = expected_in_verify - set(gi.VERIFY_SURFACE_IDS)
    assert not missing, f"missing from verify surface: {sorted(missing)}"


# ── Command uniqueness ─────────────────────────────────────────────────────────


def test_no_duplicate_commands():
    commands = [g["command"] for g in gi.CANONICAL_GATES]
    seen: set[str] = set()
    dupes = []
    for cmd in commands:
        if cmd in seen:
            dupes.append(cmd)
        seen.add(cmd)
    assert not dupes, f"duplicate commands: {dupes}"


# ── gates_by_id and all_commands ──────────────────────────────────────────────


def test_gates_by_id_returns_all_gates():
    by_id = gi.gates_by_id()
    assert len(by_id) == len(gi.CANONICAL_GATES)
    for gate in gi.CANONICAL_GATES:
        assert gate["id"] in by_id


def test_all_commands_maps_id_to_command():
    cmds = gi.all_commands()
    for gate in gi.CANONICAL_GATES:
        assert gate["id"] in cmds
        assert cmds[gate["id"]] == gate["command"]


def test_verify_surface_gates_returns_correct_subset():
    vs = gi.verify_surface_gates()
    ids = [g["id"] for g in vs]
    assert ids == list(gi.VERIFY_SURFACE_IDS), (
        "verify_surface_gates() order must match VERIFY_SURFACE_IDS"
    )


# ── Parity checker ─────────────────────────────────────────────────────────────


_LINT_GATE = {
    "id": "lint",
    "name": "Lint",
    "command": "ruff check mempalace_code/ tests/ scripts/",
    "category": "quality",
    "surfaces": ["verify.md"],
}


def test_check_parity_surface_missing(tmp_path):
    """Missing surface file should be reported as an error."""
    root = tmp_path / "repo"
    root.mkdir()
    gates = [{**_LINT_GATE, "surfaces": ["missing_surface.md"]}]
    errors = gi.check_parity(root, gates=gates)
    assert any("MISSING-SURFACE" in e and "missing_surface.md" in e for e in errors)


def test_check_parity_command_missing_from_surface(tmp_path):
    """Surface exists but doesn't contain the command → drift error."""
    root = tmp_path / "repo"
    root.mkdir()
    surface = root / "verify.md"
    surface.write_text("# verify\nsome other content\n", encoding="utf-8")
    gates = [_LINT_GATE]
    errors = gi.check_parity(root, gates=gates)
    assert any("DRIFT" in e and "lint" in e for e in errors)


def test_check_parity_command_present_in_surface(tmp_path):
    """Surface contains the command → no drift error."""
    root = tmp_path / "repo"
    root.mkdir()
    surface = root / "verify.md"
    surface.write_text("ruff check mempalace_code/ tests/ scripts/\n", encoding="utf-8")
    gates = [_LINT_GATE]
    errors = gi.check_parity(root, gates=gates)
    drift = [e for e in errors if "lint" in e.lower() and "DRIFT" in e]
    assert not drift, f"Unexpected drift errors: {drift}"


def test_check_parity_no_surfaces_no_errors(tmp_path):
    """A gate with empty surfaces list never generates surface-parity errors."""
    root = tmp_path / "repo"
    root.mkdir()
    gates = [
        {
            "id": "release_readiness",
            "name": "Release readiness",
            "command": "python scripts/release_readiness_gate.py --check --json",
            "category": "release",
            "surfaces": [],
        }
    ]
    errors = gi.check_parity(root, gates=gates)
    surface_errors = [e for e in errors if "DRIFT" in e or "MISSING-SURFACE" in e]
    assert not surface_errors


def test_check_parity_stale_command_detected(tmp_path):
    """If the surface has a different (stale) command string, drift is reported."""
    root = tmp_path / "repo"
    root.mkdir()
    surface = root / "verify.md"
    surface.write_text("ruff check mempalace_code/\n", encoding="utf-8")
    gates = [_LINT_GATE]
    errors = gi.check_parity(root, gates=gates)
    assert any("DRIFT" in e for e in errors)


# ── CLI main() ─────────────────────────────────────────────────────────────────


def test_main_list_prints_gate_ids(capsys):
    rc = gi.main(["--list"])
    assert rc == 0
    out = capsys.readouterr().out
    for gate in gi.CANONICAL_GATES:
        assert gate["id"] in out


def test_main_json_output_is_valid(capsys):
    rc = gi.main(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "gates" in data
    assert "verify_surface_ids" in data
    assert data["schema_version"] == 1


def test_main_check_passes_on_live_repo(capsys):
    """The --check mode should pass on the current tracked repository."""
    rc = gi.main(["--check"])
    out = capsys.readouterr()
    assert rc == 0, f"gate-inventory --check failed:\nstdout={out.out!r}\nstderr={out.err!r}"


# ── Dev-dependency contract for canonical gate scripts ─────────────────────────


def test_artifact_release_gate_deps_declared_in_both_dev_surfaces():
    """build and twine must appear in both dev dependency surfaces.

    release_readiness_gate.py runs `python -m build`; release_artifact_gate.py
    runs `python -m twine`. If either package is absent from a dev surface the
    canonical gate fails in a clean environment.
    """
    pyproject = ROOT / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)

    def _pkg_names(deps: list) -> set[str]:
        """Normalize 'pkg>=x.y' entries to bare lowercase package names."""
        names: set[str] = set()
        for dep in deps:
            if not isinstance(dep, str):
                continue
            # Strip PEP 508 version specifiers and extras: 'pkg[x]>=1' -> 'pkg'
            bare = dep.split(">")[0].split("<")[0].split("=")[0].split("!")[0].split("[")[0]
            names.add(bare.strip().lower())
        return names

    optional_dev: list = data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    dep_group_dev: list = data.get("dependency-groups", {}).get("dev", [])

    optional_names = _pkg_names(optional_dev)
    dep_group_names = _pkg_names(dep_group_dev)

    required = {
        "build": "release_readiness_gate.py (python -m build)",
        "twine": "release_artifact_gate.py (python -m twine)",
    }
    for pkg, source in required.items():
        assert pkg in optional_names, (
            f"'{pkg}' missing from [project.optional-dependencies].dev — required by {source}"
        )
        assert pkg in dep_group_names, (
            f"'{pkg}' missing from [dependency-groups].dev — required by {source}"
        )
