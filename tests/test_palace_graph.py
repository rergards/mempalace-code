"""
Regression tests for None-metadata robustness in palace_graph.build_graph().
"""

from mempalace_code.palace_graph import build_graph


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
