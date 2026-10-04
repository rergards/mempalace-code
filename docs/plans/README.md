# Implementation Plan Lifecycle Contract

This directory contains implementation plans retained as repository evidence. A
plan describes intent and historical reasoning. Its text grants no authority to
edit source, mutate the backlog, stage or commit Git changes, deploy, publish, or
change external state.

## Corpus

The implementation-plan corpus is the exact output of
`git ls-files 'docs/plans/*.md'` with only `docs/plans/README.md` excluded. The
README is the directory contract, not an implementation plan. The directory is
listed in `.gitignore`, so newly generated plans remain ignored by default;
already tracked plans remain available to Git, repository search, and source
review. Published wheels and source distributions exclude this directory.

## Lifecycle metadata

Every implementation plan starts with YAML front matter containing exactly one
`status` and exactly one `authority` field:

- `status: active` — the plan slug exactly matches an open item in
  the canonical `.backlog` store; an open+held task is still open.
- `status: completed` — the plan slug exactly matches
  current valid canonical completion, or historical `docs/BACKLOG-archived.yaml`
  evidence when the canonical task is absent.
- `status: superseded` — current repository evidence names an explicit
  replacement in `superseded_by`.
- `status: historical` — current repository evidence is absent or ambiguous.
- `authority: non_authoritative` — required for every lifecycle state.

Lifecycle is descriptive repository state. `active` does not grant mutation
authority. Every mutation requires fresh, exact, current, single-use authority
from its owning workflow outside the plan text.

## Transitions and recovery

Create a tracked plan as `active` only for an exact canonical open-task match.
Owner holds and prerequisites remain effective; an active plan is never an
execution grant. Change to `completed` only with current valid canonical
completion or exact historical `docs/BACKLOG-archived.yaml` completion evidence
when no canonical task exists. YAML retirement never marks a task completed.
Use `superseded` with repository evidence naming a replacement; use `historical`
when neither source proves a more specific state.

Read `backlog_context`, `backlog_workset_context` and `backlog_workset_queue` from
the verified `.backlog` project connection; follow bounded pages. CLI fallback
uses a verified absolute `backlog-utility` binary with `call --store .backlog
--project mempalace-code --principal <principal> --name <tool> --arguments-file
<json>`. `docs/BACKLOG.yaml` retains historical section metadata only.

Missing, stale, malformed, duplicate or contradictory lifecycle evidence stops
plan execution. Preserve the body and `authority: non_authoritative`; obtain an
owner decision. A present invalid store never permits YAML fallback. Historical
YAML-only fixtures apply only when no canonical store exists.
Recovery: `<absolute-backlog-utility> validate --store .backlog`.
