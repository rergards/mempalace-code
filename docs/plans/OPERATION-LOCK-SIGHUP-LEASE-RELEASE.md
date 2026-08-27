---
slug: OPERATION-LOCK-SIGHUP-LEASE-RELEASE
status: completed
authority: non_authoritative
goal: "Make installed watchers handle POSIX SIGHUP through the existing graceful shutdown and lease-release lifecycle."
risk: medium
risk_note: "The change is small but affects long-running signal handling and durable cross-process ownership; incomplete restoration or weak subprocess proof could leave false owners or alter unrelated signal semantics."
files:
  - path: mempalace_code/watcher.py
    change: "Consolidate the duplicated watcher shutdown-handler lifecycle and register POSIX SIGHUP beside SIGTERM so both watch entry points stop through their existing event, finally restoration, and OperationLock lease context."
  - path: tests/test_watcher.py
    change: "Replace the permissive SIGTERM-only seam with focused coverage that both watcher entry points register and restore SIGTERM/SIGHUP through the shared shutdown event while preserving unrelated signal behavior."
  - path: tests/test_cli_golden_scenarios.py
    change: "Add a parameterized real-subprocess watcher scenario for SIGTERM and SIGHUP that proves clean exit, immediate owner-descriptor removal, exclusive-writer and watcher restart availability, and healthy/searchable palace poststate in source and exact-installed modes."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable quality scorecard after the accepted watcher tests."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable quality scorecard after the accepted watcher tests."
acceptance:
  - id: AC-1
    when: "the installed watcher reaches WATCH_RUN state=watch-ready and receives SIGTERM or POSIX SIGHUP"
    then: "each signal stops the process within the bounded timeout with exit status 0 and the normal watch-stopped summary from the shared cleanup path"
  - id: AC-2
    when: "operation.lock.owners.json is inspected after watch-ready and again immediately after each signaled process exits, before any later lock acquisition"
    then: "the live watcher PID is present before the signal and absent after exit for both SIGTERM and SIGHUP"
  - id: AC-3
    when: "the signal poststate is clean and the installed package immediately attempts an exclusive writer lease followed by a new watcher start"
    then: "the writer acquires and releases the exclusive lease, and the replacement watcher reaches watch-ready without stale-owner reaping being needed"
  - id: AC-4
    when: "health --json and semantic search run against the interrupted watcher's palace after each signal"
    then: "health exits successfully with valid storage state and search still returns the pre-mined unique fixture result"
  - id: AC-5
    when: "the exact-wheel installed-golden gate executes the signal scenario"
    then: "the watcher command is the freshly installed absolute console executable, installed module provenance remains outside the checkout, and owner metadata poststate is inspected directly"
out_of_scope:
  - "Changing OperationLock owner schema, stale-owner pruning, live-owner exclusion, or lease acquisition/release semantics."
  - "Treating SIGINT, SIGQUIT, SIGUSR1, or arbitrary signals as graceful watcher shutdown requests."
  - "Changing watcher debounce, mining, backup/recovery, optimization, health, search, scheduler, or update behavior."
  - "Adding a second installed-package harness or editing release workflow, gate inventory, release documentation, backlog metadata, or archives."
contract_policy:
  flow: full_spdd
  reason: "Standard pre-release runtime fix crosses POSIX signal delivery, long-running watcher shutdown, durable lock metadata, and exact-installed subprocess validation."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "SIGTERM and POSIX SIGHUP must stop installed watchers promptly through one graceful shutdown path."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Graceful signal exit must remove the watcher's durable owner record before process termination completes."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "A writer and replacement watcher must be able to start immediately after either graceful signal."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Signal interruption must leave palace health and semantic retrieval valid."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Behavioral proof must run the freshly installed executable and inspect owner metadata before another acquisition can reap stale state."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Watcher shutdown signal lifecycle"
      kind: internal
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "Both single-project and multi-project watcher loops install the same bounded SIGTERM/SIGHUP event handler on POSIX, restore prior handlers in finally, return normally, and let the existing outer lease context remove ownership metadata."
  invariants:
    - id: INV-1
      statement: "OperationLock remains the sole owner of advisory locking, live-owner exclusion, owner metadata mutation, stale-owner pruning, and idempotent lease release."
      applies_to: ["mempalace_code/watcher.py", "mempalace_code/operation_lock.py"]
    - id: INV-2
      statement: "SIGINT continues through the existing KeyboardInterrupt path, and signals other than SIGTERM/SIGHUP retain their prior behavior."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-3
      statement: "Both watcher entry points restore every replaced signal handler even when watchfiles iteration raises or shutdown is repeated."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-4
      statement: "The exact-wheel readiness owner and tests/test_cli_golden_scenarios.py remain the only installed-golden installation and scenario harnesses."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "Adding SIGHUP separately to two loops could preserve divergent setup or restoration behavior."
      mitigation: "Move registration and restoration into one watcher-owned internal lifecycle reused by watch_and_mine and watch_all."
    - id: RISK-2
      risk: "A test that acquires another lock before inspecting metadata could hide the defect through existing stale-owner pruning."
      mitigation: "Read operation.lock.owners.json immediately after process exit and before the writer or replacement watcher starts."
    - id: RISK-3
      risk: "Source-mode subprocess success could be mistaken for installed-package proof."
      mitigation: "Retain source-mode coverage, then require the existing exact-wheel gate and its absolute executable/module provenance for AC-5."
    - id: RISK-4
      risk: "Referencing SIGHUP on a platform without it could break import or watcher startup."
      mitigation: "Register SIGHUP only when the runtime exposes the POSIX signal; SIGTERM behavior remains portable and unchanged."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_watcher.py::TestWatcherShutdownSignals -q"
      proves: "Focused signal seams cover shared SIGTERM/SIGHUP registration, event delivery, restoration for both watcher entry points, repeated shutdown, and the unrelated-signal boundary."
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_cli_golden_watcher_signal_cleanup -q"
      proves: "The real source-mode subprocess scenario observes clean signal exit, immediate owner poststate, exclusive and watcher reacquisition, health, and semantic search for both supported signals."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The existing CI-owned exact-wheel contour installs the watch extra, proves absolute executable and installed-module provenance, and runs the same signal/poststate scenario against the fresh wheel."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_operation_lock.py tests/test_watcher.py::TestWatcherOperationLease -q"
        proves: "Existing shared/exclusive exclusion, stale-owner pruning, idempotent release, and watcher lease release remain intact without changes to operation_lock.py."
        acceptance_ids: [AC-2, AC-3]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_watcher.py::TestWatcherShutdownSignals tests/test_cli_golden_scenarios.py::test_cli_golden_watcher_signal_cleanup -q"
        proves: "The focused unit and real-subprocess contours agree on clean SIGTERM/SIGHUP behavior while preserving the established watcher lifecycle."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Reuse `_with_watcher_lease` unchanged. Its `with lease` block already guarantees `OperationLease.release()` after either watcher entry point returns or raises; graceful signal handling only needs to make SIGHUP drive the normal return path.
- Consolidate the duplicated SIGTERM registration/restoration in `watch_and_mine()` and `watch_all()` into one small internal lifecycle in `mempalace_code/watcher.py`. It should create or receive the existing `threading.Event`, capture prior handlers, register one event-setting callback for SIGTERM plus SIGHUP when available, and restore every captured handler in `finally`.
- Keep handler work signal-safe and idempotent: set the event only. Do not write owner metadata, print, close the lease, raise, or call process-exit functions inside the handler.
- Preserve the existing ordering: acquire the shared lease before watcher startup, install handlers before emitting `watch-ready`, let `watchfiles.watch(..., stop_event=shutdown_event)` return, restore handlers, print the normal shutdown summary, return through the decorator, then release the lease and remove its owner token.
- If handler registration fails partway, restore any handler already replaced before propagating the error. This avoids leaving a partially modified host process when the API is embedded rather than run as the CLI.
- Keep the existing `KeyboardInterrupt` handling. Do not register SIGINT or broaden the graceful set beyond SIGTERM and available SIGHUP.
- In `tests/test_watcher.py`, use the existing mocked watcher patterns to prove both entry points consume the shared lifecycle and restore original handlers. Replace the old subprocess assertion that accepted killed-by-SIGTERM return codes; that assertion cannot prove cleanup.
- Add one parameterized scenario to `tests/test_cli_golden_scenarios.py`; do not create another script or suite. Initialize and mine a disposable project, start `[*_CLI, --palace, ..., watch, ..., --on-save]`, wait for the current run's `watch-ready`, and assert the owner descriptor contains that process PID before signaling.
- After `wait()` returns 0, inspect the descriptor directly before invoking any command that acquires a lock. Require the PID/token to be absent and the normal shutdown summary to be present; this distinguishes graceful lease release from next-start stale reaping.
- Prove immediate writer availability with the installed executable's sibling interpreter in installed mode (and the current interpreter in source mode) importing the same package to acquire/release one exclusive `OperationLock` lease at the isolated HOME path. Then launch a replacement watcher, require `watch-ready`, and stop it through the same supported graceful path.
- Run `health --json` and semantic `search` against the already mined palace after each signal. Assert successful health/storage output and the unique fixture marker in search output so signal cleanup cannot mask storage corruption or retrieval regression.
- Reuse `_assert_installed_cli_provenance`, `_CLI`, `_make_env`, watcher output queues/timeouts, and the exact-wheel readiness harness. AC-5 is satisfied only by the installed-golden execution with `MEMPALACE_TEST_INSTALLED_CLI`; source-mode execution is complementary regression evidence.
- Command context basis: `pyproject.toml` declares Python 3.11+, pytest, and the `watchfiles` extra; `.github/workflows/ci.yml` builds one wheel and invokes the exact command in VER-3; `scripts/release_readiness_gate.py` installs that wheel with `[watch]`, supplies the absolute console path, runs `tests/test_cli_golden_scenarios.py` from a neutral cwd, and checks installed provenance.
- The incident-class registry is absent from the current tracked tree, so this plan adds no `incident_proof` block. The runtime fix remains covered by direct source and exact-installed behavioral evidence.
- PLAN did not execute tests, builds, release gates, verification wrappers, or generated-plan validation.
