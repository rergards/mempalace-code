"""Contract tests for the concise release-skill entry point."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / ".claude" / "skills" / "release" / "SKILL.md"
PREP_SKILL = ROOT / ".claude" / "skills" / "release-prep" / "SKILL.md"
SKILL_PATH = ".claude/skills/release/SKILL.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module("docs_drift_guard", ROOT / "scripts" / "docs_drift_guard.py")
gate_inventory = _load_module("gate_inventory", ROOT / "scripts" / "gate_inventory.py")
SKILL_TEXT = SKILL.read_text(encoding="utf-8")


def test_release_skill_is_a_non_model_entry_point():
    lines = SKILL_TEXT.splitlines()
    assert lines[0] == "---"
    frontmatter_end = lines.index("---", 1)
    frontmatter = lines[1:frontmatter_end]
    assert "name: release" in frontmatter
    assert "disable-model-invocation: true" in frontmatter


def test_release_skill_routes_to_the_canonical_owners():
    assert "Read `AGENTS.md` and `docs/RELEASING.md` in full" in SKILL_TEXT
    assert "Do not restate or improvise" in SKILL_TEXT
    assert gate_inventory.RELEASE_READINESS_COMMAND in SKILL_TEXT


def test_release_skill_keeps_credentials_and_clients_out_of_release_checks():
    for marker in (
        "Never invoke Codex, Claude, Gemini",
        "Never read, copy, inspect, require, or transmit API keys",
        "ambient credentials",
    ):
        assert marker in SKILL_TEXT
    assert not re.search(r"^\s*(?:codex|claude|gemini)(?:\s|$)", SKILL_TEXT, re.MULTILINE)


def test_release_skill_requires_separate_authority_for_remote_mutations():
    for mutation in (
        "Candidate push",
        "`main` update",
        "tag push",
        "candidate deletion",
        "commit",
    ):
        assert mutation in SKILL_TEXT
    assert "fresh explicit authority" in SKILL_TEXT


def test_release_skill_does_not_duplicate_the_promotion_runbook():
    for duplicated_detail in (
        "git commit-tree",
        'git push publish "$CANDIDATE_BRANCH"',
        "release-status-surfaces",
        guard.CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND,
    ):
        assert duplicated_detail not in SKILL_TEXT


def test_tracked_release_skill_satisfies_the_docs_guard():
    _, errors = guard.evaluate(ROOT)
    assert [error for error in errors if error.startswith(f"{SKILL_PATH}:")] == []


def test_release_prep_skill_uses_the_credential_free_public_tag_owner():
    text = PREP_SKILL.read_text(encoding="utf-8")
    assert "python scripts/release_public_read.py --version-tags" in text
    assert "git ls-remote" not in text
