# Ship — Verify, Fix, Push Loop

Autonomous loop: local verify -> fix -> push to origin.

**Prerequisite:** Must be on `main` branch with clean working tree or committed changes ready to push.

## Phase 1: Local Verification

Run `/verify`. If it fails:

1. Analyze failures
2. Fix code issues (lint errors, test failures)
3. Re-run only the failed checks to confirm fixes
4. Loop until all local checks pass

**Time-box:** If a fix requires more than 3 attempts or touches > 5 files, stop and report to the user rather than spiralling.

## Phase 2: Commit & Push

1. Follow the shared commit checkpoint procedure in `.claude/skills/_shared/commit-checkpoint.md`:
   - Read edit log, cross-reference git status, stage explicitly, review diff, commit, post-commit verify.
   - Commit message format: `fix: <descriptive message for the verify fixes>`
2. Save verify baseline: `git rev-parse HEAD > .verify-state`
3. Push to origin: `git push origin main`

## Phase 3: Verify Push Success

```bash
git log --oneline origin/main -1
git log --oneline main -1
```

Confirm both match. If push failed (rejected, auth error), report to user.

## Phase 4: Report

Output a summary:

```
## Ship Complete

Local: PASS (N tests, lint clean)
Push: SUCCESS to origin/main

Commits shipped:
- <sha> <message>

Issues fixed during ship:
- <description of each fix>
```

## Abort Conditions

Stop and report to the user if any of these occur:
- More than 3 fix cycles for the same failure
- A failure that requires architectural changes (> 5 files)
- Push authentication issues
- Tests that consistently fail (environment mismatch)
