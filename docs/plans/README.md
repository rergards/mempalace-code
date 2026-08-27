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
  `docs/BACKLOG.yaml`.
- `status: completed` — the plan slug exactly matches completion evidence in
  `docs/BACKLOG-archived.yaml`.
- `status: superseded` — current repository evidence names an explicit
  replacement in `superseded_by`.
- `status: historical` — current repository evidence is absent or ambiguous.
- `authority: non_authoritative` — required for every lifecycle state.

Lifecycle is descriptive repository state. `active` does not grant mutation
authority. Every mutation requires fresh, exact, current, single-use authority
from its owning workflow outside the plan text.

## Transitions and recovery

Create a tracked plan as `active` only when its slug has an exact open-backlog
match. Change it to `completed` when runner-owned bookkeeping records its exact
archived completion. Use `superseded` only when repository evidence records the
replacement. Use `historical` when neither source proves a more specific state.

On missing, stale, malformed, duplicate, or contradictory lifecycle evidence,
preserve the plan body, set or retain `authority: non_authoritative`, and stop.
The recovery action is an owner decision based on current
`docs/BACKLOG.yaml` and `docs/BACKLOG-archived.yaml` before executing any plan
command.
