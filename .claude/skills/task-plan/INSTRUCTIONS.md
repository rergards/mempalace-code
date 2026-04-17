# Task Planning Workflow

Use this skill instead of manually pasting the long planning prompt.

Before doing anything, classify the task using the 5-axis triage in `.claude/skills/_shared/mode-classification.md`.

- `lite`: simple fast-path work. No disk plan and no Codex by default.
- `standard`: non-trivial but bounded work. Durable plan, Codex only when explicitly justified.
- `strict`: high-risk or cross-boundary work. Durable plan plus Codex second-pass review.

Do not use this skill to manufacture a heavyweight plan for a task that clearly qualifies for `lite`.

## Expected Input

Invoke with a task slug and optionally a short task description:

```text
/task-plan MINE-CSHARP
```

If the user did not provide a slug, derive one from the task and state it explicitly.

## Workflow

1. Initialize task state per `.claude/skills/_shared/task-state.md` — write `/tmp/claude-task-state-<SLUG>.json` (using the task slug) with task slug, skill = "/task-plan", phase = "started". Update throughout the workflow. This survives context compaction.

2. Derive or confirm the task slug, then do a short preflight scan before choosing the mode:
   - look up the task details: `backlog show <SLUG> --file docs/BACKLOG.yaml`
   - inspect the likely touched files and existing implementation pattern
   - apply the 5-axis triage and decision rule from `.claude/skills/_shared/mode-classification.md`
   - state the chosen mode briefly in chat with the main reason

3. If the task is `lite`:
   - do minimal repo research
   - do not create a disk plan unless the user explicitly asked for one
   - do not run Codex unless the user explicitly asked for it
   - give a brief implementation-ready summary in chat:
     - goal / problem
     - main files or subsystems
     - biggest risk or assumption
     - `Mode: lite; Codex: skipped`
   - stop

4. For `standard` or `strict`, create task artifacts:

```bash
mkdir -p .tasks/TASK-<slug> .protocols/TASK-<slug>
```

5. **Enter Claude plan mode** (`EnterPlanMode`) before creating the plan. Use plan mode to:
   - explore the codebase (Glob, Grep, Read) guided by the task
   - identify existing patterns, shared code, and integration points
   - resolve ambiguities and surface hidden risks
   - design the implementation approach
   - present the plan for user approval before writing plan files

   Skip plan mode only when: running in `claude -p` (non-interactive), OR the task is `lite`.

6. After exiting plan mode, write the plan:
   - write untouched first draft to `docs/plans/<slug>-original.md`
   - refine to final `docs/plans/<slug>.md`
   - stop for blocking questions only if repo research cannot resolve them

7. **Acceptance criteria pre-check** (recommended for `standard`/`strict`):
   Before Codex review or handoff to implementation, verify that every AC in the plan is:
   - **Observable**: describes a user-visible or API-observable outcome, not an internal implementation detail.
   - **Testable**: can be mapped to a specific test command or pytest case. If an AC cannot be verified by a test, rewrite it or flag it as needing manual verification.
   - **Scoped**: does not smuggle in work outside the stated task boundary.
   If any AC fails these checks, revise the plan before proceeding.

8. Codex plan review policy:
   - `strict`: required
   - `standard`: run only if the user explicitly asked for Codex, or planning uncovered hidden cross-subsystem risk, storage risk, MCP contract risk, or unresolved ambiguity that benefits from a second pass
   - `lite`: skipped by default

If Codex review is required or justified, run:

```bash
./scripts/codex-review.sh --show-codex-comments plan <task-slug> docs/plans/<task-slug>.md
```

9. **Codex accessibility gate.** If Codex review is required but Codex is inaccessible (auth failure, 401, network error, CLI missing):
   - **Stop** — do not continue to the summary step or mark the plan as ready.
   - **Save progress** — ensure `docs/plans/<slug>.md` and all `.tasks/TASK-<slug>/` artifacts are written to disk.
   - **Update BACKLOG.yaml** — add note that task is blocked on Codex access.
   - **Commit immediately** — follow the shared commit checkpoint in `.claude/skills/_shared/commit-checkpoint.md`.
   - **Report** in chat: what was saved, why Codex failed, and that the task is parked.
   - Do NOT fall back to skipping Codex silently when the mode required it.

10. If Codex ran successfully and reports actionable gaps, close them and re-save `docs/plans/<task-slug>.md`.

11. **Commit plan artifacts (mandatory).** Skip only in `claude -p` or `lite` mode.

    Follow the shared commit checkpoint procedure in `.claude/skills/_shared/commit-checkpoint.md`:
    - Read edit log, cross-reference git status, stage explicitly, review diff, commit, post-commit verify.
    - Expected files to stage: `docs/plans/<slug>.md`, `docs/plans/<slug>-original.md`, `.protocols/TASK-<slug>/`, `.tasks/TASK-<slug>/`.
    - Commit message format: `docs(plan): <TASK-SLUG> — <mode> plan ready`

12. End with a brief plan summary in the chat. Keep it short and execution-oriented. Include:
   - the problem / goal in one sentence
   - the main implementation areas or subsystems
   - the biggest risk, migration concern, or key assumption
   - mode (`lite`, `standard`, or `strict`)
   - Codex plan review status (`clean`, `revised after review`, or `skipped: <reason>`)

## Rules

- **Plan scope constraint**: Plans specify product-level acceptance criteria + high-level approach only. Do NOT include granular implementation steps (function names, variable names, line-by-line code changes). Over-specified plans cascade errors when implementation details are wrong — let the implementing agent determine its own path.
- Keep `docs/plans/<slug>-original.md` untouched after first write.
- Canonical final output remains `docs/plans/<slug>.md`.
- Store supporting artifacts in `.tasks/TASK-<slug>/`.
- Do not treat Codex comments as truth; validate them against repository evidence.
- Do not stop at writing the plan file; always give the user a brief summary of the final execution-ready plan.
- If the task clearly qualifies for the fast path after the preflight scan, say so explicitly instead of manufacturing a durable plan just because `/task-plan` was invoked.
- A user-supplied size estimate never overrides repo-evidenced risk.
