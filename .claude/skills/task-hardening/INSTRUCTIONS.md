# Task Hardening Workflow

Use this skill instead of manually pasting the hardening prompt after implementation.

Before doing anything, classify the task using the 5-axis triage in `.claude/skills/_shared/mode-classification.md`.
Hardening should classify from the actual diff and touched boundaries, not the original task size marker.

- `lite`: small low-risk work. No Codex by default.
- `standard`: non-trivial but bounded work. Codex on round 1 only by default.
- `strict`: high-risk or cross-boundary work. Codex on round 1 is required; later Codex passes are conditional, not automatic.

Treat these as sensitive boundaries for Codex escalation on later rounds: storage operations, embedding model changes, MCP tool contracts, CLI breaking changes, backup/restore paths.

## Expected Input

Invoke with:
- task slug
- feature name
- feature scope
- optional round number

Example:

```text
/task-hardening MINE-CSHARP "C# Language Support" "miner"
```

If the round is not provided, detect the next round automatically.

## Workflow

1. Initialize task state per `.claude/skills/_shared/task-state.md` — write `/tmp/claude-task-state-<SLUG>.json` with task slug, skill name, phase = "started". Update `modified_files`, `decisions`, and `phase` throughout the workflow.

2. Determine the round number if it was omitted, then classify the task as `lite`, `standard`, or `strict` from the real change surface:
   - review the current diff and changed files first
   - apply the 5-axis triage and decision rule from `.claude/skills/_shared/mode-classification.md`

3. Codex hardening policy:
   - `lite`: skip by default
   - `standard`: run on round 1 only by default
   - `strict`: run on round 1; for round 2+ rerun only if unresolved P1/P2 remain, the previous fixes touched sensitive boundaries again, or the user explicitly asked for another Codex pass

If Codex should run for this round:

```bash
./scripts/codex-review.sh --show-output hardening <task-slug> "<feature name>" "<feature scope>" <round>
```

4. **Enter Claude plan mode** (`EnterPlanMode`) before executing the hardening prompt for `standard` and `strict` tasks. Use plan mode to:
   - review the current diff and changed files
   - trace touched boundaries and shared code paths
   - identify regression risks and missing test coverage
   - prioritize findings by severity before implementing fixes
   - present the hardening approach for user approval

   Skip plan mode only when: running in `claude -p` (non-interactive), OR the task is `lite`.

5. After exiting plan mode, execute the hardening round:
   - Review current diff first.
   - Use Codex output as candidate leads, not as truth.
   - **Triage every finding before acting** (mandatory for all modes):
     - Score each finding on three axes:
       - **(a) Real bug vs style nit?** Does this cause incorrect behavior, data loss, or security exposure? Or is it a naming preference, formatting issue, or theoretical concern?
       - **(b) Can it happen in production?** Is there a realistic code path that triggers this? Or does it require conditions that the codebase structurally prevents?
       - **(c) Is there a test that would catch it?** If a regression test exists or could exist, prioritize adding the test. If the finding is untestable, it's likely speculative.
     - **Simplicity tiebreaker** (for borderline 2/3 scores): Does the proposed fix add disproportionate complexity relative to the risk?
     - **Triage decision:**
       - Score >= 2/3 (at least two axes positive): implement fix + add regression test.
       - Score 1/3: add to `docs/BACKLOG.yaml` with origin context. Do NOT spend implementation effort.
       - Score 0/3: dismiss with one-line justification in the round report. Do NOT backlog.
     - Record the triage decision for each finding in the round report. Format: `Finding | Score | Decision (fix/backlog/dismiss) | Reason`.
   - Implement only the triaged-in fixes (score >= 2/3). Add regression tests for each.
   - Write the canonical round report to `docs/audits/<slug>-round-<n>.md`.

6. Backlog and resolve out-of-scope findings:
   - For every finding dismissed as pre-existing, out of scope, or deferred: either fix it on the spot if it is truly trivial, or add/update a backlog entry with origin context.
   - Prefer updating an existing backlog item over adding a duplicate.

7. Default stopping rule:
   - Finish one round.
   - Stop with a convergence decision and the smallest recommended next focus.
   - Do not automatically start another round unless the user explicitly asked for looping.

8. **Update backlog and commit (mandatory — do not wait for the user to ask):**
    - Update `docs/BACKLOG.yaml` with hardening convergence status.
    - Follow the shared commit checkpoint procedure in `.claude/skills/_shared/commit-checkpoint.md`:
      - Read edit log, cross-reference git status, stage explicitly, review diff, commit, post-commit verify.
    - Expected files to stage: `docs/audits/<slug>-round-<n>.md`, `docs/BACKLOG.yaml`, `.tasks/TASK-<slug>/`, `.protocols/TASK-<slug>/`, and any hardening fix files.
    - Commit message format: `chore(<slug>): hardening R<n> — <converged|findings backlogged>`

## Rules

- Canonical round report remains in `docs/audits/`.
- Codex output remains supporting evidence in `.tasks/TASK-<slug>/`.
- Prefer no finding over a weak finding.
- If Codex cannot run because auth is missing, report that briefly and continue the hardening round.
- Every dismissed or deferred material finding must be either fixed in-round or backlogged. Do not silently drop it.
- **Single Codex pass default**: In `standard` mode, run Codex once (round 1). A second pass requires concrete justification.
- **Doom-loop breaker**: If the same test or check fails twice with the same approach, STOP. Report findings + remaining hypotheses to the user rather than trying a third time.
- The original estimate or task-size label never overrides the actual diff.
- Step 5 triage is mandatory — every finding must be scored before implementation effort is spent.
- Step 8 (update backlog + commit) is mandatory — never finish a hardening round without it.
