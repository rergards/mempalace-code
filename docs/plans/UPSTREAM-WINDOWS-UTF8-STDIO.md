---
slug: UPSTREAM-WINDOWS-UTF8-STDIO
status: completed
authority: non_authoritative
goal: "Normalize Windows CLI and MCP stdio to UTF-8 without changing non-Windows behavior"
risk: medium
risk_note: "Entry-point stdio and MCP JSON serialization affect user-visible output and JSON-RPC framing."
files:
  - path: mempalace_code/_stdio.py
    change: "Add shared Windows-only UTF-8 stdio reconfiguration helper with explicit per-stream error policies and per-stream failure handling."
  - path: mempalace_code/cli.py
    change: "Call the shared helper at CLI startup through a thin CLI policy wrapper using surrogateescape stdin and replace stdout/stderr."
  - path: mempalace_code/mcp/dispatch.py
    change: "Call the shared helper before MCP argparse/stdio handling and preserve non-ASCII text in JSON-RPC output."
  - path: tests/test_stdio.py
    change: "Add platform-monkeypatched tests for Windows policies, non-Windows no-op behavior, failing stream fallback, and MCP non-ASCII output."
acceptance:
  - id: AC-1
    when: "the CLI stdio wrapper runs with sys.platform patched to win32 and fake stdin/stdout/stderr streams exposing reconfigure()"
    then: "stdin is reconfigured to encoding=utf-8 errors=surrogateescape and stdout/stderr are reconfigured to encoding=utf-8 errors=replace"
  - id: AC-2
    when: "the MCP main loop handles a tool response containing Cyrillic and CJK text with sys.platform patched to win32"
    then: "captured stdout is valid one-line JSON-RPC and contains the original non-ASCII characters rather than ASCII-only escapes or mojibake"
  - id: AC-3
    when: "a Windows stream object raises OSError from reconfigure()"
    then: "the helper records or reports the failed stream and continues reconfiguring remaining streams without propagating the exception"
  - id: AC-4
    when: "the shared helper runs with sys.platform patched to linux and fake streams exposing reconfigure()"
    then: "no stdin/stdout/stderr reconfigure call is made"
out_of_scope:
  - "Changing storage, search ranking, or drawer content normalization."
  - "Adding a real Windows CI runner or changing hosted workflow matrices."
  - "Backlog completion, backlog archive files, or bookkeep-owned metadata."
contract_policy:
  flow: full_spdd
  reason: "standard task changes CLI and MCP entry-point behavior plus protocol text handling"
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Windows CLI startup must reconfigure stdio to UTF-8 with explicit input and output error policies."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-3, AC-4]
    - id: REQ-2
      statement: "Windows MCP stdio startup must not corrupt or fail non-ASCII JSON-RPC request/response text solely because the process inherited a legacy code page."
      source: "backlog description"
      acceptance_ids: [AC-2, AC-3, AC-4]
    - id: REQ-3
      statement: "Non-Windows platforms must keep existing stdio behavior."
      source: "backlog description"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Shared stdio helper"
      kind: "internal"
      paths: ["mempalace_code/_stdio.py"]
      expected_behavior: "Provide a single Windows-only helper that applies UTF-8 reconfigure calls per stream and handles individual stream failures."
    - name: "CLI entry point"
      kind: "cli"
      paths: ["mempalace_code/cli.py"]
      expected_behavior: "Apply the shared helper before argparse command execution without changing command routing or parser semantics."
    - name: "MCP stdio server"
      kind: "api"
      paths: ["mempalace_code/mcp/dispatch.py"]
      expected_behavior: "Apply the shared helper before reading stdin/writing stdout and serialize JSON-RPC with non-ASCII text preserved."
    - name: "Focused stdio tests"
      kind: "internal"
      paths: ["tests/test_stdio.py"]
      expected_behavior: "Simulate Windows and non-Windows streams without requiring a Windows runner."
  invariants:
    - id: INV-1
      statement: "The helper must be a no-op when sys.platform is not win32."
      applies_to: ["mempalace_code/_stdio.py", "mempalace_code/cli.py", "mempalace_code/mcp/dispatch.py"]
    - id: INV-2
      statement: "CLI import and command dispatch contracts must remain unchanged apart from stdio setup at main() startup."
      applies_to: ["mempalace_code/cli.py"]
    - id: INV-3
      statement: "MCP stdout must continue to contain only JSON-RPC response lines from the protocol loop."
      applies_to: ["mempalace_code/mcp/dispatch.py"]
  risks:
    - id: RISK-1
      risk: "Changing MCP JSON serialization can break framing or turn protocol output into invalid JSON."
      mitigation: "Add a focused MCP loop test that parses the captured stdout line as JSON and asserts original non-ASCII text is present."
    - id: RISK-2
      risk: "Replaced or test-harness stdio streams may lack working reconfigure() and crash entry-point startup."
      mitigation: "Keep reconfigure failure handling per stream and test a raising stream continues with the remaining streams."
    - id: RISK-3
      risk: "A Windows-only fix could accidentally mutate macOS/Linux stdio behavior."
      mitigation: "Gate on sys.platform == win32 and test the non-Windows no-op path."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_stdio.py -q"
      proves: "simulated Windows policies, reconfigure failure handling, MCP non-ASCII JSON output, and non-Windows no-op behavior"
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      command: "python -m pytest tests/test_cli_command_modules.py tests/test_mcp_registry.py -q"
      proves: "public CLI and MCP import/registry contracts still hold after entry-point wiring"
      acceptance_ids: [AC-1, AC-2]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_stdio.py tests/test_cli_command_modules.py tests/test_mcp_registry.py -q"
        proves: "focused stdio behavior remains correct while existing CLI/MCP entry-point contracts stay intact"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Use upstream `v3.3.5:mempalace/_stdio.py` as the source pattern, adapted to `mempalace_code/_stdio.py`.
- Keep the helper Windows-only. It should return immediately unless `sys.platform == "win32"`.
- Use a CLI wrapper in `mempalace_code/cli.py` so tests can assert CLI-specific policies without running the full parser.
- CLI policy: `stdin` uses `surrogateescape`; `stdout` and `stderr` use `replace`, matching upstream's drawer-text safety for printable user content.
- MCP policy should also be explicit at the dispatch entry point before the stdio loop. Preserve real Cyrillic/CJK JSON text by using `ensure_ascii=False` for the tool result text and the outer JSON-RPC line.
- Do not reconfigure stdio at import time. Direct imports of `mempalace_code.cli` and `mempalace_code.mcp_server` should remain lightweight and side-effect-minimal; the entry-point `main()` functions own the setup.
- Tests should use fake stream objects with `reconfigure()` call recording and monkeypatch `sys.platform`; no Windows runner is required.
