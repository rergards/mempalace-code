#!/usr/bin/env python3
"""
Code retrieval benchmark for mempalace chunking strategies.

Mines a local repo, runs known-answer developer questions, and compares
file-level retrieval quality for naive, smart, and tree-sitter chunking.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import mempalace_code.miner as miner  # noqa: E402
from mempalace_code.storage import DEFAULT_EMBED_MODEL, open_store  # noqa: E402
from mempalace_code.version import __version__  # noqa: E402

SUPPORTED_MODES = ("naive", "smart", "treesitter")
DEFAULT_DATASET = Path(__file__).resolve().parent / "data" / "code_retrieval_queries.json"
NAIVE_WINDOW_LINES = 80
NAIVE_OVERLAP_LINES = 10


class BenchError(Exception):
    """Expected user-facing benchmark failure."""


def load_dataset(path: Path, limit: int | None = None) -> list[dict]:
    """Load and validate query records."""
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise BenchError("dataset must be a JSON list")
    if limit is not None:
        if limit <= 0:
            raise BenchError("--limit must be positive")
        records = records[:limit]
    if not records:
        raise BenchError("dataset must contain at least one record")

    required = {"id", "query", "expected_files", "category"}
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            raise BenchError(f"dataset record {idx} must be an object")
        missing = sorted(required - set(record))
        if missing:
            raise BenchError(f"dataset record {idx} is missing: {', '.join(missing)}")
        if not isinstance(record["id"], str) or not record["id"]:
            raise BenchError(f"dataset record {idx} id must be a non-empty string")
        if not isinstance(record["query"], str) or not record["query"]:
            raise BenchError(f"dataset record {record['id']} query must be a non-empty string")
        if not isinstance(record["category"], str) or not record["category"]:
            raise BenchError(f"dataset record {record['id']} category must be a non-empty string")
        expected_files = record["expected_files"]
        if (
            not isinstance(expected_files, list)
            or not expected_files
            or any(not isinstance(expected, str) or not expected for expected in expected_files)
        ):
            raise BenchError(
                f"dataset record {record['id']} expected_files must be a non-empty list of strings"
            )
    return records


def normalize_modes(raw: str) -> list[str]:
    """Parse a comma-separated mode list and reject unsupported modes before mining."""
    modes = [part.strip() for part in raw.split(",") if part.strip()]
    invalid = [mode for mode in modes if mode not in SUPPORTED_MODES]
    if not modes or invalid:
        supported = ", ".join(SUPPORTED_MODES)
        bad = ", ".join(invalid or ["<empty>"])
        raise BenchError(f"unsupported mode(s): {bad}; supported modes: {supported}")
    return modes


def _source_identity(source_file: str) -> tuple[str, str]:
    source = source_file.replace("\\", "/")
    return source, Path(source).name


def file_matches_expected(source_file: str, expected_file: str) -> bool:
    """Match expected file by basename equality or repo-relative suffix equality."""
    source, basename = _source_identity(source_file)
    expected = expected_file.replace("\\", "/")
    return basename == expected or source.endswith(expected)


def hit_at_k(metadatas: list[dict], expected_files: list[str], k: int) -> bool:
    """Return True when any expected file appears within top-k result metadata."""
    return rank_of_first_hit(metadatas[:k], expected_files) is not None


def rank_of_first_hit(metadatas: list[dict], expected_files: list[str]) -> int | None:
    """Return 1-based rank of the first matching source file, if any."""
    for rank, meta in enumerate(metadatas, start=1):
        source_file = meta.get("source_file", "")
        if any(file_matches_expected(source_file, expected) for expected in expected_files):
            return rank
    return None


def scan_corpus_files(repo_dir: Path) -> list[Path]:
    """Scan readable source files using the same project scanner as mining."""
    return sorted(miner.scan_project(str(repo_dir)), key=lambda p: str(p))


def validate_dataset(repo_dir: Path, records: list[dict]) -> int:
    """Validate that every expected file resolves in the scanned corpus."""
    scanned = [str(path.relative_to(repo_dir)) for path in scan_corpus_files(repo_dir)]
    failures = []
    for record in records:
        for expected in record["expected_files"]:
            if not any(file_matches_expected(source, expected) for source in scanned):
                failures.append((record["id"], expected))
                print(f"FAIL {record['id']}: missing {expected}")
            else:
                print(f"PASS {record['id']}: {expected}")
    if failures:
        return 1
    print(f"PASS dataset: {len(records)} queries")
    return 0


@contextlib.contextmanager
def smart_chunking_only(enabled: bool):
    """Temporarily suppress tree-sitter parser lookup for benchmark smart mode."""
    if not enabled:
        yield
        return
    original = miner.get_parser
    miner.get_parser = lambda _language: None
    try:
        yield
    finally:
        miner.get_parser = original


def _repo_commit(repo_dir: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _index_size_mb(palace_path: Path) -> float:
    lance_dir = palace_path / "lance"
    if not lance_dir.exists():
        return 0.0
    size = sum(path.stat().st_size for path in lance_dir.rglob("*") if path.is_file())
    return size / (1024 * 1024)


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _naive_windows(lines: list[str]) -> Iterable[tuple[int, str]]:
    step = max(1, NAIVE_WINDOW_LINES - NAIVE_OVERLAP_LINES)
    for chunk_index, start in enumerate(range(0, len(lines), step)):
        window = lines[start : start + NAIVE_WINDOW_LINES]
        text = "\n".join(window).strip()
        if text:
            yield chunk_index, text


def mine_naive(repo_dir: Path, palace_path: Path):
    """Mine readable files using benchmark-only fixed line windows."""
    store = open_store(str(palace_path), create=True, embed_model=DEFAULT_EMBED_MODEL)
    files = scan_corpus_files(repo_dir)
    ids = []
    documents = []
    metadatas = []

    for filepath in files:
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if len(content) < miner.MIN_CHUNK:
            continue
        language = miner.detect_language(filepath, content)
        rel_source = str(filepath.resolve())
        source_hash = _source_hash(content)
        for chunk_index, text in _naive_windows(content.splitlines()):
            symbol_name, symbol_type = miner.extract_symbol(text, language)
            drawer_id = hashlib.md5(
                f"naive:{rel_source}:{chunk_index}".encode(),
                usedforsecurity=False,
            ).hexdigest()
            ids.append(f"drawer_code_bench_general_{drawer_id[:16]}")
            documents.append(text)
            metadatas.append(
                {
                    "wing": "code-bench",
                    "room": "general",
                    "source_file": rel_source,
                    "chunk_index": chunk_index,
                    "added_by": "bench",
                    "filed_at": datetime.now(timezone.utc).isoformat(),
                    "language": language,
                    "symbol_name": symbol_name,
                    "symbol_type": symbol_type,
                    "source_hash": source_hash,
                    "extractor_version": __version__,
                    "chunker_strategy": "naive_fixed_window_v1",
                }
            )

    if ids:
        store.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return store, len(ids), {"tree_sitter_available": False, "mode_degraded": False}


def mine_with_miner(repo_dir: Path, palace_path: Path, mode: str):
    """Mine through production process_file, with benchmark-local mode isolation."""
    store = open_store(str(palace_path), create=True, embed_model=DEFAULT_EMBED_MODEL)
    files = scan_corpus_files(repo_dir)
    project_path = repo_dir.resolve()
    rooms = [{"name": "general", "description": "Code retrieval benchmark corpus"}]

    with smart_chunking_only(mode == "smart"):
        total = 0
        for filepath in files:
            total += miner.process_file(
                filepath=filepath,
                project_path=project_path,
                collection=store,
                wing="code-bench",
                rooms=rooms,
                agent="bench",
                dry_run=False,
            )

    strategies = _chunker_strategies(store)
    tree_sitter_available = "treesitter_v1" in strategies
    return (
        store,
        total,
        {
            "tree_sitter_available": tree_sitter_available if mode == "treesitter" else False,
            "mode_degraded": mode == "treesitter" and not tree_sitter_available,
            "chunker_strategies": sorted(strategies),
        },
    )


def _chunker_strategies(store) -> set[str]:
    rows = store.get(include=["metadatas"], limit=100000)
    return {
        meta.get("chunker_strategy", "")
        for meta in rows.get("metadatas", [])
        if meta.get("chunker_strategy")
    }


def mine_mode(repo_dir: Path, palace_path: Path, mode: str):
    if mode == "naive":
        return mine_naive(repo_dir, palace_path)
    return mine_with_miner(repo_dir, palace_path, mode)


def run_queries(store, records: list[dict]) -> tuple[list[dict], list[float]]:
    per_query = []
    latencies = []
    for record in records:
        t0 = time.time()
        results = store.query(
            query_texts=[record["query"]],
            n_results=10,
            include=["documents", "metadatas", "distances"],
        )
        latencies.append((time.time() - t0) * 1000)
        metas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
        rank = rank_of_first_hit(metas, record["expected_files"])
        per_query.append(
            {
                "id": record["id"],
                "query": record["query"],
                "category": record["category"],
                "expected_files": record["expected_files"],
                "expected_symbols": record.get("expected_symbols", []),
                "rank": rank,
                "hit_at_5": rank is not None and rank <= 5,
                "hit_at_10": rank is not None and rank <= 10,
                "top5_files": [meta.get("source_file", "") for meta in metas[:5]],
                "top5_symbols": [meta.get("symbol_name", "") for meta in metas[:5]],
            }
        )
    return per_query, latencies


def aggregate_results(per_query: list[dict], latencies: list[float]) -> dict:
    query_count = len(per_query)
    r5 = sum(1 for row in per_query if row["hit_at_5"]) / query_count
    r10 = sum(1 for row in per_query if row["hit_at_10"]) / query_count
    mrr = sum(1 / row["rank"] for row in per_query if row["rank"]) / query_count

    by_category = defaultdict(list)
    for row in per_query:
        by_category[row["category"]].append(row)

    per_category = {}
    for category, rows in sorted(by_category.items()):
        count = len(rows)
        per_category[category] = {
            "query_count": count,
            "R@5": sum(1 for row in rows if row["hit_at_5"]) / count,
            "R@10": sum(1 for row in rows if row["hit_at_10"]) / count,
            "MRR": sum(1 / row["rank"] for row in rows if row["rank"]) / count,
        }

    return {
        "R@5": r5,
        "R@10": r10,
        "MRR": mrr,
        "query_latency_avg_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "per_category": per_category,
    }


def run_mode(repo_dir: Path, mode: str, records: list[dict]) -> dict:
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"code_bench_{mode}_"))
    try:
        t0 = time.time()
        store, chunk_count, mode_meta = mine_mode(repo_dir, tmp_dir, mode)
        embed_time_s = time.time() - t0
        per_query, latencies = run_queries(store, records)
        metrics = aggregate_results(per_query, latencies)
        return {
            "chunk_count": chunk_count,
            "embed_time_s": embed_time_s,
            "index_size_mb": _index_size_mb(tmp_dir),
            "query_latency_avg_ms": metrics["query_latency_avg_ms"],
            "R@5": metrics["R@5"],
            "R@10": metrics["R@10"],
            "MRR": metrics["MRR"],
            "per_category": metrics["per_category"],
            "per_query": per_query,
            **mode_meta,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def build_comparison(modes: dict) -> dict:
    """Build compact table-friendly comparison metrics."""
    return {
        mode: {
            "R@5": result["R@5"],
            "R@10": result["R@10"],
            "MRR": result["MRR"],
            "chunk_count": result["chunk_count"],
            "query_latency_avg_ms": result["query_latency_avg_ms"],
        }
        for mode, result in modes.items()
    }


def print_table(modes: dict) -> None:
    print("\nCode retrieval results")
    print("mode          chunks   R@5    R@10   MRR    query_ms")
    print("------------  -------  -----  -----  -----  --------")
    for mode, result in modes.items():
        print(
            f"{mode:<12}  {result['chunk_count']:>7}  "
            f"{result['R@5']:.3f}  {result['R@10']:.3f}  "
            f"{result['MRR']:.3f}  {result['query_latency_avg_ms']:.1f}"
        )


def run_benchmark(repo_dir: Path, dataset_path: Path, modes: list[str], limit: int | None) -> dict:
    records = load_dataset(dataset_path, limit)
    mode_results = {mode: run_mode(repo_dir, mode, records) for mode in modes}
    return {
        "meta": {
            "date": datetime.now(timezone.utc).isoformat(),
            "repo_path": str(repo_dir),
            "repo_name": repo_dir.name,
            "repo_commit": _repo_commit(repo_dir),
            "embed_model": DEFAULT_EMBED_MODEL,
            "dataset_path": str(dataset_path),
            "query_count": len(records),
        },
        "modes": mode_results,
        "comparison": build_comparison(mode_results),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", default=".", help="Local repository to mine")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Known-answer query JSON")
    parser.add_argument("--modes", default="smart", help="Comma-separated: naive,smart,treesitter")
    parser.add_argument("--limit", type=int, help="Limit query count for smoke runs")
    parser.add_argument("--out", help="Write benchmark JSON to this path")
    parser.add_argument(
        "--validate-dataset",
        action="store_true",
        help="Validate expected_files against scanned corpus without embedding",
    )
    args = parser.parse_args(argv)

    try:
        repo_dir = Path(args.repo_dir).expanduser().resolve()
        dataset_path = Path(args.dataset).expanduser().resolve()
        records = load_dataset(dataset_path, args.limit)
        if args.validate_dataset:
            return validate_dataset(repo_dir, records)
        modes = normalize_modes(args.modes)
        report = run_benchmark(repo_dir, dataset_path, modes, args.limit)
        print_table(report["modes"])
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"\nWrote {out_path}")
        return 0
    except BenchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
