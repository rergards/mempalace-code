# Task State Handoff — Shared Procedure

Owns local state persistence for `/task-plan` and `/task-hardening`. The state
file is recovery evidence. Inspection, review, or skill invocation does not
authorize creating, replacing, truncating, or clearing it.

## State Admission

Use `${AUTOPILOT_TASK_STATE}` when set; otherwise use
`/tmp/claude-task-state-<SLUG>.json`. Before any state write, perform these steps
in order:

1. Resolve the exact state path and inspect whether it exists. If it exists,
   read and preserve its bytes before evaluating a write.
2. Inspect the current Git root, Git directory, `HEAD`, branch, and
   `git status --porcelain`. Stop if the task repository is unknown or differs
   from the state evidence.
3. Run `autopilot doctor --json` before `autopilot status`. Preserve both
   outputs as read-only admission evidence.
4. Resolve the current actor and owner:
   - inside the owning Autopilot provider, require matching task/run/attempt and
     `phase_write_allowed=true` for the exact state path;
   - for an operator outside that provider, require `safe_to_edit=true` for the
     exact repository and paths.
5. Classify the existing state before choosing an action:
   - absent plus the applicable live predicate above permits one idempotent
     initialization;
   - valid matching state is resumed without initialization;
   - active-owner, blocked, resumable, stale, malformed, unknown, mismatched, or
     contradictory state is preserved. Stop with the failed predicate and the
     recovery command `autopilot doctor --json`.

Never overwrite, clear, repair, or replace evidence to make admission pass.
Unknown ownership and conflicting ownership fail closed.

## State Record

Initialize only an admitted absent path. Bind the record to the values observed
during admission:

```json
{
  "task_slug": "MINE-CSHARP",
  "skill": "/task-hardening",
  "phase": "started",
  "repository": "<absolute-git-root>",
  "head_sha": "<40-hex-sha>",
  "run_id": "<run-or-operator-session-id>",
  "attempt": "<attempt-id>",
  "updated_at": "<UTC timestamp>",
  "modified_files": [],
  "decisions": [],
  "pending_actions": []
}
```

Every later state update needs current write authority for this exact path and
must re-read the file plus live owner first. Write atomically. If the observed
record changed, preserve it and stop; do not merge from conversational memory.

## Provider-Failure Evidence

Record a failed provider attempt only in ignored local evidence. Bind each row
to `run_id`, `attempt`, `provider`, `model`, `phase`, the input/output artifact
identity, and a freshness timestamp. A provider failure does not require a
backlog edit, tracked report, staging, or commit.

On retry or partial invocation, read the state, failure evidence, Git post-state,
and provider post-state first. Keep completed evidence and completed actions.
Request authority only for the single remaining exact action; never replay a
completed action or inherit authority from the earlier invocation.

## Commit Checkpoint Integration

The commit checkpoint may read `modified_files` as secondary evidence. Git is
the ground truth. A mismatch stops the checkpoint; it does not authorize a
state rewrite.

State and result ledgers remain ignored local evidence. Clearing either file is
a separate mutation requiring current exact-path authority after the consuming
action has an unambiguous verified outcome.
