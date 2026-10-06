# Installed-candidate acceptance reports

One report per release, `vX.Y.Z.md`, written by the installed-candidate acceptance
test in [`docs/RELEASING.md`](../../RELEASING.md) section 1a. A release cannot be
tagged without it: the tag preflight, which the tag workflow repeats, reports an
`acceptance_report` row that must be `ok`:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean
```

## What the preflight checks

The check is deterministic, offline, and credential-free. It reads only local git
objects and fails unless:

- `docs/quality/acceptance/vX.Y.Z.md` is committed at `HEAD`;
- the front-matter header has every required field below, well formed;
- the report is UTF-8 text;
- `version` equals `project.version` in `pyproject.toml` exactly, without a `v` prefix;
- `date` is a real calendar date in `YYYY-MM-DD` form;
- `result` is exactly `PASS`;
- `mempalace_code_tree`, `pyproject_toml_blob`, and `uv_lock_blob` equal the ids
  `HEAD` has for `mempalace_code/`, `pyproject.toml`, and `uv.lock`;
- the report has `## Coverage`, `## Issues`, and `## Re-test` sections outside code fences;
- the report contains no absolute local path or secret-like token.

Git object ids depend only on content, so they survive the candidate commit that
carries the reviewed tree onto public `main`. Any change to package code, package
metadata, or the lock after testing changes an id and needs a new round.
Documentation-only commits keep every id and need no new round. The ids do not
cover user-run files outside the package, such as `hooks/` or
`scripts/bootstrap.sh`; after changing one, re-test its area and record that
round.

The preflight proves the report is bound to the tree. Whether the report is true
and complete is for the reviewer.

## Header fields

| Field | Required | Value |
|---|---|---|
| `version` | yes | `project.version`, for example `1.15.0` |
| `date` | yes | Day the final re-test round finished, `YYYY-MM-DD` |
| `result` | yes | `PASS` or `FAIL`; see the exit rule below |
| `mempalace_code_tree` | yes | `git rev-parse HEAD:mempalace_code` |
| `pyproject_toml_blob` | yes | `git rev-parse HEAD:pyproject.toml` |
| `uv_lock_blob` | yes | `git rev-parse HEAD:uv.lock` |
| `wheel_sha256` | yes | Lowercase SHA-256 of the tested wheel |
| `wheel` | no | Wheel filename |
| `previous_release` | no | The release used for the upgrade test |
| `platforms` | no | Operating systems and Python versions tested |

The wheel digest identifies the tested artifact. The preflight binds the source ids
instead, because the tag workflow rebuilds the distributions from the same tree.

`result: PASS` requires complete direct functional coverage under RELEASING
section 1a. Every discovered supported command/subcommand and enabled MCP tool
in every profile needs actual installed-interface execution and checked results.
Separate success, documented refusal, failure/retry, and discovery-only evidence.
Help, parser errors, listings, direct handler calls and source-test counts cannot
substitute for operation coverage. Missing required coverage is blocking `UNRUN`;
it cannot be deferred to obtain PASS. Platform-specific cases run on a supported
platform. No confirmed critical or high issue may remain open; other product
findings must be fixed or explicitly deferred with a reason and a backlog reference.

## Sections

- **Coverage**: one row for each area in `docs/RELEASING.md` section 1a. Name the
  environments (venv, `pipx`, `uv tool`, base or which extras), what was exercised,
  and the outcome: `pass`, `fail`, or `not run` with the reason. A `not run` row is
  a deferred finding and needs an issue-list entry.
- **Issues**: every problem found, with an ID, severity (`critical`, `high`,
  `medium`, `low`), area, summary, reproduction (commands, input, expected and
  actual result), and disposition: `fixed` with the commit, `deferred` with the
  reason and follow-up, or `not a bug` with the reason.
- **Re-test**: one entry per round with the ids it tested, the reproductions and
  areas it re-ran against the rebuilt wheel, and the outcome. The last round's ids
  are the header ids.

## Public safety

The report is published with the repository. Use placeholders such as `$HOME`,
`<project>`, and `<palace>` in reproductions. Never include local absolute paths,
user or host names, IP or email addresses, credentials, tokens, private repository
names, or transcript text. The tag preflight scans the committed report more
strictly than `scripts/public_safety_scan.py --tracked --staged`: it rejects any
absolute root such as `/tmp/`, `/opt/`, or `/home/`, not only this machine's paths.
After committing, run `python scripts/release_preflight.py --tag vX.Y.Z` and confirm
the `acceptance_report` row is ok.

## Template

```markdown
---
version: X.Y.Z
date: YYYY-MM-DD
result: PASS
mempalace_code_tree: <git rev-parse HEAD:mempalace_code>
pyproject_toml_blob: <git rev-parse HEAD:pyproject.toml>
uv_lock_blob: <git rev-parse HEAD:uv.lock>
wheel_sha256: <sha256 of the tested wheel>
wheel: mempalace_code-X.Y.Z-py3-none-any.whl
previous_release: <previous version>
platforms: <operating systems and Python versions>
---

# Installed-candidate acceptance: vX.Y.Z

## Coverage

| Area | Environments | Exercised | Outcome |
|---|---|---|---|
| Install and onboarding | | | |
| Project mining, search, read | | | |
| Conversations | | | |
| MCP over real stdio | | | |
| KG, architecture, graph | | | |
| Data lifecycle | | | |
| Watch, schedules, updates, concurrency | | | |
| Migration, offline, custom models | | | |
| LLM-agent perspective and hooks | | | |

## Issues

| ID | Severity | Area | Summary | Reproduction | Disposition |
|---|---|---|---|---|---|

## Re-test

| Round | Tested ids | Re-run | Outcome |
|---|---|---|---|
```
