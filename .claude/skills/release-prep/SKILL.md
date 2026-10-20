---
name: release-prep
description: Clean verified release artifacts and prepare MemPalace metadata, installed acceptance, and local qualification before separately authorized publication.
disable-model-invocation: true
---

# Release preparation

## Entry and authority

- Read `AGENTS.md`, `docs/RELEASING.md`, `CONTRIBUTING.md`, and
  `docs/quality/acceptance/README.md`. Those files own gates and report format.
- Derive permitted edits, cleanup, commits, and exclusions from the active request.
  Reuse existing authorization, including disposable-platform tests and local
  source delivery. Check each external effect separately. Inspection alone permits
  no mutations; do not ask again for an already-authorized effect.
- Verify cwd, Git root/common directory, status, worktrees, processes and open files.
  Use `autopilot doctor --json` when available; otherwise use the repository's
  documented manual ownership check. Preserve initial edits and stop overlapping writes.
- Never invoke Codex, Claude, Gemini, another model/provider, or an authenticated
  client as a preparation or qualification gate. Never inspect or require
  credentials, tokens, keychains, auth files or paid-account state.
- Push, tag creation, public ref promotion, settings changes and publication each
  require explicit operator authorization. Preparation grants none of them.
  Never use `--force` or rewrite a public ref.

## Inspect and clean

- Read current backlog through the project-bound `backlog-utility` interface.
  Do not create tasks, worksets or a second release plan merely to run this skill.
- Resolve public history with `python scripts/release_public_read.py --version-tags`.
  Local tags and local development `main` are insufficient release identity.
  Separate newest public tag, last published release and pending local version.
- Compare public history with the current behavior owners. Choose the smallest
  justified version change; keep an already prepared unpublished version when suitable.
- Inspect untracked/ignored files, stashes and commits unique to affected worktrees
  before cleanup. Remove only identified disposable artifacts with verified ownership
  and no open writer; apply the repository's target-identity gate before deletion.
  Preserve palaces, databases, backups, handoffs, evidence, environments and unique work.
  Missing ownership blocks only cleanup of that item. Do not blanket-clean or prune.

## Reconcile open pull requests and issues

- At each preparation start and before candidate readiness, inspect every open PR
  and issue in the verified public repository by credential-free, paginated, public
  read-only observation separate from product qualification. A failed or incomplete
  read is UNKNOWN and blocks readiness; an empty successful read is explicit evidence.
- Retain the observation time, IDs, exact PR head/diff, issue claims and a disposition
  for every item in the existing release evidence. Verify claims against current
  behavior and accepted requirements before changing code.
- Resolve confirmed in-scope defects and required dependency updates before release.
  Use the authorized engineering route, then rerun affected product checks. Keep
  AI engineering outside preparation/qualification gates. Do not expand scope,
  weaken tests/audits or accept an advisory through an automatic allowlist entry.
- Port accepted PR changes to the development trunk through its existing owner.
  Never merge a PR into public main. If exact changes are already shipped, verify
  the public release tag and close the PR with that version under existing authority.
  Otherwise retain closure until the release containing those changes is published.
- Classify each issue as fixed in the candidate, already shipped, refuted with
  evidence, or unresolved. Keep unreleased fixes open until publication or the
  existing issue owner confirms resolution. Unresolved confirmed release blockers
  stop readiness. Record other dispositions with their evidence and owner.
- Missing authority or significant out-of-scope correction blocks the dependent
  fix and release claim; report the smallest correction and one recovery action.
  Re-read open items after changes and reconcile additions or changed PR heads.

## Prepare the existing owners

- Use `pyproject.toml`, `CHANGELOG.md`, public docs and existing generators.
  Keep `## Unreleased`; consolidate user-visible changes under the pending version.
  Exclude private operational history and local machine details from public notes.
- State exact edited paths and acceptance commands before writing; verify all four
  Git views afterward. Do not add another release controller, gate or procedure.
- Audit current public entrypoints for each changed behavior: README, feature guide,
  agent installation, LLM rules and examples; check packaged instructions only for
  their declared capabilities. Preserve dated historical reports. Resolve claims
  against source and link the existing feature owner instead of copying a procedure.
- Require RELEASING section 2's privacy audit before public delivery. Use Git's
  inventory to include hidden LLM instructions/prompts/settings and new staged
  backlog history. Review actual private identifiers/context, not just token patterns;
  classify examples and public authorship with evidence. Inspect both archive contents
  and exact outgoing ancestry. Preserve local private evidence, retain only redacted
  findings and block delivery on confirmed disclosure or consequential unknowns.
- Inspect newly staged canonical records for private data. Preserve sealed local
  records and use existing ignore rules and supported backlog operations; never
  scrub immutable history or exempt it from the scanner. Before switching or
  integrating refs that still track excluded files, retain validated sealed bytes
  through the existing backup/export route and verify hashes/store validity afterward.
- Follow section 1a of `docs/RELEASING.md` for installed-candidate acceptance and
  write its report at `docs/quality/acceptance/vX.Y.Z.md`. Use disposable installs,
  palaces and profiles; preserve real data and user configuration.
- Require direct coverage of installed CLI commands, delegated subcommands, every
  enabled MCP tool in every profile, both protocol handshakes, and supported extras.
  Retain wheel-bound invocations, expected/actual results and relevant failure/retry
  postconditions. Classify help, parser errors and listings as discovery/guidance;
  classify documented retired/unauthorized-operation refusals explicitly. Missing
  required execution is blocking UNRUN, even when source tests or CI pass.
- Reuse unchanged, identity-bound evidence. Rebuild and rerun affected acceptance
  after package changes; do not count source tests as installed CLI/MCP execution.
  Never inspect or import real user conversations to satisfy synthetic coverage.
- Triage findings in the existing evidence. Fix a small blocking defect only when
  required and within current authority; otherwise report its smallest correction.
  No automatic backlog decomposition or separately mandated task per fix.

## Qualification

Use the repository virtualenv. Run the exact existing gate set in RELEASING
section 1 and CONTRIBUTING; retain raw logs outside the published tree.
For dependency-contract changes, follow `docs/DEPENDENCY_UPGRADE_GATE.md` and
commit its generated report with the dependency files. Before pushing, run its
`ci-check` against the verified candidate parent and require a matching successful
report. Retain the scheduled `current-audit` evidence as its separate check.

Core preparation checks:

```bash
python scripts/docs_drift_guard.py
python scripts/public_safety_scan.py --tracked --staged
python scripts/public_safety_scan.py --committed
python scripts/gitleaks_scan.py full-history --artifact-dir .codex-local/release-privacy
python scripts/quality_scorecard.py --check
python scripts/gen_code_intelligence_packet.py --check
python scripts/release_preflight.py --json
```

Build both distribution formats, then run the existing artifact checker, installer matrix and installed
application owner; get all flags and platform prerequisites from RELEASING:

```bash
python -m build --outdir dist
MEMPALACE_RELEASE_WHEEL="$(pwd)/dist/mempalace_code-X.Y.Z-py3-none-any.whl"
python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist --json
python scripts/release_install_metadata_smoke.py --all-installers --install-spec "$MEMPALACE_RELEASE_WHEEL" --json
python scripts/release_readiness_gate.py --installed-golden-wheel "$MEMPALACE_RELEASE_WHEEL" --json
```

Replace `X.Y.Z` with the pending version and retain the exact wheel digest.
Use that wheel in every installer and platform contour; a source install is not
evidence for the built artifact. Set `MEMPALACE_RELEASE_SYSTEMD_USER=1` only in the
congruent disposable Linux fixture described in RELEASING.
Before candidate push, reconcile separate platform runs and focused retries under
RELEASING section 3. Preserve raw aggregate failures and required native Linux coverage.
The required Linux systemd-user receipt cannot be replaced by macOS results.
Missing model provenance or platform prerequisites remain blocking `UNRUN`;
provision only within current authority, then retry the existing owner command.
No confirmed high/critical issue may remain; record other findings and explicit
deferrals per the acceptance-report contract. Never invent PASS or weaken a gate.

An authorized local commit follows the repository's independent source-review
policy; that review is separate from credential-free release qualification and
is not application-acceptance evidence. Do not launch provider clients from this
workflow. Write the acceptance report after installed qualification, inspect every
public path including newly staged records, rerun public-safety on the complete
staged tree, and commit within existing authority. Once the acceptance report is
committed for the exact package ids:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --json
```

For the opt-in read-only pre-tag check at its documented stage:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

Clean-tree or committed-report checks remain pending until their prerequisites exist.
After documentation-only edits, rebuild archives and compare runtime/plugin members,
dependency/entrypoint metadata and bound package ids with the tested wheel. A README-only
metadata delta needs fresh artifact and installed metadata checks; record both wheel
digests and the exact delta before reusing application evidence. Other package changes
need affected installed checks and a refreshed report. Preserve unaffected evidence.
Candidate creation follows RELEASING and requires installed acceptance first.

## Result and recovery

Report version/public baseline, reviewed source SHA, documentation surfaces checked,
exact changes and cleanup,
wheel/source identities, checks run versus reused, unrun/failed gates and one
existing recovery command. Mark local readiness separately from public admission.
For each platform name direct installed CLI/MCP coverage, installer/systemd receipts,
fixture cleanup and live-state preservation; distinguish them from source tests.
Report privacy outcomes separately for the current public tree, LLM instructions,
archives, outgoing ancestry and retained local state. Detector PASS is not proof that
private operational data is absent. Name unresolved findings before release handoff.
Hand off to `/release` only after local qualification and committed acceptance pass.
Push, tag, release and live-palace actions remain pending unless explicitly authorized.
