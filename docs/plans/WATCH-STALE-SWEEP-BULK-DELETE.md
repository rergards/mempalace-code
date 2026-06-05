---
slug: WATCH-STALE-SWEEP-BULK-DELETE
goal: "Bulk-delete stale watch initial-mine drawers instead of issuing one Lance delete per stale source file"
risk: medium
risk_note: "Touches the incremental stale deletion path and Lance delete predicates; scope is narrow, but source/wing isolation must be preserved for destructive storage operations."
files:
  - path: mempalace_code/storage.py
    change: "Add a bulk source-file deletion API (`delete_by_source_files`) with a LanceStore implementation that dedupes the requested source_file values and deletes them in bounded batches — one `source_file IN (...) AND wing = ...` count/delete predicate per batch (default batch size 500, centralized and tunable) — so a stale set of thousands of files collapses to a small constant number of Lance versions instead of one-per-file, while keeping empty/no-match batches as no-op deletes."
  - path: mempalace_code/mining/orchestrator.py
    change: "Replace the initial full incremental stale-path loop's per-file drawer deletion with the new bulk source-file deletion call, preserving the existing stale-sweep guard, KG invalidation, and tiny-hash cleanup."
  - path: tests/test_storage.py
    change: "Add focused LanceStore bulk-delete tests for multi-source deletion, no-op inputs, quote escaping, wing scoping, and a large stale set (a few thousand source files) proving the chunked delete returns the exact deleted-row count and produces a bounded number of Lance versions rather than one-per-file."
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
  - id: AC-6
    when: "`python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_large_stale_set_deletes_in_bounded_batches -q` is run"
    then: "deleting a few thousand source files in one wing removes all matching rows, returns the exact deleted-row count, and produces a bounded number of Lance versions (at most ceil(n / batch_size) deletes plus a small constant), not one Lance version per source file"
out_of_scope:
  - "Changing watch event filtering, debounce timing, startup backup/recovery behavior, or optimize/cleanup scheduling."
  - "Changing document/content chunking, embeddings, source hashing, source_file metadata shape, or Lance table schema. (The new delete-batch chunking inside the bulk-delete API is in scope and is a separate concept.)"
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
    - id: REQ-5
      statement: "At the scale that triggered the incident (thousands of stale files), bulk deletion must produce a small bounded number of Lance versions, not one per stale file; this is enforced by deduping and chunking the stale set into bounded batches inside storage.py."
      source: "backlog description (Lance versions climbed into the thousands)"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Storage source deletion API"
      kind: store
      paths: ["mempalace_code/storage.py"]
      expected_behavior: "DrawerStore exposes delete_by_source_files(source_files, wing); LanceStore dedupes the source set and implements it with one count/delete predicate per bounded batch (default 500) so thousands of stale files collapse to a small constant number of Lance versions, while empty/no-match batches do not mutate Lance."
    - name: "Incremental stale sweep"
      kind: internal
      paths: ["mempalace_code/mining/orchestrator.py"]
      expected_behavior: "When incremental mining walks the full file set, stale_paths are sent to the bulk storage API once before KG invalidation and tiny-hash pruning continue with existing guards."
    - name: "Storage regression tests"
      kind: store
      paths: ["tests/test_storage.py"]
      expected_behavior: "Tests prove the Lance bulk-delete predicate removes all requested stale source rows, returns the correct count, skips no-op deletes, escapes quotes, stays wing-scoped, and at a few-thousand-file stale set produces a bounded number of Lance versions instead of one-per-file."
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
      risk: "Very large stale sets (the incident scale — thousands of files) could produce a single oversized Lance/DataFusion predicate that is rejected or pathologically slow, leaving the reported scenario unresolved."
      mitigation: "Dedupe and chunk the stale set into bounded batches (default 500) inside storage.py, issuing one predicate per batch so version count is ceil(n / batch_size) regardless of stale-set size; batch size is centralized and tunable, and AC-6/VER-6 exercise a few-thousand-file set to prove acceptance, correct count, and bounded versions. Miner control flow is unchanged — it still calls delete_by_source_files once."
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
    - id: VER-6
      command: "python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_large_stale_set_deletes_in_bounded_batches -q"
      proves: "A few-thousand-file stale set is accepted, deletes all matching rows with the exact count, and produces a bounded number of Lance versions instead of one-per-file."
      acceptance_ids: [AC-6]
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
      - id: REG-3
        command: "python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_empty_or_nonmatching_source_files_do_not_delete -q"
        proves: "Empty and no-match bulk-delete inputs return 0 without calling table.delete, so no no-op Lance version is created."
        acceptance_ids: [AC-3]
      - id: REG-4
        command: "python -m pytest tests/test_miner.py::test_incremental_detects_content_change tests/test_miner.py::test_incremental_full_flag_forces_rebuild -q"
        proves: "Modified-file reindexing and explicit full-rebuild deletion stay separate from the stale-file sweep and continue to replace drawers correctly."
        acceptance_ids: [AC-5]
      - id: REG-5
        command: "python -m pytest tests/test_storage.py::TestDeleteBySourceFiles::test_large_stale_set_deletes_in_bounded_batches -q"
        proves: "Incident-scale stale sets keep deleting in bounded batches with the correct count and a bounded number of Lance versions."
        acceptance_ids: [AC-6]
---

## Design Notes

- Keep the current stale-sweep placement: after any pending drawer batch flush and only under `incremental and limit == 0`.
- Add `delete_by_source_files(source_files, wing)` to the storage abstraction with a generic fallback, then implement the Lance path with deduped source paths chunked into bounded batches (default 500, a centralized/tunable constant in `storage.py`), issuing one `source_file IN (...) AND wing = ...` predicate per batch. This makes the Lance version count `ceil(n / batch_size)` rather than one-per-file, which is what actually resolves the reported incident (versions climbing into the thousands), and sidesteps the risk of a single oversized DataFusion predicate being rejected or running pathologically slowly.
- Count before deleting and skip `table.delete` for any empty batch or a batch whose count is zero; this avoids creating no-op Lance versions.
- Verification boundary: the large-N storage test (AC-6/VER-6) exercises a few-thousand-file stale set against a real LanceDB table to prove predicate acceptance, exact count, and bounded version growth. This is verified at the storage layer; it is not an end-to-end watcher run against the large remote corpus that triggered the incident.
- Do not route modified-file reindexing or `incremental=False` rebuilds through the stale sweep. Those paths delete exactly the source file being reprocessed and should stay easy to reason about.
- Leave KG stale invalidation as a per-source loop for now. It does not create Lance versions, and widening it would add a second destructive API surface outside the reported hotspot.
- Remove stale tiny-hash sidecar entries exactly as today; tiny-only stale files are not present in `existing_hashes`, so they should not trigger a Lance delete.
