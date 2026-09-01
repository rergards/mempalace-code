---
slug: RELEASE-DIRECT-INSTALLED-LINUX-SYSTEMD
status: completed
authority: non_authoritative
goal: "Make the exact MemPalace wheel self-sufficient on supported Linux pip and bootstrap-venv installs by declaring overrides>=7.7 as one direct runtime dependency."
risk: medium
risk_note: "The edit is metadata-only, but it changes every default installation and must preserve audited resolution, exact-wheel receipts, and the credential-free Linux systemd-user release contour."
files:
  - path: pyproject.toml
    change: "Add overrides>=7.7 exactly once to project.dependencies beside the existing runtime requirements."
  - path: uv.lock
    change: "Refresh the editable root dependency and requires-dist metadata for overrides>=7.7 while retaining the existing overrides 7.7.0 resolution unless the resolver proves a compatible change is required."
  - path: docs/dependency-upgrade-reports/v1.13.5-release.json
    change: "Regenerate the existing public dependency report against the final project and lock hashes, including OSV and fresh default/runtime resolution evidence for overrides."
  - path: tests/test_packaging_namespace.py
    change: "Extend the existing packaging contract with exact-once project, lock, and built-wheel assertions for the direct overrides>=7.7 runtime requirement and locked 7.7.0 version."
  - path: docs/quality/scorecard.md
    change: "Regenerate the deterministic scorecard after the packaging-contract test edit."
  - path: docs/quality/scorecard.json
    change: "Regenerate the deterministic machine-readable scorecard after the packaging-contract test edit."
acceptance:
  - id: AC-1
    when: "The final pyproject, uv lock root package, and an exact rebuilt wheel are inspected on the corrected SHA."
    then: "Each declares overrides>=7.7 exactly once as a direct default dependency, and uv.lock retains overrides 7.7.0 unless the existing resolver records a required compatible change."
  - id: AC-2
    when: "The dependency files differ from base bf5079af and the existing v1.13.5 report is regenerated and checked."
    then: "The gate records clean OSV and fresh default/runtime resolution evidence for the final hashes, verify-report and ci-check pass, and absent, stale, mismatched, or ambiguous report evidence remains a fail-closed error."
  - id: AC-3
    when: "A fresh plain pip venv and fresh bootstrap-venv install the exact rebuilt wheel, followed by the unchanged disposable-user Linux all-installer run."
    then: "Both installs import LanceDB and pass ordinary_runtime_no_chromadb; the aggregate emits four installer PASS receipts, linux_systemd_update_lifecycle=pass, and complete disposable-user and staging cleanup."
  - id: AC-4
    when: "The release dependency and installed-application qualification contours execute."
    then: "They invoke no external AI client or authentication command and read, require, or transmit no user credential, key, token, keychain, or paid-account state."
  - id: AC-5
    when: "The exact corrected SHA enters final release qualification on macOS and fresh Linux Python 3.12."
    then: "Focused packaging and smoke checks, both complete offline suites, Ruff, format, both Pyright gates, scorecard, gate inventory, public-safety, changed-range Gitleaks, dependency audit, and independent correctness, security, and Rule Zero reviews all report success."
out_of_scope:
  - "Pinning or downgrading LanceDB, patching or vendoring LanceDB, or changing MemPalace runtime imports."
  - "Changing installer, smoke, workflow, systemd-user lifecycle, updater, process-group cleanup, or release-job topology."
  - "Adding an installer-specific hidden install, dependency fallback, compatibility module, new report, new gate, or new runtime owner."
  - "External AI-client or authentication execution, credential access, publication, tag, push, deployment, or unrelated remote mutation."
  - "Backlog metadata, archival, staging, commit, and runner-owned finalization."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release dependency and installed-runtime qualification changes a default package contract and crosses audited resolver and hosted Linux lifecycle gates."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The default MemPalace package and exact wheel expose overrides>=7.7 once as a direct runtime requirement, with synchronized lock metadata."
      source: "Backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The existing dependency-upgrade report and gates prove the final dependency state and reject stale or ambiguous evidence."
      source: "Backlog AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The exact wheel succeeds through plain pip, bootstrap-venv, all four installer contours, and the disposable-user Linux systemd lifecycle."
      source: "Backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Release qualification remains credential-free and contains no external AI-client execution."
      source: "Backlog AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "All declared release checks and reviews pass at one exact corrected SHA."
      source: "Backlog AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Default runtime dependency contract"
      kind: internal
      paths: [pyproject.toml, uv.lock]
      expected_behavior: "Project metadata, lock root dependencies, lock requires-dist metadata, and the built wheel agree on one overrides>=7.7 requirement."
    - name: "v1.13.5 dependency audit evidence"
      kind: internal
      paths: [docs/dependency-upgrade-reports/v1.13.5-release.json]
      expected_behavior: "One existing public report binds clean advisory and fresh resolver results to the final pyproject and lock hashes."
    - name: "Packaging dependency regression contract"
      kind: internal
      paths: [tests/test_packaging_namespace.py]
      expected_behavior: "A focused test fails on missing, duplicate, indirect-only, stale-lock, wrong-floor, or absent built-wheel runtime metadata."
    - name: "Deterministic quality evidence"
      kind: internal
      paths: [docs/quality/scorecard.md, docs/quality/scorecard.json]
      expected_behavior: "Both generated scorecard representations match the final tracked tree without changing gate definitions."
  invariants:
    - id: INV-1
      statement: "LanceDB remains at its existing declared range and resolved version; no application import path or fallback is added."
      applies_to: [pyproject.toml, uv.lock]
    - id: INV-2
      statement: "The all-installer order, ordinary_runtime_no_chromadb probe, Linux systemd-user lifecycle, updater behavior, and process-group teardown remain unchanged."
      applies_to: [tests/test_packaging_namespace.py]
    - id: INV-3
      statement: "Only the existing v1.13.5 dependency report is updated; other dependency reports and audit-gate code remain unchanged."
      applies_to: [docs/dependency-upgrade-reports/v1.13.5-release.json]
    - id: INV-4
      statement: "Release gates remain local and credential-free, with no external AI client, authentication command, user secret, keychain, or paid-account dependency."
      applies_to: [pyproject.toml, uv.lock, docs/dependency-upgrade-reports/v1.13.5-release.json]
    - id: INV-5
      statement: "Scorecard commands, schema, and quality thresholds remain unchanged; only deterministic outputs are regenerated."
      applies_to: [docs/quality/scorecard.md, docs/quality/scorecard.json]
  risks:
    - id: RISK-1
      risk: "Adding the requirement only to pyproject or only to the resolved package list could leave built-wheel or uv root metadata inconsistent."
      mitigation: "One packaging-contract test compares project dependencies, the editable root dependency list, root requires-dist metadata, the overrides package version, and freshly built wheel METADATA."
    - id: RISK-2
      risk: "A hand-edited or stale dependency report could appear clean without matching the final dependency files or fresh resolver results."
      mitigation: "Regenerate through the existing audit command, then require verify-report and ci-check against bf5079af; preserve fail-closed report cardinality and hash checks."
    - id: RISK-3
      risk: "A local editable or manager-supplied overrides package could mask the plain pip wheel failure."
      mitigation: "Use fresh neutral plain-pip and bootstrap-venv installs of the exact wheel, then require the unchanged disposable-user all-installer receipt."
    - id: RISK-4
      risk: "Dependency work could accidentally broaden the release gate into credential or provider access."
      mitigation: "Leave gate code and workflow topology unchanged and retain the focused credential-free workflow admission contract plus public-safety and Gitleaks gates."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_packaging_namespace.py -q"
      proves: "Project, lock root metadata, locked version, and freshly built wheel metadata contain one direct overrides>=7.7 requirement and fail on packaging drift."
      acceptance_ids: [AC-1]
    - id: VER-2
      owner: provider
      command: "python scripts/dependency_upgrade_gate.py verify-report docs/dependency-upgrade-reports/v1.13.5-release.json"
      proves: "The single updated report is successful, structurally complete, hash-bound to final files, and contains successful resolver evidence."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-3
      owner: provider
      command: "python scripts/dependency_upgrade_gate.py ci-check --base-ref bf5079af"
      proves: "Dependency changes from the qualified base are covered by exactly one matching successful report."
      acceptance_ids: [AC-2]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_dependency_upgrade_gate.py -q"
      proves: "Missing, stale, mismatched, unresolvable-base, and multiple matching report states continue to fail closed while valid evidence passes."
      acceptance_ids: [AC-2]
    - id: VER-5
      owner: provider
      command: "python -m pytest tests/test_release_workflow_admission.py -q"
      proves: "The unchanged installed-application job still stages one local wheel, preserves four installer and Linux lifecycle ownership, disables credential persistence, and contains no AI-provider command."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-6
      owner: configured_runner
      command: "MEMPALACE_RELEASE_SYSTEMD_USER=1 python scripts/release_install_metadata_smoke.py --all-installers --install-spec dist/mempalace_code-*.whl --json"
      proves: "The disposable Linux user installs the exact wheel through venv, bootstrap-venv, pipx, and uv-tool; every runtime probe passes, systemd update lifecycle passes, and cleanup receipts are complete."
      acceptance_ids: [AC-3, AC-4, AC-5]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist"
      proves: "The rebuilt wheel and sdist retain the required public artifact shape after dependency metadata changes."
      acceptance_ids: [AC-1, AC-5]
    - id: VER-8
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The packaging regression satisfies the configured lint gate."
      acceptance_ids: [AC-5]
    - id: VER-9
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The packaging regression satisfies the configured format gate."
      acceptance_ids: [AC-5]
    - id: VER-10
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The final tree satisfies the configured basic Pyright gate."
      acceptance_ids: [AC-5]
    - id: VER-11
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The final tree satisfies the configured strict Pyright slice."
      acceptance_ids: [AC-5]
    - id: VER-12
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The regenerated Markdown and JSON scorecards are deterministic, public-safe, and fresh for the final tree."
      acceptance_ids: [AC-5]
    - id: VER-13
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The canonical release gate inventory remains synchronized and unchanged in topology."
      acceptance_ids: [AC-3, AC-4, AC-5]
    - id: VER-14
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The final tracked and staged release artifacts contain no private path or secret-like material."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-15
      owner: configured_runner
      command: "python scripts/gitleaks_scan.py changed-range --base-ref BASE --head-ref HEAD"
      proves: "The exact candidate change range contains no maintained credential signature or entropy finding."
      acceptance_ids: [AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The configured complete offline suite passes on both the macOS and fresh Linux Python 3.12 qualification contours without changing product or release lifecycle behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Current HEAD `a7c3c860` already owns the needed behavior. `pyproject.toml` owns direct runtime requirements; the editable `mempalace-code` package in `uv.lock` owns synchronized root dependencies and `requires-dist`; `scripts/dependency_upgrade_gate.py` owns advisory, fresh-resolver, report-hash, and report-cardinality checks; `scripts/release_install_metadata_smoke.py` owns all installer and Linux systemd-user receipts. Add no runtime module, fallback, gate, report, or workflow.
- The current residual is metadata-only: LanceDB 0.37.1 imports `overrides` on supported Python 3.12+, while its own wheel marker can omit that transitive package. The lock already resolves `overrides` 7.7.0 through the Python-below-3.12 branch, so `overrides>=7.7` reuses a present, known-good package and moves it into the MemPalace direct default contract.
- Add the requirement once in `project.dependencies`, then refresh `uv.lock` with the repository's existing uv workflow. Require one root `dependencies` entry and one root `package.metadata.requires-dist` entry with specifier `>=7.7`; retain the existing standalone `overrides` package at 7.7.0 unless the resolver itself produces a compatible required change. Do not edit lock text by hand.
- Extend `tests/test_packaging_namespace.py`, the existing packaging-contract owner. Build a wheel into a disposable pytest temporary directory with the existing local build toolchain, inspect its `.dist-info/METADATA`, and compare it with `pyproject.toml` plus the editable root package in `uv.lock`. The assertion must reject a missing requirement, duplicate direct requirement, marker-constrained requirement, wrong floor, indirect-only lock entry, stale root metadata, or a wheel lacking `Requires-Dist: overrides>=7.7`.
- Regenerate `docs/dependency-upgrade-reports/v1.13.5-release.json` through `scripts/dependency_upgrade_gate.py audit`, using a disposable manifest outside the tracked tree. Preserve the report's current audited target set, add `overrides: 7.7.0` as a target, retain the default fresh resolver audit, and write with slug `v1.13.5-release`. Remove the disposable manifest immediately; no second report or manifest becomes a repository artifact.
- `verify-report` must bind the regenerated report to the final pyproject and lock hashes. `ci-check --base-ref bf5079af` must find exactly this one matching successful report. Any absent, stale, duplicate, mismatched, advisory-affected, or resolver-failed evidence keeps the task open.
- Run the aggregate installed-application evidence only from its existing fresh Linux disposable-user contour against the exact rebuilt wheel. The required observable JSON/progress receipts are four installer passes, successful `ordinary_runtime_no_chromadb` for plain venv and bootstrap-venv, `linux_systemd_update_lifecycle=pass`, and complete user plus staging cleanup. A local non-systemd `UNRUN` is partial evidence and cannot close AC-3.
- The release credential boundary remains an invariant of the unchanged gate and workflow. The focused workflow-admission regression, public-safety scan, changed-range Gitleaks, and inspection of the installed-application receipt establish the boundary without executing any external AI client, authentication command, or credential lookup.
- Regenerate `docs/quality/scorecard.md` and `docs/quality/scorecard.json` only with `python scripts/quality_scorecard.py --write` after the test edit. Do not hand-edit metrics, commands, schema, or thresholds.
- Cheapest decisive falsifier: VER-1 fails if any source, lock, or exact-wheel dependency surface lacks the one unmarked `overrides>=7.7` direct requirement. The runtime falsifier is VER-6: any plain pip or bootstrap-venv LanceDB import failure, missing installer receipt, lifecycle status other than pass, or incomplete cleanup rejects the candidate.
- Command context basis: `pyproject.toml` declares Python 3.11+ and the dev build/test tools; `uv.lock` is the current resolver source; `.claude/skills/verify/INSTRUCTIONS.md`, `scripts/gate_inventory.py`, `.github/workflows/ci.yml`, and `docs/RELEASING.md` define the repository-root commands and the dedicated Ubuntu disposable-user installed-application contour. PLAN inspected these manifests and source paths only; no test, build, audit, gate, wrapper, or review command ran.
- Independent correctness, security, and Rule Zero verdicts are runner-owned review outputs for AC-5. They do not create repository files and are not represented as shell pseudo-commands.
- `docs/quality/incident-class-registry.yaml` is absent. This direct package-metadata workaround changes no provider boundary, routing/profile, budget minimum, recovery-state owner, or verify-fix authority, so no `incident_proof` block applies.
- Implementation stops after the six declared paths and exact qualification. Backlog bookkeeping, staging, commit, source verification, publication, tag, push, deployment, and finalization remain runner-owned.
