#!/usr/bin/env python3
"""
BENCH-DOTNET — C#/.NET repository code retrieval benchmark for mempalace.

Mines a multi-project .NET repo into a temp LanceDB palace and evaluates
R@5 / R@10 across 4 query categories:
  - symbol_lookup     : named C# classes and enums by description
  - cross_project     : interfaces (Application layer) vs implementations (Infrastructure)
  - interface_impl    : concrete service and validator implementations
  - project_dependency: NuGet packages and project references in .csproj files

Target repo: jasontaylordev/CleanArchitecture v7.0.0
Pinned commit: 5a600ab8749c110384bc3bd436b9c67f3067b489

Usage:
    python benchmarks/dotnet_bench.py --repo-dir /path/to/CleanArchitecture
    python benchmarks/dotnet_bench.py --repo-dir /path/to/CleanArchitecture --validate-queries
    python benchmarks/dotnet_bench.py --repo-dir /path/to/CleanArchitecture --out results.json
"""

import argparse
import json
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

from mempalace_code.miner import process_file, scan_project  # noqa: E402
from mempalace_code.storage import open_store  # noqa: E402

EMBED_MODEL = "all-MiniLM-L6-v2"
R5_THRESHOLD = 0.800

# =============================================================================
# KNOWN-ANSWER QUERY SET — 20 queries across 4 .NET-specific categories
#
# Target: jasontaylordev/CleanArchitecture
# expected_files are basenames — consistent with embed_ab_bench.py.
# =============================================================================

QUERIES = [
    # ── symbol_lookup ────────────────────────────────────────────────────────
    {
        "query": "TodoItem domain entity title description is done priority",
        "expected_files": ["TodoItem.cs"],
        "category": "symbol_lookup",
    },
    {
        "query": "TodoList aggregate root collection of todo items",
        "expected_files": ["TodoList.cs"],
        "category": "symbol_lookup",
    },
    {
        "query": "PriorityLevel enum low medium high priority values",
        "expected_files": ["PriorityLevel.cs"],
        "category": "symbol_lookup",
    },
    {
        "query": "CreateTodoItemCommand application command create new todo item",
        "expected_files": ["CreateTodoItemCommand.cs"],
        "category": "symbol_lookup",
    },
    {
        "query": "GetTodosQuery handler return all todo lists with items",
        "expected_files": ["GetTodosQuery.cs"],
        "category": "symbol_lookup",
    },
    # ── cross_project ────────────────────────────────────────────────────────
    {
        "query": "IApplicationDbContext interface Entity Framework DbSet TodoItems TodoLists",
        "expected_files": ["IApplicationDbContext.cs"],
        "category": "cross_project",
    },
    {
        "query": "ApplicationDbContext Entity Framework Core database context implementation",
        "expected_files": ["ApplicationDbContext.cs"],
        "category": "cross_project",
    },
    {
        "query": "IIdentityService interface get user name by user identifier",
        "expected_files": ["IIdentityService.cs"],
        "category": "cross_project",
    },
    {
        "query": "IdentityService ASP.NET Core Identity user lookup implementation",
        "expected_files": ["IdentityService.cs"],
        "category": "cross_project",
    },
    {
        "query": "IDateTime interface abstract system clock current date time",
        "expected_files": ["IDateTime.cs"],
        "category": "cross_project",
    },
    # ── interface_impl ───────────────────────────────────────────────────────
    {
        "query": "DateTimeService current UTC date time service implementation",
        "expected_files": ["DateTimeService.cs"],
        "category": "interface_impl",
    },
    {
        "query": "FluentValidation validator create todo item title required rule",
        "expected_files": ["CreateTodoItemCommandValidator.cs"],
        "category": "interface_impl",
    },
    {
        "query": "infrastructure service registration extension method dependency injection",
        "expected_files": ["ConfigureServices.cs"],
        "category": "interface_impl",
    },
    {
        "query": "application layer MediatR pipeline behavior registration assembly scan",
        "expected_files": ["ConfigureServices.cs"],
        "category": "interface_impl",
    },
    {
        "query": "TodoItemCompleted domain event notification handler",
        "expected_files": ["TodoItemCompletedEventHandler.cs"],
        "category": "interface_impl",
    },
    # ── project_dependency ───────────────────────────────────────────────────
    {
        "query": "Microsoft EntityFrameworkCore SqlServer NuGet PackageReference",
        "expected_files": ["Infrastructure.csproj"],
        "category": "project_dependency",
    },
    {
        "query": "project reference Infrastructure depends on Application ProjectReference",
        "expected_files": ["Infrastructure.csproj"],
        "category": "project_dependency",
    },
    {
        "query": "MediatR package reference application layer service dependency",
        "expected_files": ["Application.csproj"],
        "category": "project_dependency",
    },
    {
        "query": "target framework net7 web sdk application configuration",
        "expected_files": ["WebUI.csproj"],
        "category": "project_dependency",
    },
    {
        "query": "Domain class library TargetFramework no external dependencies",
        "expected_files": ["Domain.csproj"],
        "category": "project_dependency",
    },
]


# =============================================================================
# METRICS
# =============================================================================


def hit_at_k(results_metadatas, expected_files, k):
    """Check if any expected file appears in top-k results (basename equality)."""
    top_k = results_metadatas[:k]
    for meta in top_k:
        source = meta.get("source_file", "")
        source_basename = source.rsplit("/", 1)[-1]
        for expected in expected_files:
            if source_basename == expected:
                return True
    return False


# =============================================================================
# MINING
# =============================================================================


def mine_project(repo_dir, palace_path):
    """Mine a .NET repo into a temp palace with the default embedding model.

    Does NOT call load_config on the target repo — it won't have mempalace.yaml.
    Wing and rooms are hardcoded for .NET benchmarking.
    """
    store = open_store(palace_path, create=True, embed_model=EMBED_MODEL)
    project_path = Path(repo_dir).resolve()
    wing = "dotnet-bench"
    rooms = [{"name": "general", "description": "C#/.NET source files"}]
    files = scan_project(repo_dir)

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


# =============================================================================
# BENCHMARK
# =============================================================================


def run_bench(repo_dir):
    """Mine repo, run 20 queries, return results dict."""
    print(f"\nMining {repo_dir} with {EMBED_MODEL}...")

    tmp_dir = tempfile.mkdtemp(prefix="dotnet_bench_")
    try:
        t0 = time.time()
        store, chunk_count = mine_project(repo_dir, tmp_dir)
        embed_time = time.time() - t0
        print(f"Mined {chunk_count} chunks in {embed_time:.1f}s")

        # Index size
        lance_dir = Path(tmp_dir) / "lance"
        if lance_dir.exists():
            index_bytes = sum(f.stat().st_size for f in lance_dir.rglob("*") if f.is_file())
        else:
            index_bytes = 0
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
        # p95: index n*0.95-1 (floor) to avoid max==p95 issue (BENCH-EMBED-AB F-002)
        p95_idx = max(0, int(len(query_latencies) * 0.95) - 1)
        p95_latency = sorted(query_latencies)[p95_idx]

        return {
            "code_retrieval": {
                "R@5": r5,
                "R@10": r10,
                "per_category": cat_scores,
                "per_query": query_results,
            },
            "performance": {
                "embed_time_s": round(embed_time, 1),
                "chunk_count": chunk_count,
                "query_latency_avg_ms": round(avg_latency, 1),
                "query_latency_p95_ms": round(p95_latency, 1),
                "index_size_mb": round(index_mb, 1),
            },
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# VALIDATE-QUERIES MODE
# =============================================================================


def validate_queries(repo_dir):
    """Mine the repo and check that every expected_file basename is present.

    Prints PASS/FAIL per query. Exits non-zero if any query FAILs.
    """
    print(f"\nValidating query set against {repo_dir}...")

    tmp_dir = tempfile.mkdtemp(prefix="dotnet_validate_")
    try:
        store, chunk_count = mine_project(repo_dir, tmp_dir)
        print(f"Mined {chunk_count} chunks\n")

        # Collect all distinct basenames using column scan (reliable even when
        # chunk_count mismatches stored count due to dedup/batch failures).
        source_files = store.get_source_files("dotnet-bench") or set()
        basenames = {sf.rsplit("/", 1)[-1] for sf in source_files}

        any_fail = False
        for q in QUERIES:
            missing = [f for f in q["expected_files"] if f not in basenames]
            if missing:
                status = "FAIL"
                any_fail = True
            else:
                status = "PASS"
            print(f"  [{status}] {q['query'][:65]}")
            if missing:
                print(f"         missing basenames: {missing}")

        if any_fail:
            print("\nFAIL — some expected files were not found in the mined corpus.")
            print("Update expected_files in QUERIES to match actual filenames.")
            sys.exit(1)
        else:
            print("\nPASS — all expected files are present in the mined corpus.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# REPORTING
# =============================================================================


def get_repo_commit(repo_dir):
    """Return HEAD commit hash of the repo, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "unknown"


def print_report(bench_results):
    """Print results table to stdout."""
    cr = bench_results["code_retrieval"]
    perf = bench_results["performance"]

    print(f"\n{'=' * 60}")
    print("  BENCH-DOTNET Results")
    print(f"{'=' * 60}")
    print(f"\n  Model:      {EMBED_MODEL}")
    print(f"  Chunks:     {perf['chunk_count']}")
    print(f"  Embed time: {perf['embed_time_s']}s")
    print(f"  Index size: {perf['index_size_mb']}MB")
    print(f"  Query avg:  {perf['query_latency_avg_ms']}ms")
    print(f"  Query p95:  {perf['query_latency_p95_ms']}ms")

    print(f"\n  OVERALL  R@5={cr['R@5']:.3f}  R@10={cr['R@10']:.3f}")

    if cr["R@5"] < R5_THRESHOLD:
        print(f"\n  WARNING: R@5 {cr['R@5']:.3f} is below threshold {R5_THRESHOLD:.3f}")

    print("\n  Per-category R@5 / R@10:\n")
    categories = ["symbol_lookup", "cross_project", "interface_impl", "project_dependency"]
    for cat in categories:
        scores = cr["per_category"].get(cat, {})
        r5 = scores.get("R@5", 0)
        r10 = scores.get("R@10", 0)
        print(f"    {cat:<22}  R@5={r5:.3f}  R@10={r10:.3f}")

    # Per-query detail for misses
    misses = [r for r in cr["per_query"] if not r["hit_at_5"]]
    if misses:
        print(f"\n  Misses at R@5 ({len(misses)}):")
        for r in misses:
            hit10 = "hit@10" if r["hit_at_10"] else "miss"
            print(f"    [{hit10}] {r['query'][:60]}")
            print(f"             expected: {r['expected_files']}")
            print(f"             got top5: {r['top5_files']}")

    print(f"\n{'=' * 60}\n")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="C#/.NET code retrieval benchmark for mempalace")
    parser.add_argument(
        "--repo-dir",
        required=True,
        help="Path to pre-cloned .NET repository (e.g. jasontaylordev/CleanArchitecture)",
    )
    parser.add_argument(
        "--validate-queries",
        action="store_true",
        help="Check that each expected_file basename is present in the mined corpus; exit",
    )
    parser.add_argument(
        "--out",
        help="Output JSON path (default: benchmarks/results_dotnet_bench_<date>.json)",
    )
    args = parser.parse_args()

    repo_dir = str(Path(args.repo_dir).resolve())

    if not Path(repo_dir).is_dir():
        print(f"Error: --repo-dir {repo_dir!r} is not a directory")
        sys.exit(1)

    print(f"BENCH-DOTNET — target: {repo_dir}")
    print(f"Model: {EMBED_MODEL}  |  Queries: {len(QUERIES)}")

    if args.validate_queries:
        validate_queries(repo_dir)
        return

    bench_results = run_bench(repo_dir)
    print_report(bench_results)

    # Build output JSON
    today = time.strftime("%Y-%m-%d")
    out_path = args.out
    if not out_path:
        date_compact = time.strftime("%Y-%m-%d")
        out_path = str(_PROJECT_ROOT / "benchmarks" / f"results_dotnet_bench_{date_compact}.json")

    output = {
        "meta": {
            "date": today,
            "repo": "jasontaylordev/CleanArchitecture",
            "repo_tag": "v7.0.0",
            "expected_repo_commit": "5a600ab8749c110384bc3bd436b9c67f3067b489",
            "repo_commit": get_repo_commit(repo_dir),
            "embed_model": EMBED_MODEL,
            "query_count": len(QUERIES),
        },
        "code_retrieval": bench_results["code_retrieval"],
        "performance": bench_results["performance"],
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to: {out_path}")


if __name__ == "__main__":
    main()
