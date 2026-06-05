---
slug: WATCH-INITIALIZED-ROOT-UX
goal: "Let `mempalace-code watch` handle an initialized project directory directly while preserving parent-directory watch behavior."
risk: medium
risk_note: "Touches watcher startup project selection and user-facing CLI/docs text, but leaves mining, storage, and steady-state watch loops unchanged."
files:
  - path: mempalace_code/watcher.py
    change: "Teach watch_all to recognize when the supplied directory is itself an initialized project, watch that root as a single project, and emit a clearer diagnostic when no initialized root or child projects exist."
  - path: mempalace_code/cli.py
    change: "Update watch argument help so the command advertises both initialized-project and parent-directory inputs."
  - path: README.md
    change: "Clarify Auto-Watch examples and command summary for initialized project roots versus parent directories."
  - path: docs/AGENT_INSTALL.md
    change: "Keep agent install/operator guidance aligned with the expanded watch input contract."
  - path: tests/test_watcher.py
    change: "Add focused watch_all tests for initialized-root happy path, uninitialized-root diagnostic, parent-directory regression, and initialized-root precedence over child scanning."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_initialized_root_is_watched_as_single_project -q` is run"
    then: "watch_all called with an initialized project directory runs the initial mine for that directory, uses its configured wing, and passes that root to watchfiles instead of reporting no child projects"
  - id: AC-2
    when: "`python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_uninitialized_project_root_prints_actionable_init_command -q` is run"
    then: "watch_all called with a project root that has project markers but no mempalace config exits non-zero and prints the exact `mempalace-code init <dir>` command for that root"
  - id: AC-3
    when: "`python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_parent_directory_still_watches_initialized_children -q` is run"
    then: "watch_all called with a non-project parent still discovers initialized immediate child projects and mines each child with its configured wing"
  - id: AC-4
    when: "`python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_initialized_root_takes_precedence_over_child_project_scan -q` is run"
    then: "when the supplied directory is initialized and also contains project-looking children, watch_all treats the supplied root as the single watch target to avoid nested duplicate mining"
  - id: AC-5
    when: "`python -m mempalace_code watch --help | rg 'initialized project|parent directory'` is run"
    then: "CLI help communicates that `watch <dir>` accepts either an initialized project or a parent directory containing initialized projects"
  - id: AC-6
    when: "`rg 'watch .*initialized project|watch .*parent directory|mempalace-code watch <initialized-project>' README.md docs/AGENT_INSTALL.md` is run"
    then: "user-facing docs mention both supported watch input shapes"
out_of_scope:
  - "Changing `detect_projects()` globally or changing `mempalace-code mine-all` root/child discovery semantics."
  - "Adding recursive project discovery below the current immediate-child scan."
  - "Changing watch debounce, disk-budget, backup/recovery, git-ref filtering, stale cleanup, mining, or storage behavior."
  - "Backlog completion, archive metadata, or any docs/BACKLOG.yaml changes."
contract_policy:
  flow: full_spdd
  reason: "Standard UX/CLI behavior change for a watcher entry point with persistent mining side effects."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "`mempalace-code watch <initialized-project>` must watch and mine that project directly."
      source: "backlog description"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Unsupported project-root inputs must fail with an actionable diagnostic naming the correct initialization command."
      source: "backlog description"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Existing parent-directory watch behavior for initialized child projects must remain intact."
      source: "backlog description"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Initialized root handling must avoid nested duplicate targets when children also look like projects."
      source: "edge-case acceptance"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "CLI help and public docs must describe the accepted input shapes."
      source: "UX clarification"
      acceptance_ids: [AC-5, AC-6]
  surfaces:
    - name: "Watcher project selection"
      kind: internal
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "Before scanning children, watch_all identifies an initialized supplied root and builds the project map from that root only; otherwise it uses existing immediate-child detection."
    - name: "Watch diagnostics"
      kind: cli
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "No-target output distinguishes an uninitialized project root from a parent with no initialized child projects and prints the root-specific init command when applicable."
    - name: "CLI help"
      kind: cli
      paths: ["mempalace_code/cli.py"]
      expected_behavior: "The watch positional argument and command help no longer imply that only parent directories are valid."
    - name: "Public watch docs"
      kind: cli
      paths: ["README.md", "docs/AGENT_INSTALL.md"]
      expected_behavior: "Auto-watch examples and command summaries document initialized-root and parent-directory usage consistently."
    - name: "Watcher tests"
      kind: internal
      paths: ["tests/test_watcher.py"]
      expected_behavior: "Focused mocked tests prove root support, diagnostic output, parent scan regression coverage, and initialized-root precedence."
  invariants:
    - id: INV-1
      statement: "`detect_projects()` remains an immediate-child scanner for existing callers."
      applies_to: ["mempalace_code/watcher.py", "mempalace_code/mining/projects.py"]
    - id: INV-2
      statement: "Parent-directory watch continues to ignore uninitialized child projects and still rejects duplicate initialized wings before mining."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-3
      statement: "The watcher still uses configured wing resolution, startup recovery, disk-budget checks, git-ref watch paths, and on-save filtering exactly as before after project selection completes."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-4
      statement: "Documentation changes must not claim recursive discovery or automatic initialization."
      applies_to: ["README.md", "docs/AGENT_INSTALL.md", "mempalace_code/cli.py"]
  risks:
    - id: RISK-1
      risk: "Adding root support through `detect_projects()` would unintentionally change mine-all and other batch discovery behavior."
      mitigation: "Keep the root check local to watch_all or a watch-specific helper and add a parent-directory regression test."
    - id: RISK-2
      risk: "A root project with project-looking children could be mined twice or watch nested paths."
      mitigation: "Make initialized root selection take precedence over child scanning and verify only the root is mined/watched."
    - id: RISK-3
      risk: "The new no-target diagnostic could hide the existing parent-directory guidance."
      mitigation: "Branch diagnostics by root shape: initialized root, uninitialized project root, or plain parent with no initialized child projects."
    - id: RISK-4
      risk: "Docs/help could overpromise support for recursive project discovery."
      mitigation: "Use precise wording: initialized project root or parent directory containing immediate initialized project directories."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_initialized_root_is_watched_as_single_project -q"
      proves: "Initialized root input is accepted and watched/mined as one project."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_uninitialized_project_root_prints_actionable_init_command -q"
      proves: "Uninitialized project-root input fails with an actionable root-specific init command."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_parent_directory_still_watches_initialized_children -q"
      proves: "Existing parent-directory child discovery still works."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_initialized_root_takes_precedence_over_child_project_scan -q"
      proves: "Initialized root selection avoids nested duplicate watch/mining targets."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m mempalace_code watch --help | rg 'initialized project|parent directory'"
      proves: "CLI help describes both accepted watch input shapes."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "rg 'watch .*initialized project|watch .*parent directory|mempalace-code watch <initialized-project>' README.md docs/AGENT_INSTALL.md"
      proves: "Public docs describe both watch input shapes."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_watcher.py::TestWatchAll::test_watch_all_uses_configured_wings tests/test_watcher.py::TestWatchAll::test_watch_all_duplicate_wings_exit_before_initial_mine -q"
        proves: "Existing configured-wing resolution and duplicate-wing guard still run for parent-directory watch."
        acceptance_ids: [AC-3]
      - id: REG-2
        command: "python -m pytest tests/test_miner.py::TestDetectProjects -q"
        proves: "Generic project detection remains an immediate-child scanner and does not start returning the scan root."
        acceptance_ids: [AC-3, AC-4]
      - id: REG-3
        command: "python -m pytest tests/test_watcher.py::TestWatchAllInitialMineRecovery -q"
        proves: "Watch_all startup backup/recovery behavior remains intact after project selection changes."
        acceptance_ids: [AC-1, AC-3]
      - id: REG-4
        command: "python -m pytest tests/test_watcher.py::TestWatchAndMineDiskBudget tests/test_watcher.py::TestOptimizeOnce -q"
        proves: "Disk-budget and optimize behavior around watcher cycles remains unchanged."
        acceptance_ids: [AC-1, AC-3]
      - id: REG-5
        command: "python -m mempalace_code watch --help | rg 'initialized project|parent directory'"
        proves: "The user-facing command help remains aligned with the expanded input contract."
        acceptance_ids: [AC-5]
---

## Problem & Approach

**Problem.** `mempalace-code watch <dir>` only ever scans `<dir>` for *immediate initialized child projects*. Running `watch /projects` correctly discovers and watches the initialized child `/projects/app`, but running `watch /projects/app` — pointing the command at the initialized project directory itself — finds no child projects and reports nothing to watch, with no hint that the directory was already a valid target or how to fix the invocation.

**Approach.** Do both halves of the backlog ask:
1. **Support the initialized root directly.** Before child scanning, `watch_all` checks whether the supplied directory is itself an initialized project; if so it watches/mines that root as a single project (AC-1), taking precedence over any project-looking children to avoid nested duplicate mining (AC-4).
2. **Emit a clear, actionable diagnostic otherwise.** When the supplied directory is an *uninitialized* project root, exit non-zero and print the exact `mempalace-code init <root>` command (AC-2); when it is a plain parent with no initialized children, keep the existing parent-directory guidance (RISK-3). Existing parent-directory child discovery (`watch /projects` → `/projects/app`) is preserved unchanged (AC-3).

The change is scoped to watcher project selection plus user-facing CLI/docs text; `detect_projects()`, mining, storage, and steady-state watch loops are untouched (see invariants and out-of-scope below).

## Design Notes

- Prefer a watch-specific root detector over changing `detect_projects()`. `detect_projects()` is documented and tested as an immediate-child scanner and is also used by `mine-all`; changing it would widen this task beyond the watcher UX issue.
- Root detection should run before child scanning. If the supplied directory has a mempalace init marker, treat it as the explicit single project target. This makes `watch /projects/app` mine and watch `/projects/app`, while `watch /projects` still finds initialized child `/projects/app`.
- Reuse the existing project-map path by constructing the same entry shape that `detect_projects()` returns (`path`, `markers`, `initialized`). Use existing `resolve_wing_for_project()` for the root so configured wing behavior and config parse errors stay identical.
- Use the same project-marker catalog from `mempalace_code.mining.projects` to decide whether a non-initialized supplied root looks like a project. If it does, the diagnostic should name the root and print `mempalace-code init <root>`.
- If the supplied directory is neither initialized nor project-looking, keep the current parent-directory guidance: no initialized projects found under the parent and run init on projects first.
- For an initialized root that also contains project-looking children, do not scan children. Nested duplicate mining is more dangerous than requiring the user to watch the parent directory explicitly when they want a batch.
- Keep watch loop behavior untouched after `project_map` is built: pre-watch backup/recovery, initial incremental mine, duplicate-wing checks for multi-project mode, on-commit `.git/refs/heads` path selection, on-save full-tree watch, disk budget, and optimize behavior should stay as-is.
- Tests should mock `watchfiles.watch`, `mine`, disk-budget/open-store pieces as existing watcher tests do. Avoid real long-running watch loops and avoid embedding/model initialization.
- CLI/docs wording should be compact and precise: `watch <initialized-project>` for one project; `watch <parent-dir>` for immediate initialized child projects. Do not document recursive discovery.
