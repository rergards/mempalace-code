"""Tests for EntityRegistry atomic save behavior."""

import json
import os
import platform
from pathlib import Path

import pytest

from mempalace_code import entity_registry
from mempalace_code.entity_registry import EntityRegistry
from mempalace_code.onboarding import quick_setup


def _build_registry(tmp_path: Path) -> EntityRegistry:
    reg = EntityRegistry.load(config_dir=tmp_path)
    reg._data["mode"] = "work"
    reg._data["people"]["Alice"] = {
        "source": "onboarding",
        "contexts": ["work"],
        "aliases": [],
        "relationship": "colleague",
        "confidence": 1.0,
    }
    reg._data["projects"] = ["MemPalace"]
    reg._data["ambiguous_flags"] = []
    reg._data["wiki_cache"] = {
        "Sam": {"inferred_type": "person", "confidence": 0.9, "confirmed": True}
    }
    return reg


def test_summary_omits_empty_people_name_list(tmp_path):
    reg = EntityRegistry.load(config_dir=tmp_path)

    assert reg.summary().splitlines()[1] == "People: 0"


def test_summary_includes_populated_people_name_list(tmp_path):
    reg = _build_registry(tmp_path)

    assert reg.summary().splitlines()[1] == "People: 1 (Alice)"


def test_summary_truncates_people_name_list_after_eight(tmp_path):
    reg = EntityRegistry.load(config_dir=tmp_path)
    for index in range(1, 10):
        reg._data["people"][f"Person {index}"] = {}

    assert reg.summary().splitlines()[1] == (
        "People: 9 (Person 1, Person 2, Person 3, Person 4, "
        "Person 5, Person 6, Person 7, Person 8...)"
    )


def test_save_writes_valid_json_and_loads_existing_data(tmp_path):
    reg = _build_registry(tmp_path)
    reg.save()

    registry_file = tmp_path / "entity_registry.json"
    assert registry_file.exists()

    raw = json.loads(registry_file.read_text())
    assert raw["mode"] == "work"
    assert "Alice" in raw["people"]
    assert raw["projects"] == ["MemPalace"]
    assert raw["wiki_cache"]["Sam"]["inferred_type"] == "person"

    loaded = EntityRegistry.load(config_dir=tmp_path)
    assert loaded.mode == "work"
    assert "Alice" in loaded.people
    assert loaded.projects == ["MemPalace"]
    assert loaded._data["wiki_cache"]["Sam"]["confirmed"] is True


def test_save_failure_before_replace_preserves_existing_registry(tmp_path, monkeypatch):
    reg = _build_registry(tmp_path)
    reg.save()

    original_bytes = (tmp_path / "entity_registry.json").read_bytes()

    reg2 = EntityRegistry.load(config_dir=tmp_path)
    reg2._data["mode"] = "personal"
    reg2._data["people"]["Bob"] = {
        "source": "onboarding",
        "contexts": ["personal"],
        "aliases": [],
        "relationship": "friend",
        "confidence": 1.0,
    }

    def broken_replace(_src, _dst):
        raise OSError("simulated crash at replace boundary")

    monkeypatch.setattr(os, "replace", broken_replace)

    with pytest.raises(OSError, match="simulated crash"):
        reg2.save()

    assert (tmp_path / "entity_registry.json").read_bytes() == original_bytes

    # No partial temp file should remain
    tmp_files = list(tmp_path.glob(".entity_registry_*.tmp"))
    assert tmp_files == [], f"leftover temp files: {tmp_files}"

    loaded = EntityRegistry.load(config_dir=tmp_path)
    assert loaded.mode == "work"
    assert "Alice" in loaded.people
    assert "Bob" not in loaded.people


def test_temp_name_permission_error_is_not_retried(tmp_path, monkeypatch):
    reg = _build_registry(tmp_path)
    reg.save()
    registry_file = tmp_path / "entity_registry.json"
    original = registry_file.read_bytes()
    reg._data["mode"] = "personal"
    attempts = 0

    def refuse(_path, _flags, _mode):
        nonlocal attempts
        attempts += 1
        raise PermissionError("directory refuses temporary files")

    monkeypatch.setattr(entity_registry.os, "open", refuse)

    with pytest.raises(PermissionError, match="refuses temporary"):
        reg.save()

    assert attempts == 1
    assert registry_file.read_bytes() == original
    assert list(tmp_path.glob(".entity_registry_*.tmp")) == []


def test_temp_name_collision_retries_then_saves(tmp_path, monkeypatch):
    reg = _build_registry(tmp_path)
    real_open = entity_registry.os.open
    attempts = 0

    def collide_twice(path, flags, mode):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise FileExistsError("occupied")
        return real_open(path, flags, mode)

    monkeypatch.setattr(entity_registry.os, "open", collide_twice)

    reg.save()

    assert attempts == 3
    assert json.loads((tmp_path / "entity_registry.json").read_text())["mode"] == "work"


def test_temp_name_collisions_are_bounded(tmp_path, monkeypatch):
    reg = _build_registry(tmp_path)
    attempts = 0

    def collide(_path, _flags, _mode):
        nonlocal attempts
        attempts += 1
        raise FileExistsError("occupied")

    monkeypatch.setattr(entity_registry.os, "open", collide)

    with pytest.raises(FileExistsError, match="occupied"):
        reg.save()

    assert attempts == entity_registry._TEMP_NAME_ATTEMPTS


def test_packaged_registry_has_no_wikipedia_network_api():
    assert not hasattr(entity_registry, "_wikipedia_lookup")
    assert not hasattr(EntityRegistry, "research")
    assert not hasattr(EntityRegistry, "confirm_research")


def test_load_malformed_json_fails_closed_and_preserves_registry(tmp_path):
    registry_file = tmp_path / "entity_registry.json"
    original = b"{this is not valid json!!!}"
    registry_file.write_bytes(original)

    with pytest.raises(ValueError, match="not valid JSON"):
        EntityRegistry.load(config_dir=tmp_path)

    assert registry_file.read_bytes() == original


def test_load_non_object_json_fails_closed_and_preserves_registry(tmp_path):
    registry_file = tmp_path / "entity_registry.json"
    original = b'["Alice"]'
    registry_file.write_bytes(original)

    with pytest.raises(ValueError, match="root must be a JSON object"):
        EntityRegistry.load(config_dir=tmp_path)

    assert registry_file.read_bytes() == original


def test_load_invalid_utf8_fails_closed_and_preserves_registry(tmp_path):
    registry_file = tmp_path / "entity_registry.json"
    original = b'{"people": ["Alic\xffe"]}'
    registry_file.write_bytes(original)

    with pytest.raises(ValueError, match="not valid JSON"):
        EntityRegistry.load(config_dir=tmp_path)

    assert registry_file.read_bytes() == original


def test_quick_setup_refuses_to_replace_malformed_registry(tmp_path):
    registry_file = tmp_path / "entity_registry.json"
    original = b'{"people":{"Alice":{"relationship":"friend"}}'
    registry_file.write_bytes(original)

    with pytest.raises(ValueError, match="not valid JSON"):
        quick_setup(
            "work",
            [{"name": "Bob", "relationship": "colleague", "context": "work"}],
            config_dir=tmp_path,
        )

    assert registry_file.read_bytes() == original


def test_load_read_error_fails_closed(tmp_path, monkeypatch):
    registry_file = tmp_path / "entity_registry.json"
    registry_file.write_text("{}")

    def unreadable(_self):
        raise PermissionError("registry is unreadable")

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    with pytest.raises(PermissionError, match="registry is unreadable"):
        EntityRegistry.load(config_dir=tmp_path)


def test_save_sets_restrictive_permissions_where_supported(tmp_path):
    reg = _build_registry(tmp_path)
    reg.save()

    registry_file = tmp_path / "entity_registry.json"
    assert registry_file.exists()

    if platform.system() == "Windows":
        pytest.skip("chmod/stat mode bits not enforced on this platform")

    mode = registry_file.stat().st_mode & 0o777
    assert mode & 0o077 == 0, f"group/other bits should be 0, got {oct(mode)}"
    assert mode & 0o600 == 0o600, f"owner read/write bits should be set, got {oct(mode)}"
