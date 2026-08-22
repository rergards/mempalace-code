---
slug: UPSTREAM-SPLIT-NAME-DISPOSITION-SYNC
status: completed
authority: non_authoritative
goal: "Synchronize the canonical upstream comparison artifacts with the implemented split-name opt-in behavior and its current local evidence."
risk: low
risk_note: "The change is documentation-only, but an unsynchronized stance or accidental snapshot drift could misstate a release-critical upstream delta."
files:
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Mark split-name-detection-opt-in as adopted and replace the obsolete fallback narrative with the current explicit-config loader and focused predicate evidence."
  - path: docs/quality/upstream-comparison.json
    change: "Set the matching delta-decision row to adopted and synchronize its rationale while retaining its upstream source and local predicates."
acceptance:
  - id: AC-1
    when: "the static upstream comparison guard reports the canonical document and manifest dispositions"
    then: "both canonical artifacts record split-name-detection-opt-in with the adopted stance."
  - id: AC-2
    when: "the updated split-name rationale and its named local predicates are inspected and the focused split-name predicate is executed"
    then: "the rationale identifies the explicit-config _load_known_people() path and tests/test_split_mega_files.py::test_load_known_people_requires_explicit_config, which proves generic names are not detected when configuration is absent."
  - id: AC-3
    when: "the comparison diff and guard output are inspected after the synchronized edit"
    then: "the reviewed upstream SHA remains 3e56979fb456c7478a4b57414027873bd78f2d37 and every unrelated delta disposition remains unchanged."
  - id: AC-4
    when: "the static and live comparison guards, documentation drift guard, public-safety scan, and focused comparison and split-name tests run"
    then: "the updated artifacts pass all configured checks, while the focused guard coverage continues to reject document/manifest stance drift and missing adopted predicates."
out_of_scope:
  - "Changing split-name runtime behavior, configuration format, loader implementation, or focused runtime tests."
  - "Advancing the reviewed upstream commit, source links, review dates, capability inventory, or any unrelated delta decision."
  - "Editing backlog metadata, release bookkeeping, or runner-owned finalization artifacts."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release documentation sync governs a release-critical upstream disposition and must preserve machine-checked comparison evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Both canonical comparison artifacts must record the implemented split-name opt-in with the adopted stance."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The synchronized rationale must cite the current explicit-config loader and its focused no-config predicate."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The reviewed upstream SHA and every unrelated disposition must remain byte-for-byte unchanged."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Static/live comparison checks, documentation drift, public safety, and focused regression evidence must remain green and fail closed on stance or predicate drift."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "canonical upstream comparison"
      kind: internal
      paths: ["docs/UPSTREAM_COMPARISON.md"]
      expected_behavior: "Present split-name-detection-opt-in as adopted and explain that absent explicit configuration produces no generic person-name matches."
    - name: "upstream comparison manifest"
      kind: store
      paths: ["docs/quality/upstream-comparison.json"]
      expected_behavior: "Machine-readably mirror the adopted stance, current rationale, and concrete local loader/test predicates."
  invariants:
    - id: INV-1
      statement: "The reviewed upstream commit remains 3e56979fb456c7478a4b57414027873bd78f2d37, with its dates, compare range, and pinned source links unchanged."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-2
      statement: "Every delta decision other than split-name-detection-opt-in retains its existing category, rationale, sources, criticality, and predicates."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-3
      statement: "The split-name runtime and tests remain unchanged; this task only corrects canonical comparison metadata and prose to match existing behavior."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
  risks:
    - id: RISK-1
      risk: "Updating only one artifact could leave the public narrative and machine-readable disposition inconsistent."
      mitigation: "Edit both canonical rows together and run the static comparison guard that binds document categories to manifest decisions."
    - id: RISK-2
      risk: "An adopted stance could overstate local behavior if it points to stale or generic evidence."
      mitigation: "Name the existing _load_known_people() implementation and exact no-config pytest node; retain the manifest local predicates checked by the guard."
    - id: RISK-3
      risk: "A broad documentation edit could silently alter the reviewed pin or unrelated upstream decisions."
      mitigation: "Limit the diff to the split-name table/narrative and matching manifest row, then inspect the focused diff and guard facts before handoff."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_split_mega_files.py::test_load_known_people_requires_explicit_config tests/test_split_mega_files.py::test_load_known_people_from_list_config -q"
      proves: "The cited boundary rejects generic name detection without configuration and still detects explicitly configured names."
      acceptance_ids: [AC-2, AC-4]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_upstream_comparison_guard.py -q"
      proves: "Focused guard coverage accepts synchronized dispositions and rejects document/manifest category drift or missing adopted predicates."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/upstream_comparison_guard.py"
      proves: "The configured static guard confirms canonical artifact synchronization, the preserved reviewed snapshot, valid adopted predicates, and unchanged comparison structure."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/upstream_comparison_guard.py --check-live --json"
      proves: "The configured live guard confirms the preserved reviewed SHA still matches the upstream branch head and the synchronized artifacts remain admissible."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The configured documentation gate reports no cross-document contract drift after the disposition correction."
      acceptance_ids: [AC-4]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The configured scanner reports no private paths, credentials, or orchestration residue in the public comparison artifacts."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: false
    no_behavior_change_exception: "Only existing canonical documentation and manifest facts change; runtime and test code remain untouched, while the focused predicate and comparison-guard suites verify the cited behavior and synchronization contract."
    checks: []
---

## Design Notes

- Change the `split-name-detection-opt-in` category from `deferred` to `adopted` in both the Markdown table/narrative and the JSON manifest row. Use the existing closed-set category exactly; do not introduce an `implemented` category.
- Replace the obsolete fallback claim with the current behavior: `_load_known_people()` reads optional `~/.mempalace/known_names.json` data and returns an empty list when the file is absent or unusable, so `extract_people()` does not match generic person names by default.
- Cite `mempalace_code/split_mega_files.py` and `tests/test_split_mega_files.py::test_load_known_people_requires_explicit_config` as the adopted local evidence. Preserve the manifest's existing `source_refs`, `release_critical`, and `local_predicates` structure.
- Keep the full reviewed SHA `3e56979fb456c7478a4b57414027873bd78f2d37`, previous SHA, dates, compare URL, source links, capability sections, and all other delta rows unchanged.
- Keep the edit documentation-only. No runtime owner or new regression test is required because the loader and focused no-config/configured-name predicates already implement and pin the behavior.
- Command context basis: `.github/workflows/ci.yml` owns the exact static comparison, documentation-drift, and tracked/staged public-safety commands; `.github/workflows/upstream-drift.yml` owns the exact live guard command; the two selected pytest surfaces are focused existing tests for the runtime predicate and comparison contract.
