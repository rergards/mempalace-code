---
slug: ARCH-EXTRACTION-WING-SCOPE
goal: "Scope architecture KG invalidation to the project currently being mined so sequential single-wing mines preserve other wings' arch facts."
risk: low
risk_note: "Keeps the existing KG schema and architecture extraction flow; risk is limited to source-file invalidation predicates and sentinel provenance."
files:
  - path: mempalace_code/knowledge_graph.py
    change: "Add a predicate-scoped invalidation helper for active triples whose source_file is exactly one of a provided set or is under a resolved project-root prefix, with path-boundary handling."
  - path: mempalace_code/architecture.py
    change: "Add a wing/project-specific namespace-project sentinel source_file helper and use it when emitting namespace in_project facts."
  - path: mempalace_code/miner.py
    change: "Replace the global architecture predicate sweep with current-project arch invalidation before optional re-emission, including the current wing's namespace sentinel."
  - path: tests/test_architecture_extraction.py
    change: "Add regression coverage for sequential multi-wing mines, disabled architecture cleanup, deleted source cleanup, namespace sentinel scoping, and source-prefix boundaries."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_architecture_extraction.py::TestMiningIntegration::test_sequential_wing_mines_preserve_prior_arch_facts -q` mines fixture wing alpha and then fixture wing beta into the same KG."
    then: "current incoming `Service` facts include both `AlphaService` and `BetaService`, and current incoming `Data` facts still include `AlphaRepository` after beta is mined."
  - id: AC-2
    when: "`python -m pytest tests/test_architecture_extraction.py::TestMiningIntegration::test_namespace_project_sentinel_is_scoped_per_wing -q` mines two wings that both declare namespace `Company.Shared`."
    then: "current outgoing `in_project` facts for `Company.Shared` include both wing/project names after the second mine."
  - id: AC-3
    when: "`python -m pytest tests/test_architecture_extraction.py::TestMiningIntegration::test_disabling_architecture_expires_only_current_wing_facts -q` mines alpha and beta, then re-mines alpha with `architecture.enabled: false`."
    then: "alpha's current `is_pattern`, `is_layer`, `in_namespace`, and `in_project` arch facts are absent, while beta's current arch facts remain queryable."
  - id: AC-4
    when: "`python -m pytest tests/test_architecture_extraction.py::TestMiningIntegration::test_deleted_source_expires_current_wing_arch_facts_without_touching_other_wings -q` deletes `AlphaService.cs` and re-mines alpha after beta has already been mined."
    then: "`AlphaService is_pattern Service` is no longer current, a surviving alpha file's arch facts are re-emitted, and beta's arch facts remain current."
  - id: AC-5
    when: "`python -m pytest tests/test_architecture_extraction.py::TestPredicatesFilter::test_project_prefix_invalidation_respects_path_boundaries -q` expires arch predicates for project root `/tmp/proj` while another active arch fact has source_file `/tmp/proj-other/BetaService.cs`."
    then: "only triples under `/tmp/proj/` or an explicitly provided sentinel are expired; sibling-prefix triples under `/tmp/proj-other/` remain current."
out_of_scope:
  - "Adding a wing column or otherwise migrating the KG schema."
  - "Changing entity IDs, KG query semantics, or historical valid_from/valid_to behavior."
  - "Changing drawer storage, embedding models, chunking, or mine-all project selection."
  - "Fixing cross-wing deduplication for identical subject/predicate/object triples beyond the invalidation bug."
---

## Design Notes

- Prefer source-file provenance scoping over a schema migration. All mined source files already use resolved absolute paths, so the architecture refresh can invalidate only active arch triples whose `source_file` is inside `project_path`.
- Add the KG helper as a general primitive, not architecture-specific SQL embedded in `miner.py`. It should accept `predicates`, a resolved source root, and optional exact `source_file` values for sentinel rows.
- The source-root match must be path-boundary aware: `/tmp/proj` matches `/tmp/proj/src/A.cs`, but not `/tmp/proj-other/B.cs`. Normalize with `Path(...).resolve()` and use an exact-root check plus a separator-suffixed prefix or equivalent SQL conditions.
- Keep `invalidate_by_predicates()` for existing callers, but stop using it for the architecture mining pass.
- Replace `_NS_PROJECT_SENTINEL` usage with a helper such as `namespace_project_source_file(project_name)` returning a stable value derived from the current wing/project, for example `__arch_ns_project__:<project_name>`.
- In `mine()`, compute `arch_source_root = str(project_path)` and `arch_sentinel = namespace_project_source_file(wing)` before loading/re-emitting architecture facts. Call the new KG helper before checking `architecture.enabled`, so config flips to `false` still expire only the current wing's arch facts.
- The helper should still expire arch facts for files deleted from the working tree because it targets all active arch triples under the project root, not only `walked_paths`.
- Existing per-file KG invalidation for changed/deleted files should remain unchanged; it owns non-architecture triples such as `inherits`, `implements`, `depends_on`, and XAML relations.
- Tests can follow the existing `TestMiningIntegration` style with temporary projects, one shared `palace_path`, and one shared `KnowledgeGraph`. Use distinct class names per wing to avoid hiding invalidation behavior behind KG triple deduplication.
