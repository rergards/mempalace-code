slug: AUTOPILOT-DEMO-MCP-STDIO-CONTRACTS
round: 1
date: 2026-06-19
commit_range: 5a50404..07dded0
findings:
  - id: F-1
    title: "Missing _assert_no_model_noise in three of five contract tests"
    severity: low
    location: "tests/test_mcp_server.py:3846,3946,3993"
    claim: >
      test_default_full_profile_tools_list_over_stdio,
      test_include_exclude_profile_tools_list_over_stdio, and
      test_hidden_profile_tool_call_errors_over_stdio each run a real stdio
      subprocess with HF_HUB_OFFLINE=1 but do not call _assert_no_model_noise
      after capturing stdout/stderr. RISK-1 mitigation (plan section) explicitly
      requires asserting no model-loading markers on all profile/list/status paths;
      the omission means a model-load regression would be silent in three tests.
    decision: fixed
    fix: >
      Added _assert_no_model_noise(stdout, stderr) at the end of each of the
      three affected tests, before the finally cleanup block, matching the
      pattern already used in test_minimal_profile_status_call_over_stdio and
      in TestDeleteAfterReadOfflineNoEmbedder.
totals:
  fixed: 1
  backlogged: 0
  dismissed: 0
fixes_applied:
  - "Added _assert_no_model_noise(stdout, stderr) to test_default_full_profile_tools_list_over_stdio, test_include_exclude_profile_tools_list_over_stdio, and test_hidden_profile_tool_call_errors_over_stdio"
new_backlog: []
