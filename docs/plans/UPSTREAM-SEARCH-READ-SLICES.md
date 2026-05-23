---
slug: UPSTREAM-SEARCH-READ-SLICES
goal: "Expose mined line ranges and add a precise read path for search hits."
risk: medium
risk_note: "Additive Lance metadata plus CLI/MCP behavior changes touch mining, search, and read surfaces."
files:
  - path: mempalace_code/storage.py
    change: "Add line_start and line_end metadata columns with legacy-safe defaults and schema migration."
  - path: mempalace_code/mining/orchestrator.py
    change: "Attach source-file line_start/line_end metadata to mined chunk specs before batch upsert."
  - path: mempalace_code/searcher.py
    change: "Return real line_range objects from search_memories and code_search while preserving legacy None."
  - path: mempalace_code/reader.py
    change: "Add shared pointer parsing, line-range overlap, and line-numbered slice rendering helpers."
  - path: mempalace_code/mcp/tools/search.py
    change: "Return line_range in file context and register an MCP surgical read tool."
  - path: mempalace_code/mcp_server.py
    change: "Re-export the new MCP read handler for existing direct-import tests and compatibility."
  - path: mempalace_code/cli_commands/query.py
    change: "Add the read command handler that uses the shared reader helpers."
  - path: mempalace_code/cli.py
    change: "Register mempalace-code read arguments and dispatch."
  - path: tests/test_storage_lance.py
    change: "Cover line_start/line_end metadata defaults and roundtrip behavior."
  - path: tests/test_miner.py
    change: "Cover mined line-range metadata for single and repeated chunks."
  - path: tests/test_searcher.py
    change: "Cover line_range output for search_memories, code_search, and legacy metadata rows."
  - path: tests/test_mcp_server.py
    change: "Cover file_context line ranges and MCP surgical read behavior."
  - path: tests/test_reader.py
    change: "Cover pointer parsing, slice rendering, multi-chunk reads, missing source, and stale pointers."
  - path: tests/test_cli.py
    change: "Cover mempalace-code read success and validation failure paths."
acceptance:
  - id: AC-1
    when: "a freshly mined fixture file is queried through search_memories and code_search"
    then: "each hit for the fixture includes line_range {start, end} matching the source lines while source_file remains the exact stored path"
  - id: AC-2
    when: "mempalace_file_context is called for a file with multiple indexed chunks"
    then: "chunks remain chunk_index ordered and each newly mined chunk reports its own non-null line_range without changing content"
  - id: AC-3
    when: "MCP mempalace_read and CLI mempalace-code read request a line span that overlaps two indexed chunks"
    then: "the response contains only the requested numbered source lines in order and excludes neighboring lines"
  - id: AC-4
    when: "the read path is given a source_file that is absent from the palace"
    then: "it returns a structured not-found result, and the CLI exits non-zero without printing drawer content"
  - id: AC-5
    when: "the read path receives an invalid range or a range outside every stored chunk line_range"
    then: "it returns a validation or stale-pointer error and never falls back to broad file context"
  - id: AC-6
    when: "search or file_context sees a legacy row with missing or zero line_start/line_end"
    then: "line_range is null and all existing hit fields keep their current fallback behavior"
out_of_scope:
  - "Porting upstream Chroma closet storage, build_closet_lines, or date-based closet pointer generation."
  - "Backfilling existing palaces without re-mining; legacy rows may keep null line_range."
  - "Changing embedding models, ranking, hybrid reranking, or source_file path preservation."
  - "Reading live source files from disk as a fallback for missing palace metadata."
contract_policy:
  flow: full_spdd
  reason: "Standard task changes storage metadata, mining, MCP, and CLI read behavior."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Mined chunks must persist 1-indexed source-file line_start and line_end metadata when source text is available."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Search, code search, and file-context responses must expose real line_range values for newly mined chunks."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2, AC-6]
    - id: REQ-3
      statement: "A surgical read path must return only the requested stored slice by source_file and line range."
      source: "backlog description"
      acceptance_ids: [AC-3, AC-4, AC-5]
    - id: REQ-4
      statement: "Legacy or incomplete rows must degrade to null line_range rather than inventing fake line numbers."
      source: "AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Lance metadata schema"
      kind: "store"
      paths: ["mempalace_code/storage.py"]
      expected_behavior: "line_start and line_end are stored as int metadata with 0 meaning unknown for legacy rows."
    - name: "Mining metadata emission"
      kind: "internal"
      paths: ["mempalace_code/mining/orchestrator.py"]
      expected_behavior: "chunk specs include line_start and line_end computed from the source text before upsert."
    - name: "Search result shaping"
      kind: "api"
      paths: ["mempalace_code/searcher.py"]
      expected_behavior: "programmatic search APIs map valid metadata to line_range {start, end} and keep None for missing ranges."
    - name: "Shared read helpers"
      kind: "internal"
      paths: ["mempalace_code/reader.py"]
      expected_behavior: "parse read pointers/ranges, find overlapping stored chunks, and render source-numbered slices."
    - name: "MCP search/read tools"
      kind: "api"
      paths: ["mempalace_code/mcp/tools/search.py", "mempalace_code/mcp_server.py"]
      expected_behavior: "file_context returns line ranges and mempalace_read exposes the surgical read path to MCP clients."
    - name: "CLI read command"
      kind: "cli"
      paths: ["mempalace_code/cli.py", "mempalace_code/cli_commands/query.py"]
      expected_behavior: "mempalace-code read accepts source_file plus line range and prints only the requested numbered slice."
    - name: "Focused regression coverage"
      kind: "internal"
      paths:
        - "tests/test_storage_lance.py"
        - "tests/test_miner.py"
        - "tests/test_searcher.py"
        - "tests/test_mcp_server.py"
        - "tests/test_reader.py"
        - "tests/test_cli.py"
      expected_behavior: "tests pin the new metadata, search, MCP, and CLI read contracts."
  invariants:
    - id: INV-1
      statement: "Stored drawer text remains verbatim; line metadata must not rewrite chunk content."
      applies_to: ["mempalace_code/mining/orchestrator.py", "mempalace_code/storage.py"]
    - id: INV-2
      statement: "Existing search filters, source_file exact-path behavior, and rerank behavior remain unchanged."
      applies_to: ["mempalace_code/searcher.py", "mempalace_code/mcp/tools/search.py"]
    - id: INV-3
      statement: "Read failures must not broaden to full file_context output or live disk reads."
      applies_to: ["mempalace_code/reader.py", "mempalace_code/mcp/tools/search.py", "mempalace_code/cli_commands/query.py"]
    - id: INV-4
      statement: "Existing Lance palaces open after schema migration and legacy rows report null line_range."
      applies_to: ["mempalace_code/storage.py", "mempalace_code/searcher.py"]
  risks:
    - id: RISK-1
      risk: "Repeated or stripped chunk text can map to the wrong source occurrence."
      mitigation: "Compute ranges with a cursor-based exact-match helper and add repeated-text tests."
    - id: RISK-2
      risk: "New metadata columns can break old Lance tables or rows without values."
      mitigation: "Use additive schema migration with 0 defaults and convert only positive start/end pairs to line_range."
    - id: RISK-3
      risk: "CLI and MCP read behavior can diverge."
      mitigation: "Route both surfaces through mempalace_code.reader and cover both with behavior tests."
    - id: RISK-4
      risk: "A stale pointer could accidentally dump too much context."
      mitigation: "Return an explicit stale-pointer error when no stored chunk overlaps the requested range."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_miner.py tests/test_storage_lance.py -k 'line_range_metadata or line_range_schema' -q"
      proves: "newly mined chunks persist valid line_start and line_end metadata and Lance metadata roundtrips them"
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      command: "python -m pytest tests/test_searcher.py -k 'line_range' -q"
      proves: "search_memories and code_search expose line_range for new rows and null for legacy rows"
      acceptance_ids: [AC-1, AC-6]
    - id: VER-3
      command: "python -m pytest tests/test_mcp_server.py -k 'file_context_line_range or read_slice' -q"
      proves: "MCP file_context and mempalace_read expose ordered ranges and surgical slices"
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
    - id: VER-4
      command: "python -m pytest tests/test_reader.py -q"
      proves: "shared reader behavior covers single-match, multi-match, missing-source, stale-pointer, and invalid-range cases"
      acceptance_ids: [AC-3, AC-4, AC-5]
    - id: VER-5
      command: "python -m pytest tests/test_cli.py -k 'read_command' -q"
      proves: "CLI read prints only requested lines on success and exits non-zero for validation failures"
      acceptance_ids: [AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_searcher.py -k 'code_search_full_source_file_path_unchanged or code_search_tolerates_none_document_and_metadata' -q"
        proves: "existing source_file preservation and None metadata fallbacks survive the new line_range shaping"
        acceptance_ids: [AC-1, AC-6]
      - id: REG-2
        command: "python -m pytest tests/test_mcp_server.py -k 'code_search_basic or happy_path_returns_all_chunks_with_fields' -q"
        proves: "existing MCP code_search and file_context shapes remain compatible while line_range changes from placeholder to data"
        acceptance_ids: [AC-1, AC-2, AC-6]
      - id: REG-3
        command: "ruff check mempalace_code/reader.py mempalace_code/searcher.py mempalace_code/mcp/tools/search.py mempalace_code/cli.py mempalace_code/cli_commands/query.py tests/test_reader.py tests/test_searcher.py tests/test_mcp_server.py tests/test_cli.py"
        proves: "new implementation and tests meet the repo lint gate for the changed surfaces"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Treat upstream PRs as design input, not code to merge wholesale: upstream is closet/Chroma-centric, while this fork's useful pointer is `source_file` plus `line_range`.
- Store two primitive metadata fields, `line_start` and `line_end`; expose the public `line_range` field as `{"start": line_start, "end": line_end}` only when both values are positive.
- Compute line ranges after `chunk_file(...)` in the mining orchestrator so all current chunkers benefit without per-language rewrites.
- Use cursor-based exact matching against the original file text to disambiguate repeated chunks. If a chunk cannot be matched exactly, leave the range unknown instead of guessing.
- The surgical read path should read stored drawer chunks from the palace, not live source files. This preserves deleted/renamed-file behavior and avoids a broad fallback.
- Add a shared `reader.py` so CLI and MCP use the same range parser, overlap logic, stale-pointer handling, and line-numbered rendering.
- Define stale pointer narrowly: the source exists in the palace, but no stored chunk has line metadata overlapping the requested range.
- Keep `mempalace_file_context` as the broad ordered-context tool; the new read path is for bounded slices after a precise search hit.
