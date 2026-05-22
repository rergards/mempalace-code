import json
import os
import tempfile

from mempalace_code.config import MempalaceConfig


def test_default_config():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert "palace" in cfg.palace_path
    assert cfg.collection_name == "mempalace_drawers"


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "/custom/palace"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.palace_path == "/custom/palace"


def test_env_override():
    os.environ["MEMPALACE_PALACE_PATH"] = "/env/palace"
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.palace_path == "/env/palace"
    del os.environ["MEMPALACE_PALACE_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))


def test_spellcheck_enabled_default_none():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.spellcheck_enabled is None


def test_spellcheck_enabled_from_config_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"spellcheck_enabled": False}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.spellcheck_enabled is False

    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"spellcheck_enabled": True}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.spellcheck_enabled is True


def test_spellcheck_enabled_env_overrides_config(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"spellcheck_enabled": True}, f)

    monkeypatch.setenv("MEMPALACE_SPELLCHECK_ENABLED", "false")
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.spellcheck_enabled is False


def test_spellcheck_enabled_invalid_env_falls_back_to_none(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"spellcheck_enabled": True}, f)

    monkeypatch.setenv("MEMPALACE_SPELLCHECK_ENABLED", "sometimes")
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.spellcheck_enabled is None


def test_entity_detection_default_false():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.entity_detection is False


def test_entity_detection_from_config_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"entity_detection": True}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.entity_detection is True

    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"entity_detection": False}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.entity_detection is False


def test_entity_detection_string_values_from_config_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"entity_detection": "yes"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.entity_detection is True

    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"entity_detection": "off"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.entity_detection is False


def test_entity_detection_invalid_falls_back_false():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"entity_detection": "sometimes"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.entity_detection is False


def test_entity_detection_env_overrides_config_file(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"entity_detection": True}, f)

    monkeypatch.setenv("MEMPALACE_ENTITY_DETECTION", "false")
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.entity_detection is False


def test_entity_detection_invalid_env_falls_back_false(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"entity_detection": True}, f)

    monkeypatch.setenv("MEMPALACE_ENTITY_DETECTION", "sometimes")
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.entity_detection is False


def test_init_writes_entity_detection_default_false():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()

    with open(os.path.join(tmpdir, "config.json"), "r") as f:
        data = json.load(f)

    assert data["entity_detection"] is False


# =============================================================================
# scan_skip_* config tests (AC-1, AC-2)
# =============================================================================


def test_scan_skip_config_defaults_and_overrides():
    """AC-1: Default scan_skip_dirs contains .kotlin-lsp; files/globs are empty.
    Explicit config values are loaded in stable normalized order without duplicates.
    """
    # Defaults (no config file)
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert ".kotlin-lsp" in cfg.scan_skip_dirs
    assert cfg.scan_skip_files == []
    assert cfg.scan_skip_globs == []

    # Explicit overrides from config file
    tmpdir2 = tempfile.mkdtemp()
    with open(os.path.join(tmpdir2, "config.json"), "w") as f:
        json.dump(
            {
                "scan_skip_files": ["workspace.json", "workspace.json"],  # dup removed
                "scan_skip_globs": ["generated/**", "build/*.js"],
                "scan_skip_dirs": [".kotlin-lsp", ".kotlin-lsp", "custom-gen"],  # dup removed
            },
            f,
        )
    cfg2 = MempalaceConfig(config_dir=tmpdir2)

    # Duplicates are removed; order is preserved
    assert cfg2.scan_skip_dirs == [".kotlin-lsp", "custom-gen"]
    assert cfg2.scan_skip_files == ["workspace.json"]
    assert cfg2.scan_skip_globs == ["generated/**", "build/*.js"]


def test_scan_skip_invalid_values_fall_back_safely():
    """AC-2: Non-list values fall back to defaults; non-string entries in lists are
    dropped (no silent str() coercion), and defaults remain usable without a crash.
    """
    tmpdir = tempfile.mkdtemp()
    # Wrong type at top level — fall back to default
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"scan_skip_dirs": "not-a-list", "scan_skip_files": 42}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.scan_skip_dirs == [".kotlin-lsp"]  # default
    assert cfg.scan_skip_files == []  # default

    # Non-string items inside a list — dropped, only valid strings kept (no coercion).
    tmpdir2 = tempfile.mkdtemp()
    with open(os.path.join(tmpdir2, "config.json"), "w") as f:
        json.dump({"scan_skip_files": [None, "", "workspace.json", 123]}, f)
    cfg2 = MempalaceConfig(config_dir=tmpdir2)
    # None / 123 / "" all dropped; only "workspace.json" survives.
    assert cfg2.scan_skip_files == ["workspace.json"]
    assert "None" not in cfg2.scan_skip_files
    assert "123" not in cfg2.scan_skip_files


def test_scan_skip_init_writes_defaults_for_fresh_install():
    """init() on a fresh config writes the three scan_skip_* keys with their defaults."""
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()

    with open(os.path.join(tmpdir, "config.json"), "r") as f:
        data = json.load(f)

    assert "scan_skip_dirs" in data
    assert ".kotlin-lsp" in data["scan_skip_dirs"]
    assert data["scan_skip_files"] == []
    assert data["scan_skip_globs"] == []


# =============================================================================
# Disk-budget config tests
# =============================================================================

_ONE_GIB = 1 * 1024 * 1024 * 1024


def test_disk_min_free_bytes_default(monkeypatch):
    """disk_min_free_bytes defaults to 1 GiB when no env or file config is set."""
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.disk_min_free_bytes == _ONE_GIB


def test_watch_disk_min_free_bytes_falls_back_to_global(monkeypatch):
    """watch_disk_min_free_bytes falls back to disk_min_free_bytes when not explicitly set."""
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES", raising=False)
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.watch_disk_min_free_bytes == cfg.disk_min_free_bytes


def test_backup_disk_min_free_bytes_falls_back_to_global(monkeypatch):
    """backup_disk_min_free_bytes falls back to disk_min_free_bytes when not explicitly set."""
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", raising=False)
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.backup_disk_min_free_bytes == cfg.disk_min_free_bytes


def test_disk_min_free_bytes_env_override(monkeypatch):
    """MEMPALACE_DISK_MIN_FREE_BYTES env sets global threshold."""
    monkeypatch.setenv("MEMPALACE_DISK_MIN_FREE_BYTES", "500000000")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.disk_min_free_bytes == 500_000_000


def test_watch_disk_min_free_bytes_env_override(monkeypatch):
    """MEMPALACE_WATCH_DISK_MIN_FREE_BYTES env sets watcher-specific threshold."""
    monkeypatch.setenv("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES", "200000000")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.watch_disk_min_free_bytes == 200_000_000


def test_backup_disk_min_free_bytes_env_override(monkeypatch):
    """MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES env sets backup-specific threshold."""
    monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", "300000000")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.backup_disk_min_free_bytes == 300_000_000


def test_backup_disk_min_free_bytes_legacy_env_alias(monkeypatch):
    """Legacy MEMPALACE_BACKUP_MIN_FREE_BYTES still sets the backup disk budget."""
    monkeypatch.delenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.setenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", "2GiB")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.backup_disk_min_free_bytes == 2 * 1024**3


def test_backup_disk_min_free_bytes_new_env_overrides_legacy_env(monkeypatch):
    """The explicit backup_disk env key wins over the legacy env alias."""
    monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", "300000000")
    monkeypatch.setenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", "200000000")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.backup_disk_min_free_bytes == 300_000_000


def test_watch_overrides_global_disk_budget(monkeypatch):
    """watch_disk_min_free_bytes file key overrides the global disk_min_free_bytes."""
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES", raising=False)
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"disk_min_free_bytes": 1000, "watch_disk_min_free_bytes": 2000}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.disk_min_free_bytes == 1000
    assert cfg.watch_disk_min_free_bytes == 2000


def test_backup_overrides_global_disk_budget(monkeypatch):
    """backup_disk_min_free_bytes file key overrides the global disk_min_free_bytes."""
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", raising=False)
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"disk_min_free_bytes": 1000, "backup_disk_min_free_bytes": 3000}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.backup_disk_min_free_bytes == 3000


def test_backup_legacy_file_key_sets_disk_budget(monkeypatch):
    """Legacy backup_min_free_bytes file key remains a backup_disk_min_free_bytes alias."""
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", raising=False)
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"disk_min_free_bytes": 1000, "backup_min_free_bytes": "4KiB"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.backup_disk_min_free_bytes == 4 * 1024


def test_disk_budget_env_suffix_gib(monkeypatch):
    """Env value with GiB suffix is parsed correctly."""
    monkeypatch.setenv("MEMPALACE_DISK_MIN_FREE_BYTES", "2GiB")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.disk_min_free_bytes == 2 * 1024**3


def test_disk_budget_invalid_env_falls_back_to_default(monkeypatch):
    """Invalid env value for disk_min_free_bytes falls back to 1 GiB default."""
    # Unset the conftest override first, then set an invalid value
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    monkeypatch.setenv("MEMPALACE_DISK_MIN_FREE_BYTES", "not_a_number")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.disk_min_free_bytes == _ONE_GIB


def test_disk_budget_invalid_file_value_falls_back_to_default(monkeypatch):
    """Invalid file config value for disk_min_free_bytes falls back to 1 GiB default."""
    monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"disk_min_free_bytes": "bad_value"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.disk_min_free_bytes == _ONE_GIB


def test_watch_env_takes_precedence_over_file_config(monkeypatch):
    """MEMPALACE_WATCH_DISK_MIN_FREE_BYTES env overrides watch_disk_min_free_bytes file key."""
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"watch_disk_min_free_bytes": 999}, f)
    monkeypatch.setenv("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES", "12345")
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.watch_disk_min_free_bytes == 12345


# =============================================================================
# Pre-optimize bounded retention tests (AC-1, AC-3)
# =============================================================================


def test_pre_optimize_retain_count_default_bounded(monkeypatch):
    """AC-1: Fresh config resolves pre_optimize retention to DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT (5)."""
    from mempalace_code.config import DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT

    monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT == 5
    assert not cfg._backup_retain_count_explicit
    assert cfg.retain_count_for_kind("pre_optimize") == DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT


def test_backup_retain_count_default_remains_zero_for_manual(monkeypatch):
    """AC-1: Global backup_retain_count default is still 0; manual kind is unbounded."""
    monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg.backup_retain_count == 0
    assert cfg.retain_count_for_kind("manual") == 0


def test_explicit_zero_backup_retain_count_keeps_pre_optimize_unbounded(monkeypatch):
    """AC-3: Explicit backup_retain_count=0 via env is keep-all for pre_optimize too."""
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "0")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg._backup_retain_count_explicit is True
    assert cfg.backup_retain_count == 0
    assert cfg.retain_count_for_kind("pre_optimize") == 0


def test_explicit_zero_via_file_keeps_pre_optimize_unbounded(monkeypatch):
    """AC-3: Explicit backup_retain_count: 0 in config file is keep-all for pre_optimize."""
    monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"backup_retain_count": 0}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)

    assert cfg._backup_retain_count_explicit is True
    assert cfg.backup_retain_count == 0
    assert cfg.retain_count_for_kind("pre_optimize") == 0


def test_explicit_nonzero_retain_count_overrides_implicit_pre_optimize_bound(monkeypatch):
    """Explicit backup_retain_count=3 applies to pre_optimize instead of the implicit 5."""
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "3")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg._backup_retain_count_explicit is True
    assert cfg.retain_count_for_kind("pre_optimize") == 3
    assert cfg.retain_count_for_kind("manual") == 3


def test_empty_env_retain_count_is_not_explicit(monkeypatch):
    """An empty MEMPALACE_BACKUP_RETAIN_COUNT env var is treated as not set.

    A blank shell export (export MEMPALACE_BACKUP_RETAIN_COUNT=) must not
    suppress the implicit pre_optimize bound or silently become keep-all.
    """
    from mempalace_code.config import DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT

    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg._backup_retain_count_explicit is False
    assert cfg.retain_count_for_kind("pre_optimize") == DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT


def test_invalid_env_retain_count_is_not_explicit(monkeypatch):
    """A non-numeric MEMPALACE_BACKUP_RETAIN_COUNT env var is treated as not set."""
    from mempalace_code.config import DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT

    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "notanumber")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg._backup_retain_count_explicit is False
    assert cfg.retain_count_for_kind("pre_optimize") == DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT


def test_negative_file_config_retain_count_is_not_explicit(monkeypatch):
    """A negative backup_retain_count in file config must not suppress implicit per-kind defaults."""
    from mempalace_code.config import (
        DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT,
        DEFAULT_SCHEDULED_RETAIN_COUNT,
    )

    monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
    cfg_dir = tempfile.mkdtemp()
    with open(os.path.join(cfg_dir, "config.json"), "w") as f:
        json.dump({"backup_retain_count": -5}, f)
    cfg = MempalaceConfig(config_dir=cfg_dir)

    assert cfg._backup_retain_count_explicit is False
    assert cfg.retain_count_for_kind("scheduled") == DEFAULT_SCHEDULED_RETAIN_COUNT
    assert cfg.retain_count_for_kind("pre_optimize") == DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT


# =============================================================================
# Scheduled retention defaults tests (AC-1, AC-2, AC-3)
# =============================================================================


def test_default_kind_retention_counts(monkeypatch):
    """AC-1: Fresh config resolves scheduled to 14, pre_optimize to 5, manual to 0."""
    from mempalace_code.config import (
        DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT,
        DEFAULT_SCHEDULED_RETAIN_COUNT,
    )

    monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert DEFAULT_SCHEDULED_RETAIN_COUNT == 14
    assert cfg.retain_count_for_kind("scheduled") == 14
    assert cfg.retain_count_for_kind("pre_optimize") == DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT
    assert cfg.retain_count_for_kind("manual") == 0
    assert cfg.backup_retain_count == 0  # INV-1: global property unchanged


def test_explicit_zero_backup_retain_count_keeps_all_kinds(monkeypatch):
    """AC-2: Explicit backup_retain_count=0 disables pruning for every kind."""
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "0")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg._backup_retain_count_explicit is True
    assert cfg.retain_count_for_kind("scheduled") == 0
    assert cfg.retain_count_for_kind("pre_optimize") == 0
    assert cfg.retain_count_for_kind("manual") == 0


def test_explicit_nonzero_retain_count_overrides_all_implicit_bounds(monkeypatch):
    """AC-3: Explicit nonzero backup_retain_count overrides scheduled and pre_optimize defaults."""
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "7")
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg._backup_retain_count_explicit is True
    assert cfg.retain_count_for_kind("scheduled") == 7
    assert cfg.retain_count_for_kind("pre_optimize") == 7
    assert cfg.retain_count_for_kind("manual") == 7
