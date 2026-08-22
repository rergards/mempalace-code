---
name: release
description: Cut and verify a public release through publish remote, hosted CI, PyPI, and GitHub Release status
disable-model-invocation: false
---

# Release Workflow

Cut a public release. Run after `/release-prep` has synced docs, changelog, and
version metadata.

Publication is bound to **one operator-reviewed 40-hex commit SHA**. Every gate
below is read-only. Every external mutation needs its own explicit approval
immediately before it runs, and no approval carries over to the next one: the
candidate branch push (Step 5), the fast-forward onto `main` (Step 5a), the tag
push (Step 6), and the candidate branch deletion (Step 8) are each asked
separately, as is anything else that writes to the remote. Never create, edit,
or bypass a ruleset, branch protection entry, tag, GitHub Release, or PyPI
distribution by hand.

## When to Use

- Ready to cut a new release
- User says "release", "publish", "ship", or "bump version"

## Step 1 — Local gates

Run `/verify`, then run these from the release commit:

```bash
ruff check mempalace_code/ tests/ scripts/
ruff format --check mempalace_code/ tests/ scripts/
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"
python -m pytest tests/ -x -q -m "not needs_network"
python scripts/docs_drift_guard.py
python scripts/public_safety_scan.py --tracked --staged
python scripts/quality_scorecard.py --check
python scripts/release_install_metadata_smoke.py --install-spec . --json
python scripts/release_readiness_gate.py --check --json
```

If dependency bounds, lockfiles, workflows, storage, miner, or optional extras
changed, also audit and reproduce the hosted resolver in a clean venv — a green
local `.venv` is not evidence of what CI and users resolve:

```bash
python -m pip install pip-audit
pip-audit
python3.13 -m venv /tmp/mempalace-ci-venv
/tmp/mempalace-ci-venv/bin/python -m pip install -e ".[dev,treesitter]"
/tmp/mempalace-ci-venv/bin/python -m pytest tests/ -q -m "not needs_network"
```

## Step 2 — Confirm version

Use the version prepared by `/release-prep`. If unclear, classify the bump and
ask the user to confirm:

| Change type | Bump |
|---|---|
| Breaking changes (API, CLI, storage format) | Major (X.0.0) |
| New features (languages, MCP tools) | Minor (0.X.0) |
| Bug fixes, docs, internal | Patch (0.0.X) |

Read public state from public sources only — never from local tags or private
remotes:

```bash
grep -E "^version\s*=" pyproject.toml
git ls-remote --tags publish 'refs/tags/v*' | tail -10
```

## Step 3 — Commit

```bash
git status --short
git add pyproject.toml CHANGELOG.md README.md docs/LLM_USAGE_RULES.md uv.lock
git commit -m "chore: release vX.Y.Z"
```

Stage only release files. Never stage private notes, tokens, temp files, or
unrelated work.

## Step 4 — Build the candidate on public `main`

Local `main` and public `main` are separate histories — public `main` carries
one squashed commit per release. `git push publish main` from a development
branch is rejected as non-fast-forward. Never use `--force` or `--force-with-lease`
and never rewrite history to resolve that; public `main` is protected against
non-fast-forward updates and deletions.

Two distinct SHAs and one branch name are in play from here on. Never let them
share a name:

| Name | Meaning |
|---|---|
| `REVIEWED_LOCAL_SHA` | the local commit whose tree was reviewed |
| `CANDIDATE_SHA` | the new commit carrying that tree on top of `publish/main` |
| `CANDIDATE_BRANCH` | the public branch carrying `CANDIDATE_SHA` for this attempt |

`CANDIDATE_SHA` is the release candidate — it is what `--expect-sha`, the tag,
and the status gate all refer to. `REVIEWED_LOCAL_SHA` never leaves this machine.
Every later step uses `$CANDIDATE_BRANCH`, never a literal branch name.

```bash
git fetch publish main
REVIEWED_LOCAL_SHA=$(git rev-parse HEAD)      # the reviewed release commit
CANDIDATE_SHA=$(git commit-tree "$REVIEWED_LOCAL_SHA^{tree}" -p publish/main -m "release vX.Y.Z")
# One immutable name per attempt: release/vX.Y.Z, then release/vX.Y.Z-rc2, -rc3.
CANDIDATE_BRANCH=release/vX.Y.Z
git switch -C "$CANDIDATE_BRANCH" "$CANDIDATE_SHA"     # local create-or-reset, pre-push only
git diff --stat "$REVIEWED_LOCAL_SHA" "$CANDIDATE_SHA" # MUST be empty — tree parity proof
git rev-parse HEAD                                     # must print $CANDIDATE_SHA
```

If `git diff --stat` prints anything, stop: the candidate does not carry the
reviewed tree. `git switch -C` is mandatory because `--require-clean` and
`--expect-sha` in Step 5 bind `HEAD`, and `-C` keeps a *local* retry safe before
the branch is pushed.

Once the branch is on `publish` it is immutable. A rebuilt candidate is a
different commit, so re-pushing it to the same branch is a non-fast-forward
update — never `--force` it and never update a published candidate branch. Set
`CANDIDATE_BRANCH=release/vX.Y.Z-rc2` (then `-rc3`, …) and redo this step. The
rejected attempt stays public as its own evidence.

## Step 5 — Push the candidate branch, then admit it

The candidate is proven green on its own public branch **before** `main` moves.
Ask before pushing unless the user already asked to publish:

```
Ready to push release vX.Y.Z to publish?
- git push publish $CANDIDATE_BRANCH   (new public branch, main untouched)
Proceed? [y/n]
```

```bash
git push publish "$CANDIDATE_BRANCH"
```

`.github/workflows/ci.yml` triggers on pushes to `main` and to `release/v*`,
which covers the first attempt and every `-rcN` rebuild, so
the candidate branch runs the full `release-required` job graph. A
`workflow_dispatch` run is still never release evidence — it skips
`gitleaks-changed-range` and `dependency-upgrade-gate`, and the aggregate check
fails closed on a skip.

Wait for hosted checks on `$CANDIDATE_SHA` itself, then require both green for
that exact SHA — **Tests** and the `release-required` aggregate:

```bash
gh run list --repo rergards/mempalace-code --commit "$CANDIDATE_SHA" --workflow Tests
gh api "repos/rergards/mempalace-code/commits/$CANDIDATE_SHA/check-runs" --jq '.check_runs[] | select(.name=="release-required") | .conclusion'
```

This is the publication boundary. Run admission against the candidate branch,
while `main` is still untouched:

```bash
git fetch publish "$CANDIDATE_BRANCH"
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --expect-sha <40-hex-candidate-sha> --candidate-ref "publish/$CANDIDATE_BRANCH" --check-required-check --check-dependency-audit --check-branch-rules --check-tag-ruleset
```

It binds `HEAD`, the intended `vX.Y.Z` target, `CANDIDATE_SHA`, and the fetched
candidate ref to one commit, then checks `release-required`, public `main` branch
rules, the `refs/tags/v*` ruleset, orphan public tags, and **Dependency Audit**
freshness through read-only GitHub APIs. Missing, failed, stale, cancelled,
skipped, undatable, or unqueryable evidence blocks publication.

## Step 5a — Fast-forward the green SHA onto `main`, then re-admit

Only an already-green `$CANDIDATE_SHA` is promoted, and only as a fast-forward.
Ask for this step's own approval — pushing the candidate branch did not
authorize moving `main` — then:

```bash
git push publish "$CANDIDATE_SHA":refs/heads/main   # fast-forward only; never --force
git fetch publish main
git rev-parse publish/main                          # must print $CANDIDATE_SHA
```

Promoting a SHA that already carries its own green **Tests** and `release-required`
results is what keeps this sequence working if required status checks are later
added to public `main`: the results for that commit already exist before the
branch update is attempted.

Public `main` has moved, so re-run admission bound to `publish/main` before any
tag exists:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --expect-sha <40-hex-candidate-sha> --candidate-ref publish/main --check-required-check --check-dependency-audit --check-branch-rules --check-tag-ruleset
```

`--check-tag-ruleset` needs a token with repository administration read, so it
is operator-only; `.github/workflows/publish.yml` re-verifies the rest with the
workflow token before building anything.

A non-zero exit means the release is not admissible. Go to **Recovery**.

## Step 6 — Tag and push the tag

Run the canonical live pre-tag check immediately before creating the immutable
tag:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

Ask for this step's own approval — promoting `main` did not authorize the
immutable tag — then:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push publish vX.Y.Z
```

The tag-only `.github/workflows/publish.yml` re-verifies admission for the exact
SHA, builds and checks both distributions, publishes through the protected
trusted-publishing environment, and creates the GitHub Release. Do not run
`twine upload`, do not create the GitHub Release by hand, and never trigger
publishing by workflow dispatch or release event.

## Step 7 — Verify hosted status

Wait for GitHub Actions and package-index propagation, then:

```bash
python scripts/release_status_gate.py --version X.Y.Z --repo rergards/mempalace-code --remote publish --branch main --expect-sha <40-hex-candidate-sha>
```

`--expect-sha` reconciles the public tag target against `CANDIDATE_SHA`, so a
tag moved or recreated after review cannot report green. Without it the gate
falls back to the tag's own commit.

The gate reports these surfaces, always one row each:

<!-- release-status-surfaces start -->

| Surface | Green means |
|---|---|
| `publish_remote_tag` | `vX.Y.Z` exists on the `publish` remote |
| `release_candidate_sha` | the candidate SHA and the public tag target are the same commit |
| `branch_tests_workflow` | the newest completed **Tests** run for that exact SHA succeeded |
| `release_required_check` | the newest completed `release-required` check-run for that SHA succeeded |
| `publish_to_pypi_workflow` | the newest completed **Publish to PyPI** run for that SHA succeeded |
| `github_release` | the release exists, is non-draft, non-prerelease, and latest |
| `pypi_json` | PyPI reports the version with both wheel and sdist |
| `pypi_provenance` | every exact-version PyPI file verifies for `rergards/mempalace-code`, `.github/workflows/publish.yml`, and environment `release` |
| `install_smoke` | a disposable venv install agrees on the version across metadata, module, and CLI |
| `public_main_protection` | public `main` carries the required non-fast-forward, deletion, and status-check rules |
| `public_v_tag_ruleset` | an active `refs/tags/v*` ruleset holds creation, update, and deletion rules |
| `public_orphan_tags` | no unacknowledged public `v*` tag lacks a GitHub Release or PyPI distribution |
| `dependency_audit_freshness` | the latest **Dependency Audit** run succeeded inside the freshness window |

<!-- release-status-surfaces end -->

Surface names are pinned to `REQUIRED_SURFACES` in
`scripts/release_status_gate.py` and enforced by `scripts/docs_drift_guard.py`.

For the first release after provenance verification lands, run the exact-version,
exact-SHA command above against public PyPI without mutation and retain its bounded
`pypi_provenance` row as live evidence. Hermetic contract fixtures do not replace
this hosted read-only check.

`--skip-smoke` is diagnostic-only and can never be called shipped. A release is
shipped only when the gate exits 0. Until then, report the `Remaining blockers`
list verbatim and do not use "shipped" or "latest" language.

## Step 8 — Retire the candidate branch (separate approval)

`$CANDIDATE_BRANCH` is temporary, but deleting it is its own external mutation.
Never delete it under the approval given for the push, the promotion, or the
tag. Leaving it costs nothing; ask, and accept "no".

Propose the deletion only when all three hold: `publish/main` is
`$CANDIDATE_SHA`, tag `vX.Y.Z` targets `$CANDIDATE_SHA`, and Step 7 exited 0.

```
Release vX.Y.Z is verified. Delete the temporary candidate branch?
- git push publish --delete $CANDIDATE_BRANCH
Proceed? [y/n]
```

```bash
git push publish --delete "$CANDIDATE_BRANCH"
```

If any condition is unmet, keep the branch and say so. A rejected `-rcN` branch
is public evidence of what failed — never delete one to tidy up.

## Recovery

Every failed or errored row prints one `remediation`. A proven partial state has
`build=success`, `publish=success`, unique `github-release=failure`, exact
repository/tag/SHA/run identity, and every prerequisite green. Only that state
prints concrete numeric IDs in this command:

```bash
gh run rerun <publish-workflow-run-id> --job <github-release-job-id> --repo rergards/mempalace-code
```

Ask for explicit approval immediately before running the emitted command. It
reruns only the exact `github-release` job. The job reuses the original run's
verified wheel and sdist, rechecks PyPI inventory and provenance, creates a
missing Release, validates a complete existing Release, or uploads only a
missing expected asset whose peers already match. It fails on unexpected or
mismatched assets and never overwrites or deletes them.

Every other failed, in-progress, stale, reordered, duplicated, wrong-repository,
or wrong-SHA state prints `BOUNDED INSTRUCTION: no safe publication mutation
command is available`. Resolve its named blockers. Then re-read the report:

```bash
python scripts/release_status_gate.py --version X.Y.Z --repo rergards/mempalace-code --remote publish --branch main --expect-sha <40-hex-candidate-sha> --json
```

Run the full status gate after the job rerun. The release is shipped only when
every surface is green. Do not improvise a different repair. Never dispatch a new
**Tests** run to fix `release_required_check` (dispatch-shaped runs skip
release-critical jobs and republish a red result), never move or delete a
published tag, never create the GitHub Release manually, and never edit a ruleset
to clear a row. The row-by-row recovery table is
`docs/release-admission-rulesets.md`.

## Output

```
## Release vX.Y.Z

Version: X.Y.Z
Candidate SHA: <40-hex-candidate-sha>
Candidate branch: <$CANDIDATE_BRANCH> [kept/deleted with approval]
Tag: vX.Y.Z
Pushed to publish: [yes/no]
Release status gate: [passed/failed]

Remaining blockers:
- [none or exact blocker from release_status_gate.py output]
```

Release notes are public: user-facing changes, package/version advisory IDs, and
verification boundaries only. No private remotes, local paths, tokens,
hostnames, or incident-only details.
