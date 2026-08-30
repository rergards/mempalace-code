---
slug: REL-SDIST-EXCLUDE-LOCAL-OPS
goal: "Exclude local Playwright residue and tracked operational records from public source distributions while retaining public documentation."
risk: low
risk_note: "The change extends one existing Hatch exclusion list and its existing packaging contract assertion; incorrect path specificity could still leak operational files or omit public docs."
files:
  - path: pyproject.toml
    change: "Add the four exact local and operational paths to the existing Hatch sdist exclusion list."
  - path: tests/test_release_artifact_gate.py
    change: "Extend the existing pyproject packaging contract assertion to require each new exclusion exactly once and preserve the public-doc boundary."
acceptance:
  - id: AC-1
    when: "the Hatch sdist configuration is inspected"
    then: "the exclusion list contains .playwright-mcp/, docs/BACKLOG.yaml, docs/BACKLOG-archived.yaml, and docs/task-evidence/ exactly once each"
  - id: AC-2
    when: "the focused packaging contract test runs against the task configuration, or any required entry is absent or duplicated"
    then: "the exact four-entry contract passes for the task configuration and fails for a missing or duplicate required exclusion"
  - id: AC-3
    when: "a fresh wheel and sdist are built while the user-owned .playwright-mcp directory exists and archive members are inspected"
    then: "neither artifact contains .playwright-mcp/, docs/BACKLOG.yaml, docs/BACKLOG-archived.yaml, or docs/task-evidence/"
  - id: AC-4
    when: "the existing artifact-only release readiness command inspects the fresh wheel and sdist"
    then: "the existing artifact gate and its delegated Twine check both pass"
  - id: AC-5
    when: "the fresh sdist member list is inspected after applying the exact exclusions"
    then: "public documentation under docs/quality remains present"
  - id: AC-6
    when: "the implementation diff and focused packaging regression evidence are inspected"
    then: "only the existing sdist exclusion contract changes; release gates, dependencies, documentation content, runtime behavior, and user-owned local artifacts remain unchanged"
out_of_scope:
  - "Changing scripts/release_artifact_gate.py, release workflows, readiness orchestration, or Twine behavior."
  - "Deleting, editing, tracking, or creating the user-owned .playwright-mcp directory or its contents."
  - "Editing backlog metadata, task evidence, public documentation, dependencies, runtime code, version metadata, or changelog content."
  - "Adding a packaging helper, gate, dependency, external AI client, credential access, or second packaging owner."
  - "Building, publishing, tagging, pushing, or otherwise mutating a public release during implementation."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release task changes the public source-distribution boundary and requires exact construction and artifact evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Hatch must exclude the four exact local and operational surfaces exactly once."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The existing packaging contract test must assert all four exact exclusions and the public-doc boundary."
      source: "current backlog contract AC-2 and AC-5"
      acceptance_ids: [AC-2, AC-5]
    - id: REQ-3
      statement: "A fresh build with local Playwright residue present must omit all four forbidden surfaces and pass existing artifact and metadata admission."
      source: "current backlog contract AC-3 and AC-4"
      acceptance_ids: [AC-3, AC-4]
    - id: REQ-4
      statement: "The task must preserve unrelated release, dependency, documentation, runtime, and user-owned local state."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Hatch source-distribution membership"
      kind: internal
      paths: ["pyproject.toml"]
      expected_behavior: "The existing Hatch owner omits four exact local and operational paths without broadening exclusions into public docs."
  invariants:
    - id: INV-1
      statement: "Wheel package selection and every pre-existing sdist exclusion remain unchanged."
      applies_to: ["pyproject.toml", "tests/test_release_artifact_gate.py"]
    - id: INV-2
      statement: "Public documentation, including docs/quality, remains eligible for and present in the sdist."
      applies_to: ["pyproject.toml", "tests/test_release_artifact_gate.py"]
    - id: INV-3
      statement: "The existing artifact gate, Twine delegation, release workflows, dependencies, runtime code, and documentation content remain unchanged."
      applies_to: ["pyproject.toml", "tests/test_release_artifact_gate.py"]
    - id: INV-4
      statement: "User-owned .playwright-mcp files remain byte-unchanged and untracked."
      applies_to: ["pyproject.toml", "tests/test_release_artifact_gate.py"]
  risks:
    - id: RISK-1
      risk: "A broad docs exclusion could remove public quality documentation with the operational records."
      mitigation: "Use exact backlog-file and task-evidence-directory entries and retain an explicit docs/quality boundary assertion and real-sdist inspection."
    - id: RISK-2
      risk: "A spelling or duplicate entry could leave a local surface publishable or obscure configuration ownership."
      mitigation: "Assert count equality of one for each exact exclusion in the existing packaging contract test."
    - id: RISK-3
      risk: "Editing the artifact gate would create a second change owner beyond the requested construction fix."
      mitigation: "Leave the gate unchanged and use its existing artifact-only readiness path solely as post-build evidence."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_artifact_gate.py -q"
      proves: "The focused artifact and packaging contract requires each exact exclusion once, rejects missing or duplicate configuration through its assertions, preserves public-doc eligibility, and retains existing archive-member behavior."
      acceptance_ids: [AC-1, AC-2, AC-5, AC-6]
    - id: VER-2
      owner: configured_runner
      command: "python scripts/release_readiness_gate.py --artifact-only --json"
      proves: "From the repository root, the existing disposable build creates a fresh wheel and sdist and runs unchanged artifact inspection plus delegated Twine validation; with the owner-provided .playwright-mcp fixture present, archive evidence covers all excluded surfaces and retained docs/quality members."
      acceptance_ids: [AC-3, AC-4, AC-5, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_release_artifact_gate.py -q"
        proves: "The complete focused artifact-gate suite preserves existing valid, forbidden, untracked, malformed, metadata, and packaging-configuration behavior around the bounded Hatch change."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Rule Zero selects the existing `[tool.hatch.build.targets.sdist].exclude` owner in `pyproject.toml` and the existing build-configuration contract in `tests/test_release_artifact_gate.py`. Extending these owners is cheaper and clearer than changing the artifact gate, adding a helper, or creating another packaging policy surface.
- Add exactly `.playwright-mcp/`, `docs/BACKLOG.yaml`, `docs/BACKLOG-archived.yaml`, and `docs/task-evidence/`. Preserve every existing exclusion and the wheel target unchanged.
- Extend `test_pyproject_excludes_repository_only_release_configuration_from_the_sdist` rather than creating another test module. Assert `exclude.count(path) == 1` for every new entry; retain its existing `.claude/**`, `/.gitleaksignore`, and `scripts/codex-review.sh` assertions.
- Keep the docs boundary path-specific. Do not add `docs/`, `docs/quality/`, a wildcard covering all YAML or Markdown, or a generic operational-name matcher.
- The current plan worktree has no `.playwright-mcp` directory. VER-2 becomes AC-3 evidence only in the runner contour where the owner-provided directory exists; the command must inspect it without creating, deleting, editing, tracking, or cleaning it. If that fixture is absent, report AC-3 as unrun rather than manufacturing local residue.
- `scripts/release_readiness_gate.py --artifact-only --json` is the existing configured root-level command: it builds into a disposable directory, calls the unchanged artifact gate, and delegates metadata validation to Twine. Its archive evidence must show all four forbidden surfaces absent and at least one `docs/quality/` member present before AC-3 or AC-5 is claimed.
- Cheapest decisive falsifier: VER-1 fails if any exact entry is absent or duplicated; VER-2 or its archive-member evidence falsifies the solution if local residue or operational records ship, public quality docs disappear, or artifact/Twine admission fails.
- Rollback is the direct reversal of the two planned files. No migration, cleanup, compatibility period, dependency change, workflow rollout, credential use, publication, or runtime recovery exists.
- PLAN inspected repository-root `pyproject.toml`, `tests/test_release_artifact_gate.py`, `scripts/release_artifact_gate.py`, `scripts/release_readiness_gate.py`, `scripts/gate_inventory.py`, and hosted workflow command declarations. It ran no tests, builds, gates, wrappers, external AI clients, Git finalization, or publication.
