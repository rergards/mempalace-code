"""
test_quality_scorecard.py — Tests for scripts/quality_scorecard.py.

Covers the scorecard's output shape, deterministic behavior, public-safety
self-scan, and the --check / --write entry points. Metric *logic* is exercised
against a hermetic synthetic repo so the assertions do not drift as the real
repository grows; determinism and public-safety are checked against the live
tree.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

# ── Load the scorecard module from scripts/ without installing it ──────────────

ROOT = Path(__file__).parent.parent


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: spec_from_file_location is non-None for an existing file
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: loader is a real Loader at runtime but typed Optional
    return mod


sc = _load_module_from_path("quality_scorecard", ROOT / "scripts" / "quality_scorecard.py")


# ── Hermetic synthetic repo (metric logic, drift-free) ─────────────────────────

_FAKE_PYPROJECT = """\
[tool.ruff.lint]
select = ["E", "F", "W"]
ignore = ["E501", "B904"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["ARG001", "ARG002"]

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "basic"
include = ["mempalace_code", "tests"]
"""


def _make_fake_repo(tmp_path: Path) -> Path:
    pkg = tmp_path / "mempalace_code"
    pkg.mkdir()
    (pkg / "a.py").write_text("x = 1\n# a comment\n\ndef f():\n    return x\n", encoding="utf-8")
    (pkg / "b.py").write_text("y = 2\n\ndef g():\n    return y\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_a.py").write_text(
        "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
        encoding="utf-8",
    )
    fixtures = tests / "fixtures"
    fixtures.mkdir()
    # A fixture-dir file with a test-looking name must be excluded from counts.
    (fixtures / "test_decoy.py").write_text(
        "def test_decoy():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(_FAKE_PYPROJECT, encoding="utf-8")
    return tmp_path


def test_code_size_counts_package_and_tests(tmp_path):
    root = _make_fake_repo(tmp_path)
    cs = sc.collect_code_size(root)
    assert cs["package_files"] == 2
    assert cs["test_files"] == 1  # fixtures excluded
    assert cs["package_total_lines"] > 0
    assert cs["package_code_lines"] <= cs["package_total_lines"]


def test_test_functions_exclude_fixtures(tmp_path):
    root = _make_fake_repo(tmp_path)
    tests = sc.collect_tests(root)
    assert tests["test_files"] == 1
    assert tests["test_functions"] == 2  # decoy in fixtures/ not counted


def test_ruff_metrics_from_pyproject(tmp_path):
    root = _make_fake_repo(tmp_path)
    pyproject = sc.load_pyproject(root)
    ruff = sc.collect_ruff(pyproject)
    assert ruff["global_ignores"] == 2
    assert ruff["global_ignore_rules"] == ["B904", "E501"]  # sorted
    assert ruff["selected_rule_families"] == 3
    assert ruff["per_file_ignores"]["patterns"] == 1
    assert ruff["per_file_ignores"]["total_entries"] == 2


def test_pyright_metrics_from_pyproject(tmp_path):
    root = _make_fake_repo(tmp_path)
    py = sc.collect_pyright(sc.load_pyproject(root))
    assert py["type_checking_mode"] == "basic"
    assert py["strict"] is False
    assert py["python_version"] == "3.11"


def test_build_scorecard_validates_on_fake_repo(tmp_path):
    root = _make_fake_repo(tmp_path)
    data = sc.build_scorecard(root)
    assert sc.validate(data) == []


# ── Output shape (live repo) ───────────────────────────────────────────────────


def test_build_scorecard_has_required_top_level_keys():
    data = sc.build_scorecard(ROOT)
    for key in (
        "schema_version",
        "scope",
        "code_size",
        "demo_gates",
        "gitleaks",
        "largest_modules",
        "performance_budgets",
        "public_safety",
        "ruff",
        "pyright",
        "suppressions",
        "tests",
        "suites",
        "verification_commands",
    ):
        assert key in data, f"missing top-level key: {key}"


def test_live_scorecard_validates():
    assert sc.validate(sc.build_scorecard(ROOT)) == []


def test_largest_modules_sorted_descending():
    mods = sc.build_scorecard(ROOT)["largest_modules"]
    assert mods, "largest_modules must not be empty"
    line_counts = [m["lines"] for m in mods]
    assert line_counts == sorted(line_counts, reverse=True)
    for m in mods:
        assert not m["path"].startswith("/"), "module paths must be relative"


def test_suppressions_invariant_holds():
    sup = sc.build_scorecard(ROOT)["suppressions"]
    assert sup["unreasoned_total"] == sup["type_pyright_unreasoned"] + sup["noqa_blanket"]


def test_suites_include_known_surfaces():
    suites = {s["name"]: s for s in sc.build_scorecard(ROOT)["suites"]}
    for name in ("cli", "cli_golden_scenarios", "mcp_stdio", "migrate_storage_smoke"):
        assert name in suites
        assert suites[name]["present"] is True
    # cli_golden_scenarios is a distinct suite from cli (subprocess workflows vs
    # in-process unit coverage) — same path never satisfies both.
    assert suites["cli_golden_scenarios"]["path"] != suites["cli"]["path"]


# ── Determinism ────────────────────────────────────────────────────────────────


def test_json_render_is_deterministic():
    a = sc.render_json(sc.build_scorecard(ROOT))
    b = sc.render_json(sc.build_scorecard(ROOT))
    assert a == b


def test_markdown_render_is_deterministic():
    a = sc.render_markdown(sc.build_scorecard(ROOT))
    b = sc.render_markdown(sc.build_scorecard(ROOT))
    assert a == b


def test_json_is_parseable_and_sorted():
    text = sc.render_json(sc.build_scorecard(ROOT))
    parsed = json.loads(text)
    assert parsed["schema_version"] == sc.SCHEMA_VERSION
    # sort_keys=True means re-dumping the parsed object reproduces the text.
    assert json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n" == text


def test_markdown_has_required_sections():
    md = sc.render_markdown(sc.build_scorecard(ROOT))
    for header in (
        "# Quality Scorecard",
        "## Code Size",
        "## Largest Modules",
        "## Ruff Ignores",
        "## Pyright",
        "## Pyright Strict Slice",
        "## Public Safety",
        "## Gitleaks",
        "## Demo Gates",
        "## Performance Budgets",
        "## Suppressions",
        "## Tests",
        "## Available Suites",
        "## Verification Commands",
    ):
        assert header in md, f"missing section: {header}"


# ── Public-safety self-scan ────────────────────────────────────────────────────


def test_real_output_is_public_safe():
    data = sc.build_scorecard(ROOT)
    md = sc.render_markdown(data)
    js = sc.render_json(data)
    assert sc.scan_public_safety(md, js) == []


def test_public_safety_flags_private_path():
    # Construct the trigger from parts so this test file itself stays clean of the
    # literal pattern the commit-checkpoint preflight greps for.
    planted = "/" + "Users" + "/example/.ssh/id_rsa"
    assert sc.scan_public_safety(planted)


def test_public_safety_flags_token():
    planted = "gh" + "p_" + "A" * 30
    assert sc.scan_public_safety(planted)


def test_scorecard_reports_distinct_public_safety_and_gitleaks_coverage():
    data = sc.build_scorecard(ROOT)

    assert set(data["public_safety"]["modes"]) == {"committed", "staged", "tracked"}
    assert "changed_range" not in data["public_safety"]["modes"]
    assert set(data["gitleaks"]["modes"]) == {
        "baseline",
        "changed_range",
        "fixture_smoke",
        "full_history",
    }
    assert "local-only-artifact-path" not in data["gitleaks"]["coverage"]
    assert "maintained_default_corpus" in data["gitleaks"]["coverage"]
    assert "entropy_rule" in data["gitleaks"]["coverage"]
    assert "full_git_history" in data["gitleaks"]["coverage"]
    commands = {c["name"]: c["command"] for c in data["verification_commands"]}
    assert commands["public_safety"] == "python scripts/public_safety_scan.py --tracked --staged"
    assert commands["gitleaks_baseline"] == "python scripts/gitleaks_scan.py validate-baseline"


# ── Validation catches malformed output ────────────────────────────────────────


def test_validate_flags_bad_schema_version():
    data = sc.build_scorecard(ROOT)
    data["schema_version"] = 999
    assert sc.validate(data)


def test_validate_flags_unsorted_modules():
    data = sc.build_scorecard(ROOT)
    data["largest_modules"] = list(reversed(data["largest_modules"]))
    assert sc.validate(data)


def test_validate_flags_broken_suppression_invariant():
    data = sc.build_scorecard(ROOT)
    data["suppressions"]["unreasoned_total"] += 1
    assert sc.validate(data)


def test_validate_flags_missing_section():
    data = sc.build_scorecard(ROOT)
    data["suites"] = []
    assert sc.validate(data)


# ── Entry points ───────────────────────────────────────────────────────────────


def test_main_check_returns_zero():
    assert sc.main(["--check"]) == 0


def test_run_check_returns_zero_on_live_repo():
    assert sc.run_check(ROOT) == 0


def test_main_json_emits_valid_json(capsys):
    rc = sc.main(["--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out)["schema_version"] == sc.SCHEMA_VERSION


def test_main_markdown_emits_header(capsys):
    rc = sc.main(["--format", "markdown"])
    assert rc == 0
    assert "# Quality Scorecard" in capsys.readouterr().out


def test_write_outputs_creates_md_and_json(tmp_path):
    written = sc.write_outputs(ROOT, tmp_path)
    assert len(written) == 2
    md_path = tmp_path / "scorecard.md"
    json_path = tmp_path / "scorecard.json"
    assert md_path.exists()
    assert json_path.exists()
    json.loads(json_path.read_text(encoding="utf-8"))  # valid JSON
    assert sc.scan_public_safety(md_path.read_text(encoding="utf-8")) == []


def test_write_outputs_refuses_unsafe(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "render_markdown", lambda *_: "leak /" + "Users" + "/secret")
    with pytest.raises(SystemExit):
        sc.write_outputs(ROOT, tmp_path)


def test_write_outputs_refuses_unsafe_json_only(tmp_path, monkeypatch):
    # The json arm of scan_public_safety(md, js) must also block a leak.
    monkeypatch.setattr(sc, "render_json", lambda *_: '{"leak": "/' + "Users" + '/secret"}')
    with pytest.raises(SystemExit):
        sc.write_outputs(ROOT, tmp_path)


def test_main_write_to_absolute_out_dir(tmp_path):
    # --out-dir accepts an absolute path outside the repo; --write must not crash
    # on the post-write relative_to() display.
    rc = sc.main(["--write", "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "scorecard.md").exists()
    assert (tmp_path / "scorecard.json").exists()


def test_main_markdown_refuses_unsafe(monkeypatch):
    monkeypatch.setattr(sc, "render_markdown", lambda *_: "leak /" + "Users" + "/secret")
    with pytest.raises(SystemExit):
        sc.main(["--format", "markdown"])


def test_main_json_refuses_unsafe(monkeypatch):
    # The stdout path scans both md and js regardless of --format.
    monkeypatch.setattr(sc, "render_json", lambda *_: '{"x": "/' + "Users" + '/secret"}')
    with pytest.raises(SystemExit):
        sc.main(["--format", "json"])


def test_main_both_emits_markdown_then_json(capsys):
    rc = sc.main(["--format", "both"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Quality Scorecard" in out
    payload = json.loads(out[out.index("{") :])
    assert payload["schema_version"] == sc.SCHEMA_VERSION


# ── run_check failure paths (the CI gate must actually fail) ────────────────────


def test_run_check_fails_on_validate_error(monkeypatch):
    monkeypatch.setattr(sc, "validate", lambda *_: ["boom"])
    assert sc.run_check(ROOT) == 1


def test_run_check_fails_on_public_safety_hit(monkeypatch):
    monkeypatch.setattr(sc, "scan_public_safety", lambda *_: ["leak"])
    assert sc.run_check(ROOT) == 1


def test_run_check_fails_on_stale_committed_artifacts(monkeypatch):
    monkeypatch.setattr(sc, "check_committed_artifacts", lambda *_: ["stale"])
    assert sc.run_check(ROOT) == 1


def test_run_check_fails_when_build_raises(monkeypatch):
    def _boom(_root):
        raise RuntimeError("nope")

    monkeypatch.setattr(sc, "build_scorecard", _boom)
    assert sc.run_check(ROOT) == 1


# ── validate() catches each malformed shape ────────────────────────────────────


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["pyright"].__setitem__("strict", "yes"),
        lambda d: d["code_size"].__setitem__("package_files", -1),
        lambda d: d["suites"][0].pop("present"),
        lambda d: d["verification_commands"][0].pop("command"),
        lambda d: d["gitleaks"].__setitem__("modes", ["baseline"]),
        lambda d: d["ruff"].__setitem__("global_ignore_rules", {}),
        lambda d: d["performance_budgets"].__setitem__("valid", "yes"),
        lambda d: d["performance_budgets"]["metrics"][0].pop("current"),
    ],
)
def test_validate_flags_malformed_shapes(mutate):
    data = copy.deepcopy(sc.build_scorecard(ROOT))
    mutate(data)
    assert sc.validate(data)


# ── Suppression scan: tokenize-awareness + gate parity ─────────────────────────


def test_suppression_scan_ignores_string_literals(tmp_path):
    # A type-ignore or noqa directive mentioned only inside a string or docstring
    # must NOT be counted — only real comment tokens are suppressions.
    pkg = tmp_path / "mempalace_code"
    pkg.mkdir()
    (pkg / "m.py").write_text(
        'MSG = "use # type: ignore[code]  # reason: x or # noqa here"\n'
        "x = 1  # type: ignore[bad]  # reason: a real one\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    sup = sc.collect_suppressions(tmp_path)
    # Only the real trailing comment counts; the in-string mention is ignored.
    assert sup["type_pyright_total"] == 1
    assert sup["type_pyright_unreasoned"] == 0
    assert sup["noqa_total"] == 0


def test_comment_units_falls_back_on_tokenize_error(tmp_path):
    # Unterminated triple-quoted string -> tokenize.TokenError -> raw-line fallback.
    p = tmp_path / "broken.py"
    p.write_text("# marker-xyz comment\nbroken = '''unterminated\n", encoding="utf-8")
    units = sc._comment_units(p)
    assert any("marker-xyz" in u for u in units)


def test_suppression_regexes_match_gate():
    # The scorecard advertises mirroring tests/test_type_suppressions.py — enforce it.
    ts = _load_module_from_path("ts_gate", ROOT / "tests" / "test_type_suppressions.py")
    assert sc._SUPPRESSION_RE.pattern == ts.SUPPRESSION_RE.pattern
    assert sc._ACCEPTED_RE.pattern == ts.ACCEPTED_RE.pattern


# ── Cross-version determinism: test-function counting ──────────────────────────


def test_count_test_functions_counts_pep695_generic(tmp_path):
    # AST counts a PEP 695 generic on 3.12+; on 3.11 it raises SyntaxError and the
    # regex fallback must count it too, so the value is identical across versions.
    src = "def test_plain():\n    pass\n\n\ndef test_generic[T]():\n    pass\n"
    p = tmp_path / "test_g.py"
    p.write_text(src, encoding="utf-8")
    assert sc._count_test_functions(p) == 2
    fallback = sum(1 for ln in src.splitlines() if sc._TEST_DEF_RE.match(ln))
    assert fallback == 2


def test_count_test_functions_regex_fallback_on_syntax_error(tmp_path):
    src = "def test_x(:\n    pass\n\n\ndef test_y(:\n    pass\n"
    p = tmp_path / "test_broken.py"
    p.write_text(src, encoding="utf-8")
    assert sc._count_test_functions(p) == 2


# ── Traversal excludes build/cache/venv noise ──────────────────────────────────


def test_iter_py_files_skips_noise_dirs(tmp_path):
    pkg = tmp_path / "mempalace_code"
    (pkg / "build" / "lib").mkdir(parents=True)
    (pkg / "build" / "lib" / "copy.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "stale.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "real.py").write_text("x = 1\n", encoding="utf-8")
    found = {p.name for p in sc._iter_py_files(pkg, tmp_path)}
    assert found == {"real.py"}


# ── Robustness: non-UTF-8 source fails loud, never silently miscounts ───────────


def test_run_check_fails_loud_on_non_utf8_source(tmp_path, capsys):
    root = _make_fake_repo(tmp_path)
    (root / "mempalace_code" / "bad.py").write_bytes(b"\xff\xfex = 1\n")
    assert sc.run_check(root) == 1
    assert "FAIL" in capsys.readouterr().err


# ── Extra public-safety carriers (home/temp/Windows roots) ─────────────────────


@pytest.mark.parametrize(
    "planted",
    [
        "/var/folders/ab/cd/T/x",
        "/" + "root" + "/secret",
        "/" + "opt" + "/app/secret",
        "/" + "tmp" + "/scratch",
        "C:" + "\\Users\\" + "alice",
    ],
)
def test_public_safety_flags_extra_roots(planted):
    assert sc.scan_public_safety(planted)


# ── Drift guards: committed artifacts + verify-skill command parity ─────────────


def test_committed_artifacts_are_fresh():
    data = sc.build_scorecard(ROOT)
    md = (ROOT / "docs" / "quality" / "scorecard.md").read_text(encoding="utf-8")
    js = (ROOT / "docs" / "quality" / "scorecard.json").read_text(encoding="utf-8")
    assert md == sc.render_markdown(data) + "\n", (
        "Stale scorecard.md — run: python scripts/quality_scorecard.py --write"
    )
    assert js == sc.render_json(data), (
        "Stale scorecard.json — run: python scripts/quality_scorecard.py --write"
    )


def test_verification_commands_match_verify_skill():
    instructions = (ROOT / ".claude" / "skills" / "verify" / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )
    for _name, cmd in sc._VERIFICATION_COMMANDS:
        assert cmd in instructions, f"verification command not in /verify verbatim: {cmd!r}"


def test_strict_slice_command_in_verify_and_ci():
    """AC-4: the strict-slice command stays wired into /verify and CI, and the strict
    config keeps reportMissingImports enabled rather than being weakened to pass."""
    strict_cmd = next(
        cmd for name, cmd in sc._VERIFICATION_COMMANDS if name == "typecheck_strict_slice"
    )
    assert strict_cmd == "python -m pyright -p pyrightconfig.strict.json"

    instructions = (ROOT / ".claude" / "skills" / "verify" / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )
    assert strict_cmd in instructions, "strict-slice command missing from /verify INSTRUCTIONS.md"

    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert strict_cmd in ci, "strict-slice command missing from .github/workflows/ci.yml"

    strict_config = json.loads((ROOT / "pyrightconfig.strict.json").read_text(encoding="utf-8"))
    assert strict_config["reportMissingImports"] is True
    assert strict_config["include"] == strict_config["strict"], (
        "strict slice include/strict arrays must stay identical"
    )


# ── Strict-slice metrics ───────────────────────────────────────────────────────


def test_strict_slice_in_pyright():
    data = sc.build_scorecard(ROOT)
    ss = data["pyright"]["strict_slice"]
    assert isinstance(ss["file_count"], int)
    assert ss["file_count"] >= 0
    assert isinstance(ss["paths"], list)
    assert ss["file_count"] == len(ss["paths"])
    assert ss["paths"] == sorted(ss["paths"]), "strict_slice.paths must be sorted"
    assert isinstance(ss["include_strict_match"], bool)
    # Live repo has pyrightconfig.strict.json with known entries
    assert ss["file_count"] > 0
    assert "mempalace_code/disk_budget.py" in ss["paths"]


def test_strict_slice_absent_config_gives_zero(tmp_path):
    root = _make_fake_repo(tmp_path)
    # No pyrightconfig.strict.json in fake repo
    ss = sc.collect_pyright_strict_slice(root)
    assert ss["file_count"] == 0
    assert ss["paths"] == []
    assert isinstance(ss["include_strict_match"], bool)


# ── Public-safety coverage metadata ───────────────────────────────────────────


def test_public_safety_modes_present():
    data = sc.build_scorecard(ROOT)
    pub = data["public_safety"]
    assert isinstance(pub["modes"], list)
    for mode in ("committed", "staged", "tracked"):
        assert mode in pub["modes"], f"public_safety.modes missing: {mode!r}"


def test_public_safety_modes_have_commands():
    pub = sc.collect_public_safety_coverage()
    for mode in pub["modes"]:
        assert mode in pub["commands"], f"no command for mode {mode!r}"
        assert "--" + mode in pub["commands"][mode]


# ── Demo gate metrics ──────────────────────────────────────────────────────────


def test_demo_gates_keys():
    gates = sc.build_scorecard(ROOT)["demo_gates"]
    for key in (
        "architecture_guard",
        "cli_golden_scenarios",
        "dependency_audit",
        "docs_drift_guard",
        "mcp_stdio_contracts",
    ):
        assert key in gates, f"demo_gates missing: {key!r}"
        assert gates[key]["status"] in ("present", "absent")
    # dependency_audit must be present in live repo (both gate files exist)
    assert gates["dependency_audit"]["status"] == "present"
    assert gates["architecture_guard"]["status"] == "present"
    assert gates["docs_drift_guard"]["status"] == "present"
    assert gates["cli_golden_scenarios"]["status"] == "present"
    assert gates["cli_golden_scenarios"]["count"] > 0


def test_docs_drift_guard_reports_expanded_coverage():
    """demo_gates.docs_drift_guard must name the expanded check categories (present)."""
    gates = sc.build_scorecard(ROOT)["demo_gates"]
    coverage = gates["docs_drift_guard"]["coverage"]
    assert coverage == [
        "cli_commands",
        "mcp_tools_and_profiles",
        "optional_extras",
        "release_and_dependency_gates",
        "verification_commands",
    ]


def test_docs_drift_guard_coverage_empty_on_fake_repo(tmp_path):
    root = _make_fake_repo(tmp_path)
    gates = sc.collect_demo_gates(root)
    assert gates["docs_drift_guard"]["status"] == "absent"
    assert gates["docs_drift_guard"]["coverage"] == []


def test_mcp_stdio_contract_count_equals_class_methods():
    """mcp_stdio_contracts count must equal the TestMCPStdioContracts method count in test_mcp_server.py."""
    import ast as _ast

    gates = sc.build_scorecard(ROOT)["demo_gates"]
    count_from_scorecard = gates["mcp_stdio_contracts"]["count"]

    # Derive expected count directly from the source class via AST
    tree = _ast.parse((ROOT / "tests" / "test_mcp_server.py").read_text(encoding="utf-8"))
    cls_node = next(
        n
        for n in _ast.walk(tree)
        if isinstance(n, _ast.ClassDef) and n.name == "TestMCPStdioContracts"
    )
    expected = sum(
        1
        for m in cls_node.body
        if isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and m.name.startswith("test")
    )

    assert expected > 0, "TestMCPStdioContracts must have at least one test method"
    assert count_from_scorecard == expected, (
        f"scorecard mcp_stdio_contracts count {count_from_scorecard} != "
        f"TestMCPStdioContracts method count {expected}"
    )


def test_demo_gates_all_absent_on_fake_repo(tmp_path):
    root = _make_fake_repo(tmp_path)
    gates = sc.collect_demo_gates(root)
    for key in (
        "architecture_guard",
        "cli_golden_scenarios",
        "dependency_audit",
        "docs_drift_guard",
    ):
        assert gates[key]["status"] == "absent"
    assert gates["mcp_stdio_contracts"]["count"] == 0
    assert gates["mcp_stdio_contracts"]["status"] == "absent"
    assert gates["cli_golden_scenarios"]["count"] == 0


# ── Performance-budget rows (demo_performance_budgets) ─────────────────────────

_PERF_METRIC_NAMES = (
    "mine_full",
    "mine_incremental_noop",
    "search_p95",
    "read_p95",
    "maintenance",
)


def test_demo_performance_budgets_valid_on_live_repo():
    """The committed benchmarks/demo_perf_budgets.json validates on the real repo."""
    pb = sc.build_scorecard(ROOT)["performance_budgets"]
    assert pb["valid"] is True
    assert pb["errors"] == []
    assert pb["budget_changed_because"].strip() != ""
    assert {m["name"] for m in pb["metrics"]} == set(_PERF_METRIC_NAMES)


def test_demo_performance_budgets_metrics_have_before_current_budget():
    pb = sc.build_scorecard(ROOT)["performance_budgets"]
    for m in pb["metrics"]:
        assert set(m) == {"name", "unit", "before", "current", "budget", "comparison"}
        assert m["unit"] in ("secs", "ms")
        assert isinstance(m["current"], (int, float))
        assert isinstance(m["budget"], (int, float))
        assert m["before"] is None or isinstance(m["before"], (int, float))
        # Never executed here — a fresh baseline is always <= its own hard budget.
        assert m["current"] <= m["budget"]


def test_demo_performance_budgets_renders_markdown_table():
    md = sc.render_markdown(sc.build_scorecard(ROOT))
    assert "## Performance Budgets" in md
    assert "| Metric | Unit | Before | Current | Budget |" in md
    for name in _PERF_METRIC_NAMES:
        assert f"| {name} |" in md


def test_demo_performance_budgets_missing_artifact_is_invalid(tmp_path):
    root = _make_fake_repo(tmp_path)  # no benchmarks/ directory at all
    pb = sc.collect_performance_budgets(root)
    assert pb["valid"] is False
    assert len(pb["errors"]) == 1
    assert "missing" in pb["errors"][0]
    assert pb["metrics"] == []
    # Shape still validates — "invalid" is itself a well-formed, non-gating state.
    data = sc.build_scorecard(root)
    assert sc.validate(data) == []


def test_demo_performance_budgets_malformed_artifact_fails_closed(tmp_path):
    root = _make_fake_repo(tmp_path)
    bench_dir = root / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "demo_perf_budgets.json").write_text("{not valid json", encoding="utf-8")

    pb = sc.collect_performance_budgets(root)
    assert pb["valid"] is False
    assert len(pb["errors"]) == 1
    assert "malformed" in pb["errors"][0].lower()


def test_demo_performance_budgets_before_absent_renders_baseline_absent():
    """A first-ever baseline (before=None) must render deterministically, not crash."""
    data = copy.deepcopy(sc.build_scorecard(ROOT))
    for m in data["performance_budgets"]["metrics"]:
        m["before"] = None
    md = sc.render_markdown(data)
    assert "baseline absent" in md


# ── Malformed expanded metric validation ───────────────────────────────────────


def test_malformed_expanded_metric_missing_public_safety_mode():
    data = sc.build_scorecard(ROOT)
    data["public_safety"]["modes"] = ["tracked", "staged"]  # missing "committed"
    errors = sc.validate(data)
    assert errors, "validate must flag a missing public-safety mode"
    assert any("committed" in e for e in errors)


def test_malformed_expanded_metric_non_integer_scenario_count():
    data = sc.build_scorecard(ROOT)
    data["demo_gates"]["cli_golden_scenarios"]["count"] = "five"
    errors = sc.validate(data)
    assert errors, "validate must flag a non-integer scenario count"


def test_malformed_expanded_metric_missing_strict_slice():
    data = sc.build_scorecard(ROOT)
    del data["pyright"]["strict_slice"]
    errors = sc.validate(data)
    assert errors, "validate must flag absent strict_slice"


def test_malformed_expanded_metric_bad_strict_slice_count():
    data = sc.build_scorecard(ROOT)
    data["pyright"]["strict_slice"]["file_count"] = -1
    errors = sc.validate(data)
    assert errors, "validate must flag negative strict_slice.file_count"


# ── No-subprocess guarantee for demo-gate collectors ──────────────────────────


def test_no_subprocess_in_demo_gates(monkeypatch):
    """Demo-gate collection runs on file-presence and AST reads only — no subprocess."""
    import subprocess

    def _raise(*args, **kwargs):
        raise AssertionError("subprocess must not be called during demo_gates collection")

    monkeypatch.setattr(subprocess, "run", _raise)
    monkeypatch.setattr(subprocess, "check_output", _raise)
    monkeypatch.setattr(subprocess, "Popen", _raise)

    gates = sc.collect_demo_gates(ROOT)
    assert isinstance(gates, dict)
    assert "mcp_stdio_contracts" in gates
    assert isinstance(gates["mcp_stdio_contracts"]["count"], int)
    assert gates["dependency_audit"]["status"] == "present"
