---
slug: WING-MIGRATION-EXISTING-DESTINATION-GUARD
status: completed
authority: non_authoritative
goal: "Implement one uninstalled maintenance runner and prove an exact, recoverable wing union on inventoried disposable synthetic fixtures."
risk: high
risk_note: "Multiple independent stores, opaque row IDs, WAL state, temporal eligibility, and interrupted recovery require fail-closed classification; original state is outside mutation authority."
files:
  - path: scripts/wing_migration.py
    change: "Add temporary fixture-bound inventory, snapshot, apply, recover, and qualify commands using existing storage formats."
  - path: tests/test_wing_migration.py
    change: "Add synthetic contract, interruption, isolation, installed-runtime, and subprocess qualification coverage."
  - path: docs/operations/wing-migration.md
    change: "Document private evidence, recovery, retention, removal, and separate full-copy/live authority boundaries."
acceptance:
  - id: AC-1
    when: "Synthetic collision and preflight fixtures exercise duplicate drawer IDs, same-source hash/chunk conflicts within and across wings, equal-content distinct IDs, diary records, malformed/conflicting tiny hashes, entity-name/triple-ID conflicts, temporal facts, scoped/legacy sentinels, stale/wrong-target receipts, active owners, and insufficient disk."
    then: "Invalid inventories refuse before data mutation with named predicates; valid distinct rows and unrelated state retain their exact inventoried multiplicity and values."
  - id: AC-2
    when: "A metadata-rich drawer and committed WAL-visible KG undergo primitive qualification, snapshot/restore, a wing-only update, and unchanged mining through the inventoried installed runtime."
    then: "All drawer fields/schema/vectors except wing survive, committed WAL facts restore, no export/import/add/upsert/re-embedding transport is called, and unchanged mining writes zero file drawers."
  - id: AC-3
    when: "Whole-state restore targets a fresh isolated fixture and faults occur after each mutation stage, each Lance batch, each commit before receipt replacement, and removal/replacement boundaries during recovery."
    then: "Verified snapshots restore exact non-SQLite bytes and logical SQLite preimages, including WAL-dirty targets; known partial states recover under the fence, unknown states refuse, corrupted snapshots refuse before destructive writes, and duplicate apply of merged state writes nothing."
  - id: AC-4
    when: "The complete synthetic rehearsal migrates into a populated destination."
    then: "The exact approved union remains, only approved wing/KG/hash/marker deltas occur, every manual/diary payload and vector survives, obsolete source routing keys are removed, and unrelated rows/configuration/sidecars/KG state remain unchanged."
  - id: AC-5
    when: "The rehearsal queries query_relationship, incoming/outgoing query_entity, timeline, and iter_all_triples, then refreshes destination architecture after dropping an inventoried namespace."
    then: "Current migrated facts resolve under the destination; triple multiplicity and all unapproved fields stay exact; historical facts stay readable; migrated refresh-owned open-ended facts expire with no selected old/legacy sentinel; finite-window facts retain their window and destination sentinel."
  - id: AC-6
    when: "Fixtures place eligible facts in palace-local and default KG candidates, include empty/absent candidates, omit a required candidate, and reuse triple IDs across distinct databases."
    then: "Both derived physical candidates are inventoried independently; eligible candidates are snapshotted/corrected, exclusions have zero-eligible proofs and unchanged fingerprints, and omission or ambiguity blocks before Lance mutation."
  - id: AC-7
    when: "One fixed synthetic repository path is mined into the source, receives destination manual/diary state, migrates using the receipt-bound installed runtime, activates its copied marker, and mines incrementally again."
    then: "Resolver and effective mine select the destination and write zero unchanged file drawers; baseline source hashes/exclusions remain intact without repairs, and destination diary state survives."
  - id: AC-8
    when: "Subprocess tests invoke qualify in synthetic mode, then request full-copy qualification without an owner-supplied inventory."
    then: "Complete synthetic qualification exits zero with synthetic-only evidence; the full-copy request exits nonzero with an explicit missing-inventory predicate and cannot treat synthetic evidence as full-copy acceptance."
  - id: AC-9
    when: "An eligible finite-window fact crosses its temporal boundary after apply or a partial apply and before retry."
    then: "Classification still uses the receipt's frozen instant, eligible IDs, and field transitions, yielding the same merged or partial verdict without new temporal selection."
  - id: AC-10
    when: "The focused checks inspect package entry points/public CLI/MCP registration, qualification artifact lifecycle, and generated recovery guidance."
    then: "The runner has no installed/public entry point; evidence names retention/removal rules and one exact receipt-specific recovery command; failed fixtures are retained, only verified successful disposable fixtures are removed, and original-host/watch state is untouched."
  - id: AC-11
    when: "Apply, recover, or qualification is requested for live targets, an unregistered fixture, overlapping/linked paths, or missing distinct operational authority."
    then: "The runner refuses before mutation and reports separate outstanding original-host/target, snapshot, mutation, marker, rollback, original-path no-op, and later watcher-restart authority; this implementation cannot authorize live execution."
out_of_scope:
  - "Original-host reads requiring private inventory, original-state mutations, marker changes, watcher starts/stops, live migration, and rollout acceptance."
  - "Executing owner-authorized full-copy qualification or claiming it complete."
  - "Public CLI/MCP routes, installed runner entry points, alias stores, databases, services, durable application owners, or application schema/interface changes."
  - "Export/import transport, semantic deduplication, re-embedding, ID rewriting, source hash repair, or unrelated cleanup."
  - "Backlog changes, package/dependency changes, and copying an unlanded candidate implementation unchanged."
contract_policy:
  flow: full_spdd
  reason: "Standard task coordinates a potentially destructive cross-store migration with explicit synthetic-only authority."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Reject collisions and unsafe state before moving an exact identity-preserving union."
      source: "Backlog collision predicates and exact Lance union decision."
      acceptance_ids: [AC-1, AC-2, AC-4]
    - id: REQ-2
      statement: "Fence classification and mutations and recover verified complete snapshots across interruptions."
      source: "Backlog snapshot, receipt, and narrow retry requirements."
      acceptance_ids: [AC-3, AC-9]
    - id: REQ-3
      statement: "Correct both KG candidates using frozen eligibility and preserve all other graph identity/history."
      source: "Backlog KG identity, provenance, and temporal semantics."
      acceptance_ids: [AC-5, AC-6, AC-9]
    - id: REQ-4
      statement: "Prove actual installed-runtime continuity at a fixed fixture repository path."
      source: "Backlog runtime prerequisite and incremental-mine acceptance."
      acceptance_ids: [AC-2, AC-7]
    - id: REQ-5
      statement: "Provide synthetic-only qualification, retained recovery evidence, and fail-closed external authority boundaries."
      source: "Current scope and separate full-copy/live tasks."
      acceptance_ids: [AC-8, AC-10, AC-11]
  surfaces:
    - name: "Temporary fixture-only migration coordinator"
      kind: internal
      paths: [scripts/wing_migration.py]
      expected_behavior: "Coordinate existing stores privately with exact inventories and recovery; no new application owner or public route."
  invariants:
    - id: INV-1
      statement: "Existing LanceStore, KnowledgeGraph, mining sidecar, marker formats, and public entry points retain ownership and interfaces."
      applies_to: [scripts/wing_migration.py]
    - id: INV-2
      statement: "Only explicitly inventoried disposable fixture paths may be mutated; no original-host or watcher mutation is available."
      applies_to: [scripts/wing_migration.py, tests/test_wing_migration.py]
    - id: INV-3
      statement: "IDs, row multiplicity, vectors, historical facts, and every field outside the approved delta remain exact."
      applies_to: [scripts/wing_migration.py]
    - id: INV-4
      statement: "State evidence under a retained fence controls retries and recovery; phase labels and wall-clock reselection confer no authority."
      applies_to: [scripts/wing_migration.py]
  risks:
    - id: RISK-1
      risk: "A cross-store interruption or stale WAL resurrects inconsistent state."
      mitigation: "Canonical SQLite backups, complete snapshots, authenticated component hashes, restartable replacement stages, and exact state-based recovery."
    - id: RISK-2
      risk: "Path aliases or unobserved clients defeat synthetic isolation or fencing."
      mitigation: "Closed fixture inventory, inode/device/link checks, no path overlap, exclusive OperationLock plus process ownership observation, fail closed on unknown observation."
    - id: RISK-3
      risk: "Convenience row APIs hide multiplicity, schema, metadata, or temporal loss."
      mitigation: "Full Arrow/schema and SQL row-multiset fingerprints, direct scoped updates, and independent expected-state assertions."
    - id: RISK-4
      risk: "Checkout imports or repaired hashes manufacture a false incremental no-op."
      mitigation: "Real baseline mine, immutable baseline hashes, isolated installed runtime with package provenance, and subprocess output/state checks."
  verification:
    - id: VER-1
      executor: provider
      command: "python -m pytest tests/test_wing_migration.py -q -o addopts="
      proves: "Focused unfiltered synthetic suite exercises every listed acceptance predicate, including real runner/runtime subprocesses and retained failure artifacts."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        executor: provider
        command: "python -m pytest tests/test_explicit_wing_consistency.py -q -o addopts="
        proves: "Existing explicit-wing consistency remains valid alongside the temporary runner."
        acceptance_ids: [AC-7]
---

## Design Notes

- Scope is three implementation files. Preserve the 11 current backlog acceptance IDs. The runner coordinates existing owners; do not add application support modules or alter production owners to accommodate qualification. If the installed runtime fails its required predicate, report that dependency rather than repairing runtime/hash behavior inside this task.
- Command context: repository-root pyproject.toml declares Python 3.11+, pytest in dev dependencies, tests/ as testpaths, and default network/slow exclusions. Use the project's dev virtualenv Python. The two focused provider-owned commands explicitly clear addopts to avoid silently skipping qualification cases. No broad verification command is claimed here; the parent owns broad checks. PLAN runs no tests, builds, or generated-plan validators.

### Rule Zero and bounded reuse ledger

- LanceStore in mempalace_code/storage.py owns mempalace_drawers. Its canonical Arrow schema and existing typed table access provide the storage primitive; public get/export projections are insufficient for exact full-row proof. Extend privately with underlying Lance update over exact inventoried source IDs, changing only wing. Preserve the complete actual schema, including additional metadata columns, and every physical row. The cheapest falsifier is a duplicated physical ID after snapshot: classification must be unknown, including when payloads are identical.
- mempalace_code/export.py export_drawers selects a fixed metadata list; import_jsonl performs similarity deduplication and the insertion path. Existing tests/test_export.py covers its own transport. Reusing it cannot meet all-column/vector/multiplicity preservation. Do not replace or extend export/import for this task.
- KnowledgeGraph in mempalace_code/knowledge_graph.py owns entities/triples, _in_window, palace_kg_path, DEFAULT_KG_PATH, and query methods. mempalace_code/architecture.py owns namespace_project_source_file; mining/orchestrator.py invokes scoped and legacy invalidation. Archived ARCH-EXTRACTION-WING-SCOPE and current temporal query/invalidation code establish existing ownership. Residual work is private transactional identity correction with frozen ID selection, never add_entity/add_triple transport.
- mining/orchestrator.py owns _tiny_hashes_path/load/save and the incremental source-hash shortcut; mining/projects.py owns resolve_wing_for_project and mempalace.yaml/mempal.yaml marker discovery. Reuse their semantics, but implement strict complete-document validation and atomic dictionary merge privately: forgiving loaders cannot authorize destructive input. Existing explicit-wing tests provide regression coverage.
- backup.py owns generic backup/restore and rollback helpers; operation_lock.py owns exclusive leases and observable owner records. Archived backup/retention work already provides generic backup behavior. The missing guarantee spans both KG candidates, configuration, marker, tiny hashes, full Lance files, frozen eligibility, and interruption-safe recovery. SQLite backup API and OperationLock are reused without modifying their owners. A generic backup alone is not the sealed whole-state snapshot.
- Delete/simplify cannot deliver migration. Extending public migration/export interfaces increases installed authority; a new module/store/service adds lifecycle without a current requirement. One temporary script plus focused tests and operating notes has the smallest removal cost. The backlog explicitly authorizes this private coordinator. No new durable application architecture boundary is introduced. Candidate d17d03c8 is unlanded reference evidence only; current code and stated failure predicates control implementation.

### Inventory, isolation, and receipt

- Expose private inventory, snapshot, apply, recover, and qualify subcommands in the script only. Require an explicit inventory for mutation and a synthetic disposable mode; never infer a target from ambient user defaults. Qualify may create its own synthetic tree, then inventory it before any migration mutation. Derive default KG under the isolated runtime's fixture home; never redirect or inspect the real user's KG. Package/runtime reads may occur outside the fixture, but mutations may not.
- Validate normalized paths, symlink components, devices/inodes, file link counts, complete input types, and expected absence. Reject snapshot/evidence/config/data overlap, including nested destinations, and all external hardlinks. Account for intentionally contained palace-local KG and tiny sidecar as separate inventoried components without double-restoring them. Model missing files explicitly. Reject unknown schema/columns/types that cannot be preserved exactly rather than coercing them.
- Acquire the fixture's explicit OperationLock exclusively before classification in apply/recover and before snapshot. Retain it through every data stage and verification. Independently observe readers/writers using the fixture; fixture clients must be closed/terminated through the test harness, not by a live process-killing route. Unknown process-observation capability or an unobserved client blocks mutation. The lock alone is insufficient. Recheck path ownership/fingerprints under the fence to prevent classify-before-lock races.
- Inventory all affected and unrelated physical Lance rows, complete Arrow schema/types, ID uniqueness, source/chunk groups and hashes within each wing and across the union. Reject protected manual/diary sources that a later ordinary file-owned replacement would overwrite. Equal content with distinct IDs stays distinct. Equal source identities require equal complete grouped chunk/hash inventories; conflicting tiny hashes or malformed unrelated JSON keys block without repair.
- Derive both KG candidates from the exact runtime and palace; record path/inode identity and handle aliasing explicitly as one physical owner. Distinct databases keep independent triple-ID namespaces. For each candidate record eligible IDs or a zero-eligible proof plus complete fingerprint; a non-empty caller list never substitutes for this derivation.
- Seal a versioned private receipt containing target/inventory/approval identity, runtime and runner hashes, configuration, full schema and row multiplicity, source inventories, all preimage/snapshot hashes, expected stage deltas, one frozen KG instant, exact triple IDs and field transitions. Use restrictive permissions, atomic replacement and durable writes. Revalidate it and every snapshot component before destructive actions. Do not treat a self-supplied label or synthetic approval as external operational authority.

### Apply and classification

- First qualify the vector-preserving update and committed-WAL snapshot primitives on a small synthetic fixture. Construct the full rehearsal baseline with a real source-wing mine at one fixed repository path; include tiny files, ordinary chunks, rich metadata, existing destination manual/diary rows, unrelated state, both KGs, and historical/current/future and finite-window facts. Never rewrite preexisting hashes or exclude extra sources to force a no-op.
- Build exact expected whole-state fingerprints and allowed intermediate states before mutation. Classify observed state under the fence as original, merged, partial, or unknown by complete values/multiplicity, not receipt phase. Original permits planned apply; merged returns success without data or receipt writes; known partial remains fenced and restores the snapshot; unknown refuses apply and recovery. An interrupted Lance batch never resumes in place. Distinguish known interruption states from arbitrary mixed or tampered state.
- Apply ordered stages: exact source Lance wing updates; each selected KG transaction; atomic tiny-hash merge/removal of source key; data postconditions; installed-runtime destination proof; copied marker activation last. Within each KG transaction create a missing destination entity using the owner's deterministic identity rule; preserve an existing exact ID/name entity's other fields. Preserve the source entity for history. Reject mismatched ID/name or corrupt duplicate IDs within a physical database.
- Select current in_project triples using the owner's temporal semantics at the frozen instant and proven exact project-root provenance, old scoped sentinel, or legacy sentinel paired with old object. Change only eligible object and approved sentinel source_file. Preserve triple IDs, distinct logical duplicates, confidence, extraction metadata and windows. Keep historical/future/unrelated rows and all unapproved entities exact. Retry never reevaluates eligibility against the new clock.
- Prove the intended installed interpreter and entry point before marker activation, including real package origin/version/code hashes and resolver/effective-mine destination behavior. Use a disposable non-editable install of the intended code and clean subprocess import context; reject PYTHONPATH/checkout substitution. Stage the candidate marker/configuration for a bounded resolver/effective-mine probe without activating the fixed repository marker early. After activation, run the real incremental mine at the fixed baseline path. Report file-drawer writes and compare complete state, rather than relying on a success exit code. Local model setup must already be available; no provider calls, credential access, hidden network fetches, or mocked-runtime substitutes qualify this predicate.

### Snapshot and recover

- Before any data write, check free space for complete copies plus working recovery staging; snapshot Lance files without hardlinks, strict tiny JSON, exact marker/config bytes, and all included KGs. Use SQLite connection.backup after fencing to capture committed WAL-visible state. Record original main/WAL/SHM existence and hashes alongside canonical logical SQL fingerprints. Verify every copied component and prove restore into a fresh explicitly inventoried isolated target.
- Recovery closes handles and revalidates all snapshot hashes before removing data. Use durable receipt-bound staging and atomic installation for non-SQLite components. Treat each SQLite main/WAL/SHM set as one fenced replacement stage, installing the canonical backup main with no stale journal sidecars before reopening. Verify logical preimage for SQLite and exact bytes for all other restored components. Do not promise cross-store atomicity or original physical SQLite page layout.
- Inventory recovery staging and allowed removal/install intermediate fingerprints in advance so interruption after Lance removal or SQLite main removal is recognizable on restart. Retain immutable snapshots until recovery verifies; interrupted recovery must not require the removed original component to exist. Unknown drift still refuses recovery. Include failure injection after each stage/batch, data commit before receipt replacement, every destructive recovery boundary, and receipt replacement itself.

### Qualification and lifecycle

- tests/test_wing_migration.py must exercise real script subprocesses for qualify success/failure and installed-runtime mining, with independent expected multisets and bytes. Mutation tests use only per-test inventoried disposable trees. Collision, path, fencing, snapshot-corruption, and failure-retention tests assert unchanged external sentinels and preimage fingerprints, not merely error text. Test default-KG omission, same-ID rows across separate KGs, unexpected physical duplicate Lance rows, same-wing chunk conflicts, late extra destination rows, and mutation attempted between classification and fence acquisition.
- Synthetic qualify emits explicit scope/status/predicate/evidence paths and a fully expanded receipt-specific recovery command. A full-copy request without owner inventory must fail clearly. Full-copy execution and any live mode remain blocked in this deliverable, even if synthetic qualify passed; do not implement a bypass flag. Separate future work supplies full-copy acceptance and explicit live authorities.
- Operating note records one exact recovery-command template: python scripts/wing_migration.py recover --inventory INVENTORY_PATH --receipt RECEIPT_PATH; runtime output substitutes the receipt-bound absolute interpreter, script, inventory and receipt paths with safe argument quoting. Recovery authority is only the inventoried disposable fixture. Unknown state directs the operator to preserve evidence and refresh inventory under separate authority rather than offering force recovery.
- Private receipts/evidence/snapshots never enter Git. Successful synthetic working fixtures may be removed only after complete verification and a passing summary; failed/partial fixtures and their snapshots/receipts remain with reported locations. Retain failed evidence and snapshots at least 30 days and until recovery or explicit owner disposition, whichever is later; never automatically age-delete unresolved recovery material. Remove this temporary runner and its dedicated tests after the separately authorized migration is accepted and its rollback/retention window closes, or after explicit cancellation. No watcher or original-host operation occurs here.
