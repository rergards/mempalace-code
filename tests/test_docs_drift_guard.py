"""Contract tests for the stdlib-only public documentation drift guard."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module("docs_drift_guard", ROOT / "scripts" / "docs_drift_guard.py")
# The exact module the guard itself loads: published facts must equal the enforced
# constants, so the assertions below compare against them rather than literals.
ADMISSION = guard._load_admission_checks()

_OFFLINE_USAGE_DISCLOSURE = (
    "With version checks disabled, core commands run offline. "
    "`update status` and `update check` are read-only. Each refreshes canonical package "
    "metadata from PyPI. MEMPALACE_VERSION_CHECK=0 does not block updater PyPI requests. "
    "While offline, do not run `update status`, `update check`, `update apply --yes`, or "
    "scheduled update execution. The low-level Python API exposes "
    "`EntityRegistry.research()`, which contacts the English Wikipedia REST API. Standard "
    "CLI and MCP flows never call this method.\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# Canonical verification gates the guard checks. Kept in sync with
# guard.VERIFICATION_COMMAND_SURFACES so the fixture satisfies each public surface.
_GATE_INVENTORY_SOURCE = """CANONICAL_GATES = [
    {"id": "lint", "command": "ruff check pkg/ tests/ scripts/"},
    {"id": "format", "command": "ruff format --check pkg/ tests/ scripts/"},
    {"id": "tests", "command": "python -m pytest tests/ -x -q"},
    {"id": "typecheck", "command": "python -m pyright"},
    {"id": "typecheck_strict_slice", "command": "python -m pyright -p pyrightconfig.strict.json"},
    {"id": "public_safety", "command": "python scripts/public_safety_scan.py --tracked --staged"},
    {"id": "gitleaks_fixture_smoke", "command": "python scripts/gitleaks_scan.py fixture-smoke"},
    {"id": "gitleaks_changed_range", "command": "python scripts/gitleaks_scan.py changed-range --base-ref BASE --head-ref HEAD"},
    {"id": "scorecard", "command": "python scripts/quality_scorecard.py --check"},
    {"id": "architecture_guard", "command": "python scripts/architecture_guard.py --root ."},
]
VERIFY_SURFACE_IDS = (
    "lint",
    "format",
    "tests",
    "typecheck",
    "typecheck_strict_slice",
    "public_safety",
    "gitleaks_fixture_smoke",
    "gitleaks_changed_range",
    "scorecard",
    "architecture_guard",
)
"""

_CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND = (
    "python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream"
)
_CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND = (
    "python scripts/release_preflight.py --tag vX.Y.Z --require-clean "
    "--expect-sha <40-hex-candidate-sha> --check-public-main "
    "--check-required-check --check-dependency-audit --check-branch-rules "
    "--check-tag-ruleset"
)
_CANONICAL_RELEASE_STATUS_COMMAND = (
    "python scripts/release_status_gate.py --version X.Y.Z "
    "--repo rergards/mempalace-code --remote publish --branch main "
    "--expect-sha <40-hex-candidate-sha>"
)
_CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND = (
    "gh run rerun <publish-workflow-run-id> --job <github-release-job-id> "
    "--repo rergards/mempalace-code"
)
_CANONICAL_CANDIDATE_READINESS_COMMAND = (
    'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
)


def test_release_instructions_bind_candidate_without_client_execution():
    releasing = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    skill = (ROOT / ".claude" / "skills" / "release" / "SKILL.md").read_text(encoding="utf-8")

    for surface in (releasing, skill):
        assert surface.count(_CANONICAL_CANDIDATE_READINESS_COMMAND) == 1
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    forbidden = ("release_direct_application_gate.py", "@openai/codex", "claude-code", "gemini-cli")
    for text in (releasing, skill, workflow):
        assert all(value not in text for value in forbidden)


# The full managed rules block has one canonical owner. Line-anchored markers
# only; prose mentions do not count.
_MANAGED_RULES_BODY = "# mempalace-code — Usage Rules\n\n## Mental model\n\n## Never\n"
_MANAGED_RULES_BLOCK = (
    "<!-- mempalace-rules:start -->\n" + _MANAGED_RULES_BODY + "<!-- mempalace-rules:end -->\n"
)

# Public `main` is fast-forward-only: the docs must describe the commit-tree
# candidate branch, never `git push publish main` from a development branch. The
# candidate branch is pushed and proven green *before* it reaches `main`, so the
# fixture carries that ordering too — it is the sequence the guard enforces. The
# branch flows through one variable, and a rebuild takes the next immutable
# `-rcN` name rather than re-pushing over a published candidate.
_PROMOTION_FLOW = (
    "git fetch publish main\n"
    'CANDIDATE_SHA=$(git commit-tree "$REVIEWED^{tree}" -p publish/main -m "release vX.Y.Z")\n'
    "CANDIDATE_BRANCH=release/vX.Y.Z   # a rebuild uses release/vX.Y.Z-rc2, then -rc3\n"
    'git push publish "$CANDIDATE_BRANCH"\n'
    "# wait for Tests and release-required to be green for $CANDIDATE_SHA\n"
    'python scripts/release_preflight.py --candidate-ref "publish/$CANDIDATE_BRANCH"\n'
    'git push publish "$CANDIDATE_SHA":refs/heads/main   # fast-forward only; never --force\n'
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
custom-models = ["sentence-transformers>=2.2"]
dev = ["pytest>=7.0"]
spellcheck = ["autocorrect>=2.0"]
watch = ["watchfiles>=1.0"]
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

mempalace-code --palace "$PALACE" export --only-manual --with-kg --out "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run
mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"
Without `--force`, tar restore refuses state found at the selected palace or KG during its checks, claims the exact `lance/` name exclusively, and publishes the KG with an atomic no-replace operation. An existing real empty palace directory is the only reusable initial state. Unsupported no-replace KG publication fails closed. This boundary is not a transaction for concurrent replacement of the palace root or its ancestors, or for arbitrary edits elsewhere in the palace. Back up every reported destination before an intentional `--force` restore. See docs/BACKUP_RESTORE.md.
The separate global KG differs from <palace>/knowledge_graph.sqlite3.
mempalace-code repair --rollback --dry-run

**Optional extras:**

```bash
# mempalace-code[custom-models]  # CPU-only Linux: docs/OFFLINE_USAGE.md
pip install "mempalace-code[dev]"
pip install "mempalace-code[spellcheck]"
pip install "mempalace-code[treesitter]"
pip install "mempalace-code[watch]"
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
        tmp_path / "mempalace_code" / "README.md",
        "Runtime storage is LanceDB-only. ChromaDB appears only as migration input.\n",
    )
    _write(
        tmp_path / "AGENTS.md",
        """## Running Tests

Optional extras:

- `.[custom-models]` — custom models
- `.[dev]` — development tools
- `.[spellcheck]` — spellcheck
- `.[treesitter]` — AST parsing
- `.[watch]` — file watching

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
    _write(tmp_path / "CLAUDE.md", "@AGENTS.md\n")
    _write(
        tmp_path / "CONTRIBUTING.md",
        "ChromaDB is isolated to the one-way bridge in .[chroma-migration].\n",
    )
    _write(
        tmp_path / "docs" / "WHY_THIS_FORK.md",
        "Runtime storage is LanceDB-only; ChromaDB remains migration input.\n",
    )
    _write(
        tmp_path / "docs" / "AGENT_INSTALL.md",
        "| MCP tools | 2 tools\n`full` — all 2 tools\nPython 3.11+\n\n"
        "## Section 2 — Human-in-the-loop Questions\n\n"
        "Ask all seven questions before acting.\n\n"
        "### Q1 — First\n### Q2 — Second\n### Q3 — Third\n"
        "### Q4 — Fourth\n### Q5 — Fifth\n### Q6 — Sixth\n### Q7 — Seventh\n\n"
        "## Section 3 — Continue\n\n"
        "## Section 7 — Agent Instruction Loading (Agent Plugin Only)\n\n"
        "Agent Plugins 1.0 clients use this read-only check:\n\n"
        "mempalace-code agent-plugin path --json\n\n"
        "Instruction files stay unchanged.\n\n"
        "## End State\n",
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
        "subset of the 2 tools\n" + "\n".join(blocks) + "\n" + _MANAGED_RULES_BLOCK,
    )
    _write(
        tmp_path / "mempalace_code" / "agent_plugin" / "skills" / "mempalace" / "SKILL.md",
        "# Concise MemPalace skill\n\nUse the four minimal-profile tools.\n",
    )
    _write(
        tmp_path / "docs" / "RELEASING.md",
        guard.ABOUT_TEMPLATE.format(tool_count=2)
        + "\n\nPublish to PyPI workflow. Tests workflow.\n"
        + _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND
        + "\n"
        + _CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND
        + "\n"
        + _CANONICAL_RELEASE_STATUS_COMMAND
        + "\n"
        + _CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND
        + "\n"
        + "\n".join(guard.PUBLIC_READ_BOUNDARY_MARKERS)
        + "\nscripts/release_admission_checks.py\n"
        + "scripts/release_preflight.py\n"
        + "scripts/release_readiness_gate.py\n"
        + "scripts/release_status_gate.py\n"
        + _PROMOTION_FLOW,
    )
    # Built from the guard's own derived marker list so the fixture cannot drift
    # away from the admission contract constants it is meant to exercise.
    _write(
        tmp_path / "docs" / "release-admission-rulesets.md",
        "Public release admission contract fixture.\n"
        + "\n".join(guard.release_admission_markers())
        + "\n"
        + _CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND
        + "\n"
        + "\n".join(guard.PUBLIC_READ_BOUNDARY_MARKERS)
        + "\n",
    )
    _write(
        tmp_path / "docs" / "BACKUP_RESTORE.md",
        "## Recommended Rebuild Workflow\n"
        'PALACE="${HOME}/.mempalace/palace"\n'
        'EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"\n'
        'BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"\n'
        'QUARANTINE="${PALACE}.quarantine-$(date -u +%Y%m%dT%H%M%SZ)"\n'
        ': "${PALACE:?set PALACE to the inspected active palace}"\n'
        ': "${EXPORT_JSONL:?set EXPORT_JSONL to a new JSONL path}"\n'
        ': "${BACKUP_TAR:?set BACKUP_TAR to a new tar path}"\n'
        ': "${QUARANTINE:?set QUARANTINE to a new sibling path}"\n'
        'test ! -e "$EXPORT_JSONL"\n'
        'test ! -e "$BACKUP_TAR"\n'
        'test ! -e "$QUARANTINE"\n'
        + "\n".join(guard.BACKUP_RESTORE_REBUILD_SEQUENCE)
        + "\nKeep `$QUARANTINE`, `$EXPORT_JSONL`, and `$BACKUP_TAR`. "
        "Only then may you dispose of the quarantine.\n"
        "### Failure recovery\n" + "\n".join(guard.BACKUP_RESTORE_RECOVERY_SEQUENCE) + "\n"
        "The separate global KG differs from <palace>/knowledge_graph.sqlite3.\n"
        "## Tarball Backup (Full Snapshot)\n"
        + "\n".join(guard.BACKUP_RESTORE_TARBALL_SEQUENCE)
        + "\nWithout `--force`, the CLI refuses when its checks find state in the selected\n"
        "palace or at the selected KG destination. A real empty palace directory remains\n"
        "reusable. At publication, restore claims the exact `lance/` name exclusively and\n"
        "creates the exact KG destination with an atomic no-replace hard link. If either\n"
        "name is raced in, restore preserves it; a KG publication failure also removes the\n"
        "Lance root still owned by that invocation. Unsupported hard links fail closed.\n"
        "This boundary does not make arbitrary concurrent edits elsewhere under the palace\n"
        "transactional and does not protect concurrent replacement of the palace root or\n"
        "its ancestors. The safe flow above uses absent destinations so retries cannot\n"
        "overwrite managed publication names.\n"
        "mempalace-code repair --rollback --dry-run\n"
        "## Restore Procedure\n"
        "`--force` replaces the target's managed `lance/` data and atomically replaces the\n"
        "selected KG after archive validation. It preserves unrelated entries in a real\n"
        "palace directory. Symlink objects found at the selected palace, Lance, or KG\n"
        "validation boundary are replaced without modifying their referents; concurrent\n"
        "replacement of the palace root or its ancestors remains outside this boundary.\n"
        "Use `--force` only after inspecting the\n"
        "archive and exact destinations, then creating and inspecting a fresh backup of\n"
        "the current target. If `--kg-path` selects a KG outside that target, back up that\n"
        "file separately before adding `--force`:\n"
        ': "${KG_DEST:?set KG_DEST to the selected KG destination}"\n'
        + "\n".join(guard.BACKUP_RESTORE_FORCE_SEQUENCE)
        + "\n### Tarball Restore — KG Destination\n"
        "Use `mempalace-code migrate-storage SRC DST --verify` with "
        "`mempalace-code[chroma-migration]` for legacy ChromaDB migration input.\n",
    )
    _write(
        tmp_path / "docs" / "UPDATES.md",
        "Updates preserve installed extras, including `chroma-migration` when present.\n",
    )
    _write(
        tmp_path / "docs" / "UPSTREAM_HARDENING.md",
        "Current releases reject ChromaDB input without mutation. "
        "Follow docs/BACKUP_RESTORE.md for historical recovery.\n",
    )
    _write(
        tmp_path / "docs" / "DEPENDENCY_UPGRADE_GATE.md",
        "Dependency Audit workflow. Tests workflow.\n"
        + "\n".join(guard.dependency_audit_markers())
        + "\nRelease admission requires a successful Dependency Audit within the window.\n"
        "scripts/dependency_upgrade_gate.py\n"
        "scripts/release_admission_checks.py\n",
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
        _OFFLINE_USAGE_DISCLOSURE,
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
        "python scripts/gitleaks_scan.py fixture-smoke\n"
        "python scripts/gitleaks_scan.py changed-range --base-ref BASE --head-ref HEAD\n"
        "python scripts/quality_scorecard.py --check\n"
        "python scripts/architecture_guard.py --root .\n",
    )
    _write(
        tmp_path / ".claude" / "skills" / "release" / "SKILL.md",
        "Read AGENTS.md and docs/RELEASING.md.\n" + _CANONICAL_CANDIDATE_READINESS_COMMAND + "\n",
    )
    _write(
        tmp_path / ".claude" / "skills" / "release-prep" / "SKILL.md",
        _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND + "\n",
    )
    _write(
        tmp_path / "docs" / "UPSTREAM_COMPARISON.md",
        _CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND + "\n",
    )
    _write(tmp_path / "scripts" / "gate_inventory.py", _GATE_INVENTORY_SOURCE)
    _write(tmp_path / "scripts" / "quality_scorecard.py", "# fixture stub\n")
    _write(tmp_path / "scripts" / "release_admission_checks.py", "# fixture stub\n")
    _write(tmp_path / "scripts" / "release_preflight.py", "# fixture stub\n")
    _write(tmp_path / "scripts" / "release_readiness_gate.py", "# fixture stub\n")
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


def test_runbook_consistency_accepts_canonical_release_and_install_docs(tmp_path: Path):
    root = _make_repo(tmp_path)

    _, errors = guard.evaluate(root)

    assert errors == []


def test_runbook_consistency_rejects_duplicate_candidate_sha_assignment(tmp_path: Path):
    root = _make_repo(tmp_path)
    path = root / "docs" / "RELEASING.md"
    assignment = next(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("CANDIDATE_SHA=")
    )
    path.write_text(path.read_text(encoding="utf-8") + assignment + "\n", encoding="utf-8")

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("docs/RELEASING.md:")
        and "exactly one line-anchored CANDIDATE_SHA" in error
        and "found 2" in error
        for error in errors
    ), errors


def test_runbook_consistency_rejects_non_contiguous_install_question_headings(
    tmp_path: Path,
):
    root = _make_repo(tmp_path)
    path = root / "docs" / "AGENT_INSTALL.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("### Q7 — Seventh", "### Q8 — Eighth"),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("docs/AGENT_INSTALL.md:")
        and "headings must be contiguous Q1 through Q7" in error
        and "[1, 2, 3, 4, 5, 6, 8]" in error
        for error in errors
    ), errors


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
    assert facts["optional_extras"] == [
        "custom-models",
        "dev",
        "spellcheck",
        "treesitter",
        "watch",
    ]
    assert facts["workflow_names"] == {
        "tests": "Tests",
        "publish": "Publish to PyPI",
        "dependency_audit": "Dependency Audit",
    }
    # Derived, not restated: the guard enforces "192 hours" in
    # docs/DEPENDENCY_UPGRADE_GATE.md through dependency_audit_markers(), so a
    # literal here would let the published fact contradict the enforced window.
    assert (
        facts["release_admission"]["aggregate_required_check"] == ADMISSION.AGGREGATE_REQUIRED_CHECK
    )
    assert (
        facts["release_admission"]["dependency_audit_max_age_hours"]
        == ADMISSION.DEFAULT_AUDIT_MAX_AGE_HOURS
    )
    assert facts["release_admission"]["ruleset_doc"] == ADMISSION.RULESET_DOC
    assert f"{ADMISSION.DEFAULT_AUDIT_MAX_AGE_HOURS} hours" in guard.dependency_audit_markers()

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


def test_agents_optional_extras_report_missing_declared_extra_despite_section_prose(
    tmp_path: Path,
):
    root = _make_repo(tmp_path)
    agents_path = root / "AGENTS.md"
    agents_path.write_text(
        agents_path.read_text(encoding="utf-8")
        .replace("- `.[treesitter]` — AST parsing\n", "")
        .replace(
            "\n## Running Tests\n",
            "\nA prose note still mentions `.[treesitter]`.\n\n## Running Tests\n",
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error == "AGENTS.md: 'Optional extras' section: drift (missing treesitter)"
        for error in errors
    ), errors


def test_agents_optional_extras_report_stale_unknown_extra(tmp_path: Path):
    root = _make_repo(tmp_path)
    agents_path = root / "AGENTS.md"
    agents_path.write_text(
        agents_path.read_text(encoding="utf-8").replace(
            "- `.[watch]` — file watching\n",
            "- `.[watch]` — file watching\n- `.[unknown]` — unsupported\n",
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error == "AGENTS.md: 'Optional extras' section: drift (stale unknown)" for error in errors
    ), errors


# ── AC-4: Canonical verification command documentation ─────────────────────────


def test_canonical_verification_command_docs_match_gate_inventory(tmp_path: Path):
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
        "gitleaks_fixture_smoke",
        "gitleaks_changed_range",
        "scorecard",
        "architecture_guard",
    }

    # AGENTS.md drifting from the canonical lint command is reported with the
    # affected surface and command name.
    root2 = _make_repo(tmp_path / "agents-md-drift")
    agents_path = root2 / "AGENTS.md"
    agents_path.write_text(
        agents_path.read_text(encoding="utf-8").replace(
            "ruff check pkg/ tests/ scripts/", "ruff check pkg/ tests/"
        ),
        encoding="utf-8",
    )
    _, errors = guard.evaluate(root2)
    assert any(
        "AGENTS.md" in error and "canonical verification command drift (lint)" in error
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


def test_exact_sha_release_admission_commands_are_synchronised(tmp_path: Path):
    root = _make_repo(tmp_path)
    _, errors = guard.evaluate(root)
    assert errors == []

    releasing = root / "docs" / "RELEASING.md"
    releasing.write_text(
        releasing.read_text(encoding="utf-8").replace(
            _CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND,
            "python scripts/release_preflight.py --tag vX.Y.Z --require-clean",
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("docs/RELEASING.md:")
        and _CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND in error
        for error in errors
    ), errors


def test_partial_publication_recovery_command_is_synchronised(tmp_path: Path):
    for index, relative_path in enumerate(guard.PARTIAL_PUBLICATION_RECOVERY_SURFACES):
        root = _make_repo(tmp_path / f"partial-recovery-{index}")
        path = root / relative_path
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                _CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND,
                "gh run rerun <run-id> --failed",
            ),
            encoding="utf-8",
        )

        _, errors = guard.evaluate(root)

        assert any(
            error.startswith(f"{relative_path}:")
            and _CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND in error
            for error in errors
        ), errors


def test_release_ruleset_doc_markers_are_required(tmp_path: Path):
    root = _make_repo(tmp_path)
    path = root / "docs" / "release-admission-rulesets.md"
    path.write_text("refs/heads/main requires release-required.\n", encoding="utf-8")

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("docs/release-admission-rulesets.md:") and "refs/tags/v*" in error
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


def test_current_chroma_support_and_duplicate_recovery_are_rejected(tmp_path: Path):
    current_root = _make_repo(tmp_path / "current-chroma-support")
    readme = current_root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8")
        + "\nChromaDB only, as a deprecated optional runtime backend.\n",
        encoding="utf-8",
    )
    backup = current_root / "docs" / "BACKUP_RESTORE.md"
    command = guard.CHROMA_RECOVERY_COMMAND
    backup.write_text(f"Recovery: {command}\nRepeated: {command}\n", encoding="utf-8")

    _, errors = guard.evaluate(current_root)

    assert any("current ChromaDB runtime support wording" in error for error in errors)
    assert any("duplicate ChromaDB recovery command" in error for error in errors)


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
        pyproject_path.read_text(encoding="utf-8") + 'new-extra = ["example>=1.0"]\n',
        encoding="utf-8",
    )
    _, extras_errors = guard.evaluate(extras_root)
    assert any(
        e.startswith("README.md:") and "Optional extras" in e and "new-extra" in e
        for e in extras_errors
    ), extras_errors

    # Current-support docs: ChromaDB runtime backend wording is rejected.
    chroma_runtime_root = _make_repo(tmp_path / "chroma-runtime-docs")
    chroma_readme = chroma_runtime_root / "README.md"
    chroma_readme.write_text(
        chroma_readme.read_text(encoding="utf-8")
        + "\nChromaDB only, as a deprecated optional runtime backend.\n",
        encoding="utf-8",
    )
    _, chroma_errors = guard.evaluate(chroma_runtime_root)
    assert any(
        e.startswith("README.md:") and "ChromaDB runtime support wording" in e
        for e in chroma_errors
    ), chroma_errors

    for relative_path, marker in (
        ("CONTRIBUTING.md", "deprecated legacy optional extra (`.[chroma]`)"),
        ("docs/WHY_THIS_FORK.md", "kept as an opt-in `.[chroma]` extra"),
        ("docs/UPSTREAM_HARDENING.md", "one-way migration bridge"),
    ):
        case_root = _make_repo(
            tmp_path / f"chroma-runtime-{relative_path.replace('/', '-').replace('.', '-')}"
        )
        case_path = case_root / relative_path
        case_path.write_text(
            case_path.read_text(encoding="utf-8") + f"\n{marker}\n",
            encoding="utf-8",
        )
        _, case_errors = guard.evaluate(case_root)
        assert any(
            e.startswith(f"{relative_path}:") and "ChromaDB runtime support wording" in e
            for e in case_errors
        ), case_errors

    # Release/dependency gates: docs/DEPENDENCY_UPGRADE_GATE.md loses the
    # workflow-name reference after a rename.
    gate_root = _make_repo(tmp_path / "gate")
    audit_path = gate_root / ".github" / "workflows" / "dependency-audit.yml"
    audit_path.write_text("name: Dep Scan\n\non: [schedule]\n", encoding="utf-8")
    _, gate_errors = guard.evaluate(gate_root)
    assert any(
        e.startswith("docs/DEPENDENCY_UPGRADE_GATE.md:") and "Dep Scan" in e for e in gate_errors
    ), gate_errors

    # Verification commands: AGENTS.md drops the canonical format command.
    verify_root = _make_repo(tmp_path / "verify")
    agents_path = verify_root / "AGENTS.md"
    agents_path.write_text(
        agents_path.read_text(encoding="utf-8").replace(
            "ruff format --check pkg/ tests/ scripts/\n", ""
        ),
        encoding="utf-8",
    )
    _, verify_errors = guard.evaluate(verify_root)
    assert any(
        e.startswith("AGENTS.md:") and "canonical verification command drift (format)" in e
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
        "release_admission",
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
        _OFFLINE_USAGE_DISCLOSURE.replace(
            "English Wikipedia REST API", "English Wikipedia\nREST API"
        ),
        encoding="utf-8",
    )

    _, errors = guard.evaluate(root)

    assert errors == []


@pytest.mark.parametrize("marker", guard.OFFLINE_USAGE_DISCLOSURE_MARKERS)
def test_offline_usage_missing_disclosure_fails_with_useful_diagnostic(tmp_path: Path, marker: str):
    root = _make_repo(tmp_path / "offline-usage-no-disclosure")
    path = root / "docs" / "OFFLINE_USAGE.md"
    path.write_text(_OFFLINE_USAGE_DISCLOSURE.replace(marker, "removed"), encoding="utf-8")

    _, errors = guard.evaluate(root)

    assert any(
        error.startswith("docs/OFFLINE_USAGE.md:") and marker in error for error in errors
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


# ── Agent install: update-choice sequence, notification defaults, scheduler gating
# ── (AC-1 through AC-6, VER-1 through VER-4) ─────────────────────────────────


def test_agent_install_update_choice_sequence():
    """AC-1/VER-1: AGENT_INSTALL.md has a numbered decision sequence with separate
    notification and scheduled-update choices; notifications are described as PyPI
    metadata only (no package installation).
    """
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    # Notification choice step must exist
    assert "version-check --enable" in text, "AGENT_INSTALL.md: missing version-check --enable"
    assert "version-check --disable" in text, "AGENT_INSTALL.md: missing version-check --disable"
    # Scheduler choice step must exist separately
    assert "update scheduler install --yes" in text, (
        "AGENT_INSTALL.md: missing update scheduler install --yes"
    )
    # Must state notifications are package-metadata-only
    assert "package metadata only" in text.lower() or "metadata only" in text.lower(), (
        "AGENT_INSTALL.md: must state that notifications inspect PyPI metadata only, "
        "not package installation"
    )
    assert "does not install packages" in text, (
        "AGENT_INSTALL.md: must state that notifications do not install packages"
    )


def test_agent_install_notification_choice_records_safe_defaults():
    """AC-2/VER-2: Affirmative → version-check --enable; negative/empty/EOF/unclear
    → version-check --disable (safe No path).
    """
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    assert "version-check --enable" in text
    assert "version-check --disable" in text
    # The --disable path must be associated with safe-default language:
    # find the --disable occurrence and check surrounding context mentions
    # negative/empty/EOF/unclear answers.
    disable_idx = text.find("version-check --disable")
    assert disable_idx != -1
    # Look at the 800 chars before the first --disable occurrence for safe-default cues.
    context = text[max(0, disable_idx - 800) : disable_idx + 300].lower()
    assert any(word in context for word in ("no", "empty", "eof", "unclear", "safe", "negative")), (
        "AGENT_INSTALL.md: the version-check --disable path must appear near language "
        "describing negative, empty, EOF, or unclear answers as the safe default"
    )


def test_agent_install_scheduler_choice_is_readonly_gated():
    """AC-3/VER-3: Scheduler question is gated behind read-only eligibility checks
    (OS=Linux, systemd-user available, update status --json shows supported installer
    and scheduler); affirmative path renders units, installs with --yes, verifies status.
    """
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    # Must have OS check for Linux
    assert "linux" in text.lower() or "Linux" in text, (
        "AGENT_INSTALL.md: must document OS=Linux check before scheduler choice"
    )
    # Must reference systemd-user check
    assert "systemd" in text, "AGENT_INSTALL.md: must document systemd-user check"
    # Must reference update status --json for installer/scheduler-support check
    assert "update status --json" in text, (
        "AGENT_INSTALL.md: must run 'update status --json' as read-only preflight "
        "before the scheduler question"
    )
    # Affirmative path: render → install --yes → status (in document order)
    render_idx = text.find("update scheduler render")
    install_idx = text.find("update scheduler install --yes")
    status_idx = text.find("update scheduler status")
    assert render_idx != -1, "AGENT_INSTALL.md: missing 'update scheduler render'"
    assert install_idx != -1, "AGENT_INSTALL.md: missing 'update scheduler install --yes'"
    assert status_idx != -1, "AGENT_INSTALL.md: missing 'update scheduler status'"
    assert render_idx < install_idx, (
        "AGENT_INSTALL.md: scheduler render must appear before scheduler install --yes"
    )
    assert install_idx < status_idx, (
        "AGENT_INSTALL.md: scheduler install --yes must appear before scheduler status"
    )


def test_agent_install_unsupported_update_outcomes_are_manual_only():
    """AC-4/VER-3: macOS, Windows, unavailable systemd-user, and unsupported installers
    produce a manual-update-only outcome (update status + update apply --yes) without
    a scheduler prompt or fallback mutation.
    """
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    # Must name macOS as unsupported for scheduled updates
    assert "macOS" in text, (
        "AGENT_INSTALL.md: must mention macOS as unsupported for scheduled updates"
    )
    # Must provide manual update commands for unsupported paths
    assert "update status" in text, (
        "AGENT_INSTALL.md: must document 'update status' as manual option"
    )
    assert "update apply --yes" in text, (
        "AGENT_INSTALL.md: must document 'update apply --yes' as manual option"
    )
    # Must state that unsupported paths skip to the next step (no mutation)
    assert "skip to Step 6.6" in text or "skip" in text.lower(), (
        "AGENT_INSTALL.md: unsupported paths must skip scheduler prompt without mutation"
    )


def test_agent_install_uses_installed_executable_verification():
    """AC-5/VER-4: Post-install verification uses the installed executable and
    version-check --status, not ambient system python3 to import mempalace_code.
    """
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    # Must use executable-based checks
    assert "command -v mempalace-code" in text, (
        "AGENT_INSTALL.md: post-install verification must use 'command -v mempalace-code'"
    )
    assert "version-check --status" in text, (
        "AGENT_INSTALL.md: post-install verification must use 'version-check --status'"
    )
    assert "update status --json" in text, (
        "AGENT_INSTALL.md: post-install verification must use 'update status --json'"
    )


def test_agent_install_final_report_fields():
    """AC-6/VER-4: Final install report always includes installed version, notification
    state, updater installer/support result, scheduler supported/enabled state, and
    exact commands for later opt-in changes.
    """
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    # Installed version field
    assert "Installed version" in text or "MEMPALACE_VERSION" in text, (
        "AGENT_INSTALL.md: final report must include installed version"
    )
    # Notification enabled/disabled state and later-change commands
    assert "Notification" in text, "AGENT_INSTALL.md: final report must include notification state"
    assert "version-check --enable" in text
    assert "version-check --disable" in text
    # Updater installer/support result
    assert "installer" in text.lower() or "Updater" in text, (
        "AGENT_INSTALL.md: final report must include updater installer/support"
    )
    # Scheduler supported/enabled state and later-change command
    assert "scheduler" in text.lower(), (
        "AGENT_INSTALL.md: final report must include scheduler state"
    )
    assert "update scheduler install --yes" in text


# ── VER-8: docs and CLI hint command alignment ────────────────────────────────


def test_update_docs_and_cli_hint_commands_stay_aligned():
    """VER-8: The drift guard fails if README, AGENT_INSTALL, UPDATES, CLI help,
    or version-check hints lose the guarded update-command alignment.
    No first-party hint must recommend raw 'pip install --upgrade mempalace-code'.
    """
    # version_check.py: guarded commands, no raw pip upgrade
    vc_text = (ROOT / "mempalace_code" / "version_check.py").read_text(encoding="utf-8")
    assert "pip install --upgrade mempalace-code" not in vc_text, (
        "mempalace_code/version_check.py: stale raw pip upgrade hint still present in hint text; "
        "use 'mempalace-code update status' and 'mempalace-code update apply --yes' instead"
    )
    assert "update status" in vc_text, (
        "mempalace_code/version_check.py: guarded 'update status' command missing from hint text"
    )
    assert "update apply --yes" in vc_text, (
        "mempalace_code/version_check.py: guarded 'update apply --yes' command missing from hint text"
    )

    # AGENT_INSTALL.md: guarded update commands present
    agent_install = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    assert "update status" in agent_install, (
        "docs/AGENT_INSTALL.md: missing 'update status' command"
    )
    assert "update apply --yes" in agent_install, (
        "docs/AGENT_INSTALL.md: missing 'update apply --yes' command"
    )

    # README.md: guarded update commands present
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "update apply --yes" in readme, (
        "README.md: missing 'update apply --yes' command reference"
    )

    # docs/UPDATES.md: guarded update commands present
    updates = (ROOT / "docs" / "UPDATES.md").read_text(encoding="utf-8")
    assert "update apply --yes" in updates, (
        "docs/UPDATES.md: missing 'update apply --yes' command reference"
    )


# ── Agent instruction loading boundary ───────────────────────────────


def _agent_install_section7() -> str:
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    start = text.find("## Section 7")
    end = text.find("\n## End State", start)
    assert start >= 0
    assert end > start
    return text[start:end]


def test_agent_install_instruction_setup_uses_plugin_only():
    """AC-1/VER-1: public instruction setup is read-only Agent Plugin discovery."""
    section = _agent_install_section7()
    assert "Agent Plugins 1.0" in section
    assert section.count(guard.AGENT_PLUGIN_RECOVERY_COMMAND) == 1
    assert "read-only" in section
    assert "CLAUDE.md" not in section
    assert "AGENTS.md" not in section
    for verb in ("write", "paste", "insert", "replace", "restore", "append", "inject", "mutate"):
        assert verb not in section.lower()
    assert guard.agent_instruction_mutation_errors(section, "docs/AGENT_INSTALL.md") == []


def test_agent_instruction_unsafe_states_share_fail_closed_recovery():
    """AC-2/VER-2: every stale, skipped, retry, and partial state stops identically."""
    section = _agent_install_section7()
    section_lower = section.lower()
    for state in (
        "default",
        "skipped",
        "legacy",
        "malformed",
        "missing",
        "wrong target",
        "symlinked target or parent",
        "duplicate retry",
        "partial prior execution",
    ):
        assert state in section_lower
    assert "same result: no instruction-file operation" in section_lower
    assert section.count(guard.AGENT_PLUGIN_RECOVERY_COMMAND) == 1


def test_agent_install_defers_instruction_file_apply_contract():
    """AC-3/VER-3: no partial filesystem transaction promise remains."""
    install = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    rules = (ROOT / "docs" / "LLM_USAGE_RULES.md").read_text(encoding="utf-8")
    install_section = _agent_install_section7().lower()
    rules_preface = rules.split("<!-- mempalace-rules:start -->", 1)[0].lower()
    for unsupported_contract in (
        "atomic replace",
        "backup identity",
        "chmod",
        "directory fsync",
        "mode preservation",
        "poststate",
        "restore protocol",
    ):
        assert unsupported_contract not in install_section
        assert unsupported_contract not in rules_preface
    assert "repeated discovery\nis read-only" in install.lower()
    assert guard.agent_instruction_mutation_errors(rules_preface, "rules") == []


def _write_instruction_boundary_fixture(root: Path) -> tuple[str, str]:
    rules = (
        "Canonical reference.\n\n"
        "<!-- mempalace-rules:start -->\n"
        "# mempalace-code — Usage Rules\n\n"
        "## Mental model\n\n"
        "## Never\n"
        "<!-- mempalace-rules:end -->\n"
    )
    install = (
        "## Section 7 — Agent Instruction Loading (Agent Plugin Only)\n\n"
        "Agent Plugins 1.0 clients use this read-only check.\n\n"
        "mempalace-code agent-plugin path --json\n\n"
        "Instruction files stay unchanged.\n\n"
        "## End State\n"
    )
    _write(root / "docs" / "LLM_USAGE_RULES.md", rules)
    _write(root / "docs" / "AGENT_INSTALL.md", install)
    _write(
        root / "mempalace_code" / "agent_plugin" / "skills" / "mempalace" / "SKILL.md",
        "# Concise skill\n",
    )
    return rules, install


def test_agent_rules_have_one_canonical_source_across_release_shape(tmp_path: Path):
    """AC-4/VER-4: arbitrary documentation and package copies are rejected."""
    rules, install = _write_instruction_boundary_fixture(tmp_path)
    assert guard.agent_instruction_boundary_errors(tmp_path, rules, install) == []

    canonical_body = guard._canonical_rules_block(rules)
    assert canonical_body is not None
    _, body = canonical_body
    cases = (
        ("docs/unexpected-name.md", "<!-- mempalace-rules:start -->\norphan\n"),
        ("docs/reference-copy.md", body),
        ("mempalace_code/agent_plugin/notes.dat", body),
    )
    for relative_path, duplicate in cases:
        case_root = tmp_path / relative_path.replace("/", "-")
        case_rules, case_install = _write_instruction_boundary_fixture(case_root)
        _write(case_root / relative_path, duplicate)
        errors = guard.agent_instruction_boundary_errors(case_root, case_rules, case_install)
        assert any(relative_path in error and "duplicate or orphan" in error for error in errors)

    live_rules = (ROOT / "docs" / "LLM_USAGE_RULES.md").read_text(encoding="utf-8")
    live_install = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    assert guard.agent_instruction_boundary_errors(ROOT, live_rules, live_install) == []

    for malformed in (
        "No managed markers here.\n",
        "<!-- mempalace-rules:end -->\nbody\n<!-- mempalace-rules:start -->\n",
    ):
        errors = guard.agent_instruction_boundary_errors(tmp_path, malformed, install)
        assert len(errors) == 1
        assert "exactly one ordered line-anchored" in errors[0]

    missing_section = guard.agent_instruction_boundary_errors(tmp_path, rules, "no section")
    assert any("instruction-loading section is missing" in error for error in missing_section)

    missing_package_root = tmp_path / "missing-package"
    missing_package = guard.agent_instruction_boundary_errors(missing_package_root, rules, install)
    assert any("packaged Agent Plugin directory is missing" in error for error in missing_package)


def test_agent_instruction_mutation_failure_classes_are_rejected():
    """AC-5/VER-5: named unsafe apply and recovery classes share one diagnostic."""
    unsafe_guidance = {
        "wrong target": "Write the rules to CLAUDE.md even when the selected target differs.",
        "substituted backup": "Copy AGENTS.md to a backup, then restore it after failure.",
        "changed mode": "Change mode on the instruction file after installing the rules.",
        "symlink parent": "Follow the symlink parent before writing CLAUDE.md.",
        "post-replace failure": "After replace failure, restore the instruction file.",
        "repeated apply": "Retry by writing AGENTS.md again after an ambiguous apply.",
    }
    for failure_class, text in unsafe_guidance.items():
        errors = guard.agent_instruction_mutation_errors(text, failure_class)
        assert len(errors) == 1
        assert "unsupported instruction-file mutation route" in errors[0]
        assert guard.AGENT_PLUGIN_RECOVERY_COMMAND in errors[0]


def test_agent_instruction_mutation_action_verbs_and_postposed_negation():
    unsafe_guidance = (
        "Update CLAUDE.md with the rules.",
        "Configure CLAUDE.md for the agent.",
        "Place the rules in CLAUDE.md.",
        "Manage CLAUDE.md when installing.",
        "Sync mempalace usage rules to AGENTS.md.",
        "Load the matching profile block into .cursorrules.",
        "Embed these instructions in the system prompt.",
        "Set the agent instructions from docs/LLM_USAGE_RULES.md.",
    )
    for guidance in unsafe_guidance:
        errors = guard.agent_instruction_mutation_errors(guidance, "docs/setup.md")
        assert len(errors) == 1
        assert "unsupported instruction-file mutation route" in errors[0]

    assert (
        guard.agent_instruction_mutation_errors(
            "Change the MCP profile, not CLAUDE.md.", "docs/setup.md"
        )
        == []
    )

    safe_guidance = (
        "CLAUDE.md should not be changed.",
        "The installer will not update CLAUDE.md.",
        "The installer can not update CLAUDE.md.",
        "The installer cannot update CLAUDE.md.",
        "The installer can configure the MCP server; CLAUDE.md is a reference only.",
        "Previously, the installer changed CLAUDE.md.",
    )
    for guidance in safe_guidance:
        assert guard.agent_instruction_mutation_errors(guidance, "docs/setup.md") == []

    assert guard.agent_instruction_mutation_errors(
        "The installer changed CLAUDE.md previously.", "docs/setup.md"
    )


def test_agent_instruction_mutation_guidance_is_rejected_in_renamed_public_docs(
    tmp_path: Path,
):
    """AC-5/VER-5: filename changes cannot bypass stale public setup guidance."""
    stale_guidance = {
        "copy-rules.md": "Copy usage rules from docs/LLM_USAGE_RULES.md.",
        "gemini-setup-renamed.md": "Add the canonical usage rules to GEMINI.md.",
        "cursor-setup-renamed.md": "Paste the matching profile block into .cursorrules.",
        "prompt-setup-renamed.md": "Inject these rules into the system prompt.",
        "generic-setup-renamed.md": "Add mempalace usage rules to agent instructions.",
        "runbook-summary-renamed.md": (
            "The install runbook covers MCP wiring, instruction injection, and verification."
        ),
    }
    for filename, guidance in stale_guidance.items():
        case_root = tmp_path / filename
        rules, install = _write_instruction_boundary_fixture(case_root)
        relative = f"guides/{filename}"
        _write(case_root / relative, guidance)

        errors = guard.agent_instruction_boundary_errors(case_root, rules, install)

        assert any(
            relative in error and "unsupported instruction-file mutation route" in error
            for error in errors
        )

    git_root = tmp_path / "git-release-shape"
    rules, install = _write_instruction_boundary_fixture(git_root)
    _write(git_root / ".gitignore", "docs/audits/\n")
    subprocess.run(["git", "init", "-q"], cwd=git_root, check=True)
    subprocess.run(["git", "add", "."], cwd=git_root, check=True)

    unsafe_guidance = "Add mempalace usage rules to agent instructions."
    ignored_path = "docs/audits/local-review.md"
    tracked_path = "guides/public-setup.md"
    _write(git_root / ignored_path, unsafe_guidance)
    _write(git_root / tracked_path, unsafe_guidance)
    subprocess.run(["git", "add", tracked_path], cwd=git_root, check=True)

    errors = guard.agent_instruction_boundary_errors(git_root, rules, install)

    assert any(
        tracked_path in error and "unsupported instruction-file mutation route" in error
        for error in errors
    )
    assert all(ignored_path not in error for error in errors)


def test_agent_instruction_boundary_allows_prohibitions_references_and_history(
    tmp_path: Path,
):
    """AC-5/VER-5: prohibitions, read-only references, and history stay public."""
    rules, install = _write_instruction_boundary_fixture(tmp_path)
    safe_docs = {
        "docs/unsupported-client.md": (
            "Do not copy usage rules into AGENTS.md. Instruction-file mutation is unsupported. "
            "Use docs/LLM_USAGE_RULES.md only as read-only reference material."
        ),
        "docs/authority-reference.md": (
            "CLAUDE.md is a public authority file. Keep it public-safe."
        ),
        "CHANGELOG.md": (
            "Historically, users copied usage rules into agent instructions before Agent Plugins."
        ),
        "docs/plans/old-instruction-loader.md": (
            "The reviewed plan previously directed users to paste usage rules into AGENTS.md."
        ),
    }
    for relative, content in safe_docs.items():
        _write(tmp_path / relative, content)

    assert guard.agent_instruction_boundary_errors(tmp_path, rules, install) == []


def test_llm_usage_rules_has_ambiguous_write_outcome_protocol():
    """The unchanged canonical rules retain their ambiguous MCP-write protocol."""
    text = (ROOT / "docs" / "LLM_USAGE_RULES.md").read_text(encoding="utf-8").lower()
    assert "ambiguous write outcome" in text
    assert "timeout" in text or "context loss" in text
    assert "search" in text or "reconcile" in text


def test_direct_cli_recovery_contracts_stay_synchronised():
    """Direct diary and update recovery guidance stays aligned across public owners."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    updates = (ROOT / "docs" / "UPDATES.md").read_text(encoding="utf-8")
    rules = (ROOT / "docs" / "LLM_USAGE_RULES.md").read_text(encoding="utf-8")
    rules_single_line = " ".join(rules.split())

    for text in (readme, rules):
        text_single_line = " ".join(text.split()).lower()
        for marker in (
            "Diary entry stored.",
            "`ID`",
            "`Wing`",
            "`Room`",
            "`Topic`",
            "`Verify before retry`",
            "printed search",
            "exact hit means success",
            "do not repeat the write",
            "response or printed command is unavailable",
            "do not retry",
            "mempalace_diary_read",
            "owner reconciliation",
        ):
            assert marker.lower() in text_single_line

    for text in (readme, updates, rules):
        for marker in (
            "`update apply`",
            "`update scheduler install`",
            "`update scheduler remove`",
            "exits 2 before mutation",
            "`Recovery: <command>`",
            "`recovery_command`",
            "mutation authority",
        ):
            assert marker in text

    for marker in (
        "exactly one parseable JSON object",
        "`ok: false`",
        "`stage: confirmation`",
        "`exit_code: 2`",
        "`--yes --json`",
    ):
        assert marker in updates

    assert "## Direct CLI recovery" in rules
    assert "do not invent a retry" in rules_single_line
    assert "Do not add flags, change the action, or invent a nearby retry." in rules_single_line
    assert "## Ambiguous Write Outcome" in rules
    assert "mempalace_add_drawer" in rules
    assert "mempalace_kg_add" in rules
    assert "mempalace_diary_write" in rules


def test_releasing_uses_all_installer_recovery_smoke_contract():
    text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")

    assert (
        "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json"
    ) in text
    assert all(name in text for name in ("venv", "bootstrap-venv", "pipx", "uv-tool"))
    assert "three update confirmation refusals" in text
    assert "interpreter-site socket guard" in text
    assert "python -m pip install pipx" in text
    assert "python -m pip install uv" in text


def test_releasing_names_exact_wheel_installed_golden_cache_and_provenance_contract():
    text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    command = 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'

    assert text.count(command) == 3
    assert "`watch` extra" in text
    assert 'HF_HOME="$MEMPALACE_TEST_HF_HOME" mempalace-code fetch-model' in text
    assert "mempalace-fastembed/all-MiniLM-L6-v2-v1/.mempalace-model.json" in text
    assert "interpreter-site\nsocket guard" in text
    assert "neutral cwd" in text
    assert "outside the checkout and ambient PATH" in text
    assert "manager matrix" in text


def test_custom_models_linux_cpu_install_and_recovery_authority_contract():
    offline = (ROOT / "docs" / "OFFLINE_USAGE.md").read_text(encoding="utf-8")
    agent = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    releasing = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    mkdir = 'install -d -m 700 "$HOME/.cache/mempalace/tmp"'
    free_space = 'df -h "$HOME/.cache/mempalace/tmp"'
    cpu_install = (
        'TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install torch '
        "--index-url https://download.pytorch.org/whl/cpu"
    )
    extra_install = (
        'TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install '
        "'mempalace-code[custom-models]'"
    )
    recovery = (
        'TMPDIR="$HOME/.cache/mempalace/tmp" python scripts/release_readiness_gate.py '
        '--installed-golden-wheel "$WHEEL" --json'
    )

    assert all(token in offline for token in (mkdir, free_space, cpu_install, extra_install))
    assert offline.index(mkdir) < offline.index(free_space) < offline.index(cpu_install)
    assert offline.index(cpu_install) < offline.index(extra_install)
    assert offline.count(cpu_install) == 2
    assert offline.count(extra_install) == 2
    assert "from any\ndirectory" in offline
    assert "incomplete" in offline

    for user_surface in (offline, agent, readme, agents):
        assert "scripts/release_readiness_gate.py" not in user_surface
        assert '"$WHEEL"' not in user_surface

    assert "ask for authority" in agent
    assert "docs/OFFLINE_USAGE.md" in agent
    assert cpu_install not in agent
    assert extra_install not in agent

    for entry_point in (readme, agents):
        assert "docs/OFFLINE_USAGE.md" in entry_point
        assert cpu_install not in entry_point
        assert extra_install not in entry_point

    assert "mempalace-code[custom-models]" in readme
    optional_extras = readme.split("**Optional extras:**", 1)[1].split("```", 2)[1]
    assert "docs/OFFLINE_USAGE.md" in optional_extras
    custom_model_rows = [
        line for line in optional_extras.splitlines() if "mempalace-code[custom-models]" in line
    ]
    assert len(custom_model_rows) == 1
    assert custom_model_rows[0].lstrip().startswith("#")

    assert all(token in releasing for token in (mkdir, free_space, cpu_install, extra_install))
    assert releasing.index(mkdir) < releasing.index(free_space) < releasing.index(cpu_install)
    assert releasing.index(cpu_install) < releasing.index(extra_install)
    assert releasing.count(recovery) == 1
    assert "adequate free space" in releasing


def test_releasing_agent_plugin_locator_is_machine_readable():
    text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    command = f"`{guard.AGENT_PLUGIN_RECOVERY_COMMAND}`"
    assert text.count(command) == 2
    for suffix in text.split(command)[1:]:
        assert re.search(r"\bparses the\s+JSON\s+`path` field", suffix[:100])


# --- Public release shape (REL-V1-13-5-PUBLIC-SHAPE-PREP) -----------------------

CHANGELOG_HEAD = """# Changelog

## Unreleased

## v1.13.5 — 2026-08-15

Patch release summary.

## 2026-04-01 · OLD-TASK-KEY

Published history from before per-release consolidation.
"""


def test_changelog_shape_accepts_one_release_header_and_legacy_history():
    assert guard.changelog_shape_errors(CHANGELOG_HEAD) == []


def test_changelog_shape_rejects_per_task_headers_above_the_release_header():
    text = CHANGELOG_HEAD.replace(
        "## Unreleased",
        "## 2026-08-15 · INSTALL-ALIAS-TARGET-CONTAINMENT\n\nHonor the target.\n\n## Unreleased",
    )
    errors = guard.changelog_shape_errors(text)
    assert len(errors) == 1
    assert "INSTALL-ALIAS-TARGET-CONTAINMENT" in errors[0]
    assert "consolidated" in errors[0]


def test_changelog_shape_rejects_duplicate_release_headers():
    text = CHANGELOG_HEAD + "\n## v1.13.5 — 2026-08-16\n\nSecond header.\n"
    errors = guard.changelog_shape_errors(text)
    assert any("duplicate release headers for 1.13.5" in e for e in errors)


def test_release_promotion_accepts_the_candidate_branch_flow():
    assert guard.release_promotion_errors({"docs/RELEASING.md": _PROMOTION_FLOW}) == []


def test_release_promotion_rejects_pushing_local_main_to_publish():
    text = _PROMOTION_FLOW + "\ngit push publish main\n"
    errors = guard.release_promotion_errors({"docs/RELEASING.md": text})
    assert len(errors) == 1
    assert "not fast-forwardable" in errors[0]
    assert errors[0].startswith("docs/RELEASING.md:")


def test_release_promotion_requires_every_candidate_flow_marker():
    errors = guard.release_promotion_errors({"docs/RELEASING.md": "just tag it\n"})
    assert len(errors) == len(guard._PROMOTION_MARKERS)
    assert all(e.startswith("docs/RELEASING.md: missing") for e in errors)
    for marker in guard._PROMOTION_MARKERS:
        assert any(repr(marker) in e for e in errors), marker


@pytest.mark.parametrize("marker", guard._PROMOTION_MARKERS)
def test_release_promotion_reports_each_missing_marker_on_its_own(marker: str):
    """Dropping any single step of the sequence is reported, not just the first."""
    errors = guard.release_promotion_errors(
        {"docs/RELEASING.md": _PROMOTION_FLOW.replace(marker, "<elided>")}
    )
    assert [e for e in errors if repr(marker) in e], errors


def test_release_promotion_requires_pushing_the_candidate_branch_before_main():
    """Fast-forwarding a SHA onto `main` is only safe once that SHA is green.

    The branch push is what gives the candidate its own Tests and
    `release-required` results, so a sequence that goes straight to `main` is
    missing the step that keeps promotion working under required checks.
    """
    straight_to_main = _PROMOTION_FLOW.replace('git push publish "$CANDIDATE_BRANCH"\n', "")
    errors = guard.release_promotion_errors({"docs/RELEASING.md": straight_to_main})
    assert any('git push publish "$CANDIDATE_BRANCH"' in e for e in errors)


def test_release_promotion_requires_an_immutable_retry_branch_name():
    """A rebuilt candidate is a different commit, so it needs a different branch.

    Without the `-rcN` convention the only way to re-push a fixed candidate is a
    force-update of a branch the previous attempt already published.
    """
    no_retry_name = _PROMOTION_FLOW.replace("   # a rebuild uses release/vX.Y.Z-rc2, then -rc3", "")
    errors = guard.release_promotion_errors({"docs/RELEASING.md": no_retry_name})
    assert any("release/vX.Y.Z-rc2" in e for e in errors)


def test_release_promotion_checks_force_safety_without_requiring_publication():
    """A handoff surface is held to force-push safety, not to the promotion flow.

    Release-prep must never publish, so requiring the flow markers there would
    push publication commands into a doc whose whole contract is not to run them
    — while `--force` guidance in it is exactly as dangerous as anywhere else.
    """
    handoff = "Hand off to /release; never --force and never rewrite public history.\n"
    assert (
        guard.release_promotion_errors(
            {".claude/skills/release-prep/SKILL.md": handoff},
            require_promotion_flow=False,
        )
        == []
    )

    unsafe = "Resolve the rejected push with --force.\n"
    errors = guard.release_promotion_errors(
        {".claude/skills/release-prep/SKILL.md": unsafe}, require_promotion_flow=False
    )
    assert len(errors) == 1
    assert "has no prohibition within" in errors[0]


def test_release_promotion_rejects_force_push_without_a_nearby_prohibition():
    text = _PROMOTION_FLOW.replace("never --force", "use --force if needed")
    errors = guard.release_promotion_errors({"docs/RELEASING.md": text})
    assert any("has no prohibition within" in e for e in errors)


def test_release_promotion_rejects_a_prohibition_too_far_from_the_flag():
    """A `never --force` in some other section does not govern this mention."""
    text = _PROMOTION_FLOW.replace("; never --force", "")
    text += "Resolve the rejected push with --force.\n"
    text += "filler line\n" * 60
    text += "Never use --force on public main.\n"
    errors = guard.release_promotion_errors({"docs/RELEASING.md": text})
    assert len(errors) == 1
    assert "has no prohibition within" in errors[0]


@pytest.mark.parametrize(
    "prohibition",
    [
        "never `--force`",
        "**never** use `--force`",
        "_never rewrite_ history",
    ],
)
def test_release_promotion_reads_through_markdown_emphasis(prohibition: str):
    """Backticks and bold must not hide a prohibition that a reader plainly sees."""
    text = _PROMOTION_FLOW.replace("never --force", prohibition)
    assert guard.release_promotion_errors({"docs/RELEASING.md": text}) == []


def test_release_promotion_reads_a_prohibition_wrapped_across_lines():
    text = _PROMOTION_FLOW.replace("; never --force", "\nNever use\n--force here.\n")
    assert guard.release_promotion_errors({"docs/RELEASING.md": text}) == []


def test_release_promotion_rejects_a_flag_split_across_lines():
    text = _PROMOTION_FLOW.replace("--candidate-ref", "--candidate-\nref")
    errors = guard.release_promotion_errors({"docs/RELEASING.md": text})
    assert any("split across lines" in e for e in errors)


def test_tracked_release_runbook_carries_the_fast_forward_only_flow():
    """The shipped runbook, not just a fixture, describes the executable promotion."""
    path = "docs/RELEASING.md"
    assert guard.release_promotion_errors({path: (ROOT / path).read_text(encoding="utf-8")}) == []


def test_the_shipped_release_doc_proves_the_candidate_green_before_moving_main():
    """Ordering the guard cannot express as a marker set, so assert it directly.

    Every marker can be present in the wrong order. The branch push must come
    first, and `release-required` must be required between it and the
    fast-forward, or the candidate reaches `main` without its own green checks.
    """
    text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    branch_push = text.index('git push publish "$CANDIDATE_BRANCH"')
    main_push = text.index('git push publish "$CANDIDATE_SHA":refs/heads/main')
    assert branch_push < main_push
    assert text.index("release-required", branch_push) < main_push


def test_the_shipped_release_runbook_gates_candidate_branch_deletion_on_approval():
    """Deleting the candidate branch is its own external mutation.

    The canonical runbook names the deletion command and requires separate
    approval, so it cannot ride along on an earlier mutation approval.
    """
    text = (ROOT / "docs/RELEASING.md").read_text(encoding="utf-8")
    delete = text.index('git push publish --delete "$CANDIDATE_BRANCH"')
    window = text[max(0, delete - 1200) : delete]
    assert "approval" in window.lower()
    assert text.index('git push publish "$CANDIDATE_SHA":refs/heads/main') < delete


def test_the_release_prep_skill_is_force_safe_without_carrying_publication():
    """Release-prep gets the safety half of the promotion contract, not the flow."""
    path = ".claude/skills/release-prep/SKILL.md"
    text = (ROOT / path).read_text(encoding="utf-8")
    assert guard.release_promotion_errors({path: text}, require_promotion_flow=False) == []

    # It hands off; it must not be the thing that publishes.
    assert "--force" in text, f"{path}: no force-push guidance to hold safe"
    assert 'git push publish "$CANDIDATE_BRANCH"' not in text, f"{path}: must not publish"


def test_agent_install_declined_or_offline_model_choice():
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    init_line = '"$MEMPALACE_BIN" init "<MINE_PATH>" --skip-model-download'

    assert init_line in text
    assert "`no` → Set `DOWNLOAD_MODEL=no`" in text
    assert "`offline` → Set `DOWNLOAD_MODEL=no`" in text
    assert (
        text.count('Print exactly one later recovery\ncommand: `"$MEMPALACE_BIN" fetch-model`') == 1
    )
    mine_section = text[text.index("### Step 4d") : text.index("## Section 5")]
    search_section = text[text.index("### Step 6.2") : text.index("### Step 6.3")]
    assert "MODEL_READY=false" in mine_section
    assert "MODEL_READY=false" in search_section


def test_agent_install_selected_method_is_consistent():
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")

    for method in ("uv", "pipx", "project", "bootstrap"):
        assert f"`INSTALL_METHOD={method}`" in text
    assert "Each value is terminal" in text
    assert "never fall through to another installer" in text
    assert 'MEMPALACE_MCP="$(dirname "$MEMPALACE_BIN")/mempalace-code-mcp"' in text


def test_agent_install_client_scope_contract():
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")

    assert "If `MCP_CLIENTS=claude|both`, require `CLAUDE_SCOPE=user|project`." in text
    assert "If `MCP_CLIENTS=codex|skip`, do not require or set `CLAUDE_SCOPE`." in text
    assert "If `CLAUDE_SCOPE=project`, also require an existing absolute" in text
    assert "claude mcp add --scope user" in text
    assert "claude mcp add --scope project" in text
    assert 'codex mcp add mempalace-code -- "$MEMPALACE_MCP"' in text
    assert "MCP_SCOPE" not in text
    assert "`CLAUDE_SCOPE=user`" in text
    assert "`CLAUDE_SCOPE=project`" in text
    assert "user scope writes `~/.claude.json`" in text
    assert "project scope writes `<project>/.mcp.json`" in text
    assert "project-scoped `.codex/config.toml`" in text
    scopes = re.findall(r"^#### 5\.1-[AB]: .*?`CLAUDE_SCOPE=(user|project)`", text, re.MULTILINE)
    assert scopes == ["user", "project"]


def test_agent_install_notification_precedes_prompting_commands():
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")

    disable = text.index('"$MEMPALACE_BIN" version-check --disable')
    init = text.index('"$MEMPALACE_BIN" init "<MINE_PATH>"')
    assert disable < init
    assert "Empty, EOF, malformed, or contradictory input means `no`" in text


def test_agent_install_scheduler_default_and_final_state():
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")

    assert "Scheduled package updates are a **separate**" in text
    assert "or `no` (default)" in text
    step = text[text.index("### Step 6.5") : text.index("### Step 6.6")]
    assert "daily systemd-user timer" in step
    assert "once per day" in step
    assert "weekly systemd-user timer" not in step
    for label in ("Installer:", "Notification checks:", "Scheduler support:", "Scheduler enabled:"):
        assert label in text


def test_agent_install_remote_bootstrap_is_explicit_and_bounded():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agent_install = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")

    predicate = '[[ "${BOOTSTRAP_REF:-}" =~ ^[0-9a-fA-F]{40}$ ]]'
    assert predicate in readme
    assert readme.index(predicate) < readme.index("curl -fL")
    assert '[[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]' in agent_install
    for text in (readme, agent_install):
        assert "immutable release tag" not in text
        assert "immutable vX.Y.Z" not in text
        assert "/tmp/mempalace-bootstrap.sh" not in text
        assert not re.search(r"curl[^\n]*\|[^\n]*bash", text)
        assert "trap - EXIT" not in text

    assert "`INSTALL_METHOD=bootstrap`" in agent_install
    assert "download a named file" in agent_install
    assert "`direct` (explicit convenience choice)" in agent_install
    assert agent_install.count('BOOTSTRAP_VENV="${MEMPALACE_VENV:-$HOME/.mempalace/venv}"') == 2
    assert readme.count('BOOTSTRAP_FILE="$(mktemp -t mempalace-bootstrap.XXXXXX)"') == 1
    assert agent_install.count('BOOTSTRAP_FILE="$(mktemp -t mempalace-bootstrap.XXXXXX)"') == 2
    assert readme.count("(\n  trap 'rm -f -- \"$BOOTSTRAP_FILE\"' EXIT") == 1
    assert agent_install.count("  (\n    trap 'rm -f -- \"$BOOTSTRAP_FILE\"' EXIT") == 2
    assert readme.count("trap 'rm -f -- \"$BOOTSTRAP_FILE\"' EXIT") == 1
    assert agent_install.count("trap 'rm -f -- \"$BOOTSTRAP_FILE\"' EXIT") == 2
    assert readme.count(") || exit 1") == 1
    assert (
        agent_install.count('  ) || exit 1\n  MEMPALACE_BIN="$BOOTSTRAP_VENV/bin/mempalace-code"')
        == 2
    )
    assert readme.count('-o "$BOOTSTRAP_FILE" || exit 1') == 1
    assert agent_install.count('-o "$BOOTSTRAP_FILE" || exit 1') == 2
    assert agent_install.count('MEMPALACE_VENV="$BOOTSTRAP_VENV" MEMPALACE_SOURCE=') == 2
    assert agent_install.count('bash "$BOOTSTRAP_FILE" || exit 1') == 2
    assert agent_install.count('MEMPALACE_BIN="$BOOTSTRAP_VENV/bin/mempalace-code"') == 2


def test_install_contract_degraded_context_matrix():
    text = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")

    for degraded in (
        "Empty, EOF, malformed, or contradictory",
        "already-current",
        "do not suggest inspecting or editing multiple files",
        "Print only the command matching `CLAUDE_SCOPE`",
        "separate quoted argv value",
    ):
        assert degraded in text


def test_agent_install_has_only_valid_repair_dry_run_form():
    for path in (ROOT / "README.md", ROOT / "docs" / "AGENT_INSTALL.md"):
        text = path.read_text(encoding="utf-8")
        assert "repair --rollback --dry-run" in text
        assert "repair --dry-run" not in text


def test_tracked_changelog_has_one_release_header_at_the_top():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert guard.changelog_shape_errors(changelog) == []


def test_backup_restore_runbook_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")

    assert guard.backup_restore_contract_errors(readme, runbook) == []
    rebuild = runbook.split("## Recommended Rebuild Workflow", 1)[1].split(
        "## Restore Procedure", 1
    )[0]
    rebuild_lines = [line.strip() for line in rebuild.splitlines()]
    positions = [rebuild_lines.index(marker) for marker in guard.BACKUP_RESTORE_REBUILD_SEQUENCE]
    assert positions == sorted(positions)
    assert rebuild.count('mv "$PALACE" "$QUARANTINE"') == 1
    assert "Only then may you dispose of the" in rebuild
    recovery = runbook.split("### Failure recovery", 1)[1].split("## Restore Procedure", 1)[0]
    recovery_lines = [line.strip() for line in recovery.splitlines()]
    positions = [recovery_lines.index(marker) for marker in guard.BACKUP_RESTORE_RECOVERY_SEQUENCE]
    assert positions == sorted(positions)


def test_backup_restore_guard_rejects_degraded_paths():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")

    export_step, dry_run_step, backup_step, _, quarantine_step, *rest = (
        guard.BACKUP_RESTORE_REBUILD_SEQUENCE
    )
    force_backup = guard.BACKUP_RESTORE_FORCE_SEQUENCE[6]
    force_restore = guard.BACKUP_RESTORE_FORCE_SEQUENCE[8]
    cases = {
        "wrong target": (
            runbook.replace(export_step, export_step.replace("$PALACE", "$OTHER"), 1),
            "expected exactly one recovery step",
        ),
        "missing failed target preservation guard": (
            runbook.replace('if test -e "$PALACE" || test -L "$PALACE"; then\n', "", 1),
            "expected exactly one recovery step",
        ),
        "additive wrong restore target": (
            runbook.replace(
                "### Tarball Restore — KG Destination",
                'mempalace-code --palace "$OTHER" restore "$ARCHIVE"\n\n'
                "### Tarball Restore — KG Destination",
                1,
            ),
            "restore command is not an approved documented form",
        ),
        "missing artifact assertion": (
            runbook.replace(': "${EXPORT_JSONL:?set EXPORT_JSONL to a new JSONL path}"', ":", 1),
            "missing expected text",
        ),
        "duplicate retry": (
            runbook.replace(quarantine_step, f"{quarantine_step}\n{quarantine_step}", 1),
            "expected exactly one recovery step",
        ),
        "reordered verification": (
            runbook.replace(
                f"{export_step}\n{dry_run_step}\n{backup_step}",
                f"{export_step}\n{backup_step}\n{dry_run_step}",
                1,
            ),
            "recovery steps are out of order",
        ),
        "partial execution": (runbook.replace(rest[-1], "", 1), "expected exactly one"),
        "destructive delete": (
            runbook.replace(quarantine_step, 'rm -rf "$PALACE"\n' + quarantine_step, 1),
            "recursive deletion of the active palace is forbidden",
        ),
        "prompt promise": (
            runbook.replace(
                "Without `--force`, the CLI refuses when its checks find state in the selected\n"
                "palace or at the selected KG destination.",
                "Restore prompts before overwrite",
                1,
            ),
            "promises a nonexistent prompt",
        ),
        "missing initial checked-state refusal": (
            runbook.replace(
                "Without `--force`, the CLI refuses when its checks find state in the selected\n"
                "palace or at the selected KG destination.",
                "",
                1,
            ),
            "missing expected text",
        ),
        "unsafe force": (
            runbook.replace(
                f"{force_backup}\n{guard.BACKUP_RESTORE_FORCE_SEQUENCE[7]}\n{force_restore}",
                f"{force_restore}\n{force_backup}\n{guard.BACKUP_RESTORE_FORCE_SEQUENCE[7]}",
                1,
            ),
            "recovery steps are out of order",
        ),
        "missing export output": (
            runbook.replace(' --out "$EXPORT_JSONL"', "", 1),
            "export command is missing required --out",
        ),
        "invalid repair dry run": (
            runbook.replace("repair --rollback --dry-run", "repair --dry-run", 1),
            "repair --dry-run requires --rollback",
        ),
        "early quarantine disposal": (
            runbook.replace(
                "Only then may you dispose of the", "You may immediately dispose of the", 1
            ),
            "missing expected text",
        ),
        "missing publication cleanup": (
            runbook.replace(
                "KG publication failure also removes\nthe Lance root still owned by that invocation",
                "",
                1,
            ),
            "missing expected text",
        ),
        "missing exclusive Lance claim": (
            runbook.replace("claims the exact `lance/` name exclusively", "", 1),
            "missing expected text",
        ),
        "missing atomic KG publication": (
            runbook.replace(
                "creates the exact KG destination with an atomic no-replace hard link", "", 1
            ),
            "missing expected text",
        ),
        "missing raced-name preservation": (
            runbook.replace("If either\nname is raced in, restore preserves it", "", 1),
            "missing expected text",
        ),
        "missing hard-link fail closed": (
            runbook.replace("Unsupported hard links fail\nclosed.", "", 1),
            "missing expected text",
        ),
        "missing concurrent-edit boundary": (
            runbook.replace(
                "does not make arbitrary concurrent edits elsewhere under\n"
                "the palace transactional and does not protect concurrent replacement of the\n"
                "palace root or its ancestors.",
                "",
                1,
            ),
            "missing expected text",
        ),
        "missing atomic force KG replacement": (
            runbook.replace(
                "`--force` replaces the target's managed `lance/` data and atomically replaces the\n"
                "selected KG after archive validation.",
                "",
                1,
            ),
            "inspected force-restore section is missing",
        ),
        "missing unrelated-entry preservation": (
            runbook.replace("preserves unrelated entries in a real\npalace directory", "", 1),
            "missing expected text",
        ),
        "missing symlink protection": (
            runbook.replace(
                "Symlink objects found at the selected palace, Lance, or KG\n"
                "validation boundary are replaced without modifying their referents",
                "",
                1,
            ),
            "missing expected text",
        ),
        "missing external KG backup": (
            runbook.replace("back up that file separately before adding\n`--force`", "", 1),
            "missing expected text",
        ),
    }

    for label, (degraded, expected_error) in cases.items():
        assert degraded != runbook, label
        errors = guard.backup_restore_contract_errors(readme, degraded)
        assert any(expected_error in error for error in errors), (label, errors)

    readme_cases = (
        "tar restore refuses state found at the selected palace or KG during\nits checks",
        "claims the exact `lance/` name exclusively",
        "publishes the KG with\nan atomic no-replace operation",
        "Unsupported no-replace KG publication fails closed.",
        "not a transaction for concurrent replacement of the palace\nroot or its ancestors, or for arbitrary edits elsewhere in the palace.",
        "Back up\nevery reported destination before an intentional `--force` restore",
    )
    for marker in readme_cases:
        degraded_readme = readme.replace(marker, "", 1)
        assert degraded_readme != readme, marker
        errors = guard.backup_restore_contract_errors(degraded_readme, runbook)
        assert any("missing expected text" in error for error in errors), (marker, errors)
