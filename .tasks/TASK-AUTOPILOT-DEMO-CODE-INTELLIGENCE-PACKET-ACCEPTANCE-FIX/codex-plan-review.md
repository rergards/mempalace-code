verdict: NEEDS_CHANGES

## Summary

The plan is well-grounded against current repo state. I verified its core premises:

- The fallback stub exists with `# fallback: backlog-recovery` on line 1 of
  `docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET.md`, so VER-7's negative assert
  targets a real current string.
- `docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-round-1.md` is git-tracked despite
  `docs/audits/` being in `.gitignore` (line 43), and it contains the F-1/F-2 findings that VER-7
  expects in the relocated evidence file.
- The B905 violation is real and currently failing: `ruff check` reports exactly one issue,
  `scripts/gen_code_intelligence_packet.py:739:37 B905` on `zip(requests, responses)`, and rule
  family "B" is selected in `pyproject.toml:79`. `ruff format --check` also currently fails on the
  generator, so AC-10 covers a real current failure.
- The MCP exchange currently checks only `len(responses) < 3`, so an extra response is silently
  truncated by the zip — AC-4's new failure test targets real behavior.
- `scripts/public_safety_scan.py` supports `--tracked` (line 221); `scripts/quality_scorecard.py`
  supports `--check` and currently exits 0; the packet test slice currently passes (62 tests).
- The tracked scan currently flags this task's audit file (github-pat-prefix ×2 +
  local-only-artifact-path) and the generator at `scripts/gen_code_intelligence_packet.py:385`
  (the literal `ghp_` prefix inside `_SECRET_TOKEN_RE`), matching the plan's remediation targets.
  The test file is NOT currently flagged, so test rewording is precautionary only.
- `task_contract`, `contract_policy` (flow: full_spdd, sync_gate: required, verification_path:
  automated) are present; every AC has a VER row; backlog files are explicitly out of scope; all
  verification commands are runnable shell commands grounded in the root-level repo layout.

Two high-severity gaps remain, both fixable with small plan edits.

gaps:
  - severity: high
    claim: "AC-9/VER-9/REG-6 fail by construction against current repo state: the needle 'AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET' matches two pre-existing tracked files the plan does not remove — '.tasks/TASK-AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET/harden-result.json' and 'harden-scope.json' — which appear in 'python scripts/public_safety_scan.py --tracked' output as local-only-artifact-path findings. Even after the audit file is deleted and the generator regex is encoded, the substring check 'n in out' will hit these paths and sys.exit(1)."
    evidence: "Plan AC-9 (lines 55-56), VER-9 (lines 208-211), REG-6 (lines 240-243); verified live: 'git ls-files .tasks/' shows both files tracked, and the current scan output contains 'tracked:.tasks/TASK-AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET/harden-result.json:1:1: local-only-artifact-path' (+ harden-scope.json)."
    suggested_fix: "Path-anchor the needles to the surfaces this task owns, e.g. ('docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET', 'docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET', 'docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE', 'tracked:scripts/gen_code_intelligence_packet.py') — OR explicitly add removal of the two tracked .tasks/TASK-AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET/ files to the plan's file list. As written, the boundary command contradicts current repo evidence (verification command context preflight failure)."

  - severity: high
    claim: "AC-7 has no corresponding regression_plan.checks row. REG-1 covers AC-1/AC-3/AC-4/AC-6, REG-2 covers AC-2, REG-3 covers AC-5, REG-4 covers AC-10, REG-5 covers AC-8, REG-6 covers AC-9 — AC-7 (durable plan replaced, evidence present, audit artifact gone) is linked to no regression check."
    evidence: "Plan regression_plan.checks (lines 219-243): no check row lists AC-7 in acceptance_ids."
    suggested_fix: "Add a REG-7 row reusing the VER-7 python -c command with acceptance_ids: [AC-7]."

  - severity: medium
    claim: "The needle 'AUTOPILOT-DEMO-CODE-INTELLIGENCE-PACKET-ACCEPTANCE-FIX' in AC-9/VER-9/REG-6 will also self-trip if any of this task's own .tasks/TASK-AUTOPILOT-DEMO-CODE-INTELLIGENCE-PACKET-ACCEPTANCE-FIX/* artifacts get committed during the autopilot flow — there is direct precedent: the prior golden-packet task's harden-result.json/harden-scope.json were committed and are flagged today. The check would then fail at verify time for reasons outside the implementation's control."
    evidence: "Current tracked scan output flags .tasks/TASK-AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET/harden-*.json; this task's .tasks directory already exists in the worktree and receives phase artifacts (including this review file)."
    suggested_fix: "Same as gap 1: path-anchor needles to docs/ and scripts/ surfaces (e.g. prefix-match on 'tracked:docs/...' / 'tracked:scripts/...') instead of bare task slugs, so phase-artifact commits cannot trip the boundary."

  - severity: low
    claim: "INV-4's applies_to is incoherent with its statement: the invariant says backlog metadata and archive files stay bookkeep-owned and unedited, but applies_to lists docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET.md and docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md — the two files the plan explicitly edits/creates."
    evidence: "Plan lines 148-152 (INV-4)."
    suggested_fix: "Point INV-4 applies_to at docs/BACKLOG.yaml and docs/BACKLOG-archived.yaml (the files the statement actually constrains), or reword the statement."

## Notes (non-gaps, verified)

- AC-2's `gen_code_intelligence_packet.py --check` is a real flag and the committed artifacts were
  previously generated in an equivalent autopilot worktree, so regeneration is feasible here; the
  plan correctly names it a manual gate (slow, needs cached embeddings) and keeps it out of
  /verify per INV-2.
- Encoding the `ghp_` literal in `_SECRET_TOKEN_RE` (e.g. string concatenation) is feasible
  without weakening the regex's runtime behavior; the scanner's github-pat-prefix rule matches the
  source literal, not the compiled pattern.
- The scorecard's `_VERIFICATION_COMMANDS` table is drift-tested against
  `.claude/skills/verify/INSTRUCTIONS.md`; the plan's wording changes target the suite description
  (`code_intelligence_packet`, scripts/quality_scorecard.py:89-92), not the command table, so no
  drift-test conflict.
- File list is otherwise complete: new tests change scorecard counts → scorecard.{json,md}
  regeneration is listed; generator changes → docs/demo artifacts regeneration is listed;
  docs/task-evidence/ does not exist yet and is created by the plan.
