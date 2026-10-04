"""UAT regressions for configuration, CLI parsing, and init (config-init group)."""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import mempalace_code.config as config_module
from mempalace_code.cli import main
from mempalace_code.config import (
    DEFAULT_PALACE_PATH,
    DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT,
    DEFAULT_VERSION_CHECK_INTERVAL_HOURS,
    MempalaceConfig,
    expand_palace_path,
)

TEN_TIB = 10 * 1024**4


@pytest.fixture(autouse=True)
def _fresh_warning_registry(monkeypatch):
    """Each test sees its own once-per-process warnings."""
    monkeypatch.setattr(config_module, "_WARNED_INVALID_SETTINGS", set())
    monkeypatch.setattr(config_module, "_WARNED_UNREADABLE_CONFIGS", set())
    for name in (
        "MEMPALACE_PALACE_PATH",
        "MEMPAL_PALACE_PATH",
        "MEMPALACE_DISK_MIN_FREE_BYTES",
        "MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES",
        "MEMPALACE_BACKUP_MIN_FREE_BYTES",
        "MEMPALACE_WATCH_DISK_MIN_FREE_BYTES",
        "MEMPALACE_BACKUP_WARN_SIZE_BYTES",
        "MEMPALACE_BACKUP_RETAIN_COUNT",
        "MEMPALACE_VERSION_CHECK",
        "MEMPALACE_VERSION_CHECK_INTERVAL_HOURS",
    ):
        monkeypatch.delenv(name, raising=False)


def _config(tmp_path: Path, payload: object) -> MempalaceConfig:
    (tmp_path / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    return MempalaceConfig(config_dir=tmp_path)


# ── install-2 / gap-12: one '~' expansion everywhere ──────────────────────


def test_env_palace_path_with_tilde_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", "~/palaces/tilde")

    assert MempalaceConfig(config_dir=tmp_path).palace_path == str(tmp_path / "palaces" / "tilde")


def test_config_file_palace_path_with_tilde_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    cfg = _config(tmp_path, {"palace_path": "~/palaces/timing"})

    assert cfg.palace_path == str(tmp_path / "palaces" / "timing")


def test_relative_palace_path_is_made_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", "rel/palace")

    assert MempalaceConfig(config_dir=tmp_path).palace_path == str(tmp_path / "rel" / "palace")


def test_expand_palace_path_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    once = expand_palace_path("~/p")
    assert once == str(tmp_path / "p")
    assert expand_palace_path(once) == once
    assert expand_palace_path(Path("~/p")) == once


def test_non_string_palace_path_in_config_warns_and_uses_default(tmp_path, capsys):
    cfg = _config(tmp_path, {"palace_path": 42})

    assert cfg.palace_path == DEFAULT_PALACE_PATH
    err = capsys.readouterr().err
    assert "palace_path in" in err
    assert "42" in err


# ── install-3 / config-1: valid JSON that is not an object ────────────────


@pytest.mark.parametrize("payload", ["null", "[1, 2]", '["x"]', "42", '"str"'])
def test_non_object_config_json_is_ignored_with_warning(tmp_path, capsys, payload):
    (tmp_path / "config.json").write_text(payload, encoding="utf-8")

    cfg = MempalaceConfig(config_dir=tmp_path)

    assert cfg.palace_path == DEFAULT_PALACE_PATH
    assert cfg.version_check_enabled is None
    assert cfg.version_check_interval_hours == DEFAULT_VERSION_CHECK_INTERVAL_HOURS
    assert cfg.backup_warn_size_bytes == 0
    assert cfg.scan_skip_dirs == [".kotlin-lsp"]
    err = capsys.readouterr().err
    assert f"Warning: ignoring {tmp_path / 'config.json'}" in err
    assert "top-level value must be a JSON object" in err
    assert "NoneType" not in err


@pytest.mark.parametrize("command", [["health", "--json"], ["version-check", "--status"]])
def test_non_object_config_json_does_not_crash_cli(tmp_path, monkeypatch, capsys, command):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".mempalace").mkdir()
    (tmp_path / ".mempalace" / "config.json").write_text("null", encoding="utf-8")
    palace = tmp_path / "palace"

    with patch.object(sys, "argv", ["mempalace-code", "--palace", str(palace), *command]):
        try:
            main()
        except SystemExit:
            pass

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "TypeError" not in captured.err
    assert "top-level value must be a JSON object" in captured.err


# ── config-2 / cfg-1: invalid numeric values warn and fall through ────────


def test_invalid_backup_floor_falls_through_to_global_floor(tmp_path, capsys):
    cfg = _config(tmp_path, {"backup_disk_min_free_bytes": "abc", "disk_min_free_bytes": TEN_TIB})

    assert cfg.backup_disk_min_free_bytes == TEN_TIB
    err = capsys.readouterr().err
    assert "backup_disk_min_free_bytes in" in err
    assert "'abc'" in err
    assert "disk_min_free_bytes in" in err


def test_integral_json_float_backup_floor_is_accepted(tmp_path):
    cfg = _config(tmp_path, {"backup_disk_min_free_bytes": 1e13})

    assert cfg.backup_disk_min_free_bytes == 10**13


def test_invalid_backup_floor_env_falls_through_to_file_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", "lots")
    cfg = _config(tmp_path, {"backup_disk_min_free_bytes": TEN_TIB})

    assert cfg.backup_disk_min_free_setting == (
        TEN_TIB,
        f"backup_disk_min_free_bytes in {tmp_path / 'config.json'}",
    )
    assert "'lots' for MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES" in capsys.readouterr().err


def test_global_env_floor_applies_to_backups_and_is_named(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_DISK_MIN_FREE_BYTES", "10TiB")

    cfg = MempalaceConfig(config_dir=tmp_path)

    assert cfg.backup_disk_min_free_setting == (TEN_TIB, "MEMPALACE_DISK_MIN_FREE_BYTES")


def test_backup_warn_size_accepts_size_suffixes(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_BACKUP_WARN_SIZE_BYTES", "20KiB")

    assert MempalaceConfig(config_dir=tmp_path).backup_warn_size_bytes == 20 * 1024


def test_invalid_watch_floor_env_warns_and_uses_global(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES", "lots")
    cfg = _config(tmp_path, {"disk_min_free_bytes": 2 * 1024**3})

    assert cfg.watch_disk_min_free_bytes == 2 * 1024**3
    assert "'lots' for MEMPALACE_WATCH_DISK_MIN_FREE_BYTES" in capsys.readouterr().err


def test_negative_retain_count_env_is_not_explicit(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "-1")

    cfg = MempalaceConfig(config_dir=tmp_path)

    assert cfg._backup_retain_count_explicit is False
    assert cfg.retain_count_for_kind("pre_optimize") == DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT
    assert "'-1' for MEMPALACE_BACKUP_RETAIN_COUNT" in capsys.readouterr().err


def test_invalid_retain_count_env_falls_through_to_file_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "many")

    cfg = _config(tmp_path, {"backup_retain_count": 3})

    assert cfg.retain_count_for_kind("pre_optimize") == 3


@pytest.mark.parametrize("value", ["abc", "-5", "0"])
def test_invalid_version_check_interval_warns(tmp_path, monkeypatch, capsys, value):
    monkeypatch.setenv("MEMPALACE_VERSION_CHECK_INTERVAL_HOURS", value)

    cfg = MempalaceConfig(config_dir=tmp_path)

    assert cfg.version_check_interval_hours == DEFAULT_VERSION_CHECK_INTERVAL_HOURS
    assert f"'{value}' for MEMPALACE_VERSION_CHECK_INTERVAL_HOURS" in capsys.readouterr().err


def test_invalid_interval_env_falls_through_to_file_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_VERSION_CHECK_INTERVAL_HOURS", "abc")

    assert (
        _config(tmp_path, {"version_check_interval_hours": 24}).version_check_interval_hours == 24
    )


def test_each_rejected_value_warns_once_per_process(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES", "lots")
    cfg = MempalaceConfig(config_dir=tmp_path)

    for _ in range(3):
        cfg.watch_disk_min_free_bytes  # noqa: B018 - property access is the behaviour under test

    assert capsys.readouterr().err.count("Warning: ignoring") == 1


# ── install-25 / cfg-1: version-check env spellings, status note, check-now ─


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_version_check_env_accepts_documented_true_spellings(tmp_path, monkeypatch, value):
    from mempalace_code.version_check import resolve_config

    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", value)

    config = resolve_config(tmp_path)

    assert (config.enabled, config.source, config.invalid_env) == (True, "env", False)


@pytest.mark.parametrize("value", ["maybe", "2"])
def test_version_check_invalid_env_fails_closed_and_status_says_so(
    tmp_path, monkeypatch, capsys, value
):
    from mempalace_code.cli_commands import version_check as version_check_command
    from mempalace_code.version_check import resolve_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", value)

    config = resolve_config(tmp_path)
    assert (config.enabled, config.invalid_env) == (False, True)

    version_check_command.cmd_version_check(
        SimpleNamespace(enable=False, disable=False, check_now=False)
    )
    out = capsys.readouterr().out
    assert "unrecognized value" in out
    assert "fail closed" in out


@pytest.mark.parametrize("value", ["", "  "])
def test_blank_version_check_env_is_disabled_not_unrecognized(tmp_path, monkeypatch, value):
    from mempalace_code.version_check import resolve_config

    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", value)

    config = resolve_config(tmp_path)

    assert (config.enabled, config.source, config.invalid_env) == (False, "env", False)


def test_invalid_spellcheck_env_warning_names_the_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_SPELLCHECK_ENABLED", "perhaps")

    assert MempalaceConfig(config_dir=tmp_path).spellcheck_enabled is None

    err = capsys.readouterr().err
    assert "using the default instead" in err
    assert "unset" not in err


def test_check_now_records_last_checked(tmp_path, monkeypatch, capsys):
    from mempalace_code.cli_commands import version_check as version_check_command
    from mempalace_code.version_check import load_state

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(version_check_command, "fetch_latest_version", lambda: "0.0.1")

    version_check_command.cmd_version_check(
        SimpleNamespace(enable=False, disable=False, check_now=True)
    )
    assert load_state(tmp_path / ".mempalace").last_check_ts is not None

    version_check_command.cmd_version_check(
        SimpleNamespace(enable=False, disable=False, check_now=False)
    )
    assert "Last checked:    never" not in capsys.readouterr().out


def test_failed_check_now_does_not_record_last_checked(tmp_path, monkeypatch):
    from mempalace_code.cli_commands import version_check as version_check_command
    from mempalace_code.version_check import load_state

    monkeypatch.setenv("HOME", str(tmp_path))

    def _fail():
        raise RuntimeError("offline")

    monkeypatch.setattr(version_check_command, "fetch_latest_version", _fail)

    version_check_command.cmd_version_check(
        SimpleNamespace(enable=False, disable=False, check_now=True)
    )

    assert load_state(tmp_path / ".mempalace").last_check_ts is None


# ── gap-12: '~' in the public Python API ─────────────────────────────────


def test_python_api_expands_tilde_palace_paths(seeded_collection, tmp_dir, monkeypatch):
    from mempalace_code.knowledge_graph import open_palace_kg, palace_kg_path
    from mempalace_code.searcher import code_search, search_memories
    from mempalace_code.storage import LanceStore, open_store

    monkeypatch.setenv("HOME", tmp_dir)
    monkeypatch.chdir(tmp_dir)

    found = search_memories("JWT session tokens", "~/palace")
    assert "error" not in found
    assert found["results"]
    assert "error" not in code_search("~/palace", "JWT session tokens")
    assert open_store("~/palace", create=False, read_only=True).count() == 4
    assert open_store("~/palace", create=False).count() == 4
    assert LanceStore(palace_path="~/palace", read_only=True).count() == 4

    open_palace_kg("~/kgpalace").add_triple("a", "b", "c")

    assert palace_kg_path("~/kgpalace") == str(
        Path(tmp_dir) / "kgpalace" / "knowledge_graph.sqlite3"
    )
    assert (Path(tmp_dir) / "kgpalace" / "knowledge_graph.sqlite3").is_file()
    assert not (Path(tmp_dir) / "~").exists()


def test_python_mine_entry_points_expand_tilde_palace_paths(tmp_path, monkeypatch):
    """mine()/mine_convos() keep tiny hashes and optimize backups beside the Lance data."""
    from mempalace_code.convo_miner import mine_convos
    from mempalace_code.miner import mine
    from mempalace_code.storage import open_store

    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    project = tmp_path / "project"
    convos = tmp_path / "convos"
    for directory in (home, cwd, project / "src", convos):
        directory.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    (project / "mempalace.yaml").write_text("wing: proj\nrooms:\n- name: general\n")
    (project / "src" / "app.py").write_text(
        "".join(
            f'def handler_{i}(request):\n    """Serve request kind {i} and log it."""\n'
            f"    return request.respond(status=200, body='handled kind {i}')\n\n\n"
            for i in range(8)
        )
    )
    (project / "src" / "tiny.py").write_text("x = 1\n")
    (convos / "chat.txt").write_text(
        "> How do I deploy the service?\n"
        "Run the deploy script and then check the health endpoint carefully.\n\n"
        "> What about rollback?\n"
        "Use the rollback command with the previous version tag and verify the logs.\n"
    )

    mine(str(project), palace_path="~/palaces/code")
    mine_convos(str(convos), palace_path="~/palaces/convos", wing="chats")

    assert open_store(str(home / "palaces" / "code"), create=False).count() > 0
    assert open_store(str(home / "palaces" / "convos"), create=False).count() > 0
    assert (home / "palaces" / "code" / ".mempalace" / "tiny_hashes.json").is_file()
    assert not (cwd / "~").exists()


# ── install-21: --palace edge cases ───────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["--palace", "", "status", "--summary"],
        ["status", "--summary", "--palace", ""],
        ["status", "--summary", "--palace="],
        ["--palace", "   ", "health", "--json"],
    ],
)
def test_empty_palace_value_is_rejected(argv, capsys):
    with (
        patch("mempalace_code.cli.cmd_status") as status,
        patch("mempalace_code.cli.cmd_health") as health,
    ):
        with patch.object(sys, "argv", ["mempalace-code", *argv]):
            with pytest.raises(SystemExit) as exc:
                main()

    assert exc.value.code == 2
    assert "expected a non-empty path" in capsys.readouterr().err
    status.assert_not_called()
    health.assert_not_called()


def test_trailing_bare_palace_reports_missing_value(capsys):
    with patch.object(sys, "argv", ["mempalace-code", "status", "--summary", "--palace"]):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "argument --palace: expected one argument" in err
    assert "unrecognized arguments" not in err


def test_cli_palace_value_is_expanded_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch("mempalace_code.cli.cmd_status") as status:
        with patch.object(sys, "argv", ["mempalace-code", "status", "--palace=~/p"]):
            main()

    assert status.call_args.args[0].palace == str(tmp_path / "p")


# ── install-27 / ops-28: help <command> ───────────────────────────────────


def test_help_topic_prints_that_commands_help(capsys):
    with patch.object(sys, "argv", ["mempalace-code", "help", "mine"]):
        main()

    out = capsys.readouterr().out
    assert "usage:" in out
    assert " mine " in out
    assert "--wing" in out


def test_help_unknown_topic_is_a_usage_error(capsys):
    with patch.object(sys, "argv", ["mempalace-code", "help", "nope"]):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 2
    assert "unknown command 'nope'" in capsys.readouterr().err


# ── init: re-run safety (init-1, install-4) ───────────────────────────────

CUSTOM_YAML = (
    "wing: my_custom_wing\n"
    "rooms:\n"
    "  - name: billing\n"
    "    description: hand-tuned\n"
    "    keywords: [invoice]\n"
    "architecture:\n"
    "  enabled: false\n"
)


def _init(argv, monkeypatch=None, tty=False):
    if monkeypatch is not None:
        monkeypatch.setattr("mempalace_code.cli_commands.ingest._stdin_is_interactive", lambda: tty)
    with patch.object(sys, "argv", ["mempalace-code", "init", *argv, "--skip-model-download"]):
        main()


def _project(tmp_path, monkeypatch, name="reinit"):
    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / name
    (project / "api").mkdir(parents=True)
    (project / "api" / "invoice.py").write_text("def invoice():\n    return 1\n")
    return project


def test_rerunning_init_keeps_existing_config(tmp_path, monkeypatch, capsys):
    import yaml as _yaml

    project = _project(tmp_path, monkeypatch)
    (project / "mempalace.yaml").write_text(CUSTOM_YAML, encoding="utf-8")

    _init([str(project)])

    assert (project / "mempalace.yaml").read_text(encoding="utf-8") == CUSTOM_YAML
    assert not (project / "mempalace.yaml.bak").exists()
    out = capsys.readouterr().out
    assert "already exists" in out
    assert "Kept unchanged (wing: my_custom_wing, 1 room(s))" in out
    assert f"mempalace-code init {project} --force" in out
    assert _yaml.safe_load(CUSTOM_YAML)["wing"] == "my_custom_wing"


def test_init_force_keeps_wing_and_settings_and_backs_up(tmp_path, monkeypatch, capsys):
    import yaml as _yaml

    project = _project(tmp_path, monkeypatch)
    config_path = project / "mempalace.yaml"
    config_path.write_text(CUSTOM_YAML, encoding="utf-8")

    _init([str(project), "--force"])

    cfg = _yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert cfg["wing"] == "my_custom_wing"
    assert cfg["architecture"] == {"enabled": False}
    assert [room["name"] for room in cfg["rooms"]] == ["backend", "general"]
    assert (project / "mempalace.yaml.bak").read_text(encoding="utf-8") == CUSTOM_YAML
    out = capsys.readouterr().out
    assert "Previous config backed up to:" in out
    assert f"mine {project} --full" in out

    _init([str(project), "--force"])
    assert (project / "mempalace.yaml.bak.1").is_file()
    assert (project / "mempalace.yaml.bak").read_text(encoding="utf-8") == CUSTOM_YAML


def test_init_keeps_legacy_mempal_yaml(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    (project / "mempal.yaml").write_text("wing: legacy\n", encoding="utf-8")

    _init([str(project)])

    assert not (project / "mempalace.yaml").exists()


def test_init_force_regenerates_unparseable_config_from_scratch(tmp_path, monkeypatch, capsys):
    import yaml as _yaml

    project = _project(tmp_path, monkeypatch, name="broken")
    (project / "mempalace.yaml").write_text("wing: [unclosed\n", encoding="utf-8")

    _init([str(project), "--force"])

    assert _yaml.safe_load((project / "mempalace.yaml").read_text())["wing"] == "broken"
    assert (project / "mempalace.yaml.bak").read_text() == "wing: [unclosed\n"
    assert "cannot be parsed" in capsys.readouterr().err


# ── init without a terminal (install-10, init-2) ──────────────────────────


def test_interactive_without_tty_exits_before_writing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch)

    with patch("builtins.input", side_effect=AssertionError("must not prompt")):
        with pytest.raises(SystemExit) as exc:
            _init([str(project), "--interactive"], monkeypatch, tty=False)

    assert exc.value.code == 2
    assert not (project / "mempalace.yaml").exists()
    err = capsys.readouterr().err
    assert "needs a terminal" in err
    assert "No changes were saved" in err
    assert "Traceback" not in err


def test_yes_overrides_interactive(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)

    with patch("builtins.input", side_effect=AssertionError("must not prompt")):
        _init([str(project), "--interactive", "--yes"], monkeypatch, tty=False)

    assert (project / "mempalace.yaml").is_file()


def test_closed_input_during_room_review_aborts_cleanly(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch)

    with patch("builtins.input", side_effect=EOFError):
        with pytest.raises(SystemExit) as exc:
            _init([str(project), "--interactive"], monkeypatch, tty=True)

    assert exc.value.code == 1
    assert not (project / "mempalace.yaml").exists()
    err = capsys.readouterr().err
    assert "No changes were saved" in err
    assert "--yes" in err


def test_detect_entities_without_tty_auto_accepts(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch, name="notes")
    (project / "notes.md").write_text("Alice said the Apollo repo is ready.\n")
    detected = {"people": [{"name": "Alice"}], "projects": [{"name": "Apollo"}], "uncertain": []}

    with (
        patch("mempalace_code.entity_detector.scan_for_detection", return_value=["notes.md"]),
        patch("mempalace_code.entity_detector.detect_entities", return_value=detected),
        patch(
            "mempalace_code.entity_detector.confirm_entities",
            return_value={"people": ["Alice"], "projects": ["Apollo"]},
        ) as confirm,
        patch("builtins.input", side_effect=AssertionError("must not prompt")),
    ):
        _init([str(project), "--detect-entities"], monkeypatch, tty=False)

    confirm.assert_called_once_with(detected, yes=True)
    assert json.loads((project / "entities.json").read_text()) == {
        "people": ["Alice"],
        "projects": ["Apollo"],
    }
    assert "stdin is not a terminal" in capsys.readouterr().out


@pytest.mark.parametrize("force", [False, True])
def test_rerun_init_keeps_existing_entities_unless_forced(tmp_path, monkeypatch, capsys, force):
    """A kept mempalace.yaml keeps its hand-curated entities.json too; --force replaces it."""
    project = _project(tmp_path, monkeypatch, name="notes10")
    (project / "mempalace.yaml").write_text(CUSTOM_YAML, encoding="utf-8")
    curated = {"people": ["Carol"], "projects": ["Hand Curated"]}
    (project / "entities.json").write_text(json.dumps(curated))
    detected = {"people": [{"name": "Zed"}], "projects": [], "uncertain": []}

    with (
        patch("mempalace_code.entity_detector.scan_for_detection", return_value=["notes.md"]),
        patch("mempalace_code.entity_detector.detect_entities", return_value=detected),
        patch(
            "mempalace_code.entity_detector.confirm_entities",
            return_value={"people": ["Zed"], "projects": []},
        ),
    ):
        argv = [str(project), "--detect-entities", "--yes"] + (["--force"] if force else [])
        _init(argv, monkeypatch, tty=False)

    saved = json.loads((project / "entities.json").read_text())
    out = capsys.readouterr().out
    if force:
        assert saved == {"people": ["Zed"], "projects": []}
        assert "Entities saved" in out
    else:
        assert saved == curated
        assert "Kept existing" in out


def test_kept_legacy_config_hint_does_not_promise_a_backup(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch, name="leg")
    (project / "mempal.yaml").write_text(CUSTOM_YAML, encoding="utf-8")

    _init([str(project)])

    out = capsys.readouterr().out
    assert "leaves mempal.yaml in place" in out
    assert "backed up" not in out


def test_closed_input_during_entity_confirmation_aborts_cleanly(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch, name="notes")
    detected = {
        "people": [{"name": "Alice", "confidence": 0.9, "signals": ["said"], "type": "person"}],
        "projects": [],
        "uncertain": [],
    }

    with (
        patch("mempalace_code.entity_detector.scan_for_detection", return_value=["notes.md"]),
        patch("mempalace_code.entity_detector.detect_entities", return_value=detected),
        patch("builtins.input", side_effect=EOFError),
    ):
        with pytest.raises(SystemExit) as exc:
            _init([str(project), "--detect-entities"], monkeypatch, tty=True)

    assert exc.value.code == 1
    assert not (project / "mempalace.yaml").exists()
    assert not (project / "entities.json").exists()
    assert "No changes were saved" in capsys.readouterr().err


# ── init output and room proposals (install-22, ops-28, init-3) ──────────


def test_init_rooms_have_unique_keywords_and_all_sources(tmp_path):
    from mempalace_code.room_detector_local import detect_rooms_from_folders

    for name in ("scripts", "tools", "frontend", "src", "proj22"):
        (tmp_path / name).mkdir()

    rooms = {room["name"]: room for room in detect_rooms_from_folders(str(tmp_path))}

    for room in rooms.values():
        assert len(room["keywords"]) == len(set(room["keywords"])), room
    assert rooms["frontend"]["keywords"] == ["frontend"]
    assert rooms["src"]["keywords"] == ["src"]
    assert rooms["scripts"]["description"] == "Files from scripts/, tools/"
    assert rooms["scripts"]["keywords"] == ["scripts", "tools"]


def test_init_skips_symlinked_directories(tmp_path):
    from mempalace_code.room_detector_local import detect_rooms_from_folders

    project = tmp_path / "proj"
    (project / "real").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (project / "linkdir_outside").symlink_to(tmp_path / "outside")
    (project / "linkdir_inside").symlink_to(project / "real")

    names = [room["name"] for room in detect_rooms_from_folders(str(project))]

    assert names == ["real", "general"]


@pytest.mark.parametrize("reverse_project_order", [False, True])
def test_dotnet_init_keeps_folder_rooms_outside_projects(
    tmp_path, monkeypatch, reverse_project_order
):
    import yaml as _yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "poly"
    for rel in ("src/Acme.Web", "src/Acme.Data", "backend", "frontend", "docs"):
        (project / rel).mkdir(parents=True)
    (project / "Acme.sln").write_text("Microsoft Visual Studio Solution File\n")
    for name in ("Acme.Web", "Acme.Data"):
        (project / "src" / name / f"{name}.csproj").write_text("<Project />\n")

    original_glob = Path.glob

    def project_glob(path, pattern, **kwargs):
        found = original_glob(path, pattern, **kwargs)
        if path == project and pattern == "**/*.csproj":
            return iter(sorted(found, reverse=reverse_project_order))
        return found

    monkeypatch.setattr(Path, "glob", project_glob)
    _init([str(project)])

    cfg = _yaml.safe_load((project / "mempalace.yaml").read_text())
    names = [room["name"] for room in cfg["rooms"]]
    # Project rooms precede folder rooms; directory enumeration order is unspecified.
    assert set(names[:2]) == {"acme_web", "acme_data"}
    assert {"backend", "frontend", "documentation"} <= set(names)
    assert names[-1] == "general"
    assert cfg["dotnet_structure"] is True
    assert cfg["wing"] == "acme", "init writes the .sln wing that mine stores"


def test_dotnet_init_root_project_proposes_no_unfillable_folder_rooms(
    tmp_path, monkeypatch, capsys
):
    """A root-level .csproj owns the whole tree: mine routes every file to its room."""
    import yaml as _yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "rootproj"
    for rel in ("Controllers", "docs", "scripts"):
        (project / rel).mkdir(parents=True)
    (project / "Shop.csproj").write_text("<Project />\n")
    (project / "Controllers" / "HomeController.cs").write_text("public class Home {}\n")
    (project / "docs" / "deploy.md").write_text("# Deploy\n")
    (project / "scripts" / "deploy.sh").write_text("echo deploy\n")

    _init([str(project)])

    cfg = _yaml.safe_load((project / "mempalace.yaml").read_text())
    assert [room["name"] for room in cfg["rooms"]] == ["shop", "general"]
    out = capsys.readouterr().out
    assert "rooms detected from .csproj projects)" in out


@pytest.mark.parametrize(("owned", "expect_fetch"), [(False, True), (True, False)])
def test_init_next_steps_include_fetch_model_when_uncached(
    tmp_path, monkeypatch, capsys, owned, expect_fetch
):
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr("mempalace_code.storage.canonical_fastembed_cache_owned", lambda: owned)

    _init([str(project)])

    out = capsys.readouterr().out
    assert ("mempalace-code fetch-model" in out) is expect_fetch
    assert f"mempalace-code mine {project}" in out
    assert out.index("Config saved") < out.index("Next step")


def test_init_model_failure_names_fetch_model_once_as_the_next_step(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr("mempalace_code.storage.canonical_fastembed_cache_owned", lambda: False)

    def offline(model_name):
        raise RuntimeError("offline; run mempalace-code fetch-model while online")

    monkeypatch.setattr("mempalace_code.cli_commands.model.fetch_model", offline)
    with patch.object(sys, "argv", ["mempalace-code", "init", str(project)]):
        main()

    captured = capsys.readouterr()
    assert "Warning: model cache/verify failed: offline" in captured.err
    assert "manually when the model is available" not in captured.err
    steps = captured.out[captured.out.index("Next steps:") :]
    assert steps.index("mempalace-code fetch-model") < steps.index(f"mempalace-code mine {project}")


def test_init_next_step_preserves_palace(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr("mempalace_code.storage.canonical_fastembed_cache_owned", lambda: True)
    palace = tmp_path / "my palace"

    with patch.object(
        sys,
        "argv",
        ["mempalace-code", "--palace", str(palace), "init", str(project), "--skip-model-download"],
    ):
        main()

    assert f"mempalace-code --palace '{palace}' mine {project}" in capsys.readouterr().out


# ── wing names: init writes what mine stores (mine-all-1, wing-1) ─────────


def test_init_wing_matches_the_wing_mine_stores(tmp_path, monkeypatch):
    import yaml as _yaml

    from mempalace_code.mining.projects import (
        _normalize_configured_wing,
        load_config,
        resolve_wing_for_project,
    )

    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "my proj (v2)"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n")

    _init([str(project)])

    written = _yaml.safe_load((project / "mempalace.yaml").read_text())["wing"]
    assert written == "my_proj_v2"
    assert _normalize_configured_wing(load_config(str(project))["wing"]) == written
    assert resolve_wing_for_project(str(project)) == written


def test_init_uses_git_origin_for_repository_root(tmp_path, monkeypatch):
    import yaml as _yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "alpha"
    (project / ".git").mkdir(parents=True)
    (project / "invoice.py").write_text("x = 1\n")
    real_run = __import__("subprocess").run

    def fake_git(cmd, *args, **kwargs):
        if cmd[:1] == ["git"] and "get-url" in cmd:
            return SimpleNamespace(
                returncode=0, stdout="https://github.com/acme/Billing-Engine.git\n"
            )
        return real_run(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=fake_git):
        _init([str(project)])
        from mempalace_code.mining.projects import resolve_wing_for_project

        preview = resolve_wing_for_project(str(project))

    assert _yaml.safe_load((project / "mempalace.yaml").read_text())["wing"] == "billing_engine"
    assert preview == "billing_engine"


def test_mine_all_names_skipped_subdirectories(tmp_path, capsys):
    parent = tmp_path / "pa"
    (parent / "alpha").mkdir(parents=True)
    (parent / "alpha" / "pyproject.toml").write_text("[project]\nname = 'alpha'\n")
    (parent / "notes").mkdir()
    (parent / "notes" / "a.md").write_text("# notes\n")
    (parent / "rusty").mkdir()
    (parent / ".hidden").mkdir()

    with patch.object(
        sys,
        "argv",
        ["mempalace-code", "--palace", str(tmp_path / "p"), "mine-all", str(parent), "--dry-run"],
    ):
        main()

    out = capsys.readouterr().out
    assert "Skipped 2 subdirectories without project markers or mempalace.yaml: notes, rusty" in out
    assert f"mempalace-code init {parent / 'notes'}" in out
    assert ".hidden" not in out


# ── malformed mempalace.yaml (mine-5) ─────────────────────────────────────


@pytest.mark.parametrize(
    ("content", "wing", "rooms"),
    [
        ("", "yv", None),
        ("rooms:\n  - name: general\n", "yv", ["general"]),
        ("wing: yv6\nrooms:\n  - billing\n  - adr\n", "yv6", ["billing", "adr"]),
        ("wing: 12345\nrooms:\n  - name: general\n", "12345", ["general"]),
        ("wing: w\nrooms:\n  - name: r\n    keywords: invoice\n", "w", ["r"]),
    ],
)
def test_load_config_fills_defaults_and_accepts_simple_forms(tmp_path, content, wing, rooms):
    from mempalace_code.mining.projects import load_config

    project = tmp_path / "yv"
    project.mkdir()
    (project / "mempalace.yaml").write_text(content, encoding="utf-8")

    config = load_config(str(project))

    assert config["wing"] == wing
    if rooms is None:
        assert "rooms" not in config
    else:
        assert [room["name"] for room in config["rooms"]] == rooms
        assert all(isinstance(room["keywords"], list) for room in config["rooms"])


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ("wing: [a, b]\n", "'wing' must be a text value"),
        ("rooms: general\n", "'rooms' must be a list"),
        ("rooms:\n  - {description: x}\n", "rooms[0] must be a mapping with a non-empty 'name'"),
        ("rooms:\n  - name: x\n    keywords: {a: 1}\n", "rooms[0].keywords"),
    ],
)
def test_load_config_rejects_unusable_fields(tmp_path, content, detail):
    from mempalace_code.mining.projects import InvalidProjectConfigError, load_config

    project = tmp_path / "yv"
    project.mkdir()
    (project / "mempalace.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(InvalidProjectConfigError, match=re.escape(detail)):
        load_config(str(project))


@pytest.mark.parametrize("content", ["wing: [unclosed\nrooms:\n  - name: x\n", "rooms: general\n"])
def test_mine_with_malformed_yaml_fails_without_traceback(tmp_path, capsys, content):
    project = tmp_path / "yv"
    project.mkdir()
    (project / "invoice.py").write_text("def invoice():\n    return 1\n")
    config_path = project / "mempalace.yaml"
    config_path.write_text(content, encoding="utf-8")

    with patch.object(
        sys, "argv", ["mempalace-code", "--palace", str(tmp_path / "p"), "mine", str(project)]
    ):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert f"Error: cannot parse {config_path}" in err
    assert f"mempalace-code init {project}" in err
    assert "Traceback" not in err


# ── global config and halls (install-12, gap-13) ──────────────────────────


def test_config_init_no_longer_writes_legacy_hall_taxonomy(tmp_path):
    written = json.loads(MempalaceConfig(config_dir=tmp_path).init().read_text())

    assert "hall_keywords" not in written
    assert "topic_wings" not in written


def test_dotnet_config_without_wing_defaults_to_sln_name_everywhere(tmp_path):
    from mempalace_code.mining.projects import load_config, resolve_wing_for_project

    project = tmp_path / "poly"
    project.mkdir()
    (project / "Acme.sln").write_text("Microsoft Visual Studio Solution File\n")
    (project / "mempalace.yaml").write_text("dotnet_structure: true\n", encoding="utf-8")

    assert load_config(str(project))["wing"] == "acme"
    assert resolve_wing_for_project(str(project)) == "acme"
