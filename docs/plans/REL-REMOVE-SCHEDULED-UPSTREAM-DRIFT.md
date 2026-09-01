---
slug: REL-REMOVE-SCHEDULED-UPSTREAM-DRIFT
status: completed
authority: non_authoritative
goal: "Remove the standalone Upstream drift workflow while retaining fail-closed live drift checks at pre-tag and tag-publish release boundaries."
risk: low
risk_note: "The change deletes one redundant notification source; focused admission coverage and preserved release-time owners bound the risk of accidentally removing drift enforcement."
files:
  - path: .github/workflows/upstream-drift.yml
    change: "Delete the standalone scheduled and manually dispatchable Upstream drift workflow."
  - path: tests/test_release_workflow_admission.py
    change: "Add one repository-shape assertion that fails if the removed workflow path is reintroduced."
  - path: docs/UPSTREAM_COMPARISON.md
    change: "State the release-time-only live drift policy, name both surviving owners, and retain one concrete manual recovery command."
acceptance:
  - id: AC-1
    when: "The candidate workflow tree and existing workflow-admission suite are inspected and exercised, including a candidate where .github/workflows/upstream-drift.yml is reintroduced."
    then: ".github/workflows/upstream-drift.yml is absent, and the admission assertion fails on its reintroduction so neither its schedule nor manual trigger can return silently."
  - id: AC-2
    when: "The canonical pre-tag live-upstream path is exercised with matching upstream state, drifted state, fetch failure, and an unusable response."
    then: "release_preflight.py delegates to the existing live guard, accepts only trusted matching state, and fails closed for drift or an untrusted response."
  - id: AC-3
    when: "The tag-only publish workflow shape is inspected by the workflow-admission suite."
    then: "publish.yml still invokes the live upstream guard after exact-SHA admission and before building or publishing artifacts."
  - id: AC-4
    when: "The documentation drift guard inspects the current upstream automation and recovery policy."
    then: "The documentation says live drift detection runs only at release time, names the pre-tag and tag-publish owners, and gives python scripts/upstream_comparison_guard.py --check-live --json as the manual recovery command."
  - id: AC-5
    when: "The configured workflow, guard, preflight, documentation, public-safety, and admission checks run in the repository-root development environment."
    then: "Actionlint, Zizmor, upstream guard tests, release preflight tests, docs drift, public safety, and workflow admission tests all exit successfully without an AI client, auth or credential access, push, tag, release, or PyPI operation."
out_of_scope:
  - "Changing scripts/upstream_comparison_guard.py, its reviewed upstream pin, manifest, static CI invocation, or fail-closed semantics."
  - "Changing scripts/release_preflight.py or the canonical pre-tag --check-live-upstream command."
  - "Changing .github/workflows/publish.yml, its tag-only trigger, release admission, live guard, build order, or publication jobs."
  - "Adding a replacement schedule, manual workflow, notification setting, helper, guard, policy document, external client, provider call, auth probe, or credential path."
  - "Editing CHANGELOG.md, docs/BACKLOG.yaml, backlog archives, or runner-owned completion bookkeeping."
  - "Committing, pushing, tagging, publishing, changing GitHub settings, creating a GitHub Release, or uploading to PyPI."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release workflow change removes a public automation surface while preserving two fail-closed release-admission boundaries and their credential-free validation contract."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The standalone Upstream drift workflow must be absent and its existing path must be protected by the workflow-admission suite."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The canonical pre-tag command must retain the live upstream guard and fail closed on drift, fetch failure, or unusable responses."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The tag-only publish workflow must retain its direct live guard before artifact construction or publication."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Current upstream documentation must describe one release-time-only live policy, both owners, and one manual recovery command."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The named credential-free static, security, guard, preflight, documentation, public-safety, and admission checks must remain green."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "standalone upstream drift workflow"
      kind: internal
      paths: [".github/workflows/upstream-drift.yml"]
      expected_behavior: "The public workflow surface is absent, so GitHub cannot schedule or manually dispatch this redundant live guard."
    - name: "workflow admission shape"
      kind: internal
      paths: ["tests/test_release_workflow_admission.py"]
      expected_behavior: "The existing admission suite rejects reintroduction of the exact removed workflow path while continuing to protect publish ordering."
    - name: "upstream automation and recovery policy"
      kind: internal
      paths: ["docs/UPSTREAM_COMPARISON.md"]
      expected_behavior: "The document presents live drift detection as release-time-only through pre-tag preflight and tag-publish defense in depth, with one manual recovery command."
  invariants:
    - id: INV-1
      statement: "scripts/upstream_comparison_guard.py, docs/quality/upstream-comparison.json, and the reviewed upstream pin remain byte-unchanged."
      applies_to: [".github/workflows/upstream-drift.yml", "tests/test_release_workflow_admission.py", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-2
      statement: "scripts/release_preflight.py continues to invoke scripts/upstream_comparison_guard.py --check-live only when --check-live-upstream is selected and continues to fail closed on nonzero guard results."
      applies_to: ["tests/test_release_workflow_admission.py", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-3
      statement: ".github/workflows/publish.yml remains tag-only and retains its direct live guard before Build distributions and every publication step."
      applies_to: ["tests/test_release_workflow_admission.py", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-4
      statement: ".github/workflows/ci.yml retains the deterministic static upstream comparison guard and all existing release-required dependencies."
      applies_to: [".github/workflows/upstream-drift.yml", "tests/test_release_workflow_admission.py", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-5
      statement: "Validation executes no external AI client, provider authentication, credential inspection, remote mutation, tag, release, or package publication."
      applies_to: ["tests/test_release_workflow_admission.py", "docs/UPSTREAM_COMPARISON.md"]
  risks:
    - id: RISK-1
      risk: "Deleting the scheduled workflow could also remove the only live drift check if release owners have drifted."
      mitigation: "Keep release_preflight.py and publish.yml unchanged and verify both existing live paths with their focused suites."
    - id: RISK-2
      risk: "A future contributor could recreate the same scheduled or manually dispatchable workflow after the deletion."
      mitigation: "Add one exact-path absence assertion to the existing workflow-admission suite."
    - id: RISK-3
      risk: "Documentation could continue directing maintainers to scheduled-workflow failures or imply live checks run continuously."
      mitigation: "Update the existing Automation Policy and Drift Recovery sections together, naming both release owners and the established recovery command."
    - id: RISK-4
      risk: "Workflow deletion could leave invalid YAML references or weaken workflow security posture."
      mitigation: "Run the existing Actionlint and offline medium-severity Zizmor commands over the resulting workflow/action tree."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python -m pytest tests/test_release_workflow_admission.py -q"
      proves: "The exact scheduled-workflow path is absent, its reintroduction is rejected, publish remains tag-only, and the direct live guard precedes artifact construction."
      acceptance_ids: [AC-1, AC-3]
    - id: VER-2
      owner: configured_runner
      command: "python -m pytest tests/test_release_preflight.py -q"
      proves: "The pre-tag opt-in still delegates to the live upstream guard and propagates its drift or untrusted-response failure."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-3
      owner: configured_runner
      command: "python -m pytest tests/test_upstream_comparison_guard.py -q"
      proves: "The unchanged guard accepts matching state and fails closed for live drift, fetch failures, unusable responses, and invalid recovery metadata."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The documented pre-tag command and release-time policy remain synchronized with the repository release surfaces."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-5
      owner: configured_runner
      command: "actionlint .github/workflows/*.yml"
      proves: "Every remaining GitHub Actions workflow is syntactically valid after the workflow file is removed."
      acceptance_ids: [AC-5]
    - id: VER-6
      owner: configured_runner
      command: "uv run zizmor --offline --min-severity=medium .github/workflows/ .github/actions/"
      proves: "The remaining workflow and local-action tree retains the configured offline medium-severity security posture."
      acceptance_ids: [AC-5]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged --committed"
      proves: "The changed public files contain no private path, credential-shaped value, local orchestration residue, or unauthorized external-operation content."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/test_release_workflow_admission.py tests/test_release_preflight.py tests/test_upstream_comparison_guard.py -q"
        proves: "The complete focused workflow, pre-tag delegation, and fail-closed live-guard slice remains green after removing scheduled execution."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-5]
---

## Design Notes

- Delete `.github/workflows/upstream-drift.yml`; do not transfer its `schedule`, `workflow_dispatch`, concurrency, checkout, setup, or direct `--check-live --json` step into another workflow.
- Add one `UPSTREAM_DRIFT_WORKFLOW` path constant beside the existing CI and publish workflow constants in `tests/test_release_workflow_admission.py`, plus one direct absence test. Keep the assertion at the exact path so a stale checkout, duplicate action, or reordered implementation cannot silently preserve the removed public workflow.
- Keep the existing publish workflow assertions and extend their focused contract only if the current suite lacks an explicit ordering assertion for the live upstream step before `Build distributions`. Reuse `_publish_build_job()` and parsed step names; do not add a second YAML loader or test module.
- Update only the `Automation Policy` and `Drift Recovery` wording in `docs/UPSTREAM_COMPARISON.md`. Replace the scheduled-workflow reference with the two surviving release-time signals: the canonical pre-tag `release_preflight.py --check-live-upstream` path and the tag-only direct guard in `publish.yml`.
- Retain exactly `python scripts/upstream_comparison_guard.py --check-live --json` as the concrete manual recovery command. Keep the existing recovery sequence and fail-closed guidance intact.
- Preserve `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `scripts/release_preflight.py`, `scripts/upstream_comparison_guard.py`, `docs/quality/upstream-comparison.json`, and their existing tests except for the one admission-suite edit named above.
- Command context basis: `pyproject.toml` defines the repository-root pytest environment and pins Actionlint and Zizmor in the dev dependency set; `.github/workflows/ci.yml` supplies the exact Actionlint and offline Zizmor commands; existing strict release plans record the focused pytest, docs-drift, and combined public-safety commands as configured-runner checks. No package-directory or container prefix is required.
- AC-1 supplies the happy path and the duplicate/reintroduction edge; AC-2 supplies the explicit failure path for drift, fetch failure, and malformed live state; AC-3 preserves the tag-only ordering boundary. No tests, builds, shell parsers, or verification wrappers ran during PLAN.
