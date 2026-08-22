# Commit Checkpoint — Shared Procedure

Owns staging, commit, and amend admission for all skills. Calling a skill,
reviewing a diff, planning, verification, or approving one Git action does not
authorize another action.

## Read-Only Admission

Run admission before requesting mutation authority, in this order:

1. Resolve the exact repository root and Git directory. Stop on an unknown,
   mismatched, linked-to-an-unexpected-repository, or non-Git target.
2. Read `HEAD`, branch, `git status --porcelain`, unstaged diff, staged diff,
   `/tmp/claude-edits.log`, and the admitted task state. State the exact intended
   paths; preserve unrelated or owner-unknown changes.
   Reconcile the edit log, task state, and Git path sets explicitly:

   ```bash
   if [ -f /tmp/claude-edits.log ]; then
     sed -n '/Modified:/s/.*Modified: //p' /tmp/claude-edits.log | sort -u
   fi
   if [ -n "${AUTOPILOT_TASK_STATE:-}" ]; then
     state_file="$AUTOPILOT_TASK_STATE"
   elif [ -n "${task_slug:-}" ]; then
     state_file="/tmp/claude-task-state-${task_slug}.json"
   else
     echo "ERROR: exact task state path or task slug required" >&2
     exit 1
   fi
   if [ -e "$state_file" ]; then
     if ! python -c 'import json, sys; from pathlib import Path; files = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["modified_files"]; valid = isinstance(files, list) and all(isinstance(item, str) for item in files); sys.exit(1) if not valid else print(*sorted(set(files)), sep="\n")' "$state_file" 2>/dev/null; then
       echo "ERROR: invalid task state" >&2
       exit 1
     fi
   fi
   git diff --name-only && git diff --name-only --cached
   git status --porcelain
   ```

   Compare the exact lists. An edit-log path absent from Git state must be
   investigated before staging; a Git path absent from the edit log must be
   verified as intentional or treated as owner-unknown. If another agent has
   an uncommitted edit to an intended path, stop and coordinate; do not
   overwrite or stage that path.
3. Resolve the live owner. Inside the owning provider require
   `phase_write_allowed=true`; for an operator require `safe_to_edit=true`.
   Active, stale, contradictory, or unknown ownership stops before staging.
4. For a remote action, bind the literal remote name, URL, full destination ref,
   and 40-hex local SHA. Normalize the URL to `owner/repository`. For GitHub,
   require `gh repo view --json nameWithOwner,isPrivate`; `nameWithOwner` must
   equal the normalized identity and `isPrivate` must match the declared target.
   Unknown identity, visibility, ref, or SHA stops before authority is requested.
5. State the exact staged content and exact commit message or amend command.
   Re-read the index and `HEAD` immediately before requesting authority.

Public targets and release intent leave this checkpoint read-only and route to
`.claude/skills/release/SKILL.md`. This procedure never substitutes for release
admission or publication authority.

Before staging any public diff, run the canonical safety scan:

```bash
python scripts/public_safety_scan.py --tracked --staged
```

Review any reported false positive explicitly. Never publish raw review logs,
private benchmark results, local absolute paths, private remotes, or
customer/project identifiers.

## Mutation Admission

Request a separate current authority immediately before each mutation:

- staging authority: exact repository, observed `HEAD`, observed status, and
  complete path list;
- commit authority: exact repository, index tree, parent SHA, and message;
- amend authority: exact repository, current `HEAD`, replacement index tree,
  complete command, and message;
- ordinary-push authority: exact repository, remote identity, visibility, full
  destination ref, local SHA, observed remote SHA, and exact push command.

An authority token is valid for one named mutation attempt only.
It is consumed when the command starts, including failure or ambiguous outcome. It is invalid
after any path, index, `HEAD`, owner, remote, ref, SHA, visibility, command,
message, or observed state changes. Authority never carries across steps,
retries, reordered commands, invocations, repositories, or skills.

## Execute One Authorized Action

For staging, use `git add -- <exact paths>` only. Never use `git add .` or
`git add -A`. Inspect `git diff --cached --name-only` and the staged patch after
the attempt.

For commit or amend, execute only the authorized command, then inspect `HEAD`,
the index, status, and commit contents. If the outcome is ambiguous, do not
retry. Read post-state, report it, and request fresh authority for the one
remaining action.

Local evidence such as `.tasks/`, `.protocols/`, `docs/audits/`, task state, and
provider output stays unstaged unless separate tracked-publication authority
names the exact sanitized paths. Never clear local evidence as part of commit or
amend authority.

## Result

Report admitted predicates, the exact action attempted, its post-state, and any
remaining action. Do not automatically stage, commit, amend, push, clear state,
or repair a mismatch.
