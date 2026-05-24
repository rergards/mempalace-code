"""
Regression tests for palace_graph typed payload shapes.
"""

import os

from mempalace_code.palace_graph import build_graph, find_tunnels, graph_stats, traverse
from mempalace_code.storage import LanceStore, open_store


class _FakeGraphStore:
    """Fake store with a fixed metadata list. Simulates col.count() and col.get()."""

    def __init__(self, metadatas):
        self._metadatas = metadatas

    def count(self):
        return len(self._metadatas)

    def get(self, limit=1000, offset=0, include=None):
        chunk = self._metadatas[offset : offset + limit]
        return {
            "metadatas": chunk,
            "ids": [str(i) for i in range(offset, offset + len(chunk))],
        }


class TestBuildGraphNoneMetadata:
    """AC-4 / AC-5: build_graph() tolerates rows with None metadata."""

    def test_build_graph_skips_none_metadata_rows(self):
        """AC-4: None row is ignored; valid alpha and beta rows produce the expected tunnel edge."""
        store = _FakeGraphStore(
            metadatas=[
                None,
                {"wing": "alpha", "room": "architecture", "hall": "bridge", "date": "2026-01-01"},
                {"wing": "beta", "room": "architecture", "hall": "bridge", "date": "2026-01-02"},
            ]
        )

        nodes, edges = build_graph(col=store)

        assert "architecture" in nodes
        assert nodes["architecture"]["count"] == 2
        assert set(nodes["architecture"]["wings"]) == {"alpha", "beta"}
        assert len(edges) == 1
        edge = edges[0]
        assert edge["room"] == "architecture"
        assert {edge["wing_a"], edge["wing_b"]} == {"alpha", "beta"}
        assert edge["hall"] == "bridge"

    def test_build_graph_all_none_metadata_returns_empty_graph(self):
        """AC-5: A store with only None metadata rows returns empty nodes and edges."""
        store = _FakeGraphStore(metadatas=[None, None, None])

        nodes, edges = build_graph(col=store)

        assert nodes == {}
        assert edges == []

    def test_build_graph_mixed_none_and_valid_preserves_valid_counts(self):
        """Multiple None rows interspersed among valid rows do not corrupt counts."""
        store = _FakeGraphStore(
            metadatas=[
                None,
                {"wing": "project", "room": "backend", "hall": "", "date": ""},
                None,
                {"wing": "project", "room": "backend", "hall": "", "date": ""},
                None,
            ]
        )

        nodes, edges = build_graph(col=store)

        assert "backend" in nodes
        assert nodes["backend"]["count"] == 2
        assert nodes["backend"]["wings"] == ["project"]
        assert edges == []

    def test_build_graph_no_store_returns_empty(self):
        """build_graph() returns empty graph when col is None and no config is resolvable."""
        nodes, edges = build_graph(col=None, config=None)

        assert nodes == {}
        assert edges == []


class TestBuildGraphOutputShape:
    """AC-1: build_graph() returns JSON-friendly sorted list payloads."""

    def test_node_payload_has_sorted_lists(self):
        """Node values use sorted lists, not sets, for wings/halls/dates."""
        store = _FakeGraphStore(
            metadatas=[
                {"wing": "zeta", "room": "api", "hall": "http", "date": "2026-03-01"},
                {"wing": "alpha", "room": "api", "hall": "grpc", "date": "2026-01-01"},
            ]
        )

        nodes, _ = build_graph(col=store)

        assert "api" in nodes
        node = nodes["api"]
        assert node["wings"] == ["alpha", "zeta"]
        assert node["halls"] == ["grpc", "http"]
        assert node["count"] == 2
        assert isinstance(node["dates"], list)

    def test_edge_payload_keys_present(self):
        """Edges include room, wing_a, wing_b, hall, count keys."""
        store = _FakeGraphStore(
            metadatas=[
                {"wing": "alpha", "room": "design", "hall": "shared", "date": ""},
                {"wing": "beta", "room": "design", "hall": "shared", "date": ""},
            ]
        )

        _, edges = build_graph(col=store)

        assert len(edges) == 1
        edge = edges[0]
        assert edge["room"] == "design"
        assert {edge["wing_a"], edge["wing_b"]} == {"alpha", "beta"}
        assert edge["hall"] == "shared"
        assert edge["count"] == 2

    def test_no_edge_when_room_has_no_hall(self):
        """A tunnel room with empty hall produces no edges."""
        store = _FakeGraphStore(
            metadatas=[
                {"wing": "alpha", "room": "schema", "hall": "", "date": ""},
                {"wing": "beta", "room": "schema", "hall": "", "date": ""},
            ]
        )

        nodes, edges = build_graph(col=store)

        assert "schema" in nodes
        assert set(nodes["schema"]["wings"]) == {"alpha", "beta"}
        assert edges == []

    def test_dates_limited_to_five_most_recent(self):
        """dates field keeps only the 5 most recent sorted date strings, not just any 5."""
        metadatas = [
            {"wing": "w", "room": "room1", "hall": "", "date": f"2026-0{i}-01"} for i in range(1, 8)
        ]
        store = _FakeGraphStore(metadatas=metadatas)

        nodes, _ = build_graph(col=store)

        assert nodes["room1"]["dates"] == [
            "2026-03-01",
            "2026-04-01",
            "2026-05-01",
            "2026-06-01",
            "2026-07-01",
        ]


class TestTraverseOutputShape:
    """AC-2: traverse() returns hop paths with correct observable shape."""

    def _make_store(self):
        return _FakeGraphStore(
            metadatas=[
                {"wing": "alpha", "room": "backend", "hall": "rest", "date": ""},
                {"wing": "alpha", "room": "architecture", "hall": "rest", "date": ""},
                {"wing": "beta", "room": "architecture", "hall": "rest", "date": ""},
                {"wing": "beta", "room": "frontend", "hall": "rest", "date": ""},
            ]
        )

    def test_traverse_start_room_is_hop_zero(self):
        """Starting room is included at hop 0 with its wings and halls."""
        result = traverse("backend", col=self._make_store())

        assert isinstance(result, list)
        start = result[0]
        assert start["room"] == "backend"
        assert start["hop"] == 0
        assert "wings" in start
        assert "halls" in start
        assert "count" in start

    def test_traverse_finds_connected_rooms(self):
        """Rooms sharing a wing with backend are found within max_hops."""
        result = traverse("backend", col=self._make_store(), max_hops=2)

        assert isinstance(result, list)
        rooms = {r["room"] for r in result}
        assert "architecture" in rooms

    def test_traverse_unknown_room_returns_error_dict(self):
        """traverse() returns an error dict for a room not in the graph."""
        result = traverse("nonexistent", col=self._make_store())

        assert isinstance(result, dict)
        assert "error" in result
        assert "nonexistent" in result["error"]
        assert "suggestions" in result

    def test_traverse_empty_store_returns_error(self):
        """traverse() on an empty store returns an error dict."""
        result = traverse("any", col=_FakeGraphStore([]))

        assert isinstance(result, dict)
        assert "error" in result

    def test_traverse_respects_max_hops(self):
        """Rooms reachable only beyond max_hops are excluded from results."""
        result = traverse("backend", col=self._make_store(), max_hops=1)

        assert isinstance(result, list)
        rooms = {r["room"] for r in result}
        # architecture is hop 1 (shares alpha with backend) — included
        assert "architecture" in rooms
        # frontend is hop 2 (shares beta with architecture) — excluded at max_hops=1
        assert "frontend" not in rooms


class TestFindTunnelsOutputShape:
    """AC-2: find_tunnels() returns tunnel rooms with correct keys."""

    def _make_store(self):
        return _FakeGraphStore(
            metadatas=[
                {"wing": "alpha", "room": "database", "hall": "sql", "date": "2026-01-10"},
                {"wing": "beta", "room": "database", "hall": "sql", "date": "2026-02-01"},
                {"wing": "alpha", "room": "logging", "hall": "", "date": ""},
            ]
        )

    def test_find_tunnels_returns_multi_wing_rooms(self):
        """find_tunnels() returns rooms appearing in 2+ wings."""
        result = find_tunnels(col=self._make_store())

        assert isinstance(result, list)
        rooms = {t["room"] for t in result}
        assert "database" in rooms
        assert "logging" not in rooms

    def test_find_tunnels_payload_keys(self):
        """Each tunnel entry has room, wings, halls, count, recent keys."""
        result = find_tunnels(col=self._make_store())

        entry = result[0]
        assert "room" in entry
        assert "wings" in entry
        assert "halls" in entry
        assert "count" in entry
        assert "recent" in entry

    def test_find_tunnels_filtered_by_wing(self):
        """wing_a filter returns only rooms that include that wing."""
        result = find_tunnels(wing_a="alpha", col=self._make_store())

        for entry in result:
            assert "alpha" in entry["wings"]

    def test_find_tunnels_no_results_for_unknown_wing(self):
        """find_tunnels() returns empty list when wing filter matches nothing."""
        result = find_tunnels(wing_a="nonexistent", col=self._make_store())

        assert result == []

    def test_find_tunnels_empty_store_returns_empty(self):
        """find_tunnels() on an empty store returns an empty list."""
        result = find_tunnels(col=_FakeGraphStore([]))

        assert result == []


class TestGraphStatsOutputShape:
    """AC-2: graph_stats() returns correct summary counts."""

    def _make_store(self):
        return _FakeGraphStore(
            metadatas=[
                {"wing": "alpha", "room": "database", "hall": "sql", "date": ""},
                {"wing": "beta", "room": "database", "hall": "sql", "date": ""},
                {"wing": "alpha", "room": "backend", "hall": "", "date": ""},
                {"wing": "beta", "room": "frontend", "hall": "", "date": ""},
            ]
        )

    def test_graph_stats_keys_present(self):
        """graph_stats() result has all expected top-level keys."""
        result = graph_stats(col=self._make_store())

        assert "total_rooms" in result
        assert "tunnel_rooms" in result
        assert "total_edges" in result
        assert "rooms_per_wing" in result
        assert "top_tunnels" in result

    def test_graph_stats_counts_are_correct(self):
        """total_rooms and tunnel_rooms reflect the store contents."""
        result = graph_stats(col=self._make_store())

        assert result["total_rooms"] == 3
        assert result["tunnel_rooms"] == 1

    def test_graph_stats_rooms_per_wing(self):
        """rooms_per_wing maps each wing to its room count."""
        result = graph_stats(col=self._make_store())

        assert result["rooms_per_wing"]["alpha"] == 2
        assert result["rooms_per_wing"]["beta"] == 2

    def test_graph_stats_top_tunnels_shape(self):
        """top_tunnels entries have room, wings, count keys."""
        result = graph_stats(col=self._make_store())

        assert len(result["top_tunnels"]) == 1
        entry = result["top_tunnels"][0]
        assert entry["room"] == "database"
        assert set(entry["wings"]) == {"alpha", "beta"}
        assert entry["count"] == 2

    def test_graph_stats_empty_store(self):
        """graph_stats() on an empty store returns all-zero counts."""
        result = graph_stats(col=_FakeGraphStore([]))

        assert result["total_rooms"] == 0
        assert result["tunnel_rooms"] == 0
        assert result["total_edges"] == 0
        assert result["rooms_per_wing"] == {}
        assert result["top_tunnels"] == []


# ---------------------------------------------------------------------------
# VER-2 / AC-2: direct graph helpers open real LanceDB palace read-only
# ---------------------------------------------------------------------------


class _TestConfig:
    """Minimal config shim for _get_store tests — only palace_path is needed."""

    def __init__(self, palace_path: str):
        self.palace_path = palace_path


def _guard_embedder(monkeypatch) -> None:
    """Patch LanceStore._get_embedder to raise — proves no embedder is initialized."""

    def _raise(_self):  # noqa: N805
        raise RuntimeError("embedder must not be called during read-only graph operation")

    monkeypatch.setattr(LanceStore, "_get_embedder", _raise)


def _seed_graph_palace(palace_path: str) -> None:
    """Seed a palace with graph-friendly metadata: one tunnel room (alpha+beta), one single-wing."""
    store = open_store(palace_path, create=True)
    store.add(
        ids=["g_alpha_arch_001", "g_beta_arch_002", "g_alpha_backend_003"],
        documents=[
            "Architecture overview for alpha project.",
            "Architecture notes for beta project.",
            "Backend implementation details.",
        ],
        metadatas=[
            {
                "wing": "alpha",
                "room": "architecture",
                "hall": "design",
                "date": "2026-01-01",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
            },
            {
                "wing": "beta",
                "room": "architecture",
                "hall": "design",
                "date": "2026-01-02",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-02T00:00:00",
            },
            {
                "wing": "alpha",
                "room": "backend",
                "hall": "",
                "date": "",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-03T00:00:00",
            },
        ],
    )


class TestGraphReadOnlyNoEmbedder:
    """VER-2/AC-2: direct graph helpers (_get_store path) read real LanceDB without embedder."""

    def test_build_graph_read_only_no_embedder(self, monkeypatch, palace_path):
        """build_graph via _get_store reads a populated palace without embedder startup."""
        _seed_graph_palace(palace_path)
        _guard_embedder(monkeypatch)

        nodes, edges = build_graph(config=_TestConfig(palace_path))

        assert "architecture" in nodes
        assert set(nodes["architecture"]["wings"]) == {"alpha", "beta"}
        assert nodes["architecture"]["count"] == 2
        assert len(edges) == 1

    def test_graph_stats_read_only_no_embedder(self, monkeypatch, palace_path):
        """graph_stats via _get_store returns expected counts without embedder startup."""
        _seed_graph_palace(palace_path)
        _guard_embedder(monkeypatch)

        result = graph_stats(config=_TestConfig(palace_path))

        assert result["total_rooms"] == 2
        assert result["tunnel_rooms"] == 1
        assert result["rooms_per_wing"]["alpha"] == 2
        assert result["rooms_per_wing"]["beta"] == 1

    def test_find_tunnels_read_only_no_embedder(self, monkeypatch, palace_path):
        """find_tunnels via _get_store returns the tunnel room without embedder startup."""
        _seed_graph_palace(palace_path)
        _guard_embedder(monkeypatch)

        result = find_tunnels(config=_TestConfig(palace_path))

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["room"] == "architecture"
        assert set(result[0]["wings"]) == {"alpha", "beta"}

    def test_traverse_read_only_no_embedder(self, monkeypatch, palace_path):
        """traverse via _get_store walks the graph without embedder startup."""
        _seed_graph_palace(palace_path)
        _guard_embedder(monkeypatch)

        result = traverse("architecture", config=_TestConfig(palace_path))

        assert isinstance(result, list)
        rooms = {r["room"] for r in result}
        assert "architecture" in rooms


# ---------------------------------------------------------------------------
# VER-4 / AC-3: missing palace — empty graph, no directory created
# ---------------------------------------------------------------------------


class TestGraphMissingPalaceNoEmbedder:
    """VER-4/AC-3: graph helpers on a missing palace return empty results, no dir created."""

    def test_build_graph_missing_palace_no_embedder(self, monkeypatch, tmp_dir):
        """build_graph on a missing palace returns empty graph without creating directories."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        nodes, edges = build_graph(config=_TestConfig(missing))

        assert nodes == {}
        assert edges == []
        assert not os.path.exists(missing)

    def test_graph_stats_missing_palace_no_embedder(self, monkeypatch, tmp_dir):
        """graph_stats on a missing palace returns all-zero counts, no dir created."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        result = graph_stats(config=_TestConfig(missing))

        assert result["total_rooms"] == 0
        assert result["tunnel_rooms"] == 0
        assert not os.path.exists(missing)

    def test_find_tunnels_missing_palace_no_embedder(self, monkeypatch, tmp_dir):
        """find_tunnels on a missing palace returns empty list, no dir created."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        result = find_tunnels(config=_TestConfig(missing))

        assert result == []
        assert not os.path.exists(missing)

    def test_traverse_missing_palace_no_embedder(self, monkeypatch, tmp_dir):
        """traverse on a missing palace returns an error dict without embedder startup or dir creation."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        result = traverse("some_room", config=_TestConfig(missing))

        assert isinstance(result, dict), (
            f"Expected error dict for missing palace traverse; got: {result!r}"
        )
        assert "error" in result
        assert not os.path.exists(missing)


# ---------------------------------------------------------------------------
# VER-4 / AC-4: empty (initialized) palace — empty graph, no embedder
# ---------------------------------------------------------------------------


class TestGraphEmptyPalaceNoEmbedder:
    """VER-4/AC-4: graph helpers on an initialized empty palace return empty results."""

    def test_build_graph_empty_palace_no_embedder(self, monkeypatch, palace_path):
        """build_graph on an empty palace returns empty nodes/edges without embedder startup."""
        open_store(palace_path, create=True)  # initialize empty LanceDB table
        _guard_embedder(monkeypatch)

        nodes, edges = build_graph(config=_TestConfig(palace_path))

        assert nodes == {}
        assert edges == []

    def test_graph_stats_empty_palace_no_embedder(self, monkeypatch, palace_path):
        """graph_stats on an empty palace returns all-zero counts without embedder startup."""
        open_store(palace_path, create=True)
        _guard_embedder(monkeypatch)

        result = graph_stats(config=_TestConfig(palace_path))

        assert result["total_rooms"] == 0
        assert result["tunnel_rooms"] == 0
        assert result["total_edges"] == 0
