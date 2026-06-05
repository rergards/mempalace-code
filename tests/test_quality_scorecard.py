"""
test_quality_scorecard.py — Tests for scripts/quality_scorecard.py.

Covers the scorecard's output shape, deterministic behavior, public-safety
self-scan, and the --check / --write entry points. Metric *logic* is exercised
against a hermetic synthetic repo so the assertions do not drift as the real
repository grows; determinism and public-safety are checked against the live
tree.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# ── Load the scorecard module from scripts/ without installing it ──────────────

ROOT = Path(__file__).parent.parent
_sc_path = ROOT / "scripts" / "quality_scorecard.py"
_spec = importlib.util.spec_from_file_location("quality_scorecard", _sc_path)
sc = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]  # reason: spec_from_file_location is non-None for an existing file
_spec.loader.exec_module(sc)  # type: ignore[union-attr]  # reason: loader is a real Loader at runtime but typed Optional


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
