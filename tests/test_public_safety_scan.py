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
