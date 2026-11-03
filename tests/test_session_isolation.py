"""Exercise the real session fixtures in a separate, credential-free process."""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize("palace_variable", [None, "MEMPALACE_PALACE_PATH", "MEMPAL_PALACE_PATH"])
def test_session_environment_isolation(tmp_path, palace_variable):
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copyfile(Path(__file__).with_name("conftest.py"), suite / "conftest.py")
    (suite / "test_probe.py").write_text(
        textwrap.dedent(
            """
            import os
            from pathlib import Path
            from mempalace_code.config import DEFAULT_PALACE_PATH, MempalaceConfig

            # Collection happens after conftest imports, before fixtures run.
            assert "MEMPALACE_PALACE_PATH" not in os.environ
            assert "MEMPAL_PALACE_PATH" not in os.environ
            assert Path(DEFAULT_PALACE_PATH).is_relative_to(Path.home())

            def test_fixture_config(config, palace_path):
                assert config.palace_path == palace_path
                assert config.spellcheck_enabled is None
                assert os.environ["MEMPALACE_DISK_MIN_FREE_BYTES"] == "1"
                assert os.environ["MEMPALACE_TEST_HF_HOME"].endswith("harness-cache")
                assert os.environ["MEMPALACE_TEST_INSTALLED_CLI"] == "harness-only"
                assert os.environ["MEMPALACE_RELEASE_SYSTEMD_USER"] == "0"

            def test_explicit_override(config, tmp_path, monkeypatch):
                legacy = str(tmp_path / "legacy")
                current = str(tmp_path / "current")
                monkeypatch.setenv("MEMPAL_PALACE_PATH", legacy)
                assert config.palace_path == legacy
                monkeypatch.setenv("MEMPALACE_PALACE_PATH", current)
                assert config.palace_path == current
                monkeypatch.setenv("MEMPALACE_SPELLCHECK_ENABLED", "false")
                assert config.spellcheck_enabled is False

            def test_override_restored(config, palace_path):
                assert config.palace_path == palace_path
                assert config.spellcheck_enabled is None
            """
        ),
        encoding="utf-8",
    )
    home = tmp_path / "ambient-home"
    home.mkdir()
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "HOMEDRIVE": "synthetic-drive",
        "HOMEPATH": str(home),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "MEMPALACE_SPELLCHECK_ENABLED": "false",
        "MEMPALACE_TEST_HF_HOME": str(tmp_path / "harness-cache"),
        "MEMPALACE_TEST_INSTALLED_CLI": "harness-only",
        "MEMPALACE_RELEASE_SYSTEMD_USER": "0",
    }
    ambient_palace = tmp_path / "ambient-palace-must-not-exist"
    if palace_variable is not None:
        env[palace_variable] = str(ambient_palace)
        env["MEMPALACE_DISK_MIN_FREE_BYTES"] = "999999999999999999"
    runner = textwrap.dedent(
        """
        import os
        import sys
        import pytest

        def relevant():
            return {
                key: value for key, value in os.environ.items()
                if key.startswith(("MEMPALACE_", "MEMPAL_"))
                or key in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
            }

        before = relevant()
        result = pytest.main([sys.argv[1], "-q", "-p", "no:cacheprovider"])
        assert relevant() == before, "session environment was not restored"
        raise SystemExit(result)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", runner, str(suite)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout
    assert not ambient_palace.exists()
    assert list(home.iterdir()) == []
