---
slug: BENCH-DOTNET-CI-GATE
goal: "Add a GitHub Actions .NET retrieval benchmark gate that fails when overall R@5 is below the configured threshold and always publishes the JSON report."
risk: medium
risk_note: "The implementation is small, but the documented pinned-corpus baseline is R@5=0.600 while the requested gate threshold is 0.800, so enabling the gate before retrieval quality improves will intentionally fail CI."
files:
  - path: .github/workflows/dotnet-bench.yml
    change: "New workflow for pull_request, push to main, and workflow_dispatch; skip pull requests labeled skip-bench; install the package with benchmark dependencies; fetch jasontaylordev/CleanArchitecture at the pinned commit 5a600ab8749c110384bc3bd436b9c67f3067b489; run query validation and the threshold-enforced benchmark; upload the JSON report with actions/upload-artifact using if: always()."
  - path: benchmarks/dotnet_bench.py
    change: "Add threshold-enforced mode for CI, using R5_THRESHOLD=0.800 by default or an explicit CLI value; preserve existing warning-only local behavior unless enforcement is requested; write the JSON report before exiting non-zero; include enough result metadata for the workflow to verify the pinned target commit."
  - path: tests/test_dotnet_bench.py
    change: "Add fast unit tests around the threshold decision, boundary behavior at exactly 0.800, report writing before failure, invalid threshold handling, and commit metadata without mining or embedding a real repository."
  - path: benchmarks/README.md
    change: "Update the .NET benchmark section with the CI gate command, pinned commit, artifact name, skip-bench label behavior, and the current-baseline warning so docs do not imply the gate passes today."
acceptance:
  - id: AC-1
    when: "the dotnet benchmark GitHub Actions workflow runs on a pull request without the skip-bench label or on a push to main"
    then: "the job checks out this repo, fetches jasontaylordev/CleanArchitecture at commit 5a600ab8749c110384bc3bd436b9c67f3067b489, verifies HEAD equals that hash, runs benchmarks/dotnet_bench.py --validate-queries, then runs the benchmark with threshold enforcement and R5_THRESHOLD=0.800"
  - id: AC-2
    when: "python -m pytest tests/test_dotnet_bench.py -k threshold_pass -q runs a stubbed benchmark result with overall R@5 equal to 0.800"
    then: "the command exits 0, writes the JSON report, and records code_retrieval.R@5 as 0.800 rather than treating the exact threshold as a regression"
  - id: AC-3
    when: "python -m pytest tests/test_dotnet_bench.py -k threshold_fail -q runs a stubbed benchmark result with overall R@5 of 0.799 and threshold enforcement enabled"
    then: "the command observes exit code 1 after the JSON report is written and the failure message names the observed R@5 and 0.800 threshold"
  - id: AC-4
    when: "the workflow benchmark step exits non-zero after producing benchmarks/results_dotnet_bench_ci.json"
    then: "the upload-artifact step still runs and publishes an artifact containing benchmarks/results_dotnet_bench_ci.json"
  - id: AC-5
    when: "the workflow runs for a pull request labeled skip-bench"
    then: "the .NET benchmark job is skipped before cloning CleanArchitecture or downloading the embedding model"
out_of_scope:
  - "Improving .NET retrieval quality enough to raise the current pinned-corpus R@5 from 0.600 to 0.800"
  - "Lowering R5_THRESHOLD or resetting the quality target to the current baseline"
  - "Changing the benchmark query set or expected files except where needed to keep existing validation behavior testable"
  - "Adding GitHub branch protection rules or making the workflow required in repository settings"
---

## Design Notes

- Keep `R5_THRESHOLD = 0.800` as the source-of-truth quality target in `benchmarks/dotnet_bench.py`. The workflow should pass the same value through `R5_THRESHOLD` or an explicit `--fail-under-r5 0.800` argument so CI logs show the gate threshold.
- Do not make normal local runs fail by default. Add an opt-in enforcement path for CI so existing documentation examples still produce a report and warning unless the caller asks for a gate.
- Ensure the script writes the JSON output before evaluating the enforced threshold. That makes artifact upload useful even on a failing regression run.
- Fetch the target repository by commit hash, not by trusting a mutable tag checkout. A safe workflow sequence is `git init`, `git remote add origin`, `git fetch --depth=1 origin "$CLEAN_ARCHITECTURE_COMMIT"`, `git checkout --detach FETCH_HEAD`, then compare `git rev-parse HEAD` to the expected hash.
- Use the existing CI style from `.github/workflows/ci.yml`: `actions/checkout@v5`, `actions/setup-python@v6`, Python 3.13, pip cache keyed by `pyproject.toml` and `uv.lock`, and `pip install -e ".[dev,treesitter]"` unless implementation proves a smaller install is sufficient.
- Cache the HuggingFace MiniLM model path like the existing `model-tests` job and run `mempalace-code fetch-model` before the benchmark to reduce repeated CI downloads.
- Use a separate workflow file instead of folding the slow benchmark into the main `Tests` workflow. The benchmark has network, model-cache, and target-repo setup costs that should be easy to identify and skip.
- The `skip-bench` label can be implemented at job level with a pull-request-only label check. Pushes to `main` should not try to inspect pull request labels.
- Unit tests should import `benchmarks/dotnet_bench.py` the same way the existing benchmark tests import scripts. Patch `run_bench`, `get_repo_commit`, and filesystem inputs so tests never mine a real repo or instantiate sentence-transformers.
- The current documented result is expected to fail the new `0.800` gate. Do not hide this by changing the threshold; call it out in `benchmarks/README.md` and leave quality improvement or deliberate threshold reset to a separate task.
