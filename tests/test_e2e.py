"""
test_e2e.py — End-to-end user scenario tests covering 12 real-world workflows.

Each test is self-contained with its own temp palace, KG, and config. No shared
state between tests. Follows the plan at docs/plans/QUAL-E2E-USER-SCENARIOS.md
and docs/plans/QUAL-E2E-REMAINING-MODULES.md.
"""

import json
import os
import shutil
import time
from pathlib import Path

import lancedb
import pyarrow as pa
import pytest
import yaml

from mempalace_code import export as exp
from mempalace_code.convo_miner import mine_convos
from mempalace_code.knowledge_graph import KnowledgeGraph
from mempalace_code.miner import mine
from mempalace_code.storage import open_store

# ── helpers ───────────────────────────────────────────────────────────────────


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_palace_config(project_root: Path, wing: str = "e2e_test") -> None:
    with open(project_root / "mempalace.yaml", "w") as f:
        yaml.dump(
            {
                "wing": wing,
                "rooms": [
                    {"name": "backend", "description": "Backend code"},
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )


# Padded Python source so files exceed the miner's minimum-size threshold
_PADDING = "    # " + "x" * 50 + "\n"

_PY_MODULE = (
    "def compute_result(x):\n"
    '    """Compute a result based on input value x."""\n'
    + _PADDING
    * 12
    + "    return x * 2\n\n\n"
    "class DataProcessor:\n"
    '    """Process data items efficiently."""\n' + _PADDING * 12 + "    pass\n"
)


def _patch_mcp(monkeypatch, palace_path: str, kg, base_tmp: Path):
    """Patch mcp_server globals for an isolated MCP test."""
    from mempalace_code import mcp_server
    from mempalace_code.config import MempalaceConfig

    cfg_dir = str(base_tmp / "mcp_config")
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, "config.json"), "w") as f:
        json.dump({"palace_path": palace_path}, f)
    config = MempalaceConfig(config_dir=cfg_dir)

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)
    monkeypatch.setattr(mcp_server, "_store", None)
    return config


# ── AC-1: mine → add → export → nuke → import → search ───────────────────────


def test_mine_search_export_nuke_import(tmp_path):
    """AC-1: Full mine→manual-add→export→nuke→import→search roundtrip."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_file(project_root / "module.py", _PY_MODULE)
    _make_palace_config(project_root)

    palace_path = str(tmp_path / "palace")
    mine(str(project_root), palace_path)

    store = open_store(palace_path, create=False)
    assert store.count() > 0

    # Add a manual drawer (simulate user/MCP write)
    manual_content = (
        "Unique manual note: authentication uses JWT with RS256 signing for all sessions."
    )
    store.add(
        ids=["manual_auth_note"],
        documents=[manual_content],
        metadatas=[{"wing": "e2e_test", "room": "general", "chunker_strategy": "manual_v1"}],
    )

    # Export only manual drawers to JSONL
    backup_path = str(tmp_path / "backup.jsonl")
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    result = exp.write_jsonl(
        path=backup_path,
        store=store,
        kg=kg,
        only_manual=True,
        palace_path=palace_path,
    )
    # Exactly 1 manual drawer exported — verifies only_manual filter excludes mined drawers
    assert result["drawer_count"] == 1

    # Nuke the palace directory
    shutil.rmtree(palace_path)

    # Import backup into a fresh palace
    new_store = open_store(palace_path, create=True)
    import_result = exp.import_jsonl(path=backup_path, store=new_store, kg=kg, skip_dedup=True)
    assert import_result["imported_drawers"] == 1
    assert not import_result["warnings"]

    # Search must find the restored manual drawer
    results = new_store.query(
        query_texts=["JWT RS256 authentication signing sessions"],
        n_results=5,
        include=["documents"],
    )
    found_docs = results["documents"][0]
    assert any("JWT" in doc for doc in found_docs), "Restored manual drawer not found by search"


# ── AC-2: incremental re-mine after file edit ─────────────────────────────────


def test_incremental_remine_after_edit(tmp_path):
    """AC-2: Incremental remine updates changed file; unchanged file's drawers are untouched."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    stable_file = project_root / "stable.py"
    changed_file = project_root / "changed.py"
    _write_file(stable_file, _PY_MODULE)
    _write_file(changed_file, _PY_MODULE)
    _make_palace_config(project_root)

    palace_path = str(tmp_path / "palace")
    mine(str(project_root), palace_path)

    store = open_store(palace_path, create=False)

    # Snapshot stable file's drawers before re-mine
    pre = store.get(
        where={"source_file": str(stable_file)},
        include=["documents", "metadatas"],
        limit=100,
    )
    assert len(pre["ids"]) > 0, "Stable file produced no drawers on first mine"
    pre_docs = set(pre["documents"])
    pre_filed_ats = {m["filed_at"] for m in pre["metadatas"]}

    # Edit the changed file (guarantees a new content hash)
    new_content = (
        "def updated_algorithm(data):\n"
        '    """Updated algorithm — completely new implementation for incremental test."""\n'
        + _PADDING * 12
        + "    return sorted(data)\n"
    )
    _write_file(changed_file, new_content)

    # Incremental re-mine (default incremental=True)
    mine(str(project_root), palace_path)

    store2 = open_store(palace_path, create=False)

    # (a) Changed file's new content is indexed and searchable
    changed_result = store2.get(
        where={"source_file": str(changed_file)},
        include=["documents"],
        limit=100,
    )
    all_changed_text = " ".join(changed_result["documents"])
    assert "updated_algorithm" in all_changed_text, (
        "Changed file content not indexed after incremental remine"
    )

    # (b) The changed file now has a hash tracked in the store
    hashes = store2.get_source_file_hashes("e2e_test")
    assert str(changed_file) in hashes

    # (c) Stable file's drawers are byte-identical — content and filed_at unchanged
    post = store2.get(
        where={"source_file": str(stable_file)},
        include=["documents", "metadatas"],
        limit=100,
    )
    post_docs = set(post["documents"])
    post_filed_ats = {m["filed_at"] for m in post["metadatas"]}

    assert pre_docs == post_docs, "Stable file's drawer content changed after incremental remine"
    assert pre_filed_ats == post_filed_ats, (
        "Stable file's filed_at changed after incremental remine — skip path not taken"
    )


# ── AC-3: MCP session lifecycle ───────────────────────────────────────────────


def test_mcp_session_lifecycle(tmp_path, monkeypatch):
    """AC-3: status → search → add_drawer → search (found) → delete_drawer → search (gone)."""
    palace_path = str(tmp_path / "palace")
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    _patch_mcp(monkeypatch, palace_path, kg, tmp_path)

    from mempalace_code.mcp_server import (
        tool_add_drawer,
        tool_delete_drawer,
        tool_search,
        tool_status,
    )

    # Step 1: status on empty (not-yet-created) palace — must not error
    status = tool_status()
    assert "error" in status, f"Expected no-palace error on lazy startup, got: {status}"

    # Step 2: search on empty palace — must return results key without crashing
    search_empty = tool_search(query="authentication JWT tokens")
    assert "results" in search_empty

    # Step 3: add a drawer
    add_result = tool_add_drawer(
        wing="mcp_e2e",
        room="general",
        content="Authentication uses JWT tokens with RS256 signing. Sessions expire in 24 hours.",
    )
    assert add_result["success"] is True
    drawer_id = add_result["drawer_id"]

    # Step 4: search now finds the new drawer
    search_after = tool_search(query="JWT RS256 authentication session expire")
    assert "results" in search_after
    assert len(search_after["results"]) > 0
    assert any("JWT" in r["text"] for r in search_after["results"])

    # Step 5: delete the drawer
    del_result = tool_delete_drawer(drawer_id)
    assert del_result["success"] is True

    # Step 6: search no longer returns the deleted drawer
    search_gone = tool_search(query="JWT RS256 authentication session expire")
    found_texts = [r["text"] for r in search_gone.get("results", [])]
    assert not any("JWT" in t for t in found_texts), "Deleted drawer still returned by search"


# ── AC-4: code search file context ───────────────────────────────────────────


def test_code_search_file_context(tmp_path):
    """AC-4: Mine Python files; code_search returns hits with language/symbol_name/symbol_type."""
    # Large-enough functions to prevent adaptive merging (>TARGET_MAX/2 chars each)
    padding = "    # " + "x" * 60 + "\n"
    py_src = (
        "def authenticate_user(token):\n"
        '    """Authenticate a user from a JWT token string."""\n'
        + padding
        * 22
        + "    return True\n\n\n"
        "class AuthManager:\n"
        '    """Manages authentication sessions and tokens for users."""\n'
        + padding * 22
        + "    pass\n"
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_file(project_root / "auth.py", py_src)
    _make_palace_config(project_root)

    palace_path = str(tmp_path / "palace")
    mine(str(project_root), palace_path)

    from mempalace_code.searcher import code_search

    result = code_search(palace_path=palace_path, query="authentication user token JWT sessions")
    assert "results" in result, f"code_search returned error: {result}"
    assert len(result["results"]) > 0, "code_search returned no hits after mining Python source"

    hit = result["results"][0]
    for field in ("text", "wing", "room", "source_file", "symbol_name", "symbol_type", "language"):
        assert field in hit, f"Missing field {field!r} in code_search hit"

    assert hit["language"] == "python"

    all_names = [r["symbol_name"] for r in result["results"]]
    all_types = [r["symbol_type"] for r in result["results"]]
    assert any(n for n in all_names), "No symbol_name populated in code_search results"
    assert any(t for t in all_types), "No symbol_type populated in code_search results"


# ── AC-5: schema migration + multi-write ──────────────────────────────────────


def test_schema_migration_multi_write(tmp_path):
    """AC-5: Create 9-column palace, open_store migrates it, 10 rapid writes all persist."""
    palace_path = str(tmp_path / "palace")
    os.makedirs(palace_path)

    # Create a pre-migration 9-column LanceDB table directly
    db = lancedb.connect(os.path.join(palace_path, "lance"))
    old_schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
            pa.field("wing", pa.string()),
            pa.field("room", pa.string()),
            pa.field("source_file", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("added_by", pa.string()),
            pa.field("filed_at", pa.string()),
        ]
    )
    db.create_table("mempalace_drawers", schema=old_schema)

    # open_store triggers schema migration
    store = open_store(palace_path, create=False)

    # Write 10 drawers in rapid succession after migration
    for i in range(10):
        store.add(
            ids=[f"migrated_drawer_{i}"],
            documents=[
                f"Post-migration drawer {i}: distinct content for rapid write stress test"
                f" after schema upgrade number {i}"
            ],
            metadatas=[{"wing": "e2e_migrate", "room": "general"}],
        )

    assert store.count() == 10

    # Verify all 10 IDs are retrievable
    result = store.get(include=["metadatas"], limit=20)
    stored_ids = set(result["ids"])
    for i in range(10):
        assert f"migrated_drawer_{i}" in stored_ids, (
            f"migrated_drawer_{i} not found after migration"
        )


# ── AC-6: KG lifecycle ────────────────────────────────────────────────────────


def test_kg_lifecycle(tmp_path):
    """AC-6: add_triple → query (present) → invalidate → query as_of after valid_to → timeline."""
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))

    kg.add_entity("Alice", entity_type="person")
    kg.add_entity("Rust", entity_type="technology")

    valid_from = "2025-01-01"
    valid_to_date = "2026-01-01"

    kg.add_triple("Alice", "uses", "Rust", valid_from=valid_from)

    # Fact is present before invalidation
    before = kg.query_entity("Alice")
    uses_rust = [r for r in before if r["predicate"] == "uses" and r["object"] == "Rust"]
    assert len(uses_rust) == 1
    assert uses_rust[0]["current"] is True

    # Invalidate the fact (sets valid_to in place on the existing row — no new row)
    kg.invalidate("Alice", "uses", "Rust", ended=valid_to_date)

    # Query as_of a date AFTER valid_to — fact must be absent
    facts_after = kg.query_entity("Alice", as_of="2026-06-01")
    uses_rust_after = [r for r in facts_after if r["predicate"] == "uses" and r["object"] == "Rust"]
    assert len(uses_rust_after) == 0, "Invalidated fact still returned by as_of query"

    # Timeline: single record with valid_to populated and current=False
    tl = kg.timeline(entity_name="Alice")
    rust_entries = [r for r in tl if r["predicate"] == "uses" and r["object"] == "Rust"]
    assert len(rust_entries) == 1, (
        f"Expected 1 timeline entry for Alice→uses→Rust, got {len(rust_entries)}"
    )
    assert rust_entries[0]["valid_to"] == valid_to_date
    assert rust_entries[0]["current"] is False


# ── AC-7: diary write/read continuity ────────────────────────────────────────


def test_diary_write_read_continuity(tmp_path, monkeypatch):
    """AC-7: 5 diary entries → diary_read returns all 5 in reverse-chronological order."""
    palace_path = str(tmp_path / "palace")
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    _patch_mcp(monkeypatch, palace_path, kg, tmp_path)

    from mempalace_code.mcp_server import tool_diary_read, tool_diary_write

    topics = ["arch", "debug", "deploy", "review", "retro"]
    agent = "e2e_diary_agent"

    for i, topic in enumerate(topics):
        result = tool_diary_write(
            agent_name=agent,
            entry=f"Entry {i + 1}: {topic} diary entry for e2e continuity test session.",
            topic=topic,
        )
        assert result["success"] is True, f"diary_write failed for topic={topic!r}"

    # Read back all entries
    read_result = tool_diary_read(agent_name=agent, last_n=10)
    assert read_result["total"] == 5
    entries = read_result["entries"]
    assert len(entries) == 5

    # All 5 topics must be present
    returned_topics = [e["topic"] for e in entries]
    for topic in topics:
        assert topic in returned_topics, f"Topic {topic!r} missing from diary_read"

    # Reverse-chronological: newest (retro, written last) must be entries[0]
    assert entries[0]["topic"] == "retro", (
        f"Expected newest entry 'retro' first, got {entries[0]['topic']!r}"
    )
    # Oldest (arch, written first) must be entries[-1]
    assert entries[-1]["topic"] == "arch", (
        f"Expected oldest entry 'arch' last, got {entries[-1]['topic']!r}"
    )


# ── AC-8: offline gate ────────────────────────────────────────────────────────


@pytest.mark.needs_network
def test_offline_gate(tmp_path, monkeypatch):
    """AC-8: fetch_model → set HF_HUB_OFFLINE=1 → mine → search → export — no network needed."""
    # Use a CI-provided shared cache when available; otherwise isolate to a fresh temp dir.
    # MEMPALACE_TEST_HF_HOME is set by the model-backed CI job so the downloaded model
    # survives across test runs without being re-downloaded into a throwaway directory.
    ci_hf_home = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if ci_hf_home:
        hf_home = ci_hf_home
    else:
        hf_home = str(tmp_path / "hf")
        Path(hf_home).mkdir()
    monkeypatch.setenv("HF_HOME", hf_home)

    from mempalace_code.cli import fetch_model
    from mempalace_code.storage import DEFAULT_EMBED_MODEL

    fetch_model(DEFAULT_EMBED_MODEL)

    # Go offline
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_file(project_root / "offline.py", _PY_MODULE)
    _make_palace_config(project_root)

    palace_path = str(tmp_path / "palace")
    mine(str(project_root), palace_path)

    store = open_store(palace_path, create=False)
    assert store.count() > 0, "Mine produced no drawers in offline mode"

    # Search offline
    results = store.query(
        query_texts=["compute result function"],
        n_results=3,
        include=["documents"],
    )
    assert "documents" in results

    # Export offline
    backup_path = str(tmp_path / "backup.jsonl")
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    summary = exp.write_jsonl(path=backup_path, store=store, kg=kg, palace_path=palace_path)
    assert summary["drawer_count"] > 0
    assert os.path.exists(backup_path)


# ── AC-9: large palace search latency ────────────────────────────────────────


@pytest.mark.slow
def test_large_palace_search_latency(tmp_path):
    """AC-9: Mine 500-file project; search completes under 500ms (perf-smoke gate)."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    # 500 distinct Python files with ~25 lines each
    for i in range(500):
        content = (
            f"# Module {i:04d} — load test for large palace search latency\n"
            f"def handler_{i}(request):\n"
            f'    """Handle request type {i} in the processing pipeline."""\n'
            f"    data = request.get('payload_{i}', None)\n"
            f"    if data is None:\n"
            f"        return None\n"
            f"    return process_{i}(data)\n\n\n"
            f"def process_{i}(data):\n"
            f'    """Process data item {i} through pipeline stage {i}."""\n'
            f"    items = list(data) if hasattr(data, '__iter__') else [data]\n"
            f"    return [x * {i + 1} for x in items]\n\n\n"
            f"class Stage{i}:\n"
            f'    """Pipeline stage {i} for the large palace perf test."""\n\n'
            f"    def __init__(self):\n"
            f"        self.stage_id = {i}\n\n"
            f"    def run(self, data):\n"
            f"        return process_{i}(data)\n"
        )
        _write_file(project_root / f"module_{i:04d}.py", content)

    _make_palace_config(project_root)

    palace_path = str(tmp_path / "palace")
    mine(str(project_root), palace_path)

    store = open_store(palace_path, create=False)
    assert store.count() > 0

    # Warm up the embed model, then measure search latency
    store.warmup()
    start = time.perf_counter()
    results = store.query(
        query_texts=["handler process request payload pipeline stage"],
        n_results=5,
        include=["documents"],
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert "documents" in results
    assert elapsed_ms < 500, f"Search took {elapsed_ms:.1f}ms — expected < 500ms"


# ── AC-10/AC-11: convo_miner idempotent ingest ────────────────────────────────


def test_convo_miner_claude_json_e2e(tmp_path, monkeypatch):
    """AC-10/AC-11: mine_convos ingests Claude JSON export; idempotent on re-run."""
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

    convo_dir = tmp_path / "convos"
    convo_dir.mkdir()
    palace_path = str(tmp_path / "palace")

    # Synthetic Claude.ai JSON export — flat messages list, 3 user/assistant turns.
    export_data = [
        {"role": "user", "content": "What database should we use for the retry queue?"},
        {
            "role": "assistant",
            "content": "SQLite is the right choice for the retry queue — simple and reliable.",
        },
        {"role": "user", "content": "How many retries should we budget per job?"},
        {
            "role": "assistant",
            "content": "The sqlite retry budget decision is three attempts per job with exponential backoff.",
        },
        {"role": "user", "content": "Should we use a deadline or a counter?"},
        {
            "role": "assistant",
            "content": "Use a counter — simpler to reason about and audit in the logs.",
        },
    ]
    export_file = convo_dir / "db_convo.json"
    export_file.write_text(json.dumps(export_data), encoding="utf-8")

    mine_convos(str(convo_dir), palace_path, wing="convo_e2e", spellcheck=False)

    store = open_store(palace_path, create=False)
    count_after_first = store.count()
    assert count_after_first > 0, "mine_convos produced no drawers"

    # all stored drawers carry the expected provenance metadata
    all_result = store.get(include=["documents", "metadatas"], limit=100)
    all_docs = all_result["documents"]
    all_metas = all_result["metadatas"]

    assert any("retry" in doc.lower() for doc in all_docs), (
        "Seeded 'retry' phrase not found in any stored drawer"
    )
    assert all(m.get("ingest_mode") == "convos" for m in all_metas), (
        "Not all drawers have ingest_mode=convos"
    )
    assert all(m.get("chunker_strategy") == "convo_turn_v1" for m in all_metas), (
        "Not all drawers have chunker_strategy=convo_turn_v1"
    )

    # semantic search finds the unique decision phrase
    search_result = store.query(
        query_texts=["sqlite retry budget decision three attempts"],
        n_results=count_after_first,
        include=["documents"],
    )
    search_docs = search_result["documents"][0]
    assert any("retry" in d.lower() for d in search_docs), (
        "Search did not return the retry-related drawer"
    )

    # re-mine same directory — drawer count must not change
    mine_convos(str(convo_dir), palace_path, wing="convo_e2e", spellcheck=False)
    count_after_second = open_store(palace_path, create=False).count()
    assert count_after_second == count_after_first, (
        f"Idempotency broken: count went {count_after_first} → {count_after_second} on re-run"
    )


# ── AC-12/AC-13: layers wake_up / recall / search ─────────────────────────────


def test_layers_wake_up_recall_search_e2e(tmp_path, monkeypatch):
    """AC-12/AC-13: MemoryStack token estimates grow monotonically; missing filter no-crash."""
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

    # Mine a small project with content routed to the "backend" room via folder path
    project_root = tmp_path / "project"
    (project_root / "backend").mkdir(parents=True)
    _write_file(project_root / "backend" / "service.py", _PY_MODULE)
    wing = "layers_e2e"
    with open(project_root / "mempalace.yaml", "w") as f:
        yaml.dump(
            {
                "wing": wing,
                "rooms": [
                    {"name": "backend", "description": "Backend code"},
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )

    palace_path = str(tmp_path / "palace")
    mine(str(project_root), palace_path)

    store = open_store(palace_path, create=False)
    assert store.count() > 0, "Mine produced no drawers — layers test cannot proceed"

    # Short fixed identity (~60 chars) so L0 tokens << L0+L1 tokens
    identity_text = "I am TestAgent. Traits: focused. Project: e2e layers test."
    identity_path = str(tmp_path / "identity.txt")
    Path(identity_path).write_text(identity_text, encoding="utf-8")

    from mempalace_code.layers import MemoryStack

    stack = MemoryStack(palace_path=palace_path, identity_path=identity_path)

    # L0 identity renders the seeded file exactly
    l0_text = stack.l0.render()
    assert l0_text == identity_text, f"Layer0 did not read identity file: {l0_text!r}"
    l0_tokens = len(l0_text) // 4

    # wake_up() = L0 + L1 must be strictly larger than L0 alone
    wakeup_text = stack.wake_up(wing=wing)
    wakeup_tokens = len(wakeup_text) // 4
    assert l0_tokens < wakeup_tokens, (
        f"L0 tokens ({l0_tokens}) not < wake_up tokens ({wakeup_tokens}); L1 may be empty"
    )

    # L1 section is present and contains project content
    assert "## L1" in wakeup_text, "wake_up() missing ## L1 section"
    assert any(kw in wakeup_text.lower() for kw in ("compute", "dataprocessor", "backend")), (
        f"wake_up() L1 missing expected project content:\n{wakeup_text}"
    )

    # L2 recall adds content on top of wake_up
    recall_text = stack.recall(wing=wing, room="backend")
    recall_tokens = len(recall_text) // 4
    assert recall_tokens > 0, (
        f"recall() returned empty for wing={wing} room=backend: {recall_text!r}"
    )

    # L2 header present and contains expected project content
    assert "## L2" in recall_text, "recall() missing ## L2 header"
    assert any(kw in recall_text.lower() for kw in ("compute", "dataprocessor", "service")), (
        f"recall() missing expected backend content:\n{recall_text}"
    )

    # L3 search returns project content
    search_text = stack.search("compute result function", wing=wing)
    assert "## L3" in search_text, "search() missing ## L3 header"
    assert any(kw in search_text.lower() for kw in ("compute", "result", "dataprocessor")), (
        f"search() missing expected project content:\n{search_text}"
    )

    # recall with missing wing returns no-drawers message, does not raise
    missing_recall = stack.recall(wing="missing_wing_xyz_e2e")
    assert "no drawers found" in missing_recall.lower(), (
        f"recall with missing wing should report no drawers, got: {missing_recall!r}"
    )
    assert "compute" not in missing_recall.lower(), (
        "recall with missing wing leaked real project content"
    )


# ── AC-14/AC-15: palace_graph tunnel detection and traversal ──────────────────


def test_palace_graph_tunnels_e2e(tmp_path, monkeypatch):
    """AC-14/AC-15: Tunnel detection, traversal, graph stats, and missing-room error shape."""
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

    palace_path = str(tmp_path / "palace")

    # Project A: wing=proj_alpha — architecture room + backend room
    proj_a = tmp_path / "proj_alpha"
    (proj_a / "architecture").mkdir(parents=True)
    (proj_a / "backend").mkdir()
    _write_file(proj_a / "architecture" / "design.py", _PY_MODULE)
    _write_file(proj_a / "backend" / "service.py", _PY_MODULE)
    with open(proj_a / "mempalace.yaml", "w") as f:
        yaml.dump(
            {
                "wing": "proj_alpha",
                "rooms": [
                    {"name": "architecture", "description": "Architecture"},
                    {"name": "backend", "description": "Backend"},
                ],
            },
            f,
        )
    mine(str(proj_a), palace_path)

    # Project B: wing=proj_beta — architecture room only (shared with proj_alpha → tunnel)
    proj_b = tmp_path / "proj_beta"
    (proj_b / "architecture").mkdir(parents=True)
    _write_file(proj_b / "architecture" / "design.py", _PY_MODULE)
    with open(proj_b / "mempalace.yaml", "w") as f:
        yaml.dump(
            {
                "wing": "proj_beta",
                "rooms": [{"name": "architecture", "description": "Architecture"}],
            },
            f,
        )
    mine(str(proj_b), palace_path)

    store = open_store(palace_path, create=False)

    from mempalace_code.palace_graph import find_tunnels, graph_stats, traverse

    # find_tunnels returns "architecture" as a shared room with both wings
    tunnels = find_tunnels(col=store)
    tunnel_room_names = [t["room"] for t in tunnels]
    assert "architecture" in tunnel_room_names, (
        f"'architecture' not found in tunnel rooms: {tunnel_room_names}"
    )
    arch_tunnel = next(t for t in tunnels if t["room"] == "architecture")
    assert "proj_alpha" in arch_tunnel["wings"], (
        f"proj_alpha missing from architecture tunnel wings: {arch_tunnel['wings']}"
    )
    assert "proj_beta" in arch_tunnel["wings"], (
        f"proj_beta missing from architecture tunnel wings: {arch_tunnel['wings']}"
    )

    # traverse from "architecture" reaches "backend" through the shared wing
    traversal = traverse("architecture", col=store)
    assert isinstance(traversal, list), f"traverse should return a list, got: {traversal!r}"
    traversal_rooms = [r["room"] for r in traversal]
    assert "backend" in traversal_rooms, (
        f"'backend' not reachable from 'architecture' via traversal: {traversal_rooms}"
    )
    backend_entry = next(r for r in traversal if r["room"] == "backend")
    assert "proj_alpha" in backend_entry.get("connected_via", []), (
        f"backend not connected via proj_alpha: {backend_entry}"
    )

    # graph_stats reports at least one tunnel room
    stats = graph_stats(col=store)
    assert stats["tunnel_rooms"] >= 1, (
        f"Expected at least 1 tunnel room in graph_stats, got: {stats}"
    )

    # traverse on a non-existent room returns error dict with suggestions key
    missing = traverse("nonexistent-room-xyz", col=store)
    assert isinstance(missing, dict), (
        f"traverse of missing room should return dict, got {type(missing).__name__}: {missing!r}"
    )
    assert "error" in missing, f"Missing-room response has no 'error' key: {missing}"
    assert "suggestions" in missing, f"Missing-room response has no 'suggestions' key: {missing}"
