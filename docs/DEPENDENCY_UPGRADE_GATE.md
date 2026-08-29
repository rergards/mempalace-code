# Dependency Upgrade Gate

Repeatable, audited process for raising package ceilings or refreshing the
lock file. A dependency change must not land without a passing report.

## Required Gate Order

1. **Collect targets** — create a target manifest JSON that names each
   package's proposed target version, the dependency groups that changed, and
   the optional extras whose bounds changed.

2. **Update pyproject.toml and refresh uv.lock** — apply the new bounds
   locally and run `uv lock` so the lock file reflects the proposed state.

3. **Query advisories** — `audit` calls the OSV `querybatch` API for every
   direct dependency (current and target versions). Any target version that
   appears in an active advisory fails the gate before resolver tests run.

4. **Run fresh resolver audits** — for the default install and every changed
   group or extra, the gate creates a disposable temp venv, installs the
   package, runs `pip-audit`, and records the result. The developer's `.venv`
   is never modified.

5. **Write the public report** — if advisories and resolver audits pass, the
   gate writes a redacted JSON report to
   `docs/dependency-upgrade-reports/<slug>.json` recording the
   `pyproject_hash`, `lockfile_hash`, verdict, and sanitized summaries. No
   private paths, resolver caches, or credentials appear in the report.

6. **Refresh uv.lock only after success** — the lock file should be updated
   (step 2 above) before the audit so the report captures the final hashes.
   Do not push a lock-file refresh without a passing report.

7. **Commit pyproject.toml, uv.lock, and the report together** — CI's
   `ci-check` requires that the report's recorded hashes match the committed
   dependency files. Committing them separately causes the gate to fail.

8. **Run hosted-CI-equivalent clean pip tests** — after the lock is updated,
   run the test suite in a fresh `pip install` environment (not uv.lock-pinned)
   to catch resolver drift between platforms.

## Target Manifest Schema

```json
{
  "targets": {
    "lancedb": "0.33.0",
    "fastembed": "0.8.0",
    "onnxruntime": "1.29.0"
  },
  "changed_groups": ["runtime"],
  "changed_extras": ["custom-models"]
}
```

Fields:

| Field            | Type            | Description |
|------------------|-----------------|-------------|
| `targets`        | object          | Map of package name → exact target version. Must include every package in each named changed group and changed extra. Unknown package names are rejected. |
| `changed_groups` | array of strings | Groups whose bounds changed: `"runtime"` or `"dev"`. |
| `changed_extras` | array of strings | Optional extra names (e.g. `"spellcheck"`, `"treesitter"`) whose bounds changed. |

## Public Report Schema

Reports live at `docs/dependency-upgrade-reports/<slug>.json`. They are
public-safe: no private paths, tokens, resolver cache paths, or hostnames.

```json
{
  "schema_version": 1,
  "status": "success",
  "slug": "<slug>",
  "pyproject_hash": "sha256:<hex>",
  "lockfile_hash": "sha256:<hex>",
  "dependencies": [
    {
      "name": "lancedb",
      "normalized_name": "lancedb",
      "group": "runtime",
      "specifier": ">=0.20",
      "current_version": "0.20.0",
      "target_version": "0.33.0"
    }
  ],
  "advisory_results": [
    {
      "name": "lancedb",
      "version": "0.33.0",
      "role": "target",
      "advisories": [],
      "status": "clean"
    }
  ],
  "resolver_audits": [
    {
      "extras": [],
      "status": "success",
      "summary": "resolver audit for (default): success"
    }
  ]
}
```

| Field              | Description |
|--------------------|-------------|
| `schema_version`   | Always `1` for this schema. |
| `status`           | `"success"` or `"blocked"`. CI requires `"success"`. |
| `pyproject_hash`   | `sha256:<hex>` of `pyproject.toml` at audit time. |
| `lockfile_hash`    | `sha256:<hex>` of `uv.lock` at audit time. |
| `dependencies`     | All direct runtime, dev, and optional-extra dependencies with current and target versions. |
| `advisory_results` | Per-package-version advisory query results. `role` is `"current"` or `"target"`. |
| `resolver_audits`  | One entry per fresh-env audit (default install + each changed group/extra). |

## Commands

```bash
# Run the full audit
python scripts/dependency_upgrade_gate.py audit \
  --manifest targets.json \
  [--slug my-upgrade] \
  [--root .]

# Verify an existing report
python scripts/dependency_upgrade_gate.py verify-report \
  docs/dependency-upgrade-reports/my-upgrade.json \
  [--root .]

# CI enforcement check
python scripts/dependency_upgrade_gate.py ci-check \
  --base-ref <sha> \
  [--root .]
```

## CI Behavior

The Tests workflow runs `ci-check` on every pull request and push:

- **Neither `pyproject.toml` nor `uv.lock` changed from the base ref** →
  gate passes immediately (no report required). Clean PRs that do not touch
  dependencies are never blocked.

- **Only release/package metadata changed** → gate passes without a report when
  dependency-relevant `pyproject.toml` content is unchanged and `uv.lock` differs
  only by the root editable package version. Normal release version bumps do not
  require a dependency-upgrade audit report.

- **Either file changed from the base ref** → the gate requires exactly one
  report under `docs/dependency-upgrade-reports/` whose `pyproject_hash` and
  `lockfile_hash` match the current workspace files, and whose `status` is
  `"success"`. A missing report, hash mismatch, or non-success status fails
  the gate.

- **Base ref unresolvable** (e.g., all-zeros SHA on a force-push) → the gate
  treats the dependency files as changed and fails closed, so a broken base
  ref can never let an unaudited bump through.

## Verification Boundary

The `ci-check` step added to `.github/workflows/ci.yml` — including the
`fetch-depth: 0` checkout change and the base-ref event expressions — is
syntax- and version-checked by `actionlint`. Its hosted runtime behavior is
not execution-tested unless a real `pull_request` or `push` trigger runs the
Tests workflow.

---

## Scheduled Current Audit

The `dependency-audit.yml` workflow, named **Dependency Audit** in GitHub
Actions, runs a `current-audit` on a weekly schedule and on
`workflow_dispatch`. Unlike the upgrade gate, this audit:

- Does **not** change dependency bounds, specifiers, or `uv.lock`.
- Checks the **current resolved packages** against advisory databases and yanked
  package metadata.
- Reports range-drift findings when a custom range-drift querier is provided;
  the default scheduled run does not perform range-drift checks (range
  intersection requires a live advisory range-scan that is not included in
  the default implementation).
- Uploads a sanitized JSON/Markdown artifact on every run.
- Creates or updates a single GitHub issue (`[dependency-audit] current dependency
  audit findings`) when actionable findings exist.

### Scheduled Audit Commands

```bash
# Run a local current audit (no network calls in tests — injectable mocks)
python scripts/dependency_upgrade_gate.py current-audit \
  [--root .] \
  [--allowlist docs/dependency-audit-allowlist.json] \
  [--out-dir dependency-audit-output]
```

Output files (never committed; uploaded as workflow artifacts):

| File | Description |
|------|-------------|
| `dependency-audit-output/current-audit-report.json` | Sanitized JSON with findings, resolver audit results, and allowlist summary. |
| `dependency-audit-output/current-audit-issue-body.md` | GitHub issue body for failure notification. |

### Public-Safe Output Contract

Scheduled audit reports, artifacts, and issue payloads are **public-safe**.
They contain only:

- Package names and versions
- Advisory IDs (e.g., `GHSA-…`)
- Remediation notes derived from the advisory ID and package name

They **never** include: raw resolver output, private paths, temp directory paths,
resolver cache directories, credentials, hostnames, tokens, or private remote names.

### Allowlist Schema

Known accepted risks must be added to `docs/dependency-audit-allowlist.json`.
Each entry requires all five fields; missing or partial entries are rejected.

```json
{
  "schema_version": 1,
  "entries": [
    {
      "advisory_id": "GHSA-xxxx-xxxx-xxxx",
      "package": "example-pkg",
      "affected_range": ">=1.0,<2.0",
      "reason": "This advisory does not affect our usage pattern; see issue #NNN.",
      "expires": "2026-12-31"
    }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `advisory_id` | Yes | Exact advisory ID from OSV (e.g., `GHSA-…`). |
| `package` | Yes | Package name (normalized, case-insensitive). |
| `affected_range` | Yes | Must exactly match the declared specifier in `pyproject.toml`. |
| `reason` | Yes | Non-empty explanation of why the risk is accepted. |
| `expires` | Yes | ISO date (`YYYY-MM-DD`). Entry is rejected on or after this date. |

Entries are fail-closed: expired entries, missing fields, or mismatched
`affected_range` values cause the audit to fail as if no entry existed.

### Scheduled Audit Verification Boundary

The `dependency-audit.yml` workflow is syntax-checked by `actionlint` and its
wiring is covered by unit tests (workflow shape, trigger presence, artifact
upload, issue notification steps). Its **hosted** schedule execution and live
OSV/PyPI network behavior are not proven by unit tests — they require a real
GitHub Actions run triggered via `schedule` or `workflow_dispatch`.

### Release Admission Freshness

Release admission uses `scripts/release_admission_checks.py` to inspect the
latest completed **Dependency Audit** workflow run through read-only GitHub
Actions metadata. The latest completed `schedule` or `workflow_dispatch` run
must have conclusion `success` and must be no older than 192 hours.

The window is the weekly audit cadence (168 hours) plus 24 hours of slack. A
window equal to the cadence would flip to stale on every scheduler delay and
turn a healthy repository into a blocked release; a genuinely skipped week is
still older than the window and still fails closed. The cadence, the slack, and
the resulting window live in `DEPENDENCY_AUDIT_CADENCE_HOURS` and
`DEFAULT_AUDIT_MAX_AGE_HOURS`, and `scripts/docs_drift_guard.py` fails when this
paragraph disagrees with them.

Runs are ordered by parsed timestamp rather than by GitHub's response order.
Missing runs, failed runs, cancelled runs, skipped runs, stale timestamps,
timestamps in the future (an untrustworthy clock), expired evidence, unparseable
responses, and GitHub API or permission errors all fail closed. The bounded
remediation is `gh workflow run 'Dependency Audit' --repo rergards/mempalace-code`
— the repository is named explicitly so a shell defaulted to a fork cannot
dispatch the wrong one — wait for a successful fresh run, then rerun release
preflight or status. Release admission does not edit dependency files, issues,
rulesets, tags, or releases.
