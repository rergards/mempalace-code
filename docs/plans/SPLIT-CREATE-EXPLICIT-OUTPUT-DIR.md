---
slug: SPLIT-CREATE-EXPLICIT-OUTPUT-DIR
status: completed
authority: non_authoritative
goal: "Make split preview and apply agree when --output-dir names a new directory."
risk: medium
risk_note: "The change is localized, but it touches directory creation, output replacement safety, partial-failure reporting, source backup behavior, and the release-blocking installed CLI contour."
files:
  - path: mempalace_code/split_mega_files.py
    change: "Extend the existing split owner to create an absent explicit output directory only during apply, refuse replacement of existing output files, and report one bounded retry action while preserving source and target guards."
  - path: tests/test_split_mega_files.py
    change: "Add focused absent-directory dry-run/apply, repeated-apply, directory-target, post-state, and source-preservation coverage alongside the existing hostile-target and partial-write regressions."
  - path: tests/test_cli_golden_scenarios.py
    change: "Add one direct CLI subprocess scenario that exercises the same absent --output-dir through source mode and the existing exact-wheel installed-golden harness and inspects filesystem post-state."
acceptance:
  - id: AC-1
    when: "the direct split CLI previews a valid two-session transcript with --output-dir set to a previously absent path"
    then: "the command exits successfully, reports the planned files, and leaves the output directory absent"
  - id: AC-2
    when: "the direct split CLI applies the same valid transcript and previously absent --output-dir path"
    then: "the command exits successfully, creates that directory and only the planned regular files within it, and renames the source according to the existing .mega_backup contract"
  - id: AC-3
    when: "split apply is repeated where a synthesized output file already exists"
    then: "the command exits nonzero without changing the existing output or source and reports exactly one bounded action to retry with a new empty output directory"
  - id: AC-4
    when: "focused split regression scenarios exercise FIFO, symlink, hardlink, directory targets, partial writes, and source preservation"
    then: "every hostile or conflicting target remains untouched, partial failures remain reported, and the original source is preserved on failure"
  - id: AC-5
    when: "the canonical exact-wheel installed-golden gate runs the direct split scenario with an absent --output-dir"
    then: "the installed console proves dry-run non-creation, successful apply, planned regular-file post-state, and source backup post-state"
out_of_scope:
  - "Changing session-boundary detection, chunk contents, generated filenames, person detection, or timestamp extraction."
  - "Changing the default same-directory output contract or the .mega_backup naming contract."
  - "Adding a helper module, new CLI flag, output mode, release gate, or alternate split command path."
  - "Editing backlog metadata, release bookkeeping, or runner-owned finalization artifacts."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release bug changes user-visible CLI filesystem behavior and must preserve fail-closed output and source-safety contracts through the installed application path."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Dry-run with an absent explicit output directory must remain fully non-mutating."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Apply must create an absent explicit output directory, write only planned regular chunks, and preserve the existing source backup contract."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Repeated apply must refuse existing output files without changing them or the source and must give one bounded recovery action."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Existing non-regular-target, no-follow, partial-failure, and source-preservation protections must remain effective."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The existing exact-wheel golden contour must run the absent-output-directory scenario and inspect its post-state."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "split output directory and file mutation boundary"
      kind: cli
      paths: ["mempalace_code/split_mega_files.py"]
      expected_behavior: "Preview computes output paths without creating the directory; apply creates an absent explicit directory, writes new regular files without replacement, and backs up the source only after complete success."
  invariants:
    - id: INV-1
      statement: "Dry-run creates no directory, output file, or source backup and leaves the source unchanged."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-2
      statement: "Descriptor-capable platforms keep FIFO, symlink, hardlink, directory-target, parent-replacement, no-follow, single-link regular-file, and partial-write checks fail-closed. The documented fallback keeps O_EXCL final-entry protection without claiming parent-path TOCTOU closure."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
    - id: INV-3
      statement: "The source is renamed to .mega_backup only after every planned output for that source is written successfully; any failure leaves the source in place."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-4
      statement: "Omitting --output-dir continues to target the source directory, and split parsing, naming, and chunk content remain unchanged."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
    - id: INV-5
      statement: "The golden CLI harness continues to use a neutral directory, isolated HOME and XDG state, offline execution, and the absolute installed console when configured."
      applies_to: ["tests/test_cli_golden_scenarios.py"]
  risks:
    - id: RISK-1
      risk: "Directory creation could make dry-run mutating or create an empty directory for an input that produces no chunks."
      mitigation: "Create the directory only on the apply path after a valid split is established, and assert absent-directory post-state before and after preview."
    - id: RISK-2
      risk: "A repeated or partially retried split could truncate an existing regular output before failure."
      mitigation: "Keep creation in the existing descriptor owner, use exclusive creation for synthesized files, and assert existing bytes and source state after refusal."
    - id: RISK-3
      risk: "Creating the directory before target checks could leave partial filesystem state or weaken hostile-entry handling."
      mitigation: "Permit only the requested directory plus successfully created regular chunks, retain descriptor-level no-follow and fstat checks, and inspect post-state for success and failure scenarios."
    - id: RISK-4
      risk: "In-process tests could pass while console dispatch or the installed wheel still has divergent behavior."
      mitigation: "Run the same direct subprocess scenario through the existing source and exact-wheel golden harness with executable provenance and filesystem assertions."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_split_mega_files.py tests/test_cli_golden_scenarios.py::test_cli_golden_split_creates_explicit_output_dir -q"
      proves: "Focused unit and direct source-CLI behavior cover absent-directory preview/apply, repeated refusal and recovery text, regular output post-state, hostile targets, partial failure, and source backup preservation."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel gate invokes the installed console from its existing isolated contour and runs the same split absent-directory and post-state scenario."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The configured non-network repository suite retains split parsing, naming, regular-output, hostile-target, partial-failure, source-preservation, and unrelated CLI behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Keep `split_file()` as the sole owner of output-directory lifecycle. Resolve the directory exactly as today. On dry-run, calculate and print the same planned paths without calling `mkdir` or any write primitive. On apply, create the absent explicit directory before the first output write; do not add a second CLI-layer creation path.
- Reuse `_open_regular_output_descriptor()` for output creation and validation. Preserve `O_NOFOLLOW`, `O_NONBLOCK`, `lstat`, `fstat`, regular-file, and single-link checks. Make synthesized output creation exclusive on every supported platform so a pre-existing regular file is refused before truncation as well as FIFO, symlink, hardlink, and directory entries.
- On platforms with directory descriptors, retain one validated output-directory descriptor for the whole split and open every chunk relative to it; reject a symlink or replaced directory path. Where those primitives are unavailable, preserve the documented `O_EXCL` fallback and state its exact boundary: final output entries cannot be replaced, while parent-path TOCTOU containment is unavailable.
- Keep output-directory creation bounded to the requested path. A missing parent, an existing non-directory at the requested path, or another directory-creation error flows through the existing per-source `OSError` handling, leaves the source untouched, and exits nonzero. Do not create unrelated parents or clean up operator-owned entries.
- Reuse the current per-source `progress` list and failure summary. A failure after one chunk still reports the created count, retains that regular chunk for inspection, and leaves the source in place. Do not roll back or overwrite partial outputs.
- For an existing synthesized output, emit one recovery action directing the operator to rerun with a new empty `--output-dir`. Keep the diagnostic bounded and deterministic so repeated commands do not depend on remembered conversational context.
- Extend `tests/test_split_mega_files.py` in place. Cover `split_file()` and `main()` with a previously absent directory, assert dry-run absence, apply contents and directory membership, source-to-backup transition only after success, repeat refusal without byte changes, exactly one recovery action, and the existing hostile/partial failure matrix.
- Add one scenario to `tests/test_cli_golden_scenarios.py`; reuse `_CLI`, `_make_env`, `_run_cli`, `_assert_installed_cli_provenance`, the neutral cwd, and disposable paths. Build a two-session transcript without mining or embeddings, run dry-run then apply against an absent output directory, inspect the exact directory entries, regular-file types and contents, and source backup, then repeat apply against a fresh copy whose synthesized targets already exist to prove refusal and recovery behavior.
- AC-5 is satisfied only when the existing installed-golden gate executes this same test with `MEMPALACE_TEST_INSTALLED_CLI`; source-mode execution is complementary focused evidence.
- Command context basis: `pyproject.toml` declares Python 3.11+, pytest under the `tests` root, and `mempalace-code = mempalace_code:main`; `tests/test_cli_golden_scenarios.py` already selects the absolute installed console when configured; `scripts/gate_inventory.py` owns VER-2 byte-for-byte; project instructions define REG-1 as the configured non-network suite.
- `docs/quality/incident-class-registry.yaml` is absent in this checkout, so this runtime fix has no registry-matched incident-proof block.
- PLAN did not run tests, builds, installed smokes, verification wrappers, or generated-plan validation.
