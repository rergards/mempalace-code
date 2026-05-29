---
slug: WATCH-STALE-SWEEP-BULK-DELETE
goal: "Bulk-delete stale watch initial-mine drawers instead of issuing one Lance delete per stale source file"
risk: medium
risk_note: "Touches the incremental stale deletion path and Lance delete predicates; scope is narrow, but source/wing isolation must be preserved for destructive storage operations."
files:
  - path: mempalace_code/storage.py
    change: "Add a bulk source-file deletion API with a LanceStore implementation that counts and deletes all requested source_file values for one wing with a single Lance predicate when possible, while keeping empty/no-match inputs as no-op deletes."
  - path: mempalace_code/mining/orchestrator.py
    change: "Replace the initial full incremental stale-path loop's per-file drawer deletion with the new bulk source-file deletion call, preserving the existing stale-sweep guard, KG invalidation, and tiny-hash cleanup."
  - path: tests/test_storage.py
    change: "Add focused LanceStore bulk-delete tests for multi-source deletion, no-op inputs, quote escaping, and wing scoping."
  - path: tests/test_miner.py
    change: "Add regression coverage proving the incremental stale sweep batches stale drawer deletion while changed-file and full-rebuild deletion paths retain existing behavior."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_miner.py::test_incremental_stale_sweep_deletes_stale_sources_in_one_bulk_call -q` is run"
    then: "a second full incremental scan with multiple stale drawer-backed files calls storage bulk deletion once with the complete stale source set and does not issue one stale drawer delete per stale path"
  - id: AC-2
    when: "`python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_deletes_multiple_source_files_with_one_lance_delete -q` is run"
    then: "multiple source_file values in the target wing are removed by one Lance delete predicate, the returned count matches the removed drawer rows, and non-target rows remain"
  - id: AC-3
    when: "`python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_empty_or_nonmatching_source_files_do_not_delete -q` is run"
    then: "empty input and source files with zero matching rows return 0 and do not call table.delete, avoiding a no-op Lance version"
  - id: AC-4
    when: "`python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_bulk_delete_escapes_quotes_and_stays_wing_scoped -q` is run"
    then: "source_file and wing values containing single quotes are escaped correctly and only rows in the requested wing are deleted"
  - id: AC-5
    when: "`python -m pytest tests/test_miner.py::test_incremental_detects_content_change tests/test_miner.py::test_incremental_full_flag_forces_rebuild -q` is run"
    then: "changed source files and explicit full rebuilds still replace existing drawers without relying on the stale-file sweep path"
out_of_scope:
  - "Changing watch event filtering, debounce timing, startup backup/recovery behavior, or optimize/cleanup scheduling."
  - "Changing chunking, embeddings, source hashing, source_file metadata shape, or Lance table schema."
  - "Bulk invalidating knowledge-graph triples; KG invalidation may remain per stale source because the reported hotspot is Lance drawer deletion versions."
  - "Backlog completion, archive metadata, or any docs/BACKLOG.yaml changes."
contract_policy:
  flow: full_spdd
  reason: "Standard reliability task touching destructive storage behavior in the watcher/miner data path."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The initial full incremental stale-file sweep must delete stale drawer rows through a bulk storage operation, not one storage delete per stale source file."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Bulk stale deletion must preserve existing storage semantics: target wing only, exact source_file matches only, and accurate deleted-row count."
      source: "storage behavior contract"
      acceptance_ids: [AC-2, AC-4]
    - id: REQ-3
      statement: "Bulk stale deletion must not create Lance delete versions for empty or no-match stale sets."
      source: "failure-path acceptance"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Changed-file reindexing and explicit full rebuild deletion behavior must remain separate from the stale-file sweep optimization."
      source: "regression acceptance"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Storage source deletion API"
      kind: store
      paths: ["mempalace_code/storage.py"]
      expected_behavior: "DrawerStore exposes delete_by_source_files(source_files, wing); LanceStore implements it with one count/delete predicate for the requested source set and wing, while empty/no-match inputs do not mutate Lance."
    - name: "Incremental stale sweep"
      kind: internal
      paths: ["mempalace_code/mining/orchestrator.py"]
      expected_behavior: "When incremental mining walks the full file set, stale_paths are sent to the bulk storage API once before KG invalidation and tiny-hash pruning continue with existing guards."
    - name: "Storage regression tests"
      kind: store
      paths: ["tests/test_storage.py"]
      expected_behavior: "Tests prove the Lance bulk-delete predicate removes all requested stale source rows, returns the correct count, skips no-op deletes, escapes quotes, and stays wing-scoped."
    - name: "Miner regression tests"
      kind: internal
      paths: ["tests/test_miner.py"]
      expected_behavior: "Tests prove the stale sweep calls bulk deletion once for multiple stale files and existing changed-file/full-rebuild paths keep replacing drawers correctly."
  invariants:
    - id: INV-1
      statement: "The stale-file sweep only runs when incremental is true and limit == 0."
      applies_to: ["mempalace_code/mining/orchestrator.py"]
    - id: INV-2
      statement: "Per-file delete-then-reindex remains in place for modified files and explicit full rebuilds."
      applies_to: ["mempalace_code/mining/orchestrator.py"]
    - id: INV-3
      statement: "source_file metadata remains an exact absolute-path string and wing scoping remains mandatory for destructive deletes."
      applies_to: ["mempalace_code/storage.py", "mempalace_code/mining/orchestrator.py"]
    - id: INV-4
      statement: "Unsupported or legacy storage backends keep a safe fallback path and are not required to gain Lance-specific predicate behavior."
      applies_to: ["mempalace_code/storage.py"]
  risks:
    - id: RISK-1
      risk: "A malformed IN predicate could delete rows outside the stale source set or target wing."
      mitigation: "Dedupe paths, escape single quotes in every literal, include wing in the same predicate, and cover quote/wing boundaries in storage tests."
    - id: RISK-2
      risk: "An empty stale set could still call table.delete and create a pointless Lance version."
      mitigation: "Return 0 before count/delete for empty input and skip delete when count_rows reports zero matches."
    - id: RISK-3
      risk: "Optimizing the stale sweep could accidentally change modified-file replacement behavior."
      mitigation: "Limit orchestrator changes to stale_paths after the main scan and keep changed-file/full-rebuild regression tests in the verification path."
    - id: RISK-4
      risk: "Very large stale sets could produce a long Lance predicate."
      mitigation: "Keep predicate construction centralized in storage.py so chunking can be added there if Lance rejects a real-world predicate length, without changing miner control flow."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_miner.py::test_incremental_stale_sweep_deletes_stale_sources_in_one_bulk_call -q"
      proves: "The initial incremental stale sweep batches multiple stale source files through one storage call."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_deletes_multiple_source_files_with_one_lance_delete -q"
      proves: "LanceStore bulk deletion removes all requested source rows for one wing with one delete predicate."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_empty_or_nonmatching_source_files_do_not_delete -q"
      proves: "Empty and no-match bulk deletes return 0 without calling table.delete."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_bulk_delete_escapes_quotes_and_stays_wing_scoped -q"
      proves: "Bulk delete predicates safely handle quoted strings and wing isolation."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_miner.py::test_incremental_detects_content_change tests/test_miner.py::test_incremental_full_flag_forces_rebuild -q"
      proves: "Existing modified-file and explicit full-rebuild deletion behavior remains intact."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_miner.py::test_incremental_detects_deletion -q"
        proves: "Deleted files are still absent from storage after an incremental re-mine and keeper files remain indexed."
        acceptance_ids: [AC-1]
      - id: REG-2
        command: "python -m pytest tests/test_storage.py::TestDeleteBySourceFile -q"
        proves: "The existing single-source deletion API still returns counts, handles quotes, and remains wing-scoped for callers outside the stale sweep."
        acceptance_ids: [AC-2, AC-4]
---

## Design Notes

- Keep the current stale-sweep placement: after any pending drawer batch flush and only under `incremental and limit == 0`.
- Add `delete_by_source_files(source_files, wing)` to the storage abstraction with a generic fallback, then implement the Lance path with deduped source paths and one `source_file IN (...) AND wing = ...` predicate.
- Count before deleting and skip `table.delete` when the source set is empty or when the count is zero; this avoids creating no-op Lance versions.
- Do not route modified-file reindexing or `incremental=False` rebuilds through the stale sweep. Those paths delete exactly the source file being reprocessed and should stay easy to reason about.
- Leave KG stale invalidation as a per-source loop for now. It does not create Lance versions, and widening it would add a second destructive API surface outside the reported hotspot.
- Remove stale tiny-hash sidecar entries exactly as today; tiny-only stale files are not present in `existing_hashes`, so they should not trigger a Lance delete.
