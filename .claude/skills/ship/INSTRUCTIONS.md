# Ship — Verify and Report Readiness

Invocation authorizes read-only inspection, verification, and a readiness
report. Fixes, tracked writes, staging, commit, amend, ordinary push, and public
publication each require their own current exact authority.

## 1. Verify Locally

Run `/verify` and inspect the current diff. Report failures without editing. If
a fix is requested, require fresh edit authority bound to the exact repository,
paths, observed `HEAD` and status, and proposed change. Consume it after one
attempt, verify post-state, and report. More than three failed attempts on the
same outcome or a fix crossing five files stops the workflow.

## 2. Admit the Exact Target

Before requesting any Git mutation authority, evaluate these predicates in
order:

1. Resolve the exact repository root and Git directory. Read `HEAD`, branch,
   status, and diff. Stop on an unknown or mismatched repository.
2. Resolve live ownership. Inside the owning provider require
   `phase_write_allowed=true`; for an operator require `safe_to_edit=true`.
   Active, stale, contradictory, or unknown ownership stops.
3. Require a literal remote name and URL, full destination ref, and 40-hex local SHA.
   Do not infer `origin`, `main`, the current branch, or `HEAD` as a target.
4. Normalize the supported remote URL to `owner/repository`. For GitHub, run
   `gh repo view --json nameWithOwner,isPrivate`; require exact normalized
   `nameWithOwner` equality and known `isPrivate` visibility. Unknown or
   mismatched identity or visibility stops.
5. Read the current destination SHA with `git ls-remote <remote> <full-ref>`.
   Record absent only when creating that exact ref is intended.

If `isPrivate=false`, visibility is unknown, or the request expresses release,
publish, tag, package-index, or public-distribution intent, stop ship mutation
and route to `.claude/skills/release/SKILL.md`. Perform no push here. The release
skill owns public admission and every publication mutation.

## 3. Admit One Local Git Mutation

If fixes produced changes, follow
`.claude/skills/_shared/commit-checkpoint.md`. Staging, commit, and amend have
separate single-use authority bound to the exact paths, index, message or
command, repository, `HEAD`, owner, and observed state. Ship invocation and fix
authority authorize none of them.

After every attempt, inspect post-state. A failure or ambiguous outcome consumes
authority. Do not retry or continue to the next mutation without fresh authority
for the single remaining exact action.

## 4. Admit One Ordinary Private Push

An ordinary push is eligible only after all target predicates passed and
`isPrivate=true`. Re-read the repository, live owner, remote URL, normalized
identity, local SHA, and remote destination SHA immediately before authority is
requested.

Request fresh ordinary-push authority bound to the exact repository, remote
name and URL, `owner/repository`, `isPrivate=true`, full destination ref,
40-hex local SHA, observed remote SHA, and literal push command. The literal
command must use the immutable SHA as its source refspec:
`git push <literal-remote> <40-hex-local-sha>:<full-destination-ref>`. Do not use
a branch name, tag, or `HEAD` as the source refspec. The authority permits one
attempt and is consumed when the command starts.

Immediately before execution, re-read live ownership, resolve the intended local
source ref to its 40-hex SHA, and re-read the remote destination SHA. Require the
resolved local SHA to equal both the authorized SHA and the immutable source in
the literal push command. Any change invalidates authority. Stop, report the new
state, and request fresh authority.
Never rebase, force, retarget, or retry automatically.

## 5. Report

Report local verification, exact target admission predicates, mutations actually
attempted, their post-state, and the single remaining action. A readiness report
must not claim that verification implied mutation authority or that a local SHA
was shipped without exact remote-SHA confirmation.
