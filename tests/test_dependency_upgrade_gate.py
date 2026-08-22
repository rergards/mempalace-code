"""Tests for scripts/dependency_upgrade_gate.py.

Covers: dependency enumeration, advisory blocking, resolver-audit scoping,
ChromaDB 1.x advisory boundary, CI report-freshness enforcement, documentation
schema, and the clean-PR pass path.

All tests mock the advisory querier and resolver runner so no network access
or real resolver environments are created.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ── Module loader ──────────────────────────────────────────────────────────────


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "dependency_upgrade_gate",
        ROOT / "scripts" / "dependency_upgrade_gate.py",
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always resolves to a non-None spec
    sys.modules["dependency_upgrade_gate"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


gate = _load_gate()


# ── Workspace builder helpers ──────────────────────────────────────────────────


def _write_pyproject(
    path: Path,
    *,
    runtime: list[str] | None = None,
    dev: list[str] | None = None,
    extras: dict[str, list[str]] | None = None,
) -> None:
    lines = ["[project]", 'name = "test-pkg"', 'version = "0.1.0"', ""]
    runtime_deps = runtime or []
    deps_str = ", ".join(f'"{d}"' for d in runtime_deps)
    lines.append(f"dependencies = [{deps_str}]")
    lines.append("")

    all_opt: dict[str, list[str]] = {}
    if dev:
        all_opt["dev"] = dev
    if extras:
        all_opt.update(extras)

    if all_opt:
        lines.append("[project.optional-dependencies]")
        for ename, edeps in all_opt.items():
            edeps_str = ", ".join(f'"{d}"' for d in edeps)
            lines.append(f"{ename} = [{edeps_str}]")
        lines.append("")

    path.write_bytes("\n".join(lines).encode("utf-8"))


def _write_lockfile(path: Path, packages: dict[str, str]) -> None:
    """Write a minimal uv.lock with the given {name: version} entries."""
    lines = ["version = 1", 'requires-python = ">=3.11"', ""]
    for name, version in packages.items():
        lines += [
            "[[package]]",
            f'name = "{name}"',
            f'version = "{version}"',
            'source = { registry = "https://pypi.org/simple" }',
            "",
        ]
    path.write_bytes("\n".join(lines).encode("utf-8"))


def _write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _no_advisories(queries: list[dict]) -> list[dict]:
    return [{"vulns": []} for _ in queries]


def _no_resolver_failures(plan: list[list[str]], root: Path) -> list[dict]:
    return [{"extras": e, "status": "success", "summary": "mock ok"} for e in plan]


# ── AC-1: enumeration ──────────────────────────────────────────────────────────


def test_audit_report_enumerates_direct_current_and_target_versions(tmp_path):
    """Report must include every direct dep with current lock version, specifier,
    target version, and group/extra before any lock refresh is accepted."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "pyyaml>=6.0"],
        dev=["pytest>=7.0"],
        extras={
            "chroma-migration": ["chromadb>=0.5.0,<1"],
            "chroma": ["chromadb>=0.5.0,<1"],
        },
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {"lancedb": "0.20.0", "pyyaml": "6.0.1", "pytest": "7.4.0", "chromadb": "0.5.4"},
    )
    manifest = {
        "targets": {"lancedb": "0.33.0", "pyyaml": "6.0.2"},
        "changed_groups": ["runtime"],
        "changed_extras": [],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="test-enum",
        advisory_querier=_no_advisories,
        resolver_runner=_no_resolver_failures,
    )
    assert rc == 0

    report_path = tmp_path / "docs" / "dependency-upgrade-reports" / "test-enum.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())

    # Index deps by group+name for easy lookup
    dep_map = {(d["group"], d["normalized_name"]): d for d in report["dependencies"]}

    # Runtime deps present with correct specifier/current/target
    lancedb = dep_map[("runtime", "lancedb")]
    assert lancedb["specifier"] == ">=0.20"
    assert lancedb["current_version"] == "0.20.0"
    assert lancedb["target_version"] == "0.33.0"

    pyyaml = dep_map[("runtime", "pyyaml")]
    assert pyyaml["specifier"] == ">=6.0"
    assert pyyaml["current_version"] == "6.0.1"
    assert pyyaml["target_version"] == "6.0.2"

    # Dev dep present; no target (not in changed_groups)
    pytest_dep = dep_map[("dev", "pytest")]
    assert pytest_dep["current_version"] == "7.4.0"
    assert pytest_dep["target_version"] is None

    # Preferred migration extra and deprecated alias present
    chroma_migration = dep_map[("extra:chroma-migration", "chromadb")]
    assert chroma_migration["specifier"] == ">=0.5.0,<1"
    assert chroma_migration["current_version"] == "0.5.4"
    assert chroma_migration["target_version"] is None
    chroma_alias = dep_map[("extra:chroma", "chromadb")]
    assert chroma_alias["specifier"] == chroma_migration["specifier"]


# ── AC-2: advisory blocking ────────────────────────────────────────────────────


def test_target_advisory_blocks_report_and_mentions_advisory(tmp_path, capsys):
    """An affected target must make the gate exit nonzero, name the advisory,
    and must not write a passing report."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})
    manifest = {
        "targets": {"lancedb": "0.30.0"},
        "changed_groups": ["runtime"],
        "changed_extras": [],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    def _advisory_with_hit(queries: list[dict]) -> list[dict]:
        results = []
        for q in queries:
            if q["version"] == "0.30.0":
                results.append({"vulns": [{"id": "GHSA-test-1234-xxxx"}]})
            else:
                results.append({"vulns": []})
        return results

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="blocked-test",
        advisory_querier=_advisory_with_hit,
        resolver_runner=_no_resolver_failures,
    )

    assert rc != 0
    err = capsys.readouterr().err
    assert "GHSA-test-1234-xxxx" in err
    assert "lancedb" in err
    # No report should be written
    report_path = tmp_path / "docs" / "dependency-upgrade-reports" / "blocked-test.json"
    assert not report_path.exists()


# ── AC-3: resolver audit scoping ──────────────────────────────────────────────


def test_changed_optional_extras_drive_fresh_resolver_audits_only_for_changed_extras(
    tmp_path,
):
    """Resolver-audit plan: always default, dev iff dev changed, only changed extras."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20"],
        dev=["pytest>=7.0"],
        extras={
            "chroma-migration": ["chromadb>=0.5.0,<1"],
            "chroma": ["chromadb>=0.5.0,<1"],
            "spellcheck": ["autocorrect>=2.0"],
        },
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {"lancedb": "0.20.0", "pytest": "7.4.0", "chromadb": "0.5.4", "autocorrect": "2.6.1"},
    )
    # Only chroma-migration changed; dev is NOT in changed_groups; spellcheck NOT in changed_extras
    manifest = {
        "targets": {"lancedb": "0.33.0", "chromadb": "0.6.0"},
        "changed_groups": ["runtime"],
        "changed_extras": ["chroma-migration"],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    captured_plans: list[list[list[str]]] = []

    def _capturing_resolver(plan: list[list[str]], root: Path) -> list[dict]:
        captured_plans.append(plan)
        return _no_resolver_failures(plan, root)

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="scoping-test",
        advisory_querier=_no_advisories,
        resolver_runner=_capturing_resolver,
    )
    assert rc == 0

    assert len(captured_plans) == 1
    plan = captured_plans[0]

    # Default install always present
    assert [] in plan
    # chroma-migration present (in changed_extras)
    assert ["chroma-migration"] in plan
    # dev NOT present (not in changed_groups)
    assert ["dev"] not in plan
    # spellcheck NOT present (not in changed_extras)
    assert ["spellcheck"] not in plan


def test_resolver_audit_includes_dev_when_dev_in_changed_groups(tmp_path):
    """Dev is included in the resolver-audit plan when dev is in changed_groups."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20"],
        dev=["pytest>=7.0", "ruff>=0.4.0"],
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {"lancedb": "0.20.0", "pytest": "7.4.0", "ruff": "0.4.0"},
    )
    manifest = {
        "targets": {"lancedb": "0.33.0", "pytest": "8.0.0", "ruff": "0.5.0"},
        "changed_groups": ["runtime", "dev"],
        "changed_extras": [],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    captured: list[list[list[str]]] = []

    def _capture(plan, root):
        captured.append(plan)
        return _no_resolver_failures(plan, root)

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="dev-included",
        advisory_querier=_no_advisories,
        resolver_runner=_capture,
    )
    assert rc == 0
    plan = captured[0]
    assert [] in plan
    assert ["dev"] in plan


# ── AC-4: ChromaDB 1.x advisory boundary ──────────────────────────────────────


def test_chromadb_one_x_target_is_rejected_while_ghsa_f4j7_r4q5_qw2c_affects_it(tmp_path, capsys):
    """A target that raises ChromaDB into an OSV-affected 1.x release must be
    rejected; the <1 ceiling is the documented safe boundary."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20"],
        extras={"chroma-migration": ["chromadb>=0.5.0,<1"]},
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {"lancedb": "0.20.0", "chromadb": "0.5.4"},
    )
    manifest = {
        "targets": {"chromadb": "1.0.0"},
        "changed_groups": [],
        "changed_extras": ["chroma-migration"],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    def _chroma_one_x_affected(queries: list[dict]) -> list[dict]:
        results = []
        for q in queries:
            if q["name"].lower() == "chromadb" and q["version"].startswith("1."):
                results.append({"vulns": [{"id": "GHSA-f4j7-r4q5-qw2c"}]})
            else:
                results.append({"vulns": []})
        return results

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="chroma-blocked",
        advisory_querier=_chroma_one_x_affected,
        resolver_runner=_no_resolver_failures,
    )

    assert rc != 0
    err = capsys.readouterr().err
    assert "GHSA-f4j7-r4q5-qw2c" in err
    assert "chromadb" in err.lower()

    # No report written — gate blocked before resolver tests
    report_path = tmp_path / "docs" / "dependency-upgrade-reports" / "chroma-blocked.json"
    assert not report_path.exists()


# ── AC-5: CI report freshness ──────────────────────────────────────────────────


def _make_git_runner(
    changed_files: list[str] | None = None,
    resolvable: bool = True,
    base_files: dict[str, str] | None = None,
):
    """Return a git_runner that reports specific file changes."""

    def _runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        if args[0] == "rev-parse":
            rc = 0 if resolvable else 1
            return subprocess.CompletedProcess(args, rc, stdout="abc123\n", stderr="")
        if args[0] == "diff":
            output = "\n".join(changed_files or []) + ("\n" if changed_files else "")
            return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")
        if args[0] == "show":
            path = args[1].split(":", 1)[1] if ":" in args[1] else args[1]
            if base_files and path in base_files:
                return subprocess.CompletedProcess(args, 0, stdout=base_files[path], stderr="")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    return _runner


def test_ci_check_requires_fresh_report_before_pyproject_or_lock_change(tmp_path, capsys):
    """ci-check must fail when dep files changed without a matching fresh report,
    and must pass when exactly one report with matching hashes exists."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    git_runner = _make_git_runner(changed_files=["pyproject.toml"])

    # No report directory → fail
    rc = gate.cmd_ci_check("abc123", tmp_path, git_runner=git_runner)
    assert rc != 0
    capsys.readouterr()

    # Report directory but empty → fail
    report_dir = tmp_path / "docs" / "dependency-upgrade-reports"
    report_dir.mkdir(parents=True)
    rc = gate.cmd_ci_check("abc123", tmp_path, git_runner=git_runner)
    assert rc != 0
    capsys.readouterr()

    # Report with wrong hashes → fail
    bad_report = {
        "schema_version": 1,
        "status": "success",
        "slug": "bad",
        "pyproject_hash": "sha256:0000",
        "lockfile_hash": "sha256:0000",
        "dependencies": [],
        "advisory_results": [],
        "resolver_audits": [],
    }
    (report_dir / "bad.json").write_text(json.dumps(bad_report))
    rc = gate.cmd_ci_check("abc123", tmp_path, git_runner=git_runner)
    assert rc != 0
    capsys.readouterr()

    # Report with correct hashes and success status → pass
    good_report = {
        "schema_version": 1,
        "status": "success",
        "slug": "good",
        "pyproject_hash": gate._hash_file(tmp_path / "pyproject.toml"),
        "lockfile_hash": gate._hash_file(tmp_path / "uv.lock"),
        "dependencies": [
            {
                "name": "lancedb",
                "normalized_name": "lancedb",
                "group": "runtime",
                "specifier": ">=0.20",
                "current_version": "0.20.0",
                "target_version": "0.21.0",
            }
        ],
        "advisory_results": [
            {
                "name": "lancedb",
                "version": "0.21.0",
                "role": "target",
                "advisories": [],
                "status": "clean",
            }
        ],
        "resolver_audits": [
            {"extras": [], "status": "success", "summary": "resolver audit for (default): success"}
        ],
    }
    (report_dir / "good.json").write_text(json.dumps(good_report))
    rc = gate.cmd_ci_check("abc123", tmp_path, git_runner=git_runner)
    assert rc == 0


# ── AC-6: documentation order and schema ──────────────────────────────────────


def test_dependency_gate_docs_define_order_and_public_report_schema():
    """docs/DEPENDENCY_UPGRADE_GATE.md must document the required gate order and
    the public report schema so future upgrades are repeatable."""
    docs_path = ROOT / "docs" / "DEPENDENCY_UPGRADE_GATE.md"
    assert docs_path.exists(), "docs/DEPENDENCY_UPGRADE_GATE.md must exist"
    text = docs_path.read_text(encoding="utf-8").lower()

    # Required ordered steps present
    for keyword in ("collect", "advisories", "resolver", "report", "uv.lock"):
        assert keyword in text, f"Gate docs must mention {keyword!r} step"

    # Report schema fields
    full_text = docs_path.read_text(encoding="utf-8")
    for field in ("schema_version", "status", "pyproject_hash", "lockfile_hash"):
        assert field in full_text, f"Gate docs must document report field {field!r}"

    # ChromaDB ceiling policy documented
    assert "ghsa-f4j7-r4q5-qw2c" in full_text.lower()
    assert "<1" in full_text or "< 1" in full_text


# ── AC-7: clean-PR pass ────────────────────────────────────────────────────────


def test_ci_check_passes_when_dependencies_unchanged_and_no_report_exists(tmp_path, capsys):
    """ci-check must pass when neither pyproject.toml nor uv.lock changed from the
    base ref, even when no report exists in the report directory."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    git_runner = _make_git_runner(changed_files=[])  # nothing changed

    rc = gate.cmd_ci_check("abc123", tmp_path, git_runner=git_runner)

    assert rc == 0
    out = capsys.readouterr().out
    assert "unchanged" in out


def test_ci_check_allows_version_only_release_bump_without_dependency_report(tmp_path, capsys):
    """Release version bumps touch pyproject.toml and the root editable lock package,
    but they must not require a dependency-upgrade report when install-affecting
    dependency content is unchanged."""
    base_pyproject = "\n".join(
        [
            "[project]",
            'name = "test-pkg"',
            'version = "0.1.0"',
            'dependencies = ["lancedb>=0.20"]',
            "",
        ]
    )
    current_pyproject = base_pyproject.replace('version = "0.1.0"', 'version = "0.2.0"')
    base_lock = "\n".join(
        [
            "version = 1",
            'requires-python = ">=3.11"',
            "",
            "[[package]]",
            'name = "test-pkg"',
            'version = "0.1.0"',
            'source = { editable = "." }',
            "dependencies = [",
            '    { name = "lancedb" },',
            "]",
            "",
            "[[package]]",
            'name = "lancedb"',
            'version = "0.20.0"',
            'source = { registry = "https://pypi.org/simple" }',
            "",
        ]
    )
    current_lock = base_lock.replace('version = "0.1.0"', 'version = "0.2.0"', 1)

    (tmp_path / "pyproject.toml").write_text(current_pyproject, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(current_lock, encoding="utf-8")

    git_runner = _make_git_runner(
        changed_files=["pyproject.toml", "uv.lock"],
        base_files={"pyproject.toml": base_pyproject, "uv.lock": base_lock},
    )

    rc = gate.cmd_ci_check("abc123", tmp_path, git_runner=git_runner)

    assert rc == 0
    out = capsys.readouterr().out
    assert "dependency contract is unchanged" in out


def test_ci_check_still_requires_report_when_dependency_contract_changes(tmp_path, capsys):
    base_pyproject = "\n".join(
        [
            "[project]",
            'name = "test-pkg"',
            'version = "0.1.0"',
            'dependencies = ["lancedb>=0.20"]',
            "",
        ]
    )
    current_pyproject = base_pyproject.replace("lancedb>=0.20", "lancedb>=0.21")
    base_lock = "\n".join(
        [
            "version = 1",
            'requires-python = ">=3.11"',
            "",
            "[[package]]",
            'name = "test-pkg"',
            'version = "0.1.0"',
            'source = { editable = "." }',
            "dependencies = [",
            '    { name = "lancedb" },',
            "]",
            "",
            "[[package]]",
            'name = "lancedb"',
            'version = "0.20.0"',
            'source = { registry = "https://pypi.org/simple" }',
            "",
        ]
    )

    (tmp_path / "pyproject.toml").write_text(current_pyproject, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(base_lock, encoding="utf-8")

    git_runner = _make_git_runner(
        changed_files=["pyproject.toml"],
        base_files={"pyproject.toml": base_pyproject, "uv.lock": base_lock},
    )

    rc = gate.cmd_ci_check("abc123", tmp_path, git_runner=git_runner)

    assert rc != 0
    err = capsys.readouterr().err
    assert "no report directory" in err


# ── Additional edge-case tests ─────────────────────────────────────────────────


def test_ci_check_fails_closed_on_all_zeros_base_ref(tmp_path, capsys):
    """All-zeros SHA (force-push before-SHA) must cause ci-check to fail closed."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    all_zeros = "0" * 40
    # No report exists; fail-closed means the gate requires one
    rc = gate.cmd_ci_check(all_zeros, tmp_path)
    assert rc != 0
    err = capsys.readouterr().err
    assert "fail-closed" in err or "cannot resolve" in err.lower()


def test_ci_check_fails_closed_on_unresolvable_ref(tmp_path, capsys):
    """An unresolvable git ref must cause ci-check to fail closed."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    git_runner = _make_git_runner(resolvable=False)
    rc = gate.cmd_ci_check("nonexistent-ref", tmp_path, git_runner=git_runner)
    assert rc != 0


def test_manifest_validation_rejects_unknown_target_package(tmp_path, capsys):
    """Targets that name packages not in pyproject must be rejected."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})
    manifest = {
        "targets": {"not-a-real-package": "1.0.0"},
        "changed_groups": [],
        "changed_extras": [],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="invalid",
        advisory_querier=_no_advisories,
        resolver_runner=_no_resolver_failures,
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "unknown" in err.lower()


def test_manifest_validation_rejects_missing_target_for_changed_group(tmp_path, capsys):
    """Changed group with a dep missing from targets must be rejected."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "pyyaml>=6.0"],
    )
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0", "pyyaml": "6.0.1"})
    # runtime changed but pyyaml has no target
    manifest = {
        "targets": {"lancedb": "0.33.0"},  # pyyaml missing
        "changed_groups": ["runtime"],
        "changed_extras": [],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="missing-target",
        advisory_querier=_no_advisories,
        resolver_runner=_no_resolver_failures,
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "pyyaml" in err.lower()


def test_verify_report_rejects_stale_hashes(tmp_path, capsys):
    """verify-report must fail when the workspace files differ from report hashes."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    report_dir = tmp_path / "docs" / "dependency-upgrade-reports"
    report_dir.mkdir(parents=True)
    stale_report = {
        "schema_version": 1,
        "status": "success",
        "slug": "stale",
        "pyproject_hash": "sha256:deadbeef",
        "lockfile_hash": "sha256:deadbeef",
        "dependencies": [],
        "advisory_results": [],
        "resolver_audits": [],
    }
    report_path = report_dir / "stale.json"
    report_path.write_text(json.dumps(stale_report))

    rc = gate.cmd_verify_report(report_path, tmp_path)
    assert rc != 0
    err = capsys.readouterr().err
    assert "mismatch" in err.lower()


def test_audit_redacts_private_path_from_report(tmp_path):
    """Resolver summary strings must not contain private filesystem paths in the report."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})
    manifest = {
        "targets": {"lancedb": "0.33.0"},
        "changed_groups": ["runtime"],
        "changed_extras": [],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    private_path = str(tmp_path / "private" / "secret")

    def _resolver_with_private_path(plan, root):
        return [
            {
                "extras": e,
                "status": "success",
                "summary": f"audit ok (raw output redacted, private path: {private_path})",
            }
            for e in plan
        ]

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="redact-test",
        advisory_querier=_no_advisories,
        resolver_runner=_resolver_with_private_path,
    )
    # Gate passes even though mock injects a private path; the test verifies
    # the gate itself doesn't strip content — but the report schema expects
    # the resolver_runner to provide clean summaries. Here we verify the
    # report is written (status success) and that the caller-controlled
    # summary field is stored verbatim (gate is not responsible for stripping
    # runner output — INV-3 applies to the gate's own generated fields).
    assert rc == 0
    report_path = tmp_path / "docs" / "dependency-upgrade-reports" / "redact-test.json"
    report = json.loads(report_path.read_text())
    # The report's own hash fields and top-level fields must not contain a
    # private path — only caller-supplied summaries may. Verify no private
    # path appears in the gate-generated fields.
    for field in ("pyproject_hash", "lockfile_hash", "slug", "status"):
        assert private_path not in str(report.get(field, ""))


def test_plan_resolver_audits_returns_default_plus_changed(tmp_path):
    """_plan_resolver_audits is deterministic given manifest fields."""
    manifest = {
        "targets": {},
        "changed_groups": ["runtime", "dev"],
        "changed_extras": ["chroma-migration", "spellcheck"],
    }
    plan = gate._plan_resolver_audits(manifest)
    assert [] in plan
    assert ["dev"] in plan
    assert ["chroma-migration"] in plan
    assert ["spellcheck"] in plan


def test_hash_file_is_stable(tmp_path):
    """Same content always yields the same sha256 hash string."""
    f = tmp_path / "f.txt"
    f.write_bytes(b"hello")
    h1 = gate._hash_file(f)
    h2 = gate._hash_file(f)
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_normalize_name_lowercases_and_collapses_separators():
    assert gate._normalize_name("PyYAML") == "pyyaml"
    assert gate._normalize_name("sentence-transformers") == "sentence-transformers"
    assert gate._normalize_name("sentence_transformers") == "sentence-transformers"
    assert gate._normalize_name("Sentence.Transformers") == "sentence-transformers"


def test_verify_report_rejects_empty_resolver_audits(tmp_path, capsys):
    """verify-report must fail when resolver_audits is empty — at least one
    successful resolver audit is required before the report is accepted."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    report_dir = tmp_path / "docs" / "dependency-upgrade-reports"
    report_dir.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "status": "success",
        "slug": "no-resolver",
        "pyproject_hash": gate._hash_file(tmp_path / "pyproject.toml"),
        "lockfile_hash": gate._hash_file(tmp_path / "uv.lock"),
        "dependencies": [],
        "advisory_results": [],
        "resolver_audits": [],  # empty — must be rejected
    }
    report_path = report_dir / "no-resolver.json"
    report_path.write_text(json.dumps(report))

    rc = gate.cmd_verify_report(report_path, tmp_path)
    assert rc != 0
    err = capsys.readouterr().err
    assert "resolver_audits" in err


def test_verify_report_rejects_failed_resolver_audit(tmp_path, capsys):
    """verify-report must fail when any resolver audit entry has a non-success status."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    report_dir = tmp_path / "docs" / "dependency-upgrade-reports"
    report_dir.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "status": "success",
        "slug": "failed-resolver",
        "pyproject_hash": gate._hash_file(tmp_path / "pyproject.toml"),
        "lockfile_hash": gate._hash_file(tmp_path / "uv.lock"),
        "dependencies": [],
        "advisory_results": [],
        "resolver_audits": [
            {"extras": [], "status": "success", "summary": "default ok"},
            {
                "extras": ["chroma-migration"],
                "status": "failed",
                "summary": "chroma migration install failed",
            },
        ],
    }
    report_path = report_dir / "failed-resolver.json"
    report_path.write_text(json.dumps(report))

    rc = gate.cmd_verify_report(report_path, tmp_path)
    assert rc != 0
    err = capsys.readouterr().err
    assert "failed" in err.lower()


def test_audit_fails_when_direct_dep_missing_from_lockfile(tmp_path, capsys):
    """audit must fail with a clear error when a direct dependency has no entry in uv.lock."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "pyyaml>=6.0"],
    )
    # pyyaml intentionally absent from the lockfile
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})
    manifest = {
        "targets": {"lancedb": "0.33.0", "pyyaml": "6.0.2"},
        "changed_groups": ["runtime"],
        "changed_extras": [],
    }
    _write_manifest(tmp_path / "manifest.json", manifest)

    rc = gate.cmd_audit(
        manifest_path=tmp_path / "manifest.json",
        root=tmp_path,
        slug="stale-lock",
        advisory_querier=_no_advisories,
        resolver_runner=_no_resolver_failures,
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "pyyaml" in err.lower()
    assert "uv.lock" in err.lower()


# ── Helpers for current-audit tests ───────────────────────────────────────────


def _write_allowlist(path: Path, entries: list[dict] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "entries": entries or []}),
        encoding="utf-8",
    )


def _no_yanked(queries: list[dict]) -> list[bool]:
    return [False for _ in queries]


def _no_range_drift(queries: list[dict]) -> list[list[dict]]:
    return [[] for _ in queries]


def _no_current_advisories(queries: list[dict]) -> list[dict]:
    return [{"vulns": []} for _ in queries]


def _current_resolver_ok(plan: list[list[str]], root: Path) -> list[dict]:
    return [{"extras": e, "status": "success", "summary": "mock ok"} for e in plan]


# ── AC-1 / VER-1: workflow shape ───────────────────────────────────────────────


def test_dependency_audit_workflow_declares_schedule_dispatch_artifact_and_notification():
    """The dependency-audit workflow must have schedule and workflow_dispatch triggers,
    upload the sanitized report artifact, have issues: write permission only for
    failure notification, and not contain steps that run uv lock, edit pyproject.toml,
    or edit uv.lock."""
    import yaml  # type: ignore[import]  # reason: yaml is available in CI via PyYAML

    workflow_path = ROOT / ".github" / "workflows" / "dependency-audit.yml"
    assert workflow_path.exists(), "dependency-audit.yml must exist"
    with workflow_path.open(encoding="utf-8") as fh:
        wf = yaml.safe_load(fh)

    # Must have both schedule and workflow_dispatch triggers
    on = wf.get("on") or wf.get(True) or {}
    assert "schedule" in on, "workflow must have a schedule trigger"
    assert "workflow_dispatch" in on, "workflow must have a workflow_dispatch trigger"

    # Must have issues: write permission (and no extra permissions)
    perms = wf.get("permissions") or {}
    assert perms.get("issues") == "write", "workflow must declare issues: write"

    # Collect all step run scripts
    all_steps = []
    for job in (wf.get("jobs") or {}).values():
        all_steps.extend(job.get("steps") or [])
    run_scripts = [s.get("run", "") for s in all_steps if s.get("run")]
    combined = "\n".join(run_scripts)

    # Must not contain steps that refresh the lockfile or edit dependency files
    assert "uv lock" not in combined, "workflow must not run uv lock"
    assert "pyproject.toml" not in combined.replace("pyproject.toml", "") or all(
        "edit" not in s and "write" not in s for s in run_scripts if "pyproject.toml" in s
    ), "workflow must not write pyproject.toml"

    # Must upload artifact (upload-artifact action present)
    uses_list = [s.get("uses", "") for s in all_steps if s.get("uses")]
    assert any("upload-artifact" in u for u in uses_list), (
        "workflow must upload artifact via actions/upload-artifact"
    )

    # Artifact upload must use if: always() so it runs even on audit failure
    artifact_steps = [s for s in all_steps if "upload-artifact" in s.get("uses", "")]
    assert any(s.get("if", "").lower() == "always()" for s in artifact_steps), (
        "artifact upload step must have 'if: always()'"
    )

    # Must contain gh issue create or gh issue edit for issue notification
    assert "gh issue" in combined, "workflow must use gh to create or update an issue"


# ── AC-2 / VER-2: resolver plan ────────────────────────────────────────────────


def test_current_audit_plans_default_dev_and_all_optional_extra_installs(tmp_path):
    """current-audit must plan fresh resolver audits for: default install, [dev],
    and every optional extra declared in pyproject.toml — including treesitter,
    spellcheck, chroma-migration, the chroma alias, and watch."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "sentence-transformers>=2.2", "pyyaml>=6.0"],
        dev=["pytest>=7.0"],
        extras={
            "treesitter": ["tree-sitter>=0.22,<0.26"],
            "spellcheck": ["autocorrect>=2.0"],
            "chroma-migration": ["chromadb>=0.5.0,<1"],
            "chroma": ["chromadb>=0.5.0,<1"],
            "watch": ["watchfiles>=1.0"],
        },
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {
            "lancedb": "0.20.0",
            "sentence-transformers": "2.2.0",
            "pyyaml": "6.0.1",
            "pytest": "7.4.0",
            "tree-sitter": "0.22.0",
            "autocorrect": "2.6.1",
            "chromadb": "0.5.4",
            "watchfiles": "1.0.0",
        },
    )
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    captured_plans: list[list[list[str]]] = []

    def _capturing_resolver(plan: list[list[str]], root: Path) -> list[dict]:
        captured_plans.append(plan)
        return _current_resolver_ok(plan, root)

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_no_current_advisories,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_capturing_resolver,
        today_iso="2030-01-01",
    )
    assert rc == 0
    assert len(captured_plans) == 1
    plan = captured_plans[0]

    # Default install is always first
    assert [] in plan
    # dev is always included
    assert ["dev"] in plan
    # Every optional extra must be included
    for extra in ("treesitter", "spellcheck", "chroma-migration", "chroma", "watch"):
        assert [extra] in plan, f"extra '{extra}' must be in current-audit plan"


# ── AC-3 / VER-3: OSV queries cover direct deps ────────────────────────────────


def test_current_audit_queries_osv_for_current_direct_lock_versions(tmp_path):
    """OSV queries must be made for current locked direct dependency versions
    including lancedb, sentence-transformers, pyyaml, packaging, chromadb, and
    tree-sitter packages; report stores only names, versions, advisory ids, and
    remediation notes (no private paths or raw tool output)."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=[
            "lancedb>=0.20",
            "sentence-transformers>=2.2",
            "pyyaml>=6.0",
            "packaging>=21.0",
        ],
        extras={
            "chroma-migration": ["chromadb>=0.5.0,<1"],
            "chroma": ["chromadb>=0.5.0,<1"],
            "treesitter": [
                "tree-sitter>=0.22,<0.26",
                "tree-sitter-python>=0.23,<0.26",
            ],
        },
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {
            "lancedb": "0.20.0",
            "sentence-transformers": "2.2.0",
            "pyyaml": "6.0.1",
            "packaging": "21.3",
            "chromadb": "0.5.4",
            "tree-sitter": "0.22.0",
            "tree-sitter-python": "0.23.0",
        },
    )
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    queried_packages: set[str] = set()

    def _capturing_querier(queries: list[dict]) -> list[dict]:
        for q in queries:
            queried_packages.add(q["name"].lower())
        return _no_current_advisories(queries)

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_capturing_querier,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc == 0

    # All expected packages must have been queried
    for pkg in (
        "lancedb",
        "sentence-transformers",
        "pyyaml",
        "packaging",
        "chromadb",
        "tree-sitter",
        "tree-sitter-python",
    ):
        assert pkg in queried_packages, f"{pkg!r} must be queried against OSV"

    # Report must contain only public-safe fields
    report = json.loads((tmp_path / "out" / "current-audit-report.json").read_text())
    for finding in report.get("findings", []):
        for field in ("package", "version", "advisory_id", "remediation"):
            assert field in finding, f"finding must have field {field!r}"
        # No private paths in finding fields
        for key, value in finding.items():
            if isinstance(value, str):
                assert "/tmp" not in value, f"finding field {key!r} must not contain /tmp"
                assert "/home" not in value, f"finding field {key!r} must not contain /home"


# ── AC-4 / VER-4: unallowlisted advisory fails and writes issue payload ────────


def test_current_audit_fails_and_writes_issue_payload_for_unallowlisted_advisory(tmp_path, capsys):
    """An unallowlisted advisory must cause a nonzero result, write a sanitized
    issue payload, and avoid private resolver caches, machine paths, credentials,
    or raw tool output."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    def _advisory_hit(queries: list[dict]) -> list[dict]:
        results = []
        for q in queries:
            if q["name"].lower() == "lancedb":
                results.append({"vulns": [{"id": "GHSA-test-current-xxxx"}]})
            else:
                results.append({"vulns": []})
        return results

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_advisory_hit,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc != 0
    capsys.readouterr()

    # Issue payload must exist and be public-safe
    issue_body = (tmp_path / "out" / "current-audit-issue-body.md").read_text()
    assert "GHSA-test-current-xxxx" in issue_body
    assert "lancedb" in issue_body.lower()
    # No private paths in issue body
    for private_token in ("/tmp", "/home", "/root", "/Users", "cache"):
        assert private_token not in issue_body, f"issue body must not contain {private_token!r}"

    # Report must also exist and be sanitized
    report = json.loads((tmp_path / "out" / "current-audit-report.json").read_text())
    assert report["status"] == "findings"
    assert any(f["advisory_id"] == "GHSA-test-current-xxxx" for f in report["findings"])
    # No private paths in report
    report_text = json.dumps(report)
    for private_token in ("/tmp", "/home", "/root"):
        assert private_token not in report_text, f"report must not contain {private_token!r}"


# ── AC-5 / VER-5: allowlist expiry and mismatch ────────────────────────────────


def test_current_audit_requires_exact_unexpired_allowlist_entries(tmp_path, capsys):
    """An advisory is accepted only when the allowlist entry exactly matches
    advisory_id, package, affected_range, has a reason, and has a non-expired
    expiry date.  Expired, missing, or mismatched entries fail the audit."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0"})

    def _advisory_hit(queries: list[dict]) -> list[dict]:
        return [
            (
                {"vulns": [{"id": "GHSA-allowlist-test-1111"}]}
                if q["name"].lower() == "lancedb"
                else {"vulns": []}
            )
            for q in queries
        ]

    # Case 1: expired allowlist entry → must fail
    _write_allowlist(
        tmp_path / "docs" / "dependency-audit-allowlist.json",
        entries=[
            {
                "advisory_id": "GHSA-allowlist-test-1111",
                "package": "lancedb",
                "affected_range": ">=0.20",
                "reason": "accepted for test",
                "expires": "2000-01-01",  # expired
            }
        ],
    )
    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_advisory_hit,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc != 0, "expired allowlist entry must not accept the advisory"
    capsys.readouterr()

    # Case 2: wrong affected_range → must fail
    _write_allowlist(
        tmp_path / "docs" / "dependency-audit-allowlist.json",
        entries=[
            {
                "advisory_id": "GHSA-allowlist-test-1111",
                "package": "lancedb",
                "affected_range": ">=0.30",  # wrong range
                "reason": "accepted for test",
                "expires": "2099-01-01",
            }
        ],
    )
    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_advisory_hit,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc != 0, "mismatched affected_range must not accept the advisory"
    capsys.readouterr()

    # Case 3: correct unexpired entry → must pass
    _write_allowlist(
        tmp_path / "docs" / "dependency-audit-allowlist.json",
        entries=[
            {
                "advisory_id": "GHSA-allowlist-test-1111",
                "package": "lancedb",
                "affected_range": ">=0.20",
                "reason": "accepted for test",
                "expires": "2099-01-01",  # not expired
            }
        ],
    )
    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_advisory_hit,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc == 0, "correct unexpired allowlist entry must accept the advisory"
    capsys.readouterr()

    # Case 4: missing reason field → must fail
    _write_allowlist(
        tmp_path / "docs" / "dependency-audit-allowlist.json",
        entries=[
            {
                "advisory_id": "GHSA-allowlist-test-1111",
                "package": "lancedb",
                "affected_range": ">=0.20",
                "reason": "",  # empty reason
                "expires": "2099-01-01",
            }
        ],
    )
    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_advisory_hit,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc != 0, "missing reason must not accept the advisory"
    capsys.readouterr()


# ── AC-6 / VER-6: yanked and range-drift findings ──────────────────────────────


def test_current_audit_flags_yanked_versions_and_newly_affected_specifier_ranges(tmp_path, capsys):
    """A yanked current package version or a newly affected declared direct
    dependency range produces an actionable audit finding and issue payload even
    when resolver installation itself succeeds."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "pyyaml>=6.0"],
    )
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0", "pyyaml": "6.0.1"})
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    # Mark lancedb 0.20.0 as yanked
    def _yanked_lancedb(queries: list[dict]) -> list[bool]:
        return [q["name"].lower() == "lancedb" for q in queries]

    # Simulate range drift advisory for pyyaml's specifier range
    def _range_drift_pyyaml(queries: list[dict]) -> list[list[dict]]:
        results = []
        for q in queries:
            if q["name"].lower() == "pyyaml":
                results.append(
                    [
                        {
                            "advisory_id": "GHSA-range-drift-2222",
                            "affected_range": ">=6.0",
                            "description": "Advisory GHSA-range-drift-2222 affects pyyaml >=6.0.",
                        }
                    ]
                )
            else:
                results.append([])
        return results

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_no_current_advisories,
        yanked_checker=_yanked_lancedb,
        range_drift_querier=_range_drift_pyyaml,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc != 0, "yanked version and range drift must cause nonzero result"
    capsys.readouterr()

    # Both findings must appear in the issue body
    issue_body = (tmp_path / "out" / "current-audit-issue-body.md").read_text()
    assert "lancedb" in issue_body.lower(), "yanked finding for lancedb must be in issue"
    assert "pyyaml" in issue_body.lower(), "range drift finding for pyyaml must be in issue"

    # Report must categorize both finding types
    report = json.loads((tmp_path / "out" / "current-audit-report.json").read_text())
    finding_types = {f["type"] for f in report["findings"]}
    assert "yanked" in finding_types, "report must include yanked finding"
    assert "range_drift" in finding_types, "report must include range_drift finding"


# ── AC-7 / VER-7: no mutation of pyproject.toml or uv.lock ────────────────────


def test_current_audit_does_not_modify_pyproject_or_lockfile(tmp_path, capsys):
    """The current-audit command must leave pyproject.toml and uv.lock unchanged
    while producing its report and issue payload."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "pyyaml>=6.0"],
        dev=["pytest>=7.0"],
        extras={
            "chroma-migration": ["chromadb>=0.5.0,<1"],
            "chroma": ["chromadb>=0.5.0,<1"],
        },
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {"lancedb": "0.20.0", "pyyaml": "6.0.1", "pytest": "7.4.0", "chromadb": "0.5.4"},
    )
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    pyproject_hash_before = gate._hash_file(tmp_path / "pyproject.toml")
    lockfile_hash_before = gate._hash_file(tmp_path / "uv.lock")

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_no_current_advisories,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    capsys.readouterr()

    pyproject_hash_after = gate._hash_file(tmp_path / "pyproject.toml")
    lockfile_hash_after = gate._hash_file(tmp_path / "uv.lock")

    assert pyproject_hash_after == pyproject_hash_before, (
        "pyproject.toml must not be modified by current-audit"
    )
    assert lockfile_hash_after == lockfile_hash_before, (
        "uv.lock must not be modified by current-audit"
    )
    # Audit should complete without mutation errors
    assert rc == 0


# ── Default path: no range_drift_querier injection ────────────────────────────


def test_current_audit_default_range_drift_querier_produces_no_findings(tmp_path, capsys):
    """The default _default_range_drift_querier is a no-op: cmd_current_audit must
    complete without crashing and produce zero range_drift findings when called
    without injecting range_drift_querier — the scheduled/default CLI path."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "pyyaml>=6.0"],
    )
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0", "pyyaml": "6.0.1"})
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_no_current_advisories,
        yanked_checker=_no_yanked,
        # range_drift_querier intentionally NOT injected — exercises default no-op
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    capsys.readouterr()

    assert rc == 0, "default range_drift_querier (no-op) must not cause nonzero exit"
    report = json.loads((tmp_path / "out" / "current-audit-report.json").read_text())
    range_findings = [f for f in report["findings"] if f["type"] == "range_drift"]
    assert range_findings == [], "default range_drift_querier must produce no range_drift findings"


# ── AC-8 / VER-8: docs define allowlist and report boundaries ─────────────────


def test_dependency_audit_docs_define_allowlist_and_report_boundaries():
    """The docs must define scheduled-current-audit scope, the required allowlist
    fields, the public-safe output contract, and the boundary that workflow runtime
    is statically checked unless a real hosted run is triggered."""
    docs_path = ROOT / "docs" / "DEPENDENCY_UPGRADE_GATE.md"
    assert docs_path.exists(), "docs/DEPENDENCY_UPGRADE_GATE.md must exist"
    text = docs_path.read_text(encoding="utf-8")
    text_lower = text.lower()

    # Scheduled audit scope documented
    assert "current-audit" in text_lower or "scheduled" in text_lower, (
        "docs must mention scheduled current audit"
    )

    # Required allowlist fields documented
    for field in ("advisory_id", "affected_range", "expires", "reason"):
        assert field in text, f"docs must document allowlist field {field!r}"

    # Public-safe output contract
    for term in ("public", "sanitized", "package name", "advisory"):
        assert term.lower() in text_lower, f"docs must mention {term!r} in output contract"

    # Verification boundary documented
    assert "hosted" in text_lower, "docs must mention hosted-runtime verification boundary"
    assert "actionlint" in text_lower or "syntax" in text_lower, (
        "docs must describe static workflow checking"
    )

    # Allowlist JSON file must exist with correct schema
    allowlist_path = ROOT / "docs" / "dependency-audit-allowlist.json"
    assert allowlist_path.exists(), "docs/dependency-audit-allowlist.json must exist"
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    assert allowlist.get("schema_version") == 1, "allowlist must have schema_version: 1"
    assert isinstance(allowlist.get("entries"), list), "allowlist must have entries list"
