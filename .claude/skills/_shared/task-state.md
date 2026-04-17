# Task State Handoff — Shared Procedure

Shared state persistence for skills running multi-step workflows.
Referenced by `/task-plan`, `/task-hardening`, and any future multi-step skill.

**Purpose:** Survive context compaction by writing task state to disk. After compaction, the agent reads this file instead of relying on degraded context memory to recall which files were modified, what phase it's in, and what decisions were made.

## State File

Location: `/tmp/claude-task-state-<SLUG>.json` (e.g., `/tmp/claude-task-state-MINE-CSHARP.json`)

Use the task slug in the filename to avoid collisions when multiple sessions or autopilot instances run in parallel. If `AUTOPILOT_TASK_STATE` env var is set, use that path instead.

Structure:

```json
{
  "task_slug": "MINE-CSHARP",
  "skill": "/task-hardening",
  "phase": "triage",
  "started_at": "2026-04-17T14:30:00Z",
  "modified_files": [
    "mempalace/miner.py",
    "mempalace/lang_detect.py",
    "docs/BACKLOG.yaml"
  ],
  "decisions": [
    "F1: missing .cs extension — fix (score 3/3)",
    "F2: symbol extraction regex — fix (score 2/3)",
    "F3: benchmark dataset — backlog only (score 1/3)"
  ],
  "pending_actions": [
    "write round report to docs/audits/",
    "update BACKLOG.yaml",
    "commit via commit-checkpoint"
  ]
}
```

## When to Write

- **At skill start**: initialize with task slug, skill name, phase = "started", empty arrays.
- **After each file edit**: append the file path to `modified_files`.
- **After each decision**: append a one-line summary to `decisions`.
- **At phase transitions**: update `phase` (e.g., "research" -> "triage" -> "implementing" -> "committing").
- **After commit**: clear the file (`: > /tmp/claude-task-state-<SLUG>.json`).

## When to Read

- **After context compaction**: if `/start` is invoked mid-task, read the state file to recover task context.
- **At commit time**: the commit checkpoint (`.claude/skills/_shared/commit-checkpoint.md`) uses `modified_files` as a secondary source alongside the edit log.
- **On skill resume**: if the user re-invokes a skill after interruption, read the state file to determine where to resume.

## Integration with Commit Checkpoint

The commit checkpoint Step 1 should cross-reference three sources:
1. `/tmp/claude-edits.log` (hook-populated, most complete)
2. `/tmp/claude-task-state-<SLUG>.json` -> `modified_files` (skill-populated, survives log rotation)
3. `git diff --name-only` + `git diff --name-only --cached` (ground truth)

All three should agree. Discrepancies indicate missed files or stale state.

## Results Ledger (optional)

For tasks with experimentation (hardening, debugging, performance tuning), maintain a results log:

Location: `/tmp/claude-task-results-<SLUG>.tsv`

```tsv
timestamp	action	status	description
2026-04-17T14:30	try tree-sitter C#	keep	AST-based chunking for .cs files
2026-04-17T14:35	try regex fallback	discard	misses nested classes
2026-04-17T14:40	add symbol metadata	keep	extracts class/method/property names
```

This separates "what worked" (git history) from "what was attempted" (ledger). Useful for post-mortems and preventing re-exploration of dead ends. Not committed — lives in `/tmp/` only.

## Rules

- The state file and results ledger are ephemeral — do NOT commit them. They exist only in `/tmp/`.
- One task at a time per state file. If starting a new task, overwrite the previous state.
- Keep entries short — one line per decision, one path per file. This is a recovery aid, not a log.
- If the state file is missing or corrupt, fall back to the edit log and git status (no hard failure).
