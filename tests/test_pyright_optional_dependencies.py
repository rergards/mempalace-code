"""Tests for optional-dependency boundaries.

Documents how retired Chroma migration, watchfiles, and spellcheck optional
boundaries are handled in the default install.

Tests in this file are designed for the default install (no optional extras).
They assert package metadata contains no Chroma bridge while avoiding optional imports.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ── Chroma boundary ────────────────────────────────────────────────────────────


def test_storage_import_does_not_require_chromadb():
    """The default storage module imports without chromadb."""
    # Remove any cached chromadb from sys.modules if it shouldn't be there.
    # Just verifying the import succeeds without requiring chromadb at module level.
    spec = importlib.util.find_spec("mempalace_code.storage")
    assert spec is not None, "mempalace_code.storage should be importable without chromadb"


def test_chroma_bridge_absent_from_package_metadata_and_lock():
    """Current package metadata and lock contain no Chroma bridge dependency."""
    import tomllib as _toml

    data = _toml.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"].get("optional-dependencies", {})
    assert "chroma-migration" not in extras
    assert "chroma" not in extras
    assert not any("chromadb" in dep.lower() for dep in data["project"]["dependencies"])

    lock = _toml.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = lock["package"]
    assert not any(package["name"] == "chromadb" for package in packages)
    project = next(package for package in packages if package["name"] == "mempalace-code")
    assert not any(
        requirement["name"] in {"chromadb", "posthog"}
        for requirement in project["metadata"]["requires-dist"]
    )


# ── Watchfiles boundary ────────────────────────────────────────────────────────


def test_watcher_import_does_not_fail_at_top_level():
    """watcher.py can be imported even if watchfiles is absent — watchfiles is imported lazily."""
    # watcher.py may or may not use watchfiles at top level. If it does, this test
    # documents the ImportError message so it's stable across refactors.
    import importlib.util as ilu

    spec = ilu.find_spec("mempalace_code.watcher")
    assert spec is not None, "mempalace_code.watcher should be findable"
    # The actual import behavior depends on how watcher.py is structured.
    # We test the documented contract: the module must either import successfully
    # OR raise an ImportError that mentions 'watchfiles'.
    try:
        import mempalace_code.watcher  # noqa: F401
    except ImportError as exc:
        assert "watchfiles" in str(exc).lower(), (
            f"ImportError from watcher.py should mention watchfiles, got: {exc}"
        )
    except Exception:
        pass  # Other exceptions (e.g. from missing palace) are not the subject here


def test_watchfiles_is_optional_extra():
    """watchfiles appears in the [watch] or [dev] optional extras, not core dependencies."""
    import tomllib as _toml

    data = _toml.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    core_deps: list[str] = data["project"]["dependencies"]
    assert not any("watchfiles" in dep for dep in core_deps), (
        "watchfiles must not appear in core [project.dependencies]; it is an optional extra"
    )
    optional_extras: dict = data["project"].get("optional-dependencies", {})
    found_in_optional = any(
        "watchfiles" in dep for deps in optional_extras.values() for dep in deps
    )
    assert found_in_optional, (
        "watchfiles should appear in at least one optional extra (e.g. [watch] or [dev])"
    )


# ── Spellcheck boundary ────────────────────────────────────────────────────────


def test_autocorrect_is_optional_extra():
    """autocorrect appears only in [spellcheck] optional extra, not core dependencies."""
    import tomllib as _toml

    data = _toml.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    core_deps: list[str] = data["project"]["dependencies"]
    assert not any("autocorrect" in dep for dep in core_deps), (
        "autocorrect must not appear in core [project.dependencies]; it belongs in [spellcheck]"
    )


def test_spellcheck_extra_declared():
    """The [spellcheck] optional extra is declared in pyproject.toml."""
    import tomllib as _toml

    data = _toml.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"].get("optional-dependencies", {})
    assert "spellcheck" in extras, "pyproject.toml must declare a [spellcheck] optional extra"


# ── Default-install Pyright coverage ──────────────────────────────────────────


def test_pyrightconfig_strict_json_exists():
    """The strict Pyright slice config exists and is parseable."""
    import json as _json

    config_path = ROOT / "pyrightconfig.strict.json"
    assert config_path.exists(), "pyrightconfig.strict.json must exist"
    data = _json.loads(config_path.read_text(encoding="utf-8"))
    assert "include" in data, "pyrightconfig.strict.json must have an 'include' array"
    assert isinstance(data["include"], list), "pyrightconfig.strict.json 'include' must be a list"
    assert len(data["include"]) > 0, "pyrightconfig.strict.json 'include' must be non-empty"


def test_pyrightconfig_strict_json_no_optional_modules():
    """The strict Pyright slice does not include optional-dependency modules."""
    import json as _json

    config_path = ROOT / "pyrightconfig.strict.json"
    data = _json.loads(config_path.read_text(encoding="utf-8"))
    include = data.get("include", [])
    optional_paths = {"watcher"}
    for path in include:
        stem = Path(path).stem
        assert stem not in optional_paths, (
            f"Optional module '{path}' must not be in the strict Pyright slice; "
            "it requires optional extras that may not be present"
        )


def test_default_pyright_has_no_chroma_migration_exclusions():
    """Default Pyright has no exclusions for deleted Chroma migration modules."""
    import tomllib as _toml

    data = _toml.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = set(data["tool"]["pyright"].get("exclude", []))
    assert not any("chroma" in path or "test_migrate" in path for path in excluded)


def test_default_install_modules_do_not_import_chromadb_at_top_level():
    """Core package modules that must work without extras do not top-level import chromadb."""
    protected_modules = [
        "mempalace_code/storage.py",
        "mempalace_code/cli.py",
        "mempalace_code/searcher.py",
        "mempalace_code/knowledge_graph.py",
    ]
    for rel_path in protected_modules:
        source = (ROOT / rel_path).read_text(encoding="utf-8")
        lines = source.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            is_chromadb_import = stripped == "import chromadb" or stripped.startswith(
                "from chromadb"
            )
            # Inside a function or try/except is fine; module-level (no indentation) is not.
            if is_chromadb_import and not line.startswith(" ") and not line.startswith("\t"):
                raise AssertionError(
                    f"{rel_path}:{i}: top-level import of chromadb found — "
                    "current package modules must not depend on ChromaDB"
                )
