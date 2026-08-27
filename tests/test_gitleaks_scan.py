"""Focused contracts for the small Gitleaks launcher and workflow wiring."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent


def _load_module():
    path = ROOT / "scripts" / "gitleaks_scan.py"
    spec = importlib.util.spec_from_file_location("gitleaks_scan", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gs = _load_module()


def _completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_changed_range_uses_native_redaction_ignore_and_exact_range(tmp_path):
    calls = []

    def run(command, root):
        calls.append((command, root))
        if command[:2] == ["git", "rev-parse"]:
            return _completed(command, stdout="a" * 40 + "\n")
        return _completed(command)

    with patch.object(gs, "_run", side_effect=run):
        rc = gs.scan(
            ROOT,
            base_ref="BASE",
            head_ref="HEAD",
            artifact_dir=tmp_path / "report",
        )

    assert rc == 0
    command = calls[-1][0]
    assert command[:2] == ["gitleaks", "git"]
    assert command[command.index("--log-opts") + 1] == "BASE..HEAD"
    assert "--redact=100" in command
    assert command[command.index("--gitleaks-ignore-path") + 1] == ".gitleaksignore"
    assert command[command.index("--report-format") + 1] == "sarif"


@pytest.mark.parametrize("ref", ["", "-HEAD", "0" * 40, "HEAD;echo"])
def test_changed_range_rejects_unsafe_refs_before_scanner(tmp_path, ref):
    with patch.object(gs, "_run") as run:
        with pytest.raises(ValueError, match="unsafe base ref"):
            gs.scan(ROOT, base_ref=ref, head_ref="HEAD", artifact_dir=tmp_path)
    run.assert_not_called()


def test_full_history_rejects_shallow_checkout_before_scanner(tmp_path):
    with patch.object(
        gs,
        "_run",
        return_value=_completed(["git"], stdout="true\n"),
    ) as run:
        with pytest.raises(ValueError, match="non-shallow"):
            gs.scan(ROOT, artifact_dir=tmp_path)
    assert run.call_count == 1


def test_scanner_failure_returns_bounded_error(tmp_path, capsys):
    def run(command, root):
        if command[:2] == ["git", "rev-parse"]:
            return _completed(command, stdout="false\n")
        return _completed(command, returncode=1, stderr="secret material must not be echoed")

    with patch.object(gs, "_run", side_effect=run):
        assert gs.scan(ROOT, artifact_dir=tmp_path) == 1

    captured = capsys.readouterr()
    assert "scanner exit 1" in captured.err
    assert "secret material" not in captured.err


def test_workflows_use_only_changed_range_and_full_history_modes():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    history = (ROOT / ".github" / "workflows" / "gitleaks-history.yml").read_text(encoding="utf-8")

    assert "gitleaks_scan.py changed-range" in ci
    assert "gitleaks_scan.py full-history" in publish
    assert "gitleaks_scan.py full-history" in history
    for text in (ci, publish, history):
        assert "validate-baseline" not in text
        assert "fixture-smoke" not in text


def test_native_ignore_file_contains_unique_fingerprints_only():
    lines = [
        line.strip()
        for line in (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert lines
    assert len(lines) == len(set(lines))
    assert all(line.count(":") >= 3 for line in lines)


def test_composite_action_has_no_wrapper_dependency_install():
    action = (ROOT / ".github" / "actions" / "gitleaks-gate" / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "go install" in action
    assert "requirements.txt" not in action
    assert "pip install" not in action
