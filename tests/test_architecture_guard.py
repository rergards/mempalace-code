"""Tests for scripts/architecture_guard.py — stdlib AST import-boundary guard.

Positive/negative fixtures build synthetic ``mempalace_code/`` trees under
``tmp_path`` (per the guard's own design note: production-boundary
enforcement excludes ``tests/``, so negative cases need their own fixture
roots). The real repository tree is also exercised directly to prove the
guard reports zero violations and zero cycles against tracked source.
"""

from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "architecture_guard", ROOT / "scripts" / "architecture_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always resolves to a non-None spec
    sys.modules["architecture_guard"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


guard = _load_guard()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_embedding_manifest_rejects_torch_and_requires_custom_owner(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "storage.py", "")
    _write(
        tmp_path / "pyproject.toml",
        """[project]
dependencies = ["fastembed>=0.8", "onnxruntime>=1.20", "torch>=2"]
[project.optional-dependencies]
custom-models = []
""",
    )

    result = guard.evaluate(tmp_path)

    assert result.ok is False
    assert "forbidden default runtime dependency: torch" in result.manifest_violations
    assert "custom-models must own sentence-transformers" in result.manifest_violations


# ── AC-1: clean graph exits 0 ───────────────────────────────────────────────────


def test_clean_graph_has_no_violations_or_cycles(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "__init__.py", "")
    _write(tmp_path / "mempalace_code" / "storage.py", "import os\n")
    _write(tmp_path / "mempalace_code" / "config.py", "import json\n")
    _write(
        tmp_path / "mempalace_code" / "cli.py",
        "from .storage import open_store\n",
    )

    result = guard.evaluate(tmp_path)

    assert result.violations == []
    assert result.cycles == []
    assert result.ok is True


def test_real_repository_tree_is_clean():
    """The actual tracked tree must satisfy the boundary and cycle rules."""
    result = guard.evaluate(ROOT)

    assert result.violations == [], result.violations
    assert result.cycles == [], result.cycles
    assert result.ok is True
    assert sum(len(files) for files in result.layers.values()) > 50


def test_guard_builds_import_graph_from_stdlib_ast_without_project_import(
    tmp_path: Path, monkeypatch
):
    """AC-1: the graph comes from ast.parse, never from importing mempalace_code."""
    _write(tmp_path / "mempalace_code" / "storage.py", "from .cli import main\n")
    _write(tmp_path / "mempalace_code" / "cli.py", "")

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mempalace_code" or name.startswith("mempalace_code."):
            raise AssertionError(f"evaluate() must not import {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    result = guard.evaluate(tmp_path)

    assert result.layers["storage"] == ["mempalace_code/storage.py"]
    violation = result.violations[0]
    assert violation.path == ("mempalace_code/storage.py", "mempalace_code/cli.py")


# ── AC-3: explicit layer names with matched file paths ─────────────────────────


def test_layer_names_are_explicit_and_public():
    assert guard.LAYER_NAMES == (
        "core",
        "storage",
        "mining",
        "cli",
        "mcp",
        "scripts",
    )


def test_print_layers_lists_matched_files(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "__init__.py", "")
    _write(tmp_path / "mempalace_code" / "storage.py", "")
    _write(tmp_path / "mempalace_code" / "config.py", "")
    _write(tmp_path / "mempalace_code" / "miner.py", "")
    _write(tmp_path / "mempalace_code" / "cli.py", "")
    _write(tmp_path / "mempalace_code" / "mcp_server.py", "")
    _write(tmp_path / "scripts" / "some_tool.py", "")

    result = guard.evaluate(tmp_path)
    output = guard.format_layers(result)

    for name in guard.LAYER_NAMES:
        assert f"{name} (" in output
    assert "mempalace_code/storage.py" in output
    assert "mempalace_code/config.py" in output
    assert "mempalace_code/miner.py" in output
    assert "mempalace_code/cli.py" in output
    assert "mempalace_code/mcp_server.py" in output
    assert "scripts/some_tool.py" in output


def test_print_layers_cli_exits_zero(tmp_path: Path, capsys):
    _write(tmp_path / "mempalace_code" / "storage.py", "")

    exit_code = guard.main(["--root", str(tmp_path), "--print-layers"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "storage (" in captured.out


# ── AC-2: direct and transitive forbidden imports ───────────────────────────────


def test_direct_forbidden_import_from_storage_to_cli(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "storage.py", "from .cli import main\n")
    _write(tmp_path / "mempalace_code" / "cli.py", "")

    result = guard.evaluate(tmp_path)

    assert result.ok is False
    assert len(result.violations) == 1
    violation = result.violations[0]
    assert violation.source == "mempalace_code/storage.py"
    assert violation.target == "mempalace_code/cli.py"
    assert violation.source_layer == "storage"
    assert violation.target_layer == "cli"
    assert violation.path == ("mempalace_code/storage.py", "mempalace_code/cli.py")


def test_direct_forbidden_import_from_mining_to_mcp(tmp_path: Path):
    _write(
        tmp_path / "mempalace_code" / "mining" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "mempalace_code" / "mining" / "orchestrator.py",
        "from ..mcp_server import serve\n",
    )
    _write(tmp_path / "mempalace_code" / "mcp_server.py", "")

    result = guard.evaluate(tmp_path)

    assert result.ok is False
    violation = next(v for v in result.violations if v.source.endswith("orchestrator.py"))
    assert violation.target_layer == "mcp"


def test_transitive_forbidden_import_reports_full_hop_path(tmp_path: Path):
    _write(
        tmp_path / "mempalace_code" / "storage.py",
        "from .helper import do_thing\n",
    )
    _write(
        tmp_path / "mempalace_code" / "helper.py",
        "from .mcp_server import serve\n",
    )
    _write(tmp_path / "mempalace_code" / "mcp_server.py", "")

    result = guard.evaluate(tmp_path)

    assert result.ok is False
    assert len(result.violations) == 1
    violation = result.violations[0]
    assert violation.path == (
        "mempalace_code/storage.py",
        "mempalace_code/helper.py",
        "mempalace_code/mcp_server.py",
    )
    report = guard.format_report(result)
    assert (
        "mempalace_code/storage.py -> mempalace_code/helper.py -> mempalace_code/mcp_server.py"
        in report
    )


def test_allowed_edges_are_not_flagged(tmp_path: Path):
    """mining -> storage and core -> cli (package entry points) are not forbidden."""
    _write(tmp_path / "mempalace_code" / "__init__.py", "from .cli import main\n")
    _write(tmp_path / "mempalace_code" / "cli.py", "")
    _write(
        tmp_path / "mempalace_code" / "mining" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "mempalace_code" / "mining" / "orchestrator.py",
        "from ..storage import open_store\n",
    )
    _write(tmp_path / "mempalace_code" / "storage.py", "")

    result = guard.evaluate(tmp_path)

    assert result.violations == []
    assert result.ok is True


def test_storage_config_and_mining_cannot_reach_cli_or_mcp(tmp_path: Path):
    """AC-2: storage, config, miner, and mining/ fail against active forbidden layers."""
    _write(tmp_path / "mempalace_code" / "storage.py", "from .cli import main\n")
    _write(tmp_path / "mempalace_code" / "config.py", "from .mcp_server import serve\n")
    _write(tmp_path / "mempalace_code" / "miner.py", "from .mcp_server import serve\n")
    _write(tmp_path / "mempalace_code" / "mining" / "__init__.py", "")
    _write(
        tmp_path / "mempalace_code" / "mining" / "orchestrator.py",
        "from ..cli import main\n",
    )
    _write(tmp_path / "mempalace_code" / "cli.py", "")
    _write(tmp_path / "mempalace_code" / "mcp_server.py", "")

    result = guard.evaluate(tmp_path)

    assert result.ok is False
    offenders = {(v.source, v.target_layer) for v in result.violations}
    assert ("mempalace_code/storage.py", "cli") in offenders
    assert ("mempalace_code/config.py", "mcp") in offenders
    assert ("mempalace_code/miner.py", "mcp") in offenders
    assert ("mempalace_code/mining/orchestrator.py", "cli") in offenders


# ── AC-4: cycle detection, separate from boundary violations ───────────────────


def test_cycle_between_core_modules_is_reported(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "a.py", "from .b import thing_b\n")
    _write(tmp_path / "mempalace_code" / "b.py", "from .a import thing_a\n")

    result = guard.evaluate(tmp_path)

    assert result.violations == []  # not a boundary problem
    assert result.ok is False
    assert len(result.cycles) == 1
    cycle = result.cycles[0]
    assert set(cycle) == {"mempalace_code/a.py", "mempalace_code/b.py"}


def test_no_cycle_for_one_directional_chain(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "a.py", "from .b import thing_b\n")
    _write(tmp_path / "mempalace_code" / "b.py", "from .c import thing_c\n")
    _write(tmp_path / "mempalace_code" / "c.py", "")

    result = guard.evaluate(tmp_path)

    assert result.cycles == []
    assert result.ok is True


# ── AC-4: TYPE_CHECKING imports are bucketed separately, not enforced ──────────


def test_type_checking_import_is_not_a_boundary_violation(tmp_path: Path):
    _write(
        tmp_path / "mempalace_code" / "mining" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "mempalace_code" / "mining" / "orchestrator.py",
        "from __future__ import annotations\n\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from ..cli import CliContext\n",
    )
    _write(tmp_path / "mempalace_code" / "cli.py", "")

    result = guard.evaluate(tmp_path)

    assert result.violations == []
    assert result.ok is True
    assert len(result.type_checking_imports) == 1
    tc = result.type_checking_imports[0]
    assert tc.source == "mempalace_code/mining/orchestrator.py"
    assert tc.target == "mempalace_code/cli.py"


def test_type_checking_import_does_not_create_a_cycle(tmp_path: Path):
    _write(
        tmp_path / "mempalace_code" / "a.py",
        "from __future__ import annotations\n\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from .b import ThingB\n",
    )
    _write(tmp_path / "mempalace_code" / "b.py", "from .a import thing_a\n")

    result = guard.evaluate(tmp_path)

    assert result.cycles == []
    assert len(result.type_checking_imports) == 1


def test_else_branch_of_type_checking_if_counts_as_runtime(tmp_path: Path):
    _write(
        tmp_path / "mempalace_code" / "mining" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "mempalace_code" / "mining" / "orchestrator.py",
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    pass\n"
        "else:\n"
        "    from ..cli import main\n",
    )
    _write(tmp_path / "mempalace_code" / "cli.py", "")

    result = guard.evaluate(tmp_path)

    assert result.type_checking_imports == []
    assert result.ok is False
    assert len(result.violations) == 1


def test_direct_transitive_cycle_and_type_checking_imports_are_reported_separately(
    tmp_path: Path,
):
    """AC-4: one fixture exercising all four buckets at once, each landing separately."""
    _write(
        tmp_path / "mempalace_code" / "storage.py",
        "from .cli import main\nfrom .helper import do_thing\n",
    )
    _write(tmp_path / "mempalace_code" / "cli.py", "")
    _write(tmp_path / "mempalace_code" / "helper.py", "from .mcp_server import serve\n")
    _write(tmp_path / "mempalace_code" / "mcp_server.py", "")
    _write(tmp_path / "mempalace_code" / "a.py", "from .b import thing_b\n")
    _write(tmp_path / "mempalace_code" / "b.py", "from .a import thing_a\n")
    _write(tmp_path / "mempalace_code" / "mining" / "__init__.py", "")
    _write(
        tmp_path / "mempalace_code" / "mining" / "orchestrator.py",
        "from __future__ import annotations\n\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from ..cli import CliContext\n",
    )

    result = guard.evaluate(tmp_path)

    assert result.ok is False

    direct = [
        v
        for v in result.violations
        if v.path == ("mempalace_code/storage.py", "mempalace_code/cli.py")
    ]
    assert len(direct) == 1

    transitive = [
        v
        for v in result.violations
        if v.path
        == (
            "mempalace_code/storage.py",
            "mempalace_code/helper.py",
            "mempalace_code/mcp_server.py",
        )
    ]
    assert len(transitive) == 1

    assert len(result.cycles) == 1
    assert set(result.cycles[0]) == {"mempalace_code/a.py", "mempalace_code/b.py"}

    assert len(result.type_checking_imports) == 1
    tc = result.type_checking_imports[0]
    assert tc.source == "mempalace_code/mining/orchestrator.py"
    assert tc.target == "mempalace_code/cli.py"
    assert not any(v.source == tc.source and v.target == tc.target for v in result.violations)


# ── AC-5: file-level diagnostics in text output ─────────────────────────────────


def test_format_report_includes_source_and_target_layer_names(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "storage.py", "from .cli import main\n")
    _write(tmp_path / "mempalace_code" / "cli.py", "")

    result = guard.evaluate(tmp_path)
    report = guard.format_report(result)

    assert "storage:mempalace_code/storage.py -> cli:mempalace_code/cli.py" in report
    assert "path: mempalace_code/storage.py -> mempalace_code/cli.py" in report
    assert "FAIL" in report


def test_format_report_ok_summary(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "storage.py", "")

    result = guard.evaluate(tmp_path)
    report = guard.format_report(result)

    assert "architecture-guard: OK" in report


def test_cli_report_includes_file_level_violation_cycle_and_type_checking_paths(
    tmp_path: Path, capsys
):
    """AC-5: CLI text output surfaces layers, hop paths, cycles, TYPE_CHECKING lines, exit=1."""
    _write(tmp_path / "mempalace_code" / "storage.py", "from .cli import main\n")
    _write(tmp_path / "mempalace_code" / "cli.py", "")
    _write(tmp_path / "mempalace_code" / "a.py", "from .b import thing_b\n")
    _write(tmp_path / "mempalace_code" / "b.py", "from .a import thing_a\n")
    _write(tmp_path / "mempalace_code" / "mining" / "__init__.py", "")
    _write(
        tmp_path / "mempalace_code" / "mining" / "orchestrator.py",
        "from __future__ import annotations\n\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from ..cli import CliContext\n",
    )

    exit_code = guard.main(["--root", str(tmp_path)])

    assert exit_code == 1
    report = capsys.readouterr().err
    assert "storage:mempalace_code/storage.py -> cli:mempalace_code/cli.py" in report
    assert "path: mempalace_code/storage.py -> mempalace_code/cli.py" in report
    assert (
        "mempalace_code/a.py -> mempalace_code/b.py -> mempalace_code/a.py" in report
        or "mempalace_code/b.py -> mempalace_code/a.py -> mempalace_code/b.py" in report
    )
    assert "TYPE_CHECKING-only imports" in report
    assert "mempalace_code/mining/orchestrator.py" in report
    assert "mempalace_code/cli.py" in report
    assert "FAIL" in report


# ── CLI exit codes ───────────────────────────────────────────────────────────────


def test_main_exits_zero_on_clean_fixture(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "storage.py", "import os\n")

    assert guard.main(["--root", str(tmp_path)]) == 0


def test_main_exits_nonzero_on_violation_fixture(tmp_path: Path):
    _write(tmp_path / "mempalace_code" / "storage.py", "from .cli import main\n")
    _write(tmp_path / "mempalace_code" / "cli.py", "")

    assert guard.main(["--root", str(tmp_path)]) == 1


def test_classify_layer_matches_expected_files():
    assert guard.classify_layer("mempalace_code/storage.py") == "storage"
    assert guard.classify_layer("mempalace_code/config.py") == "storage"
    assert guard.classify_layer("mempalace_code/miner.py") == "mining"
    assert guard.classify_layer("mempalace_code/mining/scanner.py") == "mining"
    assert guard.classify_layer("mempalace_code/cli.py") == "cli"
    assert guard.classify_layer("mempalace_code/cli_commands/watch.py") == "cli"
    assert guard.classify_layer("mempalace_code/mcp_server.py") == "mcp"
    assert guard.classify_layer("mempalace_code/mcp/dispatch.py") == "mcp"
    assert guard.classify_layer("scripts/quality_scorecard.py") == "scripts"
    assert guard.classify_layer("mempalace_code/searcher.py") == "core"
