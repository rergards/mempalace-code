---
slug: INGEST-ARCH-FIFO-RACE-GUARD
status: completed
authority: non_authoritative
goal: "Make architecture inventory skip a stale listed source that races to a non-regular node without blocking mining."
risk: medium
risk_note: "The code change is a one-read delegation to an existing owner, but a missed filesystem race can hang the ingest pipeline indefinitely."
files:
  - path: mempalace_code/architecture.py
    change: "Route the inventory pass's existing text read through read_regular_text while preserving its silent OSError skip contract."
  - path: tests/test_architecture_extraction.py
    change: "Add focused delegation and process-bounded real-FIFO regression coverage without changing the existing regular-language extraction cases."
  - path: docs/quality/scorecard.md
    change: "Regenerate the canonical human-readable scorecard after the test inventory changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the canonical machine-readable scorecard after the test inventory changes."
acceptance:
  - id: AC-1
    when: "the focused architecture extraction suite spies on the inventory reader and exercises an OSError from that reader"
    then: "extract_type_inventory performs its single source read through read_regular_text with UTF-8 and errors=ignore, and returns an empty inventory without emitting an error"
  - id: AC-2
    when: "the unchanged regular .cs, .fs/.fsi, .vb, and .py inventory cases run"
    then: "their existing type names, namespaces, and source-file results remain green"
  - id: AC-3
    when: "a listed regular .py path is replaced by a real reader-less FIFO before extract_type_inventory runs in a bounded child process"
    then: "the child returns within the hard bound with an empty inventory"
  - id: AC-4
    when: "the focused architecture and regular-source suites, configured non-network suite, Ruff lint and format, scorecard freshness, and runner diff checks execute"
    then: "all commands exit zero and changed-path output contains only the four planned source, test, and generated scorecard files"
  - id: AC-5
    when: "the completed task's diff and verification evidence are inspected beside RELEASE-DIRECT-INSTALLED-APP-GATE"
    then: "this task contains no CLI-golden or release-gate change and makes no pytest-backed release-qualification claim; direct exact-wheel application qualification remains owned by that separate open task"
  - id: AC-6
    when: "the implementation and verification operation log is inspected"
    then: "it contains no credential access, nonconfigured provider-client call, network access, publication, push, tag, or release action"
out_of_scope:
  - "Changing tests/test_cli_golden_scenarios.py or any release gate, release documentation, or exact-wheel scenario."
  - "Adding a helper, scanner pass, mode, configuration, dependency, service, state owner, public interface, or warning policy."
  - "Changing the broader regular-source guard matrix or any extraction rule, namespace rule, or supported extension."
  - "Editing backlog metadata or performing staging, commits, push, tag, publication, or release work."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release bug fix changes a filesystem-race boundary in the ingest pipeline and must preserve existing extraction and release-qualification ownership."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Architecture inventory must use the existing descriptor-validated regular-source reader and silently skip its OSError failures."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Regular C#, F#, Visual Basic, and Python inventory extraction behavior must remain unchanged."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "A stale listed path replaced by a real FIFO must return no inventory within a hard child-process bound."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Focused owners, configured repository gates, generated scorecard freshness, and task-scoped diff checks must pass."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Direct exact-wheel application qualification remains separate under RELEASE-DIRECT-INSTALLED-APP-GATE, with no CLI-golden or release-gate edit in this task."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Implementation and verification remain local, credential-free, network-free, and non-publishing."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Architecture inventory source read"
      kind: internal
      paths: ["mempalace_code/architecture.py"]
      expected_behavior: "Each supported source is read once through the existing descriptor-validated reader; raced non-regular and unreadable paths are skipped without blocking or diagnostics."
  invariants:
    - id: INV-1
      statement: "Supported extensions, type parsing, namespace derivation, source_file values, result ordering, and public function signatures remain unchanged."
      applies_to: ["mempalace_code/architecture.py", "tests/test_architecture_extraction.py"]
    - id: INV-2
      statement: "Unreadable or missing architecture sources continue to be skipped silently through the existing OSError boundary."
      applies_to: ["mempalace_code/architecture.py", "tests/test_architecture_extraction.py"]
    - id: INV-3
      statement: "Descriptor validation, non-blocking opens, and filesystem race handling remain solely owned by source_io.read_regular_text."
      applies_to: ["mempalace_code/architecture.py"]
    - id: INV-4
      statement: "Release qualification, CLI-golden ownership, scanner behavior, warning policy, configuration, dependencies, and persisted state remain unchanged."
      applies_to: ["mempalace_code/architecture.py", "tests/test_architecture_extraction.py"]
  risks:
    - id: RISK-1
      risk: "A path-only regular-file precheck could retain the TOCTOU window and still block after replacement with a FIFO."
      mitigation: "Delegate the actual read to read_regular_text, whose non-blocking descriptor open and fstat validation own this race."
    - id: RISK-2
      risk: "A FIFO regression could hang the test runner or leave a child alive when the behavior regresses."
      mitigation: "Execute extraction in a bounded multiprocessing child, fail on timeout, and guarantee child termination during cleanup."
    - id: RISK-3
      risk: "Changing the reader could alter decoding or the established silent unreadable-file behavior."
      mitigation: "Pass encoding=utf-8 and errors=ignore unchanged, retain except OSError: continue, spy on the delegated call, and run all existing language cases."
    - id: RISK-4
      risk: "Adding tests can leave the committed deterministic scorecard pair stale."
      mitigation: "Regenerate both canonical scorecard files with their existing writer and run the exact configured freshness command."
  verification:
    - id: VER-1
      owner: provider_owned
      command: "python -m pytest tests/test_architecture_extraction.py tests/test_regular_source_guard.py -q"
      proves: "The complete focused architecture and shared regular-source owners cover delegated OSError handling, unchanged regular-language inventory, the bounded FIFO race, and the existing descriptor-safety matrix without a release-gate test addition."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-2
      owner: configured_runner_owned
      command: "python scripts/quality_scorecard.py --check"
      proves: "The canonical Markdown and JSON scorecards match the implementation tree after the focused test addition."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner_owned
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The exact configured non-network suite preserves ingestion, architecture, CLI, and release-test behavior while the direct exact-wheel contour remains separately owned."
        acceptance_ids: [AC-2, AC-4, AC-5, AC-6]
      - id: REG-2
        owner: configured_runner_owned
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The exact configured lint gate accepts the scoped source and test changes."
        acceptance_ids: [AC-4]
      - id: REG-3
        owner: configured_runner_owned
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The exact configured format gate accepts the scoped source and test changes."
        acceptance_ids: [AC-4]
---

## Design Notes

- Rule Zero: deletion would remove required architecture inventory; a precheck preserves the race; replacing the reader or adding a helper duplicates `source_io`; a new scanner or release scenario crosses owners. Reusing `read_regular_text` at the one current `Path.read_text` call changes one production path, adds no interface or state, and is removed by reverting that import and call.
- Import `read_regular_text` from `mempalace_code.source_io` in `architecture.py` and call it with `encoding="utf-8", errors="ignore"`. Keep the existing `except OSError: continue` exactly as the silent failure owner; do not add classification, warnings, retries, or a second path check.
- Keep all existing regular `.cs`, `.fs`/`.fsi`, `.vb`, and `.py` test bodies unchanged. Add a narrow spy case for the exact delegated call and silent OSError result if existing missing-file coverage cannot observe the reader seam.
- Add exactly one real-FIFO race case under `TestExtractTypeInventory`: create a regular `.py` path and retain it in the input list, replace the directory entry with `os.mkfifo`, invoke `extract_type_inventory` through a bounded multiprocessing primitive, and assert the returned inventory is `[]`. Skip only when the platform lacks FIFO support; ensure timeout cleanup cannot leave a child behind. Do not add a reusable production helper or extend the broader non-regular matrix.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with `python scripts/quality_scorecard.py --write`; the generator owns the deterministic pair and reflects the changed test count.
- Cheapest falsifier: the new real-FIFO case exceeds its child-process bound or returns any inventory. A delegated-reader spy that observes `Path.read_text` behavior or a changed decoding argument also falsifies the selected option.
- Command context basis: all commands run from the repository root. `pyproject.toml` configures pytest defaults and Ruff; `scripts/gate_inventory.py` declares the exact full non-network, Ruff lint, Ruff format, and scorecard commands retained as configured-runner rows. The provider owns one focused, unfiltered command over the two affected behavior owners. Runner finalization separately owns `git diff --check` and changed-path inspection against the four planned files.
- `RELEASE-DIRECT-INSTALLED-APP-GATE` remains the owner for direct exact-wheel application qualification. This task adds no `tests/test_cli_golden_scenarios.py` case, release command, or claim that pytest proves the installed artifact.
- `docs/quality/incident-class-registry.yaml` is absent in this worktree, so no registry-matched `incident_proof` block applies.
- PLAN did not execute tests, builds, release gates, verification wrappers, scorecard generation, diff validation, provider clients, network operations, or publication actions.
