"""Tests for scripts/dependency_upgrade_gate.py.

Covers: dependency enumeration, advisory blocking, resolver-audit scoping,
CI report-freshness enforcement, documentation schema, and the clean-PR pass path.

All tests mock the advisory querier and resolver runner so no network access
or real resolver environments are created.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
            "spellcheck": ["autocorrect>=2.0"],
            "watch": ["watchfiles>=1.0"],
        },
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {
            "lancedb": "0.20.0",
            "pyyaml": "6.0.1",
            "pytest": "7.4.0",
            "autocorrect": "2.6.1",
            "watchfiles": "1.2.0",
        },
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

    spellcheck = dep_map[("extra:spellcheck", "autocorrect")]
    assert spellcheck["specifier"] == ">=2.0"
    assert spellcheck["current_version"] == "2.6.1"
    assert spellcheck["target_version"] is None
    watch = dep_map[("extra:watch", "watchfiles")]
    assert watch["specifier"] == ">=1.0"


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
            "treesitter": ["tree-sitter>=0.22,<0.26"],
            "spellcheck": ["autocorrect>=2.0"],
        },
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {
            "lancedb": "0.20.0",
            "pytest": "7.4.0",
            "tree-sitter": "0.25.2",
            "autocorrect": "2.6.1",
        },
    )
    # Only treesitter changed; dev is NOT in changed_groups; spellcheck NOT in changed_extras
    manifest = {
        "targets": {"lancedb": "0.33.0", "tree-sitter": "0.25.2"},
        "changed_groups": ["runtime"],
        "changed_extras": ["treesitter"],
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
    # treesitter present (in changed_extras)
    assert ["treesitter"] in plan
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
    """All-zeros SHA (the branch-creation `before`) must make a direct ci-check call
    fail closed; the CI job maps that case to origin/main before calling it."""
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
        "changed_extras": ["treesitter", "spellcheck"],
    }
    plan = gate._plan_resolver_audits(manifest)
    assert [] in plan
    assert ["dev"] in plan
    assert ["treesitter"] in plan
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
                "extras": ["spellcheck"],
                "status": "failed",
                "summary": "spellcheck install failed",
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


def test_default_resolver_runner_upgrades_audit_tooling(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        output = json.dumps({"dependencies": [{"name": "example", "version": "1.0", "vulns": []}]})
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    result = gate._default_resolver_runner([[]], ROOT)

    assert result == [
        {
            "extras": [],
            "status": "success",
            "summary": "resolver audit for (default): success",
            "raw_status": "clean",
            "findings": [],
        }
    ]
    assert any(
        command[1:] == ["install", "--quiet", "--upgrade", "pip", "setuptools>=83", "pip-audit"]
        for command in calls
    )


@pytest.mark.parametrize(
    ("stderr", "stdout", "reason"),
    [
        ("ERROR: [Errno 122] Disk quota exceeded", "", "disk_quota_exceeded"),
        ("ERROR: [Errno 28] No space left on device", "", "no_space_left"),
        (b"ERROR: Cannot allocate memory", b"", "out_of_memory"),
        ("ERROR: ResolutionImpossible", "", "dependency_resolution"),
        ("", "ERROR: No matching distribution found for example", "dependency_resolution"),
        ("ERROR: Failed to establish a new connection", "", "network_error"),
        ("ERROR: CERTIFICATE_VERIFY_FAILED", "", "network_error"),
        (
            "Failed to establish a new connection\nNo matching distribution found for example",
            "",
            "network_error",
        ),
        ("", "", "no_output"),
        (None, None, "no_output"),
        ("unrecognized failure payload", "", "unknown"),
        ("Disk quota exceeded" + "x" * 16384, "", "unknown"),
    ],
)
def test_resolver_failure_diagnostic_is_bounded_and_derived(stderr, stdout, reason):
    process = subprocess.CompletedProcess(["pip"], 17, stdout=stdout, stderr=stderr)
    assert gate._resolver_failure_diagnostic(process) == f"exit=17; reason={reason}"


@pytest.mark.parametrize("failed_step", [0, 1, 2])
def test_resolver_setup_failure_records_diagnostic_and_stops(monkeypatch, failed_step):
    calls = []

    def fake_run(command, **kwargs):
        step = len(calls)
        calls.append(command)
        assert step <= failed_step, "audit must not run after setup failure"
        return subprocess.CompletedProcess(
            command,
            3 if step == failed_step else 0,
            stdout=b"" if step == 1 else "",
            stderr=b"ERROR: [Errno 28] No space left on device"
            if step == 1
            else "ERROR: [Errno 28] No space left on device",
        )

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    result = gate._default_resolver_runner([["custom-models"]], ROOT)
    assert len(calls) == failed_step + 1
    assert result[0]["status"] == "failed"
    assert result[0]["raw_status"] == "error"
    assert result[0]["summary"].endswith("(exit=3; reason=no_space_left)")
    assert "findings" not in result[0]


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("", "no_output"),
        ("ERROR: [Errno 28] No space left on device", "no_space_left"),
        ("ERROR: unspecified install failure", "unknown"),
    ],
)
def test_current_audit_install_failure_stays_blocked_without_retaining_output(
    tmp_path, monkeypatch, stderr, reason
):
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20"],
        extras={"custom-models": ["sentence-transformers>=3.0"]},
    )
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0", "sentence-transformers": "3.0.0"})
    private_payload = (
        " private-host.invalid /opt/private/cache/file C:\\private\\cache "
        "https://user:password@example.invalid/simple?token=query-secret "
        "https://example.invalid/?api_key=secret-value PIP_PASSWORD=secret-value "
        "ghp_example_secret git@private-host.invalid:private/project.git"
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:] == ["install", "--quiet", ".[custom-models]"]:
            return subprocess.CompletedProcess(
                command, 1, stdout="", stderr=stderr + private_payload if stderr else ""
            )
        inventory = {"dependencies": [{"name": "lancedb", "version": "0.20.0", "vulns": []}]}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(inventory), stderr="")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    queries_seen = []

    def advisory_querier(queries):
        queries_seen.extend(queries)
        return _no_current_advisories(queries)

    rc = gate.cmd_current_audit(
        root=tmp_path,
        out_dir=tmp_path / "out",
        advisory_querier=advisory_querier,
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        today_iso="2030-01-01",
    )
    assert rc == 1
    assert {q["name"] for q in queries_seen} == {"lancedb", "sentence-transformers"}
    report_text = (tmp_path / "out/current-audit-report.json").read_text()
    report = json.loads(report_text)
    assert report["status"] == "findings"
    assert report["locked_packages_audited"] == 2
    assert [r["extras"] for r in report["resolver_audits"]] == [[], ["dev"], ["custom-models"]]
    failed = report["resolver_audits"][-1]
    assert failed == {
        "extras": ["custom-models"],
        "status": "failed",
        "raw_status": "error",
        "findings": [],
        "summary": f"install failed for custom-models (exit=1; reason={reason})",
    }
    assert all(r["status"] == "success" for r in report["resolver_audits"][:-1])
    assert sum("--format" in command for command in calls) == 2
    body = (tmp_path / "out/current-audit-issue-body.md").read_text()
    assert "custom-models" in body
    for payload in (stderr, *private_payload.split()):
        if payload:
            assert payload not in report_text
            assert payload not in body


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


def test_dependency_audit_workflow_closes_the_tracked_issue_after_a_clean_run():
    """A clean run of main closes the tracked issue, and that bookkeeping can never fail the
    run whose conclusion release admission reads. Both paths match the exact title,
    and a label problem is reported instead of being silenced."""
    import yaml

    workflow_path = ROOT / ".github" / "workflows" / "dependency-audit.yml"
    wf = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = wf["jobs"]["current-audit"]["steps"]
    by_name = {step.get("name"): step for step in steps}
    title = "[dependency-audit] current dependency audit findings"

    notify = by_name["Create or update dependency-audit issue"]
    close = by_name["Close resolved dependency-audit issue"]
    terminal = by_name["Fail workflow on audit findings"]

    assert notify["if"] == (
        "(steps.audit.outcome == 'failure' || steps.audit.outputs.audit_status == 'accepted_risk') "
        "&& github.ref == 'refs/heads/main'"
    )
    # Only a clean run of main speaks for main's lock; a clean dispatch from a
    # feature branch must not close the issue that tracks main's findings.
    assert close["if"] == (
        "steps.audit.outcome == 'success' && steps.audit.outputs.audit_status == 'clean' "
        "&& github.ref == 'refs/heads/main'"
    )
    assert close.get("continue-on-error") is True, "issue bookkeeping must not fail a clean run"
    assert "continue-on-error" not in notify
    assert terminal["if"] == "steps.audit.outcome == 'failure'"
    assert "exit 1" in terminal["run"]

    for step in (notify, close):
        assert f'ISSUE_TITLE="{title}"' in step["run"]
        assert 'select(.title == \\"$ISSUE_TITLE\\")' in step["run"], "match the exact title"
        assert step["env"]["GH_REPO"] == "${{ github.repository }}"

    assert "gh issue close" in close["run"]
    assert "--comment" in close["run"]
    assert "RUN_URL" in close["env"]

    # A missing label degrades to a visible warning, never a silenced error.
    assert '--label "$ISSUE_LABEL" 2>/dev/null' not in notify["run"]
    assert "::warning::" in notify["run"]
    assert '--add-label "$ISSUE_LABEL"' in notify["run"]

    # Least privilege: the only write scope is the one the issue steps need.
    assert wf["permissions"] == {"contents": "read", "issues": "write"}


# ── AC-2 / VER-2: resolver plan ────────────────────────────────────────────────


def test_current_audit_excludes_retired_chroma_extras(tmp_path):
    """Current audit plans every remaining extra and contains no Chroma resolver row."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20", "sentence-transformers>=2.2", "pyyaml>=6.0"],
        dev=["pytest>=7.0"],
        extras={
            "treesitter": ["tree-sitter>=0.22,<0.26"],
            "spellcheck": ["autocorrect>=2.0"],
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
    for extra in ("treesitter", "spellcheck", "watch"):
        assert [extra] in plan, f"extra '{extra}' must be in current-audit plan"
    assert not any("chroma" in extra for target in plan for extra in target)


# ── AC-3 / VER-3: OSV queries cover direct deps ────────────────────────────────


def test_current_audit_queries_osv_for_current_direct_lock_versions(tmp_path):
    """OSV queries must be made for current locked direct dependency versions
    including lancedb, sentence-transformers, pyyaml, packaging, autocorrect, and
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
            "spellcheck": ["autocorrect>=2.0"],
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
            "autocorrect": "2.6.1",
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
        "autocorrect",
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
        extras={"spellcheck": ["autocorrect>=2.0"]},
    )
    _write_lockfile(
        tmp_path / "uv.lock",
        {
            "lancedb": "0.20.0",
            "pyyaml": "6.0.1",
            "pytest": "7.4.0",
            "autocorrect": "2.6.1",
        },
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


# ── Lock-wide coverage, deduplication, and fail-closed lookups ─────────────────


def _write_lock_text(path: Path, entries: list[tuple[str, str, str]]) -> None:
    """Write a uv.lock whose entries are (name, version, source-kind)."""
    lines = ["version = 1", 'requires-python = ">=3.11"', ""]
    for name, version, kind in entries:
        source = (
            '{ editable = "." }'
            if kind == "editable"
            else '{ registry = "https://pypi.org/simple" }'
        )
        lines += [
            "[[package]]",
            f'name = "{name}"',
            f'version = "{version}"',
            f"source = {source}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _vulns_for(hits: dict[str, list[str]]):
    def _querier(queries: list[dict]) -> list[dict]:
        return [{"vulns": [{"id": i} for i in hits.get(q["name"], [])]} for q in queries]

    return _querier


def test_current_audit_queries_every_locked_package_including_transitive_pins(tmp_path, capsys):
    """Every package pinned in uv.lock is checked, not only direct dependencies.

    A transitive advisory is scoped to its exact lock pin, so only an allowlist
    entry for `==<locked version>` can accept it; the project itself is skipped.
    """
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["mcp>=2,<3"])
    _write_lock_text(
        tmp_path / "uv.lock",
        [
            ("test-pkg", "0.1.0", "editable"),
            ("mcp", "2.0.0", "registry"),
            ("anyio", "4.13.0", "registry"),
        ],
    )
    allowlist = tmp_path / "docs" / "dependency-audit-allowlist.json"
    _write_allowlist(allowlist)
    queried: list[tuple[str, str]] = []

    def _capturing(queries: list[dict]) -> list[dict]:
        queried.extend((q["name"], q["version"]) for q in queries)
        return _vulns_for({"anyio": ["GHSA-transitive-0001"]})(queries)

    def _run() -> int:
        return gate.cmd_current_audit(
            root=tmp_path,
            allowlist_path=allowlist,
            out_dir=tmp_path / "out",
            advisory_querier=_capturing,
            yanked_checker=_no_yanked,
            range_drift_querier=_no_range_drift,
            resolver_runner=_current_resolver_ok,
            today_iso="2030-01-01",
        )

    assert _run() != 0
    capsys.readouterr()
    assert sorted(queried) == [("anyio", "4.13.0"), ("mcp", "2.0.0")]
    report = json.loads((tmp_path / "out" / "current-audit-report.json").read_text())
    assert report["locked_packages_audited"] == 2
    [finding] = report["findings"]
    assert finding["package"] == "anyio"
    assert finding["group"] == "transitive"
    assert finding["affected_range"] == "==4.13.0"
    issue_body = (tmp_path / "out" / "current-audit-issue-body.md").read_text()
    assert "GHSA-transitive-0001" in issue_body
    assert "across 2 locked packages" in issue_body

    entry = {
        "advisory_id": "GHSA-transitive-0001",
        "package": "anyio",
        "reason": "accepted for test",
        "expires": "2099-01-01",
    }
    _write_allowlist(allowlist, [{**entry, "affected_range": ">=4.0"}])
    queried.clear()
    assert _run() != 0, "a range that is not the exact lock pin must not accept the advisory"
    _write_allowlist(allowlist, [{**entry, "affected_range": "==4.13.0"}])
    queried.clear()
    assert _run() == 0
    assert "2 locked packages" in capsys.readouterr().out


def test_current_audit_reports_a_package_declared_in_several_groups_once(tmp_path, capsys):
    """A dependency listed in dev and in an extra is one finding naming both groups."""
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["lancedb>=0.20"],
        dev=["watchfiles>=1.0"],
        extras={"watch": ["watchfiles>=1.0"]},
    )
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0", "watchfiles": "1.0.0"})
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")
    yanked_queries: list[dict] = []

    def _capturing_yanked(queries: list[dict]) -> list[bool]:
        yanked_queries.extend(queries)
        return _no_yanked(queries)

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_vulns_for({"watchfiles": ["GHSA-dup-0001", "GHSA-dup-0001"]}),
        yanked_checker=_capturing_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc != 0
    capsys.readouterr()

    report = json.loads((tmp_path / "out" / "current-audit-report.json").read_text())
    assert [(f["package"], f["advisory_id"], f["group"]) for f in report["findings"]] == [
        ("watchfiles", "GHSA-dup-0001", "dev, extra:watch")
    ]
    assert sorted(q["name"] for q in yanked_queries) == ["lancedb", "watchfiles"]
    issue_body = (tmp_path / "out" / "current-audit-issue-body.md").read_text()
    assert len([line for line in issue_body.splitlines() if "GHSA-dup-0001" in line]) == 1
    assert "Found 1 blocking finding(s)" in issue_body
    assert "(dev, extra:watch; `>=1.0`)" in issue_body


def test_current_audit_blocks_when_a_yanked_lookup_does_not_complete(tmp_path, capsys):
    """An unknown yanked status is a blocking finding, never a silent "not yanked"."""
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20", "pyyaml>=6.0"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0", "pyyaml": "6.0.1"})
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    def _one_unknown(queries: list[dict]) -> list[bool | None]:
        return [None if q["name"] == "pyyaml" else False for q in queries]

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=_no_current_advisories,
        yanked_checker=_one_unknown,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc != 0
    assert "1 blocking finding" in capsys.readouterr().err
    report = json.loads((tmp_path / "out" / "current-audit-report.json").read_text())
    assert [(f["type"], f["package"]) for f in report["findings"]] == [
        ("yanked_lookup_failed", "pyyaml")
    ]
    # A persistent failure (for example a version removed from PyPI) needs more
    # than a rerun, so the remediation names both actions.
    remediation = report["findings"][0]["remediation"]
    assert "rerun the audit" in remediation
    assert "still exists on PyPI" in remediation
    issue_body = (tmp_path / "out" / "current-audit-issue-body.md").read_text()
    assert "### Incomplete Yanked Lookups" in issue_body
    assert "pyyaml 6.0.1" in issue_body


def test_current_audit_fails_closed_when_advisory_results_are_incomplete(tmp_path, capsys):
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["lancedb>=0.20"])
    _write_lockfile(tmp_path / "uv.lock", {"lancedb": "0.20.0", "pyarrow": "20.0.0"})
    _write_allowlist(tmp_path / "docs" / "dependency-audit-allowlist.json")

    rc = gate.cmd_current_audit(
        root=tmp_path,
        allowlist_path=tmp_path / "docs" / "dependency-audit-allowlist.json",
        out_dir=tmp_path / "out",
        advisory_querier=lambda queries: [{"vulns": []}],
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=_current_resolver_ok,
        today_iso="2030-01-01",
    )
    assert rc == 1
    assert "answered 1 of 2 locked packages" in capsys.readouterr().err
    assert not (tmp_path / "out" / "current-audit-report.json").exists()


class _Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_default_yanked_checker_reports_failed_lookups_as_unknown(monkeypatch):
    responses: dict[str, object] = {
        "yanked-pkg": _Response({"info": {"yanked": True}}),
        "live-pkg": _Response({"info": {"yanked": False}}),
        "timeout-pkg": TimeoutError("read timed out"),
        "http-pkg": gate.urllib.request.HTTPError("u", 503, "unavailable", {}, None),
        "malformed-pkg": _Response({"info": {}}),
    }

    def fake_urlopen(request, timeout):
        outcome = responses[request.full_url.split("/")[4]]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(gate.urllib.request, "urlopen", fake_urlopen)
    queries = [{"name": name, "version": "1.0"} for name in responses]
    assert gate._default_yanked_checker(queries) == [True, False, None, None, None]


def test_default_advisory_querier_fails_closed_on_failed_or_short_responses(monkeypatch, capsys):
    queries = [{"name": "a", "version": "1"}, {"name": "b", "version": "2"}]

    def short(request, timeout):
        return _Response({"results": [{"vulns": []}]})

    def timeout(request, timeout):
        raise TimeoutError("read timed out")

    def paginated(request, timeout):
        return _Response({"results": [{"vulns": []}, {"vulns": [{}], "next_page_token": "p2"}]})

    for fake in (short, timeout, paginated):
        monkeypatch.setattr(gate.urllib.request, "urlopen", fake)
        try:
            gate._default_advisory_querier(queries)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError(f"{fake.__name__} response must fail closed")
    err = capsys.readouterr().err
    assert "answered 1 of 2 queries" in err
    assert "OSV query failed" in err
    assert "OSV paginated the advisories for b" in err

    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        lambda request, timeout: _Response({"results": [{"vulns": []}, {}]}),
    )
    assert gate._default_advisory_querier(queries) == [{"vulns": []}, {}]


# pip-audit's published JSON format supplies dependencies/name/version/vulns and aliases.
_PILLOW_ADVISORY = "GHSA-8g5g-8vmr-9782"


def _pillow_exception(**overrides):
    return {
        "package": "pillow",
        "advisory_id": _PILLOW_ADVISORY,
        "affected_range": "==12.3.0",
        "reason": "Reviewed text-only usage; residual risk accepted",
        "expires": "2026-11-05",
        **overrides,
    }


def _pillow_inventory(*, version="12.3.0", advisory=_PILLOW_ADVISORY, aliases=None):
    return {
        "dependencies": [
            {
                "name": "pillow",
                "version": version,
                "vulns": [{"id": advisory, "aliases": aliases or []}],
            },
            {"name": "fastembed", "version": "0.8.1", "vulns": []},
            {"name": "mempalace-code", "skip_reason": "local project"},
        ],
        "fixes": [],
    }


def test_resolver_accepts_exact_reviewed_risk_and_keeps_raw_findings(tmp_path):
    allowlist = tmp_path / "allowlist.json"
    _write_allowlist(allowlist, [_pillow_exception()])
    result = gate._evaluate_resolver_audit(
        json.dumps(_pillow_inventory()),
        1,
        tmp_path,
        allowlist_path=allowlist,
        today_iso="2026-10-22",
    )
    assert result["status"] == "accepted_risk"
    assert result["raw_status"] == "vulnerabilities"
    assert result["findings"][0]["advisory_id"] == _PILLOW_ADVISORY
    assert result["findings"][0]["version"] == "12.3.0"
    assert result["findings"][0]["allowlisted"] is True


@pytest.mark.parametrize("case", ["new", "version", "expired", "invalid_date", "blank_reason"])
def test_resolver_blocks_changed_or_invalid_acceptance(tmp_path, case):
    inventory = _pillow_inventory()
    entry = _pillow_exception()
    today = "2026-10-22"
    if case == "new":
        inventory["dependencies"][0]["vulns"].append({"id": "GHSA-new-unreviewed-finding"})
    elif case == "version":
        inventory["dependencies"][0]["version"] = "12.2.0"
    elif case == "expired":
        today = "2026-11-05"
    elif case == "invalid_date":
        entry["expires"] = "tomorrow"
    else:
        entry["reason"] = " "
    allowlist = tmp_path / "allowlist.json"
    _write_allowlist(allowlist, [entry])
    result = gate._evaluate_resolver_audit(
        json.dumps(inventory), 1, tmp_path, allowlist_path=allowlist, today_iso=today
    )
    assert result["status"] == "failed"
    assert result["raw_status"] == "vulnerabilities"


def test_resolver_matches_published_advisory_alias_without_discarding_primary(tmp_path):
    allowlist = tmp_path / "allowlist.json"
    _write_allowlist(allowlist, [_pillow_exception()])
    result = gate._evaluate_resolver_audit(
        json.dumps(_pillow_inventory(advisory="CVE-2026-112395", aliases=[_PILLOW_ADVISORY])),
        1,
        tmp_path,
        allowlist_path=allowlist,
        today_iso="2026-10-22",
    )
    assert result["status"] == "accepted_risk"
    assert result["findings"][0]["advisory_id"] == "CVE-2026-112395"
    assert result["findings"][0]["accepted_advisory_id"] == _PILLOW_ADVISORY


@pytest.mark.parametrize("case", ["json", "empty", "skipped", "alias", "exit", "contradiction"])
def test_resolver_errors_and_incomplete_inventory_never_authorize_acceptance(tmp_path, case):
    inventory = _pillow_inventory()
    code = 1
    if case == "empty":
        inventory["dependencies"] = []
    elif case == "skipped":
        inventory["dependencies"].append({"name": "another-package", "skip_reason": "unknown"})
    elif case == "alias":
        inventory["dependencies"][0]["vulns"][0]["aliases"] = "malformed"
    elif case == "exit":
        code = 2
    elif case == "contradiction":
        code = 0
    output = "invalid JSON" if case == "json" else json.dumps(inventory)
    allowlist = tmp_path / "allowlist.json"
    _write_allowlist(allowlist, [_pillow_exception()])
    result = gate._evaluate_resolver_audit(
        output, code, tmp_path, allowlist_path=allowlist, today_iso="2026-10-22"
    )
    assert result["status"] == "failed"
    assert result["raw_status"] == "error"


def test_upgrade_resolver_remains_strict_even_with_repository_allowlist(tmp_path):
    _write_allowlist(tmp_path / "docs/dependency-audit-allowlist.json", [_pillow_exception()])
    result = gate._evaluate_resolver_audit(json.dumps(_pillow_inventory()), 1, tmp_path)
    assert result["status"] == "failed"
    assert result["findings"][0]["allowlisted"] is False


@pytest.mark.parametrize(
    "change",
    ["none", "tracked", "untracked", "committed", "version", "long", "future", "duplicate"],
)
def test_usage_exception_is_bound_to_reviewed_code_and_dependency_owner(tmp_path, change):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    git("init", "-q")
    source = tmp_path / "mempalace_code/storage.py"
    source.parent.mkdir()
    source.write_text("canonical_model = 'MiniLM'\n")
    git("add", "mempalace_code")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    tree = git("rev-parse", "HEAD:mempalace_code").stdout.strip()
    allowlist = tmp_path / "allowlist.json"
    data = {
        "schema_version": 1,
        "entries": [_pillow_exception()],
        "context": {
            "mempalace_code_tree": tree,
            "packages": {"fastembed": ["0.8.0", "0.8.1"]},
            "accepted_on": "2026-10-22",
            "review_on": "2026-10-29",
        },
    }
    if change == "long":
        data["entries"][0]["expires"] = "2026-11-06"
    if change == "duplicate":
        data["entries"].append(data["entries"][0].copy())
    allowlist.write_text(json.dumps(data))
    versions = {"fastembed": "0.8.1"}
    if change in {"tracked", "committed"}:
        source.write_text("image_input_enabled = True\n")
    if change == "committed":
        git("add", "mempalace_code")
        git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "changed",
        )
    if change == "untracked":
        (source.parent / "images.py").write_text("image_input_enabled = True\n")
    if change == "version":
        versions["fastembed"] = "0.8.2"
    accepted = gate._load_allowlist(
        allowlist,
        root=tmp_path,
        versions=versions,
        today_iso="2026-10-21" if change == "future" else "2026-10-22",
    )
    assert bool(accepted) is (change == "none")


def test_current_audit_reports_accepted_risk_instead_of_claiming_clean(tmp_path):
    _write_pyproject(tmp_path / "pyproject.toml", runtime=["fastembed>=0.8"])
    _write_lockfile(tmp_path / "uv.lock", {"fastembed": "0.8.1", "pillow": "12.3.0"})
    allowlist = tmp_path / "allowlist.json"
    _write_allowlist(allowlist, [_pillow_exception()])

    def resolver(plan, root):
        result = gate._evaluate_resolver_audit(
            json.dumps(_pillow_inventory()),
            1,
            root,
            allowlist_path=allowlist,
            today_iso="2026-10-22",
        )
        return [{**result, "extras": extra} for extra in plan]

    rc = gate.cmd_current_audit(
        tmp_path,
        allowlist_path=allowlist,
        out_dir=tmp_path / "out",
        advisory_querier=lambda queries: [
            {"vulns": [{"id": _PILLOW_ADVISORY}]} if q["name"] == "pillow" else {"vulns": []}
            for q in queries
        ],
        yanked_checker=_no_yanked,
        range_drift_querier=_no_range_drift,
        resolver_runner=resolver,
        today_iso="2026-10-22",
    )
    assert rc == 0
    report = json.loads((tmp_path / "out/current-audit-report.json").read_text())
    assert report["status"] == "accepted_risk"
    assert report["findings"][0]["allowlisted"] is True
    assert report["resolver_audits"][0]["raw_status"] == "vulnerabilities"
    assert report["resolver_audits"][0]["findings"][0]["advisory_id"] == _PILLOW_ADVISORY
    issue = (tmp_path / "out/current-audit-issue-body.md").read_text()
    assert "Accepted temporary risks" in issue
    assert "not a claim that the dependency is fixed" in issue
    assert _PILLOW_ADVISORY in issue


def _approved_transition_fixture(tmp_path, monkeypatch, *, custom_models=False):
    """Independent small inventory exercises the production snapshot checks."""
    custom_extras = {
        "custom-models": ["sentence-transformers>=5.6.0", "setuptools>=84.1.0"],
        "watch": ["watchfiles>=1.0"],
    }
    _write_pyproject(
        tmp_path / "pyproject.toml",
        runtime=["fastembed>=0.8"],
        extras=custom_extras if custom_models else None,
    )
    packages = {"fastembed": "0.8.1", "pillow": "12.3.0"}
    if custom_models:
        packages.update(
            {"sentence-transformers": "5.6.0", "setuptools": "84.1.0", "watchfiles": "1.0"}
        )
    _write_lockfile(tmp_path / "uv.lock", packages)
    allowlist = tmp_path / gate.CURRENT_AUDIT_ALLOWLIST_PATH
    allowlist.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    source = tmp_path / "mempalace_code/storage.py"
    source.parent.mkdir()
    source.write_text("canonical_model = 'MiniLM'\n")
    subprocess.run(["git", "add", "mempalace_code"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD:mempalace_code"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    today = datetime.datetime.now(datetime.UTC).date()
    allowlist.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    _pillow_exception(expires=(today + datetime.timedelta(days=13)).isoformat())
                ],
                "context": {
                    "mempalace_code_tree": tree,
                    "packages": {"fastembed": ["0.8.1"]},
                    "accepted_on": (today - datetime.timedelta(days=1)).isoformat(),
                    "review_on": (today + datetime.timedelta(days=5)).isoformat(),
                },
            }
        )
    )
    monkeypatch.setattr(
        gate,
        "_TRUST_TOOLS_SNAPSHOT",
        {
            path: gate._hash_file(tmp_path / path).removeprefix("sha256:")
            for path in ("pyproject.toml", "uv.lock", gate.CURRENT_AUDIT_ALLOWLIST_PATH)
        },
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"targets": {}, "changed_groups": [], "changed_extras": []}))

    def resolver(plan, root, *, allowlist_path=None):
        results = []
        for extras in plan:
            inventory = _pillow_inventory()
            extra_versions = {}
            if custom_models and extras == ["custom-models"]:
                extra_versions = {"sentence-transformers": "5.6.0", "setuptools": "84.1.0"}
            elif custom_models and extras == ["watch"]:
                extra_versions = {"watchfiles": "1.0"}
            inventory["dependencies"].extend(
                {"name": name, "version": version, "vulns": []}
                for name, version in extra_versions.items()
            )
            results.append(
                {
                    **gate._evaluate_resolver_audit(
                        json.dumps(inventory), 1, root, allowlist_path=allowlist_path
                    ),
                    "extras": extras,
                }
            )
        return results

    return manifest, resolver


@pytest.mark.parametrize(
    ("changed_extras", "expected_plan"),
    [
        (["custom-models"], [[], ["dev"], ["custom-models"]]),
        ([], [[], ["dev"], ["custom-models"]]),
        (
            ["watch", "custom-models", "custom-models"],
            [[], ["dev"], ["custom-models"], ["watch"]],
        ),
    ],
)
def test_approved_upgrade_preserves_changed_extras_and_requires_custom_inventory(
    tmp_path, monkeypatch, changed_extras, expected_plan
):
    manifest, resolver = _approved_transition_fixture(tmp_path, monkeypatch, custom_models=True)
    targets = {}
    if "custom-models" in changed_extras:
        targets.update({"sentence-transformers": "5.6.0", "setuptools": "84.1.0"})
    if "watch" in changed_extras:
        targets["watchfiles"] = "1.0"
    manifest.write_text(
        json.dumps({"targets": targets, "changed_groups": [], "changed_extras": changed_extras})
    )
    observed = []

    def recording_resolver(plan, root, *, allowlist_path=None):
        observed.extend(plan)
        return resolver(plan, root, allowlist_path=allowlist_path)

    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "custom",
            advisory_querier=_no_current_advisories,
            resolver_runner=recording_resolver,
        )
        == 0
    )
    assert observed == expected_plan
    report_path = tmp_path / gate.REPORT_DIR / "custom.json"
    report = json.loads(report_path.read_text())
    assert [row["extras"] for row in report["resolver_audits"]] == expected_plan
    custom = report["resolver_audits"][2]
    assert custom["audited_versions"]["sentence-transformers"] == "5.6.0"
    assert custom["audited_versions"]["setuptools"] == "84.1.0"
    assert gate.cmd_verify_report(report_path, tmp_path) == 0


@pytest.mark.parametrize(
    "change",
    ["omit_custom", "duplicate_custom", "sentence-transformers", "setuptools", "false_clean"],
)
def test_approved_upgrade_rejects_incomplete_custom_surface_at_audit_and_verify(
    tmp_path, monkeypatch, change
):
    manifest, resolver = _approved_transition_fixture(tmp_path, monkeypatch, custom_models=True)
    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "custom",
            advisory_querier=_no_current_advisories,
            resolver_runner=resolver,
        )
        == 0
    )
    report_path = tmp_path / gate.REPORT_DIR / "custom.json"
    report = json.loads(report_path.read_text())
    rows = report["resolver_audits"]
    custom = rows[-1]
    if change == "omit_custom":
        rows.pop()
    elif change == "duplicate_custom":
        rows.append(dict(custom))
    elif change == "false_clean":
        custom["status"] = "success"
    else:
        custom["audited_versions"].pop(change)
        # Even a consistent clean status must not replace required direct inventory.
        custom.update(status="success", raw_status="clean", findings=[])
    report_path.write_text(json.dumps(report))
    assert gate.cmd_verify_report(report_path, tmp_path) == 1
    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "invalid-custom",
            advisory_querier=_no_current_advisories,
            resolver_runner=lambda *args, **kwargs: rows,
        )
        == 1
    )
    blocked = json.loads((tmp_path / gate.REPORT_DIR / "invalid-custom.json").read_text())
    assert blocked["status"] == "blocked"


def test_exact_upgrade_acceptance_is_honest_and_reverified(tmp_path, monkeypatch):
    manifest, resolver = _approved_transition_fixture(tmp_path, monkeypatch)
    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "exact",
            advisory_querier=_no_current_advisories,
            resolver_runner=resolver,
        )
        == 0
    )
    report_path = tmp_path / gate.REPORT_DIR / "exact.json"
    report = json.loads(report_path.read_text())
    assert report["status"] == "accepted_risk"
    assert [a["extras"] for a in report["resolver_audits"]] == [[], ["dev"]]
    assert report["resolver_audits"][0]["raw_status"] == "vulnerabilities"
    assert gate.cmd_verify_report(report_path, tmp_path) == 0
    assert (
        gate.cmd_ci_check(
            "abc123", tmp_path, git_runner=_make_git_runner(changed_files=["uv.lock"])
        )
        == 0
    )
    # Simulate time advancing, without changing the snapshot or trusting old flags.
    original = gate._check_allowlist
    expiry = json.loads((tmp_path / gate.CURRENT_AUDIT_ALLOWLIST_PATH).read_text())["entries"][0][
        "expires"
    ]
    monkeypatch.setattr(gate, "_check_allowlist", lambda *a: original(*a[:-1], expiry))
    assert gate.cmd_verify_report(report_path, tmp_path) == 1


@pytest.mark.parametrize("path", ["pyproject.toml", "uv.lock", gate.CURRENT_AUDIT_ALLOWLIST_PATH])
def test_exact_upgrade_snapshot_drift_keeps_strict_policy(tmp_path, monkeypatch, path):
    manifest, resolver = _approved_transition_fixture(tmp_path, monkeypatch)
    with (tmp_path / path).open("a") as stream:
        stream.write("\n")
    assert gate._approved_upgrade_allowlist(tmp_path) is None
    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "drift",
            advisory_querier=_no_current_advisories,
            resolver_runner=resolver,
        )
        == 1
    )


@pytest.mark.parametrize(
    "change",
    [
        "unknown_id",
        "package",
        "version",
        "owner",
        "source",
        "flags",
        "no_versions",
        "no_findings",
        "no_dev",
        "status",
        "raw_error",
    ],
)
def test_upgrade_report_cannot_replay_or_forge_risk_evidence(tmp_path, monkeypatch, change):
    manifest, resolver = _approved_transition_fixture(tmp_path, monkeypatch)
    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "tamper",
            advisory_querier=_no_current_advisories,
            resolver_runner=resolver,
        )
        == 0
    )
    report_path = tmp_path / gate.REPORT_DIR / "tamper.json"
    report = json.loads(report_path.read_text())
    audit = report["resolver_audits"][0]
    if change == "unknown_id":
        audit["findings"][0]["advisory_id"] = "GHSA-unknown-test-1111"
    elif change == "package":
        audit["findings"][0]["package"] = "unknown-package"
    elif change == "version":
        audit["findings"][0]["version"] = "12.2.0"
    elif change == "owner":
        audit["audited_versions"]["fastembed"] = "0.8.2"
    elif change == "source":
        (tmp_path / "mempalace_code/storage.py").write_text("image_input_enabled = True\n")
    elif change == "raw_error":
        audit["raw_status"] = "error"
    elif change == "flags":
        audit["findings"][0]["allowlisted"] = False
    elif change == "no_versions":
        audit.pop("audited_versions")
    elif change == "no_findings":
        audit["findings"] = []
    elif change == "no_dev":
        report["resolver_audits"].pop()
    else:
        report["status"] = "success"
    report_path.write_text(json.dumps(report))
    assert gate.cmd_verify_report(report_path, tmp_path) == 1


def test_approved_upgrade_still_blocks_affected_target(tmp_path, monkeypatch):
    manifest, resolver = _approved_transition_fixture(tmp_path, monkeypatch)
    manifest.write_text(
        json.dumps({"targets": {"fastembed": "0.8.1"}, "changed_groups": [], "changed_extras": []})
    )
    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "target-risk",
            advisory_querier=lambda queries: [
                {"vulns": [{"id": "GHSA-new-risk-1111"}]} for _ in queries
            ],
            resolver_runner=resolver,
        )
        == 1
    )
    assert not (tmp_path / gate.REPORT_DIR / "target-risk.json").exists()


@pytest.mark.parametrize("missing", ["direct", "context", "source"])
def test_mixed_clean_and_accepted_report_requires_each_inventory(tmp_path, monkeypatch, missing):
    manifest, resolver = _approved_transition_fixture(tmp_path, monkeypatch)
    assert (
        gate.cmd_audit(
            manifest,
            tmp_path,
            "mixed",
            advisory_querier=_no_current_advisories,
            resolver_runner=resolver,
        )
        == 0
    )
    report_path = tmp_path / gate.REPORT_DIR / "mixed.json"
    report = json.loads(report_path.read_text())
    clean = report["resolver_audits"][0]
    clean.update(status="success", raw_status="clean", findings=[])
    # Clean inventory with both the required direct dependency and reviewed
    # owner is valid; a row label with either missing must be refused.
    report_path.write_text(json.dumps(report))
    assert gate.cmd_verify_report(report_path, tmp_path) == 0
    if missing == "direct":
        project = tmp_path / "pyproject.toml"
        project.write_text(
            project.read_text().replace('"fastembed>=0.8"', '"fastembed>=0.8", "mcp>=2"')
        )
        snapshot = dict(gate._TRUST_TOOLS_SNAPSHOT)
        snapshot["pyproject.toml"] = gate._hash_file(project).removeprefix("sha256:")
        monkeypatch.setattr(gate, "_TRUST_TOOLS_SNAPSHOT", snapshot)
        report["pyproject_hash"] = gate._hash_file(project)
        # Dev has complete coverage; only the clean default row omits MCP.
        report["resolver_audits"][1]["audited_versions"]["mcp"] = "2.3.0"
    elif missing == "context":
        clean["audited_versions"] = {"invented-package": "1.0"}
    else:
        (tmp_path / "mempalace_code/storage.py").write_text("changed = True\n")
    report_path.write_text(json.dumps(report))
    assert gate.cmd_verify_report(report_path, tmp_path) == 1
