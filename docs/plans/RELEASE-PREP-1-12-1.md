---
slug: RELEASE-PREP-1-12-1
goal: "Prepare a synchronized v1.12.1 patch-release tree for named systemd-user watcher coordination."
risk: medium
risk_note: "Release metadata must stay synchronized while updater fixtures continue to prove exact named-unit coordination, safe refusal, and rollback from the new baseline."
files:
  - path: pyproject.toml
    change: "Bump the published mempalace-code package version from 1.12.0 to 1.12.1."
  - path: uv.lock
    change: "Regenerate the editable root-package lock metadata at 1.12.1 without changing dependency policy or third-party resolutions."
  - path: README.md
    change: "Advance the public version shield from 1.12.0 to 1.12.1."
  - path: tests/test_updater.py
    change: "Advance fake stable-release, prerelease, install, and rollback literals so updater behavior is exercised from the 1.12.1 release baseline."
acceptance:
  - id: AC-1
    when: "Release metadata and the generated lockfile are inspected after the version bump."
    then: "pyproject.toml, the editable mempalace-code entry in uv.lock, and the README version shield all report exactly 1.12.1."
  - id: AC-2
    when: "Update apply discovers one active named MemPalace systemd-user watcher and a newer compatible stable package."
    then: "The updater installs the newer package with preserved extras and stops and starts that exact named watcher unit."
  - id: AC-3
    when: "Watcher discovery is ambiguous, malformed, unrelated, or unavailable."
    then: "Update apply refuses during preflight without invoking package installation or stopping or starting any watcher unit."
  - id: AC-4
    when: "Validation or installation fails after an update starts from the 1.12.1 baseline."
    then: "The updater reinstalls exactly 1.12.1 and restores the previously selected named watcher instead of the legacy default unit."
  - id: AC-5
    when: "Version selection sees stable, prerelease, and next-major candidates above the 1.12.1 baseline."
    then: "The updater selects only the newer compatible stable release and continues to reject prerelease and next-major candidates."
  - id: AC-6
    when: "The public changelog is inspected in the prepared release tree."
    then: "It contains exactly one v1.12.1 section dated 2026-07-12, no temporary watcher-discovery task heading, and accurate named-unit discovery, ambiguous-service refusal, and exact stop/start wording."
  - id: AC-7
    when: "The deterministic quality scorecard and committed-tree public-safety gates inspect the prepared release tree."
    then: "The committed scorecard artifacts are current and the exact committed tree has no public-safety findings."
  - id: AC-8
    when: "The v1.12.1 tag, GitHub Release, workflow results, wheel, and sdist are public after the separate publication step."
    then: "The release-status gate reports all required public surfaces healthy for version 1.12.1, including a fresh install smoke."
out_of_scope:
  - "Changing updater implementation behavior or systemd-user unit discovery logic."
  - "Changing dependency constraints, optional-extra bounds, or resolved third-party package versions."
  - "Changing release automation, release-status gate implementation, or hosted workflow configuration."
  - "Editing docs/BACKLOG.yaml or backlog archives; completion metadata belongs to Autopilot bookkeep."
  - "Tagging, pushing, publishing, creating a GitHub Release, deploying, or enabling update timers."
contract_policy:
  flow: full_spdd
  reason: "This strict release-preparation task changes publishable metadata and updater safety fixtures across package, documentation, and systemd coordination surfaces."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "All public and package release-version surfaces must identify v1.12.1 consistently."
      source: "backlog scope and acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Updater fixtures must use 1.12.1 as the installed and rollback baseline while retaining compatible-stable selection policy."
      source: "backlog acceptance and existing updater fixture pattern"
      acceptance_ids: [AC-2, AC-4, AC-5]
    - id: REQ-3
      statement: "Named watcher discovery failures must remain mutation-safe at the v1.12.1 release boundary."
      source: "backlog release-note acceptance and watcher-discovery regression contract"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The public changelog must consolidate the completed watcher coordination change into one accurate v1.12.1 entry."
      source: "backlog acceptance"
      acceptance_ids: [AC-6]
    - id: REQ-5
      statement: "Deterministic quality artifacts and the committed public tree must remain release-ready."
      source: "backlog acceptance"
      acceptance_ids: [AC-7]
    - id: REQ-6
      statement: "The existing release-status gate must be usable unchanged to verify v1.12.1 after publication."
      source: "backlog acceptance"
      acceptance_ids: [AC-8]
  surfaces:
    - name: "Package release identity"
      kind: internal
      paths: ["pyproject.toml", "uv.lock"]
      expected_behavior: "The declared project and editable locked root package expose the same 1.12.1 version without dependency-resolution drift."
    - name: "Public release references"
      kind: internal
      paths: ["README.md"]
      expected_behavior: "The public version shield presents v1.12.1. The dedicated changelog phase owns the dated patch-release entry."
    - name: "Updater release-policy fixtures"
      kind: internal
      paths: ["tests/test_updater.py"]
      expected_behavior: "Fixtures model an upgrade from 1.12.1 to a newer compatible stable release, exact rollback to 1.12.1, and unchanged named-unit safety behavior."
  invariants:
    - id: INV-1
      statement: "Unsafe or ambiguous watcher discovery must refuse before installer, watcher, or state-file mutation."
      applies_to: ["tests/test_updater.py"]
    - id: INV-2
      statement: "A successful or rolled-back update must restart the exact watcher unit selected during discovery."
      applies_to: ["tests/test_updater.py"]
    - id: INV-3
      statement: "Prerelease and next-major packages must remain ineligible under the existing update policy."
      applies_to: ["tests/test_updater.py"]
    - id: INV-4
      statement: "The release bump must not change dependency constraints or third-party lock resolutions."
      applies_to: ["pyproject.toml", "uv.lock"]
    - id: INV-5
      statement: "Release automation and publication remain unchanged and outside provider-owned implementation."
      applies_to: ["pyproject.toml", "uv.lock", "README.md", "tests/test_updater.py"]
  risks:
    - id: RISK-1
      risk: "Leaving 1.12.1 as the fake target after the package bump would turn the update happy path into a no-update case."
      mitigation: "Advance stable and prerelease candidates together and assert the selected newer stable version explicitly."
    - id: RISK-2
      risk: "Partial literal updates could install a newer package but roll back to 1.12.0."
      mitigation: "Search all v1.12.x literals and run focused install, failure, timeout, and named-watcher rollback tests."
    - id: RISK-3
      risk: "A lock regeneration could introduce unrelated dependency-resolution drift."
      mitigation: "Use uv lock, inspect the lock diff, and reject changes beyond the editable root-package version."
    - id: RISK-4
      risk: "Release notes could overstate discovery safety or lose the exact-unit coordination guarantee."
      mitigation: "Assert one dated section with all three required operator-visible guarantees and removal of the temporary task heading."
  verification:
    - id: VER-1
      command: >-
        uv lock --check && python -c 'import tomllib; from pathlib import Path; project = tomllib.load(open("pyproject.toml", "rb")); lock = tomllib.load(open("uv.lock", "rb")); root = next(item for item in lock["package"] if item["name"] == "mempalace-code"); readme = Path("README.md").read_text(encoding="utf-8"); assert project["project"]["version"] == "1.12.1"; assert root["version"] == "1.12.1"; assert "[version-shield]: https://img.shields.io/badge/version-1.12.1-" in readme'
      proves: "The project, lockfile root package, and public shield are synchronized at exactly 1.12.1."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: python -m pytest tests/test_updater.py::TestSystemdWatcherDiscovery::test_apply_coordinates_the_selected_named_watcher tests/test_updater.py::TestApplyUpdate -q
      proves: "A compatible update preserves extras and coordinates the exact selected named watcher."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: python -m pytest tests/test_updater.py::TestSystemdWatcherDiscovery::test_apply_refuses_unsafe_discovery_before_mutation -q
      proves: "Every unsafe discovery class refuses before install, stop, start, or updater-state mutation."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: python -m pytest tests/test_updater.py::TestSystemdWatcherDiscovery::test_rollback_restarts_the_selected_named_watcher tests/test_updater.py::TestRollback -q
      proves: "Failure paths restore the 1.12.1 baseline and restart the selected named watcher."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: python -m pytest tests/test_updater.py::TestUpdateStatus::test_status_reports_eligibility_provenance_and_next_run_without_mutation tests/test_updater.py::TestApplyUpdate -q
      proves: "Selection accepts the newer compatible stable fixture while excluding prerelease and next-major candidates."
      acceptance_ids: [AC-5]
    - id: VER-7
      command: python scripts/quality_scorecard.py --check && python scripts/public_safety_scan.py --committed
      proves: "Generated scorecard artifacts match the tree and the exact committed release candidate is public-safe."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: python scripts/release_status_gate.py --version 1.12.1 --repo rergards/mempalace-code --remote publish --branch main
      proves: "After the separate publication step, public tag, CI, GitHub Release, PyPI artifacts, and fresh install smoke agree on v1.12.1."
      acceptance_ids: [AC-8]
    - id: VER-9
      command: uv build
      proves: "Hatchling can build the v1.12.1 wheel and source distribution from the synchronized package metadata."
      acceptance_ids: [AC-1]
    - id: VER-10
      command: ruff check mempalace_code/ tests/ scripts/ && ruff format --check mempalace_code/ tests/ scripts/
      proves: "The prepared release tree satisfies the configured lint and formatting gates."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-11
      command: python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"
      proves: "The prepared release tree satisfies the repository type-check gate."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: python -m pytest tests/test_updater.py -q
        proves: "All updater status, discovery, apply, rollback, scheduling, installation detection, and command guards remain stable at the new baseline."
        acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
      - id: REG-2
        command: python -m pytest tests/ -x -q
        proves: "The full configured test suite remains compatible with the release metadata and fixture-only baseline changes."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-3
        command: python -m pytest tests/test_release_status_gate.py -q
        proves: "The unchanged release-status gate retains its six-surface success, blocker, JSON, and install-smoke behavior before live v1.12.1 use."
        acceptance_ids: [AC-8]
      - id: REG-5
        command: python scripts/quality_scorecard.py --check && python scripts/public_safety_scan.py --committed
        proves: "The deterministic quality scorecard artifacts remain current and the committed release tree has no public-safety findings."
        acceptance_ids: [AC-7]

---

## Design Notes

- The current public release tag and package baseline are v1.12.0. The completed named watcher-unit coordination is a backward-compatible updater fix, so the requested patch target is v1.12.1.
- `tests/test_updater.py` currently uses 1.12.1 as the fake stable target and 1.12.0 as the rollback version. Advance the stable target to 1.12.2, the rejected prerelease to 1.12.3rc1, and every prior-version or rollback expectation to 1.12.1. Keep the 2.0.0 next-major boundary fixture.
- Preserve focused coverage for the unique active named unit, active legacy unit, ambiguous multiple units, malformed names, unrelated ExecStart commands, unavailable user manager, exact-unit stop/start, and rollback restart.
- Regenerate `uv.lock` from the repository root after changing `pyproject.toml`. Its diff should change only the editable `mempalace-code` root version; dependency constraints and resolved third-party versions remain fixed.
- Replace the top temporary watcher-discovery changelog entry with the v1.12.1 section. Keep the existing v1.12.0 history intact. The new entry must distinguish read-only status discovery from apply mutation and state that apply coordinates the exact selected watcher unit.
- The deterministic scorecards contain repository metrics rather than a package-version field. Literal replacements do not change test inventory or line counts, so `--check` should pass without rewriting `docs/quality/scorecard.md` or `docs/quality/scorecard.json`; regenerate them only if the canonical check proves real drift.
- `scripts/release_status_gate.py` and `.github/workflows/publish.yml` remain unchanged. VER-8 is a post-publication gate and is expected to run only after a separately authorized release operation makes all public surfaces available.
- Commands run from the repository root because `pyproject.toml` defines the package, pytest, Ruff, and Pyright context, `uv.lock` is root-scoped, and the quality and release scripts resolve repository-relative paths. No tests, builds, or verification wrappers ran during PLAN.
- `uv build` creates ignored distribution artifacts. Remove them during implementation handoff after recording build evidence; do not include them in the implementation commit.
