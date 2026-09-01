---
slug: RELEASE-DIRECT-INSTALLED-WATCHER-SIGNALS
status: completed
authority: non_authoritative
goal: "Move watcher signal cleanup into the exact-wheel installed-golden owner while retaining one thin source pytest consumer."
risk: medium
risk_note: "The change is localized to release qualification, but it moves signal-driven process and durable lease evidence across owners and must contain hangs and failures without masking stale ownership."
files:
  - path: scripts/release_readiness_gate.py
    change: "Own and directly execute the SIGTERM/available-SIGHUP watcher scenario in the exact-wheel installed environment, emit one bounded evidence row, and deselect the thin pytest consumer from the transitional suite."
  - path: tests/test_cli_golden_scenarios.py
    change: "Replace the watcher signal scenario body with a thin source-mode consumer of the release-gate-owned scenario while preserving its public test name."
  - path: tests/test_release_readiness_gate.py
    change: "Cover direct watcher orchestration, both supported signal branches, fail-closed cleanup, sanitized recovery output, row propagation, exact-wheel ordering, and pytest deselection."
  - path: docs/quality/scorecard.md
    change: "Regenerate the deterministic human-readable metrics after ownership movement changes collected source and test structure."
  - path: docs/quality/scorecard.json
    change: "Regenerate the deterministic machine-readable metrics after ownership movement changes collected source and test structure."
acceptance:
  - id: AC-1
    when: "the exact candidate wheel installed-golden command reaches the direct watcher signal scenario from its neutral working directory"
    then: "one production-owned scenario invokes the absolute installed watcher for SIGTERM and available SIGHUP and reports observable ready ownership, exit 0, immediate owner-descriptor removal before later stale-owner pruning, replacement exclusive-writer and watcher availability, healthy storage, semantic search, bounded process cleanup, exact-wheel provenance, and an untriggered network guard"
  - id: AC-2
    when: "the source watcher pytest and the exact-wheel installed-golden command are exercised"
    then: "the pytest test is a thin consumer of the release-gate-owned scenario, the transitional installed pytest subprocess explicitly deselects it, and output shows only one scenario body and one direct runner"
  - id: AC-3
    when: "focused hostile checks, exact-wheel direct qualification, the full non-network regression, configured static gates, diff checks, and the independent Rule Zero, security, and correctness reviews complete"
    then: "all required outputs pass; every scenario failure is one bounded path-safe row with one concrete rerun command; and no push, tag, release, publication, credential access, authentication, or AI-client invocation occurs"
out_of_scope:
  - "Changing watcher product behavior, signal registration, OperationLock behavior, owner-descriptor schema, or storage/search semantics."
  - "Changing fixture shape, the composite workflow, canonical gate inventory, Linux update behavior, dependencies, credentials, AI clients, or publication behavior."
  - "Adding another runner, script, service, persisted state owner, public interface, or architecture boundary."
  - "Editing backlog metadata or performing runner-owned staging, commit, push, tag, release, publication, source verification, or finalization."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task moves ownership of a release-blocking installed-process signal and durable lease scenario across the provider pipeline."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact-wheel installed-golden owner directly executes the complete watcher SIGTERM and available-SIGHUP lease-release scenario and emits one dedicated evidence row."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The named source pytest delegates to the same scenario owner and is excluded from the transitional installed pytest subprocess."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Hostile, exact-wheel, regression, static, diff, and independent review evidence fails closed without credentials, provider clients, or publication actions."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "direct installed watcher signal cleanup gate"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Run both supported shutdown signals through the exact installed watcher lifecycle and return one stable sanitized PASS or FAIL row."
  invariants:
    - id: INV-1
      statement: "Watcher signal registration, graceful shutdown, OperationLock acquisition/release, owner-descriptor shape, health, and search product behavior remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "Owner metadata is inspected after clean process exit and before any later lock acquisition can prune stale state."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "The installed-golden contour continues to use one exact wheel with the watch extra, absolute installed executable and module provenance, credential-free offline environment, neutral cwd, socket guard, shared timeouts, and disposable roots."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-4
      statement: "The source pytest remains callable by its existing name and contains no watcher lifecycle, lease, health, search, or cleanup assertion body."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-5
      statement: "Existing direct scenarios, transitional pytest coverage, fixture shape, gate inventory, workflow, Linux behavior, release commands, and public documentation remain unchanged except for the one required watcher deselection."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-6
      statement: "Qualification performs no external AI-client call, authentication, credential access, push, tag, release, publication, or non-disposable product-data mutation."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "The pytest body could remain executable in the transitional suite, causing the signal scenario to run twice or leaving two owners."
      mitigation: "Move the complete body into one release-gate function, keep only a returned-row assertion in pytest, add its exact name to the existing deselection expression, and assert direct-row ordering in focused tests."
    - id: RISK-2
      risk: "A hung watcher or partial failure could leak a process or reader thread and abort readiness outside its row contract."
      mitigation: "Preserve bounded ready/stop waits and unconditional process/thread cleanup, inject the process boundary for hostile tests, and normalize expected launch, timeout, signal, parse, and filesystem failures through one sanitized row."
    - id: RISK-3
      risk: "A later lock acquisition could reap stale metadata and falsely prove graceful lease release."
      mitigation: "Read operation.lock.owners.json immediately after the signaled watcher exits and before starting the exclusive writer or replacement watcher."
    - id: RISK-4
      risk: "Source-mode success could be mistaken for exact-wheel evidence or a network attempt could escape the direct scenario."
      mitigation: "Run the direct owner only after the existing exact-wheel provenance and socket-guard setup, require an empty network-attempt record before PASS, and keep source pytest as complementary consumer evidence."
    - id: RISK-5
      risk: "Moving code can stale deterministic quality metrics."
      mitigation: "Regenerate only the existing scorecard Markdown and JSON artifacts when their checked metrics change."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_watcher_signal_cleanup_fails_closed tests/test_release_readiness_gate.py::test_installed_golden_uses_watch_extra_provenance_neutral_cwd_and_safe_env tests/test_cli_golden_scenarios.py::test_cli_golden_watcher_signal_cleanup -q"
      proves: "The one gate-owned scenario serves direct and source seams, covers SIGTERM and available SIGHUP, preserves ordering/deselection, and contains hostile launch, ready-timeout, stop-timeout, malformed-owner, nonzero-exit, cleanup, and network-attempt failures in one row."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The configured exact-wheel command directly emits the watcher signal row from the installed console with provenance, neutral-cwd, offline, socket-guard, lease-release, health, and search evidence."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-3
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured full non-network suite preserves watcher, OperationLock, source golden, release orchestration, and unrelated behavior after scenario ownership moves."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The canonical gate inventory and public command surfaces remain unchanged while the existing installed-golden command gains internal watcher evidence."
      acceptance_ids: [AC-2, AC-3]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The planned diff contains no private path, credential-shaped, authenticated-provider, or publication material."
      acceptance_ids: [AC-3]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the moved scenario without a new module, runner, or dependency."
      acceptance_ids: [AC-2, AC-3]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the bounded implementation and tests."
      acceptance_ids: [AC-3]
    - id: VER-8
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts signal enumeration, subprocess injection, owner JSON checks, and evidence-row flow."
      acceptance_ids: [AC-1, AC-3]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The deterministic scorecard matches the reviewed tree after the scenario body moves."
      acceptance_ids: [AC-2, AC-3]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves watcher signal, lease, storage, search, release, and unrelated non-network behavior."
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "No second gate command, mode, inventory entry, or public runner is introduced."
        acceptance_ids: [AC-2, AC-3]
---

## Design Notes

- Rule Zero outcome: extend `scripts/release_readiness_gate.py`, the existing exact-wheel installation and direct-scenario owner. Acceptance is met when it executes the completed watcher scenario once and the named pytest delegates to it. A product change, new module, new runner, or copied scenario creates broader ownership and removal cost.
- Existing owners: `mempalace_code/watcher.py` and `mempalace_code/operation_lock.py` already own completed signal and lease behavior; `scripts/release_readiness_gate.py::_run_installed_golden_wheel` owns exact-wheel provenance, environment, socket denial, timeouts, direct scenarios, and the transitional pytest; `tests/test_release_readiness_gate.py` owns hostile release-gate seams. Keep those boundaries.
- Options considered: deletion loses release proof; retaining pytest as the installed executor fails direct ownership; changing product or adding a shared runner expands scope; moving the scenario into the existing release gate and leaving one thin pytest consumer changes the fewest owners and rolls back as three source/test hunks plus deterministic metrics. The cheapest falsifier is an injected ready watcher whose owner token survives clean exit; the direct helper must return one FAIL row before any replacement lock is acquired.
- Add one stable command label and one `_run_installed_watcher_signal_cleanup_scenario(...)` beside the existing direct scenarios. Accept explicit command prefix, isolated environment, scenario root, neutral cwd, repository root, supported signal list, network-attempt evidence, and injectable subprocess boundaries needed by focused hostile tests. Return one `installed_golden_watcher_signals` row for the complete two-signal matrix.
- Relocate the existing scenario body without retaining a copy. Reuse `_write_fixture_project`, `_run_installed_cli`, `_run_golden_subprocess`, `DEFAULT_TIMEOUT`, `_installed_output_is_clean`, `_make_row`, `_installed_golden_env`, the exact installed console, and the outer temporary root. Keep a bounded gate-local ready-output wait and unconditional process/thread cleanup because streaming readiness must precede signal delivery.
- For each supported signal, initialize and mine disposable state, launch the absolute installed watcher with `--on-save`, require `state=watch-ready`, and record the live PID-owned descriptor tokens. Send the signal, require bounded exit 0 and the normal stop summary, then read the descriptor directly before any later acquisition and require both tokens and PID absent.
- Use the installed console's sibling interpreter to acquire and release one exclusive writer lease. Start a replacement watcher, require ready ownership, stop it through the same signal, require clean exit and immediate descriptor removal, then require healthy nonempty storage and semantic search for the unique fixture marker.
- Run SIGTERM everywhere and append SIGHUP only when the runtime exposes it. Absence of SIGHUP is the supported portability boundary and must neither skip SIGTERM nor produce a false failure.
- The scenario failure boundary covers process launch, ready timeout, stop timeout, unexpected exit, missing or malformed owner JSON, absent/mismatched PID tokens, failed exclusive writer, failed replacement readiness/cleanup, unhealthy storage, failed semantic search, filesystem errors, repository artifacts, and recorded socket attempts. Every branch performs cleanup first and returns one `_make_row`-sanitized detail ending with exactly one `rerun: <installed-golden command>` recovery instruction; no traceback or disposable absolute path escapes.
- Invoke the direct scenario once after installed provenance and the other prerequisite setup, stop immediately on its non-pass row, include its PASS row in the final ordered result list, and check the socket-attempt record before success. Add `not test_cli_golden_watcher_signal_cleanup` to the existing transitional pytest `-k` expression so the wheel never executes the same scenario twice.
- Keep `test_cli_golden_watcher_signal_cleanup` as the source-mode public consumer. It builds the existing `_make_env` and `_CLI`, invokes the release-gate helper once with disposable paths and supported signals, and asserts only the returned row status/detail. Remove its parameterization and lifecycle body; do not alter unrelated watcher fixtures or source golden scenarios.
- Extend `_stub_direct_golden_scenarios` and the successful exact-wheel orchestration assertion with the watcher row and deselection. Add one focused hostile matrix around the direct helper, using injected process/subprocess boundaries and fake owner files; assert bounded cleanup, one row, one rerun command, sanitizer behavior, no repository artifacts, and no duplicate invocation.
- Preserve fixture contents, direct-scenario order outside the new row, installed wheel `[watch]` installation, neutral cwd, credential-free environment, provenance, socket guard, global timeouts, and all adjacent gate behavior. No product file, workflow, inventory, dependency, release document, or backlog file changes.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` if the existing scorecard writer reports changed metrics after the move; retain no temporary output.
- Command context basis: `pyproject.toml` declares pytest, Ruff, Pyright, and the watch extra; `scripts/gate_inventory.py` owns the exact configured commands in VER-2 through VER-9; `.claude/skills/verify/INSTRUCTIONS.md` confirms they run from the repository root. PLAN inspected metadata only and did not execute tests, builds, gates, wrappers, or validation.
- `docs/quality/incident-class-registry.yaml` is absent from the discovered repository filenames, so no incident-class proof block applies. The task moves release-test ownership and does not change runtime behavior or a registry-class routing/profile surface.
- Independent Rule Zero, security, and correctness reviews remain runner-owned next phases. Diff/finalization checks remain parent-owned; this provider does not turn them into an unowned shell row.
