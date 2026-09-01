#!/usr/bin/env python3
"""
quality_scorecard.py — Deterministic, public-safe code-quality scorecard.

Emits a repo-local quality snapshot in Markdown and/or JSON. Every metric is
derived from tracked repository data only (source files, test files, and
``pyproject.toml``). There are no timestamps, no absolute paths, no machine
identifiers, and no network access — two runs against the same tree produce
byte-identical output, which is what makes the scorecard safe for CI validation.

This is the baseline tool for the ``AUTOPILOT DEMO`` backlog section: future
cleanup tasks regenerate the scorecard and report before/after deltas instead of
inventing their own reporting format.

Metrics (all public-safe, repo-local):
    - code size / file counts
    - largest modules
    - Ruff global + per-file ignore counts
    - Pyright mode / strictness status
    - unreasoned suppressions (same policy as tests/test_type_suppressions.py)
    - test count
    - available smoke / CLI / MCP suites
    - current verification commands

Usage:
    python scripts/quality_scorecard.py                 # Markdown to stdout
    python scripts/quality_scorecard.py --format json   # JSON to stdout
    python scripts/quality_scorecard.py --format both    # both, to stdout
    python scripts/quality_scorecard.py --write          # write docs/quality/*
    python scripts/quality_scorecard.py --check          # validate shape (CI)

Stdlib only — no project import, no third-party dependency — so it runs in the
lint CI job and in /verify without installing the package.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import json
import re
import sys
import tokenize
from pathlib import Path

SCHEMA_VERSION = 4
PACKAGE_DIR = "mempalace_code"
TESTS_DIR = "tests"
# Excluded everywhere: negative fixtures intentionally contain bad suppressions
# (see tests/fixtures/unreasoned_suppression.py) and are not real tests.
EXCLUDED_DIRS = ("tests/fixtures",)
# Build artifacts, caches, vendored code, and virtualenv trees are never a source
# of truth — skip them so a stray local build/venv cannot perturb the
# byte-identical output the CI gate depends on.
_SKIP_PARTS = frozenset(
    {"__pycache__", "build", "dist", ".venv", "venv", "site-packages", "node_modules", "vendor"}
)
TOP_MODULES = 10


def _load_gate_inventory():
    path = Path(__file__).with_name("gate_inventory.py")
    spec = importlib.util.spec_from_file_location("_quality_scorecard_gate_inventory", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonical gate inventory from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_GATE_INVENTORY = _load_gate_inventory()

# Suppression policy — kept identical to tests/test_type_suppressions.py so the
# scorecard's "unreasoned" count matches the gate that enforces it.
_SUPPRESSION_RE = re.compile(r"#\s*(?:type|pyright):\s*ignore")
_ACCEPTED_RE = re.compile(r"#\s*(?:type|pyright):\s*ignore\[[^\]\s]+\]\s*#\s*reason:\s*\S")
_NOQA_RE = re.compile(r"#\s*noqa")
_NOQA_BLANKET_RE = re.compile(r"#\s*noqa(?!\s*:)")
# Tolerate a PEP 695 type-parameter list (``def test_x[T](...)``) so the regex
# fallback agrees with the AST count across Python versions.
_TEST_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*[\[(]")

# Known integration / smoke / contract surfaces. Presence is detected by path so
# the scorecard reports which real-workflow suites exist, not just unit count.
_KNOWN_SUITES = (
    ("cli", "tests/test_cli.py", "CLI command tests"),
    ("cli_e2e", "tests/test_e2e.py", "End-to-end CLI workflow tests"),
    ("cli_command_modules", "tests/test_cli_command_modules.py", "CLI command module tests"),
    (
        "cli_golden_scenarios",
        "tests/test_cli_golden_scenarios.py",
        "Subprocess-level golden CLI workflow scenarios",
    ),
    ("mcp_server", "tests/test_mcp_server.py", "MCP server handler tests"),
    ("mcp_stdio", "tests/test_stdio.py", "MCP stdio transport tests"),
    ("mcp_tool_profiles", "tests/test_mcp_tool_profiles.py", "MCP tool profile tests"),
    ("backup_cli", "tests/test_backup_cli.py", "Backup/restore CLI tests"),
    ("offline", "tests/test_offline.py", "Offline / no-network guard tests"),
    (
        "code_intelligence_packet",
        "tests/test_code_intelligence_packet.py",
        "Code-intelligence demo packet generation and validation tests",
    ),
)

_PUBLIC_SAFETY_MODULE = None
_PERF_BUDGETS_MODULE = None
PERF_BUDGET_ARTIFACT_RELPATH = "benchmarks/demo_perf_budgets.json"


def repo_root() -> Path:
    """Repository root — the parent of this script's ``scripts/`` directory."""
    return Path(__file__).resolve().parent.parent


def _public_safety_module():
    """Load sibling public_safety_scan.py without requiring package installation."""
    global _PUBLIC_SAFETY_MODULE
    if _PUBLIC_SAFETY_MODULE is not None:
        return _PUBLIC_SAFETY_MODULE
    module_path = Path(__file__).resolve().parent / "public_safety_scan.py"
    spec = importlib.util.spec_from_file_location("_mempalace_public_safety_scan", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _PUBLIC_SAFETY_MODULE = module
    return module


def _perf_budgets_module():
    """Load sibling benchmarks/demo_perf_budgets.py — schema/comparison logic only.

    This never runs a benchmark measurement; it only reuses the module's stdlib-only
    ``load_and_validate_artifact``/``budget_for``/``METRIC_NAMES`` so the scorecard's
    validation stays byte-identical to the CI gate's own validation.
    """
    global _PERF_BUDGETS_MODULE
    if _PERF_BUDGETS_MODULE is not None:
        return _PERF_BUDGETS_MODULE
    module_path = Path(__file__).resolve().parent.parent / "benchmarks" / "demo_perf_budgets.py"
    spec = importlib.util.spec_from_file_location("_mempalace_demo_perf_budgets", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _PERF_BUDGETS_MODULE = module
    return module


def _is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in _SKIP_PARTS or part.endswith(".egg-info") for part in rel.parts):
        return True
    rel_posix = rel.as_posix()
    return any(rel_posix == d or rel_posix.startswith(f"{d}/") for d in EXCLUDED_DIRS)


def _iter_py_files(directory: Path, root: Path) -> list[Path]:
    """All ``*.py`` files under ``directory``, excluding fixture dirs, sorted."""
    files = [p for p in directory.rglob("*.py") if not _is_excluded(p, root)]
    return sorted(files)


def _count_lines(path: Path) -> tuple[int, int]:
    """Return (total physical lines, code lines).

    A code line is any non-blank line that is not a pure comment. Docstring
    bodies count as code — the metric tracks size, not semantics, and stays
    deterministic.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    total = len(lines)
    code = sum(1 for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))
    return total, code


def collect_code_size(root: Path) -> dict:
    pkg_files = _iter_py_files(root / PACKAGE_DIR, root)
    test_files = _iter_py_files(root / TESTS_DIR, root)
    pkg_total = pkg_code = 0
    for p in pkg_files:
        t, c = _count_lines(p)
        pkg_total += t
        pkg_code += c
    test_total = sum(_count_lines(p)[0] for p in test_files)
    return {
        "package_files": len(pkg_files),
        "package_total_lines": pkg_total,
        "package_code_lines": pkg_code,
        "test_files": len(test_files),
        "test_total_lines": test_total,
    }


def collect_largest_modules(root: Path, top_n: int = TOP_MODULES) -> list[dict]:
    sizes = []
    for p in _iter_py_files(root / PACKAGE_DIR, root):
        total, _ = _count_lines(p)
        sizes.append({"path": p.relative_to(root).as_posix(), "lines": total})
    sizes.sort(key=lambda m: (-m["lines"], m["path"]))
    return sizes[:top_n]


def load_pyproject(root: Path) -> dict:
    import tomllib

    with (root / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def collect_ruff(pyproject: dict) -> dict:
    ruff = pyproject.get("tool", {}).get("ruff", {})
    lint = ruff.get("lint", {})
    global_ignores = sorted(lint.get("ignore", []))
    selected = lint.get("select", [])
    per_file = lint.get("per-file-ignores", {})
    by_pattern = sorted(
        ({"pattern": pat, "count": len(rules)} for pat, rules in per_file.items()),
        key=lambda e: e["pattern"],
    )
    return {
        "global_ignores": len(global_ignores),
        "global_ignore_rules": global_ignores,
        "selected_rule_families": len(selected),
        "per_file_ignores": {
            "patterns": len(by_pattern),
            "total_entries": sum(e["count"] for e in by_pattern),
            "by_pattern": by_pattern,
        },
    }


def collect_pyright(pyproject: dict) -> dict:
    pyright = pyproject.get("tool", {}).get("pyright", {})
    mode = pyright.get("typeCheckingMode", "off")
    return {
        "type_checking_mode": mode,
        "python_version": str(pyright.get("pythonVersion", "")),
        "strict": mode == "strict",
        "include": sorted(pyright.get("include", [])),
    }


def _comment_units(path: Path) -> list[str]:
    """Return the comment text of each ``# ...`` token in a file.

    Suppression directives (``# type: ignore``, ``# noqa``) are only meaningful in
    comments, so scanning comment tokens — not raw lines — avoids counting string
    literals or docstrings that merely *mention* the syntax (e.g. policy text). A
    one-line ``# type: ignore[code]  # reason: text`` is a single comment token,
    so the accepted two-hash form is preserved. Falls back to raw lines if the
    file does not tokenize.
    """
    src = path.read_text(encoding="utf-8")
    try:
        return [
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src.splitlines()


def collect_suppressions(root: Path) -> dict:
    """Count type/pyright/noqa suppressions across package + tests (no fixtures).

    "Unreasoned" follows tests/test_type_suppressions.py: a type/pyright ignore
    without a ``[code]`` and a ``# reason:`` justification, plus any blanket
    ``# noqa`` carrying no specific rule code.
    """
    files = _iter_py_files(root / PACKAGE_DIR, root) + _iter_py_files(root / TESTS_DIR, root)
    type_total = type_unreasoned = noqa_total = noqa_blanket = 0
    for path in sorted(files):
        for unit in _comment_units(path):
            if _SUPPRESSION_RE.search(unit):
                type_total += 1
                if not _ACCEPTED_RE.search(unit):
                    type_unreasoned += 1
            if _NOQA_RE.search(unit):
                noqa_total += 1
                if _NOQA_BLANKET_RE.search(unit):
                    noqa_blanket += 1
    return {
        "scope": [PACKAGE_DIR, TESTS_DIR],
        "type_pyright_total": type_total,
        "type_pyright_unreasoned": type_unreasoned,
        "noqa_total": noqa_total,
        "noqa_blanket": noqa_blanket,
        "unreasoned_total": type_unreasoned + noqa_blanket,
    }


def _count_test_functions(path: Path) -> int:
    """Count ``test*`` functions/methods in a file via AST, regex on parse error."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return sum(1 for ln in text.splitlines() if _TEST_DEF_RE.match(ln))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            count += 1
    return count


def _count_class_test_methods(path: Path, class_name: str) -> int:
    """Count test* methods inside a named ClassDef via AST. Returns 0 if absent or unparseable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return sum(
                1
                for m in node.body
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
                and m.name.startswith("test")
            )
    return 0


def collect_tests(root: Path) -> dict:
    test_files = _iter_py_files(root / TESTS_DIR, root)
    return {
        "test_files": len(test_files),
        "test_functions": sum(_count_test_functions(p) for p in test_files),
    }


def collect_suites(root: Path) -> list[dict]:
    return [
        {"name": name, "path": rel, "present": (root / rel).exists(), "description": desc}
        for name, rel, desc in _KNOWN_SUITES
    ]


def verification_commands() -> list[dict]:
    return [
        {"name": gate["id"], "command": gate["command"]}
        for gate in _GATE_INVENTORY.verify_surface_gates()
    ]


def collect_pyright_strict_slice(root: Path) -> dict:
    """Metrics for the strict Pyright slice from pyrightconfig.strict.json."""
    config_path = root / "pyrightconfig.strict.json"
    if not config_path.exists():
        return {"file_count": 0, "include_strict_match": False, "paths": []}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    include_paths = sorted(data.get("include", []))
    strict_paths = sorted(data.get("strict", []))
    return {
        "file_count": len(include_paths),
        "include_strict_match": include_paths == strict_paths,
        "paths": include_paths,
    }


def collect_public_safety_coverage() -> dict:
    """Metadata about supported public-safety scan modes — no subprocess, no scan execution."""
    return {
        "commands": {
            "committed": "python scripts/public_safety_scan.py --committed",
            "staged": "python scripts/public_safety_scan.py --staged",
            "tracked": "python scripts/public_safety_scan.py --tracked",
        },
        "modes": ["committed", "staged", "tracked"],
    }


def collect_gitleaks_coverage() -> dict:
    """Metadata about supported Gitleaks modes — no subprocess, no scan execution."""
    return {
        "assurance_commands": {
            "fixture_smoke": _GATE_INVENTORY.GITLEAKS_FIXTURE_SMOKE_COMMAND,
            "validate_baseline": _GATE_INVENTORY.GITLEAKS_VALIDATE_BASELINE_COMMAND,
        },
        "commands": {
            "changed_range": _GATE_INVENTORY.GITLEAKS_CHANGED_RANGE_COMMAND,
            "full_history": _GATE_INVENTORY.GITLEAKS_FULL_HISTORY_COMMAND,
        },
        "coverage": [
            "maintained_default_corpus",
            "entropy_rule",
            "changed_commit_range",
            "full_git_history",
            "native_fingerprint_ignores",
            "reviewed_suppression_metadata",
            "redacted_sarif_report",
            "runtime_five_class_fixture",
        ],
        "modes": ["changed_range", "full_history"],
    }


def collect_demo_gates(root: Path) -> dict:
    """Public-demo gate metrics via file-presence and AST reads only — no subprocess."""
    # architecture_guard: stdlib AST import-boundary guard script
    arch_status = "present" if (root / "scripts" / "architecture_guard.py").exists() else "absent"

    # cli_golden_scenarios: test-function count from the golden scenario suite
    cli_golden_path = root / "tests" / "test_cli_golden_scenarios.py"
    cli_golden_present = cli_golden_path.exists()
    cli_golden_count = _count_test_functions(cli_golden_path) if cli_golden_present else 0

    # mcp_stdio_contracts: class-scoped count from TestMCPStdioContracts in test_mcp_server.py
    mcp_server_path = root / "tests" / "test_mcp_server.py"
    mcp_count = _count_class_test_methods(mcp_server_path, "TestMCPStdioContracts")
    mcp_status = "present" if mcp_count > 0 else "absent"

    # docs_drift_guard: static package-to-documentation consistency guard
    docs_drift_status = (
        "present" if (root / "scripts" / "docs_drift_guard.py").exists() else "absent"
    )
    # Static coverage list — kept in sync by hand with the check categories
    # scripts/docs_drift_guard.py implements (CLI inventory, MCP tools/profiles,
    # optional extras, release/dependency gates, canonical verification
    # commands). No AST introspection of the guard itself; this is a fixed,
    # deterministic label list, empty when the guard is absent.
    docs_drift_coverage = (
        [
            "cli_commands",
            "mcp_tools_and_profiles",
            "optional_extras",
            "release_and_dependency_gates",
            "verification_commands",
        ]
        if docs_drift_status == "present"
        else []
    )

    # dependency_audit: both gate script and workflow must exist
    dep_gate = (root / "scripts" / "dependency_upgrade_gate.py").exists()
    dep_wf = (root / ".github" / "workflows" / "dependency-audit.yml").exists()
    dep_status = "present" if dep_gate and dep_wf else "absent"

    return {
        "architecture_guard": {"status": arch_status},
        "cli_golden_scenarios": {
            "count": cli_golden_count,
            "status": "present" if cli_golden_present else "absent",
        },
        "dependency_audit": {"status": dep_status},
        "docs_drift_guard": {"status": docs_drift_status, "coverage": docs_drift_coverage},
        "mcp_stdio_contracts": {"count": mcp_count, "status": mcp_status},
    }


def collect_performance_budgets(root: Path) -> dict:
    """Read + validate the committed synthetic performance-budget artifact.

    Never executes a benchmark — reads ``benchmarks/demo_perf_budgets.json`` and
    reuses the runner module's own schema/comparison logic so this stays
    byte-identical to what ``--check --ci`` itself validates.
    """
    mod = _perf_budgets_module()
    artifact_path = root / PERF_BUDGET_ARTIFACT_RELPATH
    data, errors = mod.load_and_validate_artifact(artifact_path)
    if data is None:
        return {"valid": False, "errors": errors, "metrics": []}

    metrics = []
    for name in mod.METRIC_NAMES:
        m = data["metrics"][name]
        metrics.append(
            {
                "name": name,
                "unit": m["unit"],
                "before": m["before"],
                "current": m["baseline"],
                "budget": mod.budget_for(m["baseline"], m["floor"], m["ratio"]),
                "comparison": m["comparison"],
            }
        )
    return {
        "valid": True,
        "errors": [],
        "budget_changed_because": data["budget_changed_because"],
        "fixture_file_count": data["fixture"]["file_count"],
        "metrics": metrics,
    }


def build_scorecard(root: Path) -> dict:
    """Assemble the full scorecard dict. Pure function of the tracked tree."""
    pyproject = load_pyproject(root)
    pyright_data = collect_pyright(pyproject)
    pyright_data["strict_slice"] = collect_pyright_strict_slice(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": {"package_dir": PACKAGE_DIR, "tests_dir": TESTS_DIR},
        "code_size": collect_code_size(root),
        "demo_gates": collect_demo_gates(root),
        "gitleaks": collect_gitleaks_coverage(),
        "largest_modules": collect_largest_modules(root),
        "performance_budgets": collect_performance_budgets(root),
        "public_safety": collect_public_safety_coverage(),
        "ruff": collect_ruff(pyproject),
        "pyright": pyright_data,
        "suppressions": collect_suppressions(root),
        "tests": collect_tests(root),
        "suites": collect_suites(root),
        "verification_commands": verification_commands(),
    }


def render_json(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_markdown(data: dict) -> str:
    cs = data["code_size"]
    ruff = data["ruff"]
    py = data["pyright"]
    sup = data["suppressions"]
    tests = data["tests"]
    lines: list[str] = []
    lines.append("# Quality Scorecard")
    lines.append("")
    lines.append(
        "Deterministic, repo-local, public-safe metrics generated by "
        "`scripts/quality_scorecard.py`. Regenerate with "
        "`python scripts/quality_scorecard.py --write`. No timestamps or absolute "
        "paths — two runs on the same tree produce identical output."
    )
    lines.append("")
    lines.append(f"Schema version: {data['schema_version']}")
    lines.append("")

    lines.append("## Code Size")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|------:|")
    lines.append(f"| Package files (`{data['scope']['package_dir']}/`) | {cs['package_files']} |")
    lines.append(f"| Package total lines | {cs['package_total_lines']} |")
    lines.append(f"| Package code lines | {cs['package_code_lines']} |")
    lines.append(f"| Test files (`{data['scope']['tests_dir']}/`) | {cs['test_files']} |")
    lines.append(f"| Test total lines | {cs['test_total_lines']} |")
    lines.append("")

    lines.append(f"## Largest Modules (top {len(data['largest_modules'])})")
    lines.append("")
    lines.append("| Module | Lines |")
    lines.append("|--------|------:|")
    for m in data["largest_modules"]:
        lines.append(f"| `{m['path']}` | {m['lines']} |")
    lines.append("")

    lines.append("## Ruff Ignores")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|------:|")
    lines.append(f"| Selected rule families | {ruff['selected_rule_families']} |")
    lines.append(f"| Global ignores | {ruff['global_ignores']} |")
    lines.append(f"| Per-file ignore patterns | {ruff['per_file_ignores']['patterns']} |")
    lines.append(f"| Per-file ignore entries | {ruff['per_file_ignores']['total_entries']} |")
    lines.append("")
    if ruff["per_file_ignores"]["by_pattern"]:
        lines.append("| Per-file pattern | Entries |")
        lines.append("|------------------|--------:|")
        for e in ruff["per_file_ignores"]["by_pattern"]:
            lines.append(f"| `{e['pattern']}` | {e['count']} |")
        lines.append("")

    lines.append("## Pyright")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Type-checking mode | {py['type_checking_mode']} |")
    lines.append(f"| Strict | {str(py['strict']).lower()} |")
    lines.append(f"| Python version | {py['python_version']} |")
    lines.append(f"| Include | {', '.join(f'`{i}`' for i in py['include'])} |")
    lines.append("")

    ss = py.get("strict_slice", {})
    lines.append("## Pyright Strict Slice")
    lines.append("")
    lines.append(
        f"Files under strict type-checking (`pyrightconfig.strict.json`): {ss.get('file_count', 0)}."
    )
    if ss.get("paths"):
        lines.append("")
        for _p in ss["paths"]:
            lines.append(f"- `{_p}`")
    lines.append("")

    pub = data["public_safety"]
    lines.append("## Public Safety")
    lines.append("")
    lines.append("| Mode | Command |")
    lines.append("|------|---------|")
    for _mode in pub["modes"]:
        _cmd = pub.get("commands", {}).get(_mode, "")
        lines.append(f"| {_mode} | `{_cmd}` |")
    lines.append("")

    gleaks = data["gitleaks"]
    lines.append("## Gitleaks")
    lines.append("")
    lines.append("| Mode | Command |")
    lines.append("|------|---------|")
    for _mode in gleaks["modes"]:
        _cmd = gleaks.get("commands", {}).get(_mode, "")
        lines.append(f"| {_mode} | `{_cmd}` |")
    lines.append("")
    lines.append("| Assurance | Command |")
    lines.append("|-----------|---------|")
    for _name, _cmd in sorted(gleaks["assurance_commands"].items()):
        lines.append(f"| {_name} | `{_cmd}` |")
    lines.append("")
    lines.append("Coverage: " + ", ".join(f"`{c}`" for c in gleaks["coverage"]))
    lines.append("")

    demo = data["demo_gates"]
    lines.append("## Demo Gates")
    lines.append("")
    lines.append("| Gate | Status | Count |")
    lines.append("|------|:------:|------:|")
    for _gate_key in sorted(demo.keys()):
        _gate = demo[_gate_key]
        _status = _gate.get("status", "absent")
        _count = str(_gate["count"]) if "count" in _gate else ""
        lines.append(f"| {_gate_key} | {_status} | {_count} |")
    lines.append("")
    _docs_drift_coverage = demo.get("docs_drift_guard", {}).get("coverage", [])
    if _docs_drift_coverage:
        lines.append(
            "`docs_drift_guard` coverage: " + ", ".join(f"`{c}`" for c in _docs_drift_coverage)
        )
        lines.append("")

    pb = data["performance_budgets"]
    lines.append("## Performance Budgets")
    lines.append("")
    lines.append(
        "Deterministic synthetic performance budgets for mine, incremental no-op, "
        "search, read, and maintenance, read from "
        f"`{PERF_BUDGET_ARTIFACT_RELPATH}` (never executed by the scorecard). CI enforces "
        "the hard budgets with `python benchmarks/demo_perf_budgets.py --check --ci`."
    )
    lines.append("")
    if not pb["valid"]:
        lines.append(f"**Artifact invalid**: {'; '.join(pb['errors'])}")
        lines.append("")
    else:
        lines.append(f"Current baseline reason: {pb['budget_changed_because']}")
        lines.append("")
        lines.append("| Metric | Unit | Before | Current | Budget |")
        lines.append("|--------|:----:|-------:|--------:|-------:|")
        for m in pb["metrics"]:
            _before = "baseline absent" if m["before"] is None else f"{m['before']:.4f}"
            lines.append(
                f"| {m['name']} | {m['unit']} | {_before} | {m['current']:.4f} | {m['budget']:.4f} |"
            )
        lines.append("")

    lines.append("## Suppressions")
    lines.append("")
    lines.append(
        f"Scope: {', '.join(f'`{s}/`' for s in sup['scope'])} (excludes `tests/fixtures/`)."
    )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|------:|")
    lines.append(f"| type/pyright ignores (total) | {sup['type_pyright_total']} |")
    lines.append(f"| type/pyright unreasoned | {sup['type_pyright_unreasoned']} |")
    lines.append(f"| noqa (total) | {sup['noqa_total']} |")
    lines.append(f"| noqa blanket | {sup['noqa_blanket']} |")
    lines.append(f"| **Unreasoned suppressions (total)** | **{sup['unreasoned_total']}** |")
    lines.append("")

    lines.append("## Tests")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|------:|")
    lines.append(f"| Test files | {tests['test_files']} |")
    lines.append(f"| Test functions | {tests['test_functions']} |")
    lines.append("")

    lines.append("## Available Suites")
    lines.append("")
    lines.append("| Suite | Path | Present |")
    lines.append("|-------|------|:-------:|")
    for s in data["suites"]:
        mark = "yes" if s["present"] else "no"
        lines.append(f"| {s['name']} | `{s['path']}` | {mark} |")
    lines.append("")

    lines.append("## Verification Commands")
    lines.append("")
    for c in data["verification_commands"]:
        lines.append(f"- **{c['name']}**: `{c['command']}`")
    return "\n".join(lines)


def validate(data: dict) -> list[str]:
    """Return a list of shape errors; empty means the scorecard is well-formed."""
    errors: list[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    require(
        data.get("schema_version") == SCHEMA_VERSION, "schema_version must equal SCHEMA_VERSION"
    )

    cs = data.get("code_size", {})
    for key in (
        "package_files",
        "package_total_lines",
        "package_code_lines",
        "test_files",
        "test_total_lines",
    ):
        require(
            isinstance(cs.get(key), int) and cs.get(key, -1) >= 0,
            f"code_size.{key} must be a non-negative int",
        )
    require(cs.get("package_files", 0) > 0, "code_size.package_files must be > 0")

    mods = data.get("largest_modules")
    require(isinstance(mods, list) and len(mods) > 0, "largest_modules must be a non-empty list")
    if isinstance(mods, list):
        for m in mods:
            require(
                isinstance(m, dict)
                and isinstance(m.get("path"), str)
                and isinstance(m.get("lines"), int),
                "each largest_modules entry needs str path and int lines",
            )
        line_vals = [m.get("lines", 0) for m in mods if isinstance(m, dict)]
        require(
            line_vals == sorted(line_vals, reverse=True),
            "largest_modules must be sorted by lines descending",
        )

    ruff = data.get("ruff", {})
    for key in ("global_ignores", "selected_rule_families"):
        require(
            isinstance(ruff.get(key), int) and ruff.get(key, -1) >= 0,
            f"ruff.{key} must be a non-negative int",
        )
    require(
        isinstance(ruff.get("global_ignore_rules"), list), "ruff.global_ignore_rules must be a list"
    )
    pfi = ruff.get("per_file_ignores", {})
    require(
        isinstance(pfi.get("patterns"), int) and isinstance(pfi.get("total_entries"), int),
        "ruff.per_file_ignores needs int patterns and total_entries",
    )

    py = data.get("pyright", {})
    require(
        isinstance(py.get("type_checking_mode"), str) and py.get("type_checking_mode"),
        "pyright.type_checking_mode must be a non-empty str",
    )
    require(isinstance(py.get("strict"), bool), "pyright.strict must be a bool")

    ss = py.get("strict_slice", None)
    require(isinstance(ss, dict), "pyright.strict_slice must be a dict")
    if isinstance(ss, dict):
        require(
            isinstance(ss.get("file_count"), int) and ss.get("file_count", -1) >= 0,
            "pyright.strict_slice.file_count must be a non-negative int",
        )
        require(isinstance(ss.get("paths"), list), "pyright.strict_slice.paths must be a list")
        require(
            isinstance(ss.get("include_strict_match"), bool),
            "pyright.strict_slice.include_strict_match must be a bool",
        )
        if isinstance(ss.get("paths"), list) and isinstance(ss.get("file_count"), int):
            require(
                ss["file_count"] == len(ss["paths"]),
                "pyright.strict_slice.file_count must equal len(paths)",
            )
            require(
                ss["paths"] == sorted(ss["paths"]),
                "pyright.strict_slice.paths must be sorted",
            )

    ps = data.get("public_safety", {})
    require(isinstance(ps.get("modes"), list), "public_safety.modes must be a list")
    if isinstance(ps.get("modes"), list):
        for _mode in ("committed", "staged", "tracked"):
            require(_mode in ps["modes"], f"public_safety.modes must include '{_mode}'")

    gleaks = data.get("gitleaks", {})
    require(isinstance(gleaks.get("modes"), list), "gitleaks.modes must be a list")
    if isinstance(gleaks.get("modes"), list):
        for _mode in ("changed_range", "full_history"):
            require(_mode in gleaks["modes"], f"gitleaks.modes must include '{_mode}'")
    require(isinstance(gleaks.get("commands"), dict), "gitleaks.commands must be a dict")
    require(
        isinstance(gleaks.get("assurance_commands"), dict),
        "gitleaks.assurance_commands must be a dict",
    )
    if isinstance(gleaks.get("assurance_commands"), dict):
        for _command in ("validate_baseline", "fixture_smoke"):
            require(
                _command in gleaks["assurance_commands"],
                f"gitleaks.assurance_commands must include {_command}",
            )
    require(isinstance(gleaks.get("coverage"), list), "gitleaks.coverage must be a list")
    if isinstance(gleaks.get("coverage"), list):
        for _coverage in (
            "maintained_default_corpus",
            "entropy_rule",
            "changed_commit_range",
            "full_git_history",
            "native_fingerprint_ignores",
            "reviewed_suppression_metadata",
            "redacted_sarif_report",
            "runtime_five_class_fixture",
        ):
            require(_coverage in gleaks["coverage"], f"gitleaks.coverage must include {_coverage}")

    gates = data.get("demo_gates", {})
    require(isinstance(gates, dict), "demo_gates must be a dict")
    if isinstance(gates, dict):
        for _gate in (
            "architecture_guard",
            "cli_golden_scenarios",
            "dependency_audit",
            "docs_drift_guard",
            "mcp_stdio_contracts",
        ):
            require(_gate in gates, f"demo_gates.{_gate} must be present")
            if isinstance(gates.get(_gate), dict):
                require(
                    gates[_gate].get("status") in ("present", "absent"),
                    f"demo_gates.{_gate}.status must be 'present' or 'absent'",
                )
        for _count_gate in ("cli_golden_scenarios", "mcp_stdio_contracts"):
            if isinstance(gates.get(_count_gate), dict):
                require(
                    isinstance(gates[_count_gate].get("count"), int)
                    and gates[_count_gate].get("count", -1) >= 0,
                    f"demo_gates.{_count_gate}.count must be a non-negative int",
                )
        if isinstance(gates.get("docs_drift_guard"), dict):
            coverage = gates["docs_drift_guard"].get("coverage")
            require(
                isinstance(coverage, list) and all(isinstance(c, str) for c in coverage),
                "demo_gates.docs_drift_guard.coverage must be a list of str",
            )

    pb = data.get("performance_budgets", {})
    require(isinstance(pb, dict), "performance_budgets must be a dict")
    if isinstance(pb, dict):
        require(isinstance(pb.get("valid"), bool), "performance_budgets.valid must be a bool")
        if pb.get("valid") is True:
            metrics = pb.get("metrics")
            require(
                isinstance(metrics, list) and len(metrics) > 0,
                "performance_budgets.metrics must be a non-empty list when valid",
            )
            if isinstance(metrics, list):
                for m in metrics:
                    require(
                        isinstance(m, dict)
                        and isinstance(m.get("name"), str)
                        and isinstance(m.get("unit"), str)
                        and isinstance(m.get("current"), (int, float))
                        and isinstance(m.get("budget"), (int, float)),
                        "each performance_budgets.metrics entry needs name/unit/current/budget",
                    )
            require(
                isinstance(pb.get("budget_changed_because"), str)
                and pb.get("budget_changed_because", "").strip() != "",
                "performance_budgets.budget_changed_because must be a non-empty string when valid",
            )
        elif pb.get("valid") is False:
            require(
                isinstance(pb.get("errors"), list) and len(pb["errors"]) > 0,
                "performance_budgets.errors must be a non-empty list when invalid",
            )

    sup = data.get("suppressions", {})
    for key in (
        "type_pyright_total",
        "type_pyright_unreasoned",
        "noqa_total",
        "noqa_blanket",
        "unreasoned_total",
    ):
        require(
            isinstance(sup.get(key), int) and sup.get(key, -1) >= 0,
            f"suppressions.{key} must be a non-negative int",
        )
    if all(
        isinstance(sup.get(k), int)
        for k in ("type_pyright_unreasoned", "noqa_blanket", "unreasoned_total")
    ):
        require(
            sup["unreasoned_total"] == sup["type_pyright_unreasoned"] + sup["noqa_blanket"],
            "suppressions.unreasoned_total must equal type_pyright_unreasoned + noqa_blanket",
        )

    tests = data.get("tests", {})
    for key in ("test_files", "test_functions"):
        require(
            isinstance(tests.get(key), int) and tests.get(key, -1) >= 0,
            f"tests.{key} must be a non-negative int",
        )

    suites = data.get("suites")
    require(isinstance(suites, list) and len(suites) > 0, "suites must be a non-empty list")
    if isinstance(suites, list):
        for s in suites:
            require(
                isinstance(s, dict)
                and isinstance(s.get("name"), str)
                and isinstance(s.get("path"), str)
                and isinstance(s.get("present"), bool),
                "each suite needs str name, str path, and bool present",
            )

    cmds = data.get("verification_commands")
    require(
        isinstance(cmds, list) and len(cmds) > 0, "verification_commands must be a non-empty list"
    )
    if isinstance(cmds, list):
        for c in cmds:
            require(
                isinstance(c, dict)
                and isinstance(c.get("name"), str)
                and isinstance(c.get("command"), str),
                "each verification command needs str name and str command",
            )

    return errors


def scan_public_safety(*texts: str) -> list[str]:
    """Return rendered substrings that match a forbidden private/secret pattern."""
    return _public_safety_module().scan_rendered_texts(*texts)


def check_committed_artifacts(root: Path, markdown: str, json_text: str) -> list[str]:
    """Return freshness errors for committed docs/quality artifacts."""
    errors: list[str] = []
    md_path = root / "docs" / "quality" / "scorecard.md"
    json_path = root / "docs" / "quality" / "scorecard.json"
    if not md_path.exists():
        errors.append("stale-artifact: docs/quality/scorecard.md is missing")
    elif md_path.read_text(encoding="utf-8") != markdown + "\n":
        errors.append("stale-artifact: docs/quality/scorecard.md is stale; run --write")
    if not json_path.exists():
        errors.append("stale-artifact: docs/quality/scorecard.json is missing")
    elif json_path.read_text(encoding="utf-8") != json_text:
        errors.append("stale-artifact: docs/quality/scorecard.json is stale; run --write")
    return errors


def run_check(root: Path) -> int:
    """Validate shape, determinism, and public-safety. Returns process exit code."""
    problems: list[str] = []

    try:
        first = build_scorecard(root)
        second = build_scorecard(root)
    except Exception as exc:  # noqa: BLE001  # reason: surface any build failure as a check failure
        print(f"quality-scorecard: FAIL — build raised {exc!r}", file=sys.stderr)
        return 1

    if render_json(first) != render_json(second):
        problems.append("non-deterministic output: two builds differ")

    problems.extend(validate(first))

    md = render_markdown(first)
    js = render_json(first)
    problems.extend(f"public-safety: {h}" for h in scan_public_safety(md, js))
    problems.extend(check_committed_artifacts(root, md, js))

    if problems:
        print("quality-scorecard: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(
        "quality-scorecard: OK "
        f"(schema {first['schema_version']}, "
        f"{first['code_size']['package_files']} package files, "
        f"{first['tests']['test_functions']} test functions, "
        f"{first['suppressions']['unreasoned_total']} unreasoned suppressions)"
    )
    return 0


def write_outputs(root: Path, out_dir: Path) -> list[Path]:
    data = build_scorecard(root)
    md = render_markdown(data)
    js = render_json(data)
    unsafe = scan_public_safety(md, js)
    if unsafe:
        raise SystemExit("Refusing to write: public-safety scan failed:\n  " + "\n  ".join(unsafe))
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "scorecard.md"
    json_path = out_dir / "scorecard.json"
    md_path.write_text(md + "\n", encoding="utf-8")
    json_path.write_text(js, encoding="utf-8")
    return [md_path, json_path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic, public-safe code-quality scorecard (Markdown + JSON).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "both"],
        default="markdown",
        help="Output format when printing to stdout (default: markdown).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write scorecard.md and scorecard.json into --out-dir instead of stdout.",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/quality",
        help="Directory for --write output (default: docs/quality).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate output shape, determinism, and public-safety; exit non-zero on failure.",
    )
    args = parser.parse_args(argv)
    root = repo_root()

    if args.check:
        return run_check(root)

    if args.write:
        out_dir = (
            (root / args.out_dir) if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
        )
        written = write_outputs(root, out_dir)
        for path in written:
            rel = (
                path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
            )
            print(f"wrote {rel}")
        return 0

    data = build_scorecard(root)
    md = render_markdown(data)
    js = render_json(data)
    # Scan both renderings regardless of --format so the stdout path is as
    # public-safe as --write and --check; never emit private data.
    unsafe = scan_public_safety(md, js)
    if unsafe:
        raise SystemExit("Refusing to print: public-safety scan failed:\n  " + "\n  ".join(unsafe))
    if args.format == "json":
        sys.stdout.write(js)
    elif args.format == "both":
        sys.stdout.write(md)
        sys.stdout.write("\n\n")
        sys.stdout.write(js)
    else:
        sys.stdout.write(md + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
