verdict: READY

# Plan Review — MIRROR-PREFLIGHT-WRAPPER-DETECTION

## Summary
The plan is sound and ready to implement. Acceptance criteria are all expressed as
concrete `python -m pytest` invocations of named tests with observable exit codes and
stdout assertions. The design reuses the existing pure-inspection pipeline
(`shlex.split` → `_has_delete_semantics` / `_targets_state_dir` / exclude-family checks)
by inserting a normalization helper, which matches the module's documented principle
("No subprocess is ever created", mirror_preflight.py:1-4). The files list
(`mempalace_code/mirror_preflight.py`, `tests/test_cli.py`) is complete — the CLI handler
`cli_commands/preflight.py:13-18,44-45` already maps `parse_error → exit 2` and
`ok=False → exit 1`, so no handler change is needed since the wrapper logic lives entirely
inside `classify_mirror_command`.

## Contract canvas checks (all pass)
- `task_contract:` present (plan line 43). ✓
- No backlog metadata (`docs/BACKLOG.yaml`, archive files) listed in files/surfaces/touched
  files; `out_of_scope` explicitly excludes backlog/bookkeep state (lines 37). ✓
- Every `acceptance:` id (AC-1..AC-7) has a matching `verification:` row linked by
  `acceptance_ids` (VER-1..VER-7, lines 102-130). ✓
- All `verification:` and `regression_plan.checks` commands are runnable shell commands
  (`python -m pytest ...`); `verification_path: automated` — no prose/manual pseudo-commands. ✓
- `regression_plan.applies: true` with checks REG-1..REG-3; REG-1 links all of AC-1..AC-7. ✓
- `contract_policy` present with `flow: full_spdd`, `sync_gate: required`,
  `verification_path: automated` (lines 38-42). ✓
- Test names in each AC `when` exactly match the corresponding `verification` command. ✓
- The two existing tests cited in AC-7 confirmed present:
  `test_delete_mode_state_mirror_missing_excludes_exits_nonzero` (tests/test_cli.py:1176),
  `test_non_state_or_no_delete_commands_remain_ok` (tests/test_cli.py:1190); `TestMirrorDocs`
  present (tests/test_cli.py:1291). No name collisions with the new wrapped-variant tests. ✓

## Verified design feasibility
- AC-2 `sudo rsync -a --delete ~/.mempalace/ user@host:.mempalace/`: after normalization to
  effective tokens `rsync -a --delete ~/.mempalace/ ...`, the existing path yields
  `delete-mode-state-mirror-missing-excludes` with all four families missing — matches the
  asserted output. ✓
- AC-3 env + `--delete-excluded`: normalized tokens hit the `--delete-excluded` branch
  (mirror_preflight.py:120-129) → `delete-excluded-state-mirror`. ✓
- AC-6 nested malformed payload (`sh -c '...'` with an unbalanced inner quote): outer
  `shlex.split` succeeds, inner re-tokenization raises `ValueError`; the helper's error string
  must propagate to `PreflightResult(parse_error=...)` → CLI `sys.exit(2)`
  (cli_commands/preflight.py:13-18). The design note (plan line 152) specifies this return
  contract correctly. ✓

gaps:
  - severity: medium
    claim: "The 'merely mentions rsync' false-positive boundary is a stated requirement but has no dedicated test assertion. The design note requires `echo rsync --delete ~/.mempalace/` to remain OK and RISK-1 mitigates over-broad token scanning, yet no AC/verification pins this."
    evidence: "docs/plans/MIRROR-PREFLIGHT-WRAPPER-DETECTION.md:159 (design note) and lines 90-92 (RISK-1); AC-5 (test_wrapped_non_state_or_no_delete_commands_remain_ok) only covers wrapped rsync that is non-state or no-delete, not a non-wrapper command that mentions rsync, nor a wrapper resolving to a non-rsync command (e.g. `sudo cp ...`)."
    suggested_fix: "Extend the AC-5 test (or add a case to it) to assert that `echo rsync --delete ~/.mempalace/` and a wrapper-resolving-to-non-rsync command such as `sudo cp ~/.mempalace/ /dst/` both exit 0 / print OK, so the no-broad-scan mitigation is verified, not just asserted in prose."
  - severity: low
    claim: "The design supports both `sh -c` and `bash -c` wrappers, but only `sh -c` is exercised by an acceptance test."
    evidence: "docs/plans/MIRROR-PREFLIGHT-WRAPPER-DETECTION.md:157 (lists `sh -c`/`bash -c`); AC-4 (test_simple_shell_wrapped_delete_mode_state_mirror_is_classified) and VER-4 reference only the `sh -c` form."
    suggested_fix: "Add a `bash -c 'rsync ... --delete ~/.mempalace/ ...'` assertion within the AC-4 test, or note explicitly that `sh` and `bash` share one code path so a single shell variant suffices."
