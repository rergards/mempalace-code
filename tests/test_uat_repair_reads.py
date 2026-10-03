"""UAT regressions: a degraded or missing palace fails loudly instead of looking empty."""

import glob
import os
import sys
from unittest.mock import patch

import pytest

from mempalace_code.cli import main
from mempalace_code.storage import PalaceReadError, open_store


def _data_files(palace: str) -> set:
    return set(glob.glob(os.path.join(palace, "lance", "mempalace_drawers.lance", "data", "*")))


def _make_palace(root) -> tuple[str, list[set]]:
    palace = str(root / "palace")
    store = open_store(palace, create=True)
    fragments = []
    for i in range(3):
        before = _data_files(palace)
        store.add(
            ids=[f"drawer_w_r_{i:04d}"],
            documents=[f"Diary entry number {i} about the refund gateway"],
            metadatas=[{"wing": "wing_uat", "room": "diary"}],
        )
        fragments.append(_data_files(palace) - before)
    return palace, fragments


def _run(argv, capsys):
    code = 0
    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def degraded_palace(tmp_path):
    palace, fragments = _make_palace(tmp_path)
    for path in fragments[0]:
        os.remove(path)
    return palace


def test_store_reads_raise_instead_of_returning_empty(degraded_palace):
    store = open_store(degraded_palace, create=False, read_only=True)

    with pytest.raises(PalaceReadError) as excinfo:
        store.get(include=["documents"])
    assert f"--palace {degraded_palace} health" in str(excinfo.value)
    with pytest.raises(PalaceReadError):
        store.query(query_texts=["refund"], n_results=3)
    with pytest.raises(PalaceReadError):
        list(store.iter_all())
    with pytest.raises(PalaceReadError):
        store.count_by_pair("wing", "room")


def test_rejected_filter_is_not_reported_as_damage(tmp_path):
    palace, _ = _make_palace(tmp_path)
    store = open_store(palace, create=False, read_only=True)

    with pytest.raises(RuntimeError) as excinfo:
        store.get(where={"no_such_column": "x"})
    assert not isinstance(excinfo.value, PalaceReadError)


@pytest.mark.parametrize(
    "argv",
    [
        ["search", "refund gateway"],
        ["wake-up"],
        ["status"],
        ["status", "--summary"],
    ],
    ids=["search", "wake-up", "status", "status-summary"],
)
def test_read_commands_fail_loudly_on_a_degraded_palace(degraded_palace, capsys, argv):
    code, out, err = _run(["--palace", degraded_palace, *argv], capsys)

    assert code == 1
    assert "unreadable" in err
    assert "Traceback" not in err
    assert "No memories yet" not in out
    assert "No results found" not in out


def test_export_of_a_degraded_palace_writes_nothing(degraded_palace, tmp_path, capsys):
    out_path = tmp_path / "export.jsonl"

    code, _, err = _run(["--palace", degraded_palace, "export", "--out", str(out_path)], capsys)

    assert code == 1
    assert "unreadable" in err
    assert "Exported 0 drawers" not in err
    assert not out_path.exists()


def test_mcp_search_reports_a_degraded_palace(degraded_palace):
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.search import tool_search

    with patch.dict(os.environ, {"MEMPALACE_PALACE_PATH": degraded_palace}):
        assert runtime._config.palace_path == degraded_palace
        result = tool_search("refund gateway")

    assert "unreadable" in result["error"]
    assert "health" in result["error"]


@pytest.mark.parametrize("summary", [False, True], ids=["status", "status-summary"])
@pytest.mark.parametrize("shape", ["missing", "project-dir", "failed-first-mine"])
def test_status_without_a_palace_exits_nonzero(tmp_path, capsys, summary, shape):
    target = tmp_path / "target"
    if shape != "missing":
        target.mkdir()
    if shape == "failed-first-mine":
        (target / "lance").mkdir()

    code, out, _ = _run(
        ["--palace", str(target), "status"] + (["--summary"] if summary else []), capsys
    )

    assert code == 1
    assert f"No palace found at {target}" in out
