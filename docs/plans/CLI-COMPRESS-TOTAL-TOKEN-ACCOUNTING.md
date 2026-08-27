---
slug: CLI-COMPRESS-TOTAL-TOKEN-ACCOUNTING
status: completed
authority: non_authoritative
goal: "Make compression totals equal the sum of the token estimates displayed for each processed drawer."
risk: medium
risk_note: "The arithmetic change is narrow, but it affects release-blocking CLI output in both dry-run and state-writing modes and must be proven through the installed-wheel contour."
files:
  - path: mempalace_code/cli_commands/query.py
    change: "Accumulate the existing per-drawer original and summary token estimates for the final Total row, while preserving the character-based compression ratio and current storage flow."
  - path: tests/test_cli.py
    change: "Add focused command regressions for exact two-drawer totals, identical dry-run/live accounting, dry-run immutability, and empty/no-drawer boundaries."
  - path: tests/test_cli_golden_scenarios.py
    change: "Extend the existing subprocess golden workflow with compress dry-run and assert that its Total token values equal the sum of its displayed drawer rows in source and installed-wheel modes."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable quality scorecard after the focused regression changes repository metrics."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable quality scorecard from the same canonical owner."
acceptance:
  - id: AC-1
    when: "a two-drawer direct command displays rows of 31t -> 11t and 33t -> 6t"
    then: "the final summary displays Total: 64t -> 17t"
  - id: AC-2
    when: "the same two drawers are compressed once with --dry-run and once in storing mode"
    then: "both modes report the same 64t -> 17t aggregate, dry-run performs no upserts or document changes, and storing mode retains its existing upsert behavior"
  - id: AC-3
    when: "compression receives no drawers or a drawer whose original and compressed token estimates are both zero"
    then: "the command emits the existing bounded no-drawer guidance or a 0t -> 0t total without a division error"
  - id: AC-4
    when: "the freshly built candidate wheel runs the golden CLI workflow through its installed executable from the existing neutral directory"
    then: "compress --dry-run succeeds and its Total original and compressed token values equal the sums of all displayed drawer rows"
out_of_scope:
  - "Changing Dialect compression, count_tokens, compression_stats, per-drawer output, or token-estimation semantics."
  - "Changing the character-based compression ratio, stored compression metadata, batching, filtering, or upsert behavior."
  - "Adding a second summary renderer, aggregation helper, CLI option, persisted field, release gate, or installed-artifact harness."
  - "Updating user documentation because the command shape and documented output contract do not change."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release bug work changes a user-visible CLI accounting result shared by preview and state-writing paths and requires exact-wheel proof."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The Total original and compressed token counts must be the arithmetic sums of the corresponding per-drawer estimates."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Dry-run and storing modes must share aggregate accounting while preserving their existing mutation boundary."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "No-drawer and zero-token inputs must remain bounded and division-safe."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The exact installed candidate-wheel executable must demonstrate internally consistent compression totals from a neutral directory."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Compression command accounting"
      kind: cli
      paths: ["mempalace_code/cli_commands/query.py"]
      expected_behavior: "The existing per-drawer loop accumulates token estimates for one final summary renderer in both dry-run and storing modes."
  invariants:
    - id: INV-1
      statement: "Dialect.compression_stats remains the single source of per-drawer character counts, token estimates, and size ratios."
      applies_to: ["mempalace_code/cli_commands/query.py"]
    - id: INV-2
      statement: "Dry-run continues to open the store read-only and perform no upsert; live mode continues to upsert each compressed drawer with existing metadata."
      applies_to: ["mempalace_code/cli_commands/query.py", "tests/test_cli.py"]
    - id: INV-3
      statement: "The final compression ratio remains based on aggregate original and summary character counts and keeps its current formatting."
      applies_to: ["mempalace_code/cli_commands/query.py"]
    - id: INV-4
      statement: "tests/test_cli_golden_scenarios.py remains the sole source and installed-wheel subprocess scenario owner."
      applies_to: ["tests/test_cli_golden_scenarios.py"]
  risks:
    - id: RISK-1
      risk: "One mode could use the corrected totals while the other retains the stale repeated-character calculation."
      mitigation: "Accumulate token estimates before the mode branch and assert identical totals from dry-run and live invocations."
    - id: RISK-2
      risk: "Replacing all aggregate character accounting could silently change the displayed compression ratio."
      mitigation: "Retain the existing character accumulators exclusively for ratio calculation and assert its formatting remains bounded for zero values."
    - id: RISK-3
      risk: "Source tests could pass while the built wheel still exposes stale behavior."
      mitigation: "Add the consistency assertion to the existing golden scenario that the readiness owner executes through the exact installed-wheel executable from a neutral cwd."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_cli.py::TestCompressTokenAccounting -q"
      proves: "Exact two-drawer sums, shared dry-run/live accounting, dry-run immutability, live upserts, and empty/no-drawer behavior satisfy the direct CLI contract."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_cli_golden_workflow_happy_path -q"
      proves: "The focused source-mode subprocess workflow parses every displayed compression row and confirms that the final token totals equal their sums."
      acceptance_ids: [AC-2, AC-4]
    - id: VER-3
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
      proves: "The canonical readiness owner builds the candidate wheel and runs the extended golden workflow through its absolute installed executable from a disposable neutral directory."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_cli.py::TestReadOnlyNonSearchNoEmbedder::test_compress_dry_run_readonly_non_search_no_embedder tests/test_cli.py::TestCompressLiveRemainsWritable::test_compress_live_remains_writable -q"
        proves: "The corrected accounting leaves dry-run embedder avoidance and live write capability intact."
        acceptance_ids: [AC-2]
      - id: REG-2
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical non-network suite preserves existing CLI, storage, dialect, release, and installed-artifact behavior around the narrow accounting change."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- In `cmd_compress`, retain `total_original` and `total_compressed` character accumulation for `ratio`. Add token-total accumulators beside them and increment those values directly from `stats["original_tokens_est"]` and `stats["summary_tokens_est"]` inside the existing per-drawer loop.
- Remove only the two final `Dialect.count_tokens("x" * total_...)` calls. Render the token accumulators through the existing `Total:` print statement; do not add a helper or second output path.
- Add `TestCompressTokenAccounting` to `tests/test_cli.py`. Use the existing CLI entrypoint with a bounded fake store and deterministic `Dialect` seams so two returned stats rows are exactly `31t -> 11t` and `33t -> 6t`. Exercise dry-run and live mode against the same fixture, assert the same `Total: 64t -> 17t`, assert no dry-run upsert, and assert the existing live upserts.
- In the same focused class, cover a store returning no documents and a single empty document with zero-valued stats. Assert existing next-action output for no drawers and `Total: 0t -> 0t` with a finite ratio for the empty drawer.
- Extend `test_cli_golden_workflow_happy_path` immediately after its existing mine step with `compress --dry-run`. Parse all indented per-drawer `Nt -> Mt` rows separately from the final `Total:` row, require at least two drawer rows, and assert each aggregate equals the corresponding row sum. Also require the existing dry-run marker and keep later search/export evidence to show the preview left the palace usable and unchanged.
- Reuse the installed-golden owner without changing release scripts or workflows. `scripts/release_readiness_gate.py --check` already builds one wheel, invokes the absolute installed executable from a disposable neutral directory, and runs `tests/test_cli_golden_scenarios.py`; the new scenario assertion therefore supplies AC-4 without a parallel install test.
- Command context basis: `pyproject.toml` declares pytest and the repository-root test layout; `scripts/gate_inventory.py` owns the exact readiness and full non-network commands; the golden suite supplies source mode locally and installed mode when `MEMPALACE_TEST_INSTALLED_CLI` is set by readiness.
- No `incident_proof` block applies because this checkout has no `docs/quality/incident-class-registry.yaml` registry matching the runtime fix.
- PLAN did not execute tests, builds, release gates, verification wrappers, or generated-plan validation.
