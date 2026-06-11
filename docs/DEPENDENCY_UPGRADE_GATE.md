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
    "sentence-transformers": "2.7.0"
  },
  "changed_groups": ["runtime"],
  "changed_extras": []
}
```

Fields:

| Field            | Type            | Description |
|------------------|-----------------|-------------|
| `targets`        | object          | Map of package name → exact target version. Must include every package in each named changed group and changed extra. Unknown package names are rejected. |
| `changed_groups` | array of strings | Groups whose bounds changed: `"runtime"` or `"dev"`. |
| `changed_extras` | array of strings | Optional extra names (e.g. `"chroma"`, `"spellcheck"`) whose bounds changed. |

## ChromaDB 1.x Hold Policy

ChromaDB is a deprecated legacy backend. It is capped at `<1` because
`GHSA-f4j7-r4q5-qw2c` affects the currently available 1.x line.

The current safe ceiling is `chromadb>=0.5.0,<1`.

A target manifest that raises ChromaDB into a 1.x version will be rejected by
the advisory gate as long as `GHSA-f4j7-r4q5-qw2c` remains active for that
target. The ceiling must not be raised until:

1. The advisory source confirms the chosen 1.x target is advisory-clean.
2. The full `audit` command passes (advisory gate + resolver audit).
3. A passing report with the new hashes is committed together with the
   pyproject and lock-file changes.

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
