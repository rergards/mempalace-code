---
slug: REL-DEPENDENCY-REPORT-CURRENT-HASH
goal: "Regenerate the single canonical v1.13.5 dependency report for the final pyproject.toml and uv.lock hashes with complete current install-surface evidence."
risk: medium
risk_note: "The repository change is one generated JSON artifact, but stale or incomplete advisory and resolver evidence could incorrectly admit a release candidate."
files:
  - path: docs/dependency-upgrade-reports/v1.13.5-release.json
    change: "Replace the stale canonical report with the successful public-safe output from the existing dependency upgrade gate for the final dependency files and all current install surfaces."
acceptance:
  - id: AC-1
    when: "the canonical v1.13.5 report is verified against the current workspace"
    then: "it records pyproject.toml SHA-256 9c9af191fb23aa109d957d92b0f146c257ef69b7146ad385be04c00c988daa30 and uv.lock SHA-256 896e921f44e7e22aafd6e4c0f40f74eabc647456569b0c058405fbadbec34a61 with success status"
  - id: AC-2
    when: "the generated report dependency and resolver matrices are inspected"
    then: "they cover runtime, dev, custom-models, spellcheck, treesitter, and watch through successful default, dev, and per-extra audits, with no Chroma dependency or audit surface"
  - id: AC-3
    when: "verify-report and ci-check --base-ref publish/main inspect the refreshed canonical report"
    then: "both commands exit zero and ci-check finds exactly one successful report matching the current dependency-file hashes"
  - id: AC-4
    when: "the configured public-safety, documentation-drift, Ruff, and dependency-focused checks run after report regeneration"
    then: "every check exits zero without requiring changes outside the canonical report"
  - id: AC-5
    when: "the existing stale-report failure-path test changes a dependency file after report creation"
    then: "verify-report exits nonzero and reports the hash mismatch"
out_of_scope:
  - "Changing dependency bounds, pyproject.toml, uv.lock, or any package version in response to a failed advisory or resolver audit."
  - "Changing scripts/dependency_upgrade_gate.py, its report format, its gate behavior, tests, workflows, or dependency-gate documentation."
  - "Creating a second report, committing a target manifest, or restoring retired Chroma dependencies or extras."
  - "Editing backlog metadata, archive files, or runner-owned completion state."
contract_policy:
  flow: full_spdd
  reason: "This standard release-quality task refreshes security and resolver evidence consumed by an existing admission gate."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The canonical v1.13.5 report must have success status and hashes equal to the final dependency files."
      source: "current backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Audit evidence must enumerate every current direct dependency and successfully resolve the default, dev, and every current optional-extra install surface without Chroma."
      source: "current backlog AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The unchanged report verifier and CI gate must accept the refreshed report against publish/main."
      source: "current backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The refreshed public artifact must preserve repository public-safety, documentation-drift, lint, and dependency-gate test checks."
      source: "current backlog AC-4"
      acceptance_ids: [AC-4, AC-5]
  surfaces:
    - name: "canonical v1.13.5 dependency report"
      kind: store
      paths: ["docs/dependency-upgrade-reports/v1.13.5-release.json"]
      expected_behavior: "Remain the sole report owner for v1.13.5 and provide current-hash, successful, public-safe advisory and resolver evidence to verify-report and ci-check."
  invariants:
    - id: INV-1
      statement: "pyproject.toml and uv.lock remain byte-identical while the report is regenerated."
      applies_to: ["pyproject.toml", "uv.lock"]
    - id: INV-2
      statement: "The report schema and dependency gate behavior remain unchanged; the task refreshes data through the existing audit command."
      applies_to: ["scripts/dependency_upgrade_gate.py", "docs/dependency-upgrade-reports/v1.13.5-release.json"]
    - id: INV-3
      statement: "Exactly one report matches the current pyproject.toml and uv.lock hashes."
      applies_to: ["docs/dependency-upgrade-reports/v1.13.5-release.json"]
    - id: INV-4
      statement: "Retired Chroma packages and extras remain absent from current dependency and resolver evidence."
      applies_to: ["pyproject.toml", "docs/dependency-upgrade-reports/v1.13.5-release.json"]
    - id: INV-5
      statement: "No private paths, hostnames, credentials, tokens, caches, or raw resolver and advisory output enter the committed report."
      applies_to: ["docs/dependency-upgrade-reports/v1.13.5-release.json"]
  risks:
    - id: RISK-1
      risk: "A transient manifest could omit a current group or extra and produce an incomplete resolver matrix."
      mitigation: "Name runtime and dev as changed groups, name custom-models, spellcheck, treesitter, and watch as changed extras, and inspect the exact successful resolver matrix."
    - id: RISK-2
      risk: "Live OSV, resolution, or pip-audit results could block the current selected versions."
      mitigation: "Preserve the gate's fail-closed result and stop with the exact advisory or install-surface blocker instead of changing dependencies or committing a blocked report."
    - id: RISK-3
      risk: "The report could be regenerated before the final files or could coexist with another matching report."
      mitigation: "Keep dependency files unchanged, verify their exact hashes after generation, and run ci-check against publish/main to enforce singular matching evidence."
    - id: RISK-4
      risk: "Generated diagnostics could expose machine-local or sensitive data."
      mitigation: "Retain only the gate's structured public report and run the configured tracked/staged public-safety scan."
  verification:
    - id: VER-1
      command: "python scripts/dependency_upgrade_gate.py verify-report docs/dependency-upgrade-reports/v1.13.5-release.json --root ."
      proves: "The report has success status, valid schema, successful resolver rows, and hashes equal to the current dependency files."
      acceptance_ids: [AC-1, AC-3]
      owner: provider
    - id: VER-2
      command: "jq -e '([.dependencies[].group] | unique) == [\"dev\",\"extra:custom-models\",\"extra:spellcheck\",\"extra:treesitter\",\"extra:watch\",\"runtime\"] and ([.resolver_audits[].extras] == [[],[\"dev\"],[\"custom-models\"],[\"spellcheck\"],[\"treesitter\"],[\"watch\"]]) and all(.resolver_audits[]; .status == \"success\") and all(.dependencies[]; (.normalized_name | contains(\"chroma\")) | not)' docs/dependency-upgrade-reports/v1.13.5-release.json"
      proves: "The artifact covers every current dependency group and install surface and excludes retired Chroma ownership."
      acceptance_ids: [AC-2]
      owner: provider
    - id: VER-3
      command: "python scripts/dependency_upgrade_gate.py ci-check --base-ref publish/main"
      proves: "The CI gate resolves the public base and finds exactly one successful report matching the current dependency contract."
      acceptance_ids: [AC-3]
      owner: provider
    - id: VER-4
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The configured scanner finds no private or sensitive content in tracked or staged public artifacts."
      acceptance_ids: [AC-4]
      owner: configured_runner
    - id: VER-5
      command: "python scripts/docs_drift_guard.py"
      proves: "The configured documentation authority and drift rules remain satisfied by the refreshed report."
      acceptance_ids: [AC-4]
      owner: configured_runner
    - id: VER-6
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured Ruff gate remains green for the repository's linted Python surfaces."
      acceptance_ids: [AC-4]
      owner: configured_runner
    - id: VER-7
      command: "python -m pytest tests/test_dependency_upgrade_gate.py -q"
      proves: "The dependency gate's focused audit, report-verification, and CI admission behavior remains green."
      acceptance_ids: [AC-4]
      owner: provider
    - id: VER-8
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_verify_report_rejects_stale_hashes -q"
      proves: "The unchanged verifier still rejects a report after its recorded dependency-file hashes become stale."
      acceptance_ids: [AC-5]
      owner: provider
  regression_plan:
    applies: false
    no_behavior_change_exception: "The only planned repository change is regenerated JSON evidence consumed by unchanged code; focused gate tests and the explicit stale-hash guard verify the existing behavior."
    checks: []
---

## Design Notes

- Reuse `scripts/dependency_upgrade_gate.py audit` with slug `v1.13.5-release`; overwrite the existing canonical report only after the command completes successfully. Do not hand-edit the report or create another format or matching file.
- Create a disposable, untracked target manifest for execution. Set `changed_groups` to `runtime` and `dev`; set `changed_extras` to `custom-models`, `spellcheck`, `treesitter`, and `watch`. Populate every required target with the exact current version selected in `uv.lock`.
- The existing resolver planner turns that manifest into the ordered audit matrix `default`, `dev`, `custom-models`, `spellcheck`, `treesitter`, `watch`. Each row must be present once and have `status: success`; dependency rows must cover all direct runtime, dev, and current-extra declarations.
- Preserve the observed input hashes exactly: `pyproject.toml` is `9c9af191fb23aa109d957d92b0f146c257ef69b7146ad385be04c00c988daa30`; `uv.lock` is `896e921f44e7e22aafd6e4c0f40f74eabc647456569b0c058405fbadbec34a61`.
- Accept only a successful live advisory and resolver run. An OSV finding prevents report creation; a resolver failure produces blocked evidence. Either outcome stops this task and reports the exact package, advisory, or install surface without authorizing dependency edits.
- Keep only the structured public-safe report fields already owned by the gate. Delete the disposable manifest after generation and do not retain raw OSV responses, pip output, temp paths, caches, hostnames, credentials, or environment data.
- Command-context basis: the repository documents the Python gate CLI and root-relative invocation in `docs/DEPENDENCY_UPGRADE_GATE.md`; `publish/main` resolves in this worktree; the exact public-safety, docs-drift, and Ruff commands are configured in `.github/workflows/ci.yml`; the dependency-focused pytest module already owns the stale-hash and fail-closed behavior.
