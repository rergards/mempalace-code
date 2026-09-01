"""Tests for scripts/gate_inventory.py — canonical gate inventory and parity checker."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

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
        "gitleaks_fixture_smoke",
        "gitleaks_validate_baseline",
        "gitleaks_changed_range",
        "scorecard",
        "architecture_guard",
    }
    present = {g["id"] for g in gi.CANONICAL_GATES}
    missing = required_ids - present
    assert not missing, f"missing required quality gates: {sorted(missing)}"


def test_workflow_security_gates_are_canonical_and_wired_into_ci():
    expected = {
        "workflow_lint": gi.ACTIONLINT_COMMAND,
        "workflow_audit": gi.ZIZMOR_COMMAND,
    }
    gates = gi.gates_by_id()
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for gate_id, command in expected.items():
        gate = gates[gate_id]
        assert gate["category"] == "quality"
        assert gate["surfaces"] == [".github/workflows/ci.yml"]
        assert gate["command"] == command
        assert command in ci_text, f"gate '{gate_id}' is not wired into the CI lint job"

    # Excessive permissions and credential-persisting checkouts are medium-severity
    # zizmor audits, so the blocking tier must not drift back up to high.
    assert "--min-severity=medium" in gi.ZIZMOR_COMMAND
    # A workflow is only as safe as the actions it calls, so repository-local
    # composite actions stay inside the audited scope.
    assert ".github/workflows/" in gi.ZIZMOR_COMMAND
    assert ".github/actions/" in gi.ZIZMOR_COMMAND


def test_ci_has_one_upstream_gate_owner_through_package_preflight():
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    preflight_text = (ROOT / "scripts" / "release_preflight.py").read_text(encoding="utf-8")

    assert ci_text.count("run: python scripts/release_preflight.py") == 1
    assert "run: python scripts/upstream_comparison_guard.py" not in ci_text
    assert preflight_text.count('"scripts/upstream_comparison_guard.py"') == 2
    assert "release_public_read.py" not in ci_text


def _pinned_version(deps: list, name: str) -> str | None:
    """Return the exactly-pinned version of ``name`` in a dependency list."""
    for dep in deps:
        if isinstance(dep, str) and dep.startswith(f"{name}=="):
            return dep.split("==", 1)[1]
    return None


def _locked_version(lock: dict, name: str) -> str | None:
    for package in lock.get("package", []):
        if isinstance(package, dict) and package.get("name") == name:
            version = package.get("version")
            return version if isinstance(version, str) else None
    return None


def test_workflow_security_tools_are_pinned_consistently_across_dependency_surfaces():
    """The scanner pins must agree between both dev surfaces and uv.lock.

    Versions are read, never restated, so a routine bump needs no test edit.
    """
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    with (ROOT / "uv.lock").open("rb") as fh:
        lock = tomllib.load(fh)

    for name in ("actionlint-py", "zizmor"):
        optional = _pinned_version(pyproject["project"]["optional-dependencies"]["dev"], name)
        group = _pinned_version(pyproject["dependency-groups"]["dev"], name)
        assert optional is not None, f"{name} must be exactly pinned in optional-dependencies.dev"
        assert group == optional, f"{name} pins differ across pyproject dev surfaces"
        assert _locked_version(lock, name) == optional, f"uv.lock {name} drifted from pyproject"


def test_required_release_artifact_gates_present():
    required_ids = {
        "performance_budgets",
        "artifact_gate",
        "release_readiness",
        "install_smoke",
        "public_safety_committed",
        "gitleaks_full_history",
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
        "gitleaks_fixture_smoke",
        "gitleaks_changed_range",
        "scorecard",
        "architecture_guard",
    }
    missing = expected_in_verify - set(gi.VERIFY_SURFACE_IDS)
    assert not missing, f"missing from verify surface: {sorted(missing)}"


def test_gitleaks_gates_are_canonical_and_wired_into_ci():
    gates = gi.gates_by_id()
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    publish_text = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    history_text = (ROOT / ".github" / "workflows" / "gitleaks-history.yml").read_text(
        encoding="utf-8"
    )
    verify_text = (ROOT / ".claude" / "skills" / "verify" / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )

    # The CLI version is read from the checksum-locked tool module, never restated
    # here, so a Dependabot bump of tools/gitleaks/go.mod needs no test edit.
    assert gi.gitleaks_cli_version(ROOT).startswith("v8.")
    assert gates["gitleaks_changed_range"]["command"] == gi.GITLEAKS_CHANGED_RANGE_COMMAND
    assert gates["gitleaks_full_history"]["command"] == gi.GITLEAKS_FULL_HISTORY_COMMAND
    assert gates["gitleaks_fixture_smoke"]["command"] == gi.GITLEAKS_FIXTURE_SMOKE_COMMAND
    assert gates["gitleaks_validate_baseline"]["command"] == gi.GITLEAKS_VALIDATE_BASELINE_COMMAND
    assert gates["gitleaks_install"]["command"] == gi.GITLEAKS_INSTALL_COMMAND
    assert gates["gitleaks_changed_range"]["category"] == "quality"
    assert gates["gitleaks_full_history"]["category"] == "release"
    assert gates["gitleaks_fixture_smoke"]["category"] == "quality"
    assert gates["gitleaks_validate_baseline"]["category"] == "quality"
    assert gates["gitleaks_validate_baseline"]["surfaces"] == []
    assert gates["gitleaks_install"]["category"] == "install"

    assert gi.GITLEAKS_INSTALL_COMMAND in ci_text
    assert "python scripts/gitleaks_scan.py changed-range" in ci_text
    assert "--base-ref" in ci_text
    assert "--head-ref" in ci_text
    assert gi.GITLEAKS_INSTALL_COMMAND in publish_text
    assert gi.GITLEAKS_INSTALL_COMMAND in history_text
    assert gi.GITLEAKS_FULL_HISTORY_COMMAND in publish_text
    assert gi.GITLEAKS_FULL_HISTORY_COMMAND in history_text
    assert gi.GITLEAKS_FIXTURE_SMOKE_COMMAND in verify_text
    assert "gitleaks_fixture_smoke" in gi.VERIFY_SURFACE_IDS
    for text in (ci_text, publish_text, history_text):
        assert gi.GITLEAKS_FIXTURE_SMOKE_COMMAND in text
        assert gi.GITLEAKS_VALIDATE_BASELINE_COMMAND not in text
        # A mutable `go install ...@tag` must never come back into a workflow.
        assert f"{gi.GITLEAKS_GO_MODULE}@" not in text
        assert "gitleaks/v8@" not in text


def test_gitleaks_cli_version_is_read_from_the_locked_tool_module(tmp_path):
    module_dir = tmp_path / "tools" / "gitleaks"
    module_dir.mkdir(parents=True)
    (module_dir / "go.mod").write_text(
        f"module example.com/tools\n\ngo 1.24.11\n\nrequire {gi.GITLEAKS_GO_MODULE} v8.99.0\n",
        encoding="utf-8",
    )
    assert gi.gitleaks_cli_version(tmp_path) == "v8.99.0"

    (module_dir / "go.mod").write_text("module example.com/tools\n\ngo 1.24.11\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not require"):
        gi.gitleaks_cli_version(tmp_path)

    with pytest.raises(ValueError, match="unreadable"):
        gi.gitleaks_cli_version(tmp_path / "absent")


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


def _ruff_dep_string(deps: list[str]) -> str:
    matches = [dep for dep in deps if dep.startswith("ruff")]
    assert len(matches) == 1
    return matches[0]


def _write_ruff_contract_tree(root: Path) -> None:
    root.mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".pre-commit-config.yaml").write_text(
        "\n".join(
            [
                "repos:",
                f"  - repo: {gi.RUFF_PRE_COMMIT_REPO}",
                "    rev: v0.15.16",
                "    hooks:",
                "      - id: ruff",
                "        args: [--fix]",
                f"        files: {gi.CANONICAL_RUFF_PRECOMMIT_FILES}",
                "      - id: ruff-format",
                f"        files: {gi.CANONICAL_RUFF_PRECOMMIT_FILES}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "mempalace-code"',
                "",
                "[project.optional-dependencies]",
                'dev = ["ruff==0.15.16"]',
                "",
                "[dependency-groups]",
                'dev = ["ruff==0.15.16"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        "\n".join(
            [
                "[[package]]",
                'name = "mempalace-code"',
                'version = "1.13.5"',
                "",
                "[package.metadata]",
                'requires-dist = [{ name = "ruff", marker = "extra == \'dev\'", specifier = "==0.15.16" }]',
                "",
                "[package.metadata.requires-dev]",
                'dev = [{ name = "ruff", specifier = "==0.15.16" }]',
                "",
                "[[package]]",
                'name = "ruff"',
                'version = "0.15.16"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "\n".join(
            [
                "name: Tests",
                "jobs:",
                "  lint:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v5",
                f"      - run: {gi.RUFF_CI_DEV_INSTALL_COMMAND}",
                "      - run: ruff check mempalace_code/ tests/ scripts/",
                "      - run: ruff format --check mempalace_code/ tests/ scripts/",
                "  package:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - run: python -m build",
                "",
            ]
        ),
        encoding="utf-8",
    )


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
            "command": (
                "python scripts/release_readiness_gate.py --check "
                '--candidate-sha "$CANDIDATE_SHA" --json'
            ),
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


def test_ruff_precommit_hooks_match_canonical_source_scope():
    rev, hook_files = gi._precommit_ruff_contract(ROOT)
    assert rev == "v0.15.16"
    assert set(gi.RUFF_HOOK_IDS).issubset(hook_files)

    included = [
        "mempalace_code/storage.py",
        "tests/test_gate_inventory.py",
        "scripts/gate_inventory.py",
    ]
    excluded = [
        "mempalace/storage.py",
        "docs/example.py",
        "scripts/gate_inventory.txt",
        ".github/workflows/ci.yml",
    ]

    for hook_id in gi.RUFF_HOOK_IDS:
        pattern = hook_files[hook_id]
        assert pattern == gi.CANONICAL_RUFF_PRECOMMIT_FILES
        compiled = re.compile(pattern)
        assert [path for path in included if compiled.search(path)] == included
        assert not [path for path in excluded if compiled.search(path)]


def test_ruff_version_contract_matches_pyproject_ci_precommit_and_lock():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    version = "0.15.16"
    assert (
        _ruff_dep_string(pyproject["project"]["optional-dependencies"]["dev"]) == f"ruff=={version}"
    )
    assert _ruff_dep_string(pyproject["dependency-groups"]["dev"]) == f"ruff=={version}"

    with (ROOT / "uv.lock").open("rb") as fh:
        lock = tomllib.load(fh)
    ruff_package = gi._lock_package(lock, "ruff")
    assert ruff_package is not None
    assert ruff_package["version"] == version
    project_package = gi._lock_package(lock, "mempalace-code")
    assert project_package is not None
    metadata = project_package["metadata"]
    assert gi._lock_dep_specifier(metadata["requires-dist"], "ruff") == f"=={version}"
    assert gi._lock_dep_specifier(metadata["requires-dev"]["dev"], "ruff") == f"=={version}"

    rev, _hook_files = gi._precommit_ruff_contract(ROOT)
    assert rev == f"v{version}"
    lint_job = gi._ci_lint_job_text(ROOT)
    assert lint_job is not None
    assert gi.RUFF_CI_DEV_INSTALL_COMMAND in lint_job
    assert "ruff check mempalace_code/ tests/ scripts/" in lint_job
    assert "ruff format --check mempalace_code/ tests/ scripts/" in lint_job
    assert gi.check_ruff_contract(ROOT) == []


def test_ruff_contract_reports_scope_version_and_ci_boundary_drift(tmp_path):
    root = tmp_path / "repo"
    _write_ruff_contract_tree(root)
    assert gi.check_ruff_contract(root) == []

    (root / ".pre-commit-config.yaml").write_text(
        "\n".join(
            [
                "repos:",
                f"  - repo: {gi.RUFF_PRE_COMMIT_REPO}",
                "    rev: v0.9.0",
                "    hooks:",
                "      - id: ruff",
                "        files: ^(mempalace|tests)/.*\\.py$",
                "      - id: ruff-format",
                "        files: ^(mempalace|tests)/.*\\.py$",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        "\n".join(
            [
                "[[package]]",
                'name = "mempalace-code"',
                'version = "1.13.5"',
                "",
                "[package.metadata]",
                'requires-dist = [{ name = "ruff", marker = "extra == \'dev\'", specifier = "==0.9.0" }]',
                "",
                "[package.metadata.requires-dev]",
                'dev = [{ name = "ruff", specifier = "==0.9.0" }]',
                "",
                "[[package]]",
                'name = "ruff"',
                'version = "0.9.0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "\n".join(
            [
                "name: Tests",
                "jobs:",
                "  lint:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v5",
                "      - run: pip install ruff",
                "      - run: pre-commit run --all-files",
                "  package:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - run: python -m build",
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = gi.check_ruff_contract(root)
    joined = "\n".join(errors)
    assert "RUFF-HOOK-SCOPE-DRIFT" in joined
    assert "RUFF-HOOK-REV-DRIFT" in joined
    assert "RUFF-LOCK-VERSION-DRIFT" in joined
    assert "RUFF-CI-INSTALL-DRIFT" in joined
    assert "RUFF-CI-DIRECT-GATE-DRIFT" in joined


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


def test_release_readiness_command_binds_candidate_sha_on_declared_surfaces():
    assert gi.RELEASE_READINESS_COMMAND == (
        'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
    )
    row = next(gate for gate in gi.CANONICAL_GATES if gate["id"] == "release_readiness")
    assert row["command"] == gi.RELEASE_READINESS_COMMAND
    assert row["surfaces"] == ["docs/RELEASING.md", ".claude/skills/release/SKILL.md"]


def test_install_smoke_inventory_uses_canonical_aggregate_owner():
    row = next(gate for gate in gi.CANONICAL_GATES if gate["id"] == "install_smoke")
    assert row["command"] == (
        "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json"
    )


def test_installed_golden_inventory_has_distinct_readiness_owner_and_surfaces():
    manager = next(gate for gate in gi.CANONICAL_GATES if gate["id"] == "install_smoke")
    golden = next(gate for gate in gi.CANONICAL_GATES if gate["id"] == "installed_golden")

    assert golden["command"] == gi.INSTALLED_GOLDEN_COMMAND
    assert golden["command"] != manager["command"]
    assert "release_readiness_gate.py" in golden["command"]
    assert "release_install_metadata_smoke.py" in manager["command"]
    assert golden["surfaces"] == ["docs/RELEASING.md", ".github/workflows/ci.yml"]
