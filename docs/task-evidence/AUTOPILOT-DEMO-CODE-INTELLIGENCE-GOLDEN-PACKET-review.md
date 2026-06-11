# Task Evidence: AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET

Public-safe synthesis of plan-review findings for the golden-packet implementation
task. Findings F-1 and F-2 were surfaced during the hardening round, fixed in the
same task, and verified by focused tests. This file is the durable evidence record.

---

## F-1 — Public-safety gate missed generic temp paths and secret-like token prefixes

**Severity**: high
**Location**: `scripts/gen_code_intelligence_packet.py` — `_PRIVATE_PATH_RE` and
`_public_safety_check`

**Finding**: The original `_PRIVATE_PATH_RE` covered only macOS/Linux home directories
and macOS temp dirs (`/var/folders`). Generic `/tmp/` and `/srv/` absolute paths, as
well as common API key prefixes (classic PAT prefix, fine-grained PAT prefix, PyPI
upload token prefix, and OpenAI/Anthropic key prefixes), would pass
`_public_safety_check()` undetected. A normalization defect leaving any temp path in
the committed packet JSON would constitute a public-safety violation.

**Decision**: fixed

**Fix applied**:
- Extended `_PRIVATE_PATH_RE` with `/tmp/\S+` and `/srv/\S+` alternates.
- Added `_SECRET_TOKEN_RE` covering common API key prefixes (classic PAT, fine-grained
  PAT, PyPI upload token, OpenAI, and Anthropic patterns).
- Updated `_public_safety_check()` to also search `_SECRET_TOKEN_RE` and raise
  `PublicSafetyError` on a match.
- Added 7 focused tests in `TestPublicSafetyCheckExtended` covering all new patterns.

---

## F-2 — CLI and MCP subprocess failures silently become successful packet exhibits

**Severity**: medium
**Location**: `scripts/gen_code_intelligence_packet.py` — `_run_cli` (line ~593) and
`_mcp_exchange` (line ~685)

**Finding**: `_run_cli()` did not check the subprocess returncode; a failed
`mine`/`search`/`read` command returned partial stdout and proceeded to packet
assembly. `_mcp_exchange()` similarly did not check `proc.returncode`, and only
required that 3 JSON lines were parsed — a JSON-RPC error response or an id-mismatched
response would be silently accepted as a successful exhibit.

**Decision**: fixed

**Fix applied**:
- `_run_cli()`: added a `returncode != 0` guard that raises `RuntimeError` with exit
  code and stderr snippet before stdout is consumed.
- `_mcp_exchange()`: added `proc.returncode != 0` guard (before response parsing), then
  a per-response loop that raises `RuntimeError` if any response id does not match its
  request id, or if any response contains an `"error"` key.
- Added 5 focused mock-based tests in `TestRunCliReturncode` and
  `TestMcpExchangeValidation` covering: nonzero CLI exit, zero exit (positive path),
  nonzero MCP exit, JSON-RPC error response, and id mismatch.

---

## Verification boundary

Tests run: `python -m pytest tests/test_code_intelligence_packet.py` — 62 tests
(after F-1 and F-2 fixes) passing across normalization, known-answer, schema, packet
comparison, public-safety rejection, fixture creation, CLI returncode, and MCP exchange
validation.

The generator `--check` mode was not run as a CI step; it is explicitly a manual
pre-release gate that requires the embedding model to be cached and takes 20-60 s.
