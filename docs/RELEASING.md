# Releasing mempalace-code

This runbook defines the public release boundary. It covers package metadata,
documentation, build artifacts, GitHub, PyPI, and a fresh-install check. It
does not authorize a tag, push, GitHub settings change, or PyPI publication;
each external mutation requires the operator's explicit approval.

## Release invariants

- The release tag is exactly `v<project.version>` from `pyproject.toml`.
- The tag targets the current `main` commit after the branch CI is green.
- The checked-out, committed tree passes public-safety and documentation-drift
  checks.
- The published package contains both a wheel and an sdist, and a fresh virtual
  environment can install the wheel.
- The wheel and sdist contain the Agent Plugin package root with `plugin.json`,
  `mcp.json`, `skills/mempalace/SKILL.md`, vendored Agent Plugins 1.0.0
  schemas, and the schema notice.
- A fresh install's `importlib.metadata.version("mempalace-code")`,
  `mempalace_code.__version__`, and `mempalace-code version-check --status`
  all report the same version. The same install smoke runs
  `mempalace-code agent-plugin path`, validates the manifests from the
  installed package, and launches the declared
  `mempalace-code-mcp --profile=minimal` command to list the portable minimal
  tools - see `scripts/release_install_metadata_smoke.py`.
- The PyPI publication is followed by a non-draft GitHub Release and a
  six-surface publication check.

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
python scripts/release_install_metadata_smoke.py --install-spec . --json
python scripts/release_readiness_gate.py --check --json
python -m pytest tests/ -x -q -m "not needs_network"
python -m pytest tests/test_mcp_protocol_compat.py -q
python -m pytest tests/test_cli_golden_scenarios.py -q
ruff check mempalace_code/ tests/ scripts/
ruff format --check mempalace_code/ tests/ scripts/
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"
python -m pyright -p pyrightconfig.strict.json
```

`release_install_metadata_smoke.py` installs the current checkout into a
disposable venv (non-editable) and proves `importlib.metadata.version`,
`mempalace_code.__version__`, and `mempalace-code version-check --status`
agree on one version before the release commit lands. It also resolves
`mempalace-code agent-plugin path` from a neutral directory, rejects checkout
shadowing, validates the Agent Plugin manifests against the installed vendored
schema IDs, and starts the manifest-declared
`mempalace-code-mcp --profile=minimal` launcher. Pass `--installer pipx` for a
disposable pipx-style tool-environment run if the operator's real install method
is pipx or `uv tool`.

The tag preflight is intentionally local and non-mutating. It checks tag/version
agreement, the documentation contract, the committed-tree public-safety scan,
and optionally a clean worktree.

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

## 3. Tag and publish

Ask for explicit approval immediately before these external mutations:

```bash
git push publish main
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push publish vX.Y.Z
```

The tag-only publish workflow verifies that the tag names the package version
and targets current `main`, reruns the local release preflight, builds wheel and
sdist, validates them with `twine check`, waits for the protected `release`
environment before PyPI trusted publishing, then creates the GitHub Release.
Do not trigger PyPI publishing by a workflow dispatch or a release event.

## 4. Verify the public release

Wait for GitHub Actions and package-index propagation, then run:

```bash
python scripts/release_status_gate.py --version X.Y.Z \
  --repo rergards/mempalace-code --remote publish --branch main
```

The release is shipped only when this gate passes: public tag, branch Tests,
Publish to PyPI workflow, GitHub Release, PyPI wheel/sdist metadata, and the
install metadata smoke must agree. The install smoke installs `package==X.Y.Z`
into a disposable venv and requires `importlib.metadata.version`,
`mempalace_code.__version__`, and `mempalace-code version-check --status` to
all report `X.Y.Z`. Record any remaining blocker instead of claiming a
completed release.

The install smoke checks version-metadata agreement, not individual CLI
subcommand surfaces except for the Agent Plugin locator and declared MCP
launcher. It replaced an earlier smoke that only ran `mempalace-code update
--help`. That coverage is superseded, not carried forward: `main` CI's own
test/import coverage is what backstops other subcommand imports.

If a stale pipx, `uv tool`, or venv install reports a version that disagrees
with the published release, see the reinstall commands in
[`docs/AGENT_INSTALL.md`](AGENT_INSTALL.md#stale-installed-metadata-vs-imported-module).

## Maintainer checklist

- [ ] Explicit approval for tag, push, trusted PyPI publication, and any GitHub
      settings edit.
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
      has both distribution types, and `release_status_gate.py` passes.
