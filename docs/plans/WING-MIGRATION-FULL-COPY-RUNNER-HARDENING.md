---
slug: WING-MIGRATION-FULL-COPY-RUNNER-HARDENING
status: completed
authority: non_authoritative
goal: "Ship fail-closed full-copy admission and receipt-bound descendant recovery through the installed CLI."
risk: high
risk_note: "Admission and recovery protect copied storage and excluded originals; proof is limited to disposable fixtures in this task."
files:
  - path: mempalace_code/wing_migration.py
    change: "Own admission ordering, lexical containment, descendant binding, WAL-safe copies, failure handling, and private runtime measurements."
  - path: mempalace_code/cli.py
    change: "Expose the operator as the installed wing-migration subcommand."
  - path: scripts/wing_migration.py
    change: "Retain a thin repository compatibility wrapper without duplicating the implementation."
  - path: tests/test_wing_migration.py
    change: "Retain existing coverage and add behavioral admission, artifact-manifest, descendant, WAL, sanitization, and recovery regressions."
  - path: docs/operations/wing-migration.md
    change: "Document the final private inventory contract, admission boundary, descendant-only rehearsal, evidence, and receipt-bound recovery."
acceptance:
  - id: AC-1
    when: "Disposable fixtures contain dot components, prefix siblings, repeated separators, or copied symlinks targeting excluded originals across collision, protected-row, KG, copy, and runtime paths."
    then: "Canonical lexical component checks select only eligible provenance; physical access refuses unsafe paths without following links or accessing excluded originals."
  - id: AC-2
    when: "Admission receives malformed input, collisions, active or unobservable clients, insufficient disk, existing evidence, mismatched host/filesystem identity, normalized preimages, or owner-sealed installed-package identity."
    then: "It refuses before creating any receipt, report, snapshot, lock, bytecode, runtime, or probe artifact; relevant facts are checked again under the fence, and existing receipts/reports remain byte-identical."
  - id: AC-3
    when: "Admission or pre-mutation runtime/operational validation fails, or a fault interrupts an admitted descendant mutation."
    then: "The command returns sanitized nonzero output; pre-mutation refusals preserve the complete artifact manifest, while admitted interruptions retain private evidence naming one executable receipt-bound recovery command that restores the permitted preimage."
  - id: AC-4
    when: "Rehearsal, collision, every apply interruption, and every recovery interruption run on disposable full-copy fixtures, including retry and parent-authority/baseline drift challenges."
    then: "Every trial uses its own non-hardlinked descendant and receipt; the parent stays unchanged, exact merged retry writes nothing, and changed parent authority or baseline blocks descendant apply/recovery."
  - id: AC-5
    when: "An external KG has a committed WAL-only fact while a descendant is constructed and subsequently recovered."
    then: "The verified SQLite backup/restore path preserves that fact, complete logical KG state, and physical-candidate alias handling without copying only the SQLite main file."
  - id: AC-6
    when: "The installed-runtime probe mines an admitted disposable descendant successfully or reports inconsistent/missing measurements."
    then: "Private evidence retains measured source/destination row and filed-drawer counts, inconsistent evidence refuses, public output omits private diagnostics, and original-path no-op is explicitly unproved."
  - id: AC-7
    when: "The frozen revision completes focused Ruff/format checks, the complete focused module, real synthetic CLI qualification, sanitized incomplete-inventory refusal, and parent-owned final Astra review."
    then: "Checks exit zero, synthetic output retains its authority boundary, incomplete inventory exits nonzero without artifacts or private leakage, and the recorded final review has no unresolved findings; no owner rehearsal or live action is executed."
out_of_scope:
  - "Owner private inventory refresh, owner full-copy rehearsal, original-path mutation/no-op proof, watcher restart, or live rollout."
  - "New dependencies/services/storage owners, MCP registration, and a second migration implementation."
  - "Backlog edits, release qualification, Git finalization, or changing parent model routing."
contract_policy:
  flow: full_spdd
  reason: "Standard task changes storage admission and interruption recovery authority."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Reject unsafe provenance and incomplete authority before artifacts."
      source: "Current backlog AC-1 and AC-2"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Make failures private, bounded, and recoverable after admission."
      source: "Current backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-3
      statement: "Run each trial in an independent parent-bound descendant with WAL-safe KG preservation."
      source: "Current backlog AC-4 and AC-5"
      acceptance_ids: [AC-4, AC-5]
    - id: REQ-4
      statement: "Retain measured private runtime evidence without claiming original-path no-op."
      source: "Current backlog AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-5
      statement: "Qualify the frozen runner with focused checks and the required final review before owner handoff."
      source: "Current backlog AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "Installed migration operator"
      kind: cli
      paths: [mempalace_code/wing_migration.py, mempalace_code/cli.py]
      expected_behavior: "Expose existing commands through mempalace-code; admit only sealed copy authority and operate through isolated descendants."
    - name: "Operation contract"
      kind: internal
      paths: [docs/operations/wing-migration.md]
      expected_behavior: "Specify private evidence fields, current state, allowed action, and concrete recovery invocation for the final runner."
  invariants:
    - id: INV-1
      statement: "Live mode always refuses; installation never grants authority over original paths or watchers."
      applies_to: [mempalace_code/wing_migration.py, mempalace_code/cli.py, docs/operations/wing-migration.md]
    - id: INV-2
      statement: "Preserve exact union, IDs, row multiplicity/schema, source paths/hashes, protected rows, temporal KG selection, sidecars, and unknown-state refusal."
      applies_to: [mempalace_code/wing_migration.py, tests/test_wing_migration.py]
    - id: INV-3
      statement: "Synthetic qualification remains offline with independent model-cache copies and real installed-runtime probes."
      applies_to: [mempalace_code/wing_migration.py, tests/test_wing_migration.py]
    - id: INV-4
      statement: "Private inventories, source content, paths, runtime diagnostics, and executable recovery commands stay outside tracked/public evidence."
      applies_to: [mempalace_code/wing_migration.py, tests/test_wing_migration.py, docs/operations/wing-migration.md]
  risks:
    - id: RISK-1
      risk: "Read-only-looking SQLite/runtime inspection creates WAL/SHM or bytecode before admission."
      mitigation: "Audit transitive I/O and assert complete lstat/content manifests plus artifact-creation spies on every refusal path."
    - id: RISK-2
      risk: "Relocation normalization conceals content drift or resolves an original filesystem path."
      mitigation: "Normalize only explicitly inventoried physical locator fields by lexical components; retain stored provenance and all payloads verbatim."
    - id: RISK-3
      risk: "Descendant recovery accidentally derives fresh authority from mutable parent state."
      mitigation: "Seal parent receipt/inventory identity and baseline once; compare them at apply/recovery boundaries and refuse drift."
    - id: RISK-4
      risk: "A partial operation fails before reporting the actual descendant requiring recovery."
      mitigation: "Persist the bound recovery invocation before first mutation and retain the active descendant receipt on every operational exception."
  verification:
    - id: VER-1
      executor: provider
      command: "python -m pytest -o addopts= tests/test_wing_migration.py -q"
      proves: "Complete focused module exercises all admission predicates, untouched manifests, descendant trials, WAL recovery, measured runtime evidence, real synthetic subprocess, incomplete-inventory refusal, and live refusal."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
    - id: VER-2
      executor: provider
      command: "python -m ruff check mempalace_code/wing_migration.py mempalace_code/cli_commands/wing_migration.py scripts/wing_migration.py tests/test_wing_migration.py"
      proves: "Frozen runner and focused tests satisfy the required Ruff gate."
      acceptance_ids: [AC-7]
    - id: VER-3
      executor: provider
      command: "python -m ruff format --check mempalace_code/wing_migration.py mempalace_code/cli_commands/wing_migration.py scripts/wing_migration.py tests/test_wing_migration.py"
      proves: "Frozen runner and focused tests satisfy the required formatting gate."
      acceptance_ids: [AC-7]
    - id: VER-4
      executor: provider
      command: "mempalace-code wing-migration qualify --mode synthetic"
      proves: "Real standalone CLI emits successful synthetic-only qualification with installed-runtime and offline cache isolation; creates no owner-copy authority."
      acceptance_ids: [AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        executor: provider
        command: "python -m pytest -o addopts= tests/test_wing_migration.py -q"
        proves: "Retains exact union, protected data, frozen KG population, snapshot integrity, retry, interruption recovery, runtime isolation, and public-surface exclusion alongside the new regressions."
        acceptance_ids: [AC-1, AC-3, AC-4, AC-5, AC-6, AC-7]
---

## Design Notes

- Reuse evidence: current `scripts/wing_migration.py` owns inventory, fencing,
  snapshot, apply/recover, runtime probes, and qualification. Archived
  `WING-MIGRATION-EXISTING-DESTINATION-GUARD` records the landed synthetic runner
  and 60 focused tests. Residue `b2d20301c126ddef4b21c785ac3008c8ffbbe670`
  adds full-copy admission/trials in precisely the three planned files; the active
  backlog records 69 focused tests on that residue. These are historical evidence,
  not checks executed during this plan.
- Implementation starts by reusing only those three residue-file deltas against
  its first parent, reconciling with current HEAD through normal file edits.
  Do not pop/apply the whole stash, restore unrelated files, or alter Git state.
  Preserve useful existing behavior and tests; revise assertions that codify the
  reviewed gaps. No parallel runner or new production owner is needed.
- Rule Zero comparison: deleting full-copy support cannot meet acceptance;
  rebuilding duplicates the existing state machine and adds recovery/removal cost.
  Extending the existing owner is the smallest repair. A new module/service/store
  provides no current benefit. Keep the runner, focused tests, and operation doc
  under their existing shared removal lifecycle. The cheapest falsifier is a
  disposable incomplete-inventory subprocess whose entire artifact manifest
  changes or whose output exposes a private sentinel.
- Residue gaps observed: `_full_copy_runtime_identity` imports the package before
  later inventory/collision/evidence gates and seals observed package hashes without
  an owner-provided expected hash set; isolated Python ignores environment-only
  bytecode controls. `_copy_preimage` contains location-dependent state;
  cross-host numeric device inequality is insufficient filesystem provenance.
  `_qualify_full_copy` applies the first rehearsal to the parent itself.
  `_create_full_copy_trial` uses `copy2` for external SQLite and replaces descendant
  identities without binding later recovery to unchanged parent authority.
  `main` catches only `MigrationError` and infers sanitization from potentially
  malformed inputs; receipt-only trial failures must also be sanitized.
- Separate lexical provenance from physical access. Use canonical absolute lexical
  components for stored paths, including prefix-sibling/dot/double-root cases;
  never resolve them. Validate physical ancestors and descendant entries without
  following links before copy, reads, runtime execution, or mutation. Conservatively
  reject unsafe copied symlinks; do not traverse them to classify eligibility.
- Admission has a read-only stage before any artifact-producing operation. Validate
  typed schema, every target/exclusion and existing evidence, current qualification
  host, owner-sealed source host/filesystem/snapshot identity, complete normalized
  preimage, capacity and client observability, and expected installed package and
  distribution hashes before execution. Do not inspect excluded original paths to
  obtain these facts. Compare explicit owner evidence to the copy; missing evidence
  refuses. Document exact fields and normalization algorithm in the operation doc.
- Runtime identity inspection before admission must use static installed-package
  evidence, without package imports or probe artifacts. Use interpreter-level
  bytecode suppression for later isolated subprocesses. SQLite read-only opens
  need explicit WAL/SHM side-effect handling: refuse an unsafe inspection contour
  instead of using immutable mode that drops committed WAL facts. Test the complete
  artifact manifest, including absent paths, lock sidecars, caches and temporary
  files; attempted-and-cleaned writes do not meet pre-admission acceptance.
- Recheck volatile facts under the existing operation fence before snapshot/apply
  or recovery. Initial lock creation itself follows successful read-only admission.
  A race discovered after fencing may only unwind its own newly created lock state;
  it must preserve pre-existing evidence. Distinguish initial no-replace receipt/
  report creation from authorized sealed receipt progress updates and zero-write
  merged retries. Reject stale/duplicate qualification before producing artifacts.
- Interpret AC-3 at the mutation boundary: refused admission and failed validation
  leave the manifest unchanged; an admitted interrupted mutation necessarily retains
  its changed state and recovery evidence. Do not claim unchanged manifests for
  deliberately injected partial writes. Catch expected JSON/type/filesystem/SQLite/
  subprocess failures at public boundaries with fixed sanitized predicates and
  nonzero exit; never leak exception strings or tracebacks. Retain the executable
  command privately before mutating, bound to the active trial rather than the parent.
- Construct the successful rehearsal as a descendant too. Bind each descendant to
  the sealed parent inventory/receipt and baseline, validate this chain at apply and
  recovery, and fail closed on missing, stale, reordered, or contradictory authority.
  Reuse `_sqlite_backup`, integrity checking, and restore proof for external KG
  materialization; keep aliased candidate semantics and independent file identities.
  A WAL-only regression must hold the WAL open so checkpoint-on-close cannot make
  the test pass accidentally. Exercise the actual collision admission on a separate
  challenged descendant, rather than only an in-memory expected-state calculation.
- Extend the existing runtime probe report with actual before/after source and
  destination row counts and filed-drawer counts from real subprocess results.
  Relocated effective mining can file drawers; do not manufacture zero counts or
  equate this with original-path no-op. Preserve the synthetic zero-write predicate
  only where its real baseline establishes it.
- Command context: repository-root `pyproject.toml` supplies pytest/Ruff dev
  dependencies and defaults that exclude slow/network tests. The focused command
  clears `addopts` to cover the entire module without filtering. Use the existing
  MemPalace dev virtualenv interpreter as `python`; this worktree has no `.venv`.
  Prepared canonical offline MiniLM cache is required by the existing synthetic
  CLI test. Missing runtime/cache is a validation blocker, not permission to
  download models or substitute mocked runtime proof. VER-1 and REG-1 share one
  execution result when the diff is unchanged.
- Add disposable private-inventory fixtures and subprocess tests for sanitized
  refusal; do not read or refresh the owner's private inventory in this task.
  Keep all smoke artifacts disposable and clean successful fixtures. Report any
  retained failed fixture privately with its recovery action.
- Parent orchestration owns final review and broad verification. AC-7 requires the
  requested final Astra verdict on the frozen diff in addition to automated evidence;
  automated checks do not substitute for it. The provider does not launch a reviewer
  or override configured routes. Parent must reconcile the requested verdict with
  effective review routing before declaring AC-7 complete. No shell review command
  is invented here. Broad suites, installed/live rehearsal, and release workflows
  were not run in PLAN. No matching incident-class registry exists in this repository;
  this is an isolated maintenance-runner repair, not an Autopilot runtime change.
- Follow-on `WING-MIGRATION-FULL-COPY-QUALIFICATION` owns the private inventory refresh
  and owner rehearsal after this revision lands. There are no human prerequisites
  for implementing and fixture-testing this task. Runner finalization owns staging,
  commits, and bookkeeping; no backlog or package files belong to implementation scope.
