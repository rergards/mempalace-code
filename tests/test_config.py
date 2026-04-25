import os
import json
import tempfile
from mempalace.config import MempalaceConfig


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


def test_init_writes_entity_detection_default_false():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()

    with open(os.path.join(tmpdir, "config.json"), "r") as f:
        data = json.load(f)

    assert data["entity_detection"] is False
