"""Exercise legacy benchmark owners with inert storage and mocked HTTPS calls."""

import importlib.util
import io
import json
import ssl
import sys
import types
from pathlib import Path

import pytest


def _load_legacy(name, monkeypatch):
    monkeypatch.setitem(sys.modules, "chromadb", types.ModuleType("chromadb"))
    # Restore this shared factory even when the old benchmark overwrites it.
    monkeypatch.setattr(ssl, "_create_default_https_context", ssl.create_default_context)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    path = Path(__file__).parents[1] / "benchmarks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_default_tls():
    context = ssl._create_default_https_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_convomem_import_preserves_default_tls(monkeypatch):
    _load_legacy("convomem_bench", monkeypatch)
    assert ssl._create_default_https_context is ssl.create_default_context
    _assert_default_tls()


def test_convomem_download_and_discovery_use_verified_https(monkeypatch, tmp_path):
    bench = _load_legacy("convomem_bench", monkeypatch)
    calls = []

    def download(url, filename):
        _assert_default_tls()
        calls.append(url)
        Path(filename).write_text('{"evidence_items": []}', encoding="utf-8")

    def discover(request, timeout):
        _assert_default_tls()
        assert timeout == 15
        calls.append(request.full_url)
        return io.BytesIO(b'[{"path": "user_evidence/1_evidence/item.json"}]')

    monkeypatch.setattr(bench.urllib.request, "urlretrieve", download)
    monkeypatch.setattr(bench.urllib.request, "urlopen", discover)
    assert bench.download_evidence_file("user_evidence", "item.json", tmp_path) == {
        "evidence_items": []
    }
    assert bench.discover_files("user_evidence", tmp_path) == ["1_evidence/item.json"]
    assert len(calls) == 2
    assert all(url.startswith("https://") for url in calls)


def test_convomem_certificate_failure_is_not_accepted(monkeypatch, tmp_path):
    bench = _load_legacy("convomem_bench", monkeypatch)

    def rejected(*args, **kwargs):
        raise ssl.SSLCertVerificationError("untrusted test certificate")

    monkeypatch.setattr(bench.urllib.request, "urlretrieve", rejected)
    monkeypatch.setattr(bench.urllib.request, "urlopen", rejected)
    assert bench.download_evidence_file("user_evidence", "item.json", tmp_path) is None
    assert bench.discover_files("user_evidence", tmp_path) == []


@pytest.mark.parametrize("granularity", ["dialog", "session"])
@pytest.mark.parametrize("mode", ["palace", "raw"])
def test_locomo_rooms_follow_actual_parent_sessions(monkeypatch, tmp_path, granularity, mode):
    bench = _load_legacy("locomo_bench", monkeypatch)
    rooms = ["career", "hobby", "travel", "health"]
    conversation = {}
    summaries = {}
    expected_rooms = {}
    for session_num, room in enumerate(rooms, 1):
        # Dialog IDs need not encode the actual parent session number.
        ids = [f"D99:{i}" for i in range(1, 4)] if session_num == 1 else [f"D{session_num}:1"]
        conversation[f"session_{session_num}"] = [
            {"dia_id": cid, "speaker": "Alex", "text": f"{room} research"} for cid in ids
        ]
        summaries[f"session_{session_num}_summary"] = (
            f"{room} research" if session_num == 1 else room
        )
        expected_rooms.update(dict.fromkeys(ids, room))
        expected_rooms[f"session_{session_num}"] = room
    data = tmp_path / "locomo.json"
    data.write_text(
        json.dumps(
            [
                {
                    "conversation": conversation,
                    "session_summary": summaries,
                    "qa": [
                        {
                            "question": "career research",
                            "category": 1,
                            "evidence": ["D99:1"] if granularity == "dialog" else ["D1:1"],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "results.json"

    class Collection:
        def add(self, **kwargs):
            self.added = kwargs

        def query(self, **kwargs):
            self.queried = kwargs
            selected = [
                i
                for i, meta in enumerate(self.added["metadatas"])
                if not kwargs.get("where") or meta["room"] in kwargs["where"]["room"]["$in"]
            ][: kwargs["n_results"]]
            return {
                "metadatas": [[self.added["metadatas"][i] for i in selected]],
                "documents": [[self.added["documents"][i] for i in selected]],
                "distances": [[0.1 for _ in selected]],
            }

    collection = Collection()
    monkeypatch.setattr(
        bench.chromadb,
        "PersistentClient",
        lambda **kwargs: types.SimpleNamespace(create_collection=lambda *_: collection),
        raising=False,
    )
    monkeypatch.setattr(bench, "_load_api_key", lambda *_: "inert-placeholder")
    monkeypatch.setattr(
        bench,
        "palace_assign_rooms",
        lambda *_args, **_kwargs: {f"session_{i}": room for i, room in enumerate(rooms, 1)},
    )
    bench.run_benchmark(
        str(data),
        top_k=1,
        mode=mode,
        granularity=granularity,
        out_file=str(output),
        palace_cache_file=str(tmp_path / "cache.json"),
    )
    for meta in collection.added["metadatas"]:
        assert meta["room"] == (
            expected_rooms[meta["corpus_id"]] if mode == "palace" else "general"
        )
    if mode == "palace":
        assert "where" in collection.queried
        assert collection.queried["n_results"] == (5 if granularity == "dialog" else 3)
    assert json.loads(output.read_text(encoding="utf-8"))[0]["recall"] == 1.0
