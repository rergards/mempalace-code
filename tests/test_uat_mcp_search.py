"""UAT round-2 regressions for the MCP write/search/read tools.

Each test names the UAT issue id it guards. Tool contracts go through
``handle_request`` with the real registry, so schema bounds and the -32602
mapping are exercised exactly as a client sees them.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from unittest.mock import patch

import pytest

from mempalace_code.errors import InvalidArgumentError
from mempalace_code.storage import open_store


@pytest.fixture
def mcp(monkeypatch, config, palace_path, kg):
    """Call real tools through handle_request against an isolated palace and KG."""
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.dispatch import handle_request
    from mempalace_code.mcp.registry import TOOLS

    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_kg", kg)
    monkeypatch.setattr(runtime, "_store", None)
    monkeypatch.delenv("MEMPALACE_AGENT_NAME", raising=False)

    def call(name, arguments=None):
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        return handle_request(request, active_registry=TOOLS)

    return call


def _payload(response: dict) -> dict:
    assert "result" in response, response
    return json.loads(response["result"]["content"][0]["text"])


@pytest.mark.parametrize(
    ("counts", "expected_count"),
    [
        ({}, 5),
        ({"limit": 3}, 3),
        ({"max_results": 3}, 3),
        ({"max_results": "3"}, 3),
        ({"max_results": 3.0}, 3),
        ({"limit": 3, "max_results": 3}, 3),
        ({"limit": "3", "max_results": 3.0}, 3),
        ({"max_results": 1}, 1),
        ({"max_results": 50}, 7),
    ],
)
def test_search_count_alias_returns_the_same_hits(mcp, palace_path, counts, expected_count):
    store = open_store(palace_path, create=True)
    store.add(
        ids=[f"search_alias_{i}" for i in range(7)],
        documents=[f"Storage count alias reference {i}" for i in range(7)],
        metadatas=[{"wing": "alias", "room": "reference"} for _ in range(7)],
    )
    arguments = {"query": "Storage count alias reference", "wing": "alias", "room": "reference"}
    hits = _payload(mcp("mempalace_search", {**arguments, **counts}))["results"]
    canonical_count = int(counts.get("max_results", counts.get("limit", 5)))
    canonical = _payload(mcp("mempalace_search", {**arguments, "limit": canonical_count}))
    assert len(hits) == expected_count
    assert hits == canonical["results"]
    assert hits == _payload(mcp("mempalace_search", {**arguments, **counts}))["results"]


@pytest.mark.parametrize("value", [0, -1, 51, True, None, 2.5, "invalid", [], {}])
@pytest.mark.parametrize("canonical", [{}, {"limit": 3}])
def test_search_count_alias_rejects_invalid_values_before_search(mcp, value, canonical):
    with patch("mempalace_code.searcher.search_memories") as search:
        response = mcp("mempalace_search", {"query": "storage", "max_results": value, **canonical})
    assert response["error"]["code"] == -32602
    assert "max_results" in response["error"]["message"]
    search.assert_not_called()


def test_search_count_alias_rejects_conflicts_before_search(mcp):
    with patch("mempalace_code.searcher.search_memories") as search:
        response = mcp("mempalace_search", {"query": "storage", "limit": 5, "max_results": 3})
    assert response["error"]["code"] == -32602
    assert "limit and max_results must match" in response["error"]["message"]
    search.assert_not_called()


def test_search_count_alias_is_advertised_in_tools_list(mcp):
    from mempalace_code.mcp.dispatch import handle_request

    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    schema = next(t for t in response["result"]["tools"] if t["name"] == "mempalace_search")[
        "inputSchema"
    ]
    for name in ("limit", "max_results"):
        assert schema["properties"][name]["type"] == "integer"
        assert schema["properties"][name]["minimum"] == 1
        assert schema["properties"][name]["maximum"] == 50
    assert schema["required"] == ["query"]


@pytest.fixture
def missing_palace_mcp(monkeypatch, tmp_path):
    """Tools wired to a palace path that does not exist and a KG that was never opened."""
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.dispatch import handle_request
    from mempalace_code.mcp.registry import TOOLS

    palace = tmp_path / "typo_palace"

    class Config:
        palace_path = str(palace)

    monkeypatch.setattr(runtime, "_config", Config())
    monkeypatch.setattr(runtime, "_kg", None)
    monkeypatch.setattr(runtime, "_store", None)
    monkeypatch.delenv("MEMPALACE_AGENT_NAME", raising=False)

    def call(name, arguments=None):
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        return handle_request(request, active_registry=TOOLS)

    return call, palace


# ── mcp-r2-4: an explicit empty selector flag is an error, not "flag absent" ──


@pytest.mark.parametrize(
    "argv", [["--tools="], ["--tools=,"], ["--include="], ["--exclude="], ["--exclude= "]]
)
def test_empty_selector_flag_exits_nonzero(argv, capsys):
    from mempalace_code.mcp.dispatch import main

    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 1
    flag = argv[0].split("=")[0]
    assert f"{flag} was given no tool selectors" in capsys.readouterr().err


# ── agent-r2-1: repo-relative file_glob values match stored absolute paths ────


@pytest.mark.parametrize(
    ("glob", "matches"),
    [
        ("pkg/disk_budget.py", True),
        ("disk_budget.py", True),
        ("pkg/*.py", True),
        ("*/disk_budget.py", True),
        ("/abs/repo/pkg/disk_budget.py", True),
        ("budget.py", False),
        ("other/disk_budget.py", False),
        ("/pkg/disk_budget.py", False),
    ],
)
def test_file_glob_matches_relative_paths_at_a_component_boundary(glob, matches):
    from mempalace_code.searcher import _file_glob_matches

    assert _file_glob_matches("/abs/repo/pkg/disk_budget.py", glob) is matches


def test_code_search_relative_file_glob_finds_absolute_stored_path(palace_path):
    from mempalace_code.searcher import code_search

    store = open_store(palace_path, create=True)
    source = "/abs/repo/pkg/disk_budget.py"
    store.add(
        ids=["drawer_repo_code_budget"],
        documents=["def check_disk_budget(limit):\n    return limit > 0\n"],
        metadatas=[
            {
                "wing": "repo",
                "room": "code",
                "source_file": source,
                "language": "python",
                "symbol_name": "check_disk_budget",
                "symbol_type": "function",
            }
        ],
    )

    for glob in ("pkg/disk_budget.py", "disk_budget.py", "pkg/*.py"):
        result = code_search(palace_path, "disk budget", file_glob=glob, n_results=2)
        assert [hit["source_file"] for hit in result["results"]] == [source], glob


# ── mcp-r2-5 / agent-r2-5: documented ranges are schema bounds (-32602) ──────


@pytest.mark.parametrize(
    ("tool", "arguments", "fragment"),
    [
        ("mempalace_search", {"query": "a", "limit": 51}, "limit (expected 1 to 50, got 51)"),
        (
            "mempalace_code_search",
            {"query": "a", "n_results": 500},
            "n_results (expected 1 to 50, got 500)",
        ),
        (
            "mempalace_explain_subsystem",
            {"query": "a", "n_results": 51},
            "n_results (expected 1 to 50, got 51)",
        ),
        (
            "mempalace_file_context",
            {"source_file": "a.py", "limit": 0},
            "limit (expected 1 to 100, got 0)",
        ),
        (
            "mempalace_file_context",
            {"source_file": "a.py", "limit": 1000},
            "limit (expected 1 to 100, got 1000)",
        ),
        (
            "mempalace_file_context",
            {"source_file": "a.py", "offset": -5},
            "offset (expected at least 0, got -5)",
        ),
    ],
)
def test_out_of_range_paging_is_invalid_params(mcp, tool, arguments, fragment):
    response = mcp(tool, arguments)

    assert response["error"]["code"] == -32602
    assert fragment in response["error"]["message"]


def test_mine_relative_directory_is_invalid_params(mcp):
    response = mcp("mempalace_mine", {"directory": "relative/dir"})

    assert response["error"]["code"] == -32602
    assert "directory must be an absolute path" in response["error"]["message"]


# ── mcp-r2-7: oversized query and drawer text are bounded ────────────────────


def test_oversized_query_and_content_are_rejected_before_any_work(mcp, palace_path):
    search = mcp("mempalace_search", {"query": "lorem ipsum " * 2000})
    add = mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": "x" * 100_001})

    assert search["error"]["code"] == -32602
    assert "query (expected at most 10000 characters" in search["error"]["message"]
    assert add["error"]["code"] == -32602
    assert "content (expected at most 100000 characters" in add["error"]["message"]
    assert list(Path(palace_path).iterdir()) == []


# ── agent-r2-4: a profile's descriptions name only tools that profile exposes ─


def test_profile_descriptions_name_only_exposed_tools():
    from mempalace_code.mcp.registry import TOOLS
    from mempalace_code.mcp_tool_profiles import PROFILES

    for profile, names in PROFILES.items():
        for name in names:
            spec = TOOLS[name]
            text = json.dumps([spec["description"], spec["input_schema"]])
            named = set(re.findall(r"mempalace_[a-z_]+", text)) & set(TOOLS)
            assert named <= names, (profile, name, sorted(named - names))


def test_no_description_names_another_tool():
    """A custom --tools selection may expose any single tool without its neighbours."""
    from mempalace_code.mcp.registry import TOOLS

    for name, spec in TOOLS.items():
        text = json.dumps([spec["description"], spec["input_schema"]])
        named = set(re.findall(r"mempalace_[a-z_]+", text)) & set(TOOLS) - {name}
        assert not named, (name, sorted(named))


# ── agent-r2-7: a manual drawer's source_file is null, not "?" ───────────────


def test_manual_drawer_search_hit_has_null_source_file(mcp):
    added = _payload(
        mcp(
            "mempalace_add_drawer",
            {"wing": "mpc", "room": "decisions", "content": "Zebra quokka storage decision."},
        )
    )
    hits = _payload(mcp("mempalace_search", {"query": "Zebra quokka storage decision"}))

    hit = next(hit for hit in hits["results"] if hit["id"] == added["drawer_id"])
    assert hit["source_file"] is None


# ── gap-9: n_results below 1 is an error; swapped arguments are named ────────


@pytest.mark.parametrize("n_results", [0, -3])
def test_python_search_rejects_non_positive_counts(palace_path, n_results):
    from mempalace_code.searcher import code_search, search_memories

    with pytest.raises(InvalidArgumentError, match="n_results"):
        search_memories("x", palace_path, n_results=n_results)
    with pytest.raises(InvalidArgumentError, match="n_results"):
        code_search(palace_path, "x", n_results=n_results)


def test_swapped_search_arguments_get_an_argument_order_hint(palace_path, tmp_path, monkeypatch):
    from mempalace_code.searcher import code_search, search_memories

    open_store(palace_path, create=True)
    monkeypatch.chdir(tmp_path)

    swapped_code = code_search("refund", palace_path)
    swapped_memories = search_memories(palace_path, "refund")

    assert swapped_code["error"] == "No palace found"
    assert "code_search(palace_path, query, ...)" in swapped_code["hint"]
    assert "search_memories(query, palace_path, ...)" in swapped_memories["hint"]


# ── agent-r2-2 / mcp-r2-6 / agent-r2-6: a missing palace is never created ────


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("mempalace_add_drawer", {"wing": "mpc", "room": "decisions", "content": "Use LanceDB."}),
        ("mempalace_diary_write", {"agent_name": "uat", "entry": "Session one."}),
        ("mempalace_delete_drawer", {"drawer_id": "drawer_x"}),
        ("mempalace_delete_wing", {"wing": "mpc"}),
        ("mempalace_kg_query", {"entity": "x"}),
        ("mempalace_kg_add", {"subject": "a", "predicate": "uses", "object": "b"}),
        ("mempalace_kg_stats", {}),
    ],
)
def test_writes_and_kg_on_missing_palace_answer_like_reads(missing_palace_mcp, tool, arguments):
    call, palace = missing_palace_mcp
    status = _payload(call("mempalace_status"))

    payload = _payload(call(tool, arguments))

    assert status["error"] == "No palace found"
    assert payload == status
    assert not palace.exists()


def test_kg_on_palace_path_that_is_a_file_is_no_palace(missing_palace_mcp):
    call, palace = missing_palace_mcp
    palace.write_text("x\n")

    response = call("mempalace_kg_query", {"entity": "x"})

    assert _payload(response)["error"] == "No palace found"
    assert response["result"]["isError"] is True


def test_mine_still_creates_the_palace(missing_palace_mcp, tmp_path):
    call, palace = missing_palace_mcp
    project = tmp_path / "proj"
    project.mkdir()
    (project / "mempalace.yaml").write_text("wing: proj\nrooms:\n  - name: general\n")
    (project / "app.py").write_text("def main():\n    return 'mined into a new palace'\n" * 5)

    result = _payload(call("mempalace_mine", {"directory": str(project)}))

    assert result["success"] is True, result
    assert (palace / "lance").is_dir()


# ── mcp-r2-3: a path-like wing is refused by mine as by add_drawer ───────────


def test_mcp_mine_refuses_path_like_wing(mcp, tmp_path, palace_path):
    project = tmp_path / "shop2"
    project.mkdir()
    (project / "mempalace.yaml").write_text("wing: shop2\nrooms:\n  - name: general\n")

    response = mcp("mempalace_mine", {"directory": str(project), "wing": "a/b"})

    assert response["error"]["code"] == -32602
    assert "wing 'a/b' must not contain" in response["error"]["message"]
    assert list(Path(palace_path).iterdir()) == []


def test_library_mine_refuses_path_like_wing(tmp_path):
    from mempalace_code.mining.orchestrator import mine

    with pytest.raises(InvalidArgumentError, match="must not contain"):
        mine(project_dir=str(tmp_path), palace_path=str(tmp_path / "p"), wing_override="x/y")
    assert not (tmp_path / "p").exists()


def test_cli_mine_refuses_path_like_wing(tmp_path, capsys):
    from mempalace_code.cli import main

    argv = ["mempalace-code", "--palace", str(tmp_path / "p"), "mine", str(tmp_path)]
    with patch.object(sys, "argv", [*argv, "--wing", "x/y"]):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--wing 'x/y' must not contain" in err
    assert "Next:" in err
    assert not (tmp_path / "p").exists()


# ── mcp-r2-1: writes wait long enough, load the model outside the lease ──────


def test_add_drawer_waits_for_a_short_writer_instead_of_failing(mcp, palace_path):
    from mempalace_code.mcp import runtime
    from mempalace_code.operation_lock import palace_write_lease

    assert runtime.MCP_WRITE_LEASE_WAIT_SECONDS >= 30
    held = threading.Event()

    def other_writer():
        with palace_write_lease(palace_path, "mine", wait=5):
            held.set()
            time.sleep(1.0)

    thread = threading.Thread(target=other_writer)
    thread.start()
    held.wait(5)
    started = time.monotonic()
    result = _payload(
        mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": "Written after a wait."})
    )
    thread.join()

    assert result["success"] is True, result
    assert time.monotonic() - started >= 0.5


def test_busy_palace_returns_a_retryable_error(mcp, palace_path, monkeypatch):
    from mempalace_code.mcp import runtime
    from mempalace_code.operation_lock import palace_write_lease

    monkeypatch.setattr(runtime, "MCP_WRITE_LEASE_WAIT_SECONDS", 0.2)
    held, release = threading.Event(), threading.Event()

    def other_writer():
        with palace_write_lease(palace_path, "mine", wait=5):
            held.set()
            release.wait(10)

    thread = threading.Thread(target=other_writer)
    thread.start()
    held.wait(5)
    try:
        response = mcp("mempalace_diary_write", {"agent_name": "uat", "entry": "busy entry"})
    finally:
        release.set()
        thread.join()

    payload = _payload(response)
    assert response["result"]["isError"] is True
    assert payload["success"] is False
    assert payload["retryable"] is True
    assert "Another MemPalace writer" in payload["error"]
    assert "Nothing was written" in payload["hint"]


def test_embedding_model_loads_before_the_lease_is_taken(mcp, monkeypatch, collection):
    from mempalace_code.mcp import runtime
    from mempalace_code.storage import LanceStore

    del collection  # the palace has its table; the server has not loaded a model yet
    events: list[str] = []
    real_lease = runtime.palace_write_lease
    real_warmup = LanceStore.warmup

    def recording_lease(*args, **kwargs):
        events.append("lease")
        return real_lease(*args, **kwargs)

    def recording_warmup(self):
        events.append("warmup")
        real_warmup(self)

    monkeypatch.setattr(runtime, "palace_write_lease", recording_lease)
    monkeypatch.setattr(LanceStore, "warmup", recording_warmup)

    _payload(mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": "Warm first."}))

    assert events[:2] == ["warmup", "lease"]


def test_write_handle_under_the_lease_reuses_the_warmed_model(mcp, monkeypatch, collection):
    from mempalace_code.mcp import runtime
    from mempalace_code.storage import LanceStore

    del collection
    loads: list[int] = []
    real_validated = LanceStore._validated_embedder

    def counting_validated(self):
        loads.append(1)
        return real_validated(self)

    monkeypatch.setattr(LanceStore, "_validated_embedder", counting_validated)

    result = _payload(mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": "One."}))

    assert result["success"] is True, result
    assert runtime._store_read_only is False
    assert len(loads) == 1


@pytest.mark.parametrize("table", ["missing", "present"])
def test_warm_up_never_opens_a_write_handle_outside_the_lease(mcp, monkeypatch, palace_path, table):
    """Opening a write handle creates a missing table or migrates an old schema."""
    from mempalace_code.mcp import runtime

    if table == "present":
        open_store(palace_path, create=True)
    events: list[str] = []
    real_lease = runtime.palace_write_lease
    real_open_store = runtime.open_store

    def recording_lease(*args, **kwargs):
        events.append("lease")
        return real_lease(*args, **kwargs)

    def recording_open_store(*args, **kwargs):
        events.append("read" if kwargs.get("read_only") else "write")
        return real_open_store(*args, **kwargs)

    monkeypatch.setattr(runtime, "palace_write_lease", recording_lease)
    monkeypatch.setattr(runtime, "open_store", recording_open_store)

    result = _payload(mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": "Two."}))

    assert result["success"] is True, result
    assert "write" in events
    assert "lease" in events[: events.index("write")], events


def test_busy_palace_without_a_table_is_left_untouched(mcp, monkeypatch, palace_path):
    """Another process holds the lease (e.g. restore swapping lance/): nothing is created."""
    import subprocess

    from mempalace_code.mcp import runtime

    monkeypatch.setattr(runtime, "MCP_WRITE_LEASE_WAIT_SECONDS", 1.0)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time\n"
            "from mempalace_code.operation_lock import palace_write_lease\n"
            f"with palace_write_lease({palace_path!r}, 'restore', wait=5):\n"
            "    print('held', flush=True)\n"
            "    sys.stdin.readline()\n",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        before = sorted(p.name for p in Path(palace_path).iterdir())
        result = _payload(
            mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": "Busy."})
        )
        after = sorted(p.name for p in Path(palace_path).iterdir())
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(10)

    assert result["success"] is False, result
    assert result["retryable"] is True
    assert not (Path(palace_path) / "lance").exists()
    assert after == before


# ── agent-r2-3: one diary wing per identity ──────────────────────────────────


def test_diary_identity_spellings_share_one_wing(mcp, monkeypatch, palace_path):
    first = _payload(mcp("mempalace_diary_write", {"agent_name": "uat-agent", "entry": "One."}))
    monkeypatch.setenv("MEMPALACE_AGENT_NAME", "UAT Agent")
    second = _payload(mcp("mempalace_diary_write", {"entry": "Session two."}))

    taxonomy = open_store(palace_path, create=False).count_by_pair("wing", "room")
    assert first["success"] is True
    assert second["success"] is True
    assert {wing for wing, rooms in taxonomy.items() if "diary" in rooms} == {"wing_uat_agent"}
    read = _payload(mcp("mempalace_diary_read", {"agent_name": "uat_agent"}))
    assert read["total"] == 2


def test_diary_read_still_finds_legacy_hyphenated_wing(mcp, palace_path):
    store = open_store(palace_path, create=True)
    store.add(
        ids=["diary_legacy_1"],
        documents=["Legacy entry without agent metadata."],
        metadatas=[{"wing": "wing_uat-agent", "room": "diary", "filed_at": "2026-01-01T00:00:00"}],
    )

    read = _payload(mcp("mempalace_diary_read", {"agent_name": "uat-agent"}))

    assert [entry["content"] for entry in read["entries"]] == [
        "Legacy entry without agent metadata."
    ]


# ── diary-1: the printed verification names the exact entry ID ───────────────


def test_diary_verification_uses_the_entry_id(tmp_path, capsys):
    from mempalace_code.cli import main
    from mempalace_code.searcher import search_memories

    palace = tmp_path / "palace"
    for entry in ("x", "short"):
        argv = ["mempalace-code", "--palace", str(palace), "diary", "write", "--agent", "a"]
        with patch.object(sys, "argv", [*argv, "--entry", entry]):
            main()
    out = capsys.readouterr().out.split("Diary entry stored.")[-1]

    match = re.search(r"ID: (\S+)", out)
    assert match is not None
    entry_id = match.group(1)
    command = out.split("Verify before retry:")[1].strip().splitlines()[0]
    assert command.endswith("--results 10 --json")
    assert f"Success means a hit whose id is {entry_id}" in out
    clue = command.split(" search ", 1)[1].split(" --wing")[0].strip("'\"")
    hits = search_memories(clue, str(palace), wing="wing_a", room="diary", n_results=10)
    assert entry_id in {hit["id"] for hit in hits["results"]}


# ── gap-7: an NFD spelling of a stored NFC path resolves ─────────────────────


def test_read_resolves_nfd_spelling_of_stored_path(palace_path, tmp_path):
    from mempalace_code.reader import SourceRows, resolve_source_rows

    stored = unicodedata.normalize("NFC", str(tmp_path / "Мой проект (v2)/with space/nfd_é.py"))
    store = open_store(palace_path, create=True)
    store.add(
        ids=["drawer_p_general_nfd"],
        documents=["x = 1\n"],
        metadatas=[
            {"wing": "p", "room": "general", "source_file": stored, "line_start": 1, "line_end": 1}
        ],
    )

    for query in (
        unicodedata.normalize("NFD", "with space/nfd_é.py"),
        unicodedata.normalize("NFD", stored),
    ):
        assert query != unicodedata.normalize("NFC", query)
        rows = resolve_source_rows(store, query)
        assert isinstance(rows, SourceRows), rows
        assert rows.source_file == stored


# ── cleanup-1: the dry run lists what the real cleanup removes ───────────────


def _versions(*offsets: float, compact: bool = False) -> list[dict]:
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 9, 1, tzinfo=UTC)
    metadata = {"total_fragments": 1, "total_deletion_files": 0} if compact else {}
    return [
        {"version": number, "timestamp": base + timedelta(seconds=offset), "metadata": metadata}
        for number, offset in enumerate(offsets, start=1)
    ]


def test_cleanup_plan_keeps_versions_committed_just_before_the_reader_anchor():
    from datetime import timedelta

    from mempalace_code.storage import cleanup_plan

    versions = _versions(0, 10, 20, 29.5, 30)
    now = versions[-1]["timestamp"] + timedelta(minutes=5)

    plan = cleanup_plan(versions, now, 0)

    # Compaction commits newer versions, so v5 stops being current and is kept for
    # readers together with v4, committed within the 1 s margin before it.
    assert plan == {"remove": [1, 2, 3], "kept_for_readers": [4], "compacts_first": True}
    assert cleanup_plan(_versions(0, 10, 20, 29.5, 30, compact=True), now, 0)["remove"] == [
        1,
        2,
        3,
        4,
    ]
    assert cleanup_plan(versions, now, 7)["remove"] == []


def test_cleanup_dry_run_matches_the_real_run(palace_path, monkeypatch):
    from datetime import timedelta

    from mempalace_code import storage
    from mempalace_code.cli_commands.maintenance import _cleanup_preview

    monkeypatch.setattr(storage, "READER_VERSION_GRACE", timedelta(seconds=1))
    store = open_store(palace_path, create=True)
    # The last two writes land within the 1 s cutoff margin of each other, as MCP
    # writes do; the real run keeps the earlier one for readers.
    for index, pause in enumerate((1.2, 1.2, 0.3, 1.5)):
        store.add(
            ids=[f"drawer_w_r_{index}"],
            documents=[f"Cleanup preview note number {index}."],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        time.sleep(pause)
    table = store._table
    assert table is not None
    before = {version["version"] for version in table.list_versions()}

    preview = _cleanup_preview(store, 0, False)
    result = store.cleanup_stale_fragments(older_than_days=0)
    table = store._table
    assert table is not None
    after = {version["version"] for version in table.list_versions()}

    assert result["ok"] is True
    assert preview["versions_to_remove"]
    assert preview["versions_kept_for_readers"]
    assert before - after == set(preview["versions_to_remove"])
    assert result["versions_kept_for_readers"] == len(preview["versions_kept_for_readers"])


# ── mcp-r2-2: a re-mined file keeps its old drawers until the new ones commit ─


def test_full_remine_replaces_each_file_in_one_commit(tmp_path, monkeypatch):
    from mempalace_code.mining.orchestrator import mine
    from mempalace_code.storage import LanceStore

    project = tmp_path / "proj"
    project.mkdir()
    (project / "mempalace.yaml").write_text("wing: proj\nrooms:\n  - name: general\n")
    source = project / "app.py"
    functions = [
        f"def handler_{n}(value):\n    '''Handle case {n} of the checkout flow.'''\n"
        + "".join(f"    value = value + {n} * {k}\n" for k in range(12))
        + "    return value\n"
        for n in range(8)
    ]
    source.write_text("\n\n".join(functions))
    palace = str(tmp_path / "palace")
    mine(project_dir=str(project), palace_path=palace)
    store = open_store(palace, create=False)
    stored_path = str(source.resolve())
    old_ids = set(store.get(where={"source_file": stored_path})["ids"])
    store.add(
        ids=["drawer_proj_notes_manual"],
        documents=["A manual note that cites app.py."],
        metadatas=[{"wing": "proj", "room": "notes", "source_file": stored_path}],
    )
    assert len(old_ids) > 1

    source.write_text("\n\n".join(functions[:2]))
    seen_during_write: list[set] = []
    real_replace = LanceStore.replace_mined_sources

    def observing_replace(self, source_files, wing, ids, documents, metadatas):
        visible = set(
            open_store(palace, create=False).get(where={"source_file": stored_path})["ids"]
        )
        seen_during_write.append(visible)
        return real_replace(self, source_files, wing, ids, documents, metadatas)

    monkeypatch.setattr(LanceStore, "replace_mined_sources", observing_replace)
    mine(project_dir=str(project), palace_path=palace, incremental=False)

    after = open_store(palace, create=False).get(where={"source_file": stored_path})["ids"]
    assert seen_during_write, "the full re-mine replaced the file through one merge"
    assert old_ids <= seen_during_write[0], "old drawers stayed readable until the new commit"
    assert "drawer_proj_notes_manual" in after
    mined_after = set(after) - {"drawer_proj_notes_manual"}
    assert mined_after
    assert len(mined_after) < len(old_ids), "stale chunks of the shorter file were dropped"


# ── gap-5: a read-only palace is named as such, not as a raw LanceDB error ────


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_add_drawer_on_read_only_palace_names_the_palace(mcp, palace_path):
    import os
    import stat

    first = _payload(
        mcp("mempalace_add_drawer", {"wing": "ro", "room": "r", "content": "Writable once."})
    )
    assert first["success"] is True, first
    dirs = [root for root, _subdirs, _files in os.walk(palace_path)]
    if os.geteuid() == 0:
        pytest.skip("root ignores permission bits")
    for path in dirs:
        os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = _payload(
            mcp("mempalace_add_drawer", {"wing": "ro", "room": "r", "content": "Refused write."})
        )
    finally:
        for path in dirs:
            os.chmod(path, stat.S_IRWXU)

    assert result["success"] is False
    assert result["error"] == f"palace is not writable: {palace_path}"
    assert "chmod -R u+w" in result["hint"]
