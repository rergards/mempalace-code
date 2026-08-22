"""Tests for scripts/public_safety_scan.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: existing script path always returns a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: existing script path has a loader
    return mod


ps = _load_module_from_path("public_safety_scan", ROOT / "scripts" / "public_safety_scan.py")


def test_rendered_scan_flags_generic_private_roots():
    planted = "/" + "Users" + "/alice/project"
    assert ps.scan_rendered_texts(planted)


def test_repository_scan_allows_public_examples():
    examples = "\n".join(
        [
            "/" + "Users" + "/you/.mempalace/palace",
            "/" + "tmp" + "/mempalace-watch.log",
            "export ANTHROPIC_API_KEY=sk-ant-...",
        ]
    )
    assert ps.scan_text("example.md", examples, ps.repository_rules(ROOT)) == []


def test_repository_scan_flags_current_home_path():
    planted = str(Path.home() / "private-project" / "file.txt")
    hits = ps.scan_text("doc.md", planted, ps.repository_rules(ROOT))
    assert [hit.rule_id for hit in hits] == ["local-home"]


def test_repository_scan_flags_secret_without_printing_match(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    token = "gh" + "p_" + "A" * 30
    (repo / "leak.txt").write_text(token + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "leak.txt"], cwd=repo, check=True, capture_output=True)

    assert ps.main(["--repo-root", str(repo), "--staged"]) == 1
    err = capsys.readouterr().err
    assert "github-token-prefix" in err
    assert token not in err


def test_repository_scan_rejects_local_only_artifact_path(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    artifact = repo / ".tasks" / "TASK-demo" / "raw.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("local evidence\n", encoding="utf-8")
    subprocess.run(["git", "add", ".tasks/TASK-demo/raw.txt"], cwd=repo, check=True)

    assert ps.main(["--repo-root", str(repo), "--staged"]) == 1
    err = capsys.readouterr().err
    assert "local-only-artifact-path" in err
    assert "staged:.tasks/TASK-demo/raw.txt" in err


# ---------------------------------------------------------------------------
# Committed-mode tests (AC-1, AC-2, AC-3)
# ---------------------------------------------------------------------------


def _init_repo_with_commit(tmp_path, files: dict) -> Path:
    """Create a git repo with an initial commit containing the given files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    for rel_path, content in files.items():
        fpath = repo / rel_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", rel_path], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def test_committed_mode_clean_head_exits_ok(tmp_path, capsys):
    repo = _init_repo_with_commit(tmp_path, {"README.md": "# mempalace\nPublic content.\n"})

    assert ps.main(["--repo-root", str(repo), "--committed"]) == 0
    out = capsys.readouterr().out
    assert "committed" in out
    assert "scanned 1 file snapshots" in out


def test_committed_mode_secret_rejected_and_redacted(tmp_path, capsys):
    token = "gh" + "p_" + "B" * 30
    repo = _init_repo_with_commit(tmp_path, {"leak.txt": token + "\n"})

    assert ps.main(["--repo-root", str(repo), "--committed"]) == 1
    err = capsys.readouterr().err
    assert "committed:leak.txt" in err
    assert "github-token-prefix" in err
    assert token not in err


def test_committed_mode_local_only_artifact_path_rejected(tmp_path, capsys):
    repo = _init_repo_with_commit(tmp_path, {".tasks/TASK-demo/raw.txt": "local evidence\n"})

    assert ps.main(["--repo-root", str(repo), "--committed"]) == 1
    err = capsys.readouterr().err
    assert "local-only-artifact-path" in err
    assert "committed:.tasks/TASK-demo/raw.txt" in err


def test_committed_vs_tracked_deleted_worktree(tmp_path, capsys):
    repo = _init_repo_with_commit(tmp_path, {".tasks/TASK-demo/raw.txt": "local evidence\n"})
    # Delete the worktree copy; HEAD still contains the file.
    (repo / ".tasks" / "TASK-demo" / "raw.txt").unlink()

    # --tracked skips the file because the worktree copy is gone.
    assert ps.main(["--repo-root", str(repo), "--tracked"]) == 0

    capsys.readouterr()  # clear stdout/stderr

    # --committed finds the path in HEAD and rejects it.
    assert ps.main(["--repo-root", str(repo), "--committed"]) == 1
    err = capsys.readouterr().err
    assert "local-only-artifact-path" in err


def test_committed_and_tracked_combined_report_separate_source_findings(tmp_path, capsys):
    token = "gh" + "p_" + "C" * 30
    repo = _init_repo_with_commit(tmp_path, {"leak.txt": token + "\n"})

    assert ps.main(["--repo-root", str(repo), "--committed", "--tracked"]) == 1
    err = capsys.readouterr().err

    assert "committed:leak.txt" in err
    assert "tracked:leak.txt" in err
    assert "staged:leak.txt" not in err
    assert "github-token-prefix" in err
    assert token not in err
    assert err.count(":leak.txt") == 2


# --- Publishable-doc runner residue (REL-V1-13-5-PUBLIC-SHAPE-PREP) -------------


def test_residue_rules_flag_runner_session_ids_and_failure_tokens():
    samples = {
        "runner-session-uuid": "blocked in run 8fbe7d92-c961-498b-9346-c294e8068dda",
        "runner-failure-token": "retried after reason=mutable_shell_context phase=implement",
        "runner-recovery-descriptor": "Supervised session evidence: see the parked row",
        "parked-row-backup-path": "backup SEC-EXAMPLE-GATE-20260815T220217Z.json",
    }
    for expected_rule, text in samples.items():
        hits = ps.scan_text("doc", text, ps.residue_rules())
        assert expected_rule in {hit.rule_id for hit in hits}, (
            f"residue rule {expected_rule} did not fire on {text!r}"
        )


def test_residue_rules_allow_public_evidence():
    """Advisory ids, protocol revisions, backlog keys, and commit SHAs are public."""
    allowed = [
        "GHSA-f4j7-r4q5-qw2c affects the available 1.x line",
        "CVE-2024-12345 does not apply",
        "MCP protocolVersion 2024-11-05",
        "AUTOPILOT-DEMO-CLI-GOLDEN-SCENARIOS passed 3/3",
        "Coding agents (Claude Code, Codex, autopilot orchestrators)",
        "Implemented by 6998c1ca and 1723af3c0dfb9a2e4c5f6a7b8c9d0e1f2a3b4c5d",
    ]
    for text in allowed:
        assert ps.scan_text("doc", text, ps.residue_rules()) == [], (
            f"residue rules must not flag public evidence: {text!r}"
        )


def test_residue_rules_apply_to_docs_but_not_tests_or_sources():
    publishable = [
        "docs/BACKLOG.yaml",
        "docs/plans/X.md",
        "README.md",
        "CHANGELOG.md",
        # Enumerating "public" directories left these uncovered; the class is
        # now the format, so a new tracked doc is covered the day it lands.
        ".claude/prompts/codex-plan-review.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/workflows/ci.yml",
        ".github/dependabot.yml",
        "benchmarks/BENCHMARKS.md",
        "mempalace_code/README.md",
        "mempalace_code/agent_plugin/skills/mempalace/SKILL.md",
        ".pre-commit-config.yaml",
    ]
    exempt = [
        "tests/test_public_safety_scan.py",
        "tests/fixtures/residue.md",
        "scripts/public_safety_scan.py",
        "mempalace_code/cli.py",
        "benchmarks/convomem_bench.py",
        # The secret-scanner baseline is written in the vocabulary it catches.
        "security/gitleaks-baseline.yml",
    ]
    for rel_path in publishable:
        assert ps.is_publishable_doc(rel_path), f"{rel_path} should carry residue rules"
    for rel_path in exempt:
        assert not ps.is_publishable_doc(rel_path), f"{rel_path} should be exempt"


def test_every_tracked_markdown_and_yaml_surface_carries_residue_rules():
    """No tracked publishable format may sit outside the residue class.

    Derived from `git ls-files` rather than a hand-kept list, so a new doc
    directory is covered on the day it appears instead of the day someone
    remembers to add it here.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()

    uncovered = [
        rel
        for rel in (part for part in tracked.split("\0") if part)
        if rel.endswith(ps.PUBLISHABLE_DOC_SUFFIXES)
        and not rel.startswith(ps.RESIDUE_EXEMPT_PREFIXES)
        and rel not in ps.DETECTOR_FIXTURE_PATHS
        and not ps.is_publishable_doc(rel)
    ]
    assert uncovered == [], f"tracked publishable surfaces with no residue rules: {uncovered}"


def test_the_uuid_rule_fires_only_on_runner_session_or_run_evidence():
    """Positive: the UUID is named as run/session evidence."""
    uuid = "8fbe7d92-c961-498b-9346-c294e8068dda"
    residue = [
        f"blocked in run {uuid}",
        f"recovered from session {uuid} after the park",
        f"{uuid} was the runner id",
        f"autopilot job {uuid}",
        f"transcript {uuid} is attached",
    ]
    for text in residue:
        hits = {hit.rule_id for hit in ps.scan_text("doc", text, ps.residue_rules())}
        assert "runner-session-uuid" in hits, f"runner residue not flagged: {text!r}"


def test_the_uuid_rule_allows_a_public_protocol_uuid():
    """Negative: the same shape is a legitimate published value.

    JSON-RPC ids, protocol examples, and namespace constants are part of the
    contract this project documents; a blanket UUID ban would make them
    unpublishable.
    """
    uuid = "8fbe7d92-c961-498b-9346-c294e8068dda"
    allowed = [
        f"MCP request id {uuid} is echoed back verbatim.",
        f'{{"id": "{uuid}", "method": "tools/call"}}',
        "The DNS namespace UUID is 6ba7b810-9dad-11d1-80b4-00c04fd430c8.",
        # `run` inside `runtime`/`prune` is not the word `run`.
        f"runtime pruning keeps {uuid} stable across restarts",
    ]
    for text in allowed:
        assert ps.scan_text("doc", text, ps.residue_rules()) == [], (
            f"public protocol UUID must not be flagged: {text!r}"
        )


def test_tracked_scan_rejects_residue_in_a_publishable_doc(tmp_path, capsys):
    repo = _init_repo_with_commit(
        tmp_path,
        {"docs/plans/EXAMPLE.md": "Blocked in run 8fbe7d92-c961-498b-9346-c294e8068dda.\n"},
    )

    assert ps.main(["--repo-root", str(repo), "--tracked"]) == 1
    err = capsys.readouterr().err
    assert "runner-session-uuid" in err
    assert "tracked:docs/plans/EXAMPLE.md" in err
    assert "8fbe7d92" not in err  # redacted: rule id and position only


def test_tracked_scan_allows_the_same_token_in_a_test_fixture(tmp_path, capsys):
    repo = _init_repo_with_commit(
        tmp_path,
        {"tests/test_example.py": "UUID = '8fbe7d92-c961-498b-9346-c294e8068dda'\n"},
    )

    assert ps.main(["--repo-root", str(repo), "--tracked"]) == 0
