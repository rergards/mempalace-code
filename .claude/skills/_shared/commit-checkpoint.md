# Commit Checkpoint — Shared Procedure

Shared commit procedure for all skills that commit.
Referenced by `/task-plan`, `/task-hardening`, `/ship`, and any future committing skill.

**Purpose:** Prevent missed files, wrong staging, private artifact leaks, and lost work by cross-referencing the edit log against git state before every commit.

## Procedure

### Step 1: Collect modified files from all sources

Cross-reference three sources to build the complete file list:

**Source A — edit log** (hook-populated, most complete):
```bash
cat /tmp/claude-edits.log 2>/dev/null | grep "Modified:" | sed 's/.*Modified: //' | sort -u
```

**Source B — task state** (skill-populated, survives log rotation):
```bash
cat "${AUTOPILOT_TASK_STATE:-/tmp/claude-task-state-${task_slug:-unknown}.json}" 2>/dev/null | grep -oP '"[^"]+\.(py|md|json|yaml)"' | tr -d '"' | sort -u
```

**Source C — git diff** (ground truth):
```bash
git diff --name-only && git diff --name-only --cached
```

If sources A and B are both empty or missing, source C is sufficient. If any source lists a file the others don't, investigate before proceeding.

### Step 2: Cross-reference with git status

```bash
git status --porcelain
```

Compare the two lists. Flag discrepancies:

- **Edited but unstaged** (`M` or `?? ` in git status, present in edit log): these MUST be staged or explicitly excluded with a reason.
- **Staged but not in edit log** (in git status `M ` or `A ` index column, absent from edit log): warn — this may be another agent's work or a stale change. Verify before committing.
- **Local task artifacts** (`.tasks/`, `.protocols/`, `docs/audits/`): these MUST stay unstaged unless the user explicitly asks to publish a sanitized artifact. Treat them as local evidence by default.

If any discrepancy is found, list it explicitly before proceeding. Do not silently skip mismatched files.

### Step 3: Run public-safety preflight

Before staging, check whether the intended public diff contains secrets, private paths, local artifact directories, or private project names:

```bash
rg -n "(/Users/|/srv/[^[:space:]'\"\`]+|[g]ithub_pat_|[g]hp_|[p]ypi-[A-Za-z0-9_-]{20,}|[s]k-[A-Za-z0-9])" -- $(git ls-files)
git status --short | grep -E "^.. (\\.tasks/|\\.protocols/|docs/audits/)" && echo "ERROR: local artifacts must not be staged"
```

False positives such as placeholder tokens or policy text are allowed only after explicit review. Do not publish raw review logs, private benchmark results, local absolute paths, private remotes, or customer/project identifiers.

### Step 4: Stage explicitly

Stage ONLY the files that belong to this commit, by name:

```bash
git add <file1> <file2> ...
```

**NEVER** use `git add .` or `git add -A`. If the edit log shows files you did not intend to modify, investigate before staging.

### Step 5: Review staged diff

```bash
git diff --cached --stat
git diff --cached --name-only | grep -E "^(\\.tasks/|\\.protocols/|docs/audits/)" && echo "ERROR: local artifact staged"
```

Verify the staged file count and names match expectations. If a file is unexpectedly large or unexpected, investigate.

### Step 6: Commit

```bash
git commit -m "<message>"
```

Use the calling skill's commit message format (e.g., `docs(plan):`, `chore(<slug>):`, `fix:`, etc.).

**Git trailers (optional but encouraged):** When the task involved rejecting alternatives or discovering constraints, append trailers to the commit message body. These help future sessions avoid re-exploring dead ends:

```
Rejected: <approach> — <reason>
Constraint: <invariant discovered during this task>
Scope-risk: <boundary that future changes should be careful about>
```

Queryable later via `git log --grep="Rejected:"` or `git log --grep="Constraint:"`.

### Step 7: Post-commit verification

```bash
git show --name-only --pretty=format: HEAD | grep -E "^(\.tasks/|\.protocols/|docs/audits/)" && echo "ERROR: local artifact committed — revert/amend before pushing" || echo "ok: no local artifacts committed"
```

If local artifacts were committed, amend before pushing. Publish only sanitized summaries in tracked docs such as `docs/plans/`, `docs/refactoring/`, `docs/BACKLOG.yaml`, `CHANGELOG.md`, or release notes.

### Step 8: Clear session state

```bash
: > /tmp/claude-edits.log
: > "${AUTOPILOT_TASK_STATE:-/tmp/claude-task-state-${task_slug:-unknown}.json}"
```

This prevents the next commit checkpoint from seeing stale entries from a previous task unit.

## Agent File Coordination

Before editing a file in a multi-agent session, check for another agent's uncommitted changes:

```bash
grep "Modified:.*<target-file>" /tmp/claude-edits.log 2>/dev/null
```

If the file appears in the edit log but is not yet committed (present in `git status --porcelain` output), another agent may have uncommitted work on it. In that case:
- **Warn** in chat: "File `<path>` has uncommitted changes from another agent."
- **Do not overwrite** — either wait for the other agent to commit, or coordinate with the user.
- If you must edit the file, note the conflict potential in the task state file.

This is a cheap coordination mechanism that works on a single branch without requiring multi-branch isolation.

## Rules

- Every committing skill MUST follow this procedure instead of writing ad-hoc commit logic.
- If Step 2 reveals files from another agent's uncommitted work, do NOT stage them. Warn and proceed with only your own files.
- If the edit log contains files outside the task scope, investigate — they may be side effects from a shared hook or linter auto-fix.
- The edit log is the primary record. Task state is the secondary record. Git status is the ground truth. All three should agree before committing.
