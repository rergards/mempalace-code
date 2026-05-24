---
slug: CLI-READ-SOURCE-PATH-DISCOVERY
goal: "Make CLI search output copyable for read and let read resolve unique visible source paths."
risk: medium
risk_note: "Small CLI/shared-reader surface, but source_file resolution changes failure modes and MCP read inherits reader.py behavior."
files:
  - path: mempalace_code/searcher.py
    change: "Print the exact stored source_file in human CLI search output instead of trimming it to basename."
  - path: mempalace_code/reader.py
    change: "Resolve read source_file inputs by exact match first, then unique path-component suffix/basename and macOS /var alias matches within the optional wing."
  - path: mempalace_code/cli_commands/query.py
    change: "Render ambiguous source_file candidates and resolved-source errors clearly for mempalace-code read."
  - path: mempalace_code/cli.py
    change: "Update read help text so users know search output and unique visible paths are accepted."
  - path: tests/test_searcher.py
    change: "Cover CLI search printing the full stored source_file path."
  - path: tests/test_reader.py
    change: "Cover source_file resolution for exact, unique suffix/basename, ambiguous, missing, wing-scoped, and macOS /var alias cases."
  - path: tests/test_cli.py
    change: "Cover mempalace-code read success via basename/suffix and ambiguous-candidate CLI output."
acceptance:
  - id: AC-1
    when: "`mempalace-code search \"stored credential lookup\" --wing manual_wing` returns a hit stored as `/private/var/tmp/project/auth.py`"
    then: "the printed `Source:` line contains `/private/var/tmp/project/auth.py`, which can be copied directly into `mempalace-code read`"
  - id: AC-2
    when: "`mempalace-code read auth.py --start 1 --end 2 --wing manual_wing` is run and exactly one stored source in that wing ends with `auth.py`"
    then: "the command exits 0 and prints only the requested numbered lines from that stored source"
  - id: AC-3
    when: "`mempalace-code read src/auth.py --start 1 --end 2 --wing manual_wing` is run and exactly one stored source in that wing ends with `src/auth.py`"
    then: "the command exits 0 and prints only the requested numbered lines from that stored source"
  - id: AC-4
    when: "`mempalace-code read auth.py --start 1 --end 2 --wing manual_wing` is run and multiple stored sources in that wing end with `auth.py`"
    then: "the command exits non-zero, prints an ambiguity message with the matching stored source_file candidates, and prints no drawer content"
  - id: AC-5
    when: "`mempalace-code read /var/tmp/project/auth.py --start 1 --end 2 --wing manual_wing` is run for a row stored as `/private/var/tmp/project/auth.py`"
    then: "the command exits 0 and prints the requested stored lines using the canonical stored source_file"
  - id: AC-6
    when: "`mempalace-code read missing.py --start 1 --end 2 --wing manual_wing` is run with no exact, suffix, basename, or macOS alias match"
    then: "the command exits non-zero with a not-found message and does not fall back to file_context or live disk reads"
out_of_scope:
  - "Adding new CLI JSON or machine-readable search modes."
  - "Changing MCP tool schemas, ranking, embeddings, mining metadata, or storage schema."
  - "Backfilling or rewriting existing source_file metadata."
  - "Reading source files from disk when palace chunks are missing."
contract_policy:
  flow: full_spdd
  reason: "Standard task changes CLI behavior and shared read resolution used by developer tools."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "CLI search must expose the exact stored source_file path needed by CLI read."
      source: "backlog description"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "CLI read must accept a unique visible source value, including basename and project-relative path suffixes, within the requested wing."
      source: "backlog description"
      acceptance_ids: [AC-2, AC-3]
    - id: REQ-3
      statement: "CLI read must reject ambiguous visible source values with candidate source_file paths instead of guessing."
      source: "backlog description"
      acceptance_ids: [AC-4]
    - id: REQ-4
      statement: "CLI read must treat macOS /var and /private/var spellings of the same path as equivalent for lookup."
      source: "backlog description"
      acceptance_ids: [AC-5]
    - id: REQ-5
      statement: "Unresolvable inputs must remain bounded read failures and must not broaden to file_context or live disk reads."
      source: "AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "CLI search output"
      kind: "cli"
      paths: ["mempalace_code/searcher.py"]
      expected_behavior: "human search output prints the stored source_file unchanged, while programmatic search data remains unchanged."
    - name: "Shared read source resolver"
      kind: "internal"
      paths: ["mempalace_code/reader.py"]
      expected_behavior: "read_slice resolves exact, unique suffix/basename, and macOS /var aliases before querying chunks; ambiguous or missing inputs return structured errors."
    - name: "CLI read command"
      kind: "cli"
      paths: ["mempalace_code/cli_commands/query.py", "mempalace_code/cli.py"]
      expected_behavior: "read prints slice output on resolved success and clear non-zero messages for not_found, stale_pointer, invalid_range, and ambiguous_source."
    - name: "Focused regression coverage"
      kind: "internal"
      paths: ["tests/test_searcher.py", "tests/test_reader.py", "tests/test_cli.py"]
      expected_behavior: "tests pin copyable search output, source-path discovery, ambiguity, missing-source, and existing exact-path read behavior."
  invariants:
    - id: INV-1
      statement: "Search ranking, filters, returned result dictionaries, and source_file metadata values do not change."
      applies_to: ["mempalace_code/searcher.py"]
    - id: INV-2
      statement: "Exact source_file matches remain preferred over suffix or alias resolution."
      applies_to: ["mempalace_code/reader.py"]
    - id: INV-3
      statement: "The optional wing filter scopes both source resolution and final chunk reads."
      applies_to: ["mempalace_code/reader.py", "mempalace_code/cli_commands/query.py"]
    - id: INV-4
      statement: "Read failures never read live files and never broaden to full file_context output."
      applies_to: ["mempalace_code/reader.py", "mempalace_code/cli_commands/query.py"]
    - id: INV-5
      statement: "Existing invalid_range and stale_pointer behavior for exact stored source_file inputs remains intact."
      applies_to: ["mempalace_code/reader.py", "mempalace_code/cli_commands/query.py"]
  risks:
    - id: RISK-1
      risk: "Basename matching can pick the wrong file when multiple files share a name."
      mitigation: "Only resolve suffix/basename matches when exactly one candidate remains after wing scoping; otherwise return candidates."
    - id: RISK-2
      risk: "Raw substring suffix matching can match unrelated paths such as `my_auth.py`."
      mitigation: "Compare normalized path components, so `auth.py` matches only a final component and `src/auth.py` matches final components."
    - id: RISK-3
      risk: "macOS alias normalization could accidentally rewrite stored source_file values."
      mitigation: "Use aliases only for comparison and keep the canonical stored source_file in returned results and chunk queries."
    - id: RISK-4
      risk: "Candidate discovery can become expensive on large palaces."
      mitigation: "Use the existing store.get_source_files(wing) fast path when wing is provided, dedupe candidates, and fall back to metadata scans only when needed."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_searcher.py -k 'search_cli_full_source_file_path' -q"
      proves: "CLI search prints exact stored source_file values that can be copied into read"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_reader.py -k 'source_file_resolution' -q"
      proves: "read_slice resolves exact, basename, project-relative suffix, wing-scoped, ambiguous, missing, and macOS /var alias inputs"
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-3
      command: "python -m pytest tests/test_cli.py -k 'read_command_source_path_discovery' -q"
      proves: "mempalace-code read succeeds through visible source values and reports ambiguous candidates without drawer content"
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_reader.py -k 'single_chunk_exact_range or stale_pointer_range_outside_chunks or invalid_range_start_greater_than_end or wing_filter_restricts_to_matching_wing' -q"
        proves: "existing exact-path read, stale-pointer, invalid-range, and wing-filter behavior still works"
        acceptance_ids: [AC-2, AC-3, AC-6]
      - id: REG-2
        command: "python -m pytest tests/test_searcher.py -k 'search_memories_full_source_file_path or search_cli_tolerates_none_metadata_and_document' -q"
        proves: "programmatic source_file preservation and CLI fallback output remain compatible"
        acceptance_ids: [AC-1]
      - id: REG-3
        command: "ruff check mempalace_code/searcher.py mempalace_code/reader.py mempalace_code/cli_commands/query.py mempalace_code/cli.py tests/test_searcher.py tests/test_reader.py tests/test_cli.py"
        proves: "changed CLI/read surfaces and focused tests pass the repo lint gate"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Choose the simple compatibility path: make human CLI search show the exact stored `source_file` rather than adding a new `--json` mode.
- In `searcher.search()`, replace `Path(meta.get("source_file", "?")).name` with a display value that preserves the stored string; keep `?` for missing or empty metadata.
- Add small private helpers in `reader.py`:
  - normalize path separators and split paths into comparable components;
  - produce comparison aliases for `/var/...` and `/private/var/...`;
  - collect candidate `source_file` values scoped by wing, using `get_source_files(wing)` when available.
- Resolution order should be deterministic:
  1. exact stored source_file match;
  2. exact macOS alias match;
  3. unique path-component suffix match, where basename is a one-component suffix;
  4. `ambiguous_source` if multiple candidates match;
  5. existing `not_found` if none match.
- Query chunks only with the resolved canonical stored `source_file`. Return that canonical path in success, stale-pointer, and ambiguity payloads so CLI/MCP callers can recover.
- Keep ambiguity bounded: include candidate paths, not drawer text. CLI output should be copyable, but it must not dump matching chunk contents on an ambiguous read.
- `read_slice()` is shared by MCP read; the plan intentionally avoids MCP schema changes, but the structured `ambiguous_source` result will naturally pass through MCP if a client sends an ambiguous path.
- Do not introduce live-disk fallback. The read command is a palace read of stored chunks, including deleted or renamed source files.
