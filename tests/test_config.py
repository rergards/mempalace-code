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
