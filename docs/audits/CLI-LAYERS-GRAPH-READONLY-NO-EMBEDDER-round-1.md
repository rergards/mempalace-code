slug: CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER
round: 1
date: 2026-05-24
commit_range: fe62680..209d142
findings:
  - id: F-1
    title: "CLI smoke _assert_no_model_output cannot detect accidental embedder startup"
    severity: info
    location: "tests/test_layers.py:27"
    claim: |
      _ensure_embedder() already suppresses model-loading output at the OS fd level
      (dup2 to /dev/null while loading). The _assert_no_model_output helper checks
      for HF/sentence-transformers markers in subprocess output, but these are
      already redirected to /dev/null even when the embedder IS loaded. The assertion
      provides no real protection against accidental embedder startup in the CLI
      smoke path. The test's actual correctness proof comes from exit code == 0 and
      the "L1 — ESSENTIAL STORY" content assertion.
    decision: dismissed
    fix: ~

  - id: F-2
    title: "test_empty_palace_no_embedder_recall has no content assertion"
    severity: low
    location: "tests/test_layers.py:259"
    claim: |
      The test only asserted isinstance(text, str) and len(text) > 0. It did not
      verify the user-visible "No drawers found" message, so a silent behavior
      regression (e.g. returning an empty-looking but structurally wrong string)
      would pass the test.
    decision: fixed
    fix: "Added assert 'No drawers found' in text with a descriptive failure message."

  - id: F-3
    title: "TestGraphMissingPalaceNoEmbedder missing traverse coverage"
    severity: low
    location: "tests/test_palace_graph.py:450"
    claim: |
      The missing-palace test class covered build_graph, graph_stats, and
      find_tunnels but not traverse. traverse returns a different shape for a
      missing palace (error dict with 'error' key) vs a populated palace (list of
      hop results). Without a test, the error-dict shape and no-directory-creation
      guarantee were unprotected under AC-3.
    decision: fixed
    fix: "Added test_traverse_missing_palace_no_embedder: guards embedder, calls traverse('some_room', config=_TestConfig(missing)), asserts error dict returned and directory not created."

  - id: F-4
    title: "RISK-1 mitigation not implemented in layers.py for missing-palace message"
    severity: info
    location: "mempalace_code/layers.py:92"
    claim: |
      The plan's RISK-1 identified that read_only=True returning a stub instead of
      raising could change a missing-palace response from "No palace found. Run:
      mempalace-code mine <dir>" to "No memories yet." However, investigation shows
      that before the fix, lancedb.connect() creates the lance/ directory without
      raising, so the outer except block was already unreachable in the typical
      case. The "No palace found" message was effectively dead code for LanceDB
      prior to the fix. After the fix: same "No memories yet" message is shown for
      missing palaces, and the spurious directory-creation side effect is
      eliminated. The MCP path handles this correctly via runtime._get_store()'s
      explicit _db is None check. No behavior regression in practice.
    decision: dismissed
    fix: ~

totals:
  fixed: 2
  backlogged: 0
  dismissed: 2
fixes_applied:
  - "tests/test_layers.py: added assert 'No drawers found' in text for empty palace recall test"
  - "tests/test_palace_graph.py: added test_traverse_missing_palace_no_embedder covering error dict shape and no directory creation"
new_backlog: []
