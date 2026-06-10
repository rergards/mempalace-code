slug: AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET
round: 1
date: 2026-06-11
commit_range: d403f36..HEAD
findings:
  - id: F-1
    title: "Public-safety gate misses /tmp/, /srv/, and secret-like token patterns"
    severity: high
    location: "scripts/gen_code_intelligence_packet.py:368"
    claim: >
      _PRIVATE_PATH_RE only covered macOS/Linux home dirs and macOS temp
      (/var/folders). Generic /tmp/ and /srv/ absolute paths, as well as
      common API key prefixes (sk-*, ghp_*, pypi-*), would pass
      _public_safety_check() undetected. A mis-normalization that left a
      /tmp/... path in the packet JSON would be committed to the public repo.
    decision: fixed
    fix: >
      Extended _PRIVATE_PATH_RE with /tmp/\S+ and /srv/\S+ alternates.
      Added _SECRET_TOKEN_RE covering GitHub PATs (ghp_, github_pat_),
      PyPI tokens (pypi-), and OpenAI/Anthropic keys (sk-*/sk-ant-*).
      Updated _public_safety_check() to also search _SECRET_TOKEN_RE and
      raise PublicSafetyError on a match. Added 7 focused tests in
      TestPublicSafetyCheckExtended covering all new patterns.

  - id: F-2
    title: "CLI and MCP subprocess failures silently become successful packet exhibits"
    severity: medium
    location: "scripts/gen_code_intelligence_packet.py:593,685"
    claim: >
      _run_cli() never checked subprocess returncode; a failed mine/search/read
      command would still return its partial stdout and proceed to packet
      assembly. _mcp_exchange() similarly did not check proc.returncode, and
      only required that 3 JSON lines were parsed — a JSON-RPC error response
      or a response with a mismatched id would be silently accepted as a
      successful exhibit.
    decision: fixed
    fix: >
      _run_cli(): added a returncode != 0 guard that raises RuntimeError with
      exit code and stderr snippet before the stdout is consumed.
      _mcp_exchange(): added proc.returncode != 0 guard (before response
      parsing), then a per-response loop that raises RuntimeError if any
      response id does not match its request id, or if any response contains
      an "error" key. Added 5 focused mock-based tests in TestRunCliReturncode
      and TestMcpExchangeValidation covering: nonzero CLI exit, zero exit
      (positive), nonzero MCP exit, JSON-RPC error response, and id mismatch.

totals:
  fixed: 2
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "Extended _PRIVATE_PATH_RE with /tmp/ and /srv/ path alternates"
  - "Added _SECRET_TOKEN_RE for common API key patterns (sk-*, ghp_*, github_pat_*, pypi-*)"
  - "Updated _public_safety_check() to raise on secret token matches"
  - "Added returncode check in _run_cli() — raises RuntimeError on non-zero exit"
  - "Added returncode check + per-response id/error validation in _mcp_exchange()"
  - "Added 12 new tests (TestPublicSafetyCheckExtended, TestRunCliReturncode, TestMcpExchangeValidation)"

new_backlog: []
