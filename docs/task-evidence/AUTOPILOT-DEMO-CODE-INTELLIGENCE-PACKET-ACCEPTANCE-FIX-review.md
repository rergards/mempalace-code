# Task Evidence: AUTOPILOT-DEMO-CODE-INTELLIGENCE-PACKET-ACCEPTANCE-FIX

Public-safe synthesis of the hardening finding raised during the acceptance-fix
task. The finding was fixed in the same task and verified by focused tests. This
file replaces the local-only audit artifact for durable tracked evidence.

---

## F-1 - Fewer-than-expected MCP responses needed explicit regression coverage

**Severity**: medium
**Location**: `tests/test_code_intelligence_packet.py` - `TestMcpExchangeValidation`

**Finding**: The implementation changed the MCP response-count guard from a
one-sided fewer-than-expected check to an exact-count check paired with
`zip(..., strict=True)`. The new invariant rejects both extra and missing
responses, but only the extra-response path initially had a dedicated regression
test.

**Decision**: fixed

**Fix applied**:
- Added `test_raises_on_fewer_mcp_responses`.
- The test supplies two responses for three requests and asserts that the MCP
  exchange raises `RuntimeError` with a response-count diagnostic.
- This covers the fewer-than-expected branch of the exact-count MCP guard.

---

## Verification boundary

Focused verification after the task:

- `python scripts/gen_code_intelligence_packet.py --check` passed.
- `python -m pytest tests/test_code_intelligence_packet.py -x -q` passed with 66
  tests.
- `python scripts/quality_scorecard.py --check` passed.
- Focused Ruff check and format commands passed for the packet generator,
  packet tests, quality scorecard script, and scorecard tests.

Raw `python scripts/public_safety_scan.py --tracked` remains a repository-level
failure because of pre-existing tracked local-only artifacts outside this task.
This acceptance-fix task must not add its own `.tasks/` or `docs/audits/`
findings to that output.
