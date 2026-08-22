---
slug: PROJECT-MARKER-GITFILE-SUPPORT
status: completed
authority: non_authoritative
goal: "Detect Git worktree and submodule roots whose .git marker is a safe regular file."
risk: low
risk_note: "The change extends one existing marker branch and preserves the established regular-source guard, directory behavior, and non-Git marker paths."
files:
  - path: mempalace_code/mining/projects.py
    change: "Accept .git as a project marker when it is either an existing directory or a path accepted by the existing regular-source predicate."
  - path: tests/test_miner.py
    change: "Add focused project-discovery coverage for a real linked Git worktree, the equivalent regular .git-file form used by submodules, and the existing .git-directory form."
  - path: tests/test_regular_source_guard.py
    change: "Add bounded non-regular .git marker coverage proving discovery rejects the entry without hanging or blocking sibling discovery."
acceptance:
  - id: AC-1
    when: "project discovery scans a parent containing a linked Git worktree root whose .git entry is Git's regular gitdir pointer file"
    then: "the worktree root is returned as a project with .git in its markers"
  - id: AC-2
    when: "project discovery scans a parent containing an ordinary repository whose .git entry is a directory"
    then: "the repository remains returned as a project with .git in its markers"
  - id: AC-3
    when: "project discovery encounters a candidate whose only .git entry is a FIFO or another non-regular filesystem node alongside a valid sibling project"
    then: "the unsafe candidate is omitted, discovery returns promptly, and the valid sibling is still returned"
  - id: AC-4
    when: "the focused project-discovery checks and the configured non-network repository suite execute after the change"
    then: "both commands exit successfully while covering the regular .git file, .git directory, and unsafe non-regular marker cases"
out_of_scope:
  - "Parsing or validating the contents or target of a regular .git gitdir pointer file."
  - "Changing recursive discovery depth, hidden-directory handling, marker catalogs, initialization detection, or wing derivation."
  - "Changing watcher commit-ref resolution for worktrees or submodules."
  - "Editing backlog metadata or performing runner-owned staging, commits, publication, or finalization."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release correctness work changes project classification at a source-safety boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "A safe regular .git file must identify Git worktree and submodule roots as projects."
      source: "backlog description and AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The existing .git directory marker behavior must remain unchanged."
      source: "backlog description and AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Non-regular .git entries must remain fail-closed and must not block discovery of other candidates."
      source: "backlog description and AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Focused discovery coverage and the configured non-network suite must validate the completed behavior."
      source: "backlog description and AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "multi-project detector"
      kind: internal
      paths: ["mempalace_code/mining/projects.py"]
      expected_behavior: "Classify an immediate child as a project when .git is a directory or safe regular file, while rejecting other .git node types and preserving all other markers."
    - name: "project discovery behavior tests"
      kind: internal
      paths: ["tests/test_miner.py", "tests/test_regular_source_guard.py"]
      expected_behavior: "Prove real worktree detection, equivalent submodule marker handling, ordinary repository compatibility, and fail-closed non-regular marker behavior."
  invariants:
    - id: INV-1
      statement: "Ordinary .git directories continue to identify projects without requiring a file read."
      applies_to: ["mempalace_code/mining/projects.py", "tests/test_miner.py"]
    - id: INV-2
      statement: "Non-Git literal and glob marker behavior, initialized flags, immediate-child scope, and result ordering remain unchanged."
      applies_to: ["mempalace_code/mining/projects.py", "tests/test_miner.py"]
    - id: INV-3
      statement: "FIFO, socket, device, and other non-regular .git entries are never opened or read during marker discovery."
      applies_to: ["mempalace_code/mining/projects.py", "tests/test_regular_source_guard.py"]
  risks:
    - id: RISK-1
      risk: "A broad existence check could accept unsafe .git node types and reintroduce blocking filesystem behavior."
      mitigation: "Reuse is_regular_source_path for the file branch and cover a non-regular .git node with bounded focused tests."
    - id: RISK-2
      risk: "Replacing the .git branch could regress ordinary repository discovery."
      mitigation: "Keep the existing directory predicate as an explicit accepted branch and retain focused .git-directory coverage."
    - id: RISK-3
      risk: "Testing only a hand-written pointer file could miss the actual linked-worktree filesystem shape."
      mitigation: "Create a disposable linked worktree with plain Git commands in the focused test and pass its parent to detect_projects."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_miner.py::TestDetectProjects::test_detect_finds_linked_git_worktree tests/test_miner.py::TestDetectProjects::test_detect_finds_git_file tests/test_miner.py::TestDetectProjects::test_detect_finds_git_dirs tests/test_regular_source_guard.py::test_detect_projects_rejects_non_regular_git_marker_without_blocking -q"
      proves: "A real linked worktree and regular .git-file form are detected, the ordinary directory form remains detected, and an unsafe marker is skipped without blocking a valid sibling."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The exact configured non-network repository suite remains green after the project-marker behavior change."
        acceptance_ids: [AC-2, AC-3, AC-4]
---

## Design Notes

- Keep the change in the existing `PROJECT_MARKERS` loop. For `.git`, accept `marker_path.is_dir()` or `is_regular_source_path(marker_path)`; do not read the pointer contents or introduce a second filesystem helper.
- A regular `.git` file is the shared filesystem form for linked worktrees and submodules. Discovery needs only marker classification, so pointer syntax and gitdir target validation remain Git's responsibility.
- Preserve the explicit directory branch because `is_regular_source_path()` intentionally accepts files only. Preserve the existing helper's `OSError -> False` behavior so disappeared, inaccessible, or malformed filesystem entries are skipped without aborting the parent scan.
- Build the AC-1 fixture through plain Git subprocess commands in a disposable `tmp_path`, then assert both the detected path and `.git` marker. Keep a small hand-written regular gitdir file case to cover the equivalent submodule shape without network or a nested repository dependency.
- Put the FIFO or socket regression beside the existing regular-source fixtures and platform guards. Include a normal sibling marker in the same scan so the test proves fail-closed isolation rather than only an empty result.
- Command context basis: `pyproject.toml` configures pytest discovery under `tests`, `tests/test_miner.py` already owns `TestDetectProjects`, `tests/test_regular_source_guard.py` owns FIFO/socket fixtures, and `CLAUDE.md` defines the exact configured non-network full-suite command.
