#!/usr/bin/env python3
"""
BENCH-EMBED-AB — A/B embedding model benchmark for mempalace.

Compares embedding models on code retrieval quality and performance.
Uses the mempalace repo itself as the test corpus and the known-answer queries in
benchmarks/data/code_retrieval_queries.json, shared with code_retrieval_bench.py.

With --longmemeval-data, every model must also match or beat the first (baseline)
model's LongMemEval R@5. The run exits 1 when that gate fails or cannot run.

Usage:
    python benchmarks/embed_ab_bench.py
    python benchmarks/embed_ab_bench.py --models minilm,nomic
    python benchmarks/embed_ab_bench.py --longmemeval-data benchmarks/data/longmemeval_s_cleaned.json
    python benchmarks/embed_ab_bench.py --skip-longmemeval --out results.json
"""

import argparse
import gc
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

# Import mempalace_code from this checkout and the shared query set from this directory.
_BENCH_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BENCH_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_BENCH_DIR))

from code_retrieval_bench import DEFAULT_DATASET, hit_at_k, load_dataset  # noqa: E402

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
# code_retrieval_bench.py owns this ground truth and checks it against the current
# module owners (`--validate-dataset`); hits match path suffixes and, for symbol
# queries, the declared symbol.
# =============================================================================

QUERIES = load_dataset(DEFAULT_DATASET)


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
            h5 = hit_at_k(metas, q["expected_files"], 5, q.get("expected_symbols"))
            h10 = hit_at_k(metas, q["expected_files"], 10, q.get("expected_symbols"))

            query_results.append(
                {
                    "id": q["id"],
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


def _gate_error(model_key, detail):
    print(f"  [{model_key}] LongMemEval gate could not run: {detail}", file=sys.stderr)
    return {"R@5": None, "R@10": None, "NDCG@10": None, "error": detail}


def run_longmemeval_gate(model_key, data_path):
    """Run LongMemEval with a model and parse R@5 from output.

    A run that cannot produce R@5 returns an ``error`` entry that fails the gate.
    benchmarks/longmemeval_bench.py still imports the retired chromadb package, so in
    a current environment the gate reports that import failure instead of passing.
    """
    lme_key = _LONGMEMEVAL_MODEL_MAP.get(model_key)
    if not lme_key:
        return _gate_error(model_key, "no LongMemEval embedding mapping for this model")

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

        # The harness pads k to two columns and prints recall and NDCG on one line.
        r5 = None
        r10 = None
        ndcg = None
        for line in output.splitlines():
            for match in re.finditer(r"(recall|ndcg)@\s*(5|10)\s*:\s*(\S+)", line, re.I):
                try:
                    value = float(match[3])
                except ValueError:
                    return _gate_error(model_key, f"invalid metric: {match[0]}")
                if not math.isfinite(value) or not 0 <= value <= 1:
                    return _gate_error(model_key, f"invalid metric: {match[0]}")
                metric = (match[1].lower(), match[2])
                if metric == ("recall", "5"):
                    r5 = value
                elif metric == ("recall", "10"):
                    r10 = value
                elif metric == ("ndcg", "10"):
                    ndcg = value

        if result.returncode != 0 or r5 is None:
            last_line = next((ln.strip() for ln in reversed(output.splitlines()) if ln.strip()), "")
            return _gate_error(
                model_key,
                f"longmemeval_bench.py exited {result.returncode} without Recall@5: "
                f"{last_line or 'no output'}",
            )

        print(f"  [{model_key}] LongMemEval R@5={r5:.3f}")

        return {"R@5": r5, "R@10": r10, "NDCG@10": ndcg}

    except (subprocess.TimeoutExpired, OSError) as e:
        return _gate_error(model_key, str(e))


def longmemeval_verdicts(all_results, model_keys):
    """Gate each model on LongMemEval R@5: it must match or beat the first (baseline) model."""
    baseline_r5 = all_results[model_keys[0]].get("text_retrieval", {}).get("R@5")
    verdicts = {}
    for key in model_keys:
        r5 = all_results[key].get("text_retrieval", {}).get("R@5")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in (r5, baseline_r5)
        ):
            verdicts[key] = "ERROR"
        elif key == model_keys[0]:
            verdicts[key] = "BASE"
        else:
            verdicts[key] = "PASS" if r5 >= baseline_r5 else "FAIL"
    return verdicts


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
        print("\n  TEXT RETRIEVAL (LongMemEval no-regression gate: match or beat baseline R@5):\n")
        print(f"  {'Model':<10} | {'R@5':>6} | {'R@10':>6} | {'NDCG@10':>8} | {'Gate':>6}")
        print(f"  {'-' * 10}-+-{'-' * 6}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 6}")
        verdicts = longmemeval_verdicts(all_results, model_keys)
        for key in model_keys:
            tr = all_results[key].get("text_retrieval", {})
            gate = verdicts[key]
            if tr.get("R@5") is None:
                print(f"  {key:<10} | {'N/A':>6} | {'N/A':>6} | {'N/A':>8} | {gate:>6}")
                continue
            r10 = tr.get("R@10") or 0
            ndcg_val = tr.get("NDCG@10") or 0
            print(f"  {key:<10} | {tr['R@5']:>6.3f} | {r10:>6.3f} | {ndcg_val:>8.3f} | {gate:>6}")

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

    gate_requested = bool(args.longmemeval_data) and not args.skip_longmemeval
    if gate_requested and not Path(args.longmemeval_data).is_file():
        print(f"LongMemEval data not found: {args.longmemeval_data}", file=sys.stderr)
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
        if gate_requested:
            result["text_retrieval"] = run_longmemeval_gate(key, args.longmemeval_data)

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

    if gate_requested:
        verdicts = longmemeval_verdicts(all_results, model_keys)
        failed = [key for key in model_keys if verdicts[key] in {"FAIL", "ERROR"}]
        if failed:
            print(
                f"LongMemEval no-regression gate did not pass for: {', '.join(failed)}",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
