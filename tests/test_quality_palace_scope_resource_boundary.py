"""
test_quality_palace_scope_resource_boundary.py — AC-7 quality artifact guard.

Verifies that docs/quality/PALACE-SCOPE-RESOURCE-BOUNDARY.md:
  - Exists and is non-empty.
  - Contains before/after resource evidence for each AC.
  - Contains reproduction commands (code blocks or CLI commands).
  - Does not contain private paths, hostnames, auth tokens, or machine-local artifacts.
"""

import re
from pathlib import Path

ARTIFACT_PATH = (
    Path(__file__).parent.parent / "docs" / "quality" / "PALACE-SCOPE-RESOURCE-BOUNDARY.md"
)

PRIVATE_PATH_PATTERNS = [
    r"/Users/[a-zA-Z0-9_.-]+/",
    r"/home/[a-zA-Z0-9_.-]+/",
    r"~/.claude/",
    r"~/.codex",
    r"\.codex-local/",
    r"\b[a-zA-Z0-9_.-]+\.internal\b",
    r"\b[a-zA-Z0-9_.-]+\.corp\b",
    r"\b[a-zA-Z0-9_.-]+\.local\b",
]

TOKEN_PATTERNS = [
    r"\bghp_[A-Za-z0-9]+\b",
    r"\bsecret[_-]?key\b",
    r"\bapi[_-]?key\b",
    r"\bauth[_-]?token\b",
    r"\bpassword\s*=\s*\S",
]


def _read_artifact() -> str:
    assert ARTIFACT_PATH.exists(), (
        f"Quality artifact must exist at {ARTIFACT_PATH.relative_to(ARTIFACT_PATH.parent.parent.parent)}"
    )
    content = ARTIFACT_PATH.read_text(encoding="utf-8")
    assert content.strip(), "Quality artifact must not be empty"
    return content


class TestArtifactExists:
    def test_artifact_file_exists(self):
        """AC-7: The quality artifact file must exist."""
        assert ARTIFACT_PATH.exists(), "Missing: docs/quality/PALACE-SCOPE-RESOURCE-BOUNDARY.md"

    def test_artifact_is_not_empty(self):
        """AC-7: The quality artifact must contain content."""
        content = _read_artifact()
        assert len(content) > 200, "Quality artifact must contain substantial content"


class TestBeforeAfterEvidence:
    def test_contains_before_after_for_ac1(self):
        """AC-7: Artifact must document before/after evidence for scoped backup (AC-1)."""
        content = _read_artifact()
        assert "AC-1" in content, "Artifact must reference AC-1"
        assert re.search(r"before", content, re.IGNORECASE), (
            "Artifact must contain 'before' evidence"
        )
        assert re.search(r"after", content, re.IGNORECASE), "Artifact must contain 'after' evidence"

    def test_contains_before_after_for_ac3_noop_mine(self):
        """AC-7: Artifact must document before/after evidence for no-op mine (AC-3)."""
        content = _read_artifact()
        assert "AC-3" in content, "Artifact must reference AC-3"
        assert re.search(
            r"no.op\s+mine|noop\s+mine|incremental.*no\s+change", content, re.IGNORECASE
        ), "Artifact must reference no-op mine behavior"

    def test_contains_resource_metrics(self):
        """AC-7: Artifact must contain at least one resource metric (warmup, disk, time, RSS)."""
        content = _read_artifact()
        metrics = ["warmup", "disk", "wall time", "rss", "archive", "kg sqlite"]
        found = [m for m in metrics if m.lower() in content.lower()]
        assert found, (
            f"Artifact must contain at least one resource metric from {metrics}, found: {found}"
        )

    def test_before_after_shows_improvement(self):
        """AC-7: Artifact must show improvement between before and after states."""
        content = _read_artifact()
        # Must mention both a "not called" or "not created" positive state
        assert re.search(
            r"not\s+call|not\s+creat|0\s+byte|no\s+change|skip", content, re.IGNORECASE
        ), "Artifact must document that the fixed state avoids the wasteful operation"


class TestReproductionCommands:
    def test_contains_code_blocks(self):
        """AC-7: Artifact must contain at least one code block for reproduction."""
        content = _read_artifact()
        code_blocks = re.findall(r"```", content)
        assert len(code_blocks) >= 2, (
            f"Artifact must have at least one fenced code block (found {len(code_blocks) // 2} pairs)"
        )

    def test_contains_reproduction_commands_for_ac3(self):
        """AC-7: Artifact must include reproduction commands for the no-op mine."""
        content = _read_artifact()
        assert re.search(r"mine.*palace|mempalace-code\s+mine", content, re.IGNORECASE), (
            "Artifact must include mine reproduction commands"
        )

    def test_contains_reproduction_commands_for_ac4(self):
        """AC-7: Artifact must include reproduction commands for the /tmp alias."""
        content = _read_artifact()
        assert re.search(r"_macos_var_aliases|/tmp/|/private/tmp/", content), (
            "Artifact must document the /tmp alias fix with an example"
        )


class TestPublicSafety:
    def test_no_private_user_paths(self):
        """AC-7: Artifact must not contain machine-local home directory paths."""
        content = _read_artifact()
        bad = []
        for pattern in PRIVATE_PATH_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                bad.extend(matches)
        assert not bad, f"Artifact must not contain private paths or hostnames. Found: {bad}"

    def test_no_auth_tokens_or_secrets(self):
        """AC-7: Artifact must not contain auth tokens, API keys, or credentials."""
        content = _read_artifact()
        bad = []
        for pattern in TOKEN_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                bad.extend(matches)
        assert not bad, f"Artifact must not contain secrets or tokens. Found: {bad}"

    def test_no_claude_or_codex_local_paths(self):
        """AC-7: Artifact must not reference .claude/, .codex-local/, or similar private dirs."""
        content = _read_artifact()
        forbidden = [".codex-local", "~/.claude", "autopilot-", "worktrees/"]
        found = [f for f in forbidden if f in content]
        assert not found, f"Artifact must not reference private/local paths. Found: {found}"

    def test_no_machine_hostnames(self):
        """AC-7: Artifact must not reference internal or machine-specific hostnames."""
        content = _read_artifact()
        # Must not contain .internal, .corp, .local (network hostnames)
        hostname_patterns = [r"\w+\.internal\b", r"\w+\.corp\b"]
        bad = []
        for pattern in hostname_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            bad.extend(matches)
        assert not bad, f"Artifact must not reference internal hostnames. Found: {bad}"

    def test_reproduction_commands_use_relative_paths(self):
        """AC-7: Reproduction commands should use relative paths or /tmp, not absolute user paths."""
        content = _read_artifact()
        # Extract code blocks
        code_blocks = re.findall(r"```.*?```", content, re.DOTALL)
        for block in code_blocks:
            # Check for absolute user paths (not /tmp which is acceptable for examples)
            bad = re.findall(r"/(?:Users|home)/[a-zA-Z0-9_.-]+/", block)
            assert not bad, (
                f"Code block must not contain absolute user paths. Found: {bad}\nBlock: {block[:200]}"
            )
