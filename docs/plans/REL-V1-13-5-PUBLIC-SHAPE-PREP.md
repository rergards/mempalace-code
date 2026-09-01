---
slug: REL-V1-13-5-PUBLIC-SHAPE-PREP
status: completed
authority: non_authoritative
goal: "Keep the tracked Codex review helper available to developers while excluding and rejecting it from v1.13.5 public source distributions."
risk: medium
risk_note: "A missed or over-broad packaging rule could either publish developer authentication handling or remove a tracked developer tool from the repository."
files:
  - path: pyproject.toml
    change: "Add exactly scripts/codex-review.sh to the existing Hatch sdist exclude list."
  - path: scripts/release_artifact_gate.py
    change: "Add the exact repository-only review script to the existing forbidden archive-member contract."
  - path: tests/test_release_artifact_gate.py
    change: "Cover the exact Hatch exclusion and the bounded synthetic-sdist rejection diagnostic."
acceptance:
  - id: AC-1
    when: "A real wheel and sdist are built from the task tree and the tracked developer-script path is inspected."
    then: "Neither artifact contains scripts/codex-review.sh, while the repository file remains tracked, unchanged, and available to developers."
  - id: AC-2
    when: "The existing release artifact gate inspects a synthetic sdist containing scripts/codex-review.sh."
    then: "The sdist-members row fails with exactly one bounded rejected-member diagnostic naming scripts/codex-review.sh."
  - id: AC-3
    when: "Focused release artifact tests, real artifact inspection, documentation drift, and the combined tracked, staged, and committed public-safety checks run on the task tree."
    then: "Every check exits successfully and the real artifacts satisfy the existing release member contract."
  - id: AC-4
    when: "The unchanged release workflow and credential-boundary contracts are exercised and the implementation diff is inspected."
    then: "No release workflow or gate invokes an external AI client, login flow, keychain, auth file, or provider API, and the task performs no push, tag, publication, GitHub-setting, or PyPI mutation."
out_of_scope:
  - "Deleting, rewriting, renaming, or untracking scripts/codex-review.sh."
  - "Broadening the sdist exclusion beyond the exact repository-only script named by this task."
  - "Creating a new release gate, helper, client runner, credential path, workflow, or packaging abstraction."
  - "Changing release workflows, release publication procedures, package version metadata, changelog content, or dependencies."
  - "Editing docs/BACKLOG.yaml or backlog archives; runner bookkeeping owns completion metadata."
  - "Committing, pushing, tagging, publishing, changing GitHub settings, or mutating PyPI."
contract_policy:
  flow: full_spdd
  reason: "This strict release-boundary task changes both artifact construction and fail-closed admission for a tracked developer authentication surface."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The v1.13.5 source distribution must omit exactly scripts/codex-review.sh while the tracked repository file remains unchanged."
      source: "backlog scope and AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The existing artifact gate must fail closed if scripts/codex-review.sh appears in an sdist."
      source: "backlog scope and AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The focused artifact, real-build, docs-drift, and public-safety release checks must remain green together."
      source: "backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Release validation must remain credential-free, AI-client-free, and non-publishing within this task."
      source: "release credential boundary and backlog AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Hatch source-distribution membership"
      kind: internal
      paths: ["pyproject.toml"]
      expected_behavior: "Hatch omits the exact tracked developer review script from sdists without changing wheel package selection or other exclusions."
    - name: "Release artifact member admission"
      kind: internal
      paths: ["scripts/release_artifact_gate.py"]
      expected_behavior: "The existing forbidden-member check rejects the exact review-script path even though Git tracks it."
  invariants:
    - id: INV-1
      statement: "scripts/codex-review.sh remains tracked and byte-unchanged for developer use."
      applies_to: ["pyproject.toml", "scripts/release_artifact_gate.py", "tests/test_release_artifact_gate.py"]
    - id: INV-2
      statement: "Wheel package selection and all existing allowed, generated, unsafe-path, duplicate, and forbidden-member rules remain unchanged."
      applies_to: ["pyproject.toml", "scripts/release_artifact_gate.py", "tests/test_release_artifact_gate.py"]
    - id: INV-3
      statement: "Release workflows and gates remain free of external AI-client execution and AI credential access."
      applies_to: ["scripts/release_artifact_gate.py"]
    - id: INV-4
      statement: "Publication, remote mutation, versioning, changelog, and dependency surfaces remain outside the implementation diff."
      applies_to: ["pyproject.toml", "scripts/release_artifact_gate.py", "tests/test_release_artifact_gate.py"]
  risks:
    - id: RISK-1
      risk: "Changing only Hatch configuration could remove the file from real sdists while allowing a synthetic or backend-regressed archive through the gate."
      mitigation: "Represent the same exact path in the existing construction exclusion and forbidden-member admission contract, then exercise both."
    - id: RISK-2
      risk: "A directory-wide scripts exclusion could silently remove public or operational scripts from the source distribution."
      mitigation: "Use the exact scripts/codex-review.sh path in both owners and assert that exact entry in the focused test."
    - id: RISK-3
      risk: "A synthetic rejection test could pass on unrelated missing members or emit an unbounded diagnostic."
      mitigation: "Assert the sdist-members row and its single exact rejected-member detail."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python -m pytest tests/test_release_artifact_gate.py -q"
      proves: "The existing artifact contract still accepts valid members, the exact Hatch exclusion is present, and a synthetic sdist containing the tracked review script fails with the bounded diagnostic."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      owner: configured_runner
      command: "python scripts/release_readiness_gate.py --artifact-only --json"
      proves: "The repository-root Hatch project builds a real wheel and sdist in a disposable directory, and the existing artifact and metadata inspection accepts both without credentials or publication."
      acceptance_ids: [AC-1, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The configured documentation and release-command drift guard remains synchronized after the packaging-only change."
      acceptance_ids: [AC-3]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --committed --tracked --staged"
      proves: "The canonical combined release scan finds no private-path, credential-shaped, or local-only leakage in committed, tracked, or staged public surfaces."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-5
      owner: configured_runner
      command: "python -m pytest tests/test_release_skill_contract.py tests/test_release_workflow_admission.py -q"
      proves: "Release entry points retain their credential-free and AI-client-free contract, remote mutations still require separate authority, and hosted release workflow boundaries remain intact."
      acceptance_ids: [AC-4]
    - id: VER-6
      owner: configured_runner
      command: "git ls-files --error-unmatch scripts/codex-review.sh"
      proves: "The developer review script remains tracked at the exact repository path."
      acceptance_ids: [AC-1]
    - id: VER-7
      owner: configured_runner
      command: "git diff --exit-code b690ae640daf7d9ae44cdedaf85d300c0cd58236 -- scripts/codex-review.sh"
      proves: "The implementation leaves the tracked developer review script byte-unchanged relative to the task input commit."
      acceptance_ids: [AC-1, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/test_release_artifact_gate.py tests/test_release_readiness_gate.py -q"
        proves: "The complete focused artifact-member and artifact-only readiness regression slice preserves existing archive shape, metadata, fail-closed, temporary-directory, and credential-free build behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Add `scripts/codex-review.sh` as one exact Hatch sdist exclusion. Keep every existing exclusion and the wheel package configuration unchanged.
- Extend `FORBIDDEN_MEMBER_PREFIXES` with the exact file path. `_is_forbidden_member` already supports exact matches through `prefix.rstrip("/")`; no new predicate or collection is needed.
- Add one synthetic-sdist regression whose `sdist-members` detail is exactly one rejection for the archive-rooted `scripts/codex-review.sh` member. Keep missing-plugin diagnostics outside that member-row assertion.
- Extend the existing pyproject contract test to require exactly one `scripts/codex-review.sh` exclusion entry. Do not create a second packaging test module.
- `python scripts/release_readiness_gate.py --artifact-only --json` is the real-build command because it uses a disposable directory, a credential-free environment, Hatch through the root `pyproject.toml`, and the existing artifact gate. It performs no public admission or installation step in artifact-only mode.
- `scripts/gate_inventory.py` supplies the exact configured docs-drift and combined public-safety commands. Commands run from the repository root because the package manifest, tests, scripts, and Git inventory are root-relative.
- The script itself stays tracked and unchanged. Exclusion controls only the constructed sdist; the artifact gate independently protects against backend or configuration regression.
- Release workflow files, release skills, version metadata, changelog, dependencies, remotes, tags, and public services remain unchanged. No tests, builds, or verification wrappers ran during PLAN.
