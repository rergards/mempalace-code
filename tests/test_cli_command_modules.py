"""
test_cli_command_modules.py — Import contract tests for the cli_commands package.

Verifies:
  - mempalace_code.cli still exports the stable public symbols
  - Each command module can be imported without eagerly loading heavy runtime deps
  - Each expected command name maps to a callable handler in the owning module
  - python -m mempalace_code.cli does not emit the runpy RuntimeWarning (AC-1, AC-2)
"""

import subprocess
import sys
import types

import pytest

_RUNPY_WARNING = "RuntimeWarning: 'mempalace_code.cli' found in sys.modules"


def test_no_runpy_warning_on_help():
    """AC-1: python -m mempalace_code.cli --help prints help and emits no runpy RuntimeWarning."""
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "mempalace_code.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"--help should exit 0; stderr={result.stderr!r}"
    assert _RUNPY_WARNING not in result.stderr, (
        f"runpy RuntimeWarning must be absent; stderr={result.stderr!r}"
    )
    assert "usage:" in result.stdout, "help output must contain 'usage:'"


def test_no_runpy_warning_on_unknown_command():
    """AC-2: python -m mempalace_code.cli <unknown> reports arg error only, no runpy warning."""
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "mempalace_code.cli", "does-not-exist"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "unknown command should exit non-zero"
    assert _RUNPY_WARNING not in result.stderr, (
        f"runpy RuntimeWarning must be absent; stderr={result.stderr!r}"
    )
    assert "invalid choice" in result.stderr or "error:" in result.stderr, (
        f"stderr must describe the invalid command; stderr={result.stderr!r}"
    )


def test_search_help_describes_semantic_verbatim_behavior():
    """Search help should not imply exact keyword search semantics."""
    result = subprocess.run(
        [sys.executable, "-m", "mempalace_code.cli", "search", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"search --help should exit 0; stderr={result.stderr!r}"
    assert "Semantic search" in result.stdout
    assert "verbatim stored text" in result.stdout
    assert "Find anything, exact words" not in result.stdout


def test_package_main_is_callable():
    """AC-3: import mempalace_code; mempalace_code.main must be callable for console-script compat."""
    import mempalace_code

    assert callable(mempalace_code.main), "mempalace_code.main must be callable"


def test_cli_module_exports_stable_entry_points():
    """AC-1/INV-2: mempalace_code.cli must export main, main_alias, install_legacy_alias, fetch_model."""
    import mempalace_code.cli as cli

    assert callable(cli.main), "main must be callable"
    assert callable(cli.main_alias), "main_alias must be callable"
    assert callable(cli.install_legacy_alias), "install_legacy_alias must be callable"
    assert callable(cli.fetch_model), "fetch_model must be callable"


def test_cli_commands_package_importable():
    """Each command module in cli_commands must be importable."""
    modules = [
        "mempalace_code.cli_commands",
        "mempalace_code.cli_commands.common",
        "mempalace_code.cli_commands.alias",
        "mempalace_code.cli_commands.agent_plugin",
        "mempalace_code.cli_commands.model",
        "mempalace_code.cli_commands.ingest",
        "mempalace_code.cli_commands.query",
        "mempalace_code.cli_commands.maintenance",
        "mempalace_code.cli_commands.watch",
        "mempalace_code.cli_commands.backup_restore",
        "mempalace_code.cli_commands.diary",
        "mempalace_code.cli_commands.export_import",
    ]
    for mod_name in modules:
        mod = __import__(mod_name, fromlist=["_"])
        assert isinstance(mod, types.ModuleType), f"{mod_name} must be a module"


def test_no_eager_heavy_imports_on_cli_import():
    """INV-3: importing mempalace_code.cli must not pull in sentence_transformers, watchfiles, or lancedb."""
    heavy = {"sentence_transformers", "watchfiles", "lancedb"}

    # Record which heavy modules were present before the import
    already_loaded = heavy & set(sys.modules)

    # Re-importing after it's already in sys.modules is a no-op, so we need to
    # ensure we're checking that the import path itself doesn't drag them in.
    # The test is most useful when run in isolation; here we validate that the
    # module is importable AND that none of the heavy deps are newly added.
    pre_modules = set(sys.modules)
    import mempalace_code.cli  # noqa: F401 — import side effect is the test

    post_modules = set(sys.modules)
    newly_loaded = (post_modules - pre_modules) & heavy

    # Only fail for modules that were NOT already present before our import
    unexpected = newly_loaded - already_loaded
    assert not unexpected, f"importing mempalace_code.cli must not eagerly load: {unexpected}"


def test_alias_module_exports():
    """alias.py must export CANONICAL_CLI_COMMAND, LEGACY_CLI_ALIAS, install_legacy_alias, main_alias."""
    from mempalace_code.cli_commands import alias

    assert alias.CANONICAL_CLI_COMMAND == "mempalace-code"
    assert alias.LEGACY_CLI_ALIAS == "mempalace"
    assert callable(alias.install_legacy_alias)
    assert callable(alias.main_alias)
    assert callable(alias.cmd_install_alias)


def test_agent_plugin_module_exports():
    """agent_plugin.py must export cmd_agent_plugin."""
    from mempalace_code.cli_commands import agent_plugin

    assert callable(agent_plugin.cmd_agent_plugin)


def test_model_module_exports():
    """model.py must export fetch_model and cmd_fetch_model."""
    from mempalace_code.cli_commands import model

    assert callable(model.fetch_model)
    assert callable(model.cmd_fetch_model)


def test_ingest_module_exports():
    """ingest.py must export the expected handler functions."""
    from mempalace_code.cli_commands import ingest

    for name in (
        "cmd_init",
        "cmd_onboarding",
        "cmd_mine",
        "_resolve_spellcheck",
        "cmd_mine_all",
        "cmd_split",
        "cmd_status",
    ):
        assert callable(getattr(ingest, name)), f"ingest.{name} must be callable"


def test_query_module_exports():
    """query.py must export cmd_search, cmd_wakeup, cmd_compress."""
    from mempalace_code.cli_commands import query

    for name in ("cmd_search", "cmd_wakeup", "cmd_compress"):
        assert callable(getattr(query, name)), f"query.{name} must be callable"


def test_maintenance_module_exports():
    """maintenance.py must export cmd_health, cmd_cleanup, cmd_repair, cmd_migrate_storage."""
    from mempalace_code.cli_commands import maintenance

    for name in ("cmd_health", "cmd_cleanup", "cmd_repair", "cmd_migrate_storage"):
        assert callable(getattr(maintenance, name)), f"maintenance.{name} must be callable"


def test_watch_module_exports():
    """watch.py must export cmd_watch, cmd_watch_schedule, cmd_watch_status."""
    from mempalace_code.cli_commands import watch

    for name in ("cmd_watch", "cmd_watch_schedule", "cmd_watch_status"):
        assert callable(getattr(watch, name)), f"watch.{name} must be callable"


def test_backup_restore_module_exports():
    """backup_restore.py must export cmd_backup, cmd_backup_create, cmd_backup_list, cmd_restore."""
    from mempalace_code.cli_commands import backup_restore

    for name in (
        "cmd_backup",
        "cmd_backup_create",
        "cmd_backup_list",
        "cmd_backup_schedule",
        "cmd_restore",
    ):
        assert callable(getattr(backup_restore, name)), f"backup_restore.{name} must be callable"


def test_diary_module_exports():
    """diary.py must export cmd_diary_write and cmd_diary."""
    from mempalace_code.cli_commands import diary

    assert callable(diary.cmd_diary_write)
    assert callable(diary.cmd_diary)


def test_export_import_module_exports():
    """export_import.py must export cmd_export and cmd_import."""
    from mempalace_code.cli_commands import export_import

    assert callable(export_import.cmd_export)
    assert callable(export_import.cmd_import)


def test_install_legacy_alias_is_same_object_as_in_alias_module():
    """cli.install_legacy_alias must be the same function as alias.install_legacy_alias (no copy)."""
    import mempalace_code.cli as cli
    from mempalace_code.cli_commands import alias

    assert cli.install_legacy_alias is alias.install_legacy_alias


def test_fetch_model_is_same_object_as_in_model_module():
    """cli.fetch_model must be the same function as model.fetch_model (no copy)."""
    import mempalace_code.cli as cli
    from mempalace_code.cli_commands import model

    assert cli.fetch_model is model.fetch_model


def _install_fake_fetch_model(monkeypatch, calls, *, fail_local=False):
    class FakeSentenceTransformer:
        def __init__(self, model_name, **kwargs):
            calls.append((model_name, kwargs))
            if fail_local and kwargs.get("local_files_only"):
                raise RuntimeError("local model unavailable")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )


def test_fetch_model_uses_cached_model_without_download(tmp_path, monkeypatch, capsys):
    """Cached fetch-model must not perform an online-capable load."""
    from mempalace_code.cli_commands import model
    from mempalace_code.storage import DEFAULT_EMBED_MODEL

    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    cache_dir = model._model_cache_dir(DEFAULT_EMBED_MODEL)
    assert cache_dir is not None
    (cache_dir / "refs").mkdir(parents=True)
    (cache_dir / "snapshots" / "snapshot").mkdir(parents=True)

    calls = []
    _install_fake_fetch_model(monkeypatch, calls)

    model.fetch_model(DEFAULT_EMBED_MODEL)

    assert calls == [(DEFAULT_EMBED_MODEL, {"local_files_only": True})]
    output = capsys.readouterr().out
    assert "already available locally" in output
    assert "Downloading model" not in output


def test_fetch_model_downloads_after_local_cache_miss(monkeypatch, capsys):
    """Uncached fetch-model probes local files first, then performs one online load."""
    from mempalace_code.cli_commands import model
    from mempalace_code.storage import DEFAULT_EMBED_MODEL

    calls = []
    _install_fake_fetch_model(monkeypatch, calls, fail_local=True)

    model.fetch_model(DEFAULT_EMBED_MODEL)

    assert calls == [
        (DEFAULT_EMBED_MODEL, {"local_files_only": True}),
        (DEFAULT_EMBED_MODEL, {"local_files_only": False}),
    ]
    output = capsys.readouterr().out
    assert "Downloading model" in output
    assert "Waiting for model download" in output


def test_fetch_model_force_skips_local_probe(monkeypatch, capsys):
    """--force must re-download instead of accepting a local cached load."""
    from mempalace_code.cli_commands import model
    from mempalace_code.storage import DEFAULT_EMBED_MODEL

    calls = []
    _install_fake_fetch_model(monkeypatch, calls)

    model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    assert calls == [(DEFAULT_EMBED_MODEL, {"local_files_only": False})]
    assert "Waiting for model download" in capsys.readouterr().out


def test_fetch_model_existing_local_path_does_not_retry_online(tmp_path, monkeypatch):
    """An existing filesystem model path must not be interpreted as a remote repo fallback."""
    from mempalace_code.cli_commands import model

    model_path = tmp_path / "local-model"
    model_path.mkdir()
    calls = []
    _install_fake_fetch_model(monkeypatch, calls, fail_local=True)

    with pytest.raises(RuntimeError, match="local model unavailable"):
        model.fetch_model(str(model_path))

    assert calls == [(str(model_path), {"local_files_only": True})]


def test_main_alias_is_same_object_as_in_alias_module():
    """cli.main_alias must be the same function as alias.main_alias (no copy)."""
    import mempalace_code.cli as cli
    from mempalace_code.cli_commands import alias

    assert cli.main_alias is alias.main_alias


def test_dispatch_keys_cover_all_expected_commands():
    """Every expected CLI subcommand must map to a callable handler in its owning module.

    A missing or misnamed handler would cause a KeyError at dispatch time.
    """
    from mempalace_code.cli_commands import (
        agent_plugin,
        alias,
        backup_restore,
        diary,
        export_import,
        ingest,
        maintenance,
        model,
        query,
        watch,
    )

    expected: dict = {
        "init": ingest.cmd_init,
        "onboarding": ingest.cmd_onboarding,
        "mine": ingest.cmd_mine,
        "mine-all": ingest.cmd_mine_all,
        "watch": watch.cmd_watch,
        "split": ingest.cmd_split,
        "search": query.cmd_search,
        "compress": query.cmd_compress,
        "wake-up": query.cmd_wakeup,
        "migrate-storage": maintenance.cmd_migrate_storage,
        "health": maintenance.cmd_health,
        "cleanup": maintenance.cmd_cleanup,
        "repair": maintenance.cmd_repair,
        "status": ingest.cmd_status,
        "diary": diary.cmd_diary,
        "fetch-model": model.cmd_fetch_model,
        "install-alias": alias.cmd_install_alias,
        "agent-plugin": agent_plugin.cmd_agent_plugin,
        "backup": backup_restore.cmd_backup,
        "restore": backup_restore.cmd_restore,
        "export": export_import.cmd_export,
        "import": export_import.cmd_import,
    }

    for cmd_name, handler in expected.items():
        assert callable(handler), f"Handler for '{cmd_name}' must be callable"


def test_readonly_non_search_inventory():
    """AC-5: key read-only non-search CLI callers use read_only=True; write/search paths are explicit exceptions."""
    from pathlib import Path

    base = Path(__file__).parent.parent / "mempalace_code"

    maintenance_src = (base / "cli_commands" / "maintenance.py").read_text()
    assert "read_only=True" in maintenance_src, "cmd_health must use read_only=True"
    assert "read_only=dry_run" in maintenance_src, "repair rollback must use read_only=dry_run"

    query_src = (base / "cli_commands" / "query.py").read_text()
    assert "read_only=True" in query_src, "cmd_read must use read_only=True"
    assert "read_only=args.dry_run" in query_src, (
        "cmd_compress dry-run must use read_only=args.dry_run"
    )

    export_src = (base / "cli_commands" / "export_import.py").read_text()
    assert "read_only=True" in export_src, "cmd_export must use read_only=True"

    backup_src = (base / "backup.py").read_text()
    assert "read_only=True" in backup_src, "create_backup must use read_only=True"

    write_src = (base / "mcp" / "tools" / "write.py").read_text()
    assert "create=True" in write_src, "MCP delete tools must call _get_store(create=True)"
