"""Cross-entry-point regression tests for explicit configured wing identifiers."""

import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mempalace_code.cli_commands.ingest import cmd_mine_all
from mempalace_code.mining.orchestrator import mine
from mempalace_code.mining.projects import InvalidProjectConfigError, resolve_wing_for_project
from mempalace_code.storage import open_store
from mempalace_code.watcher import watch_all


class _NoopOperationLock:
    def acquire_shared(self, operation):
        assert operation == "watcher"
        return nullcontext()


class _FakeDefaultFilter:
    ignore_dirs = ()

    def __init__(self, **kwargs):
        self.ignore_dirs = kwargs.get("ignore_dirs", ())


def _fake_watchfiles(watch):
    return SimpleNamespace(watch=watch, DefaultFilter=_FakeDefaultFilter)


def _write_project(
    project: Path,
    *,
    wing: str = "migrate-openclaw",
    config_name: str = "mempalace.yaml",
    dotnet_structure: bool | None = None,
) -> Path:
    project.mkdir()
    (project / ".git").mkdir()
    config_lines = [
        f"wing: {wing}",
        "rooms:",
        "  - name: general",
        "    description: General",
        "    keywords: []",
    ]
    if dotnet_structure is not None:
        config_lines.append(f"dotnet_structure: {str(dotnet_structure).lower()}")
    config_path = project / config_name
    config_path.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    (project / "app.py").write_text("def stable_value():\n    return 42\n" * 24, encoding="utf-8")
    return config_path


def _mine_all_args(parent: Path, palace: Path):
    return SimpleNamespace(
        dir=str(parent),
        palace=str(palace),
        agent="test",
        dry_run=False,
        new_only=False,
        no_gitignore=False,
        include_ignored=None,
    )


def _watch_once(root: Path, palace: Path, watch):
    with (
        patch.dict(sys.modules, {"watchfiles": _fake_watchfiles(watch)}),
        patch("mempalace_code.watcher._emit_run_state"),
        patch("mempalace_code.watcher._has_existing_lance_data", return_value=False),
    ):
        watch_all(
            str(root),
            str(palace),
            on_commit=False,
            operation_lock=_NoopOperationLock(),
        )


def _invoke_batch_or_watcher(entry_point: str, parent: Path, watch_root: Path, palace: Path):
    if entry_point == "mine-all":
        cmd_mine_all(_mine_all_args(parent, palace))
    else:
        _watch_once(watch_root, palace, lambda *args, **kwargs: iter([]))


@pytest.mark.parametrize("config_name", ["mempalace.yaml", "mempal.yaml"])
@pytest.mark.parametrize("dotnet_structure", [None, False])
def test_configured_hyphenated_wing_resolves_identically(config_name, dotnet_structure, tmp_path):
    project = tmp_path / "project"
    _write_project(
        project,
        config_name=config_name,
        dotnet_structure=dotnet_structure,
    )

    assert resolve_wing_for_project(str(project)) == "migrate-openclaw"


@pytest.mark.parametrize("config_name", ["mempalace.yaml", "mempal.yaml"])
@pytest.mark.parametrize("dotnet_structure", [None, False])
def test_entry_point_switching_keeps_one_destination_and_preserves_files(
    config_name, dotnet_structure, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    config_dir = home / ".mempalace"
    config_dir.mkdir(parents=True)
    watcher_config = config_dir / "config.json"
    watcher_config.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    parent = tmp_path / "projects"
    parent.mkdir()
    project = parent / "configured-project"
    project_config = _write_project(
        project,
        config_name=config_name,
        dotnet_structure=dotnet_structure,
    )
    source = project / "app.py"
    palace = tmp_path / "palace"
    snapshots = {
        project_config: project_config.read_bytes(),
        source: source.read_bytes(),
        watcher_config: watcher_config.read_bytes(),
    }
    marker_names = sorted(path.name for path in project.iterdir())

    store = open_store(str(palace), create=True)
    store.add(
        ids=["historical-row"],
        documents=["historical data must remain unchanged"],
        metadatas=[
            {
                "wing": "historical-wing",
                "room": "general",
                "source_file": "/historical/source.txt",
                "chunk_index": 0,
                "added_by": "test",
                "filed_at": "2026-01-01T00:00:00",
            }
        ],
    )

    mine(str(project), str(palace))
    first_rows = open_store(str(palace), create=False).get(
        where={"wing": "migrate-openclaw"}, limit=100
    )
    first_ids = set(first_rows["ids"])
    assert first_ids

    with patch("mempalace_code.knowledge_graph.LazyKnowledgeGraph", return_value=None):
        cmd_mine_all(_mine_all_args(parent, palace))
    _watch_once(parent, palace, lambda *args, **kwargs: iter([]))

    # Retry in a different order against the same disposable store.
    _watch_once(project, palace, lambda *args, **kwargs: iter([]))
    mine(str(project), str(palace))
    with patch("mempalace_code.knowledge_graph.LazyKnowledgeGraph", return_value=None):
        cmd_mine_all(_mine_all_args(parent, palace))

    final_store = open_store(str(palace), create=False)
    counts = final_store.count_by("wing")
    final_rows = final_store.get(where={"wing": "migrate-openclaw"}, limit=100)
    assert counts["migrate-openclaw"] == len(first_ids)
    assert "migrate_openclaw" not in counts
    assert set(final_rows["ids"]) == first_ids
    assert len(final_rows["ids"]) == len(set(final_rows["ids"]))
    assert final_store.get(ids=["historical-row"], include=["documents"])["documents"] == [
        "historical data must remain unchanged"
    ]
    assert all(path.is_relative_to(tmp_path) for path in (home, parent, palace))
    assert sorted(path.name for path in project.iterdir()) == marker_names
    assert {path: path.read_bytes() for path in snapshots} == snapshots


def test_running_watcher_keeps_startup_wing_and_fresh_watcher_reads_edit(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".mempalace").mkdir(parents=True)
    (home / ".mempalace" / "config.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    project = tmp_path / "project"
    config_path = _write_project(project)
    source = project / "app.py"
    first_calls = []

    def edit_then_event(*args, **kwargs):
        config_path.write_text(config_path.read_text().replace("migrate-openclaw", "edited-wing"))
        yield {(2, str(source))}

    def fake_mine(**kwargs):
        first_calls.append(kwargs["wing_override"])
        return {"files_processed": 0, "drawers_filed": 0, "embedder_warmed": False}

    with (
        patch("mempalace_code.watcher.mine", side_effect=fake_mine),
        patch("mempalace_code.watcher.get_collection", return_value=object()),
    ):
        _watch_once(project, tmp_path / "first-palace", edit_then_event)

    assert first_calls == ["migrate-openclaw", "migrate-openclaw"]

    fresh_calls = []

    def fresh_mine(**kwargs):
        fresh_calls.append(kwargs["wing_override"])
        return {"files_processed": 0, "drawers_filed": 0, "embedder_warmed": False}

    with (
        patch("mempalace_code.watcher.mine", side_effect=fresh_mine),
        patch("mempalace_code.watcher.get_collection", return_value=object()),
    ):
        _watch_once(project, tmp_path / "fresh-palace", lambda *args, **kwargs: iter([]))

    assert fresh_calls == ["edited-wing"]


@pytest.mark.parametrize("payload", ["{invalid: yaml: :\n", "- not\n- a\n- mapping\n"])
@pytest.mark.parametrize("entry_point", ["mine-all", "watcher"])
def test_invalid_config_fails_before_store_open(payload, entry_point, tmp_path):
    parent = tmp_path / "projects"
    parent.mkdir()
    project = parent / "bad-project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "mempalace.yaml").write_text(payload, encoding="utf-8")

    with (
        patch("mempalace_code.storage.open_store", side_effect=AssertionError("store opened")),
        patch("mempalace_code.watcher.get_collection", side_effect=AssertionError("store opened")),
        pytest.raises(SystemExit) as exc_info,
    ):
        _invoke_batch_or_watcher(entry_point, parent, project, tmp_path / "palace")

    assert exc_info.value.code == 1
    with pytest.raises(InvalidProjectConfigError) as config_error:
        resolve_wing_for_project(str(project))
    assert config_error.value.code == "invalid_project_config"


@pytest.mark.parametrize("entry_point", ["mine-all", "watcher"])
def test_canonical_duplicate_wings_fail_before_store_open(entry_point, tmp_path):
    parent = tmp_path / "projects"
    parent.mkdir()
    first = parent / "first"
    second = parent / "second"
    _write_project(first, wing="Shared Wing")
    _write_project(second, wing="shared_wing")

    with (
        patch("mempalace_code.storage.open_store", side_effect=AssertionError("store opened")),
        patch("mempalace_code.watcher.get_collection", side_effect=AssertionError("store opened")),
        pytest.raises(SystemExit) as exc_info,
    ):
        _invoke_batch_or_watcher(entry_point, parent, parent, tmp_path / "palace")

    assert exc_info.value.code == 1
