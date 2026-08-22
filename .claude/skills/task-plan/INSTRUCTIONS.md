# Task Planning Workflow

Use this skill for task planning. Invocation authorizes read-only inspection,
triage, chat output, and task-bound ignored local evidence. It does not authorize
source edits, tracked plan/report writes, backlog mutation, staging, commit,
amend, ordinary push, or publication.

## 1. Admit Existing State Before Initialization

Follow `.claude/skills/_shared/task-state.md` before any state or artifact write:

1. resolve and read the exact task-state path if it exists;
2. inspect Git root, Git directory, `HEAD`, branch, and status;
3. run `autopilot doctor --json` before `autopilot status`;
4. inside the owning provider require `phase_write_allowed=true`; for an
   operator require `safe_to_edit=true`;
5. initialize only an absent admitted state path. Resume valid matching state.
   Preserve and stop on active-owner, blocked, resumable, stale, malformed,
   unknown, mismatched, or contradictory state.

Never overwrite evidence to restart planning. The bounded recovery command is
`autopilot doctor --json`.

## 2. Classify and Research

Derive or confirm the task slug. Read the current backlog entry, likely touched
files, existing implementation owner, and the five-axis classification in
`.claude/skills/_shared/mode-classification.md`.

- `lite`: report an implementation-ready summary in chat. Create no disk plan
  unless separately authorized.
- `standard`: prepare a durable plan when exact tracked-write authority exists;
  run Codex only when the user requested it or evidence shows material risk.
- `strict`: prepare a durable plan when authorized and require Codex review.

Planning research never authorizes implementation or backlog edits.

## 3. Write Only Authorized Evidence

Ignored `.tasks/TASK-<slug>/` and `.protocols/TASK-<slug>/` evidence may be
created only for the invoked task and current admitted repository. Bind provider
evidence to run, attempt, provider, model, phase, artifact identity, and
freshness.

Tracked plan files need fresh authority bound to the exact repository, complete
path list, observed `HEAD` and status, and intended content class. Preserve the
untouched original draft when authorized, then update only the canonical final
plan. Authority for local evidence does not authorize tracked plan writes.

Use `docs/plans/README.md` as the lifecycle contract for every tracked
implementation plan. New plans start with `status: active` only when the slug
exactly matches an open item in `docs/BACKLOG.yaml`, and always include
`authority: non_authoritative` before body content. Transition to `completed`
only from exact completion evidence in `docs/BACKLOG-archived.yaml`; use
`superseded` only with an explicit repository-backed `superseded_by` reference;
use `historical` when repository evidence is absent or ambiguous. Missing,
stale, malformed, duplicate, or contradictory lifecycle evidence stops plan
execution and requires an owner decision from the current backlog files.

Acceptance criteria must be observable, testable, and scoped. Plans describe
outcomes and high-level approach; they do not grant implementation authority.

## 4. Handle Provider Failure or Partial Resume

If required Codex review fails, retain the local provider evidence and current
plan evidence. Report the provider, model, run, attempt, phase, freshness, and
exact failure. A provider outage does not require a backlog mutation, staging,
or commit.

On repeated or partial invocation, read existing state, artifacts, Git post-state,
and provider post-state first. Keep completed evidence and do not repeat completed
work. Ask only for fresh authority for the single remaining exact action.

## 5. Admit Each Tracked or Remote Mutation Separately

Require distinct current, single-use authority for each of:

- source edit: exact repository, paths, proposed change, `HEAD`, and status;
- backlog mutation: exact backlog path, item, field changes, `HEAD`, and status;
- staging: exact paths and observed index;
- commit: exact index tree, parent SHA, and message;
- amend: exact current `HEAD`, replacement index, command, and message;
- ordinary push: exact private target, visibility, full ref, local and remote SHA,
  and command;
- publication: use `.claude/skills/release/SKILL.md` and its exact mutation
  admission.

Authority is consumed when its command starts, including failure. It never
carries across action classes, retries, reordered steps, invocations, state
changes, or repositories. Use
`.claude/skills/_shared/commit-checkpoint.md` for admitted Git mutations.

## 6. Report

Return the goal, implementation areas, main risk, mode, review status, evidence
paths, completed actions, and the single remaining action. Report-only completion
is valid; do not manufacture a backlog edit or commit to park the plan.

## Rules

- Keep local raw review evidence ignored and uncommitted.
- Keep the first tracked plan draft untouched after its authorized creation.
- Validate provider comments against repository evidence.
- Stop after two failures using the same approach.
