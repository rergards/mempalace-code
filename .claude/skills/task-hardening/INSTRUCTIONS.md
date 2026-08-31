# Task Hardening Workflow

Use this skill to review an implemented change. Invocation is report-only: it
authorizes read-only inspection, triage, chat output, and task-bound ignored
local evidence. It does not authorize fixes or tracked/remote mutations. Every
such action needs separate current exact authority.

## 1. Admit Existing State Before Initialization

Follow `.claude/skills/_shared/task-state.md` in full before any state or
artifact write. It is the sole owner of admission, persistence, resume, and
recovery behavior. Recovery: `autopilot doctor --json`.

## 2. Determine and Review the Round

Read existing round evidence before deriving a missing round number. Classify
from the current diff and touched boundaries using
`.claude/skills/_shared/mode-classification.md`.

- `lite`: Codex is skipped unless requested.
- `standard`: Codex runs on round 1 by default.
- `strict`: Codex runs on round 1; later passes require unresolved P1/P2,
  newly touched sensitive boundaries, or an explicit request.

Review the diff and validate each finding against an executable path. Score it:
real defect, production reachability, and regression-testability. A score of at
least 2/3 is a fix candidate; 1/3 is a backlog candidate; 0/3 is dismissed with
evidence. Classification and triage do not authorize any mutation.

## 3. Preserve Evidence Across Failure and Partial Invocation

Write ignored local round/provider evidence only for the invoked task and
admitted repository. Bind it to run, attempt, provider, model, phase, input and
output artifact identity, and freshness. Validate any synthesized public summary
with `python scripts/workflow_summary_guard.py --file <exact-path>` before
requesting tracked-publication authority.

If a provider fails, preserve its bound evidence and continue only with
independent read-only review that the mode permits. Provider failure does not
require a backlog edit, tracked report, staging, or commit.

On retry or partial invocation, read state, prior evidence, Git post-state, and
provider post-state first. Preserve completed findings, tests, and actions.
Never replay them. Request authority only for the single remaining exact action.

## 4. Admit Each Mutation Separately

Require a fresh single-use authority immediately before each action:

- fix authority: exact repository, source/test paths, proposed change, `HEAD`,
  status, and finding identity;
- backlog authority: exact backlog path, item, field changes, `HEAD`, and status;
- staging authority: exact paths and observed index;
- commit authority: exact index tree, parent SHA, and message;
- amend authority: exact current `HEAD`, replacement index, command, and message;
- ordinary-push authority: exact private target identity, visibility, full ref,
  local SHA, observed remote SHA, and command;
- publication authority: route through `.claude/skills/release/SKILL.md`.

Use `.claude/skills/_shared/commit-checkpoint.md` for admitted Git mutations.
Authority is consumed when its command starts, including failure or ambiguous
outcome. It is invalid after any bound value changes and never carries across
actions, retries, reordered steps, rounds, invocations, repositories, or skills.

After every attempt, inspect post-state. Request fresh authority only for the
remaining action. Local report authority never authorizes a tracked report,
backlog mutation, commit, push, or publication.

## 5. Stop and Report

Finish one round by default. Report findings, scores, evidence, completed
actions, provider status, convergence, and the single recommended next action.
Report-only completion is valid. Do not force a backlog update or commit merely
to close a round.

Stop after the same test or check fails twice with the same approach. Preserve
the evidence and report remaining hypotheses.
