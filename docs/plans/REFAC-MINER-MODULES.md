---
slug: REFAC-MINER-MODULES
goal: "Split miner.py into focused mining modules while preserving existing imports and mining behavior"
risk: high
risk_note: "Large behavior-preserving refactor across a 3995-line module with CLI, watcher, convo, KG, and test import seams"
files:
  - path: docs/refactoring/REFAC-MINER-MODULES/progress.md
    change: "Track the miner split execution checkpoints as a refactoring artifact for this large module move"
  - path: mempalace_code/miner.py
    change: "Reduce to the public compatibility surface that re-exports legacy miner symbols and delegates implementation to mempalace_code.mining modules"
  - path: mempalace_code/mining/__init__.py
    change: "Create the internal mining package and expose stable internal module groups"
  - path: mempalace_code/mining/batching.py
    change: "Move hardware batch-size detection and cache state used by project and conversation mining"
  - path: mempalace_code/mining/scanner.py
    change: "Move gitignore matching, scan filter rules, skip constants, include overrides, and scan_project()"
  - path: mempalace_code/mining/languages.py
    change: "Move detect_language() and Kubernetes content detection while continuing to consume language_catalog as the canonical catalog"
  - path: mempalace_code/mining/chunkers.py
    change: "Move boundary regexes, chunk_file(), chunk_code(), prose/adaptive chunking, Tree-sitter chunkers, and Kubernetes manifest chunking"
  - path: mempalace_code/mining/symbols.py
    change: "Move per-language symbol extraction regex tables and extract_symbol()"
  - path: mempalace_code/mining/kg_extract.py
    change: "Move .NET project, solution, XAML, and source type-relationship KG extraction helpers"
  - path: mempalace_code/mining/projects.py
    change: "Move config loading, room detection, multi-project discovery, wing derivation, and .NET room-map helpers"
  - path: mempalace_code/mining/orchestrator.py
    change: "Move mine(), process_file(), drawer spec creation, batch upserts, collection helpers, incremental/stale handling, architecture pass wiring, and status()"
  - path: mempalace_code/watcher.py
    change: "Update internal imports to the new mining scanner/orchestrator modules while preserving watcher filtering behavior"
  - path: mempalace_code/convo_miner.py
    change: "Update shared batch/upsert imports to the new mining modules without changing conversation mining output"
  - path: mempalace_code/cli.py
    change: "Keep lazy mining imports stable or point them at the new modules without changing command names, flags, or exit behavior"
  - path: mempalace_code/room_detector_local.py
    change: "Update scan and room-normalization imports to the new owning modules or verified miner shim exports"
  - path: mempalace_code/README.md
    change: "Update the package module summary to document mempalace_code/mining as the implementation package and miner.py as the compatibility entrypoint"
  - path: tests/test_miner_modules.py
    change: "Add focused import-contract tests for miner shim exports and internal module ownership boundaries"
  - path: tests/test_miner.py
    change: "Update monkeypatch targets and focused mining/scanner expectations to the new module owners while preserving existing behavior assertions"
  - path: tests/test_cli.py
    change: "Update CLI mine command monkeypatch targets to the new orchestrator owner so command wiring tests still intercept mine() calls after the refactor"
  - path: tests/test_chunking.py
    change: "Update chunker imports or compatibility assertions for moved chunking functions and boundary regex constants"
  - path: tests/test_symbol_extract.py
    change: "Update symbol extraction imports or compatibility assertions for moved extract_symbol() and boundary constants"
  - path: tests/test_lang_detect.py
    change: "Update language detector imports or compatibility assertions for moved detect_language()"
  - path: tests/test_kg_extract.py
    change: "Update KG extraction imports or compatibility assertions for moved parse/extract helpers"
  - path: tests/test_treesitter.py
    change: "Update chunk_code import targets where Tree-sitter fallback tests need to patch the chunker module owner"
  - path: tests/test_watcher.py
    change: "Update watcher filter/import contract assertions for new scanner ownership"
  - path: tests/test_convo_miner.py
    change: "Update monkeypatch targets for shared batching/upsert helpers if convo_miner imports move"
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_miner_modules.py::test_miner_compatibility_exports_existing_import_surface -q` is run"
    then: "the test imports existing CLI/watcher/test-facing names from mempalace_code.miner and confirms they resolve to callable or constant-compatible objects after the split"
  - id: AC-2
    when: "`python -m pytest tests/test_miner.py::test_mine_end_to_end_language_metadata tests/test_miner.py::test_process_file_python_symbol_roundtrip -q` is run"
    then: "a seeded Python project still mines drawers with language='python' and symbol metadata for function foo and class Bar"
  - id: AC-3
    when: "`python -m pytest tests/test_miner.py::test_scan_project_does_not_reinclude_file_from_ignored_directory tests/test_miner.py::test_scan_project_can_include_exact_file_without_known_extension tests/test_watcher.py::TestIsRelevantChange::test_app_scan_excludes_match_scan_project -q` is run"
    then: "scan_project and watcher relevance filtering preserve gitignore parent exclusions, exact force-includes, and app-level scan excludes"
  - id: AC-4
    when: "`python -m pytest tests/test_lang_detect.py::test_k8s_yaml_content_returns_kubernetes tests/test_lang_detect.py::test_k8s_detection_requires_both_fields tests/test_language_catalog.py::test_catalog_preserves_current_detection_labels -q` is run"
    then: "language detection still promotes full Kubernetes YAML, keeps partial YAML as yaml, and keeps miner-visible catalog constants equal to language_catalog"
  - id: AC-5
    when: "`python -m pytest tests/test_chunking.py::test_python_two_functions_no_boundary_crossing tests/test_chunking.py::test_dispatcher_language_unknown_falls_back tests/test_treesitter.py::test_chunk_code_regex_fallback_when_treesitter_unavailable -q` is run"
    then: "chunking still keeps Python function boundaries, routes unknown languages through adaptive fallback, and falls back to regex when Tree-sitter is unavailable"
  - id: AC-6
    when: "`python -m pytest tests/test_miner.py::test_mine_no_duplicate_drawers_on_remine tests/test_miner.py::test_incremental_detects_deletion tests/test_miner.py::test_process_file_dry_run_matches_chunk_count -q` is run"
    then: "orchestration still avoids duplicate drawers, sweeps deleted files on incremental remine, and dry-run reports the same chunk count as real processing"
  - id: AC-7
    when: "`python -m pytest tests/test_kg_extract.py::test_parse_csproj_malformed_xml tests/test_kg_extract.py::test_cs_remining_invalidates_stale_triples tests/test_kg_extract.py::test_py_mine_populates_kg -q` is run"
    then: "KG extraction still returns no triples for malformed project XML, invalidates stale C# triples, and emits Python inheritance/import triples during mining"
  - id: AC-8
    when: "`python -m pytest tests/test_convo_miner.py::test_convo_mining tests/test_watcher.py::TestWatchAndMine::test_watch_passes_kg_to_mine -q` is run"
    then: "conversation mining still stores searchable drawers and watcher mining still passes a KnowledgeGraph instance to mine()"
out_of_scope:
  - "Changing storage schema, drawer metadata names, embedding model, or batch semantics"
  - "Adding, removing, or changing language support beyond import paths and module ownership"
  - "Changing CLI command names, flags, exit codes, or MCP tool behavior"
  - "Changing KnowledgeGraph persistence, architecture extraction semantics, or invalidation rules"
  - "Broad test rewrites that reduce current behavior coverage instead of updating import and patch seams"
contract_policy:
  flow: full_spdd
  reason: "Strict standard refactor of a rules-heavy mining pipeline with storage, KG, CLI, watcher, and compatibility surfaces"
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Existing direct imports from mempalace_code.miner used by CLI, watcher, convo mining, tests, and downstream callers must keep resolving."
      source: "backlog compatibility scope"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Project mining must continue to store the same language, symbol, source_hash, extractor_version, and chunker_strategy metadata for code drawers."
      source: "backlog behavior preservation scope"
      acceptance_ids: [AC-2, AC-6]
    - id: REQ-3
      statement: "Scan policy must keep gitignore, app scan excludes, skip lists, readable extensions, known filenames, and include override behavior unchanged."
      source: "backlog scanner/project-walk scope"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Language detection, chunk routing, boundary regexes, symbol extraction, and Tree-sitter fallback behavior must be unchanged after moving modules."
      source: "backlog language/chunker/symbol scope"
      acceptance_ids: [AC-4, AC-5]
    - id: REQ-5
      statement: "KG extraction and mining-time KG invalidation/emission must keep existing success and failure behavior."
      source: "backlog KG extraction scope"
      acceptance_ids: [AC-7]
    - id: REQ-6
      statement: "Non-project mining callers that share miner batching/upsert helpers must keep their observable behavior."
      source: "backlog orchestration compatibility scope"
      acceptance_ids: [AC-8]
  surfaces:
    - name: "Miner compatibility entrypoint"
      kind: "internal"
      paths: ["mempalace_code/miner.py", "mempalace_code/mining/__init__.py"]
      expected_behavior: "mempalace_code.miner remains the stable import surface while implementation moves behind mempalace_code.mining"
    - name: "Scan and watcher filtering"
      kind: "internal"
      paths: ["mempalace_code/mining/scanner.py", "mempalace_code/watcher.py"]
      expected_behavior: "Project walk and watcher relevance checks share the same scan rules and preserve include/ignore precedence"
    - name: "Language, chunking, and symbol pipeline"
      kind: "internal"
      paths: ["mempalace_code/mining/languages.py", "mempalace_code/mining/chunkers.py", "mempalace_code/mining/symbols.py", "mempalace_code/language_catalog.py"]
      expected_behavior: "Detection, chunk routing, boundary regexes, and symbol extraction move into focused modules without changing outputs"
    - name: "KG extraction"
      kind: "internal"
      paths: ["mempalace_code/mining/kg_extract.py"]
      expected_behavior: ".NET, XAML, and Python KG helpers keep existing triples, empty-result guards, and invalidation support"
    - name: "Mining orchestration"
      kind: "cli"
      paths: ["mempalace_code/mining/orchestrator.py", "mempalace_code/mining/batching.py", "mempalace_code/mining/projects.py", "mempalace_code/cli.py", "mempalace_code/convo_miner.py", "mempalace_code/room_detector_local.py"]
      expected_behavior: "CLI/watch/convo callers reach the same mine, process, batch, status, and project-resolution behavior through the new module owners"
    - name: "Regression coverage"
      kind: "internal"
      paths: ["tests/test_miner_modules.py", "tests/test_miner.py", "tests/test_cli.py", "tests/test_chunking.py", "tests/test_symbol_extract.py", "tests/test_lang_detect.py", "tests/test_kg_extract.py", "tests/test_treesitter.py", "tests/test_watcher.py", "tests/test_convo_miner.py"]
      expected_behavior: "Tests update only import/patch seams and add a compatibility contract without narrowing existing mining coverage"
  invariants:
    - id: INV-1
      statement: "mempalace_code.miner must continue exporting current public and legacy direct-import names used by this repo."
      applies_to: ["mempalace_code/miner.py"]
    - id: INV-2
      statement: "language_catalog remains the canonical source for language maps, readable extensions, known filenames, shebang patterns, and searchable languages."
      applies_to: ["mempalace_code/language_catalog.py", "mempalace_code/mining/languages.py"]
    - id: INV-3
      statement: "No drawer metadata field names, source_file hashing behavior, chunk_index sequencing, or chunker_strategy labels change."
      applies_to: ["mempalace_code/mining/orchestrator.py", "mempalace_code/mining/chunkers.py"]
    - id: INV-4
      statement: "CLI, watcher, and MCP lazy mining imports must not eagerly load mining dependencies before their existing lazy points."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/watcher.py", "mempalace_code/miner.py"]
    - id: INV-5
      statement: "KG triple predicates, subject/object derivation, and source_file invalidation semantics remain unchanged."
      applies_to: ["mempalace_code/mining/kg_extract.py", "mempalace_code/mining/orchestrator.py"]
  risks:
    - id: RISK-1
      risk: "Direct import users break when private-but-used names move out of miner.py."
      mitigation: "Keep miner.py as an explicit compatibility shim and add tests/test_miner_modules.py for the current import surface."
    - id: RISK-2
      risk: "Monkeypatches stop controlling orchestration because helpers move to new module owners."
      mitigation: "Update tests to patch owning modules and keep only direct import compatibility in miner.py."
    - id: RISK-3
      risk: "Circular imports appear between chunkers, symbols, language detection, and orchestration."
      mitigation: "Keep leaf modules acyclic: language_catalog -> languages/symbols/chunkers -> projects/scanner -> orchestrator -> miner shim."
    - id: RISK-4
      risk: "Scan and watcher filtering drift after scan helpers move."
      mitigation: "Watcher imports scanner-owned constants/helpers and AC-3 verifies shared filter behavior."
    - id: RISK-5
      risk: "Moving KG extraction accidentally changes empty-file, malformed XML, or stale invalidation behavior."
      mitigation: "Keep parser helpers pure and AC-7 verifies malformed XML, C# invalidation, and Python KG emission."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_miner_modules.py -q"
      proves: "miner.py remains a compatibility import surface for existing consumers"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_miner.py::test_mine_end_to_end_language_metadata tests/test_miner.py::test_process_file_python_symbol_roundtrip tests/test_miner.py::test_scan_project_does_not_reinclude_file_from_ignored_directory tests/test_miner.py::test_scan_project_can_include_exact_file_without_known_extension -q"
      proves: "project mining still writes language and symbol metadata for Python drawers"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_watcher.py::TestIsRelevantChange::test_app_scan_excludes_match_scan_project tests/test_lang_detect.py::test_k8s_yaml_content_returns_kubernetes tests/test_lang_detect.py::test_k8s_detection_requires_both_fields tests/test_language_catalog.py::test_catalog_preserves_current_detection_labels -q"
      proves: "scanner and watcher filtering preserve ignore/include/app-exclude behavior"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_watcher.py::TestIsRelevantChange::test_app_scan_excludes_match_scan_project tests/test_lang_detect.py::test_k8s_yaml_content_returns_kubernetes tests/test_lang_detect.py::test_k8s_detection_requires_both_fields tests/test_language_catalog.py::test_catalog_preserves_current_detection_labels -q"
      proves: "language detection and miner-visible catalog constants are unchanged"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_chunking.py::test_python_two_functions_no_boundary_crossing tests/test_chunking.py::test_dispatcher_language_unknown_falls_back tests/test_treesitter.py::test_chunk_code_regex_fallback_when_treesitter_unavailable -q"
      proves: "chunking boundaries, fallback routing, and Tree-sitter fallback remain unchanged"
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_miner.py::test_mine_no_duplicate_drawers_on_remine tests/test_miner.py::test_incremental_detects_deletion tests/test_miner.py::test_process_file_dry_run_matches_chunk_count -q"
      proves: "orchestration preserves idempotent remine, stale deletion, and dry-run chunk count behavior"
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_kg_extract.py::test_parse_csproj_malformed_xml tests/test_kg_extract.py::test_cs_remining_invalidates_stale_triples tests/test_kg_extract.py::test_py_mine_populates_kg -q"
      proves: "KG extraction guards and mining-time KG emission/invalidation remain unchanged"
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "python -m pytest tests/test_convo_miner.py::test_convo_mining tests/test_watcher.py::TestWatchAndMine::test_watch_passes_kg_to_mine -q"
      proves: "shared batching/upsert helper moves do not break convo mining or watcher KG handoff"
      acceptance_ids: [AC-8]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_miner.py tests/test_chunking.py tests/test_symbol_extract.py tests/test_lang_detect.py tests/test_kg_extract.py tests/test_treesitter.py tests/test_language_catalog.py -q"
        proves: "focused miner, detection, chunking, symbol, KG, and language catalog behavior remains intact after the split"
        acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-2
        command: "python -m pytest tests/test_watcher.py tests/test_convo_miner.py tests/test_architecture_extraction.py -q"
        proves: "downstream watcher, conversation mining, and architecture mining surfaces still work with moved miner helpers"
        acceptance_ids: [AC-8]
      - id: REG-3
        command: "python -m pytest tests/test_miner_modules.py -q"
        proves: "the compatibility shim and internal module ownership contract remain stable"
        acceptance_ids: [AC-1]
      - id: REG-4
        command: "ruff check mempalace_code/ tests/ && ruff format --check mempalace_code/ tests/"
        proves: "the moved modules and updated imports satisfy project lint and formatting gates"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
---

## Design Notes

- Use `mempalace_code/mining/` as the implementation package, following the existing `mempalace_code/mcp/` split pattern. Keep `mempalace_code.miner` as the public import and `python -m` friendly entrypoint for current callers.
- Keep the split mostly mechanical in the first implementation pass. Move code blocks with minimal edits, then update imports and test patch targets. Do not opportunistically rewrite parsing, chunking, or scan logic.
- Suggested dependency direction:
  - `language_catalog.py` stays canonical and has no mining-package dependency.
  - `mining.languages` imports `language_catalog`.
  - `mining.symbols` owns extraction regexes and the Kubernetes symbol helper.
  - `mining.chunkers` imports `languages` and `symbols`, and owns boundary regexes plus merge/split helpers.
  - `mining.scanner` owns filesystem filtering and imports only config/catalog-level helpers.
  - `mining.projects` owns config, room routing, project detection, wing normalization, and .NET room maps.
  - `mining.kg_extract` owns pure parse/extract helpers and should not import orchestration.
  - `mining.orchestrator` imports the leaf modules and remains the only owner of storage writes, incremental state, stale sweeps, architecture pass invocation, and optimize calls.
- Compatibility shim policy:
  - Re-export existing names currently imported from `mempalace_code.miner`, including constants such as `MIN_CHUNK`, `TARGET_MAX`, `HARD_MAX`, boundary regexes, scan constants, and helpers used by tests.
  - Keep direct imports working. Do not promise that assigning to `mempalace_code.miner.get_collection` or other shim globals controls orchestration internals; update repo tests to patch the new owning modules.
  - Preserve lazy import behavior for CLI/MCP startup. Do not make `mempalace_code.mcp_server` import mining modules before its current lazy mining call path.
- Scanner ownership:
  - Move `GitignoreMatcher`, app scan rules, skip constants, and include override helpers together. Watcher should import these from `mining.scanner` so save-event filtering and full project scans cannot drift.
  - Preserve the exact precedence: force include beats skip filenames, app scan excludes, skip dirs, and gitignore for covered paths; exact force include allows extensionless files.
- Chunker ownership:
  - Keep boundary regex constants in `mining.chunkers` and re-export from `miner.py` for existing tests and callers.
  - Tree-sitter chunkers should continue to use `treesitter.get_parser`; fallback tags and `chunker_strategy` values must remain unchanged.
  - Keep adaptive merge/split thresholds and chunk index sequencing unchanged.
- KG extraction ownership:
  - Keep parse helpers pure and file-path based. `mining.orchestrator` decides when to invalidate or emit triples.
  - Preserve malformed/empty parser behavior: return an empty triple list, never raise into mining for normal bad input.
- Test strategy:
  - Add `tests/test_miner_modules.py` for import surface and ownership contract checks.
  - Update existing tests only where import paths or patch targets need the new module owners.
  - Keep behavioral tests in their current files so future language additions still know where to add detection, chunking, symbol, and KG coverage.
- Implementation should run the verification rows first, then the broader regression rows. If the full focused miner set is too slow locally, report which focused commands passed and which broader commands were deferred; do not claim full verification without running it.
