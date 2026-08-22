"""Focused tests for scripts/gitleaks_scan.py."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
GATE_ACTION_DIR = Path(".github/actions/gitleaks-gate")
GITLEAKS_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/publish.yml",
    ".github/workflows/gitleaks-history.yml",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


gs = _load_module("gitleaks_scan", ROOT / "scripts" / "gitleaks_scan.py")
ps = _load_module(
    "public_safety_scan_for_gitleaks_tests", ROOT / "scripts" / "public_safety_scan.py"
)
gi = _load_module("gate_inventory_for_gitleaks_tests", ROOT / "scripts" / "gate_inventory.py")

REAL_GITLEAKS = shutil.which("gitleaks")


def _baseline(path: Path) -> Path:
    baseline = path / "baseline.yml"
    baseline.write_text("version: 1\nentries: []\n", encoding="utf-8")
    return baseline


def _ok_commit_git(command, _root):
    if command[:2] == ["rev-parse", "--verify"]:
        return gs.RunResult(0, "commit-sha\n", "")
    raise AssertionError(f"unexpected git command: {command}")


def _complete_history_git(command, _root):
    """A non-shallow worktree with reachable history, without building a repo."""
    answers = {
        ("rev-parse", "--is-inside-work-tree"): "true\n",
        ("rev-parse", "--is-shallow-repository"): "false\n",
        ("rev-list", "--count", "--all"): "42\n",
    }
    try:
        return gs.RunResult(0, answers[tuple(command)], "")
    except KeyError:
        raise AssertionError(f"unexpected git command: {command}") from None


def _workflow_jobs(relative: str) -> dict[str, list[dict]]:
    document = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    return {name: (job.get("steps") or []) for name, job in document["jobs"].items()}


def _fake_report(command, findings) -> None:
    report_path = Path(command[command.index("--report-path") + 1])
    report_path.write_text(json.dumps(findings), encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=_GIT_ENV
    )
    return result.stdout.strip()


_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Gitleaks Test",
    "GIT_AUTHOR_EMAIL": "gitleaks-test@example.invalid",
    "GIT_COMMITTER_NAME": "Gitleaks Test",
    "GIT_COMMITTER_EMAIL": "gitleaks-test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _disposable_repo(path: Path) -> tuple[str, str]:
    """Create a two-commit repository and return its (base, head) commit SHAs."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--quiet", "--initial-branch=main")
    (path / "README.md").write_text("base revision\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "--quiet", "-m", "base")
    base = _git(path, "rev-parse", "HEAD")
    (path / "app.py").write_text("VALUE = 'ordinary literal'\n", encoding="utf-8")
    _git(path, "add", "app.py")
    _git(path, "commit", "--quiet", "-m", "head")
    return base, _git(path, "rev-parse", "HEAD")


def _stub_gitleaks(bin_dir: Path, findings: list[dict], exit_code: int) -> Path:
    """Install a stub `gitleaks` on PATH that writes ``findings`` to --report-path."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "gitleaks"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        "report = argv[argv.index('--report-path') + 1]\n"
        f"open(report, 'w').write(json.dumps({findings!r}))\n"
        "sys.stdout.write('stub gitleaks run\\n')\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def test_changed_range_scan_uses_exact_base_head_log_opts_and_fails_on_findings(
    tmp_path: Path, capsys
):
    base = "1111111111111111111111111111111111111111"
    head = "2222222222222222222222222222222222222222"
    planted = "gh" + "p_" + "A" * 36
    commands: list[list[str]] = []

    def runner(command, _root):
        commands.append(list(command))
        _fake_report(
            command,
            [
                {
                    "RuleID": "github-pat",
                    "File": "pkg/config.py",
                    "StartLine": 7,
                    "Secret": planted,
                    "Match": f"token={planted}",
                    "Fingerprint": "abc123:pkg/config.py:github-pat:7",
                }
            ],
        )
        return gs.RunResult(1, f"found {planted}", "")

    outcome = gs.run_changed_range(
        root=tmp_path,
        base_ref=base,
        head_ref=head,
        config_path=ROOT / ".gitleaks.toml",
        baseline_path=_baseline(tmp_path),
        artifact_dir=tmp_path / "artifacts",
        runner=runner,
        git_runner=_ok_commit_git,
    )

    captured = capsys.readouterr()
    assert outcome.returncode == 1
    assert outcome.findings == 1
    assert len(commands) == 1
    command = commands[0]
    assert f"--log-opts={base}..{head}" in command
    assert "--log-opts=--all" not in command
    assert "--redact=100" in command
    assert command[0:2] == ["gitleaks", "git"]
    assert planted not in captured.out
    assert (
        "github-pat pkg/config.py:7 fingerprint=abc123:pkg/config.py:github-pat:7" in captured.out
    )


def test_production_default_git_runner_resolves_real_commits(tmp_path: Path):
    """Exercise the shipped `_git` default, not an injected stub.

    Every scan mode reaches Git through the module-level default runner, so an
    argument-order regression there breaks all of them in production while
    stub-injected tests stay green.
    """
    repo = tmp_path / "repo"
    base, head = _disposable_repo(repo)

    gs.ensure_changed_range(repo, base, head)
    gs.ensure_full_history(repo)

    with pytest.raises(gs.GitleaksScanError, match="not a reachable commit"):
        gs.ensure_changed_range(repo, base, "0" * 39 + "f")


def test_main_changed_range_end_to_end_with_default_runners(tmp_path: Path, monkeypatch, capsys):
    """Drive main() with production defaults: real Git, real subprocess, stub binary."""
    repo = tmp_path / "repo"
    base, head = _disposable_repo(repo)
    planted = "AK" + "IA" + "E" * 16
    _stub_gitleaks(
        tmp_path / "bin",
        [
            {
                "RuleID": "aws-access-token",
                "File": "app.py",
                "StartLine": 1,
                "Secret": planted,
                "Match": f"key={planted}",
                "Fingerprint": f"{head}:app.py:aws-access-token:1",
            }
        ],
        exit_code=1,
    )
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    artifacts = tmp_path / "artifacts"

    rc = gs.main(
        [
            "--repo-root",
            str(repo),
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--baseline",
            str(_baseline(tmp_path)),
            "changed-range",
            "--base-ref",
            base,
            "--head-ref",
            head,
            "--artifact-dir",
            str(artifacts),
        ]
    )
    captured = capsys.readouterr()

    assert rc == 1
    assert "gitleaks-scan: FAIL (changed-range; 1 finding(s))" in captured.out
    assert planted not in captured.out
    assert planted not in captured.err
    summary = (artifacts / "changed-range.summary.txt").read_text(encoding="utf-8")
    assert f"fingerprint={head}:app.py:aws-access-token:1" in summary
    assert planted not in summary


def test_main_full_history_end_to_end_is_clean_when_the_scanner_reports_nothing(
    tmp_path: Path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    _disposable_repo(repo)
    _stub_gitleaks(tmp_path / "bin", [], exit_code=0)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")

    rc = gs.main(
        [
            "--repo-root",
            str(repo),
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--baseline",
            str(_baseline(tmp_path)),
            "full-history",
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ]
    )

    assert rc == 0
    assert "gitleaks-scan: OK (full-history; 0 findings)" in capsys.readouterr().out


def test_missing_scanner_binary_is_a_bounded_error_without_a_traceback(
    tmp_path: Path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    base, head = _disposable_repo(repo)
    # Git stays reachable so the range validation still passes; only the scanner
    # is missing, which is the case a CI job with a broken install would hit.
    bin_dir = tmp_path / "git-only-bin"
    bin_dir.mkdir()
    git_path = shutil.which("git")
    assert git_path is not None
    (bin_dir / "git").symlink_to(git_path)
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = gs.main(
        [
            "--repo-root",
            str(repo),
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--baseline",
            str(_baseline(tmp_path)),
            "changed-range",
            "--base-ref",
            base,
            "--head-ref",
            head,
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ]
    )
    captured = capsys.readouterr()

    assert rc == 1
    assert "gitleaks-scan: FAIL - could not execute 'gitleaks'" in captured.err
    assert "Traceback" not in captured.err


def test_malformed_and_missing_baselines_are_bounded_errors_without_a_traceback(
    tmp_path: Path, capsys
):
    missing = tmp_path / "absent.yml"
    assert gs.baseline_validation_errors(missing) == [
        f"baseline metadata file is missing: {missing}"
    ]

    unparsable = tmp_path / "broken.yml"
    unparsable.write_text("entries: [\n  - fingerprint: 'unterminated\n", encoding="utf-8")
    assert any("not valid YAML" in error for error in gs.baseline_validation_errors(unparsable))

    not_a_mapping = tmp_path / "list.yml"
    not_a_mapping.write_text("- just\n- a list\n", encoding="utf-8")
    assert gs.baseline_validation_errors(not_a_mapping) == ["baseline metadata must be a mapping"]

    empty = tmp_path / "empty.yml"
    empty.write_text("\n", encoding="utf-8")
    assert gs.baseline_validation_errors(empty) == [f"baseline metadata file is empty: {empty}"]

    duplicated = tmp_path / "duplicated.yml"
    duplicated.write_text(
        "version: 1\nentries:\n"
        "  - fingerprint: abc:path:rule:1\n"
        "    rationale: reviewed\n"
        "    owner: release-owner\n"
        "    expires: 2027-01-01\n"
        "  - fingerprint: abc:path:rule:1\n"
        "    rationale: reviewed twice\n"
        "    owner: release-owner\n"
        "    expires: 2027-01-01\n",
        encoding="utf-8",
    )
    assert "entries[2].fingerprint duplicates 'abc:path:rule:1'" in gs.baseline_validation_errors(
        duplicated
    )

    # An absolute --baseline outside the repository root must still report cleanly.
    outside = tmp_path / "outside.yml"
    outside.write_text("version: 1\nentries: []\n", encoding="utf-8")
    rc = gs.main(["--repo-root", str(ROOT), "--baseline", str(outside), "validate-baseline"])
    assert rc == 0
    assert "gitleaks-baseline: OK" in capsys.readouterr().out

    rc = gs.main(["--repo-root", str(ROOT), "--baseline", str(unparsable), "validate-baseline"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "gitleaks-baseline: FAIL" in captured.err
    assert "Traceback" not in captured.err


def test_reviewed_baseline_fingerprints_reach_the_scanner_ignore_file(tmp_path: Path):
    """Suppression is per-fingerprint and passed explicitly on every scan.

    `--baseline-path` compares whole findings and ignores the fingerprint, so the
    fingerprint-keyed `--gitleaks-ignore-path` is the only mechanism that can
    express "this reviewed finding is allowed". It is written outside the scanned
    tree; it does *not* displace an in-tree `.gitleaksignore`, which Gitleaks
    loads as well — that surface is closed by the guard covered in
    `test_stray_gitleaksignore_in_the_scanned_tree_fails_closed_before_scanning`.
    """
    baseline = tmp_path / "baseline.yml"
    baseline.write_text(
        "version: 1\nentries:\n"
        "  - fingerprint: deadbeef:docs/NOTES.md:generic-api-key:9\n"
        "    rationale: public identifier, reviewed\n"
        "    owner: release-owner\n"
        "    review_condition: remove when the identifier changes\n",
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    def runner(command, _root):
        ignore_path = Path(command[command.index("--gitleaks-ignore-path") + 1])
        seen["ignore"] = ignore_path.read_text(encoding="utf-8")
        seen["outside_scanned_root"] = tmp_path not in ignore_path.parents
        _fake_report(command, [])
        return gs.RunResult(0, "", "")

    outcome = gs.run_changed_range(
        root=tmp_path,
        base_ref="1" * 40,
        head_ref="2" * 40,
        config_path=ROOT / ".gitleaks.toml",
        baseline_path=baseline,
        artifact_dir=tmp_path / "artifacts",
        runner=runner,
        git_runner=_ok_commit_git,
    )

    assert outcome.returncode == 0
    assert seen["ignore"] == "deadbeef:docs/NOTES.md:generic-api-key:9\n"
    assert "--baseline-path" not in outcome.command
    assert seen["outside_scanned_root"] is True


def test_stray_gitleaksignore_in_the_scanned_tree_fails_closed_before_scanning(
    tmp_path: Path, capsys
):
    """An in-tree `.gitleaksignore` is an ungoverned suppression, not an input.

    Gitleaks loads `<source>/.gitleaksignore` unconditionally, *in addition to*
    the `--gitleaks-ignore-path` this wrapper derives from reviewed metadata, so
    two lines in the worktree can silence a real finding while `validate-baseline`
    still reports OK. The scan must refuse to start rather than report a clean
    tree it did not really scan.
    """
    repo = tmp_path / "repo"
    _disposable_repo(repo)
    stray = repo / ".gitleaksignore"
    stray.write_text("deadbeef:app.py:github-pat:1\n", encoding="utf-8")

    def never_runs(command, _root):
        raise AssertionError(f"the scanner must not be invoked: {command}")

    with pytest.raises(gs.GitleaksScanError) as excinfo:
        gs.run_full_history(
            root=repo,
            config_path=ROOT / ".gitleaks.toml",
            baseline_path=_baseline(tmp_path),
            artifact_dir=tmp_path / "artifacts",
            runner=never_runs,
        )
    message = str(excinfo.value)
    assert ".gitleaksignore" in message
    assert "security/gitleaks-baseline.yml is the only governed suppression path" in message

    rc = gs.main(
        [
            "--repo-root",
            str(repo),
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--baseline",
            str(_baseline(tmp_path)),
            "full-history",
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert f"gitleaks-scan: FAIL - ungoverned .gitleaksignore in the scanned tree: {stray}" in (
        captured.err
    )
    assert "security/gitleaks-baseline.yml" in captured.err
    assert "Traceback" not in captured.err

    # The guard is about governance, not a blanket refusal: without the file the
    # same scan runs normally.
    stray.unlink()
    invocations: list[list[str]] = []

    def clean_runner(command, _root):
        invocations.append(list(command))
        _fake_report(command, [])
        return gs.RunResult(0, "", "")

    outcome = gs.run_full_history(
        root=repo,
        config_path=ROOT / ".gitleaks.toml",
        baseline_path=_baseline(tmp_path),
        artifact_dir=tmp_path / "artifacts",
        runner=clean_runner,
    )
    assert outcome.returncode == 0
    assert len(invocations) == 1


def test_scanner_failure_is_reported_as_failed_in_stdout_summary_and_sarif(tmp_path: Path, capsys):
    """A scan that never ran must not attest a clean tree.

    The exit code alone is not enough: all three workflows upload the summary and
    SARIF with `if: always()`, so "0 findings, OK" next to a red job would be a
    misleading clean attestation for whoever triages it, and for any downstream
    SARIF consumer.
    """

    def failing_runner(command, _root):
        _fake_report(command, [])
        return gs.RunResult(1, "", "FTL unable to load gitleaks config, err: no such file")

    outcome = gs.run_full_history(
        root=tmp_path,
        config_path=tmp_path / "does-not-exist.toml",
        baseline_path=_baseline(tmp_path),
        artifact_dir=tmp_path / "artifacts",
        runner=failing_runner,
        git_runner=_complete_history_git,
    )
    captured = capsys.readouterr()

    assert outcome.returncode == 1
    assert outcome.findings == 0
    headline = "gitleaks-scan: FAIL (full-history; scanner error, exit 1; 0 finding(s))"
    assert headline in captured.out
    assert "gitleaks-scan: OK" not in captured.out
    assert outcome.summary_path.read_text(encoding="utf-8").startswith(headline)
    sarif = json.loads(outcome.sarif_path.read_text(encoding="utf-8"))
    invocation = sarif["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False
    assert invocation["exitCode"] == 1
    assert invocation["exitCodeDescription"] == headline

    # A scan that really did run clean still reports OK, in every surface.
    def clean_runner(command, _root):
        _fake_report(command, [])
        return gs.RunResult(0, "", "")

    outcome = gs.run_full_history(
        root=tmp_path,
        config_path=ROOT / ".gitleaks.toml",
        baseline_path=_baseline(tmp_path),
        artifact_dir=tmp_path / "artifacts",
        runner=clean_runner,
        git_runner=_complete_history_git,
    )
    assert outcome.returncode == 0
    assert "gitleaks-scan: OK (full-history; 0 findings)" in capsys.readouterr().out
    sarif = json.loads(outcome.sarif_path.read_text(encoding="utf-8"))
    assert sarif["runs"][0]["invocations"][0]["executionSuccessful"] is True


def test_scanner_failure_without_findings_fails_closed(tmp_path: Path, capsys):
    def runner(command, _root):
        _fake_report(command, [])
        return gs.RunResult(2, "", "fatal: bad revision")

    outcome = gs.run_changed_range(
        root=tmp_path,
        base_ref="1" * 40,
        head_ref="2" * 40,
        config_path=ROOT / ".gitleaks.toml",
        baseline_path=_baseline(tmp_path),
        artifact_dir=tmp_path / "artifacts",
        runner=runner,
        git_runner=_ok_commit_git,
    )

    assert outcome.returncode == 1
    assert "fatal: bad revision" in capsys.readouterr().err


def test_full_history_modes_require_reachable_history_and_fetch_depth_zero_workflows(
    tmp_path: Path,
):
    def shallow_git(command, _root):
        if command == ["rev-parse", "--is-inside-work-tree"]:
            return gs.RunResult(0, "true\n", "")
        if command == ["rev-parse", "--is-shallow-repository"]:
            return gs.RunResult(0, "true\n", "")
        raise AssertionError(f"unexpected git command: {command}")

    with pytest.raises(gs.GitleaksScanError, match="fetch-depth 0"):
        gs.ensure_full_history(tmp_path, git_runner=shallow_git)

    for rel_path in (".github/workflows/publish.yml", ".github/workflows/gitleaks-history.yml"):
        text = (ROOT / rel_path).read_text(encoding="utf-8")
        assert "fetch-depth: 0" in text
        assert "python scripts/gitleaks_scan.py full-history" in text


def test_baseline_entries_require_fingerprint_rationale_owner_and_review_condition(
    tmp_path: Path,
):
    valid = tmp_path / "valid.yml"
    valid.write_text(
        "\n".join(
            [
                "version: 1",
                "entries:",
                "  - fingerprint: abc:path:rule:1",
                "    rationale: generated fixture false positive",
                "    owner: security-review",
                "    review_condition: remove when fixture shape changes",
                "  - fingerprint: def:path:rule:2",
                "    rationale: historical public test vector",
                "    owner: release-owner",
                "    expires: 2027-01-01",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert gs.baseline_validation_errors(valid) == []
    assert gs.baseline_fingerprints(valid) == ["abc:path:rule:1", "def:path:rule:2"]

    invalid = tmp_path / "invalid.yml"
    invalid.write_text(
        "\n".join(
            [
                "version: 1",
                "entries:",
                "  - fingerprint: abc:path:rule:1",
                "    rationale: missing owner and review condition",
                "",
            ]
        ),
        encoding="utf-8",
    )
    errors = gs.baseline_validation_errors(invalid)
    assert "entries[1].owner must be a non-empty string" in errors
    assert "entries[1] must include review_condition or a dated expires value" in errors


def test_tracked_baseline_entries_are_reviewed_and_documented():
    """Every shipped suppression must carry its review metadata, not just a hash."""
    tracked = ROOT / "security" / "gitleaks-baseline.yml"
    assert gs.baseline_validation_errors(tracked) == []
    for entry in gs.load_baseline_metadata(tracked)["entries"]:
        # A commit-scoped fingerprint (commit:path:rule:line) can never widen into a
        # path glob or a disabled rule, which is what a broad suppression would be.
        assert len(entry["fingerprint"].split(":")) == 4
        assert len(entry["rationale"]) > 40
        assert entry["owner"]
        assert entry["review_condition"] or entry.get("expires")


def test_synthetic_fixture_smoke_covers_required_non_live_secret_classes(tmp_path: Path):
    fixture_dir = tmp_path / "fixtures"
    paths = gs.build_synthetic_fixture(fixture_dir)
    assert set(paths) == set(gs.REQUIRED_SYNTHETIC_CLASSES)

    tracked_source = "\n".join(
        [
            (ROOT / "scripts" / "gitleaks_scan.py").read_text(encoding="utf-8"),
            (ROOT / "tests" / "test_gitleaks_scan.py").read_text(encoding="utf-8"),
        ]
    )
    for path in paths.values():
        fixture_value = path.read_text(encoding="utf-8").strip()
        assert fixture_value not in tracked_source

    def runner(command, _root):
        fixture_root = Path(command[-1])
        findings = [
            {
                "RuleID": path.stem,
                "File": str(path),
                "StartLine": 1,
                "Secret": path.read_text(encoding="utf-8").strip(),
                "Fingerprint": f"fixture:{path.stem}:1",
            }
            for path in sorted(fixture_root.iterdir())
        ]
        _fake_report(command, findings)
        return gs.RunResult(1, "expected fixture findings", "")

    outcome = gs.run_fixture_smoke(
        root=tmp_path,
        config_path=ROOT / ".gitleaks.toml",
        artifact_dir=tmp_path / "artifacts",
        runner=runner,
    )

    assert outcome.returncode == 0
    assert outcome.findings == len(gs.REQUIRED_SYNTHETIC_CLASSES)
    assert "5/5 required classes" in (
        tmp_path / "artifacts" / "fixture-smoke.summary.txt"
    ).read_text(encoding="utf-8")


def test_fixture_smoke_fails_when_a_required_class_goes_undetected(tmp_path: Path):
    def runner(command, _root):
        fixture_root = Path(command[-1])
        findings = [
            {
                "RuleID": path.stem,
                "File": str(path),
                "StartLine": 1,
                "Fingerprint": f"fixture:{path.stem}:1",
            }
            for path in sorted(fixture_root.iterdir())
            if path.stem != "aws-access-key"
        ]
        _fake_report(command, findings)
        return gs.RunResult(1, "", "")

    outcome = gs.run_fixture_smoke(
        root=tmp_path,
        config_path=ROOT / ".gitleaks.toml",
        artifact_dir=tmp_path / "artifacts",
        runner=runner,
    )

    assert outcome.returncode == 1
    summary = outcome.summary_path.read_text(encoding="utf-8")
    assert "undetected: aws-access-key" in summary


@pytest.mark.skipif(REAL_GITLEAKS is None, reason="gitleaks CLI is not installed")
def test_fixture_smoke_against_the_real_gitleaks_binary(tmp_path: Path):
    """The hermetic smokes above stub the scanner; this one runs the real corpus."""
    outcome = gs.run_fixture_smoke(
        root=ROOT,
        config_path=ROOT / ".gitleaks.toml",
        artifact_dir=tmp_path / "artifacts",
    )

    assert outcome.returncode == 0
    assert outcome.findings == len(gs.REQUIRED_SYNTHETIC_CLASSES)


@pytest.mark.skipif(REAL_GITLEAKS is None, reason="gitleaks CLI is not installed")
def test_changed_range_against_the_real_gitleaks_binary_on_a_disposable_repository(
    tmp_path: Path, capsys
):
    repo = tmp_path / "repo"
    base, _ = _disposable_repo(repo)
    fixtures = gs.build_synthetic_fixture(repo / "secrets")
    _git(repo, "add", "secrets")
    _git(repo, "commit", "--quiet", "-m", "plant synthetic credentials")
    head = _git(repo, "rev-parse", "HEAD")

    outcome = gs.run_changed_range(
        root=repo,
        base_ref=base,
        head_ref=head,
        config_path=ROOT / ".gitleaks.toml",
        baseline_path=_baseline(tmp_path),
        artifact_dir=tmp_path / "artifacts",
    )
    captured = capsys.readouterr()

    assert outcome.returncode == 1
    assert outcome.findings >= len(gs.REQUIRED_SYNTHETIC_CLASSES)
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (outcome.report_path, outcome.sarif_path, outcome.summary_path)
    )
    for path in fixtures.values():
        planted = path.read_text(encoding="utf-8").strip()
        for line in planted.splitlines():
            assert line not in artifact_text
            assert line not in captured.out


def test_public_safety_and_gitleaks_own_distinct_detection_classes():
    assert ps._path_policy_hit("tracked:.tasks/raw.json", ".tasks/raw.json").rule_id == (
        "local-only-artifact-path"
    )
    assert ".tasks/" in ps.LOCAL_ONLY_PREFIXES
    assert "docs/audits/" in ps.LOCAL_ONLY_PREFIXES

    config = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    assert "useDefault = true" in config
    assert "mempalace-high-entropy-assignment" in config
    assert "local-only-artifact-path" not in config
    assert ".tasks/" not in config
    assert set(gs.REQUIRED_SYNTHETIC_CLASSES) == {
        "aws-access-key",
        "github-token",
        "high-entropy",
        "private-key",
        "pypi-token",
    }


def test_tracked_gitleaks_config_declares_no_ungoverned_allowlist():
    """The config is the third way to silence a finding; only one is governed.

    `security/gitleaks-baseline.yml` suppresses one fingerprint at a time with a
    rationale, an owner and a review condition. A `[allowlist]` in the scanner
    config suppresses by path or regex with none of that, and `validate-baseline`
    would otherwise report OK right next to it.
    """
    assert gs.config_validation_errors(ROOT / ".gitleaks.toml") == []
    assert gs.baseline_validation_errors(ROOT / "security" / "gitleaks-baseline.yml") == []


def test_config_validation_rejects_top_level_and_catch_all_rule_allowlists(tmp_path: Path, capsys):
    narrow = tmp_path / "narrow.toml"
    narrow.write_text(
        "\n".join(
            [
                "[extend]",
                "useDefault = true",
                "",
                "[[rules]]",
                'id = "mempalace-high-entropy-assignment"',
                "regex = '''(?i)token\\s*[:=]\\s*([A-Za-z0-9]{32,})'''",
                "entropy = 4.2",
                "  [rules.allowlist]",
                "  paths = ['''^tests/fixtures/''', '''\\.lock$''']",
                "  regexes = ['''EXAMPLE[_-]?ONLY''']",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # A rule that scopes its own false positives stays legal — only patterns that
    # match everything are suppressions in disguise.
    assert gs.config_validation_errors(narrow) == []

    top_level = tmp_path / "top-level.toml"
    top_level.write_text(
        "[extend]\nuseDefault = true\n\n[allowlist]\npaths = ['''.*''']\n", encoding="utf-8"
    )
    errors = gs.config_validation_errors(top_level)
    assert any("top-level allowlist" in error for error in errors), errors
    assert any("security/gitleaks-baseline.yml" in error for error in errors), errors

    catch_all = tmp_path / "catch-all.toml"
    catch_all.write_text(
        "\n".join(
            [
                "[extend]",
                "useDefault = true",
                "",
                "[[rules]]",
                'id = "demo-rule"',
                "regex = '''secret'''",
                "  [rules.allowlist]",
                "  paths = ['''.*''']",
                "",
            ]
        ),
        encoding="utf-8",
    )
    errors = gs.config_validation_errors(catch_all)
    assert errors == [
        "rule 'demo-rule' allowlist paths entry '.*' matches everything, which disables "
        "the rule without review; use security/gitleaks-baseline.yml"
    ]

    # Gitleaks also accepts the plural spelling, and `regexes` silences by content
    # rather than by path; both are the same suppression.
    plural = tmp_path / "plural.toml"
    plural.write_text(
        "\n".join(
            [
                "[extend]",
                "useDefault = true",
                "",
                "[[rules]]",
                'id = "demo-rule"',
                "regex = '''secret'''",
                "  [[rules.allowlists]]",
                "  regexes = ['''(?s).*''']",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert any("matches everything" in error for error in gs.config_validation_errors(plural))

    # validate-baseline is the CI gate that runs before every scan, so the check
    # has to block there and not only in this test.
    rc = gs.main(["--repo-root", str(ROOT), "--config", str(top_level), "validate-baseline"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "gitleaks-baseline: FAIL" in captured.err
    assert "top-level allowlist" in captured.err
    assert "Traceback" not in captured.err

    rc = gs.main(["--repo-root", str(ROOT), "validate-baseline"])
    assert rc == 0
    assert "gitleaks-baseline: OK" in capsys.readouterr().out


def test_gitleaks_wrapper_does_not_trip_the_public_safety_scan():
    """The wrapper's own token patterns must not read as planted credentials.

    public_safety_scan.py stays the owner of this rule set; the wrapper avoids
    matching itself the same way that scanner does, with character-class literals.
    """
    source = (ROOT / "scripts" / "gitleaks_scan.py").read_text(encoding="utf-8")
    findings = ps.scan_text("tracked:scripts/gitleaks_scan.py", source, ps.repository_rules(ROOT))
    assert findings == [], [finding.rule_id for finding in findings]
    assert "[g]ithub_pat_" in source
    assert "[g]hp_" in source


def test_gitleaks_logs_sarif_summaries_and_artifacts_are_redacted(tmp_path: Path, capsys):
    base = "3333333333333333333333333333333333333333"
    head = "4444444444444444444444444444444444444444"
    planted = "AK" + "IA" + "D" * 16

    def runner(command, _root):
        _fake_report(
            command,
            [
                {
                    "RuleID": "aws-access-token",
                    "File": "infra/settings.env",
                    "StartLine": 12,
                    "Secret": planted,
                    "Match": f"AWS_ACCESS_KEY_ID={planted}",
                    "Fingerprint": "def456:infra/settings.env:aws-access-token:12",
                }
            ],
        )
        return gs.RunResult(1, f"raw scanner output {planted}", "")

    outcome = gs.run_changed_range(
        root=tmp_path,
        base_ref=base,
        head_ref=head,
        config_path=ROOT / ".gitleaks.toml",
        baseline_path=_baseline(tmp_path),
        artifact_dir=tmp_path / "artifacts",
        runner=runner,
        git_runner=_ok_commit_git,
    )
    captured = capsys.readouterr()

    assert outcome.returncode == 1
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (outcome.report_path, outcome.sarif_path, outcome.summary_path)
    )
    assert planted not in captured.out
    assert planted not in captured.err
    assert planted not in artifact_text
    assert "aws-access-token" in artifact_text
    assert "infra/settings.env" in artifact_text
    assert "def456:infra/settings.env:aws-access-token:12" in artifact_text


def test_scan_artifacts_are_written_outside_the_checkout_in_every_workflow():
    """--require-clean depends on no scan ever writing into the worktree."""
    for rel_path in (
        ".github/workflows/ci.yml",
        ".github/workflows/publish.yml",
        ".github/workflows/gitleaks-history.yml",
    ):
        text = (ROOT / rel_path).read_text(encoding="utf-8")
        assert ".gitleaks-artifacts" not in text, rel_path
        for line in text.splitlines():
            if "--artifact-dir" in line:
                assert "runner.temp" in line, f"{rel_path}: {line.strip()}"


def test_package_job_does_not_require_history_scanning_it_cannot_perform():
    """ci.yml's package job has a shallow checkout and no scanner installed.

    Release admission for the full-history scan is the explicit publish.yml step,
    which runs while the checkout is still complete.
    """
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    package_job = ci.split("\n  package:\n", 1)[1].split("\n  typecheck:", 1)[0]
    assert "python scripts/release_preflight.py" in package_job
    assert "--with-gitleaks-history" not in package_job
    assert "gitleaks" not in package_job
    assert "fetch-depth: 0" not in package_job

    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "python scripts/gitleaks_scan.py full-history" in publish
    # publish.yml shallow-fetches origin/main before preflight, so preflight must
    # not be the surface that owns the history scan there either.
    assert "--with-gitleaks-history" not in publish


_SHALLOW_FETCH_RE = re.compile(r"git\s+fetch\b[^\n]*--depth")


def test_publish_full_history_scan_precedes_every_shallow_fetch_in_the_same_job():
    """Step order, not a YAML comment, is what keeps release admission working.

    `git fetch origin main --depth=1` converts publish.yml's full clone into a
    shallow one, after which `ensure_full_history` refuses the scan and the
    release. This has broken twice. A substring grep over the file cannot see it,
    so the check is per job and index-based.
    """
    inspected: list[str] = []
    for job_name, steps in _workflow_jobs(".github/workflows/publish.yml").items():
        runs = [str(step.get("run") or "") for step in steps]
        scans = [index for index, run in enumerate(runs) if "gitleaks_scan.py full-history" in run]
        fetches = [index for index, run in enumerate(runs) if _SHALLOW_FETCH_RE.search(run)]
        if not scans and not fetches:
            continue
        inspected.append(job_name)
        assert scans, (
            f"publish.yml job {job_name!r} makes its checkout shallow at step "
            f"{min(fetches)} without a full-history scan anywhere in the job"
        )
        if fetches:
            assert max(scans) < min(fetches), (
                f"publish.yml job {job_name!r}: the full-history scan at step {max(scans)} runs "
                f"after the shallow fetch at step {min(fetches)}, so it would scan a shallow "
                "checkout and reject the release"
            )
    assert inspected == ["build"]


def test_gitleaks_gate_action_has_no_unpinned_package_install():
    """The gate's own Python dependency is pinned like everything else it uses.

    40-hex action pins, a checksum-locked Go tool module and `cache: false` all
    exist so that nothing mutable feeds this gate; an unpinned `pip install` in
    the same composite action would be the one exception.
    """
    for action_path in sorted((ROOT / ".github" / "actions").glob("*/action.yml")):
        relative = action_path.relative_to(ROOT).as_posix()
        # Join shell line continuations so a flag on the next line still counts.
        text = action_path.read_text(encoding="utf-8").replace("\\\n", " ")
        for line in text.splitlines():
            if "pip install" not in line:
                continue
            assert "--require-hashes" in line, f"{relative}: {line.strip()}"
            arguments = line.split("pip install", 1)[1].split()
            assert all(
                argument.startswith("-") or argument.strip('"').endswith("requirements.txt")
                for argument in arguments
            ), f"{relative}: a package name reaches pip directly: {line.strip()}"

    action = (ROOT / GATE_ACTION_DIR / "action.yml").read_text(encoding="utf-8")
    assert "pip install pyyaml" not in action
    assert "--require-hashes" in action, "the gate must still install the wrapper dependency"

    # uv.lock owns the version and the checksums; this file is its projection.
    requirements = (ROOT / GATE_ACTION_DIR / "requirements.txt").read_text(encoding="utf-8")
    hashes = set(re.findall(r"--hash=(sha256:[0-9a-f]{64})", requirements))
    pins = re.findall(r"^([A-Za-z0-9._-]+)==(\S+?)\s*\\?$", requirements, re.MULTILINE)
    assert len(pins) == 1, pins
    name, version = pins[0]

    locked = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    entry = next(package for package in locked["package"] if package["name"] == name)
    assert version == entry["version"]
    assert hashes == {
        entry["sdist"]["hash"],
        *(wheel["hash"] for wheel in entry["wheels"]),
    }


def test_every_workflow_job_that_scans_installs_the_gate_dependency_first():
    """Each scanning job gets PyYAML and the CLI from the same pinned action."""
    scanning_jobs: list[str] = []
    for relative in GITLEAKS_WORKFLOWS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "pip install pyyaml" not in text, relative
        for job_name, steps in _workflow_jobs(relative).items():
            scans = [
                index
                for index, step in enumerate(steps)
                if "scripts/gitleaks_scan.py" in str(step.get("run") or "")
            ]
            if not scans:
                continue
            gates = [
                index
                for index, step in enumerate(steps)
                if step.get("uses") == gi.GITLEAKS_SETUP_ACTION
            ]
            scanning_jobs.append(f"{relative}:{job_name}")
            assert gates, f"{relative} job {job_name!r} scans without the pinned gate action"
            assert min(gates) < min(scans), (
                f"{relative} job {job_name!r}: the gate action runs at step {min(gates)}, after "
                f"the first scan at step {min(scans)}"
            )
    assert scanning_jobs == [
        ".github/workflows/ci.yml:gitleaks-changed-range",
        ".github/workflows/publish.yml:build",
        ".github/workflows/gitleaks-history.yml:full-history",
    ]


def test_gitleaks_cli_is_installed_from_the_checksum_locked_tool_module():
    """No workflow may name a mutable @tag; the version has exactly one home."""
    go_mod = (ROOT / "tools" / "gitleaks" / "go.mod").read_text(encoding="utf-8")
    go_sum = (ROOT / "tools" / "gitleaks" / "go.sum").read_text(encoding="utf-8")
    version = gi.gitleaks_cli_version(ROOT)

    assert version.startswith("v8.")
    assert f"{gi.GITLEAKS_GO_MODULE} {version}" in go_mod
    assert f"{gi.GITLEAKS_GO_MODULE} {version}/go.mod h1:" in go_sum
    # tools.go keeps it a *direct* requirement so Dependabot's direct-dependency
    # allowlist can open bump pull requests for it.
    assert "// indirect" not in next(
        line for line in go_mod.splitlines() if gi.GITLEAKS_GO_MODULE in line
    )

    action = (ROOT / ".github" / "actions" / "gitleaks-gate" / "action.yml").read_text(
        encoding="utf-8"
    )
    assert "go install" in action
    assert f"{gi.GITLEAKS_GO_MODULE}@" not in action

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: gomod" in dependabot
    assert "directory: /tools/gitleaks" in dependabot

    for rel_path in (
        ".github/workflows/ci.yml",
        ".github/workflows/publish.yml",
        ".github/workflows/gitleaks-history.yml",
    ):
        text = (ROOT / rel_path).read_text(encoding="utf-8")
        assert gi.GITLEAKS_INSTALL_COMMAND in text, rel_path
        assert "go-version-file: tools/gitleaks/go.mod" in text, rel_path
        assert f"{gi.GITLEAKS_GO_MODULE}@" not in text, rel_path
        assert "gitleaks/v8@v8" not in text, rel_path


def test_scheduled_history_scan_is_bounded_and_upstream_only():
    history = (ROOT / ".github" / "workflows" / "gitleaks-history.yml").read_text(encoding="utf-8")
    assert "timeout-minutes:" in history
    assert "if: github.repository == 'rergards/mempalace-code'" in history
    assert "python scripts/gitleaks_scan.py fixture-smoke" in history
