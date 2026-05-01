slug: EXPLAIN-NRESULTS-CLAMP
round: 1
date: 2026-05-01
commit_range: aabf1a5..HEAD
findings:
  - id: F-1
    title: "No boundary test for the upper clamp at n_results > 50"
    severity: info
    location: "tests/test_mcp_server.py:1421-1466"
    claim: >
      The hardening AC list calls for boundary tests, but the new tests cover only the
      lower edge (n_results=1, 0, -1). There is no test that calls
      tool_explain_subsystem with n_results=51 (or 100) to assert that the clamp at
      mempalace/mcp_server.py:688 caps at 50. The defence-in-depth value is small —
      code_search() applies its own max(1, min(50, n)) clamp at searcher.py:248 and
      that path is exercised elsewhere — but the assertion that the explain layer
      itself caps would require either seeding ≥51 code chunks (the shared
      code_seeded_collection has 5) or spying on the code_search call. Both options
      add fixture/mocking complexity for a guard that mirrors the searcher's existing
      coverage.
    decision: dismissed

  - id: F-2
    title: "n_results=0/-1 tests rely on semantic similarity for query='code' rather than a direct lexical hit"
    severity: info
    location: "tests/test_mcp_server.py:1428,1440,1452"
    claim: >
      The three new boundary tests call tool_explain_subsystem(query='code', ...) and
      assert len(entry_points) == 1. None of the documents in code_seeded_collection
      contains the literal token 'code'; the assertion holds because all-MiniLM-L6-v2
      finds a code-shaped chunk semantically similar to the query. If the embedding
      model is swapped under the no-regression rule and the closest hit drops below the
      retrieval cutoff, these tests would fail in a way that looks like a clamp
      regression rather than an embedding regression. The risk is bounded — any model
      that fails to retrieve any code-shaped chunk for 'code' would also fail many
      other tests — and the assertion shape (len == 1) is exactly what proves clamping
      worked, so a stronger query would still need at least one match. Documented for
      completeness.
    decision: dismissed

  - id: F-3
    title: "Clamp silently coerces invalid input with no diagnostic"
    severity: info
    location: "mempalace/mcp_server.py:688"
    claim: >
      n_results = max(1, min(50, n_results)) silently rewrites caller input. A caller
      passing n_results=0 has almost certainly made a mistake (or is iterating over a
      range that includes 0), and the tool returns a single result instead of either
      erroring or signalling the coercion. This matches the existing convention in
      code_search() at searcher.py:248, which is also silent, so changing only the
      explain layer would fragment behaviour. Logging the coercion is also unhelpful
      because MCP tool responses are not log-buffered for the caller. Behaviour is
      consistent with the rest of the codebase; no action.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 3

fixes_applied: []

new_backlog: []
