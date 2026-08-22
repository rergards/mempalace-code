---
slug: BENCH-DOTNET
status: completed
authority: non_authoritative
goal: "Add benchmarks/dotnet_bench.py — a standalone R@5/R@10 code retrieval benchmark for a multi-project C#/.NET repository, with 20 known-answer queries across 4 .NET-specific categories (symbol_lookup, cross_project, interface_impl, project_dependency)"
risk: low
risk_note: "Additive only — new script and no changes to existing mempalace modules, tests, or CI. Depends on MINE-CSHARP and MINE-DOTNET being merged (both are done as of the latest commit)."
files:
  - path: benchmarks/dotnet_bench.py
    change: "New benchmark script — accepts --repo-dir (path to pre-cloned .NET repo), mines it into a temp LanceDB palace with the default embedding model, runs 20 known-answer queries, reports R@5/R@10 per category, saves results to benchmarks/results_dotnet_bench_<date>.json. Modeled structurally after embed_ab_bench.py."
acceptance:
  - id: AC-1
    when: "python benchmarks/dotnet_bench.py --repo-dir <path/to/cloned-repo>"
    then: "Script completes without errors and prints a results table with R@5/R@10 per category and overall"
  - id: AC-2
    when: "Benchmark run completes"
    then: "benchmarks/results_dotnet_bench_<date>.json is written with R@5, R@10, per_category scores, per_query detail, chunk_count, embed_time_s, query_latency_avg_ms, index_size_mb"
  - id: AC-3
    when: "All 20 queries are evaluated against jasontaylordev/CleanArchitecture"
    then: "Overall R@5 >= 0.800 (documented baseline; script does not abort below this threshold but prints a WARNING if missed)"
  - id: AC-4
    when: "--validate-queries flag is passed"
    then: "Script mines the repo and checks that each expected_file basename appears in at least one mined drawer's source_file; prints PASS/FAIL per query without running the full retrieval benchmark"
  - id: AC-5
    when: "symbol_lookup category queries are evaluated"
    then: "Queries for named C# classes/enums by description surface the correct .cs file in top-5"
  - id: AC-6
    when: "cross_project category queries are evaluated"
    then: "Queries referencing an interface (Application layer) and its implementation (Infrastructure layer) each surface the expected .cs file in top-5"
  - id: AC-7
    when: "project_dependency category queries are evaluated"
    then: "Queries referencing NuGet packages or project references surface the relevant .csproj file in top-5"
out_of_scope:
  - "KG-based retrieval benchmarking (interface_impl via kg_query) — this task benchmarks vector search only"
  - "Model A/B comparison — single model (all-MiniLM-L6-v2) only; model comparison follows the embed_ab_bench.py pattern if needed later"
  - "Automated repo cloning — user must pre-clone the target repo"
  - "CI integration — no CI changes in this task"
  - "Path-suffix disambiguation for duplicate basenames (e.g., two DependencyInjection.cs files in Application and Infrastructure) — basename matching is consistent with embed_ab_bench.py; a follow-on can add path-suffix support"
  - "Committing results JSON — results are generated on first run after implementation"
---

## Design Notes

### Target repo

Use `jasontaylordev/CleanArchitecture` as the canonical target. This repo is a widely-cited
Clean Architecture template with multiple projects and clear layer separation:

- `src/Domain/` — entities, enums, domain events (no external dependencies)
- `src/Application/` — interfaces, use cases, validators, DTOs (depends on Domain)
- `src/Infrastructure/` — EF Core, Identity, service implementations (depends on Application)
- `src/Web/` — ASP.NET Core API + configuration (depends on Application + Infrastructure)

Each layer is a separate .csproj with ProjectReference to the layer below. The repo has real
`IApplicationDbContext`, `IDateTime`, `IIdentityService` interfaces in Application, with
matching implementations in Infrastructure — making it ideal for cross_project and
interface_impl categories.

Clone and pin to a stable tag (e.g., `v8.0.x`) for reproducible results. Record the commit
hash in the results JSON under `meta.repo_commit`.

### Script structure — follows embed_ab_bench.py exactly

```
mine_project(repo_dir, palace_path) -> (store, chunk_count)
hit_at_k(results_metadatas, expected_files, k) -> bool
run_bench(repo_dir) -> dict
main()
```

`mine_project()` should NOT call `load_config(repo_dir)` on the target repo (it won't have
`mempalace.yaml`). Instead, hardcode:
```python
wing = "dotnet-bench"
rooms = [{"name": "general", "description": "C#/.NET source files"}]
```

Embed model is hardcoded to `"all-MiniLM-L6-v2"` (current default). No `--models` arg needed.

### Query set (20 queries)

All 20 queries target `jasontaylordev/CleanArchitecture`. `expected_files` are basenames —
consistent with `embed_ab_bench.py`. **The implementer MUST run `--validate-queries` against
the actual cloned repo before finalising the query set**, since filename details may differ
across versions.

```python
QUERIES = [
    # ── symbol_lookup ────────────────────────────────────────────
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
    # ── cross_project ────────────────────────────────────────────
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
    # ── interface_impl ───────────────────────────────────────────
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
        "expected_files": ["DependencyInjection.cs"],
        "category": "interface_impl",
    },
    {
        "query": "application layer MediatR pipeline behavior registration assembly scan",
        "expected_files": ["DependencyInjection.cs"],
        "category": "interface_impl",
    },
    {
        "query": "TodoItemCompleted domain event notification handler",
        "expected_files": ["TodoItemCompletedEventHandler.cs"],
        "category": "interface_impl",
    },
    # ── project_dependency ───────────────────────────────────────
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
        "query": "target framework net8 output type WebApplication configuration",
        "expected_files": ["Web.csproj"],
        "category": "project_dependency",
    },
    {
        "query": "Domain class library TargetFramework no external dependencies",
        "expected_files": ["Domain.csproj"],
        "category": "project_dependency",
    },
]
```

### hit_at_k — basename equality (same as embed_ab_bench.py)

```python
def hit_at_k(results_metadatas, expected_files, k):
    top_k = results_metadatas[:k]
    for meta in top_k:
        source = meta.get("source_file", "")
        source_basename = source.rsplit("/", 1)[-1]
        for expected in expected_files:
            if source_basename == expected:
                return True
    return False
```

Note: queries 13 and 14 both expect `DependencyInjection.cs`. In CleanArchitecture, both
`src/Application/DependencyInjection.cs` and `src/Infrastructure/DependencyInjection.cs`
exist. Basename matching will accept either. This is intentional — both are correct answers
for different query phrasings.

### --validate-queries flag

Before running the full benchmark, mine the corpus once and collect all distinct
`source_file` basenames. For each query, check if all entries in `expected_files` appear
in the basename set. Print a per-query PASS/FAIL report. Abort if any are FAIL (the query
set needs adjustment). This replaces the ad-hoc validation that was done manually for
embed_ab_bench.py.

### Results JSON format

Same structure as `benchmarks/results_embed_ab_2026-04-09.json`, plus a `meta` block:

```json
{
  "meta": {
    "date": "2026-MM-DD",
    "repo": "jasontaylordev/CleanArchitecture",
    "repo_commit": "<hash>",
    "embed_model": "all-MiniLM-L6-v2",
    "query_count": 20
  },
  "code_retrieval": {
    "R@5": 0.0,
    "R@10": 0.0,
    "per_category": {
      "symbol_lookup": {"R@5": 0.0, "R@10": 0.0},
      "cross_project":  {"R@5": 0.0, "R@10": 0.0},
      "interface_impl": {"R@5": 0.0, "R@10": 0.0},
      "project_dependency": {"R@5": 0.0, "R@10": 0.0}
    },
    "per_query": [...]
  },
  "performance": {
    "embed_time_s": 0.0,
    "chunk_count": 0,
    "query_latency_avg_ms": 0.0,
    "query_latency_p95_ms": 0.0,
    "index_size_mb": 0.0
  }
}
```

### CLI interface

```
python benchmarks/dotnet_bench.py --repo-dir PATH [--validate-queries] [--out FILE]
```

- `--repo-dir PATH` — required; path to pre-cloned .NET repo
- `--validate-queries` — validate query set against mined corpus, then exit (no benchmark)
- `--out FILE` — override output path (default: `benchmarks/results_dotnet_bench_<date>.json`)

### p95 latency index

Use `sorted(latencies)[int(len(latencies) * 0.95) - 1]` (index `n * 0.95 - 1`, floor) to
avoid the max-equals-p95 issue noted in BENCH-EMBED-AB hardening (F-002). With 20 queries
that is index 18 (0-based), not 19.
