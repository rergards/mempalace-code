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
        "largest_modules",
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
    for name in ("cli", "mcp_stdio", "migrate_storage_smoke"):
        assert name in suites
        assert suites[name]["present"] is True


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
        lambda d: d["ruff"].__setitem__("global_ignore_rules", {}),
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
