"""
test_onboarding.py — Safety boundary tests for onboarding under degraded input.

Uses subprocess to exercise the real CLI entry point with controlled stdin,
and unit tests with monkeypatched input for fast isolated checks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path  # noqa: TC003
from unittest.mock import patch

import pytest

from mempalace_code.onboarding import (
    _AbortOnboarding,
    _ask_mode,
    _run_onboarding_inner,
    _yn,
    quick_setup,
    run_onboarding,
)

# ─────────────────────────────────────────────────────────────────────────────
# Subprocess helpers
# ─────────────────────────────────────────────────────────────────────────────


def _run_onboarding_subprocess(
    stdin_text: str,
    home: Path,
    project_dir: Path,
    timeout: int = 10,
) -> subprocess.CompletedProcess:
    """Run mempalace-code onboarding as a subprocess with given stdin bytes."""
    return subprocess.run(
        [sys.executable, "-m", "mempalace_code", "onboarding", str(project_dir)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={"HOME": str(home), "PATH": _path_env()},
    )


def _path_env() -> str:
    import os

    return os.environ.get("PATH", "/usr/bin:/bin")


def _no_traceback(result: subprocess.CompletedProcess) -> None:
    """Assert no Python traceback appears in stderr or stdout."""
    combined = result.stdout + result.stderr
    assert "Traceback (most recent call last)" not in combined, (
        f"Unexpected traceback:\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def _assert_no_residue(home: Path) -> None:
    """Assert that no onboarding output files were written under home/.mempalace."""
    mempalace = home / ".mempalace"
    assert not (mempalace / "entity_registry.json").exists(), (
        "entity_registry.json written on abort"
    )
    assert not (mempalace / "aaak_entities.md").exists(), "aaak_entities.md written on abort"
    assert not (mempalace / "critical_facts.md").exists(), "critical_facts.md written on abort"


# ─────────────────────────────────────────────────────────────────────────────
# AC-1: Empty stdin exits cleanly without traceback
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_stdin_exits_cleanly(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    result = _run_onboarding_subprocess("", home=tmp_path, project_dir=project_dir)

    _no_traceback(result)
    assert result.returncode != 0, f"expected non-zero exit on abort, got {result.returncode}"
    combined = result.stdout + result.stderr
    assert "aborted" in combined.lower(), f"expected abort message, got: {combined!r}"
    _assert_no_residue(tmp_path)


# ─────────────────────────────────────────────────────────────────────────────
# AC-2: Invalid mode input then EOF exits cleanly
# ─────────────────────────────────────────────────────────────────────────────


def test_invalid_mode_then_eof_exits_cleanly(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    # One invalid choice, then stdin closes (EOF on next read)
    stdin = "bad\n"
    result = _run_onboarding_subprocess(stdin, home=tmp_path, project_dir=project_dir)

    _no_traceback(result)
    assert result.returncode != 0, f"expected non-zero exit on abort, got {result.returncode}"
    assert "aborted" in (result.stdout + result.stderr).lower()
    _assert_no_residue(tmp_path)


# ─────────────────────────────────────────────────────────────────────────────
# AC-3: KeyboardInterrupt at mode prompt aborts cleanly (unit test)
# ─────────────────────────────────────────────────────────────────────────────


def test_keyboard_interrupt_aborts_cleanly(tmp_path):
    """Injecting KeyboardInterrupt at mode selection aborts without traceback."""
    call_count = [0]

    def _interrupt_on_first(prompt=""):
        call_count[0] += 1
        if call_count[0] == 1:
            raise KeyboardInterrupt
        return ""

    with patch("mempalace_code.onboarding.input", side_effect=_interrupt_on_first):
        result = run_onboarding(directory=str(tmp_path), config_dir=tmp_path)

    assert result is None, "expected None on abort"
    assert not (tmp_path / "entity_registry.json").exists(), "entity_registry.json written on abort"
    assert not (tmp_path / "aaak_entities.md").exists(), "aaak_entities.md written on abort"
    assert not (tmp_path / "critical_facts.md").exists(), "critical_facts.md written on abort"


# ─────────────────────────────────────────────────────────────────────────────
# AC-4: Yes/no bounded retry exhaustion fails safely
# ─────────────────────────────────────────────────────────────────────────────


def test_yn_retry_exhaustion_raises_abort():
    """After _MAX_RETRIES ambiguous inputs, _yn raises _AbortOnboarding."""
    inputs = iter(["maybe", "dunno", "idk"])
    with patch("mempalace_code.onboarding.input", side_effect=lambda _: next(inputs)):
        with pytest.raises(_AbortOnboarding):
            _yn("Do something?", default="n")


def test_yn_accepts_explicit_yes():
    with patch("mempalace_code.onboarding.input", return_value="yes"):
        assert _yn("Do something?", default="n") is True


def test_yn_accepts_explicit_no():
    with patch("mempalace_code.onboarding.input", return_value="no"):
        assert _yn("Do something?", default="y") is False


def test_yn_empty_uses_default_n():
    with patch("mempalace_code.onboarding.input", return_value=""):
        assert _yn("Do something?", default="n") is False


def test_yn_empty_uses_default_y():
    with patch("mempalace_code.onboarding.input", return_value=""):
        assert _yn("Do something?", default="y") is True


def test_yn_rejects_prefix_y_only():
    """'yesterday' must not count as yes — only explicit 'y' or 'yes'."""
    inputs = iter(["yesterday", "y"])
    with patch("mempalace_code.onboarding.input", side_effect=lambda _: next(inputs)):
        result = _yn("Do something?", default="n")
    assert result is True  # second input was valid "y"


# ─────────────────────────────────────────────────────────────────────────────
# AC-5: Local file scanning defaults to No
# ─────────────────────────────────────────────────────────────────────────────


def test_scan_defaults_no_on_empty_answer(tmp_path):
    """Pressing enter at the scan prompt (empty input) must NOT trigger scanning."""
    (tmp_path / "proj").mkdir(exist_ok=True)

    # Empty answer at the scan yn prompt → default No → scan not called
    inputs_iter = iter(["1", "", "", "", ""])

    def fake_input(prompt=""):
        try:
            return next(inputs_iter)
        except StopIteration:
            raise EOFError from None

    with (
        patch("mempalace_code.onboarding.input", side_effect=fake_input),
        patch("mempalace_code.onboarding.scan_for_detection") as mock_scan,
    ):
        run_onboarding(directory=str(tmp_path), config_dir=tmp_path)

    mock_scan.assert_not_called()


def test_scan_explicit_yes_triggers_scan(tmp_path):
    """Typing 'yes' at the scan prompt must call scan_for_detection."""
    (tmp_path / "proj").mkdir(exist_ok=True)

    inputs_iter = iter(["1", "", "", "", "yes", str(tmp_path)])

    def fake_input(prompt=""):
        try:
            return next(inputs_iter)
        except StopIteration:
            raise EOFError from None

    with (
        patch("mempalace_code.onboarding.input", side_effect=fake_input),
        patch("mempalace_code.onboarding.scan_for_detection", return_value=[]) as mock_scan,
    ):
        run_onboarding(directory=str(tmp_path), config_dir=tmp_path)

    mock_scan.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# AC-6: Safe rerun — no duplicate registry entries
# ─────────────────────────────────────────────────────────────────────────────


def test_safe_rerun_no_duplicate_people(tmp_path):
    """Identical rerun: one entry per person. Changed rerun: updates relationship/context."""
    people = [{"name": "Alice", "relationship": "colleague", "context": "work"}]
    reg = quick_setup("work", people, projects=["Lantern"], config_dir=tmp_path)
    assert "Alice" in reg.people
    assert reg.projects == ["Lantern"]

    # Identical rerun — one entry, same data
    reg2 = quick_setup("work", people, projects=["Lantern"], config_dir=tmp_path)
    assert list(reg2.people.keys()).count("Alice") == 1
    assert reg2.people["Alice"]["relationship"] == "colleague"

    # Changed rerun — relationship/context must update, not be preserved from original
    people_changed = [{"name": "Alice", "relationship": "partner", "context": "personal"}]
    reg3 = quick_setup("work", people_changed, projects=["Lantern"], config_dir=tmp_path)
    assert list(reg3.people.keys()).count("Alice") == 1
    assert reg3.people["Alice"]["relationship"] == "partner"
    assert reg3.people["Alice"]["contexts"] == ["personal"]


def test_safe_rerun_no_duplicate_projects(tmp_path):
    """Identical rerun: no duplicates. Changed rerun: list replaced, stale projects removed."""
    reg = quick_setup("work", [], projects=["ProjectA", "ProjectB"], config_dir=tmp_path)
    assert reg.projects.count("ProjectA") == 1

    # Identical rerun — no duplicates
    reg2 = quick_setup("work", [], projects=["ProjectA", "ProjectB"], config_dir=tmp_path)
    assert reg2.projects.count("ProjectA") == 1
    assert reg2.projects.count("ProjectB") == 1

    # Changed rerun — ProjectB removed, ProjectC added; ProjectB must not survive
    reg3 = quick_setup("work", [], projects=["ProjectA", "ProjectC"], config_dir=tmp_path)
    assert "ProjectA" in reg3.projects
    assert "ProjectC" in reg3.projects
    assert "ProjectB" not in reg3.projects


def test_write_failure_restores_all_prior_onboarding_files(tmp_path):
    people = [{"name": "Alice", "relationship": "colleague", "context": "work"}]
    quick_setup("work", people, projects=["OldProject"], config_dir=tmp_path)
    paths = {
        "registry": tmp_path / "entity_registry.json",
        "aaak": tmp_path / "aaak_entities.md",
        "facts": tmp_path / "critical_facts.md",
    }
    paths["aaak"].write_text("old aaak", encoding="utf-8")
    paths["facts"].write_text("old facts", encoding="utf-8")
    before = {name: path.read_bytes() for name, path in paths.items()}

    from mempalace_code.room_detector_local import write_regular_destination as real_write

    failed = False

    def fail_once(destination, content):
        nonlocal failed
        if destination.name == "critical_facts.md" and not failed:
            failed = True
            raise OSError("simulated facts write failure")
        return real_write(destination, content)

    with (
        patch("mempalace_code.onboarding._ask_mode", return_value="personal"),
        patch("mempalace_code.onboarding._ask_people", return_value=(people, {})),
        patch("mempalace_code.onboarding._ask_projects", return_value=["NewProject"]),
        patch("mempalace_code.onboarding._ask_wings", return_value=["notes"]),
        patch("mempalace_code.onboarding._warn_ambiguous", return_value=[]),
        patch(
            "mempalace_code.room_detector_local.write_regular_destination", side_effect=fail_once
        ),
    ):
        with pytest.raises(OSError, match="simulated facts write failure"):
            _run_onboarding_inner(str(tmp_path), tmp_path, auto_detect=False)

    assert {name: path.read_bytes() for name, path in paths.items()} == before


# ─────────────────────────────────────────────────────────────────────────────
# AC-7: Mode selection bounded retries (unit)
# ─────────────────────────────────────────────────────────────────────────────


def test_ask_mode_bounded_retries():
    """_ask_mode raises _AbortOnboarding after _MAX_RETRIES invalid choices."""
    inputs = iter(["9", "x", "bad"])
    with patch("mempalace_code.onboarding.input", side_effect=lambda _: next(inputs)):
        with pytest.raises(_AbortOnboarding):
            _ask_mode()


def test_ask_mode_valid_on_third_try():
    """Mode selection succeeds if a valid choice arrives within the retry budget."""
    inputs = iter(["bad", "bad", "2"])  # two invalid, then valid
    with patch("mempalace_code.onboarding.input", side_effect=lambda _: next(inputs)):
        mode = _ask_mode()
    assert mode == "personal"


def test_ask_mode_eof_raises_abort():
    with patch("mempalace_code.onboarding.input", side_effect=EOFError):
        with pytest.raises(_AbortOnboarding):
            _ask_mode()


# ─────────────────────────────────────────────────────────────────────────────
# AC-8: Completed minimal explicit flow exits 0 and writes registry/AAAK files
# ─────────────────────────────────────────────────────────────────────────────


def test_malformed_mode_then_minimal_flow_prints_clean_summary(tmp_path):
    """Malformed mode is retried before a zero-person work-mode flow completes."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    # "bad"=retry, "1"=work, then empty people/projects and default wings/scan answers.
    stdin = "bad\n1\n\n\n\n\n"
    result = _run_onboarding_subprocess(stdin, home=tmp_path, project_dir=project_dir)

    _no_traceback(result)
    assert result.returncode == 0, (
        f"expected exit 0 on completion, got {result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "Please enter 1, 2, or 3." in result.stdout
    assert "Setup Complete" in result.stdout
    assert "People: 0" in result.stdout
    assert "People: 0 (" not in result.stdout

    mempalace = tmp_path / ".mempalace"
    assert (mempalace / "entity_registry.json").exists(), "entity_registry.json not written"
    assert (mempalace / "aaak_entities.md").exists(), "aaak_entities.md not written"
    assert (mempalace / "critical_facts.md").exists(), "critical_facts.md not written"
