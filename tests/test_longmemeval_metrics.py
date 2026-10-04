"""Check the legacy benchmark's metrics without importing its storage dependencies."""

import ast
import math
from pathlib import Path
from typing import Any

import pytest


def _load_metrics():
    path = Path(__file__).parents[1] / "benchmarks" / "longmemeval_bench.py"
    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name in {"dcg", "ndcg"}
    ]
    assert {node.name for node in functions} == {"dcg", "ndcg"}
    namespace: dict[str, Any] = {"math": math}
    statements: list[ast.stmt] = list(functions)
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["ndcg"]


@pytest.mark.parametrize(
    ("rankings", "correct_ids", "corpus_ids", "k", "expected"),
    [
        ([0, 2], ["a", "b"], ["a", "b", "c"], 2, 1 / (1 + 1 / math.log2(3))),
        ([0, 1], ["a", "b"], ["a", "b", "c"], 2, 1.0),
        ([2, 0], ["a"], ["a", "b", "c"], 2, 1 / math.log2(3)),
        ([2], ["a", "b"], ["a", "b", "c"], 2, 0.0),
        ([], ["a", "b"], ["a", "b", "c"], 2, 0.0),
        ([0, 1], [], ["a", "b", "c"], 2, 0.0),
        ([0, 1], ["a", "b"], ["a", "b", "c"], 1, 1.0),
    ],
)
def test_ndcg_uses_all_relevant_documents(rankings, correct_ids, corpus_ids, k, expected):
    assert _load_metrics()(rankings, correct_ids, corpus_ids, k) == pytest.approx(expected)


@pytest.mark.parametrize("granularity", ["session", "turn"])
@pytest.mark.parametrize("returned", [["doc_0"], ["doc_2", "doc_0"], []])
@pytest.mark.parametrize(
    "question", ["Which ordinary fact was recorded?", "Remind me what you suggested"]
)
@pytest.mark.parametrize(
    "retriever",
    [
        "build_palace_and_retrieve",
        "build_palace_and_retrieve_aaak",
        "build_palace_and_retrieve_rooms",
        "build_palace_and_retrieve_hybrid",
        "build_palace_and_retrieve_full",
        "build_palace_and_retrieve_hybrid_v2",
        "build_palace_and_retrieve_hybrid_v3",
        "build_palace_and_retrieve_hybrid_v4",
        "build_palace_and_retrieve_palace",
        "build_palace_and_retrieve_diary",
    ],
)
def test_retrievers_score_only_returned_documents(
    monkeypatch, granularity, returned, retriever, question
):
    import importlib.util
    import sys
    import types

    chroma = types.ModuleType("chromadb")
    monkeypatch.setattr(chroma, "EphemeralClient", lambda: None, raising=False)
    monkeypatch.setitem(sys.modules, "chromadb", chroma)
    dialect = types.ModuleType("mempalace_code.dialect")
    monkeypatch.setattr(
        dialect,
        "Dialect",
        lambda: types.SimpleNamespace(compress=lambda text, **kwargs: text),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "mempalace_code.dialect", dialect)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    path = Path(__file__).parents[1] / "benchmarks" / "longmemeval_bench.py"
    spec = importlib.util.spec_from_file_location("legacy_lme", path)
    assert spec is not None
    assert spec.loader is not None
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)

    class Collection:
        def add(self, **kwargs):
            self.added = kwargs

        def query(self, **kwargs):
            wanted = ["abc"[int(rid.removeprefix("doc_"))] for rid in returned]
            selected = [
                next(
                    i
                    for i, meta in enumerate(self.added["metadatas"])
                    if bench.session_id_from_corpus_id(meta["corpus_id"]) == cid
                )
                for cid in wanted
            ]
            return {
                "ids": [[self.added["ids"][i] for i in selected]],
                "distances": [[0.1 for _ in selected]],
                "metadatas": [[self.added["metadatas"][i] for i in selected]],
                "documents": [[self.added["documents"][i] for i in selected]],
            }

    monkeypatch.setattr(bench, "_fresh_collection", lambda *args: Collection())
    entry = {
        "question": question,
        "haystack_sessions": [
            [{"role": "user", "content": f"ordinary fact {i}"}] for i in range(3)
        ],
        "haystack_session_ids": ["a", "b", "c"],
        "haystack_dates": ["2024-01-01"] * 3,
        "question_date": "2024-01-02",
    }
    rankings, _, corpus_ids, _ = getattr(bench, retriever)(
        entry, granularity=granularity, n_results=max(1, len(returned))
    )
    assert set(rankings) == {int(rid.removeprefix("doc_")) for rid in returned}
    assert len(rankings) == len(returned)
    # Later hybrid owners currently build session corpora even with granularity=turn.
    session_only = retriever in {
        "build_palace_and_retrieve_hybrid_v2",
        "build_palace_and_retrieve_hybrid_v3",
        "build_palace_and_retrieve_hybrid_v4",
        "build_palace_and_retrieve_palace",
        "build_palace_and_retrieve_diary",
    }
    relevant = "c" if granularity == "session" or session_only else "c_turn_0"
    assert corpus_ids[2] == relevant
    scores = bench.evaluate_retrieval(rankings, [relevant], corpus_ids, 50)
    if "doc_2" in returned:
        assert scores[:2] == (1.0, 1.0)
        assert scores[2] > 0.0
    else:
        assert scores == (0.0, 0.0, 0.0)
