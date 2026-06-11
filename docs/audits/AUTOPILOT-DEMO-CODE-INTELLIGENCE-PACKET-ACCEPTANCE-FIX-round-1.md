slug: AUTOPILOT-DEMO-CODE-INTELLIGENCE-PACKET-ACCEPTANCE-FIX
round: 1
date: 2026-06-11
commit_range: d1bd4cb..680870f
findings:
  - id: F-1
    title: "No regression test for fewer-than-expected MCP responses after !=/strict-zip change"
    severity: medium
    location: "tests/test_code_intelligence_packet.py:602"
    claim: >
      The implementation changed the MCP response-count guard from `len(responses) < 3`
      to `len(responses) != len(requests)` and added `zip(..., strict=True)`, which is
      symmetric: both extra AND fewer responses raise. A new test was added only for the
      extra-response path (`test_raises_on_extra_mcp_response`). The fewer-response path
      (previously the only guarded direction) had no dedicated test, leaving the symmetric
      invariant half-covered and creating a silent regression risk if the guard is changed again.
    decision: fixed
    fix: >
      Added `test_raises_on_fewer_mcp_responses` to `TestMcpExchangeValidation`. The test
      passes two of the three good responses and asserts `RuntimeError` with match="responses",
      covering the `len(responses) != len(requests)` branch for the fewer-than-expected case.

totals:
  fixed: 1
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "Added test_raises_on_fewer_mcp_responses to TestMcpExchangeValidation to cover the
    fewer-response branch of the !=/strict-zip MCP count guard."

new_backlog: []
