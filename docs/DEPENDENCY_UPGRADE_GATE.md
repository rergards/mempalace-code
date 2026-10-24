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

6. **Push a lock refresh only with a passing report** — the lock file is
   updated in step 2, before the audit, so the report captures the final
   hashes. Do not push a lock-file refresh without a passing report.

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

- **Push that creates a branch** (e.g., a `release/v*` candidate) → GitHub
  sends an all-zeros `before` SHA. The Tests workflow diffs that case against
  `origin/main`, the candidate's parent, instead of passing the all-zeros SHA
  to the gate.

- **Base ref unresolvable** (e.g., an unfetched force-pushed `before` SHA, or
  an all-zeros SHA passed to the script directly) → the gate treats the
  dependency files as changed and fails closed, so a broken base ref can never
  let an unaudited bump through.

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
- Checks **every package pinned in `uv.lock`**, direct and transitive, against
  OSV advisories in one `querybatch` request. A failed request, or a response
  that does not answer every package in full (a missing result, or one OSV
  paginates), fails the audit; an unanswered package is never treated as clean.
  Only the project's own local (editable or virtual) lock entry is skipped.
- Scopes each advisory finding for the allowlist: a direct dependency carries its
  declared specifier and every group that declares it (`runtime`, `dev`,
  `extra:<name>`); a transitive package carries `transitive` and its exact lock
  pin (`==<version>`). A package declared in several groups is one finding, not
  one per group.
- Checks the locked version of each direct dependency against PyPI yanked
  metadata. A lookup that does not complete (network, HTTP, timeout, or a
  malformed response) is a blocking `yanked_lookup_failed` finding, never a
  silent "not yanked"; rerun the audit once PyPI answers, and if the failure
  persists, check that the locked version still exists on PyPI.
- Runs fresh, unpinned resolver audits (`pip-audit`) for the default install,
  `dev`, and every optional extra, so the versions a new `pip install` resolves
  are covered as well as the lock pins.
- Reports range-drift findings when a custom range-drift querier is provided;
  the default scheduled run does not perform range-drift checks (range
  intersection requires a live advisory range-scan that is not included in
  the default implementation).
- Uploads a sanitized JSON/Markdown artifact on every run.
- Creates or updates a single GitHub issue (`[dependency-audit] current dependency
  audit findings`, labelled `dependency-audit`) when actionable findings exist on
  `main`, matching it by exact title. Candidate-branch findings fail the workflow
  and retain their artifacts without changing the main issue. A missing label
  is a visible warning, not a silent fallback.
- Closes that issue, with a comment linking the run, on the next clean run of
  `main` (scheduled, or dispatched from `main`); a clean dispatch from another
  branch audits that branch's lock and leaves the issue open. The close step
  cannot fail a clean run, because release admission reads the run conclusion.
  An `accepted_risk` run updates the issue on `main` and keeps it open. Candidate
  branches never create, update or close it.

### Scheduled Audit Commands

```bash
# Run a local current audit (no network calls in tests — injectable mocks)
python scripts/dependency_upgrade_gate.py current-audit \
  [--root .] \
  [--allowlist docs/dependency-audit-allowlist.json] \
  [--out-dir dependency-audit-output]
```

Output files (git-ignored, never committed; uploaded as workflow artifacts):

| File | Description |
|------|-------------|
| `dependency-audit-output/current-audit-report.json` | Sanitized JSON with the number of locked packages audited, findings, resolver audit results, and allowlist summary. |
| `dependency-audit-output/current-audit-issue-body.md` | GitHub issue body for failure notification. |

### Public-Safe Output Contract

Scheduled audit reports, artifacts, and issue payloads are **public-safe**.
They contain only:

- Package names and versions
- Advisory IDs (e.g., `GHSA-…`)
- Remediation notes derived from the advisory ID and package name
- Fixed setup-failure classifications and numeric exit codes

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
| `affected_range` | Yes | Must exactly match the finding's range: the declared specifier in `pyproject.toml` for a direct dependency, or `==<locked version>` for a transitive package, so a lock refresh re-opens the review. |
| `reason` | Yes | Non-empty explanation of why the risk is accepted. |
| `expires` | Yes | ISO date (`YYYY-MM-DD`). Entry is rejected on or after this date. |

Entries are fail-closed: expired entries, missing fields, or mismatched
`affected_range` values cause the audit to fail as if no entry existed.

Current-audit applies reviewed entries to both locked OSV findings and fresh
pip-audit findings. A fresh-install exception must match the **actual resolved
version exactly**, using `==<version>`. Published advisory aliases can identify the
same advisory; the report retains the primary ID, aliases and accepted ID. Unknown
or skipped third-party dependencies, invalid JSON, inconsistent exit status,
tooling failure and additional vulnerabilities block acceptance. The local
`mempalace-code` distribution can be skipped because it has no published advisory
identity. Dependency-upgrade `audit` is strict except for the exact transition
described below.

### Exact trust-tools transition

The maintainer approved reuse of the existing 40 accepted risks for the
2026-10-23 transition: certifi 2026.10.19 to 2026.10.23, Sigstore 4.5.0 to
4.5.1, and removal of its unused PyOpenSSL dependency. A separately approved
security follow-up adds `opentelemetry-api>=1.45.1`, locks API 1.45.1 and
cryptography 50.0.2, and updates the existing scanner toolchain to Go 1.27.3.
On 2026-10-24 the maintainer approved a further exact transition: require
`filelock>=4.2.1`, lock filelock 4.2.4, and require `setuptools>=84.1.0` only
in the existing `custom-models` extra while locking setuptools 84.2.1. This
approval also adds the two Pillow IDs described below. All 40 prior entries
remain unchanged; the reviewed file contains 42 entries, including the
superseded OpenTelemetry entry. No expiry is extended or future snapshot
authorized. The binding names only this final dependency state.

`_TRUST_TOOLS_SNAPSHOT` in the existing gate binds the exact target
`pyproject.toml`, `uv.lock`, and reviewed risk-file SHA-256 hashes. Only that
snapshot can reuse the current-audit evaluator. Default, dev, and custom-models
fresh resolver audits are required for this transition; declared changed extras
remain in the plan. An affected upgrade target still blocks.
Other snapshots retain the strict upgrade policy.

Reports retain raw findings and actual audited versions and use `accepted_risk`
when any resolver retains approved vulnerabilities. `verify-report` and
`ci-check` re-evaluate those findings against the current source tree, dependency
owner pins, exact risk data, and current expiry date. Edited risk data, unknown
IDs, version or source drift, missing evidence, audit errors, and expired entries
cannot use the exception. The original review date is 2026-10-29; all entries
expire on 2026-11-05. Accepted risk does not mean that the packages are patched.

Reports distinguish `clean`, `accepted_risk` and blocking `findings`. Fresh resolver
rows retain `raw_status` and sanitized vulnerability identities. A successful
`accepted_risk` exit permits admission under the explicit exception; it does not
claim a clean inventory or a fixed dependency. Main's tracking issue remains open.

An optional top-level `context` binds usage-based exceptions to the reviewed
`mempalace_code_tree` Git object and exact `packages` versions (a string or explicit
list of reviewed pins). The code must match
HEAD with no tracked changes or untracked package files. A missing Git tree,
changed code or changed resolved owner version invalidates all scoped entries.
This context includes `accepted_on` and `review_on` dates. Its entries expire no
later than 14 days after acceptance; review precedes expiry. Duplicate or malformed
entries cannot grant acceptance. The dated review is a maintainer action; the
audit automatically enforces expiry on each run and does not launch an AI reviewer.
Release preflight revalidates the same entries at admission time. A previous
successful hosted audit cannot extend an exception beyond its expiry, even while
that workflow result remains inside the normal freshness window.

### Temporary Pillow risk acceptance

Accepted on **2026-10-22**, review on **2026-10-29**, expires on **2026-11-05**.
The existing allowlist records the exact 41 advisory IDs for **Pillow 12.3.0**.
The original 28 were accepted on 2026-10-22. The additional 11 were conditionally
accepted on 2026-10-23 after comparison with published 1.16.0 established no
new vulnerable operation in the inspected canonical path. The original risk
window, review date and expiry remain unchanged.
On 2026-10-24 the maintainer separately accepted GHSA-5x8w-8jj5-q52h
(Critical FPX/JPEG decoding overflow) and GHSA-654x-cwwv-5j9c (Moderate
image-to-Arrow heap disclosure), retaining the same review date and expiry.
Both fixes ship in Pillow 13.0.0, which conflicts with the Pillow `<13`
requirement of the supported FastEmbed releases. No dependency override is used.
It is bound to **FastEmbed 0.8.0** in the lock, **0.8.1** in fresh installs, and the
reviewed application package tree. MCP 2.3.0 and OpenTelemetry API 1.40.0/1.45.1
are also pinned by the shared context; any other owner version invalidates it.
The exception introduces no fork, dependency override, model change or Pillow upgrade.

The reviewed canonical MiniLM path supplies strings to FastEmbed's text tokenizer
and numerical ONNX inference. It does not invoke the affected image/PDF operations.
FastEmbed imports Pillow through shared image/type modules; import alone does not
decode an image. A bounded installed check also processed six synthetic texts
with 13 Pillow image/PDF entrypoints blocked and observed no calls. Source review,
primary advisories and independent security review establish the applicability
rationale; that bounded run alone is not a universal proof.

| Advisory | Severity | Required operation absent from canonical text inference |
| --- | --- | --- |
| GHSA-5x8w-8jj5-q52h | Critical | Decode crafted FPX/JPEG image scanlines |
| GHSA-654x-cwwv-5j9c | Moderate | Export a Pillow image through Arrow |
| GHSA-462x-pgg6-55fp | Moderate | Crafted tiled TIFF decoding |
| GHSA-58r4-6rv3-gfh8 | High | Morphology on a zero-width image |
| GHSA-65qm-jvmh-6pqg | High | GIF reuse after an oversized-frame exception |
| GHSA-8g5g-8vmr-9782 | Critical | Crafted JPEG decoding after draft/thumbnail scaling |
| GHSA-c6hw-5grf-ff96 | High | TIFF tile/RGBA decoding |
| GHSA-p4wg-p73j-c528 | High | Existing PDF parsing, including append/save |
| GHSA-pchr-8j38-3x4p | High | TIFF encoding with retained ColorMap metadata |
| GHSA-q45j-58j2-45rg | High | TIFF decoding with shortened image data |
| GHSA-vx6w-vv9f-6gvg | Moderate | Scaled EPS rendering through Ghostscript |
| GHSA-22hg-r758-rrw9 | High | Read MIC image frame counts |
| GHSA-254f-3936-288h | Moderate | Parse PDF values or page trees |
| GHSA-27h8-gf7j-v5hc | High | Apply rank filters to images |
| GHSA-332p-7hrc-92wf | Critical | Save TIFF to in-memory buffers |
| GHSA-4558-3h8r-v8xp | Moderate | Decode packed P;2L or P;4L image pixels |
| GHSA-4rr5-89j8-mwwm | Moderate | Encode TIFF to in-memory buffers |
| GHSA-5xm2-6676-qcp9 | High | Decode APNG frames |
| GHSA-74r2-7ff9-mjj2 | Moderate | Open GIF images or concatenate their comments |
| GHSA-7mwm-ghpf-9vrm | High | Transform image pixels |
| GHSA-cp9v-662q-vvx9 | High | Merge image bands |
| GHSA-f2g6-542v-9j58 | High | Rewrite PDF page trees |
| GHSA-fc9g-5qg7-mf45 | Moderate | Save GIF comments |
| GHSA-gg2r-wvfm-q9rx | High | Decode MSP RLE images |
| GHSA-j4m9-6w36-pw47 | High | Render FreeType glyphs with a stroker |
| GHSA-jg86-v3jv-hrpm | High | Save images as multipage PDFs |
| GHSA-rfgq-q3w2-pmv2 | Moderate | Quantize image pixels with a palette |
| GHSA-w889-685w-c8fh | Critical | Render EPS through Ghostscript |
| GHSA-xgh8-jp6q-p5x8 | Moderate | Open XBM images |
| GHSA-xvh5-g6gv-559v | High | Encode TIFF tags with libtiff |
| GHSA-24rc-8hj2-v98c | Moderate | Decode crafted BMP RLE data |
| GHSA-3j72-p6qg-6xp7 | High | Traverse crafted archives with PIL.TarIO |
| GHSA-4rm8-3hmm-39fg | Moderate | Load or measure crafted PILfont metrics |
| GHSA-78g4-xqwv-q3g8 | High | Decode JPEG 2000 through OpenJPEG |
| GHSA-9v9v-9qvf-h2hj | High | Render WMF or EMF through Windows native handlers |
| GHSA-g4qv-2jxx-769h | High | Parse crafted EXIF markers |
| GHSA-g7cr-3p24-7wf7 | High | Encode JPEG with ICC profiles and comments |
| GHSA-g842-9rc4-69pw | High | Seek or load SPIDER frames |
| GHSA-mrfp-p49p-3hf2 | High | Append images to crafted PDF page trees |
| GHSA-p8hx-v2p6-rp84 | Moderate | Seek or load MPO or DCX frames |
| GHSA-v9pv-5gc8-w2m6 | Critical | Decode multiframe images into native image storage |

The maintainer accepted the additional 19 IDs on 2026-10-22 under the same
review and expiry dates. The 28 findings include three Critical, sixteen High
and nine Moderate advisories; their component severity is unchanged. FreeType
glyph rendering is separate from the tokenizer used for canonical text inference.

The component remains vulnerable, including the Critical JPEG, TIFF and EPS findings. This is
an accepted temporary residual risk, not a claim that all MemPalace configurations
are unaffected. Arbitrary `[custom-models]` implementations and applications using
Pillow's image APIs are outside the canonical-path conclusion. Their exposure
requires a separate assessment; installing an extra alone does not demonstrate
an exploitable image path. The acceptance retains this uncertainty explicitly.

Reassess immediately on an application tree or FastEmbed change, a new advisory,
image/PDF processing or model change. At review, check published compatible
FastEmbed/Pillow releases and replace these entries with a normal audited upgrade
when one exists. No automatic renewal is permitted. Deleting an entry, changing
its pinned version or reaching expiry restores the blocking finding.

Primary examples: https://github.com/advisories/GHSA-8g5g-8vmr-9782,
https://github.com/advisories/GHSA-p4wg-p73j-c528 and
https://github.com/advisories/GHSA-65qm-jvmh-6pqg.

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


### Temporary OpenTelemetry risk acceptance

On **2026-10-23** the maintainer authorized publication when security does not
degrade relative to published 1.16.0. Independent engineering reviewers compared
the official artifacts and the reviewed application. The exact additional
exception is **GHSA-xcq7-p3pf-p88h**, **opentelemetry-api 1.40.0**, **Moderate**,
review **2026-10-29**, expiry **2026-11-05**. It shares the original risk window;
acceptance was not renewed or extended.

The published 1.16.0 lock already contains MCP 2.0.0, OpenTelemetry API 1.40.0
and Pillow 12.3.0. Official MCP 2.0.0 and 2.3.0 both enable trace middleware by
default; their trace-extraction modules are byte-identical. Crafted MCP `_meta`
can reach the vulnerable parser. This is a retained reachable denial-of-service
risk. HTTP header limits do not bound the stdio carrier. It is not covered by
Pillow's canonical-text non-reachability rationale.

That earlier snapshot allowed compatible existing installations to retain API
1.40.0. The maintainer subsequently approved the explicit `>=1.45.1` floor and
lock update. An ordinary upgrade now replaces the old API; a conflicting old pin
is refused. The historical acceptance record remains unchanged, while current
locked and fresh audits retain only the 39 Pillow findings. The exact approved
snapshot uses the bounded upgrade route above; earlier failed strict-audit
receipts remain historical evidence.

The release also raises the patched MCP, fsspec and certifi requirements and
adds reviewed data-preservation guards. The source comparison and bounded
23-trap text test establish no observed new Pillow operation in the canonical
MiniLM path. Arbitrary custom-model implementations remain outside that
applicability conclusion; their adapter and declared capability are unchanged.
This decision does not classify the dependency inventory as clean.

Primary artifact metadata:

- https://pypi.org/pypi/mempalace-code/1.16.0/json
- https://pypi.org/pypi/mcp/2.0.0/json
- https://pypi.org/pypi/mcp/2.3.0/json
- https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h

The additional 11 Pillow findings comprise one Critical, seven High and three
Moderate advisories. Together with the original 28, Pillow retains four Critical,
23 High and 12 Moderate findings. The separate OpenTelemetry finding is Moderate.
All IDs, component severities and raw audit findings remain visible. Unknown IDs,
version or code drift, audit errors and expiry block admission. No automatic
renewal or future advisory acceptance is authorized.
