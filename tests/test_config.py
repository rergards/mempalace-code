import os
import json
import tempfile
from mempalace.config import MempalaceConfig


def test_default_config():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert "palace" in cfg.palace_path
    assert cfg.collection_name == "mempalace_drawers"
    assert ".kotlin-lsp" in cfg.scan_skip_dirs
    assert "workspace.json" in cfg.scan_skip_files
    assert cfg.scan_skip_globs == []


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump(
            {
                "palace_path": "/custom/palace",
                "scan_skip_dirs": [".turbo"],
                "scan_skip_files": ["deps.json"],
                "scan_skip_globs": ["generated/**/*.snap"],
            },
            f,
        )
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.palace_path == "/custom/palace"
    assert cfg.scan_skip_dirs == [".kotlin-lsp", ".turbo"]
    assert cfg.scan_skip_files == ["workspace.json", "deps.json"]
    assert cfg.scan_skip_globs == ["generated/**/*.snap"]


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
