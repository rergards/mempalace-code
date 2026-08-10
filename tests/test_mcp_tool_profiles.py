"""
test_mcp_tool_profiles.py — Tests for mcp_tool_profiles profile definitions and
selector resolution.

Covers:
  - Profile contents match the design spec.
  - Selector expansion: full names, short names, wildcards.
  - Precedence: --tools replaces, --include adds, --exclude wins last.
  - Conflict: --tools + --include together are invalid.
  - Invalid inputs: unknown profile, unknown selector, empty-match wildcard, zero active.
  - AC-8 consistency: docs/LLM_USAGE_RULES.md profile blocks reference only enabled tools.
"""

import re
from pathlib import Path

import pytest

from mempalace_code.mcp_server import TOOLS
from mempalace_code.mcp_tool_profiles import (
    KNOWN_PROFILES,
    PROFILES,
    expand_selectors,
    resolve_active_tools,
)

_ALL = frozenset(TOOLS)


@pytest.fixture(scope="module")
def rules_path() -> Path:
    repo_root = Path(__file__).parent.parent
    path = repo_root / "docs" / "LLM_USAGE_RULES.md"
    assert path.exists(), f"LLM_USAGE_RULES.md not found at {path}"
    return path


# ── Profile Contents ──────────────────────────────────────────────────────────


class TestProfileContents:
    def test_known_profiles_set(self):
        assert {"minimal", "kg", "code", "notes", "full"} == KNOWN_PROFILES

    def test_minimal_exact(self):
        assert PROFILES["minimal"] == frozenset(
            {
                "mempalace_status",
                "mempalace_search",
                "mempalace_check_duplicate",
                "mempalace_add_drawer",
            }
        )

    def test_kg_is_superset_of_minimal(self):
        assert PROFILES["minimal"] < PROFILES["kg"]

    def test_kg_adds_four_kg_tools(self):
        extra = PROFILES["kg"] - PROFILES["minimal"]
        assert extra == frozenset(
            {
                "mempalace_kg_query",
                "mempalace_kg_add",
                "mempalace_kg_invalidate",
                "mempalace_kg_timeline",
            }
        )

    def test_code_contains_required_tools(self):
        code = PROFILES["code"]
        assert "mempalace_code_search" in code
        assert "mempalace_file_context" in code
        assert "mempalace_explain_subsystem" in code
        assert "mempalace_extract_reusable" in code
        assert "mempalace_status" in code
        assert "mempalace_mine" in code

    def test_code_excludes_write_and_diary(self):
        code = PROFILES["code"]
        assert "mempalace_add_drawer" not in code
        assert "mempalace_diary_write" not in code

    def test_notes_contains_required_tools(self):
        notes = PROFILES["notes"]
        assert "mempalace_diary_write" in notes
        assert "mempalace_diary_read" in notes
        assert "mempalace_add_drawer" in notes
        assert "mempalace_traverse" in notes
        assert "mempalace_find_tunnels" in notes

    def test_full_profile_sentinel_is_empty_frozenset(self):
        # "full" is a sentinel; resolve_active_tools expands it to all_tool_names.
        assert PROFILES["full"] == frozenset()

    def test_all_profile_tools_are_valid_tool_names(self):
        for name, tool_set in PROFILES.items():
            if name == "full":
                continue
            unknown = tool_set - _ALL
            assert not unknown, f"Profile {name!r} references unknown tools: {unknown}"


# ── Selector Expansion ────────────────────────────────────────────────────────


class TestSelectorExpansion:
    def test_full_name_exact(self):
        result = expand_selectors(["mempalace_search"], _ALL)
        assert result == frozenset({"mempalace_search"})

    def test_short_name(self):
        result = expand_selectors(["search"], _ALL)
        assert result == frozenset({"mempalace_search"})

    def test_short_name_status(self):
        result = expand_selectors(["status"], _ALL)
        assert result == frozenset({"mempalace_status"})

    def test_wildcard_short_diary(self):
        result = expand_selectors(["diary_*"], _ALL)
        assert result == frozenset({"mempalace_diary_write", "mempalace_diary_read"})

    def test_wildcard_full_prefix_diary(self):
        result = expand_selectors(["mempalace_diary_*"], _ALL)
        assert result == frozenset({"mempalace_diary_write", "mempalace_diary_read"})

    def test_wildcard_kg(self):
        result = expand_selectors(["kg_*"], _ALL)
        expected = {n for n in _ALL if n.startswith("mempalace_kg_")}
        assert result == frozenset(expected)

    def test_multiple_selectors(self):
        result = expand_selectors(["search", "add_drawer"], _ALL)
        assert result == frozenset({"mempalace_search", "mempalace_add_drawer"})

    def test_unknown_exact_selector_raises(self):
        with pytest.raises(ValueError, match="Unknown MCP tool selector"):
            expand_selectors(["nonexistent_tool"], _ALL)

    def test_unknown_wildcard_raises(self):
        with pytest.raises(ValueError, match="wildcard matches no known tools"):
            expand_selectors(["zzz_*"], _ALL)


# ── resolve_active_tools — Default (Full) ────────────────────────────────────


class TestResolveFullDefault:
    def test_default_profile_returns_all_tools(self):
        result = resolve_active_tools(_ALL)
        assert result == _ALL

    def test_explicit_full_returns_all_tools(self):
        result = resolve_active_tools(_ALL, profile="full")
        assert result == _ALL


# ── resolve_active_tools — Named Profile ─────────────────────────────────────


class TestResolveNamedProfile:
    def test_minimal_profile(self):
        result = resolve_active_tools(_ALL, profile="minimal")
        assert result == PROFILES["minimal"]

    def test_kg_profile(self):
        result = resolve_active_tools(_ALL, profile="kg")
        assert result == PROFILES["kg"]

    def test_code_profile(self):
        result = resolve_active_tools(_ALL, profile="code")
        assert result == PROFILES["code"]

    def test_notes_profile(self):
        result = resolve_active_tools(_ALL, profile="notes")
        assert result == PROFILES["notes"]


# ── resolve_active_tools — --tools Replacement ───────────────────────────────


class TestToolsReplacement:
    def test_tools_replaces_profile_base(self):
        result = resolve_active_tools(_ALL, profile="minimal", tools=["search", "add_drawer"])
        assert result == frozenset({"mempalace_search", "mempalace_add_drawer"})

    def test_tools_with_wildcard(self):
        result = resolve_active_tools(_ALL, tools=["search", "add_drawer", "diary_*"])
        assert "mempalace_search" in result
        assert "mempalace_add_drawer" in result
        assert "mempalace_diary_write" in result
        assert "mempalace_diary_read" in result
        # Nothing extra beyond what was selected
        assert len(result) == 4

    def test_tools_exact_names(self):
        result = resolve_active_tools(
            _ALL,
            tools=[
                "mempalace_search",
                "mempalace_add_drawer",
                "mempalace_diary_write",
                "mempalace_diary_read",
            ],
        )
        assert result == frozenset(
            {
                "mempalace_search",
                "mempalace_add_drawer",
                "mempalace_diary_write",
                "mempalace_diary_read",
            }
        )


# ── resolve_active_tools — --include ─────────────────────────────────────────


class TestInclude:
    def test_include_adds_to_profile(self):
        result = resolve_active_tools(_ALL, profile="minimal", include=["kg_query"])
        assert "mempalace_kg_query" in result
        # Base minimal tools still present
        assert PROFILES["minimal"] <= result

    def test_include_wildcard(self):
        result = resolve_active_tools(_ALL, profile="minimal", include=["kg_*"])
        kg_tools = {n for n in _ALL if n.startswith("mempalace_kg_")}
        assert kg_tools <= result


# ── resolve_active_tools — --exclude ─────────────────────────────────────────


class TestExclude:
    def test_exclude_removes_from_profile(self):
        result = resolve_active_tools(_ALL, profile="minimal", exclude=["search"])
        assert "mempalace_search" not in result
        # Other minimal tools still present
        assert "mempalace_status" in result
        assert "mempalace_add_drawer" in result

    def test_exclude_wins_over_include(self):
        result = resolve_active_tools(
            _ALL, profile="minimal", include=["kg_query"], exclude=["search"]
        )
        assert "mempalace_search" not in result
        assert "mempalace_kg_query" in result

    def test_exclude_full_profile(self):
        keep = {"mempalace_status", "mempalace_search"}
        exclude_names = [n for n in _ALL if n not in keep]
        result = resolve_active_tools(_ALL, profile="full", exclude=exclude_names)
        assert result == frozenset(keep)


# ── AC-4: minimal + include + exclude precedence ──────────────────────────────


class TestAC4Precedence:
    def test_minimal_include_kg_query_exclude_search(self):
        result = resolve_active_tools(
            _ALL, profile="minimal", include=["kg_query"], exclude=["search"]
        )
        assert "mempalace_kg_query" in result
        assert "mempalace_search" not in result


# ── Invalid Inputs ────────────────────────────────────────────────────────────


class TestInvalidInputs:
    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="Invalid MCP tool profile"):
            resolve_active_tools(_ALL, profile="bogus")

    def test_unknown_tool_selector_raises(self):
        with pytest.raises(ValueError, match="Unknown MCP tool selector"):
            resolve_active_tools(_ALL, tools=["nonexistent_tool_xyz"])

    def test_wildcard_matching_nothing_raises(self):
        with pytest.raises(ValueError, match="wildcard matches no known tools"):
            resolve_active_tools(_ALL, include=["zzz_*"])

    def test_zero_active_tools_raises(self):
        # Exclude everything from minimal
        minimal_short = [n.removeprefix("mempalace_") for n in PROFILES["minimal"]]
        with pytest.raises(ValueError, match="empty"):
            resolve_active_tools(_ALL, profile="minimal", exclude=minimal_short)

    def test_tools_and_include_conflict_raises(self):
        with pytest.raises(ValueError, match="cannot be combined"):
            resolve_active_tools(_ALL, tools=["search"], include=["kg_query"])

    def test_exclude_unknown_selector_raises(self):
        with pytest.raises(ValueError, match="Unknown MCP tool selector"):
            resolve_active_tools(_ALL, exclude=["not_a_real_tool"])


# ── AC-8: LLM_USAGE_RULES.md consistency ─────────────────────────────────────


class TestUsageRulesConsistency:
    """Each profile-matched block in docs/LLM_USAGE_RULES.md must reference
    only tools that are enabled by that profile.

    Marker format:
      <!-- mcp-profile:<name> start -->
      ...
      <!-- mcp-profile:<name> end -->
    """

    def _extract_blocks(self, text: str) -> dict[str, str]:
        """Return {profile_name: block_content} for each marked block."""
        pattern = re.compile(
            r"<!--\s*mcp-profile:(\w+)\s+start\s*-->(.*?)<!--\s*mcp-profile:\1\s+end\s*-->",
            re.DOTALL,
        )
        return {m.group(1): m.group(2) for m in pattern.finditer(text)}

    def _tools_mentioned(self, block: str) -> set[str]:
        return set(re.findall(r"mempalace_\w+", block))

    def test_profile_blocks_exist_for_known_profiles(self, rules_path):
        text = rules_path.read_text()
        blocks = self._extract_blocks(text)
        # At least one profile block must be present.
        assert blocks, (
            "No <!-- mcp-profile:<name> start/end --> markers found in LLM_USAGE_RULES.md"
        )

    def test_each_block_references_only_enabled_tools(self, rules_path):
        text = rules_path.read_text()
        blocks = self._extract_blocks(text)
        all_names = frozenset(TOOLS)

        for profile_name, content in blocks.items():
            assert profile_name in KNOWN_PROFILES, (
                f"Unknown profile {profile_name!r} in LLM_USAGE_RULES.md marker"
            )
            active = resolve_active_tools(all_names, profile=profile_name)
            mentioned = self._tools_mentioned(content)
            hidden = mentioned - active
            assert not hidden, (
                f"Profile {profile_name!r} block in LLM_USAGE_RULES.md references "
                f"tools not enabled by that profile: {sorted(hidden)}"
            )
