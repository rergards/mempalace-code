verdict: READY

gaps: []

notes:
  - All four acceptance criteria are observable through monkeypatched sys.platform and fake streams with reconfigure() recorders; no test requires a real Windows runner.
  - File list matches the actual layout: cli.py has main() at line 69; the MCP main loop and json.dumps sites are in mempalace_code/mcp/dispatch.py (lines 101 and 204); mcp_server.py is just a re-export shim that delegates to dispatch.main, so targeting dispatch.py is correct.
  - task_contract is present with mode=standard. All requirements (REQ-1..REQ-3) map to acceptance IDs; all acceptance IDs (AC-1..AC-4) map to VER-1 (and AC-1/AC-2 additionally to VER-2 for entry-point contract regression). All acceptance IDs are covered by regression_plan.checks (REG-1). All verification and regression commands are runnable pytest invocations, not prose.
  - contract_policy is present with flow=full_spdd, sync_gate=required, verification_path=automated, and a reason string.
  - regression_plan.applies=true with a non-empty checks list covering all ACs.
  - Surfaces, invariants, and risks align with the change: helper is sys.platform-gated, CLI/MCP setups are confined to main(), MCP JSON framing risk is explicitly mitigated by a parse-stdout test, and per-stream reconfigure failure is mitigated by isolated try/except per stream with AC-3 covering the failure path.
  - Design Notes explicitly forbid import-time stdio mutation, preserving the existing lightweight-import contract for mempalace_code.cli and mempalace_code.mcp_server.
  - out_of_scope correctly excludes backlog/bookkeep metadata; no backlog files are listed as touched files or surfaces.
