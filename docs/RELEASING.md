# Releasing mempalace-code

This runbook defines the public release boundary. It covers package metadata,
documentation, build artifacts, GitHub, PyPI, and a fresh-install check. It
does not authorize a tag, push, GitHub settings change, or PyPI publication;
each external mutation requires the operator's explicit approval.

## Release invariants

- The release tag is exactly `v<project.version>` from `pyproject.toml`.
- The tag targets the current public `main` commit after the branch CI is
  green for the exact operator-reviewed candidate SHA.
- The **Tests** workflow exposes the stable `release-required` aggregate check;
  release admission requires that check to be successful for the exact
  candidate SHA.
- Public `refs/heads/main` and `refs/tags/v*` follow the read-only ruleset
  contract in `docs/release-admission-rulesets.md`.
- The latest successful **Dependency Audit** run is fresh enough for release
  admission.
- The checked-out, committed tree passes public-safety and documentation-drift
  checks.
- The published package contains both a wheel and an sdist, and a fresh virtual
  environment can install the wheel.
- The wheel and sdist contain the Agent Plugin package root with `plugin.json`,
  `mcp.json`, `skills/mempalace/SKILL.md`, vendored Agent Plugins 1.0.0
  schemas, and the schema notice.
- A fresh install's `importlib.metadata.version("mempalace-code")`,
  `mempalace_code.__version__`, and `mempalace-code version-check --status`
  all report the same version. The same install smoke creates the optional
  alias through a temporary symlinked launcher under a conflicting `PATH`,
  repeats the binding through the installed `mempalace-code-alias` entry point,
  verifies that both paths target the sibling canonical launcher and report the
  same version, runs `mempalace-code agent-plugin path --json`, parses the JSON
  `path` field, validates the manifests from the installed package, and launches the declared
  `mempalace-code-mcp --profile=minimal` command to list the portable minimal
  tools - see `scripts/release_install_metadata_smoke.py`.
- The PyPI publication is followed by a non-draft GitHub Release and the
  complete machine-readable publication/admission check.

## 1. Prepare the release commit

Update the version, changelog, public documentation, and generated scorecard in
one reviewable change. Keep `## Unreleased` at the top of `CHANGELOG.md`; move
the completed items into the new version heading when cutting the release.

Run the deterministic local checks from the release commit:

```bash
python scripts/docs_drift_guard.py
python scripts/public_safety_scan.py --tracked --staged
python scripts/quality_scorecard.py --check
python scripts/release_preflight.py --tag vX.Y.Z --require-clean
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --expect-sha <40-hex-candidate-sha> --check-public-main --check-required-check --check-dependency-audit --check-branch-rules --check-tag-ruleset
python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json
WHEEL=dist/mempalace_code-X.Y.Z-py3-none-any.whl
python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json
python -m pytest tests/ -x -q -m "not needs_network"
python -m pytest tests/test_mcp_protocol_compat.py -q
python -m pytest tests/test_cli_golden_scenarios.py -q
ruff check mempalace_code/ tests/ scripts/
ruff format --check mempalace_code/ tests/ scripts/
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"
python -m pyright -p pyrightconfig.strict.json
```

Immediately before creating the immutable tag, run the opt-in live pre-tag
check. It is the canonical pre-tag command and fails closed when upstream
`develop` moved or its read-only head lookup cannot be trusted:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

`release_install_metadata_smoke.py --all-installers` installs the current checkout through
the canonical `venv`, `bootstrap-venv`, `pipx`, and `uv-tool` contours and proves
`importlib.metadata.version`,
`mempalace_code.__version__`, and `mempalace-code version-check --status`
agree on one version before the release commit lands. It also resolves
`mempalace-code agent-plugin path --json` from a neutral directory, parses the
JSON `path` field, rejects checkout shadowing, validates the Agent Plugin
manifests against the installed vendored schema IDs, and starts the manifest-declared
`mempalace-code-mcp --profile=minimal` launcher. Every contour also checks the
three update confirmation refusals without state mutation and loads an
interpreter-site socket guard before proving that disabled
`version-check --check-now` stops before network access. Missing `pipx` or `uv` fails closed;
run `python -m pip install pipx` or `python -m pip install uv`, then retry the
same aggregate command. Use `--installer pipx` only for bounded diagnostics.

The aggregate also requires one supported Linux systemd-user lifecycle receipt. Run it as
a disposable Linux OS user whose passwd `HOME`, effective uid, `/run/user/<uid>`, and user
bus agree, and set `MEMPALACE_RELEASE_SYSTEMD_USER=1`. Other platforms and unavailable or
incongruent user managers return blocking `UNRUN`; the passing manager rows remain partial
evidence. Recovery: rerun the same aggregate command in the disposable Ubuntu job shape:

```bash
MEMPALACE_RELEASE_SYSTEMD_USER=1 python scripts/release_install_metadata_smoke.py \
  --all-installers --install-spec dist/mempalace_code-*.whl --json
```

The manager matrix above remains a lightweight metadata, recovery, plugin, and
network-guard check across `venv`, `bootstrap-venv`, `pipx`, and `uv-tool`. The
full application gate runs once against the exact candidate wheel with its
`watch` extra:

```bash
WHEEL=dist/mempalace_code-X.Y.Z-py3-none-any.whl
python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json
```

Set `MEMPALACE_TEST_HF_HOME` to a pre-populated cache root before running that
command. The gate requires the CPU FastEmbed artifact and exact MemPalace
provenance at `mempalace-fastembed/all-MiniLM-L6-v2-v1/.mempalace-model.json`
and stops before venv creation when either is absent, foreign, or stale.
Provision the cache outside qualification, then retry:

```bash
HF_HOME="$MEMPALACE_TEST_HF_HOME" mempalace-code fetch-model
```

The installed-golden owner creates one disposable venv, installs only the
explicit wheel with `[watch]`, installs and positively loads an interpreter-site
socket guard, and runs direct release-owned scenarios through the venv's absolute
`mempalace-code` executable before returning the aggregate `installed_golden_suite`
result. After provenance passes, the candidate venv interpreter introspects the
installed argparse object to discover its command/subcommand tree. Only later
direct-scenario launches of that exact console count as execution evidence. A
missing member fails the existing aggregate row with the sanitized member list
and the canonical installed-golden rerun command. The owner uses a neutral cwd,
disposable HOME/XDG directories, `HF_HUB_OFFLINE=1`, and
`TRANSFORMERS_OFFLINE=1`. Passing provenance requires the wheel version,
distribution metadata, imported `mempalace_code` path, venv interpreter, and
console executable to agree and remain outside the checkout and ambient PATH.
The exact same owner runs inside `release_readiness_gate.py --check` and the
required `installed-application` CI job; missing or failing evidence therefore
blocks `release-required`.

On CPU-only Linux, the same owner qualifies `[custom-models]` by installing PyTorch from
the official CPU wheel index before installing the exact candidate wheel extra. Prepare an
owner-private scratch directory on a filesystem with adequate free space and preserve one
`TMPDIR` across the ordered contour:

```bash
install -d -m 700 "$HOME/.cache/mempalace/tmp"
df -h "$HOME/.cache/mempalace/tmp"
TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install 'mempalace-code[custom-models]'
```

An `Errno 28` or `No space left on device` result identifies the failed prerequisite or
candidate-extra stage in bounded sanitized output. Free adequate space on the selected
filesystem and repeat the complete owner from that scratch directory:

```bash
TMPDIR="$HOME/.cache/mempalace/tmp" python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json
```

The default tag preflight is deterministic, local, and non-mutating. It checks
tag/version agreement, the documentation contract, the committed-tree
public-safety scan, and optionally a clean worktree. The explicit
`--check-live-upstream` mode reuses the read-only shared upstream comparison
guard; it adds one live branch-head lookup and never rewrites source or Git
state.

The exact-SHA release admission command is the publication boundary after the
operator has reviewed the candidate commit and fetched the public target:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --expect-sha <40-hex-candidate-sha> --candidate-ref publish/main --check-required-check --check-dependency-audit --check-branch-rules --check-tag-ruleset
```

This command binds `HEAD`, the intended `vX.Y.Z` tag target, the
operator-reviewed candidate SHA, and the fixed public `main` head. It also uses
`scripts/release_admission_checks.py` to query the `release-required` aggregate
check, public `main` branch rules, `refs/tags/v*` ruleset state, orphan public
tags, and **Dependency Audit** freshness through the credential-free public-read transport.
The transport performs bounded GETs only to the fixed `rergards/mempalace-code`
GitHub API shapes, `mempalace-code` PyPI metadata and provenance, validated
`files.pythonhosted.org` distributions, and the manifest-owned reviewed upstream.
It ignores ambient proxies, credentials, cookies, netrc, redirects, and retry
configuration. Missing,
failed, stale, cancelled, skipped, or unqueryable evidence blocks publication and
prints one bounded remediation per row; the recovery command for each row is
tabulated in `docs/release-admission-rulesets.md`.
`scripts/release_readiness_gate.py --public-admission` can report the same
read-only public rows before artifact checks when the operator passes
`--candidate-sha`.

`.github/workflows/publish.yml` re-verifies the exact SHA, the aggregate check,
**Dependency Audit** freshness, and public ref state without `GH_TOKEN` or a
network Git fetch before any distribution is built or uploaded. Tag creation,
push, GitHub Release reconciliation, settings changes, and PyPI publication each
require separate explicit authorization; mutation credentials stay confined to
their existing publication owner.

The MCP protocol compatibility suite (`tests/test_mcp_protocol_compat.py`) is
part of this boundary: it proves the stable **2026-07-28** revision
(`server/discover`, per-request metadata) and the legacy `initialize` handshake
both still work over the unchanged `python -m mempalace_code.mcp_server` /
`mempalace.mcp_server` stdio entrypoints before a release ships.

The golden CLI scenario suite (`tests/test_cli_golden_scenarios.py`) is also
part of this boundary: it drives real `python -m mempalace_code.cli`
subprocesses — not in-process calls — through init, mine, status, search,
read, export, import, backup, and restore in a disposable temp HOME/palace,
plus at least one guard/failure path, so a release proves real user workflows
work end to end and not only unit internals. It is included in the default
`tests/ -x -q -m "not needs_network"` run above; the explicit line keeps this
workflow-evidence boundary named in the release checklist even if that default
selection changes.

## 2. Review public repository surfaces

Before asking for tag/publish approval, inspect the public repository as a
visitor would:

- README quick start, feature counts, Python minimum, and release badge.
- `CHANGELOG.md` for a concise user-facing entry for the pending version.
- `docs/AGENT_INSTALL.md`, `docs/LLM_USAGE_RULES.md`, and examples for current
  CLI/MCP behavior.
- GitHub About, topics, social preview, issue templates, license, and release
  notes.

The canonical GitHub About description is:

> Offline-first AI memory for coding — 29 MCP tools, temporal knowledge graph, and local vector search. No API keys, no cloud, no server.

Update the repository's GitHub About field whenever this sentence changes. The
local guard verifies the source text above; a maintainer must make and verify
the GitHub settings change separately.

## 3. Build the candidate on public `main`

Local `main` and public `main` are separate histories: public `main` carries one
squashed commit per release, so `git push publish main` from a development
branch is rejected as non-fast-forward. Never use `--force` or `--force-with-lease`
to resolve that; public `main` is protected against non-fast-forward updates and
history rewrites.

Instead, build a candidate commit whose **tree** is the reviewed local tree and
whose **parent** is current public `main`. Its later promotion is then always a
fast-forward. Two distinct SHAs are in play from here on — keep them apart:

| Name | Meaning |
|---|---|
| `REVIEWED_LOCAL_SHA` | the local commit whose tree you reviewed |
| `CANDIDATE_SHA` | the new commit carrying that tree on top of `publish/main` |
| `CANDIDATE_BRANCH` | the public branch that carries `CANDIDATE_SHA` for this attempt |

`CANDIDATE_SHA` — not `REVIEWED_LOCAL_SHA` — is the release candidate. It is
what every `--expect-sha`, tag target, and status-gate command below refers to.
`CANDIDATE_BRANCH` is the only branch name used from here on; nothing below
repeats a literal branch, so a retry needs no other edit.

```bash
git fetch publish main
REVIEWED_LOCAL_SHA=<40-hex-reviewed-local-sha>   # the tree you reviewed, verbatim
CANDIDATE_SHA=$(git commit-tree "$REVIEWED_LOCAL_SHA^{tree}" -p publish/main -m "release vX.Y.Z")

# One immutable branch name per attempt. First attempt is release/vX.Y.Z; a
# rebuild after a public push takes the next name — release/vX.Y.Z-rc2, then
# release/vX.Y.Z-rc3, and so on.
CANDIDATE_BRANCH=release/vX.Y.Z
git switch -C "$CANDIDATE_BRANCH" "$CANDIDATE_SHA"

# Tree parity proof — this MUST print nothing before you continue.
git diff --stat "$REVIEWED_LOCAL_SHA" "$CANDIDATE_SHA"

git rev-parse HEAD                               # must print $CANDIDATE_SHA
```

If `git diff --stat` prints anything, stop: the candidate does not carry the
reviewed tree. `git switch -C` is required because `--require-clean` and
`--expect-sha` bind `HEAD`, so the candidate must be checked out, not merely
created; `-C` also makes a local retry safe *before* the branch has been pushed.

Once a candidate branch exists on `publish` it is immutable. A rebuilt candidate
is a different commit, so pushing it over the branch you already published would
be a non-fast-forward update — never `--force` it and never update a published
candidate branch. Set `CANDIDATE_BRANCH=release/vX.Y.Z-rc2` (then `-rc3`, …) and
run this section again from `git fetch publish main`. Every attempt keeps its own
public check evidence, and the failed one stays readable.

### Installed-wheel acceptance

Build and validate the reviewed candidate without forwarding credentials or invoking
AI clients:

```bash
python -m build --wheel --outdir dist
python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json
```

The readiness gate builds in a disposable environment, inspects the wheel and
source distribution, then installs the exact wheel in a clean virtual environment.
It exercises package metadata and public CLI surfaces only. A successful run is
required before the candidate branch is pushed.

## 3a. Push the candidate branch and prove it green

Publish the candidate as its own public branch **before** it touches `main`.
Ask for explicit approval immediately before this external mutation:

```bash
git push publish "$CANDIDATE_BRANCH"
```

`.github/workflows/ci.yml` triggers on pushes to `main` **and** to `release/v*`,
which matches both the first attempt and every `-rcN` rebuild, so the candidate
branch runs the same complete `release-required` job graph that
`main` runs — including the two event-gated gates, `gitleaks-changed-range` and
`dependency-upgrade-gate`. Both derive their base from `github.event.before`,
which is all-zeros when a push creates a branch, and fall back to `origin/main`;
`origin/main..HEAD` is the same commit set, so nothing goes unscanned. A
`workflow_dispatch` run is still never release evidence: it skips those two
gates, and `release-required` fails closed on a skipped job.

Wait for the hosted checks to complete for `$CANDIDATE_SHA` itself, then confirm
the exact candidate from a clean checkout with the credential-free admission
owner:

```bash
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
python scripts/release_preflight.py --require-clean --expect-sha "$CANDIDATE_SHA" --check-required-check --check-dependency-audit --check-branch-rules --check-tag-ruleset
```

A non-zero exit means the release is not admissible. Fix the reported row and
rebuild the candidate; do not move `main`. Rebuilding means a fresh
`CANDIDATE_BRANCH` back in section 3 — never a second push over the branch that
already failed.

When the hosted x64 installed-application check fails at MiniLM compatibility,
read its single bounded annotation against the reviewed candidate with
`python scripts/release_public_read.py --check-run-annotations <CHECK_RUN_ID> --expect-sha <40-HEX-SHA>`.
The result authorizes only replanning the proved owner; by itself it never
authorizes a runtime, cache, or dependency change.

## 3b. Fast-forward the green SHA onto public `main`

Only an already-green `$CANDIDATE_SHA` is promoted, and only as a fast-forward:

```bash
git push publish "$CANDIDATE_SHA":refs/heads/main   # fast-forward only; never --force
git fetch publish main
git rev-parse publish/main                          # must print $CANDIDATE_SHA
```

Pushing a SHA that already carries its own green **Tests** and `release-required`
results is what keeps this sequence working if required status checks are later
added to public `main`: the checks for that commit already exist and are green
before the branch update is attempted, so the update is never blocked waiting for
checks that can only run after it.

## 3c. Re-admit against `main`, then tag

Public `main` has moved, so re-run exact-SHA admission — this time bound to
`publish/main` — before any tag exists:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --expect-sha <40-hex-candidate-sha> --candidate-ref publish/main --check-required-check --check-dependency-audit --check-branch-rules --check-tag-ruleset
```

A non-zero exit means the release is not admissible. Fix the reported row; do
not tag.

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push publish vX.Y.Z
```

The tag-only publish workflow verifies that the tag names the package version,
targets current public `main`, and matches the exact candidate SHA before any
wheel, sdist, PyPI artifact, or GitHub Release is created. It requires
`release-required` to be green for that SHA, requires a fresh **Dependency
Audit**, and queries the effective rules for `refs/heads/main` plus the active
`refs/tags/v*` ruleset. Hosted admission requires `non_fast_forward`, `deletion`,
and `required_status_checks` with `release-required`, plus tag `creation`,
`update`, and `deletion`. These public reads use no GitHub token. The workflow
also retains a direct live upstream comparison as defense in depth; that
post-tag check does not replace the canonical pre-tag command above.
Do not trigger PyPI publishing by a workflow dispatch or a release event.

## 4. Verify the public release

Wait for GitHub Actions and package-index propagation, then run:

```bash
python scripts/release_status_gate.py --version X.Y.Z --repo rergards/mempalace-code --remote publish --branch main --expect-sha <40-hex-candidate-sha>
```

`--expect-sha` takes `$CANDIDATE_SHA`, the commit that is on public `main` and
that the tag targets — never `REVIEWED_LOCAL_SHA`, which exists only locally.

The release is shipped only when this gate passes: public tag, branch Tests,
Publish to PyPI workflow, GitHub Release, PyPI wheel/sdist metadata, verified
provenance for every exact-version distribution, and the install metadata smoke
must agree. The provenance row uses the exact-pinned official verifier from the
frozen `uv.lock` resolution and requires publisher repository
`rergards/mempalace-code` plus workflow `.github/workflows/publish.yml` for every
public wheel and sdist, with trusted-publisher environment `release`. The install
smoke installs `package==X.Y.Z`
into a disposable venv and requires `importlib.metadata.version`,
`mempalace_code.__version__`, and `mempalace-code version-check --status` to
all report `X.Y.Z`. Record any remaining blocker instead of claiming a
completed release.

For the first release after the provenance gate lands, run the exact command
above against public PyPI without `--skip-smoke` or any mutation, and retain the
bounded `pypi_provenance` row with the release evidence. This is the live
read-only boundary for the hosted verifier path; automated tests use hermetic
fixtures and do not replace it.

The status gate always resolves the public tag itself, peeling an annotated tag
to the commit it publishes. With `--expect-sha` it reconciles that target against
the candidate SHA and fails when they differ, so a tag moved or recreated after
review cannot report green.

When no candidate SHA can be established — a malformed `--expect-sha`, or a
public tag that does not resolve — the exact-SHA workflow surfaces are reported
as failed rather than re-run against the branch's most recent workflow run. A
branch-latest run answers a different question, and letting it fill those rows
would print `ok` for a commit nobody reviewed inside an overall-failing report.

### Partial PyPI/GitHub publication recovery

The status gate recognizes one recoverable partial state: the newest tag-triggered
**Publish to PyPI** run belongs to `rergards/mempalace-code`, its tag and head SHA
match the public tag and `--expect-sha`, `build` and `publish` completed
successfully, and the unique `github-release` job failed. The original run's
artifact, exact PyPI filenames and SHA-256 digests, provenance, install smoke,
public `main` rules, tag-ruleset row, audit freshness, and every unrelated status
surface must also be valid. A missing Release may account for the current tag's
single orphan row.

Only that state emits this directly runnable command with concrete numeric IDs:

```bash
gh run rerun <publish-workflow-run-id> --job <github-release-job-id> --repo rergards/mempalace-code
```

Run the emitted command only after separate operator approval. It reruns the
single `github-release` job from the exact workflow run; `build` and the trusted
PyPI publisher remain untouched. The job rechecks repository, push event, tag,
SHA, public `main`, `release-required`, audit freshness, branch rules, the
original `dist` artifact, exact PyPI inventory, SHA-256 digests, and provenance.

The rerun creates a Release only when none exists. For an existing non-draft,
non-prerelease Release it validates every present asset digest, uploads only a
missing expected wheel or sdist, and repeats exact filename-set and digest
comparison. Unexpected, duplicate, or mismatched assets fail closed. The job
never overwrites or deletes an asset and never moves, deletes, or recreates the
tag.

Repeated requests while the run is in progress, a stale or wrong SHA, another
repository or tag, duplicated/missing jobs, failed prerequisites, unsafe Release
metadata, or any unrelated blocker emit `BOUNDED INSTRUCTION: no safe publication
mutation command is available`. Resolve the named row and rerun the canonical
read-only status command. Do not dispatch a new publish workflow or create the
Release manually. After any rerun, repeat the full status gate; the release is
shipped only after every surface is green.

The status gate also checks exact-SHA workflow evidence, the `release-required`
check-run, read-only public ref protection, public orphan tags, and **Dependency
Audit** freshness. A public `v*` tag without a matching non-draft GitHub
Release and PyPI identity is reported as orphan evidence. Reviewed permanent
exceptions are owned and documented by `scripts/release_admission_checks.py` and
`docs/release-admission-rulesets.md`; this runbook does not duplicate them.

The install smoke checks version-metadata agreement and alias provenance. Its
other CLI-specific surfaces are the Agent Plugin locator and declared MCP
launcher. It replaced an earlier smoke that only ran `mempalace-code update
--help`. That coverage is superseded, not carried forward: `main` CI's own
test/import coverage is what backstops other subcommand imports.

If a stale pipx, `uv tool`, or venv install reports a version that disagrees
with the published release, see the reinstall commands in
[`docs/AGENT_INSTALL.md`](AGENT_INSTALL.md#stale-installed-metadata-vs-imported-module).

## 5. Retire the candidate branch (explicit approval required)

`$CANDIDATE_BRANCH` is a temporary public branch. Leaving it costs nothing;
deleting it is an external mutation that destroys the branch pointer the release
was admitted through, so it needs its own approval — never fold it into the
approval for the tag or the promotion.

Delete it only after **all** of the following hold, and only after the maintainer
approves this specific deletion:

- `publish/main` is `$CANDIDATE_SHA` (section 3b verified it).
- The tag `vX.Y.Z` exists and targets `$CANDIDATE_SHA`.
- `release_status_gate.py` in section 4 exited 0.

```bash
# Only with explicit approval, and only when the three conditions above hold.
git push publish --delete "$CANDIDATE_BRANCH"
```

If any condition is unmet, or a `-rcN` attempt is still the newest evidence for a
release that has not shipped, keep the branch. A failed candidate branch is kept
deliberately: it is the public record of what was rejected.

## Maintainer checklist

- [ ] Explicit approval for tag, push, trusted PyPI publication, and any GitHub
      settings edit.
- [ ] The candidate was pushed as `$CANDIDATE_BRANCH` and proven green for that
      exact SHA *before* it was fast-forwarded onto public `main`.
- [ ] Any candidate rebuild took a new immutable branch name
      (`release/vX.Y.Z-rc2`, …); no published candidate branch was updated or
      force-pushed.
- [ ] Deleting `$CANDIDATE_BRANCH` was separately approved, and only after
      promotion and `release_status_gate.py` both passed.
- [ ] `main` CI, package build/install smoke, and relevant benchmark workflow
      are green for the release commit.
- [ ] `docs_drift_guard`, public-safety scan, scorecard freshness, tests, lint,
      format, and type checks pass.
- [ ] Version, changelog, README badge, MCP/profile counts, and Python minimum
      agree.
- [ ] Agent Plugin package data is present in wheel and sdist, and
      `mempalace-code-mcp --profile=minimal` lists the minimal tools from a
      fresh install.
- [ ] GitHub About matches the canonical description above; topics, social
      preview, issue templates, and license remain appropriate for public use.
- [ ] Tag workflow succeeded, GitHub Release is non-draft/non-prerelease, PyPI
      has both distribution types, every file has verified expected provenance,
      and `release_status_gate.py` passes.
- [ ] `release-required` is successful for the candidate SHA, public
      `refs/heads/main` and `refs/tags/v*` match
      `docs/release-admission-rulesets.md`, and the latest **Dependency Audit**
      run is fresh.
