slug: MINE-SWIFT
round: 1
date: 2026-04-20
commit_range: 2fb5382..HEAD
findings:
  - id: F-1
    title: "typealias symbol type mined but not in VALID_SYMBOL_TYPES"
    severity: medium
    location: "mempalace/searcher.py:213"
    claim: >
      _SWIFT_EXTRACT produces drawers with symbol_type="typealias" (and Kotlin's extractor
      has done so since MINE-KOTLIN). However VALID_SYMBOL_TYPES in searcher.py did not
      include "typealias", so code_search(symbol_type="typealias") returned an
      "invalid symbol_type" validation error even though mined drawers exist with that type.
      No test covered this path, so the regression would have been invisible.
    decision: fixed
    fix: >
      Added "typealias" to VALID_SYMBOL_TYPES in searcher.py.
      Added "typealias" to the symbol_type description string in mcp_server.py.
      Added test_code_search_typealias_symbol_type and updated
      test_swift_new_symbol_types_in_error_hint to assert "typealias" in valid_symbol_types hint.

  - id: F-2
    title: "distributed actor declarations not detected as chunk boundaries"
    severity: low
    location: "mempalace/miner.py:672"
    claim: >
      Swift 5.5+ distributed actors use the `distributed` modifier
      (e.g. `distributed actor ClusterManager { }`). SWIFT_BOUNDARY and
      _SWIFT_EXTRACT do not include `distributed` as a modifier, so
      `distributed actor Foo {` is not detected as a chunk boundary and
      extract_symbol returns ("", "") for such chunks.
    decision: backlogged
    backlog_slug: MINE-SWIFT-DISTRIBUTED

  - id: F-3
    title: "@Published regression test re-implements chunk_code boundary logic"
    severity: medium
    location: "tests/test_symbol_extract.py:1444"
    claim: >
      test_swift_published_property_not_stolen_by_func_lookback duplicated chunk_code's
      boundary-scanning loop verbatim instead of calling chunk_code(). A future change
      to chunk_code's lookback logic (e.g. adding a new skip condition, changing
      comment_prefixes) would not be caught by this test, defeating its regression
      purpose. The test was also too small (8 lines) for adaptive_merge_split to produce
      separate chunks, so it could not verify the fix at the output level.
    decision: fixed
    fix: >
      Rewrote the test to call chunk_code() with a func body large enough (~2600 chars)
      that adaptive_merge_split produces separate chunks. Asserts that the func increment
      chunk does not contain "@Published". Removed the re-implementation of boundary logic
      and the internal SWIFT_BOUNDARY / _SWIFT_PURE_ATTR imports.

  - id: F-4
    title: "test_swift_chunk_code_class_and_methods has weak assertions"
    severity: low
    location: "tests/test_symbol_extract.py:1426"
    claim: >
      The test only asserted len(chunks) > 0 and "Calculator" in full_text. Neither
      "add" nor "subtract" were asserted, so a bug that silently dropped method
      content from chunks would pass undetected.
    decision: fixed
    fix: >
      Added assertions for "add" and "subtract" in full_text.

  - id: F-5
    title: "_SWIFT_PURE_ATTR fails to match attributes with nested parentheses"
    severity: low
    location: "mempalace/miner.py:683"
    claim: >
      _SWIFT_PURE_ATTR = r"^(?:@\w+(?:\([^)]*\))?\s*)+$" uses [^)]* which stops at
      the first ')'. An attribute like @available(iOS 14, *, message: "use foo()")
      contains a ')' inside a string argument; [^)]* stops at it, and the overall
      pattern fails to match to $. Such a line would not be recognised as a pure
      attribute during lookback, causing the lookback to stop prematurely.
      In practice this requires a deprecated-API message that itself contains a
      function call — rare but valid Swift.
    decision: dismissed
    # Dismissed: the affected form requires a deprecated-message string with a nested
    # call — uncommon in real iOS code. The line still correctly acts as a chunk
    # boundary stop (lookback halts); the only cost is that the attribute is not
    # attached to the following declaration. Fixing requires a balanced-paren parser
    # which adds significant regex complexity for negligible real-world benefit.

  - id: F-6
    title: "init declarations not detected as chunk boundaries"
    severity: info
    location: "mempalace/miner.py:672"
    claim: >
      Swift init() / init?() / convenience init() are not in SWIFT_BOUNDARY or
      _SWIFT_EXTRACT. init bodies are folded into the enclosing class/struct chunk.
    decision: dismissed
    # Dismissed: init is not listed in the MINE-SWIFT acceptance criteria, and
    # init bodies are typically short. The class/struct chunk that contains init
    # is still properly indexed. Can be added in a follow-up if needed.

totals:
  fixed: 3
  backlogged: 1
  dismissed: 2

fixes_applied:
  - "F-1: Add typealias to VALID_SYMBOL_TYPES in searcher.py"
  - "F-1: Add typealias to mcp_server.py symbol_type description hint"
  - "F-1: Add test_code_search_typealias_symbol_type; update test_swift_new_symbol_types_in_error_hint"
  - "F-3: Replace reimplemented-boundary regression test with chunk_code()-level test using large content"
  - "F-4: Add assert 'add' and 'subtract' in full_text to test_swift_chunk_code_class_and_methods"

new_backlog:
  - slug: MINE-SWIFT-DISTRIBUTED
    summary: "Add distributed modifier to SWIFT_BOUNDARY and _SWIFT_EXTRACT actor pattern so distributed actor declarations create their own chunk boundary with symbol_type='actor'"
