#!/usr/bin/env python3
"""
BENCH-TOKEN-DELTA — Token savings benchmark: mempalace search vs grep+read baseline.

Measures how many tokens a developer saves by using mempalace semantic search
instead of the naive grep-for-keywords-then-read-full-files approach.

Method:
  1. Baseline: extract keywords from each query, grep for candidate files,
     read the top-5 files entirely, count tokens with tiktoken cl100k_base.
  2. MemPalace: mine the project, search_memories(query, limit=5),
     concatenate result text, count tokens the same way.
  3. Ratio: baseline_tokens / mempalace_tokens per query.

Usage:
    python benchmarks/token_delta_bench.py
    python benchmarks/token_delta_bench.py --project /path/to/repo
    python benchmarks/token_delta_bench.py --out results_token_delta.json
    python benchmarks/token_delta_bench.py --queries custom_queries.json
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path so we can import mempalace
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from mempalace.miner import load_config, process_file, scan_project  # noqa: E402
from mempalace.searcher import search_memories  # noqa: E402
from mempalace.storage import open_store  # noqa: E402


# =============================================================================
# QUERY SET (reused from embed_ab_bench.py)
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
# STOPWORDS — minimal set for keyword extraction
# =============================================================================

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "does",
        "for",
        "from",
        "has",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)


# =============================================================================
# KEYWORD EXTRACTION
# =============================================================================


def extract_keywords(query: str, max_keywords: int = 3) -> list:
    """Extract 1-3 search keywords from a query string.

    Splits on whitespace, filters stopwords and short tokens,
    returns the longest remaining terms (longer words tend to be
    more discriminating for grep).
    """
    words = query.lower().split()
    candidates = [w for w in words if w not in STOPWORDS and len(w) >= 3]
    # Sort by length descending — longer words are more specific
    candidates.sort(key=len, reverse=True)
    return candidates[:max_keywords]


# =============================================================================
# GREP BASELINE
# =============================================================================

# Detect rg (ripgrep) once at import time
_RG_PATH = shutil.which("rg")


def grep_find_files(keyword: str, project_dir: str, max_files: int = 20) -> list:
    """Use rg or grep to find files containing a keyword. Returns file paths."""
    if _RG_PATH:
        cmd = [_RG_PATH, "-l", "-i", "--max-count", "1", keyword, project_dir]
    else:
        cmd = ["grep", "-rl", "-i", keyword, project_dir]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        paths = [p.strip() for p in result.stdout.splitlines() if p.strip()]
        return paths[:max_files]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def baseline_grep_read(query: str, project_dir: str, limit: int = 5) -> tuple:
    """Simulate the grep+read baseline for one query.

    Returns (token_count, files_read_count, file_list).
    Extracts keywords, greps for candidate files, reads the top files,
    counts tokens on the concatenated content.
    """
    keywords = extract_keywords(query)
    if not keywords:
        return (0, 0, [])

    # Grep for each keyword, intersect file sets for precision
    file_sets = []
    for kw in keywords:
        found = grep_find_files(kw, project_dir)
        if found:
            file_sets.append(set(found))

    if not file_sets:
        return (0, 0, [])

    # Start from the smallest set, intersect with others
    # If intersection is empty, fall back to union of the first keyword's matches
    candidate_files = file_sets[0]
    for fs in file_sets[1:]:
        intersected = candidate_files & fs
        if intersected:
            candidate_files = intersected

    # Sort by path length (shorter = more likely a core module) and take top N
    sorted_files = sorted(candidate_files, key=len)[:limit]

    # Read files and count tokens
    combined_text = ""
    files_read = []
    for fpath in sorted_files:
        try:
            content = Path(fpath).read_text(encoding="utf-8", errors="replace")
            combined_text += content + "\n"
            files_read.append(fpath)
        except OSError:
            continue

    token_count = count_tokens(combined_text)
    return (token_count, len(files_read), files_read)


# =============================================================================
# TOKEN COUNTING
# =============================================================================

_ENCODING = None


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    global _ENCODING  # noqa: PLW0603
    if _ENCODING is None:
        import tiktoken

        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODING.encode(text))


# =============================================================================
# MEMPALACE SEARCH
# =============================================================================


def mine_project(project_dir: str, palace_path: str) -> tuple:
    """Mine a project into a temp palace. Returns (store, chunk_count)."""
    store = open_store(palace_path, create=True)
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


def mempalace_search_tokens(query: str, palace_path: str, limit: int = 5) -> tuple:
    """Search mempalace and count tokens in concatenated results.

    Returns (token_count, result_count, result_sources).
    """
    result = search_memories(query, palace_path, n_results=limit)

    if "error" in result:
        return (0, 0, [])

    hits = result.get("results", [])
    if not hits:
        return (0, 0, [])

    combined_text = "\n".join(h["text"] for h in hits)
    sources = [h["source_file"] for h in hits]
    token_count = count_tokens(combined_text)
    return (token_count, len(hits), sources)


# =============================================================================
# STATISTICS
# =============================================================================


def median(values: list) -> float:
    """Compute the median of a list of numbers."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def percentile(values: list, pct: float) -> float:
    """Compute a percentile (0-100) of a list of numbers."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (pct / 100) * (len(s) - 1)
    f = int(k)
    c = f + 1
    if c >= len(s):
        return s[f]
    return s[f] + (k - f) * (s[c] - s[f])


# =============================================================================
# REPORTING
# =============================================================================


def print_report(query_results: list):
    """Print per-query table and summary statistics to stdout."""
    print(f"\n{'=' * 90}")
    print("  BENCH-TOKEN-DELTA Results")
    print(f"{'=' * 90}\n")

    # Per-query table
    header = f"  {'#':>2}  {'Category':<16} {'Baseline':>10} {'MemPalace':>10} {'Ratio':>7}  Query"
    print(header)
    print(f"  {'-' * 86}")

    for i, qr in enumerate(query_results, 1):
        ratio_str = f"{qr['ratio']:.1f}x" if qr["ratio"] is not None else "N/A"
        query_short = qr["query"][:38]
        print(
            f"  {i:>2}  {qr['category']:<16} {qr['baseline_tokens']:>10,} "
            f"{qr['mempalace_tokens']:>10,} {ratio_str:>7}  {query_short}"
        )

    # Collect ratios (skip queries where baseline found no files)
    ratios = [qr["ratio"] for qr in query_results if qr["ratio"] is not None]

    if not ratios:
        print("\n  No valid ratios computed (grep found no files for any query).")
        return

    med = median(ratios)
    p95 = percentile(ratios, 95)
    mean_ratio = sum(ratios) / len(ratios)

    print(f"\n  {'─' * 86}")
    print(f"\n  SUMMARY ({len(ratios)} queries with valid ratios):\n")
    print(f"    Median ratio:  {med:.1f}x fewer tokens")
    print(f"    Mean ratio:    {mean_ratio:.1f}x fewer tokens")
    print(f"    P95 ratio:     {p95:.1f}x fewer tokens")

    # Per-category medians
    from collections import defaultdict

    cat_ratios = defaultdict(list)
    for qr in query_results:
        if qr["ratio"] is not None:
            cat_ratios[qr["category"]].append(qr["ratio"])

    if cat_ratios:
        print("\n  Per-category median ratios:\n")
        print(f"    {'Category':<20} {'Median':>8} {'Queries':>8}")
        print(f"    {'-' * 38}")
        for cat in sorted(cat_ratios):
            cat_med = median(cat_ratios[cat])
            print(f"    {cat:<20} {cat_med:>7.1f}x {len(cat_ratios[cat]):>8}")

    # Total token comparison
    total_baseline = sum(qr["baseline_tokens"] for qr in query_results)
    total_mempalace = sum(qr["mempalace_tokens"] for qr in query_results)
    if total_mempalace > 0:
        total_ratio = total_baseline / total_mempalace
        print(
            f"\n  Aggregate: {total_baseline:,} baseline tokens vs "
            f"{total_mempalace:,} mempalace tokens = {total_ratio:.1f}x savings"
        )

    print(f"\n{'=' * 90}\n")


# =============================================================================
# QUERY LOADING
# =============================================================================


def load_queries(queries_path: str) -> list:
    """Load queries from a JSON file.

    Expected format: list of objects with keys: query, expected_files, category.
    """
    with open(queries_path) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"ERROR: queries file must contain a JSON array, got {type(data).__name__}")
        sys.exit(1)

    for i, q in enumerate(data):
        if "query" not in q:
            print(f"ERROR: query #{i} missing 'query' field")
            sys.exit(1)
        q.setdefault("category", "custom")
        q.setdefault("expected_files", [])

    return data


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Token savings benchmark: mempalace search vs grep+read baseline"
    )
    parser.add_argument(
        "--project",
        default=".",
        help="Project directory to benchmark against (default: current directory)",
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Temp palace directory (default: auto-created tmpdir)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON results path (default: auto-named in benchmarks/)",
    )
    parser.add_argument(
        "--queries",
        default=None,
        help="Path to custom queries JSON file (default: built-in 20-query set)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of results/files to retrieve per query (default: 5)",
    )
    args = parser.parse_args()

    project_dir = str(Path(args.project).resolve())
    queries = load_queries(args.queries) if args.queries else QUERIES

    print("BENCH-TOKEN-DELTA")
    print(f"Project: {project_dir}")
    print(f"Queries: {len(queries)}")
    print(f"Search tool: {'rg (ripgrep)' if _RG_PATH else 'grep'}")
    print(f"Results per query: {args.limit}")

    # Create temp palace
    palace_path = args.palace
    palace_is_tmp = palace_path is None
    if palace_is_tmp:
        palace_path = tempfile.mkdtemp(prefix="bench_tokdelta_")

    try:
        # Phase 1: Mine the project
        print(f"\n{'─' * 55}")
        print("  Phase 1: Mining project into temp palace...")
        print(f"{'─' * 55}")

        t0 = time.time()
        _store, chunk_count = mine_project(project_dir, palace_path)
        mine_time = time.time() - t0
        print(f"  Mined {chunk_count} chunks in {mine_time:.1f}s")

        # Phase 2: Run queries
        print(f"\n{'─' * 55}")
        print("  Phase 2: Running queries (baseline + mempalace)...")
        print(f"{'─' * 55}\n")

        query_results = []
        for i, q in enumerate(queries, 1):
            query_text = q["query"]
            category = q["category"]

            # Baseline: grep + read
            base_tokens, base_files, base_file_list = baseline_grep_read(
                query_text, project_dir, limit=args.limit
            )

            # MemPalace: search
            mp_tokens, mp_results, mp_sources = mempalace_search_tokens(
                query_text, palace_path, limit=args.limit
            )

            # Compute ratio
            if base_tokens > 0 and mp_tokens > 0:
                ratio = base_tokens / mp_tokens
            else:
                ratio = None

            ratio_str = f"{ratio:.1f}x" if ratio is not None else "N/A"
            print(
                f"  [{i:>2}/{len(queries)}] {query_text[:50]:50} "
                f"baseline={base_tokens:>7,}  mp={mp_tokens:>5,}  ratio={ratio_str}"
            )

            query_results.append(
                {
                    "query": query_text,
                    "category": category,
                    "expected_files": q.get("expected_files", []),
                    "baseline_tokens": base_tokens,
                    "baseline_files_read": base_files,
                    "baseline_file_list": [
                        str(Path(p).relative_to(project_dir))
                        if str(p).startswith(project_dir)
                        else str(p)
                        for p in base_file_list
                    ],
                    "mempalace_tokens": mp_tokens,
                    "mempalace_results": mp_results,
                    "mempalace_sources": mp_sources,
                    "ratio": ratio,
                    "keywords_used": extract_keywords(query_text),
                }
            )

        # Phase 3: Report
        print_report(query_results)

        # Save JSON
        ratios = [qr["ratio"] for qr in query_results if qr["ratio"] is not None]
        summary = {
            "valid_queries": len(ratios),
            "total_queries": len(query_results),
            "median_ratio": median(ratios),
            "mean_ratio": sum(ratios) / len(ratios) if ratios else 0,
            "p95_ratio": percentile(ratios, 95),
        }

        out_path = args.out
        if not out_path:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_path = str(_PROJECT_ROOT / "benchmarks" / f"results_token_delta_{ts}.json")

        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "project": Path(project_dir).name,
            "query_count": len(queries),
            "mine_time_s": round(mine_time, 1),
            "chunk_count": chunk_count,
            "search_tool": "rg" if _RG_PATH else "grep",
            "results_per_query": args.limit,
            "summary": summary,
            "queries": query_results,
        }
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report saved to: {out_path}")

    finally:
        if palace_is_tmp:
            shutil.rmtree(palace_path, ignore_errors=True)


if __name__ == "__main__":
    main()
