---
slug: RELEASE-SMOKE-UV-TOOL-PYC-STATE-ISOLATION
status: completed
authority: non_authoritative
goal: "Prevent Python bytecode cache writes from invalidating read-only update probes across every disposable installer contour."
risk: medium
risk_note: "The code change is one shared environment flag, but it affects the release-blocking exact-wheel smoke across four installer runtimes and must preserve strict mutation detection."
files:
  - path: scripts/release_install_metadata_smoke.py
    change: "Add PYTHONDONTWRITEBYTECODE=1 to the existing credential-free environment owner inherited by all disposable install and probe subprocesses."
  - path: tests/test_release_install_metadata_smoke.py
    change: "Prove the shared flag survives probe-state isolation for every installer and that unsupported-platform snapshot checks still fail on real mutable-state writes."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable scorecard after the focused regression coverage changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable scorecard from the same canonical generator."
acceptance:
  - id: AC-1
    when: "a disposable venv, bootstrap-venv, pipx, or uv-tool contour runs any install or installed-application probe subprocess"
    then: "its environment inherits PYTHONDONTWRITEBYTECODE=1 from the single credential-free environment owner"
  - id: AC-2
    when: "the focused installed-smoke regressions exercise environment inheritance and deliberately write real application or tool state during an unsupported-platform update probe"
    then: "the bytecode-suppression flag remains present and the unchanged mutable-state snapshot reports the real mutation as a failed surface"
  - id: AC-3
    when: "the configured release-readiness gate qualifies one exact wheel at a clean candidate SHA with the configured offline model cache"
    then: "all four installers and the exact-wheel offline golden suite pass, including the uv-tool read-only update-status surface"
out_of_scope:
  - "Weakening snapshot comparison or excluding __pycache__, pyc, or arbitrary runtime paths from mutable-state evidence."
  - "Changing updater runtime behavior, installer enumeration, probe commands, credential filtering, network admission, or the exact-wheel golden suite."
  - "Adding an environment helper, installer-specific branch, command-line option, dependency, release gate, or generated-artifact owner."
  - "Editing backlog metadata, invoking AI clients or authentication, publishing, deploying, committing, or pushing."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release pipeline fix changes the shared subprocess environment used to admit exact wheels through four installer runtimes."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Every disposable installer probe must suppress Python bytecode writes through the existing credential-free environment owner."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Focused evidence must cover flag inheritance while preserving fail-closed detection of real mutable state."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "One clean exact candidate must pass the complete local release-readiness contour, including all installers and the offline installed golden suite."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "Disposable installer credential-free environment"
      kind: internal
      paths: ["scripts/release_install_metadata_smoke.py"]
      expected_behavior: "The existing shared environment exports PYTHONDONTWRITEBYTECODE=1 before venv, bootstrap-venv, pipx, and uv-tool install and probe subprocesses are derived."
    - name: "Generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "The existing generated scorecard pair remains byte-current after focused test metrics change."
  invariants:
    - id: INV-1
      statement: "_credential_free_env remains the single environment owner, and _isolate_probe_state continues to derive isolated HOME, XDG, installer, and cache paths from it."
      applies_to: ["scripts/release_install_metadata_smoke.py"]
    - id: INV-2
      statement: "_snapshot_mutable_state keeps comparing every existing application and tool state root without path, suffix, or file-type exclusions."
      applies_to: ["scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py"]
    - id: INV-3
      statement: "The four-installer order, exact installed-console provenance, neutral cwd, update command set, socket guard, and offline behavior remain unchanged."
      applies_to: ["scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py"]
    - id: INV-4
      statement: "No credential, ambient user site, provider client, authentication, network admission, publication, or deployment surface is introduced."
      applies_to: ["scripts/release_install_metadata_smoke.py"]
  risks:
    - id: RISK-1
      risk: "Setting the flag only in the uv-tool branch would leave sibling contours inconsistent and create a second environment authority."
      mitigation: "Set it once in _credential_free_env and assert that _isolate_probe_state preserves the value used by all four runners."
    - id: RISK-2
      risk: "Treating pyc files as ignorable snapshot entries could conceal genuine runtime mutations."
      mitigation: "Leave snapshot code untouched and add a negative regression that writes inside an existing mutable root and requires a failed surface."
    - id: RISK-3
      risk: "A unit-only repair could miss uv's installed interpreter behavior in the complete candidate contour."
      mitigation: "Retain the exact configured release-readiness command as acceptance evidence for all installers and the offline golden suite."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_install_metadata_smoke.py -q"
      proves: "The focused installed-smoke suite proves shared flag inheritance, strict mutation failure, and retained installer probe contracts."
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
      proves: "With CANDIDATE_SHA bound to the clean implementation HEAD and the configured offline model cache, the canonical gate builds one exact wheel and qualifies all installers plus the installed golden suite."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The generated scorecard pair is current after focused regression coverage changes."
      acceptance_ids: [AC-2]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical non-network suite preserves installed smoke, updater, golden CLI, workflow, documentation, and runtime behavior."
        acceptance_ids: [AC-1, AC-2, AC-3]
---

## Design Notes

- Extend `scripts/release_install_metadata_smoke.py::_credential_free_env`; add no installer-specific assignment. Every runner starts from this owner, and `_isolate_probe_state` copies its entries before replacing only state paths and `PATH`.
- Set `PYTHONDONTWRITEBYTECODE` to the conventional string value `1`, matching the installed golden environment in `scripts/release_readiness_gate.py`.
- Keep `_snapshot_tree`, `_snapshot_mutable_state`, `_probe_recovery_refusals`, and `_probe_unsupported_platform_updates` unchanged. The fix prevents interpreter-owned pyc creation at process startup while retaining byte-for-byte detection for real application and tool state.
- Extend the existing probe-environment regression to assert the shared flag survives isolation. Add one bounded unsupported-platform negative case whose subprocess seam writes a sentinel into an existing snapshotted root and whose expected result is `STATUS_FAIL` with the current mutation diagnostic.
- Cover the four-installer boundary through their common owner and the existing aggregate/release smoke. Add no duplicated per-installer environment assertions unless implementation evidence shows a runner bypasses `_credential_free_env`.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with `python scripts/quality_scorecard.py --write`; the canonical generator records test lines and functions.
- Command context basis: all commands run from the repository root. `scripts/gate_inventory.py` declares the exact configured release-readiness, scorecard, and full non-network commands; the runner binds `CANDIDATE_SHA` and the existing offline model-cache environment for VER-2.
- `docs/quality/incident-class-registry.yaml` is absent in this worktree, so this isolated release-smoke environment fix has no registry-matched `incident_proof` block.
- PLAN did not execute tests, builds, release gates, verification wrappers, or generated-artifact validation.
