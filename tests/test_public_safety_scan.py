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
