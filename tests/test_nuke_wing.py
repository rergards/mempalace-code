"""scripts/nuke_wing.py deletes a wing only with --yes, from the configured palace."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "nuke_wing.py"
_spec = importlib.util.spec_from_file_location("nuke_wing", _SCRIPT)
assert _spec is not None
assert _spec.loader is not None
nuke_wing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nuke_wing)


class FakeStore:
    def __init__(self, wings):
        self.wings = dict(wings)
        self.deleted = []

    def count_by(self, column):
        assert column == "wing"
        return dict(self.wings)

    def delete_wing(self, wing):
        self.deleted.append(wing)
        return self.wings.pop(wing, 0)


@pytest.fixture
def opened(monkeypatch, tmp_path):
    store = FakeStore({"proj": 3})
    paths = []

    def fake_open_store(path, create):
        assert create is False
        paths.append(path)
        return store

    monkeypatch.setattr(nuke_wing, "open_store", fake_open_store)
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(tmp_path / "configured"))
    return store, paths


def test_without_yes_reports_the_count_and_deletes_nothing(opened, tmp_path, capsys):
    store, paths = opened

    assert nuke_wing.main(["proj"]) == 0

    assert store.deleted == []
    assert paths == [str(tmp_path / "configured")]
    assert "has 3 drawers" in capsys.readouterr().out


def test_yes_deletes_the_wing_from_an_explicit_palace(opened, tmp_path, capsys):
    store, paths = opened

    assert nuke_wing.main(["proj", "--palace", str(tmp_path / "other"), "--yes"]) == 0

    assert store.deleted == ["proj"]
    assert paths == [str(tmp_path / "other")]
    assert "Deleted 3 drawers" in capsys.readouterr().out


def test_unknown_wing_deletes_nothing(opened, capsys):
    store, _paths = opened

    assert nuke_wing.main(["absent", "--yes"]) == 1

    assert store.deleted == []
    assert "nothing deleted" in capsys.readouterr().err


def test_help_is_not_treated_as_a_wing(opened):
    store, paths = opened

    with pytest.raises(SystemExit) as caught:
        nuke_wing.main(["--help"])

    assert caught.value.code == 0
    assert paths == []
    assert store.deleted == []


def test_missing_palace_is_reported_without_a_traceback(tmp_path, capsys):
    palace = tmp_path / "missing"

    assert nuke_wing.main(["proj", "--palace", str(palace), "--yes"]) == 1

    assert f"Cannot open palace {palace}" in capsys.readouterr().err
    assert not palace.exists()
