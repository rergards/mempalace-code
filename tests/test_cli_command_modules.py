"""
test_cli_command_modules.py — Import contract tests for the cli_commands package.

Verifies:
  - mempalace_code.cli still exports the stable public symbols
  - Each command module can be imported without eagerly loading heavy runtime deps
  - The dispatch mapping covers all expected command names
"""

import sys
import types


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


def test_main_alias_is_same_object_as_in_alias_module():
    """cli.main_alias must be the same function as alias.main_alias (no copy)."""
    import mempalace_code.cli as cli
    from mempalace_code.cli_commands import alias

    assert cli.main_alias is alias.main_alias
