"""Tests for EntityRegistry atomic save behavior."""

import json
import os
import platform
from pathlib import Path

import pytest

from mempalace_code.entity_registry import EntityRegistry


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


def test_load_malformed_json_still_returns_empty_registry(tmp_path):
    registry_file = tmp_path / "entity_registry.json"
    registry_file.write_text("{this is not valid json!!!}")

    loaded = EntityRegistry.load(config_dir=tmp_path)
    assert loaded.mode == "personal"
    assert loaded.people == {}
    assert loaded.projects == []
    assert loaded.ambiguous_flags == []


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
