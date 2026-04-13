"""
Tests for benchmarks/embed_ab_bench.py — focused on the --out mkdir fix (BENCH-EMBED-AB-OUT-MKDIR).
"""

import importlib.util
import json
import sys
from pathlib import Path

_BENCH_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "embed_ab_bench.py"
_spec = importlib.util.spec_from_file_location("embed_ab_bench", _BENCH_FILE)
_embed_ab_bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_embed_ab_bench)

_STUB_CODE_RESULT = {
    "code_retrieval": {"R@5": 1.0, "R@10": 1.0, "per_category": {}},
    "performance": {"embed_time_s": 0.1, "query_latency_avg_ms": 1.0, "index_size_mb": 0.1},
}


def test_out_mkdir_creates_parent_dirs(monkeypatch, tmp_path):
    """--out with a non-existent nested path auto-creates parents and writes the report (AC-1, AC-3)."""
    out_file = tmp_path / "nested" / "deep" / "report.json"

    monkeypatch.setattr(_embed_ab_bench, "run_code_bench", lambda *_a, **_kw: _STUB_CODE_RESULT)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "embed_ab_bench",
            "--models",
            "minilm",
            "--skip-longmemeval",
            "--out",
            str(out_file),
        ],
    )

    _embed_ab_bench.main()

    assert out_file.exists(), "report file was not created"
    data = json.loads(out_file.read_text())
    assert "models" in data
    assert "minilm" in data["models"]
