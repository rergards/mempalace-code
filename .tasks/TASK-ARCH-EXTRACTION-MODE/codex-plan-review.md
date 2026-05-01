verdict: READY

gaps:
  - severity: medium
    claim: "Plan emits five predicate kinds (is_pattern, is_layer, in_namespace, in_project, namespace→project) but no AC observes in_namespace, in_project, or namespace→project facts. An implementation that silently drops these predicates would still satisfy AC-1..AC-5."
    evidence: "docs/plans/ARCH-EXTRACTION-MODE.md design notes (lines 48-53) declare the predicate set; acceptance block (AC-1..AC-5) only checks is_pattern and is_layer."
    suggested_fix: "Add an AC asserting that mining a fixture with classes in namespace Company.Foo under project FooApp produces (<TypeName>, 'in_namespace', 'Company.Foo'), (<TypeName>, 'in_project', 'FooApp'), and ('Company.Foo', 'in_project', 'FooApp') queryable via mempalace_kg_query."
  - severity: medium
    claim: "Namespace-level facts (e.g., (Company.Audit, in_project, X)) are aggregated from many files, but the plan reuses the existing source_file-scoped invalidation model. It does not specify which source_file is recorded for namespace/project triples or how partial re-mines refresh them, which interacts directly with the new predicate-scoped invalidation."
    evidence: "docs/plans/ARCH-EXTRACTION-MODE.md design notes (lines 50, 53, 62-63) emit namespace-scoped triples and propose predicate-scoped invalidate_by_source_file, but say nothing about provenance for facts whose subject spans multiple files; mempalace_code/knowledge_graph.py:170 only filters by exact source_file."
    suggested_fix: "Pin a deterministic strategy in the plan: e.g., re-derive all namespace/project facts on each architecture pass and invalidate architecture predicates globally (or by namespace) rather than only by source_file, with one AC covering renaming the last type out of a namespace and verifying the namespace fact expires."
  - severity: medium
    claim: "Plan adds a new public KG API (invalidate_by_source_file(predicates=...)) but does not list tests/test_knowledge_graph.py (or equivalent) for direct unit coverage of that signature. Coverage is implicit via mining flows in test_architecture_extraction.py, leaving the predicate-filter behavior untested in isolation."
    evidence: "docs/plans/ARCH-EXTRACTION-MODE.md files block (lines 9-16) only edits knowledge_graph.py without a paired unit-test file; mempalace_code/knowledge_graph.py:170 currently has no predicates parameter."
    suggested_fix: "Add tests/test_knowledge_graph.py (or extend the nearest existing KG test module) to the files list with a unit test that mixes architecture and non-architecture triples on the same source_file and asserts predicates=['is_pattern','is_layer','in_namespace','in_project'] expires only the matching subset, plus an AC anchoring this isolation."
  - severity: low
    claim: "Architecture extraction needs per-type namespace/project info that the existing extract_type_relationships output (implements/inherits/extends/depends_on) does not provide, but the plan does not say whether architecture.py reparses the same .cs/.fs/.vb/.py files or shares state with the per-file pass. This affects AC-2 (rule must classify by namespace) and is not addressed."
    evidence: "mempalace_code/miner.py:3120-3142 (extract_type_relationships) returns only relationship triples; docs/plans/ARCH-EXTRACTION-MODE.md design notes (line 47) describe inputs as 'project root, current mined file list, ... config' without specifying namespace acquisition."
    suggested_fix: "State in the plan whether namespace/type inventory is built by re-scanning files inside architecture.py or by extending the per-file KG pass to emit type↔namespace pairs that architecture.py consumes; tie an AC to the chosen approach so reviewers can confirm namespaces are sourced consistently across .cs/.fs/.vb."
  - severity: low
    claim: "Plan asserts default rules and a config 'architecture:' block but does not pin the rule schema (suffix list shape, namespace-glob form, layer-priority list form). AC-3 only checks malformed input is ignored; AC-2 names the configured outcome but not the input shape, so two implementers could ship incompatible YAML schemas and both pass."
    evidence: "docs/plans/ARCH-EXTRACTION-MODE.md design notes (lines 56-61) describe rules in prose; AC-2 (lines 26-27) and AC-3 (lines 28-30) reference unspecified shapes."
    suggested_fix: "Add a minimal canonical YAML block to the plan (e.g., architecture.patterns: list of {name, suffixes, type_names}; architecture.layers: list of {name, namespace_globs, priority}) and reference it in AC-2/AC-3 so the rule schema is testable."
