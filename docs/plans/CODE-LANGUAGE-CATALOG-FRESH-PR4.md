---
slug: CODE-LANGUAGE-CATALOG-FRESH-PR4
goal: "Rebuild a shared language catalog for miner detection, code_search validation, and MCP schema language hints"
risk: medium
risk_note: "Refactors shared language metadata used by mining, search validation, and MCP schema output; behavior must stay byte-for-byte compatible for existing labels and detection order."
files:
  - path: mempalace/language_catalog.py
    change: "Add the canonical catalog for current extension, filename, shebang, readable-extension, searchable-language, and MCP language-description data."
  - path: mempalace/miner.py
    change: "Import catalog maps/constants while preserving detect_language() order, Kubernetes YAML override behavior, chunk routing, and public constant aliases used by watcher/downstream code."
  - path: mempalace/searcher.py
    change: "Derive SUPPORTED_LANGUAGES from the catalog and keep invalid-language responses sorted and unchanged in shape."
  - path: mempalace/mcp_server.py
    change: "Generate the mempalace_code_search language parameter description from the catalog instead of a hard-coded list."
  - path: tests/test_language_catalog.py
    change: "Add catalog contract tests covering current detector maps, detector-only labels, searchable labels, ordering helpers, and must-preserve labels from the stale PR #4 review."
  - path: tests/test_searcher.py
    change: "Add or update invalid-language coverage so code_search reports exactly the sorted catalog searchable labels."
  - path: tests/test_mcp_server.py
    change: "Assert the tools/list language description is generated from a parseable catalog list so every searchable language appears once in deterministic sorted order."
  - path: tests/test_watcher.py
    change: "Add or update watcher import compatibility coverage for miner READABLE_EXTENSIONS and KNOWN_FILENAMES aliases."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_language_catalog.py::test_catalog_preserves_current_detection_labels -q` is run"
    then: "The catalog reports all current extension, filename, and shebang labels, including swift, php, scala, dart, kubernetes, detector-only xml, and shebang-only perl."
  - id: AC-2
    when: "`python -m pytest tests/test_lang_detect.py -q` is run after miner.py imports the catalog"
    then: "Existing detection behavior still passes for extension precedence, filename-before-shebang precedence, unknown files, and Kubernetes YAML override."
  - id: AC-3
    when: "`python -m pytest tests/test_searcher.py::TestCodeSearch::test_code_search_invalid_language_matches_catalog -q` is run"
    then: "An invalid language returns an error plus supported_languages equal to the sorted catalog searchable-language set."
  - id: AC-4
    when: "`python -m pytest tests/test_mcp_server.py::TestCodeSearchTool::test_code_search_language_description_matches_catalog -q` is run"
    then: "The mempalace_code_search language schema text exposes a parseable catalog language list equal to the sorted searchable-language set exactly once, including kubernetes."
  - id: AC-5
    when: "`python -m pytest tests/test_language_catalog.py::test_catalog_keeps_non_extension_boundaries_explicit -q` is run"
    then: "Dockerfile/Containerfile/Makefile/GNUmakefile/Vagrantfile stay filename-driven, Kubernetes stays content-detected from YAML and searchable without an extension map, xml and perl remain detector-only, and no scan-exclude config behavior is introduced."
  - id: AC-6
    when: "`python -m pytest tests/test_watcher.py::test_watcher_miner_filter_imports_remain_available -q` is run"
    then: "mempalace.watcher still imports miner READABLE_EXTENSIONS and KNOWN_FILENAMES aliases successfully, and both exported filters are non-empty."
out_of_scope:
  - "Merging PR #4 directly or reusing its stale branch as code."
  - "Adding PR #4's app-level scan-exclude configuration behavior."
  - "Removing, renaming, or shrinking any currently accepted language label."
  - "Changing chunking, symbol extraction, tree-sitter support, embedding behavior, or storage schema."
  - "Changing VALID_SYMBOL_TYPES except if a failing parity test exposes an existing catalog/search inconsistency that must be preserved explicitly."
---

## Design Notes

- Treat current `mempalace/miner.py` and `mempalace/searcher.py` as the truth sources. PR #4 is useful only as a catalog-shape template.
- Start the catalog by moving the current `EXTENSION_LANG_MAP`, `FILENAME_LANG_MAP`, `SHEBANG_PATTERNS`, `READABLE_EXTENSIONS`, and `SUPPORTED_LANGUAGES` data without editing the values.
- Keep `detect_language()` resolution order unchanged: extension, exact filename, shebang fallback, then YAML-only Kubernetes override when `apiVersion` and `kind` are both present.
- Keep `kubernetes` explicit in searchable languages because no extension maps directly to it. Keep `perl` explicit in detector/shebang data even if it remains a detector-only label.
- Keep `xml` explicit as a detector/readable-only label unless a separate task intentionally adds it to `code_search`. Current `.csproj`, `.fsproj`, and `.vbproj` files detect as `xml`, while `SUPPORTED_LANGUAGES` excludes `xml`.
- Preserve miner public constants as aliases if needed so `mempalace/watcher.py` and any downstream imports keep working without an unrelated watcher refactor.
- Catalog helpers should return immutable or copied containers so callers cannot mutate global source data by accident.
- Generate MCP language description from sorted catalog data. Do not keep a second hard-coded language list in `mcp_server.py`; expose the generated comma-separated language list through a helper or otherwise make the schema list parseable so tests do not rely on fragile substring counts.
- Add contract tests that complement existing `tests/test_lang_detect.py` coverage and fail on catalog/search/miner drift, not broad snapshot tests that make future additive languages painful.
- Leave scan-exclude behavior untouched. If implementation uncovers useful scan-exclude work from PR #4, capture it as a separate backlog item before coding it.
