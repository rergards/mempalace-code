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
  Reuse existing authorization. Inspection alone permits no mutations.
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

## Prepare the existing owners

- Use `pyproject.toml`, `CHANGELOG.md`, public docs and existing generators.
  Keep `## Unreleased`; consolidate user-visible changes under the pending version.
  Exclude private operational history and local machine details from public notes.
- State exact edited paths and acceptance commands before writing; verify all four
  Git views afterward. Do not add another release controller, gate or procedure.
- Follow section 1a of `docs/RELEASING.md` for installed-candidate acceptance and
  write its report at `docs/quality/acceptance/vX.Y.Z.md`. Use disposable installs,
  palaces and profiles; preserve real data and user configuration.
- Reuse unchanged, identity-bound evidence. Rebuild and rerun affected acceptance
  after package changes; do not count source tests as installed CLI/MCP execution.
  Never inspect or import real user conversations to satisfy synthetic coverage.
- Triage findings in the existing evidence. Fix a small blocking defect only when
  required and within current authority; otherwise report its smallest correction.
  No automatic backlog decomposition or separately mandated task per fix.

## Qualification

Use the repository virtualenv. Run the exact existing gate set in RELEASING
section 1 and CONTRIBUTING; retain raw logs outside the published tree.
Core preparation checks:

```bash
python scripts/docs_drift_guard.py
python scripts/public_safety_scan.py --tracked --staged
python scripts/quality_scorecard.py --check
python scripts/gen_code_intelligence_packet.py --check
python scripts/release_preflight.py --json
```

Build the reviewed wheel, then run the existing installer matrix and installed
application owner; get all flags and platform prerequisites from RELEASING:

```bash
python -m build --wheel --outdir dist
python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json
python scripts/release_readiness_gate.py --installed-golden-wheel "$MEMPALACE_RELEASE_WHEEL" --json
```

Bind `MEMPALACE_RELEASE_WHEEL` to the exact built wheel before invocation.
The required Linux systemd-user receipt cannot be replaced by macOS results.
Missing model provenance or platform prerequisites remain blocking `UNRUN`;
provision only within current authority, then retry the existing owner command.
No confirmed high/critical issue may remain; record other findings and explicit
deferrals per the acceptance-report contract. Never invent PASS or weaken a gate.

An authorized local commit follows the repository's independent source-review
policy; that review is separate from credential-free release qualification and
is not application-acceptance evidence. Do not launch provider clients from this
workflow. Once the acceptance report is committed for the exact package ids:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --json
```

For the opt-in read-only pre-tag check at its documented stage:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

Clean-tree or committed-report checks remain pending until their prerequisites exist.
Candidate creation follows RELEASING and requires installed acceptance first.

## Result and recovery

Report version/public baseline, reviewed source SHA, exact changes and cleanup,
wheel/source identities, checks run versus reused, unrun/failed gates and one
existing recovery command. Mark local readiness separately from public admission.
Hand off to `/release` only after local qualification and committed acceptance pass.
Push, tag, release and live-palace actions remain pending unless explicitly authorized.
