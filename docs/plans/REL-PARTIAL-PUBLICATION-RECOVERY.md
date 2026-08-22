---
slug: REL-PARTIAL-PUBLICATION-RECOVERY
status: completed
authority: non_authoritative
goal: "Provide one exact-run, fail-closed recovery path when PyPI publication succeeds but GitHub Release creation fails."
risk: high
risk_note: "Recovery runs after immutable public artifacts exist; a loose retry could duplicate publication, target the wrong run, or misreport a partial release as shipped."
files:
  - path: .github/workflows/publish.yml
    change: "Make the GitHub Release job idempotent and require exact repository, tag, SHA, original artifacts, PyPI publication, and GitHub Release asset identity checks on an exact-job rerun."
  - path: scripts/release_status_gate.py
    change: "Inspect the selected exact-SHA publish run at job granularity and emit the single repository-qualified GitHub Release job-rerun command only for the proven partial-publication state."
  - path: scripts/docs_drift_guard.py
    change: "Own the canonical partial-publication recovery command shape and keep release documentation and the executable release skill synchronized."
  - path: docs/RELEASING.md
    change: "Document hosted branch-rule checks, operator-only tag-ruleset checks, partial-publication diagnosis, the exact-run recovery command, and retry outcomes."
  - path: docs/release-admission-rulesets.md
    change: "Replace ambiguous orphan/publication remediation with the bounded command-or-instruction contract and state the hosted versus operator ruleset boundary explicitly."
  - path: .claude/skills/release/SKILL.md
    change: "Use the status gate's exact remediation verbatim and define the partial-publication recovery and no-safe-command boundaries without permitting manual release creation."
  - path: tests/test_release_status_gate.py
    change: "Cover job-level partial-publication detection, exact command rendering, stale or wrong run rejection, prerequisite failures, and repeated or already-complete attempts."
  - path: tests/test_release_workflow_admission.py
    change: "Pin the hosted retry job's identity, artifact and publication rechecks, exact release-asset reconciliation, idempotent release behavior, permissions, and tag-only trigger."
  - path: tests/test_release_skill_contract.py
    change: "Require the executable skill to carry the canonical exact-run recovery promise and bounded instruction fallback."
  - path: tests/test_release_ruleset_contract.py
    change: "Verify that ruleset documentation assigns branch checks to hosted admission and v* ruleset inspection to the operator token."
  - path: tests/test_docs_drift_guard.py
    change: "Cover drift detection for the recovery command and hosted/operator ruleset boundary across the runbook and release skill."
acceptance:
  - id: AC-1
    when: "the release documentation contract is inspected for initial tag publication and an exact-job rerun"
    then: "it identifies the public main branch-rule checks performed in hosted CI and the refs/tags/v* ruleset check that remains operator-side because it needs administration read."
  - id: AC-2
    when: "the newest exact-SHA Publish to PyPI run has a successful publish job and a failed GitHub Release job while tag, SHA, artifacts, provenance, and PyPI inventory agree"
    then: "the status gate emits one directly runnable gh run rerun command bound to that repository, workflow run ID, and GitHub Release job ID; the rerun preserves the tag and rechecks every prerequisite before creating or validating the release."
  - id: AC-3
    when: "any status-gate surface is failed or errored"
    then: "human and JSON output provide either one directly runnable repository-qualified command or an explicitly labeled bounded instruction explaining why no safe command is available, and the release skill promises the same behavior."
  - id: AC-4
    when: "recovery is requested repeatedly, before prerequisites complete, after the release exists, for a reordered job state, with a stale SHA, or against a different repository or run"
    then: "the workflow converges by validating the existing release or the gate fails closed before any PyPI upload, tag mutation, or duplicate GitHub Release creation."
  - id: AC-5
    when: "the focused workflow, release-status, release-skill, documentation/ruleset, and public-safety fixture commands execute"
    then: "they exit successfully after exercising the partial-publication happy path, fail-closed matrix, synchronized operator guidance, and tracked-content safety boundary."
out_of_scope:
  - "Moving, deleting, or recreating an immutable public tag."
  - "Re-uploading a wheel or sdist, dispatching a new publish workflow, or adding a second publication route."
  - "Automatically changing branch protection, tag rulesets, repository secrets, environments, or trusted-publisher configuration."
  - "Repairing historical acknowledged orphan tags or changing their registry."
  - "Editing backlog or backlog archive metadata."
contract_policy:
  flow: full_spdd
  reason: "Strict release-recovery task spanning hosted workflow permissions, immutable public artifacts, exact-run identity, and operator-facing mutation guidance."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Release documentation must state the exact hosted branch-rule and operator-side v* tag-ruleset boundary."
      source: "AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "A proven PyPI-success/GitHub-release-failed run must yield one exact-run, exact-job recovery command whose target rechecks all publication identity prerequisites."
      source: "AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Status output and the release skill must share the command-or-bounded-instruction remediation contract."
      source: "AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Repeated, reordered, stale, wrong-target, and already-complete recovery attempts must remain idempotent or fail closed."
      source: "AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused release and public-safety fixtures must preserve the complete release and tracked-content contracts."
      source: "AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "hosted publish recovery"
      kind: internal
      paths: [".github/workflows/publish.yml"]
      expected_behavior: "The original tag-triggered run may rerun only its identified GitHub Release job, which rechecks exact identity and publication evidence and treats an existing release as valid only when its wheel and sdist assets match the verified original-run artifacts exactly."
    - name: "release status CLI"
      kind: cli
      paths: ["scripts/release_status_gate.py"]
      expected_behavior: "Exact-SHA workflow selection expands to job-level evidence and exposes a runnable exact-run recovery only for the uniquely safe partial state."
    - name: "release operator contract"
      kind: internal
      paths: ["scripts/docs_drift_guard.py", "docs/RELEASING.md", "docs/release-admission-rulesets.md", ".claude/skills/release/SKILL.md"]
      expected_behavior: "Runbook, ruleset boundary, and executable skill use one canonical recovery shape and explicitly label states that have no safe command."
    - name: "release recovery fixtures"
      kind: internal
      paths: ["tests/test_release_status_gate.py", "tests/test_release_workflow_admission.py", "tests/test_release_skill_contract.py", "tests/test_release_ruleset_contract.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "Hermetic tests cover safe recovery, exact identifiers, idempotency, fail-closed boundaries, and documentation synchronization."
  invariants:
    - id: INV-1
      statement: "The publish workflow remains push-of-v* tag triggered; workflow_dispatch and release-event publication remain forbidden."
      applies_to: [".github/workflows/publish.yml"]
    - id: INV-2
      statement: "PyPI upload remains owned only by the publish job and is never rerun by the GitHub Release recovery command."
      applies_to: [".github/workflows/publish.yml", "scripts/release_status_gate.py"]
    - id: INV-3
      statement: "release_status_gate.py remains read-only and only reports a mutation command after all recovery prerequisites are proven."
      applies_to: ["scripts/release_status_gate.py"]
    - id: INV-4
      statement: "A published v* tag is never moved, deleted, recreated, or bypassed during recovery."
      applies_to: [".github/workflows/publish.yml", "docs/RELEASING.md", ".claude/skills/release/SKILL.md"]
    - id: INV-5
      statement: "Hosted GITHUB_TOKEN checks public main protection but does not claim or request repository administration read for the v* tag ruleset."
      applies_to: [".github/workflows/publish.yml", "docs/release-admission-rulesets.md"]
    - id: INV-6
      statement: "A release is reported shipped only after the unchanged full release-status surface set is green."
      applies_to: ["scripts/release_status_gate.py", ".claude/skills/release/SKILL.md"]
  risks:
    - id: RISK-1
      risk: "Rerunning the workflow rather than the GitHub Release job could retry the trusted PyPI publisher."
      mitigation: "Render a command containing both the selected workflow run ID and the unique GitHub Release job ID; pin this shape in workflow and status tests."
    - id: RISK-2
      risk: "A red run for another SHA or repository could be mistaken for the candidate's partial publication."
      mitigation: "Bind lookup and rerun output to the explicit repository, peeled public tag SHA, reviewed SHA, workflow identity, event, run ID, and job graph."
    - id: RISK-3
      risk: "The rerun could create a duplicate or bless artifacts different from those already on PyPI."
      mitigation: "Re-download the original run artifact, compare its required wheel and sdist identity with the exact-version PyPI inventory and provenance, then require the GitHub Release asset filename set and SHA-256 digests to match. An existing release may receive only missing expected assets from that verified artifact; mismatched or unexpected assets fail closed without overwrite or deletion."
    - id: RISK-4
      risk: "Documentation could imply that hosted CI verifies the operator-only v* ruleset."
      mitigation: "Derive synchronized wording through the existing drift guard and enforce the permission boundary in workflow, ruleset, skill, and documentation contract tests."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_status_gate.py -q"
      proves: "Exact-SHA job selection, partial-publication recognition, exact remediation output, prerequisite gating, and stale/repeated/wrong-target behavior."
      acceptance_ids: [AC-2, AC-3, AC-4]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_release_workflow_admission.py -q"
      proves: "The tag-only hosted workflow reruns only the GitHub Release job and rechecks repository, tag, SHA, artifact, PyPI, and exact existing-release asset identity, including bounded missing-asset repair and fail-closed mismatch handling."
      acceptance_ids: [AC-1, AC-2, AC-4]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_release_skill_contract.py tests/test_release_ruleset_contract.py tests/test_docs_drift_guard.py -q"
      proves: "The release skill and public docs share the canonical recovery shape and accurately divide hosted branch checks from operator-side tag-ruleset inspection."
      acceptance_ids: [AC-1, AC-3, AC-5]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_public_safety_scan.py -q"
      proves: "Changed tracked workflow, script, skill, documentation, and fixture content stays inside the existing public-safety contract."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_release_status_gate.py tests/test_release_workflow_admission.py tests/test_release_skill_contract.py tests/test_release_ruleset_contract.py tests/test_docs_drift_guard.py tests/test_public_safety_scan.py -q"
        proves: "The complete focused release-recovery and public-safety slice remains green together after workflow, status, and documentation changes."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Extend `check_workflow_run` or its existing exact-SHA workflow owner to retain the selected run database ID and inspect that run's jobs. Do not add a second workflow selector.
- Treat the safe partial state narrowly: the exact tag-triggered run belongs to `rergards/mempalace-code`, its head SHA matches the peeled public tag and `--expect-sha`, build and `publish` succeeded, the unique `github-release` job failed, and the existing tag, artifact inventory, PyPI files, provenance, ref protection, audit, and install-smoke rows are otherwise green.
- Render one mutation command in that state: `gh run rerun <workflow-run-id> --job <github-release-job-id> --repo rergards/mempalace-code`. Keep placeholders only in documentation examples; status output must contain concrete IDs from the selected run.
- If the run/job identity is missing, duplicated, unparseable, in progress, stale, differently ordered, or has any failed prerequisite, emit an explicitly labeled bounded instruction to rerun the canonical read-only status command after resolving named rows. Do not emit a generic workflow rerun.
- Keep recovery out of `release_status_gate.py` execution: the gate reads and renders; the operator separately authorizes the emitted `gh run rerun` mutation.
- In `github-release`, repeat the exact repository/tag/SHA admission needed after a partial run because rerunning one job does not replay `build`. Download the original run's `dist` artifact, run the existing artifact gate, and compare the exact wheel/sdist inventory and provenance with public PyPI before any release write.
- Make GitHub Release creation convergent: if no release exists, create it with `--verify-tag` and attach the verified original-run wheel and sdist. If one exists, require matching tag and acceptable non-draft/non-prerelease metadata, compare its exact asset filename set and downloaded SHA-256 digests with the verified original-run wheel and sdist, and exit successfully only after equality is proven. When all present expected assets match and only an expected asset is missing, upload only that missing file from the verified original-run artifact and repeat the exact set-and-digest check. A mismatched expected asset, an unexpected asset, failed download, or failed post-upload comparison fails closed; never use `--clobber`, delete an asset, or create a second release.
- Preserve least privilege. The recovery job may add only the read scopes required for its own rechecks alongside `contents: write`; `administration: read` remains unavailable to `GITHUB_TOKEN`, so the `refs/tags/v*` ruleset stays an operator-side status/readiness check.
- The command basis is the repository's Python 3.11+ pytest layout in `pyproject.toml`; workflow shape tests parse YAML through the existing PyYAML dev dependency, and public-safety regression uses the existing focused fixture file.
- Do not add `incident_proof`: the repository has no `docs/quality/incident-class-registry.yaml` match for this isolated release workflow/documentation recovery task.
