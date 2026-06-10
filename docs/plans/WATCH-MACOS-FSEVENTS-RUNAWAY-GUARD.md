---
slug: WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD
goal: "Prevent broken macOS watch jobs from monitoring broad uninitialized roots and driving sustained FSEvents or Spotlight churn."
risk: medium
risk_note: "Intentionally tightens the `watch schedule` rendering contract (previously any directory was accepted) and adds startup output in on-save mode; mining, storage, disk budget, and backup/recovery behavior are untouched."
files:
  - path: mempalace_code/watcher.py
    change: "Validate the watch root in render_watch_schedule (refuse uninitialized broad parents, name the init command for uninitialized project roots), add ThrottleInterval to the rendered launchd plist, and in on-save watch_all prune high-churn directories via an extended watchfiles ignore filter plus a pre-start warning."
  - path: mempalace_code/cli_commands/watch.py
    change: "Extend cmd_watch_status to parse and print 'last exit code' and 'runs' from launchctl print output when present, giving operators a crash-loop signal."
  - path: tests/test_watcher.py
    change: "Add TestRenderWatchScheduleRootGuard (refused/allowed root shapes), TestWatchAllHighChurnPrune (on-save prune + warning), a ThrottleInterval assertion in TestRenderWatchSchedule, a TestWatchStatusCli last-exit-code test, and update the existing TestRenderWatchSchedule fallback test to use an initialized root."
  - path: README.md
    change: "Extend the Auto-Watch section with operator recovery commands (launchctl unload/bootout, plist removal) and a minimal crash-loop health check using `mempalace-code watch status`, with placeholder paths only."
acceptance:
  - id: AC-1
    when: "`rg -q '^## Root Cause Class' docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md && ! rg -q '/[U]sers/|/[h]ome/|[.]local/state' docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md` is run"
    then: "this plan contains a named, public-safe root-cause section and no user-home or machine-local absolute paths, hostnames, diagnostic report names, or incident history"
  - id: AC-2
    when: "`python -m pytest tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_uninitialized_parent_root_refused -q` is run"
    then: "render_watch_schedule raises ValueError for a parent directory with no initialized immediate child projects, naming the root and the supported root shapes, so `watch <dir> schedule` exits non-zero via the existing ValueError handling in cmd_watch_schedule"
  - id: AC-3
    when: "`python -m pytest tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_initialized_root_renders_snippet tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_parent_with_initialized_children_renders_snippet -q` is run"
    then: "an initialized project root and a parent containing at least one initialized immediate child project both render the launchd/cron snippet"
  - id: AC-4
    when: "`python -m pytest tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_uninitialized_project_root_names_init_command -q` is run"
    then: "a root with project markers but no mempalace init marker is refused with an error containing the exact `mempalace-code init <root>` command"
  - id: AC-5
    when: "`python -m pytest tests/test_watcher.py::TestWatchAllHighChurnPrune::test_on_save_prunes_skip_dirs_and_warns -q` is run"
    then: "watch_all in on-save mode passes an event filter whose ignore set includes the mining SKIP_DIRS catalog and prints a pre-start warning naming the high-churn directories detected under the watched root"
  - id: AC-6
    when: "`python -m pytest tests/test_watcher.py::TestRenderWatchSchedule::test_darwin_plist_bounds_respawn_with_throttle_interval -q` is run"
    then: "the rendered darwin plist contains a ThrottleInterval key so an installed-but-failing job cannot respawn at launchd's default rapid cadence"
  - id: AC-7
    when: "`rg -q 'launchctl (bootout|unload)' README.md && rg -q 'watch status' README.md` is run"
    then: "the README Auto-Watch section documents operator recovery commands for disabling or fixing a broken watch job and a minimal health check for confirming the watcher is not crash-looping"
  - id: AC-8
    when: "`python -m pytest tests/test_watcher.py::TestWatchStatusCli::test_status_reports_last_exit_code_and_runs -q` is run"
    then: "`mempalace-code watch status` prints the LaunchAgent's last exit code and run count when launchctl print exposes them, giving a runnable crash-loop signal"
out_of_scope:
  - "Backlog completion, archive metadata, or any docs/BACKLOG.yaml changes (bookkeep owns those)."
  - "Changing the on-commit default mode, debounce timing, mining, storage, disk-budget, or backup/recovery behavior."
  - "Auto-installing or auto-removing LaunchAgents, executing launchctl/crontab mutations from the CLI, or any change to the existing `--install` refusal."
  - "Machine-specific Spotlight settings (mdutil or similar) or any platform command that mutates a user's system without explicit operator action."
  - "Unregistering FSEvents for subdirectories of a recursively watched root — watchfiles registers per-root recursive watches; pruning is event-level by design (see Design Notes)."
contract_policy:
  flow: full_spdd
  reason: "Behavior-changing guards on watch schedule generation and watch startup with launchd daemon implications; needs explicit regression coverage of existing watcher contracts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  approved_scope_expansions:
    - path: docs/quality/scorecard.json
      phase: polish
      acceptance_ids: [AC-5]
      reason: "Generated quality scorecard refresh after polish removed dead watcher-test lines; the JSON count mirrors the task-owned tests/test_watcher.py cleanup."
    - path: docs/quality/scorecard.md
      phase: polish
      acceptance_ids: [AC-5]
      reason: "Generated quality scorecard refresh after polish removed dead watcher-test lines; the Markdown count mirrors docs/quality/scorecard.json."
  requirements:
    - id: REQ-1
      statement: "The macOS launchd/watch setup path is investigated and the root cause class documented in a public-safe plan section without private machine paths, hostnames, diagnostic report names, or local incident history."
      source: "backlog acceptance 1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Generated macOS watch jobs refuse broad parent roots that are not initialized MemPalace projects or parents containing initialized projects, with actionable diagnostics."
      source: "backlog acceptance 2"
      acceptance_ids: [AC-2, AC-3, AC-4]
    - id: REQ-3
      statement: "An installed-but-broken watch job must not respawn unbounded at launchd's default rapid cadence."
      source: "backlog acceptance 2 (installed-job half) and summary's sustained-churn concern"
      acceptance_ids: [AC-6]
    - id: REQ-4
      statement: "When a watched root contains high-churn dependency, build, cache, virtualenv, or VCS directories, the watch command prunes their events by default and emits an actionable warning before starting."
      source: "backlog acceptance 3"
      acceptance_ids: [AC-5]
    - id: REQ-5
      statement: "Safe operator recovery commands for a broken watch job and a minimal crash-loop health check are documented and runnable."
      source: "backlog acceptance 5"
      acceptance_ids: [AC-7, AC-8]
    - id: REQ-6
      statement: "The fix stays local-first and public-safe: no Spotlight settings, no private paths, no platform commands that mutate a user's system without explicit operator action."
      source: "backlog acceptance 6"
      acceptance_ids: [AC-1, AC-7]
  surfaces:
    - name: "Schedule root validation"
      kind: cli
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "render_watch_schedule classifies the supplied root (reusing _classify_watch_root and detect_projects) and raises ValueError for uninitialized project roots and for parents with zero initialized immediate children; cmd_watch_schedule's existing ValueError handler turns that into exit 1."
    - name: "Launchd plist hygiene"
      kind: cli
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "The darwin plist keeps KeepAlive/RunAtLoad but adds a ThrottleInterval respawn bound; the linux cron line is unchanged apart from sharing root validation."
    - name: "On-save high-churn pruning"
      kind: internal
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "In on-save mode watch_all builds the watchfiles filter with ignore_dirs extended by the mining scanner SKIP_DIRS catalog and, before watching, warns about high-churn directories found under each watched project root; on-commit mode is untouched."
    - name: "Watch status crash-loop signal"
      kind: cli
      paths: ["mempalace_code/cli_commands/watch.py"]
      expected_behavior: "cmd_watch_status additionally reports 'last exit code' and 'runs' values parsed tolerantly from launchctl print output, omitting the lines when unavailable."
    - name: "Operator recovery docs"
      kind: cli
      paths: ["README.md"]
      expected_behavior: "Auto-Watch documents how to unload/remove a broken LaunchAgent and how to confirm the watcher is healthy versus crash-looping, using placeholder paths only."
    - name: "Watcher tests"
      kind: internal
      paths: ["tests/test_watcher.py"]
      expected_behavior: "Mocked tests cover refused and allowed schedule roots, plist throttle, on-save pruning and warning, and the watch status crash-loop fields, without real watch loops or embedding initialization."
  invariants:
    - id: INV-1
      statement: "On-commit mode (the default) still watches only .git/refs/heads/ per project; its watch paths and filter are unchanged."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-2
      statement: "_classify_watch_root semantics ('initialized'/'project'/'parent') and watch_all's existing startup refusals are unchanged; the schedule guard reuses them rather than forking the classification."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-3
      statement: "The CLI never executes launchctl/crontab mutations; `watch schedule --install` keeps refusing with the owner-action message, and recovery commands appear only as documentation."
      applies_to: ["mempalace_code/cli_commands/watch.py", "README.md"]
    - id: INV-4
      statement: "No Spotlight or other system-settings mutation is added anywhere; all examples in code, docs, and this plan use placeholder paths."
      applies_to: ["mempalace_code/watcher.py", "mempalace_code/cli_commands/watch.py", "README.md", "docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md"]
    - id: INV-5
      statement: "Mining, storage, disk-budget checks, pre-watch backup, and initial-mine recovery flows are untouched."
      applies_to: ["mempalace_code/watcher.py"]
  risks:
    - id: RISK-1
      risk: "Schedule validation breaks workflows that rendered snippets for directories not yet initialized."
      mitigation: "This is the intended guard; the error names the exact `mempalace-code init <root>` fix or the supported root shapes, and tests pin both refused and allowed shapes."
    - id: RISK-2
      risk: "Extending ignore_dirs could prune events from a legitimately named source directory (e.g. a real `build/` package)."
      mitigation: "Reuse the exact SKIP_DIRS catalog the miner already uses — files under those names were never mined, so pruning their events cannot lose minable content."
    - id: RISK-3
      risk: "Operators could read event-level pruning as eliminating FSEvents/Spotlight churn entirely."
      mitigation: "The pre-start warning and docs state that the recursive watch still observes the whole root and recommend the default on-commit mode for high-churn trees."
    - id: RISK-4
      risk: "launchctl print output format varies across macOS versions, breaking the watch status parse."
      mitigation: "Parse tolerantly line-by-line and omit the fields when absent; tests mock multiple output shapes including missing fields."
    - id: RISK-5
      risk: "The existing TestRenderWatchSchedule fallback test uses a bare tmp_path and would fail under the new guard."
      mitigation: "Update it to write an init marker into tmp_path; the assertion about module fallback is unchanged."
  verification:
    - id: VER-1
      command: "rg -q '^## Root Cause Class' docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md && ! rg -q '/[U]sers/|/[h]ome/|[.]local/state' docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md"
      proves: "The root cause class is documented in a named plan section and the plan is free of user-home and machine-local absolute paths."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_uninitialized_parent_root_refused -q"
      proves: "Broad uninitialized parent roots are refused at schedule generation time."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_initialized_root_renders_snippet tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_parent_with_initialized_children_renders_snippet -q"
      proves: "Valid root shapes (initialized project, multi-project parent) still render schedules."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_watcher.py::TestRenderWatchScheduleRootGuard::test_uninitialized_project_root_names_init_command -q"
      proves: "Uninitialized project roots get the exact init command in the refusal."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_watcher.py::TestWatchAllHighChurnPrune::test_on_save_prunes_skip_dirs_and_warns -q"
      proves: "On-save watch prunes SKIP_DIRS events by default and warns before starting."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_watcher.py::TestRenderWatchSchedule::test_darwin_plist_bounds_respawn_with_throttle_interval -q"
      proves: "The darwin plist bounds respawn cadence for installed-but-failing jobs."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "rg -q 'launchctl (bootout|unload)' README.md && rg -q 'watch status' README.md"
      proves: "Operator recovery commands and the minimal health check are documented."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "python -m pytest tests/test_watcher.py::TestWatchStatusCli::test_status_reports_last_exit_code_and_runs -q"
      proves: "watch status surfaces the crash-loop signal fields when launchctl exposes them."
      acceptance_ids: [AC-8]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_watcher.py::TestRenderWatchSchedule -q"
        proves: "Existing schedule rendering (module fallback binary, platform handling) still works once the fallback test uses an initialized root."
        acceptance_ids: [AC-3, AC-6]
      - id: REG-2
        command: "python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot -q"
        proves: "watch_all root classification and initialized-root startup behavior are unchanged by the schedule guard."
        acceptance_ids: [AC-3]
      - id: REG-3
        command: "python -m pytest tests/test_watcher.py::TestWatchAll tests/test_watcher.py::TestWatchScanRuleReload -q"
        proves: "Parent-directory scanning, duplicate-wing guard, and on-save scan-rule reload behavior survive the new on-save filter construction."
        acceptance_ids: [AC-5]
      - id: REG-4
        command: "python -m pytest tests/test_watcher.py::TestWatchAllInitialMineRecovery tests/test_watcher.py::TestWatchAndMineDiskBudget -q"
        proves: "Pre-watch backup/recovery and disk-budget behavior are untouched."
        acceptance_ids: [AC-5]
      - id: REG-5
        command: "python -m pytest tests/test_watcher.py::TestWatchStatusCli -q"
        proves: "Existing watch status output (disk budget, LaunchAgent state, watched root) is preserved alongside the new fields."
        acceptance_ids: [AC-8]
      - id: REG-6
        command: "rg -q 'owner action required: --install' mempalace_code/cli_commands/watch.py"
        proves: "The CLI still refuses to install schedules itself; system mutation remains an explicit operator action."
        acceptance_ids: [AC-7]
      - id: REG-7
        command: "python -m pytest tests/test_watcher.py -q"
        proves: "The full watcher module suite passes with all changes in place."
        acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6, AC-8]
---

## Problem & Approach

**Problem.** A macOS operator can render and install a launchd watch job for *any* directory: `render_watch_schedule()` performs no validation of the watch root before emitting a `KeepAlive=true` + `RunAtLoad=true` plist. If the root is broad and uninitialized (a home directory, or a parent of many repos none of which are MemPalace-initialized), the installed daemon either crash-loops forever under KeepAlive (watch startup correctly exits 1, launchd respawns it) or — in on-save mode — registers a recursive FSEvents watch over a tree full of high-churn directories, driving sustained FSEvents and Spotlight activity.

**Approach.** Guard the three layers where the runaway is created, in order of leverage:
1. **Generation-time guard (REQ-2).** Validate the root in `render_watch_schedule()` using the same classification `watch_all` already applies at startup (`_classify_watch_root` + `detect_projects`): initialized project roots and parents with at least one initialized immediate child render normally; uninitialized project roots are refused with the exact `mempalace-code init <root>` command; plain parents with zero initialized children are refused with the supported root shapes. `cmd_watch_schedule` already maps `ValueError` to exit 1, so no CLI plumbing changes.
2. **Installed-job hygiene (REQ-3).** Add `ThrottleInterval` to the rendered plist so a job that was installed before the guard (or whose root later became invalid) cannot respawn at launchd's default rapid cadence while it keeps refusing to start.
3. **On-save pruning + warning (REQ-4).** In on-save mode, extend the `watchfiles` filter's ignored directories with the mining scanner's `SKIP_DIRS` catalog (dependency, build, cache, virtualenv, VCS-internal names) and emit a pre-start warning naming the high-churn directories actually present under each watched root. On-commit mode (the default) already watches only `.git/refs/heads/` and is untouched.

Recovery and observability close the loop (REQ-5): the README Auto-Watch section gains operator recovery commands (unload/bootout and plist removal — documented, never executed by the CLI) and a minimal health check; `mempalace-code watch status` additionally surfaces `last exit code` and `runs` from `launchctl print` so a crash loop is confirmable with one command.

## Root Cause Class

Public-safe description of the failure class (this section is the AC-1 artifact; examples use placeholders, no private machine paths, hostnames, diagnostic report names, or local incident history):

1. **Unvalidated schedule generation.** `render_watch_schedule()` accepts any directory and renders a launchd plist with `KeepAlive=true` and `RunAtLoad=true`. Nothing checks that the directory satisfies the root shapes `watch_all` will later require (initialized project, or parent with initialized immediate children). An operator following the printed install instructions can therefore install a permanent daemon pointed at a broad uninitialized root such as a home directory or `/path/to/all-repos`.
2. **Startup refusal plus KeepAlive equals crash loop.** `watch_all` correctly refuses invalid roots at startup and exits 1 — but under `KeepAlive=true` launchd restarts the job indefinitely at its default throttle cadence. The rendered plist sets no `ThrottleInterval`, so a misconfigured installed job re-runs Python startup and the project scan every few seconds until an operator intervenes, and nothing in the product tells the operator how to notice or stop it.
3. **Broad recursive FSEvents in on-save mode.** With `--on-save`, `watchfiles` registers a recursive FSEvents watch per project root. High-churn directories (dependency trees, build outputs, caches, virtualenvs, VCS internals) are excluded only by `watchfiles.DefaultFilter`'s narrower built-in list — names like `target`, `.next`, `coverage`, `dist`, `vendor` are not in it — so their event streams reach the process on every build or install, and macOS-level FSEvents/Spotlight activity over the broad root is sustained regardless of Python-side filtering.

## Design Notes

- **Reuse, don't fork, root classification.** The schedule guard calls the existing `_classify_watch_root` and `detect_projects` so generation-time and startup-time judgments can never disagree. The guard lives in `render_watch_schedule()` so every caller (CLI, tests, future surfaces) gets it; the function already raises `ValueError` for bad platforms and `cmd_watch_schedule` already handles it.
- **Be honest about FSEvents scope.** Event-level pruning cannot unregister FSEvents for subdirectories — the recursive watch is per-root. The guard strategy is therefore: refuse bad roots at generation and startup time (eliminates the broad-root case), bound respawn (contains pre-existing installs), and prune events plus warn (reduces process churn and informs the operator). The warning text recommends the default on-commit mode for high-churn trees rather than implying the churn is gone.
- **Prune set = miner skip set.** The on-save ignore extension reuses `SKIP_DIRS` from `mempalace_code/mining/scanner.py`. Files under those directory names are never mined, so suppressing their events cannot drop a re-mine that would have produced drawers; it only removes wasted wakeups.
- **Warning detection is shallow.** Detecting high-churn directories under each watched root scans immediate children only (matching how `SKIP_DIRS` names appear in practice at project top level) — no recursive pre-walk that would itself add startup churn on large trees.
- **ThrottleInterval value.** Use a conservative bound (around 60 seconds). It changes nothing for a healthy long-running daemon (KeepAlive only consults it on exit) and turns a tight crash loop into a slow, observable one.
- **Crash-loop signal parsing.** `launchctl print gui/<uid>/com.mempalace.watch` exposes `runs = N` and `last exit code = N` on current macOS releases; `cmd_watch_status` already runs and parses this output for `state`. Add tolerant line parsing for the two extra fields and omit them when absent — never fail status reporting because the format shifted.
- **Docs stay operator-actioned and public-safe.** Recovery commands (`launchctl unload`/`bootout`, removing the plist from `~/Library/LaunchAgents/`) are documented in README's Auto-Watch section with placeholder paths; the CLI keeps refusing `--install`, and no command in this change executes a system mutation itself.
- **Tests mock as the module's tests already do.** Schedule guard tests build tmp roots with/without init markers and project markers; on-save prune tests mock `watchfiles.watch`, mining, and store opening like `TestWatchAll` does, asserting on the filter's ignore set and captured stdout; status tests mock `subprocess.run` output shapes including missing fields.
