#!/usr/bin/env python3
"""
BENCH-EMBED-AB — A/B embedding model benchmark for mempalace.

Compares embedding models on code retrieval quality and performance.
Uses the mempalace repo itself as the test corpus.

Usage:
    python benchmarks/embed_ab_bench.py
    python benchmarks/embed_ab_bench.py --models minilm,nomic
    python benchmarks/embed_ab_bench.py --longmemeval-data benchmarks/data/longmemeval_s_cleaned.json
    python benchmarks/embed_ab_bench.py --skip-longmemeval --out results.json
"""

import argparse
import gc
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

# Add project root to path so we can import mempalace_code
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from mempalace_code.miner import load_config, process_file, scan_project  # noqa: E402
from mempalace_code.storage import open_store  # noqa: E402


# =============================================================================
# MODEL REGISTRY
# =============================================================================

MODELS = {
    "minilm": {
        "name": "all-MiniLM-L6-v2",
        "dims": 384,
        "context_tokens": 256,
        "size_mb": 80,
    },
    "mpnet": {
        "name": "all-mpnet-base-v2",
        "dims": 768,
        "context_tokens": 384,
        "size_mb": 420,
    },
    "nomic": {
        "name": "nomic-ai/nomic-embed-text-v1.5",
        "dims": 768,
        "context_tokens": 8192,
        "size_mb": 550,
    },
}


# =============================================================================
# KNOWN-ANSWER QUERY SET
#
# Each query has:
#   - query: the search string
#   - expected_files: source_file substrings that should appear in top-k
#   - category: for per-category reporting
# =============================================================================

QUERIES = [
    # ── Function lookup ──────────────────────────────────────────
    {
        "query": "detect programming language from file extension and shebang",
        "expected_files": ["miner.py"],
        "category": "function_lookup",
    },
    {
        "query": "chunk code at structural boundaries for Python TypeScript Go",
        "expected_files": ["miner.py"],
        "category": "function_lookup",
    },
    {
        "query": "extract symbol name and type from code chunk",
        "expected_files": ["miner.py"],
        "category": "function_lookup",
    },
    {
        "query": "semantic search across palace drawers",
        "expected_files": ["searcher.py"],
        "category": "function_lookup",
    },
    {
        "query": "add drawer to palace with metadata",
        "expected_files": ["miner.py"],
        "category": "function_lookup",
    },
    {
        "query": "merge small chunks and split oversized ones",
        "expected_files": ["miner.py"],
        "category": "function_lookup",
    },
    # ── Class lookup ─────────────────────────────────────────────
    {
        "query": "DrawerStore abstract interface for storage backends",
        "expected_files": ["storage.py"],
        "category": "class_lookup",
    },
    {
        "query": "LanceDB crash safe vector storage backend",
        "expected_files": ["storage.py"],
        "category": "class_lookup",
    },
    {
        "query": "ChromaStore legacy storage backend",
        "expected_files": ["storage.py"],
        "category": "class_lookup",
    },
    {
        "query": "gitignore pattern matcher for file scanning",
        "expected_files": ["miner.py"],
        "category": "class_lookup",
    },
    # ── Architecture ─────────────────────────────────────────────
    {
        "query": "how does the miner route files to rooms based on path and content",
        "expected_files": ["miner.py"],
        "category": "architecture",
    },
    {
        "query": "how are embeddings generated and stored in LanceDB",
        "expected_files": ["storage.py"],
        "category": "architecture",
    },
    {
        "query": "what metadata fields are stored per drawer in the palace",
        "expected_files": ["storage.py"],
        "category": "architecture",
    },
    {
        "query": "how does smart chunking dispatch between code prose and adaptive strategies",
        "expected_files": ["miner.py"],
        "category": "architecture",
    },
    {
        "query": "MCP server tool handler dispatch and request routing",
        "expected_files": ["mcp_server.py"],
        "category": "architecture",
    },
    # ── Cross-file concepts ──────────────────────────────────────
    {
        "query": "open_store factory function backend detection lance chroma",
        "expected_files": ["storage.py"],
        "category": "cross_file",
    },
    {
        "query": "mine project directory files into palace drawers end to end",
        "expected_files": ["miner.py"],
        "category": "cross_file",
    },
    {
        "query": "knowledge graph temporal entity relationship triples",
        "expected_files": ["knowledge_graph.py"],
        "category": "cross_file",
    },
    {
        "query": "conversation mining Claude ChatGPT Slack exports",
        "expected_files": ["convo_miner.py"],
        "category": "cross_file",
    },
    {
        "query": "tiered context loading wake-up layers for local models",
        "expected_files": ["layers.py"],
        "category": "cross_file",
    },
]


# =============================================================================
# METRICS
# =============================================================================


def hit_at_k(results_metadatas, expected_files, k):
    """Check if any expected file appears in top-k results.

    Uses basename comparison to avoid false positives where one filename is a
    substring of another (e.g. "miner.py" matching "convo_miner.py").
    """
    top_k = results_metadatas[:k]
    for meta in top_k:
        source = meta.get("source_file", "")
        source_basename = source.rsplit("/", 1)[-1]
        for expected in expected_files:
            if source_basename == expected:
                return True
    return False


# =============================================================================
# CODE RETRIEVAL BENCHMARK
# =============================================================================


def mine_project(project_dir, palace_path, embed_model):
    """Mine a project into a temp palace with a specific embedding model."""
    store = open_store(palace_path, create=True, embed_model=embed_model)
    project_path = Path(project_dir).resolve()
    config = load_config(project_dir)
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])
    wing = config["wing"]
    files = scan_project(project_dir)

    total = 0
    for filepath in files:
        drawers = process_file(
            filepath=filepath,
            project_path=project_path,
            collection=store,
            wing=wing,
            rooms=rooms,
            agent="bench",
            dry_run=False,
        )
        total += drawers

    return store, total


def run_code_bench(model_key, model_spec, project_dir):
    """Run code retrieval benchmark for one model. Returns results dict."""
    print(f"\n  [{model_key}] Mining with {model_spec['name']}...")

    tmp_dir = tempfile.mkdtemp(prefix=f"bench_{model_key}_")
    try:
        # Mine
        t0 = time.time()
        store, chunk_count = mine_project(project_dir, tmp_dir, model_spec["name"])
        embed_time = time.time() - t0
        print(f"  [{model_key}] Mined {chunk_count} chunks in {embed_time:.1f}s")

        # Index size
        lance_dir = os.path.join(tmp_dir, "lance")
        index_bytes = sum(f.stat().st_size for f in Path(lance_dir).rglob("*") if f.is_file())
        index_mb = index_bytes / (1024 * 1024)

        # Run queries
        query_results = []
        query_latencies = []

        for q in QUERIES:
            t0 = time.time()
            results = store.query(
                query_texts=[q["query"]],
                n_results=10,
                include=["documents", "metadatas", "distances"],
            )
            latency_ms = (time.time() - t0) * 1000
            query_latencies.append(latency_ms)

            metas = results["metadatas"][0] if results["metadatas"] else []
            h5 = hit_at_k(metas, q["expected_files"], 5)
            h10 = hit_at_k(metas, q["expected_files"], 10)

            query_results.append(
                {
                    "query": q["query"],
                    "category": q["category"],
                    "expected_files": q["expected_files"],
                    "hit_at_5": h5,
                    "hit_at_10": h10,
                    "top5_files": [m.get("source_file", "").rsplit("/", 1)[-1] for m in metas[:5]],
                }
            )

        # Aggregate
        r5 = sum(1 for r in query_results if r["hit_at_5"]) / len(query_results)
        r10 = sum(1 for r in query_results if r["hit_at_10"]) / len(query_results)

        per_category = defaultdict(lambda: {"hits5": 0, "hits10": 0, "total": 0})
        for r in query_results:
            cat = r["category"]
            per_category[cat]["total"] += 1
            if r["hit_at_5"]:
                per_category[cat]["hits5"] += 1
            if r["hit_at_10"]:
                per_category[cat]["hits10"] += 1

        cat_scores = {}
        for cat, counts in per_category.items():
            cat_scores[cat] = {
                "R@5": counts["hits5"] / counts["total"],
                "R@10": counts["hits10"] / counts["total"],
            }

        avg_latency = sum(query_latencies) / len(query_latencies)
        p95_latency = sorted(query_latencies)[int(len(query_latencies) * 0.95)]

        print(
            f"  [{model_key}] R@5={r5:.3f}  R@10={r10:.3f}  "
            f"embed={embed_time:.1f}s  query_avg={avg_latency:.1f}ms  "
            f"index={index_mb:.1f}MB"
        )

        return {
            "code_retrieval": {
                "R@5": r5,
                "R@10": r10,
                "per_category": cat_scores,
                "per_query": query_results,
            },
            "performance": {
                "embed_time_s": round(embed_time, 1),
                "embed_chunks": chunk_count,
                "embed_per_chunk_ms": round(embed_time / max(chunk_count, 1) * 1000, 1),
                "query_latency_avg_ms": round(avg_latency, 1),
                "query_latency_p95_ms": round(p95_latency, 1),
                "index_size_mb": round(index_mb, 1),
            },
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        gc.collect()


# =============================================================================
# LONGMEMEVAL NO-REGRESSION GATE
# =============================================================================

# Map our model keys to longmemeval_bench --embed-model keys
_LONGMEMEVAL_MODEL_MAP = {
    "minilm": "default",
    "mpnet": "mpnet",
    "nomic": "nomic",
}


def run_longmemeval_gate(model_key, data_path):
    """Run LongMemEval with a model and parse R@5 from output."""
    lme_key = _LONGMEMEVAL_MODEL_MAP.get(model_key)
    if not lme_key:
        return None

    bench_script = str(_PROJECT_ROOT / "benchmarks" / "longmemeval_bench.py")
    cmd = [
        sys.executable,
        bench_script,
        data_path,
        "--embed-model",
        lme_key,
        "--limit",
        "50",
        "--top-k",
        "10",
    ]

    print(f"  [{model_key}] Running LongMemEval gate (50 questions)...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = result.stdout + result.stderr

        # Parse recall@5 from output (format: "Recall@5: 0.960")
        r5 = None
        r10 = None
        ndcg = None
        for line in output.splitlines():
            line_lower = line.strip().lower()
            if "recall@5" in line_lower and ":" in line:
                try:
                    r5 = float(line.split(":")[-1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
            elif "recall@10" in line_lower and ":" in line:
                try:
                    r10 = float(line.split(":")[-1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
            elif "ndcg@10" in line_lower and ":" in line:
                try:
                    ndcg = float(line.split(":")[-1].strip().split()[0])
                except (ValueError, IndexError):
                    pass

        if r5 is not None:
            print(f"  [{model_key}] LongMemEval R@5={r5:.3f}")

        return {"R@5": r5, "R@10": r10, "NDCG@10": ndcg}

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [{model_key}] LongMemEval failed: {e}")
        return None


# =============================================================================
# REPORTING
# =============================================================================


def print_report(all_results, model_keys):
    """Print comparison table."""
    print(f"\n{'=' * 70}")
    print("  BENCH-EMBED-AB Results")
    print(f"{'=' * 70}")

    # Code retrieval table
    print(f"\n  CODE RETRIEVAL ({len(QUERIES)} queries on mempalace repo):\n")
    print(
        f"  {'Model':<10} | {'R@5':>6} | {'R@10':>6} | {'Embed(s)':>9} | {'Query(ms)':>10} | {'Index(MB)':>10}"
    )
    print(f"  {'-' * 10}-+-{'-' * 6}-+-{'-' * 6}-+-{'-' * 9}-+-{'-' * 10}-+-{'-' * 10}")
    for key in model_keys:
        r = all_results[key]
        cr = r.get("code_retrieval", {})
        perf = r.get("performance", {})
        print(
            f"  {key:<10} | {cr.get('R@5', 0):>6.3f} | {cr.get('R@10', 0):>6.3f} | "
            f"{perf.get('embed_time_s', 0):>9.1f} | {perf.get('query_latency_avg_ms', 0):>10.1f} | "
            f"{perf.get('index_size_mb', 0):>10.1f}"
        )

    # Per-category breakdown
    print("\n  Per-category R@5:")
    categories = sorted({q["category"] for q in QUERIES})
    header = f"  {'Model':<10}"
    for cat in categories:
        header += f" | {cat[:15]:>15}"
    print(header)
    print(f"  {'-' * 10}" + "".join(f"-+-{'-' * 15}" for _ in categories))
    for key in model_keys:
        cr = all_results[key].get("code_retrieval", {})
        cat_scores = cr.get("per_category", {})
        row = f"  {key:<10}"
        for cat in categories:
            score = cat_scores.get(cat, {}).get("R@5", 0)
            row += f" | {score:>15.3f}"
        print(row)

    # LongMemEval gate
    has_lme = any(all_results[k].get("text_retrieval") for k in model_keys)
    if has_lme:
        print("\n  TEXT RETRIEVAL (LongMemEval no-regression gate):\n")
        print(f"  {'Model':<10} | {'R@5':>6} | {'R@10':>6} | {'NDCG@10':>8} | {'Gate':>6}")
        print(f"  {'-' * 10}-+-{'-' * 6}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 6}")
        baseline_r5 = all_results[model_keys[0]].get("text_retrieval", {}).get("R@5")
        for key in model_keys:
            tr = all_results[key].get("text_retrieval", {})
            if not tr or tr.get("R@5") is None:
                print(f"  {key:<10} | {'N/A':>6} | {'N/A':>6} | {'N/A':>8} | {'SKIP':>6}")
                continue
            r5 = tr["R@5"]
            r10 = tr.get("R@10") or 0
            ndcg_val = tr.get("NDCG@10") or 0
            if key == model_keys[0]:
                gate = "BASE"
            elif baseline_r5 is not None and r5 >= baseline_r5 - 0.02:
                gate = "PASS"
            else:
                gate = "FAIL"
            print(f"  {key:<10} | {r5:>6.3f} | {r10:>6.3f} | {ndcg_val:>8.3f} | {gate:>6}")

    print(f"\n{'=' * 70}\n")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="A/B embedding model benchmark for mempalace code retrieval"
    )
    parser.add_argument(
        "--models",
        default="minilm,mpnet,nomic",
        help="Comma-separated model keys (default: minilm,mpnet,nomic)",
    )
    parser.add_argument(
        "--project",
        default=str(_PROJECT_ROOT),
        help="Project directory to mine (default: mempalace repo root)",
    )
    parser.add_argument(
        "--longmemeval-data",
        help="Path to longmemeval_s_cleaned.json for text retrieval gate",
    )
    parser.add_argument(
        "--skip-longmemeval",
        action="store_true",
        help="Skip the LongMemEval no-regression gate",
    )
    parser.add_argument(
        "--out",
        help="Output JSON report path",
    )
    parser.add_argument(
        "--validate-queries",
        action="store_true",
        help="Mine with default model and show which queries hit/miss, then exit",
    )
    args = parser.parse_args()

    model_keys = [k.strip() for k in args.models.split(",")]
    for key in model_keys:
        if key not in MODELS:
            print(f"Unknown model key: {key}. Available: {', '.join(MODELS)}")
            sys.exit(1)

    print(f"BENCH-EMBED-AB — Comparing: {', '.join(model_keys)}")
    print(f"Project: {args.project}")
    print(f"Queries: {len(QUERIES)}")

    # Validate-queries mode
    if args.validate_queries:
        print("\n  Validating queries with default model (minilm)...")
        result = run_code_bench("minilm", MODELS["minilm"], args.project)
        print("\n  Query validation results:")
        for qr in result["code_retrieval"]["per_query"]:
            status = "HIT" if qr["hit_at_5"] else ("hit@10" if qr["hit_at_10"] else "MISS")
            print(f"    [{status:>6}] {qr['query'][:60]}")
            if not qr["hit_at_5"]:
                print(f"           expected: {qr['expected_files']}")
                print(f"           got top5: {qr['top5_files']}")
        return

    # Run benchmarks
    all_results = {}
    for key in model_keys:
        spec = MODELS[key]
        print(f"\n{'─' * 55}")
        print(f"  Model: {key} ({spec['name']}, {spec['dims']}d, {spec['context_tokens']} tok)")
        print(f"{'─' * 55}")

        # Code retrieval
        result = run_code_bench(key, spec, args.project)

        # Text retrieval gate
        if not args.skip_longmemeval and args.longmemeval_data:
            lme_result = run_longmemeval_gate(key, args.longmemeval_data)
            if lme_result:
                result["text_retrieval"] = lme_result

        all_results[key] = {
            "model_name": spec["name"],
            "dims": spec["dims"],
            "context_tokens": spec["context_tokens"],
            **result,
        }

    # Report
    print_report(all_results, model_keys)

    # Save JSON
    out_path = args.out
    if not out_path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = str(_PROJECT_ROOT / "benchmarks" / f"results_embed_ab_{ts}.json")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "project": Path(args.project).name,
        "query_count": len(QUERIES),
        "models": all_results,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to: {out_path}")


if __name__ == "__main__":
    main()
