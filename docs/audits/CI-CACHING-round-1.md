slug: CI-CACHING
round: 1
date: 2026-05-01
commit_range: 49adab0..HEAD
findings:
  - id: F-1
    title: "Imports placed inside function body in test_offline.py"
    severity: low
    location: "tests/test_offline.py:20,30"
    claim: "The implement diff added `import os` inside the test function and `import pathlib` inside an else branch. This is inconsistent with test_e2e.py (module-level os import) and degrades readability with no benefit — the imports are not conditionally available."
    decision: fixed
    fix: "Hoisted `import os` and `from pathlib import Path` to the module top and use `Path(...)` instead of the deferred `pathlib.Path(...)`, matching test_e2e.py style."
  - id: F-2
    title: "HuggingFace cache key hardcodes the model name"
    severity: info
    location: ".github/workflows/ci.yml:84-87"
    claim: "Cache `path` and `key` both embed `all-MiniLM-L6-v2` literally. If `DEFAULT_EMBED_MODEL` is changed in code without updating the workflow, the workflow will keep caching/looking-for the old model directory while `mempalace fetch-model` downloads the new one. Behavior remains correct (download path simply isn't cached); the cache just becomes a no-op until the workflow string is updated."
    decision: dismissed
    fix: ""
  - id: F-3
    title: "model-tests job only runs on manual workflow_dispatch"
    severity: info
    location: ".github/workflows/ci.yml:67"
    claim: "Model-backed tests are gated to `workflow_dispatch` with `model_tests=true`. They never run on push or pull_request. AC-2 (cache HF model when model-backed tests run) is still satisfied because the cache is exercised whenever the job runs; this is a deliberate scope choice (network-bound tests stay opt-in) consistent with the existing `not needs_network` filter on push/PR."
    decision: dismissed
    fix: ""
  - id: F-4
    title: "pip cache key includes both pyproject.toml and uv.lock"
    severity: info
    location: ".github/workflows/ci.yml:28-30,42-44,58-60,77-79"
    claim: "Workflow installs via `pip install -e ...`, not `uv sync`. Including uv.lock in `cache-dependency-path` means the pip cache is invalidated on uv-only churn even though pip would not consume the lock. In practice both files change together; defensive but slightly over-eager."
    decision: dismissed
    fix: ""
  - id: F-5
    title: "MEMPALACE_TEST_HF_HOME path is trusted without existence check"
    severity: info
    location: "tests/test_offline.py:26-28, tests/test_e2e.py:438-441"
    claim: "When `MEMPALACE_TEST_HF_HOME` is set the test does not mkdir or assert the path exists. In CI the path is created by `mempalace fetch-model` (SentenceTransformer download creates dirs as needed), so this works; locally a developer who sets the var by accident would get the model materialized at that location. The variable name is namespaced (`MEMPALACE_TEST_*`) so accidental collision is unlikely."
    decision: dismissed
    fix: ""
  - id: F-6
    title: "No automated test asserts MEMPALACE_TEST_HF_HOME branch is exercised"
    severity: low
    location: "tests/test_offline.py:25-32"
    claim: "The two-branch logic (CI shared cache vs tmp_path isolation) is wired by env var but no unit test covers the branch selection itself. The branches are short and obvious, and the integration path runs end-to-end on CI dispatch, so the regression risk is low."
    decision: backlogged
    backlog_slug: CI-CACHING-TEST-ENV-BRANCH
totals:
  fixed: 1
  backlogged: 1
  dismissed: 4
fixes_applied:
  - "Hoisted os and pathlib imports to module top in tests/test_offline.py for consistency with test_e2e.py."
new_backlog:
  - slug: CI-CACHING-TEST-ENV-BRANCH
    summary: "Add unit coverage for MEMPALACE_TEST_HF_HOME branch selection in offline test helpers"
