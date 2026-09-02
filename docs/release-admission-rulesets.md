# Release Admission Rulesets

This is the machine-checkable contract for the public GitHub ref state required
before a release is admitted. Every constant named here is defined once in
`scripts/release_admission_checks.py`; `scripts/docs_drift_guard.py` fails when
this document and those constants disagree.

Release scripts inspect this state through one read-only, credential-free public-read transport.
It performs bounded GETs only to fixed GitHub, PyPI, files.pythonhosted.org, and
reviewed-upstream endpoint shapes. It does not consult ambient credentials,
proxies, cookies, netrc, redirects, or retry configuration. Creating or changing
a tag, GitHub Release, ruleset, branch protection entry, or PyPI distribution
requires separate explicit authorization in the owning publication path.

## Public main

The public release branch is `refs/heads/main`. Required repository-rule types:

| Rule type | Effect |
|---|---|
| `non_fast_forward` | force-push to `main` is rejected |
| `deletion` | deleting `main` is rejected |
| `required_status_checks` | `release-required` must be successful |

`release-required` is the stable aggregate check exposed by the **Tests**
workflow (`.github/workflows/ci.yml`). It depends on every release-critical job —
`dependency-upgrade-gate`, `dotnet-bench`, `gitleaks-changed-range`,
`installed-application`, `lint`, `package`, `test`, `typecheck` — and runs with
`if: always()` so it still reports when an upstream job fails or is skipped. It
fails when any of those jobs is failed, cancelled, skipped, missing from `needs`,
or reports an unknown result. The job name is the required-check context:
renaming it silently removes the branch requirement, so `RELEASE_CRITICAL_CI_JOBS` and
`AGGREGATE_REQUIRED_CHECK` in `scripts/release_admission_checks.py` pin both the
name and the job set, and `tests/test_release_workflow_admission.py` compares
them against the workflow.

`dotnet-bench` mines the immutable CleanArchitecture commit
`5a600ab8749c110384bc3bd436b9c67f3067b489`, validates the committed query set,
and requires vector-mode R@5 of at least `0.900`. It runs in the **Tests**
workflow for release-candidate pushes, and its report uploads even after a
failure. Missing, skipped, or failed benchmark evidence blocks the exact SHA.
Recover by re-running the failed **Tests** push run for that candidate SHA.

`release-required` is evaluated for the **exact operator-reviewed commit SHA**,
never for a branch. Only the newest completed check-run of that name on that SHA
counts, so an older green run cannot mask a newer red one, and a still-running
run blocks instead of passing.

Every job in `ci.yml` is classified: it is release-critical, it is the aggregate
check itself, or it is listed in `AGGREGATE_EXEMPT_CI_JOBS` with the reason it
cannot gate a release. The only current exemption is `model-tests`, a manual
`workflow_dispatch`-only `needs_network` suite that never runs on `push` or
`pull_request`, so requiring it would make `release-required` permanently red.
`tests/test_release_workflow_admission.py` compares the workflow's whole job set
against those three groups, so a newly added CI job blocks until it is classified.

Admission evidence therefore comes only from `push` and `pull_request` runs:
`dependency-upgrade-gate` and `gitleaks-changed-range` are skipped on
`workflow_dispatch`, and `release-required` fails closed on any skipped
dependency. A manually dispatched **Tests** run consequently publishes a *failing*
`release-required` on that SHA. Recover a red row by re-running the `push` or
`pull_request` run that already exists for the candidate SHA — never by
dispatching a new one, and never by re-running a dispatch-shaped run, because
`gh run rerun` replays the original event and republishes the same failure.
When the candidate SHA has no `push` or `pull_request` run at all, the single
supported recovery is to land that SHA through one of those events.

Hosted `.github/workflows/publish.yml` evaluates the effective
`refs/heads/main` rules and requires `non_fast_forward`, `deletion`, and
`required_status_checks` containing `release-required`. It also evaluates active
`refs/tags/v*` rulesets and requires aggregated `creation`, `update`, and
`deletion`. Both checks use the fixed credential-free public reader. The
admission receives no GitHub token.

## Public version tags

The public version-tag pattern is `refs/tags/v*`, covered by one or more
**active** rulesets with `target: tag`. Their aggregated contract is:

| Rule type | Effect |
|---|---|
| `creation` | only the configured release bypass may create a `v*` tag |
| `update` | a published `v*` tag cannot be moved |
| `deletion` | a published `v*` tag cannot be deleted |

The supported release path creates an immutable `vX.Y.Z` tag only after the
operator has reviewed the SHA, public `main` points at that SHA, and
`release-required` is green for that SHA. Pushing the tag triggers
`.github/workflows/publish.yml`, which re-verifies admission **before** building
or uploading any artifact.

GitHub's credential-free ruleset response does not expose `bypass_actors`.
Release admission therefore neither counts bypass actors nor infers that an
omitted list is empty. The repository owner verifies the configured bypass actor
in `rergards/mempalace-code` → Settings → Rules whenever the ruleset or release
authority changes. Keep the actor set minimal and use the audit log for every
break-glass tag creation. If the owner cannot verify the release actor, do not
tag. After correcting the existing ruleset, rerun `python scripts/release_preflight.py --repo rergards/mempalace-code --check-tag-ruleset --json`.

## Acknowledged orphan public tags

An *orphan* tag is a public `v*` tag with no matching non-draft GitHub Release,
or no matching PyPI distribution, or both. New orphans block a release. The tags
below are reviewed, immutable, and reported without blocking; they are the
`ACKNOWLEDGED_ORPHAN_TAGS` registry in `scripts/release_admission_checks.py`.

| Tag | Why it is acknowledged |
|---|---|
| `v1.0.0`, `v1.1.0`, `v1.1.1`, `v1.2.0`, `v1.3.0`, `v1.4.0`, `v1.4.1`, `v1.5.0`, `v1.6.0`, `v1.6.1`, `v1.6.2`, `v1.7.0`, `v1.8.0`, `v1.10.2` | historical tags: the PyPI distribution was published before GitHub Release creation was automated, so no GitHub Release exists. The tags are immutable. |
| `v1.13.2` | failed publish attempt: **no** PyPI distribution and **no** GitHub Release. The tag stays as immutable public evidence of the failure and must never be moved or deleted. |

Adding a tag to that registry is a reviewed decision for a permanent missing
surface. An in-flight partial publication stays outside the registry and follows
the exact-run recovery below.

## Partial publication recovery

When the exact tag run proves `build=success`, `publish=success`, and the unique
`github-release=failure`, `release_status_gate.py` may emit one concrete instance
of this canonical command:

```bash
gh run rerun <publish-workflow-run-id> --job <github-release-job-id> --repo rergards/mempalace-code
```

The command is available only after the status gate proves tag/SHA/run identity,
exact PyPI inventory and provenance, install smoke, public ref checks, audit
freshness, and unrelated surfaces. All other failed or ambiguous states carry an
explicit `BOUNDED INSTRUCTION` saying that no safe publication mutation command
is available. The job-only rerun downloads and verifies the original-run
artifacts, then rechecks publication prerequisites before mutation. It converges
by creating the missing Release, validating a complete existing Release, or
uploading only a missing expected asset after every present digest matches.
Unexpected or mismatched assets stop the job. Manual Release creation, tag
mutation, a whole-workflow rerun, and a new publish dispatch are unsupported.

## Scheduled dependency-audit freshness

Publication also requires recent evidence that the scheduled **Dependency Audit**
workflow succeeded. See [DEPENDENCY_UPGRADE_GATE.md](DEPENDENCY_UPGRADE_GATE.md)
for the window and its rationale. Missing, failed, stale, future-stamped, and
unqueryable evidence all fail closed.

## Read-only admission rows and recovery

Each predicate emits exactly one row, always — an error in one lookup never
removes another row from the report — and each failure names one concrete
recovery command.

| Row | Read-only lookup | Admission credentials | Recovery for a failed row |
|---|---|---|---|
| `expected_sha_format` | none | none | rerun with the reviewed candidate 40-hex SHA: `python scripts/release_preflight.py --expect-sha <40-hex-candidate-sha> …` |
| `head_expected_sha` | `git rev-parse HEAD` | none | `git checkout <40-hex-candidate-sha>` |
| `tag_expected_sha` | `git rev-parse --verify refs/tags/vX.Y.Z^{commit}` | none | re-review the SHA or bump `project.version`, and never move a published tag |
| `candidate_ref_expected_sha` | `git rev-parse <ref>^{commit}` | none | `git fetch <remote> <branch>`, then rerun with the candidate `--expect-sha` |
| `aggregate_required_check` | fixed GitHub check-runs GET for the exact SHA and `release-required` | none | `gh run list --repo rergards/mempalace-code --workflow Tests --json headSha,event,databaseId,conclusion`, then `gh run rerun <run-id> --repo rergards/mempalace-code --failed` for the run whose head SHA is the candidate SHA **and** whose event is `push` or `pull_request`; if that SHA has no such run — none at all, or only a `workflow_dispatch` run — land it through a `push` or `pull_request` event instead |
| `dependency_audit_freshness` | fixed GitHub workflow-runs GET for `Dependency Audit` | none | `gh workflow run 'Dependency Audit' --repo rergards/mempalace-code` and wait for a fresh success |
| `public_main_protection` | fixed GitHub effective branch-rules GET for `main` | none | apply the *Public main* table above in repository → Settings → Rules |
| `public_v_tag_ruleset` | fixed GitHub ruleset list/detail GETs | none | apply the *Public version tags* table in `rergards/mempalace-code` → Settings → Rules, owner-verify the minimal release bypass, then run `python scripts/release_preflight.py --repo rergards/mempalace-code --check-tag-ruleset --json` |
| `public_orphan_tags` | fixed GitHub matching-ref and release list/latest GETs plus fixed PyPI metadata GET | none | rerun `release_status_gate.py`; use its exact-job command only for the proven partial state, otherwise follow its bounded instruction; only a reviewed permanent gap enters `ACKNOWLEDGED_ORPHAN_TAGS` |

Every `gh` recovery command names the public repository explicitly. An operator
shell is frequently defaulted to a fork, where a bare `gh run list` or
`gh workflow run` silently inspects or dispatches against the wrong repository;
these gates never rely on `gh repo set-default` or on ambient remote context.

The ruleset lookup is bounded: it requests one ruleset more than it is willing to
read back, so a repository with more rulesets than the budget produces an error
row naming the truncation instead of a `fail` row claiming that no ruleset covers
`refs/tags/v*`. A page boundary can hide a ruleset; it can never be reported as
the absence of one.

`publish.yml`, the readiness gate, and the status gate all query the public
branch and tag rules through the same fixed credential-free reader. No admission
step requests or consumes a GitHub token.

Applying these rulesets to the live repository is an owner action tracked by
backlog item `REL-ADMISSION-EXACT-SHA-PROTECTED-REFS-APPLY-RULESETS`. Until it is
done, `--check-branch-rules` and `--check-tag-ruleset` fail closed, which is the
intended state: publication is blocked rather than silently unprotected.
