"""Contract tests for the stdlib-only public documentation drift guard."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module("docs_drift_guard", ROOT / "scripts" / "docs_drift_guard.py")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# Canonical verification command surfaces the guard checks. Kept in sync with
# guard.VERIFICATION_COMMAND_SURFACES so the fixture below satisfies every
# surface the real guard requires.
_VERIFICATION_COMMANDS_SOURCE = """_VERIFICATION_COMMANDS = (
    ("lint", "ruff check pkg/ tests/ scripts/"),
    ("format", "ruff format --check pkg/ tests/ scripts/"),
    ("tests", "python -m pytest tests/ -x -q"),
    ("typecheck", "python -m pyright"),
    ("typecheck_strict_slice", "python -m pyright -p pyrightconfig.strict.json"),
    ("public_safety", "python scripts/public_safety_scan.py --tracked --staged"),
    ("scorecard", "python scripts/quality_scorecard.py --check"),
    ("architecture_guard", "python scripts/architecture_guard.py --root ."),
)
"""

_CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND = (
    "python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream"
)


def _make_repo(tmp_path: Path) -> Path:
    """Build a fully synchronized synthetic repo satisfying every guard check."""
    _write(
        tmp_path / "pyproject.toml",
        """[project]
version = "1.2.3"
requires-python = ">=3.11"
classifiers = [
    "Development Status :: 4 - Beta",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]

[project.optional-dependencies]
dev = ["pytest>=7.0"]
treesitter = ["tree-sitter>=0.22"]
""",
    )
    _write(
        tmp_path / "mempalace_code" / "mcp" / "registry.py",
        "from .tools.read import TOOL_SPECS as _read_specs\n",
    )
    _write(
        tmp_path / "mempalace_code" / "mcp" / "tools" / "read.py",
        'TOOL_SPECS = {"mempalace_status": {}, "mempalace_search": {}}\n',
    )
    _write(
        tmp_path / "mempalace_code" / "mcp_tool_profiles.py",
        """PROFILES = {
    "minimal": frozenset({"mempalace_status", "mempalace_search"}),
    "kg": frozenset({"mempalace_status", "mempalace_search"}),
    "code": frozenset({"mempalace_status", "mempalace_search"}),
    "notes": frozenset({"mempalace_status", "mempalace_search"}),
    "full": frozenset(),
}
""",
    )
    _write(
        tmp_path / "mempalace_code" / "cli.py",
        '''"""Fixture CLI."""

import argparse


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Init")
    p_init.add_argument("dir")

    p_mine = sub.add_parser("mine", help="Mine")
    p_mine.add_argument("dir")

    sub.add_parser("status", help="Status")

    p_diary = sub.add_parser("diary", help="Diary commands")
    diary_sub = p_diary.add_subparsers(dest="diary_command")
    diary_sub.add_parser("write", help="Write a diary entry")

    args = parser.parse_args()
''',
    )
    _write(
        tmp_path / "README.md",
        """<strong>2 MCP Tools</strong>
### MCP Server — 2 Tools
| `full` _(default)_ | all 2 |
Python 3.11+
version-1.2.3-
Median 14.8x, peak 25.2x token savings.

Code retrieval R@5 (MiniLM, 469 chunks) 95.0%, R@10 100%.
.NET retrieval R@5 (CleanArchitecture pinned corpus, vector) 90.0%, hybrid R@5 100%.
See benchmarks/retrieval_quality_facts.json for provenance.

| Tool | What |
|------|------|
| `mempalace_status` | Palace overview |
| `mempalace_search` | Semantic search |

**Optional extras:**

```bash
pip install "mempalace-code[dev]"
pip install "mempalace-code[treesitter]"
```

<details>
<summary><strong>All CLI Commands</strong></summary>

```bash
mempalace-code init <dir>
mempalace-code mine <dir>
mempalace-code status
mempalace-code diary write --agent <name> --entry "<text>"
```

</details>
""",
    )
    _write(tmp_path / "CHANGELOG.md", "# Changelog\n\n## v1.2.3 — 2026-01-01\n")
    _write(
        tmp_path / "CLAUDE.md",
        """## Running Tests

```bash
python -m pytest tests/ -x -q
```

## Linting

```bash
ruff check pkg/ tests/ scripts/
ruff format --check pkg/ tests/ scripts/
python -m pyright
```
""",
    )
    _write(
        tmp_path / "docs" / "AGENT_INSTALL.md",
        "| MCP tools | 2 tools\n`full` — all 2 tools\nPython 3.11+\n",
    )
    blocks = []
    for profile in ("minimal", "kg", "code", "notes", "full"):
        blocks.append(
            f"<!-- mcp-profile:{profile} start -->\n"
            "mempalace_status mempalace_search\n"
            f"<!-- mcp-profile:{profile} end -->"
        )
    _write(
        tmp_path / "docs" / "LLM_USAGE_RULES.md",
        "subset of the 2 tools\n" + "\n".join(blocks),
    )
    _write(
        tmp_path / "docs" / "RELEASING.md",
        guard.ABOUT_TEMPLATE.format(tool_count=2)
        + "\n\nPublish to PyPI workflow. Tests workflow.\n"
        + _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND
        + "\nscripts/release_preflight.py\nscripts/release_status_gate.py\n",
    )
    _write(
        tmp_path / "docs" / "DEPENDENCY_UPGRADE_GATE.md",
        "Dependency Audit workflow. Tests workflow.\nscripts/dependency_upgrade_gate.py\n",
    )
    _write(
        tmp_path / "docs" / "quality" / "README.md",
        "python scripts/quality_scorecard.py --check\n"
        "python scripts/public_safety_scan.py --tracked --staged\n",
    )
    _write(
        tmp_path / "benchmarks" / "token_delta_fixture_facts.json",
        json.dumps(
            {
                "fixture_ref": "abc123abc123abc1",
                "commit": "deadbeef",
                "tracked_file_count": 100,
                "mined_drawer_count": 500,
                "supported_language_count": 10,
                "fixture_language_count": 3,
                "query_count": 20,
                "results_per_query": 5,
                "median_ratio": 14.8,
                "mean_ratio": 14.7,
                "peak_ratio": 25.2,
                "retrieval_precision_at_5": 0.5,
                "generated_at": "2026-01-01T00:00:00",
                "drift_warnings": [],
            }
        ),
    )
    _write(
        tmp_path / "docs" / "BENCH_TOKEN_DELTA.md",
        "Median 14.8x, mean 14.7x, peak 25.2x, retrieval precision@5 50%.\n",
    )
    _write(
        tmp_path / "docs" / "COMPARISON_GRAPHIFY.md",
        "Median 14.8x, peak 25.2x fewer tokens than grep + read.\n",
    )
    _write(
        tmp_path / "docs" / "OFFLINE_USAGE.md",
        "The low-level Python API also exposes one explicit network-capable method: "
        "`EntityRegistry.research()`. Calling it directly contacts the English Wikipedia "
        "REST API for the requested word. Standard CLI, MCP, onboarding, mining, search, "
        "update, and watcher flows never call this method.\n",
    )
    _write(
        tmp_path / "benchmarks" / "retrieval_quality_facts.json",
        json.dumps(
            {
                "schema_version": 1,
                "code_minilm": {
                    "source": "benchmarks/results_embed_ab_2026-04-09.json",
                    "model": "all-MiniLM-L6-v2",
                    "date": "2026-04-09",
                    "query_count": 20,
                    "chunk_count": 469,
                    "r_at_5": 0.95,
                    "r_at_10": 1.0,
                },
                "dotnet_cleanarchitecture": {
                    "source": "benchmarks/dotnet_bench.py",
                    "repo": "jasontaylordev/CleanArchitecture",
                    "repo_commit": "5a600ab8749c110384bc3bd436b9c67f3067b489",
                    "measured_date": "2026-05-03",
                    "vector_r_at_5": 0.9,
                    "hybrid_r_at_5": 1.0,
                    "reproduction_command": "python benchmarks/dotnet_bench.py --repo-dir /path/to/CleanArchitecture --compare-rerank",
                },
            }
        ),
    )
    _write(
        tmp_path / "examples" / "mcp_setup.md",
        "full 2-tool default\n| `full` _(default)_ | 2 |\n",
    )
    _write(tmp_path / "examples" / "gemini_cli_setup.md", "Python 3.11+\n")
    _write(
        tmp_path / ".claude" / "skills" / "verify" / "INSTRUCTIONS.md",
        "ruff check pkg/ tests/ scripts/\n"
        "ruff format --check pkg/ tests/ scripts/\n"
        "python -m pytest tests/ -x -q\n"
        "python -m pyright\n"
        "python -m pyright -p pyrightconfig.strict.json\n"
        "python scripts/public_safety_scan.py --tracked --staged\n"
        "python scripts/quality_scorecard.py --check\n"
        "python scripts/architecture_guard.py --root .\n",
    )
    _write(
        tmp_path / ".claude" / "skills" / "release" / "SKILL.md",
        "ruff check pkg/ tests/ scripts/\n"
        "ruff format --check pkg/ tests/ scripts/\n"
        "python -m pyright\n" + _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND + "\n",
    )
    _write(
        tmp_path / ".claude" / "skills" / "release-prep" / "SKILL.md",
        _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND + "\n",
    )
    _write(
        tmp_path / "docs" / "UPSTREAM_COMPARISON.md",
        _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND + "\n",
    )
    _write(tmp_path / "scripts" / "quality_scorecard.py", _VERIFICATION_COMMANDS_SOURCE)
    _write(tmp_path / "scripts" / "release_preflight.py", "# fixture stub\n")
    _write(tmp_path / "scripts" / "release_status_gate.py", "# fixture stub\n")
    _write(tmp_path / "scripts" / "dependency_upgrade_gate.py", "# fixture stub\n")
    _write(
        tmp_path / ".github" / "workflows" / "ci.yml",
        "name: Tests\n\non: [push]\n\njobs:\n  test:\n    strategy:\n      matrix:\n"
        '        python-version: ["3.11", "3.12", "3.13", "3.14"]\n',
    )
    _write(
        tmp_path / ".github" / "workflows" / "publish.yml", "name: Publish to PyPI\n\non: [push]\n"
    )
    _write(
        tmp_path / ".github" / "workflows" / "dependency-audit.yml",
        "name: Dependency Audit\n\non: [schedule]\n",
    )
    return tmp_path


def test_evaluate_accepts_synchronised_public_facts(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)

    assert errors == []
    assert facts["version"] == "1.2.3"
    assert facts["tool_count"] == 2
    assert facts["profile_counts"] == {
        "code": 2,
        "full": 2,
        "kg": 2,
        "minimal": 2,
        "notes": 2,
    }


def test_evaluate_reports_profile_tool_drift(tmp_path: Path):
    root = _make_repo(tmp_path)
    path = root / "docs" / "LLM_USAGE_RULES.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("mempalace_search", "", 1), encoding="utf-8"
    )

    _, errors = guard.evaluate(root)

    assert any("profile 'minimal' drift" in error for error in errors)


def test_cli_json_is_public_and_machine_readable(tmp_path: Path, capsys):
    root = _make_repo(tmp_path)

    assert guard.main(["--root", str(root), "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["facts"]["tool_count"] == 2
    assert result["errors"] == []


def test_taxonomy_filter_contract_docs():
    """AC-8: CLI help, MCP schema text, and search docs explain taxonomy validation.

    Unlike the synthesised-repo tests above, this reads the real repo tree directly —
    the taxonomy filter contract is documented in public-facing text, not structured
    facts the rest of this guard extracts.
    """
    cli_text = (ROOT / "mempalace_code" / "cli.py").read_text(encoding="utf-8")
    assert "validated against the palace taxonomy" in cli_text
    assert "exits with status 2" in cli_text

    search_tools_text = (ROOT / "mempalace_code" / "mcp" / "tools" / "search.py").read_text(
        encoding="utf-8"
    )
    assert "validated against the palace taxonomy" in search_tools_text
    assert "advisory suggestions" in search_tools_text

    how_search_text = (ROOT / "docs" / "HOW_SEARCH_WORKS.md").read_text(encoding="utf-8")
    assert "Taxonomy Filter Validation" in how_search_text
    assert "unknown_wing" in how_search_text
    assert "valid empty result" in how_search_text.lower()
    assert "advisory only" in how_search_text.lower()

    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "validated against the palace taxonomy" in readme_text
    assert "advisory" in readme_text.lower()
    assert "HOW_SEARCH_WORKS.md" in readme_text


# ── AC-1: CLI command inventory derived from argparse ──────────────────────────


def test_cli_command_inventory_is_derived_from_argparse_and_docs_must_match(tmp_path: Path):
    root = _make_repo(tmp_path)

    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["cli_top_level_commands"] == ["diary", "init", "mine", "status"]
    assert facts["cli_nested_command_count"] == 1

    # A command added to argparse but not documented in README's "All CLI
    # Commands" section is reported with file + section context.
    cli_path = root / "mempalace_code" / "cli.py"
    cli_path.write_text(
        cli_path.read_text(encoding="utf-8").replace(
            'sub.add_parser("status", help="Status")',
            'sub.add_parser("status", help="Status")\n    sub.add_parser("wake-up", help="Wake")',
        ),
        encoding="utf-8",
    )
    _, errors = guard.evaluate(root)
    assert any(
        "README.md" in error and "All CLI Commands" in error and "wake-up" in error
        for error in errors
    ), errors

    # A README command that no longer exists in argparse is reported as stale.
    root2 = _make_repo(tmp_path / "stale-cli")
    readme_path = root2 / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace(
            "mempalace-code status", "mempalace-code status\nmempalace-code removed-command"
        ),
        encoding="utf-8",
    )
    _, errors = guard.evaluate(root2)
    assert any(
        "README.md" in error
        and "All CLI Commands" in error
        and "removed-command" in error
        and "no longer in" in error
        for error in errors
    ), errors


def test_unsupported_aaak_30x_claim_is_rejected(tmp_path: Path):
    root = _make_repo(tmp_path)
    readme_path = root / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8")
        + "\nmempalace-code compress  # lossy AAAK Dialect (~30x reduction)\n",
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("README.md:") and "unsupported AAAK claim still present" in error
        for error in errors
    ), errors


def test_aaak_mention_without_lossy_qualifier_is_rejected(tmp_path: Path):
    root = _make_repo(tmp_path)
    readme_path = root / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8") + "\nmempalace-code compress  # AAAK Dialect\n",
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("README.md:") and "missing a 'lossy' qualifier" in error
        for error in errors
    ), errors


def test_readme_missing_mcp_tool_name_is_reported_with_useful_diagnostic(tmp_path: Path):
    """Every live full-profile MCP tool name must appear (backtick-quoted) in README.md."""
    root = _make_repo(tmp_path)
    readme_path = root / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace(
            "| `mempalace_search` | Semantic search |\n", ""
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("README.md:")
        and "MCP tool tables missing documented tool names" in error
        and "mempalace_search" in error
        for error in errors
    ), errors


# ── AC-2: MCP documentation matches registry and profiles ──────────────────────


def test_mcp_documentation_matches_registry_and_profiles(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["tool_count"] == 2
    assert set(facts["profile_counts"]) == {"minimal", "kg", "code", "notes", "full"}

    # Hidden/extra tool drift inside a reduced-profile block is reported.
    root2 = _make_repo(tmp_path / "mcp-extra-tool")
    path = root2 / "docs" / "LLM_USAGE_RULES.md"
    text = path.read_text(encoding="utf-8")
    marker = "<!-- mcp-profile:kg start -->\n"
    insert_at = text.index(marker) + len(marker)
    injected = text[:insert_at] + "mempalace_kg_query\n" + text[insert_at:]
    path.write_text(injected, encoding="utf-8")
    _, errors = guard.evaluate(root2)
    assert any("profile 'kg' drift" in error and "extra" in error for error in errors), errors

    # A missing profile block is reported with file + section.
    root3 = _make_repo(tmp_path / "mcp-missing-block")
    path3 = root3 / "docs" / "LLM_USAGE_RULES.md"
    text3 = path3.read_text(encoding="utf-8")
    stripped = text3.replace(
        "<!-- mcp-profile:notes start -->\n"
        "mempalace_status mempalace_search\n"
        "<!-- mcp-profile:notes end -->",
        "",
    )
    assert stripped != text3
    path3.write_text(stripped, encoding="utf-8")
    _, errors = guard.evaluate(root3)
    assert any(
        "docs/LLM_USAGE_RULES.md" in error and "missing profile block for 'notes'" in error
        for error in errors
    ), errors


# ── AC-3: Optional extras and release/dependency gate docs ─────────────────────


def test_optional_extras_and_release_gate_docs_match_metadata_and_workflows(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["optional_extras"] == ["dev", "treesitter"]
    assert facts["workflow_names"] == {
        "tests": "Tests",
        "publish": "Publish to PyPI",
        "dependency_audit": "Dependency Audit",
    }

    # README missing a declared extra is reported with file + section.
    root2 = _make_repo(tmp_path / "extras-missing")
    readme2 = root2 / "README.md"
    readme2.write_text(
        readme2.read_text(encoding="utf-8").replace(
            'pip install "mempalace-code[treesitter]"\n', ""
        ),
        encoding="utf-8",
    )
    _, errors = guard.evaluate(root2)
    assert any(
        "README.md" in error and "Optional extras" in error and "missing treesitter" in error
        for error in errors
    ), errors

    # A workflow name renamed in publish.yml is no longer reflected in
    # docs/RELEASING.md, which must be reported.
    root3 = _make_repo(tmp_path / "workflow-renamed")
    publish3 = root3 / ".github" / "workflows" / "publish.yml"
    publish3.write_text("name: Ship to PyPI\n\non: [push]\n", encoding="utf-8")
    _, errors = guard.evaluate(root3)
    assert any("docs/RELEASING.md" in error and "Ship to PyPI" in error for error in errors), errors


# ── AC-4: Canonical verification command documentation ─────────────────────────


def test_canonical_verification_command_docs_match_scorecard_commands(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["verification_commands"]["lint"] == "ruff check pkg/ tests/ scripts/"
    assert set(facts["verification_commands"]) == {
        "lint",
        "format",
        "tests",
        "typecheck",
        "typecheck_strict_slice",
        "public_safety",
        "scorecard",
        "architecture_guard",
    }

    # CLAUDE.md drifting from the canonical lint command is reported with the
    # affected surface and command name.
    root2 = _make_repo(tmp_path / "claude-md-drift")
    claude_path = root2 / "CLAUDE.md"
    claude_path.write_text(
        claude_path.read_text(encoding="utf-8").replace(
            "ruff check pkg/ tests/ scripts/", "ruff check pkg/ tests/"
        ),
        encoding="utf-8",
    )
    _, errors = guard.evaluate(root2)
    assert any(
        "CLAUDE.md" in error and "canonical verification command drift (lint)" in error
        for error in errors
    ), errors


def test_live_release_preflight_command_is_synchronised_across_release_surfaces(
    tmp_path: Path,
):
    root = _make_repo(tmp_path)
    _, errors = guard.evaluate(root)
    assert errors == []

    stale_root = _make_repo(tmp_path / "stale-live-release-preflight")
    stale_path = stale_root / ".claude" / "skills" / "release-prep" / "SKILL.md"
    stale_path.write_text(
        "python scripts/release_preflight.py --tag vX.Y.Z --require-clean\n",
        encoding="utf-8",
    )

    _, errors = guard.evaluate(stale_root)

    assert any(
        error.startswith(".claude/skills/release-prep/SKILL.md:")
        and _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND in error
        for error in errors
    ), errors


# ── Benchmark fixture facts (AC-2, AC-5) ────────────────────────────────────────


def test_benchmark_fixture_facts_are_surfaced_and_synchronised(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["benchmark_fixture_facts"]["median_ratio"] == 14.8
    assert facts["benchmark_fixture_facts"]["retrieval_precision_at_5"] == 0.5


def test_benchmark_fixture_facts_missing_file_fails_hard(tmp_path: Path):
    root = _make_repo(tmp_path / "missing-facts")
    (root / "benchmarks" / "token_delta_fixture_facts.json").unlink()

    facts, errors = guard.evaluate(root)

    assert facts == {}
    assert any("token_delta_fixture_facts.json" in error for error in errors)


def test_benchmark_fixture_facts_doc_drift_is_reported_with_file_and_field(tmp_path: Path):
    root = _make_repo(tmp_path / "bench-drift")
    readme_path = root / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace("peak 25.2x", "peak 30.0x"),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        "README.md" in error
        and "benchmark fixture facts drift (peak_ratio)" in error
        and "25.2x" in error
        for error in errors
    ), errors


def test_retrieval_quality_facts_are_surfaced_and_synchronised(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["retrieval_quality_facts"]["code_minilm"]["r_at_5"] == 0.95
    assert facts["retrieval_quality_facts"]["dotnet_cleanarchitecture"]["vector_r_at_5"] == 0.9


def test_retrieval_quality_facts_missing_file_fails_hard(tmp_path: Path):
    root = _make_repo(tmp_path / "missing-retrieval-facts")
    (root / "benchmarks" / "retrieval_quality_facts.json").unlink()

    facts, errors = guard.evaluate(root)

    assert facts == {}
    assert any("retrieval_quality_facts.json" in error for error in errors)


def test_retrieval_quality_facts_doc_drift_is_reported_with_file_and_field(tmp_path: Path):
    root = _make_repo(tmp_path / "retrieval-drift")
    readme_path = root / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace("vector) 90.0%", "vector) 85.0%"),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        "README.md" in error
        and "retrieval quality facts drift (.NET vector R@5)" in error
        and "90.0%" in error
        for error in errors
    ), errors


def test_retrieval_quality_facts_requires_readme_link(tmp_path: Path):
    root = _make_repo(tmp_path / "retrieval-no-link")
    readme_path = root / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace(
            "See benchmarks/retrieval_quality_facts.json for provenance.\n", ""
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("README.md:") and "retrieval_quality_facts.json" in error
        for error in errors
    ), errors


def test_stale_benchmark_wording_is_rejected_even_when_facts_match(tmp_path: Path):
    """AC-2/AC-5: a superseded '19k'/'595x' claim fails even alongside correct numbers."""
    root = _make_repo(tmp_path / "stale-wording")
    comparison_path = root / "docs" / "COMPARISON_GRAPHIFY.md"
    comparison_path.write_text(
        comparison_path.read_text(encoding="utf-8") + "\nOld claim: 595x on a 19k-chunk project.\n",
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        "docs/COMPARISON_GRAPHIFY.md" in error and "stale benchmark wording" in error
        for error in errors
    ), errors


# ── AC-5: stale document fixtures across every category ────────────────────────


def test_stale_document_fixtures_fail_with_file_and_section_diagnostics(tmp_path: Path):
    """Every guard category fails deterministically with a file + section diagnostic."""

    # CLI: an argparse command undocumented in README's All CLI Commands section.
    cli_root = _make_repo(tmp_path / "cli")
    cli_path = cli_root / "mempalace_code" / "cli.py"
    cli_path.write_text(
        cli_path.read_text(encoding="utf-8").replace(
            'sub.add_parser("status", help="Status")',
            'sub.add_parser("status", help="Status")\n    sub.add_parser("extra-cmd")',
        ),
        encoding="utf-8",
    )
    _, cli_errors = guard.evaluate(cli_root)
    assert any(e.startswith("README.md:") and "extra-cmd" in e for e in cli_errors), cli_errors

    # MCP: profile tool-set drift.
    mcp_root = _make_repo(tmp_path / "mcp")
    mcp_path = mcp_root / "docs" / "LLM_USAGE_RULES.md"
    mcp_path.write_text(
        mcp_path.read_text(encoding="utf-8").replace("mempalace_search", "", 1),
        encoding="utf-8",
    )
    _, mcp_errors = guard.evaluate(mcp_root)
    assert any(e.startswith("docs/LLM_USAGE_RULES.md:") and "drift" in e for e in mcp_errors), (
        mcp_errors
    )

    # Optional extras: pyproject gains an extra README never documents.
    extras_root = _make_repo(tmp_path / "extras")
    pyproject_path = extras_root / "pyproject.toml"
    pyproject_path.write_text(
        pyproject_path.read_text(encoding="utf-8") + 'chroma = ["chromadb>=0.5.0,<1"]\n',
        encoding="utf-8",
    )
    _, extras_errors = guard.evaluate(extras_root)
    assert any(
        e.startswith("README.md:") and "Optional extras" in e and "chroma" in e
        for e in extras_errors
    ), extras_errors

    # Release/dependency gates: docs/DEPENDENCY_UPGRADE_GATE.md loses the
    # workflow-name reference after a rename.
    gate_root = _make_repo(tmp_path / "gate")
    audit_path = gate_root / ".github" / "workflows" / "dependency-audit.yml"
    audit_path.write_text("name: Dep Scan\n\non: [schedule]\n", encoding="utf-8")
    _, gate_errors = guard.evaluate(gate_root)
    assert any(
        e.startswith("docs/DEPENDENCY_UPGRADE_GATE.md:") and "Dep Scan" in e for e in gate_errors
    ), gate_errors

    # Verification commands: the release skill drops the canonical format command.
    verify_root = _make_repo(tmp_path / "verify")
    skill_path = verify_root / ".claude" / "skills" / "release" / "SKILL.md"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8").replace(
            "ruff format --check pkg/ tests/ scripts/\n", ""
        ),
        encoding="utf-8",
    )
    _, verify_errors = guard.evaluate(verify_root)
    assert any(
        e.startswith(".claude/skills/release/SKILL.md:")
        and "canonical verification command drift (format)" in e
        for e in verify_errors
    ), verify_errors


# ── AC-6: JSON facts and errors are actionable and machine-readable ────────────


def test_cli_json_reports_expanded_public_facts_and_errors(tmp_path: Path, capsys):
    root = _make_repo(tmp_path)

    assert guard.main(["--root", str(root), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    for key in (
        "cli_top_level_commands",
        "cli_nested_command_count",
        "optional_extras",
        "verification_commands",
        "workflow_names",
    ):
        assert key in result["facts"], f"facts missing expanded key: {key!r}"
    assert result["errors"] == []

    # Break one CLI doc fact and confirm --json surfaces a path-prefixed error
    # plus a non-zero exit code, without crashing on the expanded checks.
    readme_path = root / "README.md"
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace('pip install "mempalace-code[dev]"\n', ""),
        encoding="utf-8",
    )
    assert guard.main(["--root", str(root), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["errors"]
    assert all(":" in error for error in result["errors"])
    assert any(error.startswith("README.md:") for error in result["errors"])


# ── Retrieval quality facts: schema_version and provenance ─────────────────────


def test_retrieval_quality_facts_schema_version_is_surfaced(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["retrieval_quality_facts"]["schema_version"] == 1


def test_retrieval_quality_facts_missing_schema_version_fails_hard(tmp_path: Path):
    root = _make_repo(tmp_path / "retrieval-no-schema-version")
    path = root / "benchmarks" / "retrieval_quality_facts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["schema_version"]
    path.write_text(json.dumps(data), encoding="utf-8")

    facts, errors = guard.evaluate(root)

    assert facts == {}
    assert any(
        "retrieval_quality_facts.json" in error and "schema_version" in error for error in errors
    ), errors


def test_retrieval_quality_facts_wrong_schema_version_fails_hard(tmp_path: Path):
    root = _make_repo(tmp_path / "retrieval-wrong-schema-version")
    path = root / "benchmarks" / "retrieval_quality_facts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")

    facts, errors = guard.evaluate(root)

    assert facts == {}
    assert any(
        "retrieval_quality_facts.json" in error and "schema_version must be 1" in error
        for error in errors
    ), errors


def test_retrieval_quality_facts_missing_repo_commit_fails_hard(tmp_path: Path):
    root = _make_repo(tmp_path / "retrieval-no-repo-commit")
    path = root / "benchmarks" / "retrieval_quality_facts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["dotnet_cleanarchitecture"]["repo_commit"]
    path.write_text(json.dumps(data), encoding="utf-8")

    facts, errors = guard.evaluate(root)

    assert facts == {}
    assert any(
        "retrieval_quality_facts.json" in error and "dotnet_cleanarchitecture.repo_commit" in error
        for error in errors
    ), errors


def test_retrieval_quality_facts_missing_reproduction_command_fails_hard(tmp_path: Path):
    root = _make_repo(tmp_path / "retrieval-no-repro-command")
    path = root / "benchmarks" / "retrieval_quality_facts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["dotnet_cleanarchitecture"]["reproduction_command"]
    path.write_text(json.dumps(data), encoding="utf-8")

    facts, errors = guard.evaluate(root)

    assert facts == {}
    assert any(
        "retrieval_quality_facts.json" in error
        and "dotnet_cleanarchitecture.reproduction_command" in error
        for error in errors
    ), errors


def test_retrieval_quality_facts_missing_query_count_fails_hard(tmp_path: Path):
    root = _make_repo(tmp_path / "retrieval-no-query-count")
    path = root / "benchmarks" / "retrieval_quality_facts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["code_minilm"]["query_count"]
    path.write_text(json.dumps(data), encoding="utf-8")

    facts, errors = guard.evaluate(root)

    assert facts == {}
    assert any(
        "retrieval_quality_facts.json" in error and "code_minilm.query_count" in error
        for error in errors
    ), errors


# ── Offline usage disclosure: EntityRegistry.research() ────────────────────────


def test_offline_usage_disclosure_is_present_by_default(tmp_path: Path):
    root = _make_repo(tmp_path)
    _, errors = guard.evaluate(root)
    assert errors == []


def test_offline_usage_disclosure_tolerates_wrapped_markdown_line(tmp_path: Path):
    """A hard line-wrap between 'English Wikipedia' and 'REST API' is normal
    Markdown formatting, not a missing disclosure — it must not fail the guard."""
    root = _make_repo(tmp_path / "offline-usage-wrapped")
    path = root / "docs" / "OFFLINE_USAGE.md"
    path.write_text(
        "The low-level Python API also exposes one explicit network-capable method: "
        "`EntityRegistry.research()`. Calling it directly contacts the English Wikipedia\n"
        "REST API for the requested word. Standard CLI, MCP, onboarding, mining, search,\n"
        "update, and watcher flows never call this method.\n",
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert errors == []


def test_offline_usage_missing_disclosure_fails_with_useful_diagnostic(tmp_path: Path):
    root = _make_repo(tmp_path / "offline-usage-no-disclosure")
    path = root / "docs" / "OFFLINE_USAGE.md"
    path.write_text("mempalace-code runs offline after model download.\n", encoding="utf-8")

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("docs/OFFLINE_USAGE.md:") and "EntityRegistry.research()" in error
        for error in errors
    ), errors
    assert any(
        error.startswith("docs/OFFLINE_USAGE.md:") and "English Wikipedia REST API" in error
        for error in errors
    ), errors
    assert any(
        error.startswith("docs/OFFLINE_USAGE.md:") and "flows never call this method" in error
        for error in errors
    ), errors


# ── Python compatibility fitness: classifiers vs CI test matrix ────────────────


def test_python_classifier_versions_match_ci_test_matrix_by_default(tmp_path: Path):
    root = _make_repo(tmp_path)
    facts, errors = guard.evaluate(root)
    assert errors == []
    assert facts["python_classifier_versions"] == ["3.11", "3.12", "3.13", "3.14"]
    assert facts["ci_python_versions"] == ["3.11", "3.12", "3.13", "3.14"]


def test_ci_matrix_missing_a_classifier_version_fails_with_useful_diagnostic(tmp_path: Path):
    root = _make_repo(tmp_path / "ci-matrix-missing-version")
    path = root / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '["3.11", "3.12", "3.13", "3.14"]', '["3.11", "3.12", "3.13"]'
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith(".github/workflows/ci.yml:")
        and "python test matrix drift" in error
        and "missing 3.14" in error
        for error in errors
    ), errors


def test_ci_matrix_with_extra_version_fails_with_useful_diagnostic(tmp_path: Path):
    root = _make_repo(tmp_path / "ci-matrix-extra-version")
    path = root / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '["3.11", "3.12", "3.13", "3.14"]', '["3.10", "3.11", "3.12", "3.13", "3.14"]'
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith(".github/workflows/ci.yml:")
        and "python test matrix drift" in error
        and "extra 3.10" in error
        for error in errors
    ), errors
