---
slug: REL-INSTALLED-RECOVERY-ALL-INSTALLERS
status: completed
authority: non_authoritative
goal: "Qualify the exact candidate wheel through the landed four-installer no-model smoke after repairing its cold dependency-install timeout."
risk: high
risk_note: "This changes a release-blocking timeout boundary; an undersized bound rejects valid cold installs, while an unbounded or over-broad change can hide stalled installers."
files:
  - path: scripts/release_install_metadata_smoke.py
    change: "Let the existing default subprocess owner give only recognized dependency-install commands a larger explicit finite bound while retaining the ordinary-probe timeout and installer-specific fail-closed diagnostics."
  - path: tests/test_release_install_metadata_smoke.py
    change: "Prove the four existing dependency-install command shapes use the install bound, ordinary probes retain their current bound, explicit CLI overrides win, and an exceeded install fails closed."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable scorecard after the focused test changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable scorecard from the same canonical generator."
acceptance:
  - id: AC-1
    when: "the standalone installed smoke or release readiness receives one exact candidate wheel in aggregate release/CI mode"
    then: "it runs venv, bootstrap-venv, pipx, and uv-tool exactly once in canonical order, and unavailable required tooling fails with one concrete recovery command"
  - id: AC-2
    when: "each installed contour executes its post-install probes"
    then: "the probes run from a neutral directory with disposable HOME, XDG, and cache state, prove interpreter, package, and absolute-console provenance, and invoke no ambient mempalace-code executable, AI client, credential, keychain, provider, or publication surface"
  - id: AC-3
    when: "the absolute installed console runs update apply, scheduler install, and scheduler remove without --yes, then runs version-check --check-now with MEMPALACE_VERSION_CHECK=0"
    then: "each update action exits 2 with exactly one JSON recovery object and no state mutation, while version-check exits 2 before any socket attempt after a positively marked interpreter-site guard loads"
  - id: AC-4
    when: "release_readiness_gate --check and the installed-application CI job qualify a candidate"
    then: "both use the shared installer enumeration and installed probe implementation, with no venv-only readiness call or workflow-owned installer loop"
  - id: AC-5
    when: "the exact candidate tree runs the configured release-readiness, installed-smoke, golden CLI, workflow, documentation-drift, public-safety, Ruff, Pyright, scorecard, and full non-network checks"
    then: "all commands exit successfully and readiness emits passing evidence for every installed contour"
  - id: AC-6
    when: 'python scripts/release_readiness_gate.py --check --candidate-sha "$(git rev-parse HEAD)" --json runs from cold disposable cache state, or a dependency install exceeds its explicit bound'
    then: "the cold candidate passes all four installer contours, while the over-bound install fails closed with its installer name and timeout detail"
out_of_scope:
  - "Changing the landed installer enumeration, recovery probes, socket guard, runtime update, scheduler, version-check, model, storage, or network behavior."
  - "Adding a timeout framework, CLI option, installer, cache service, dependency, release gate, provider-client gate, or production network seam."
  - "Executing external AI clients, authentication commands, credentials, keychains, provider APIs, publication, or remote mutation."
  - "Changing package versions, release commands, public documentation, backlog metadata, release status, tags, commits, pushes, or publication state."
contract_policy:
  flow: full_spdd
  reason: "A strict pre-release pipeline repair changes the finite execution boundary used to admit exact wheels through four supported installers."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The landed canonical smoke must continue to qualify one exact wheel through all four supported installers and fail closed when required tooling is absent."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Every contour must retain isolated state and installed interpreter, package, and console provenance."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Every contour must retain the three update refusal proofs and the installed-interpreter version-check socket-denial proof."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Standalone readiness and hosted CI must continue to delegate installer iteration and installed probes to the same owner."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The named release, workflow, safety, quality, and non-network regression contours must remain green against the candidate tree."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Cold dependency installs must receive a larger explicit finite bound, while exceeding that bound still identifies the installer and timeout."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Canonical installed-wheel smoke timeout boundary"
      kind: internal
      paths: ["scripts/release_install_metadata_smoke.py"]
      expected_behavior: "Use the existing subprocess seam to distinguish bounded dependency installation from ordinary probes across venv, bootstrap-venv, pipx, and uv-tool."
    - name: "Generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "Remain byte-current with the existing quality_scorecard.py generator after focused test metrics change."
  invariants:
    - id: INV-1
      statement: "INSTALLERS and run_all_installers_smoke remain the sole ordered installer enumeration and aggregate owner."
      applies_to: ["scripts/release_install_metadata_smoke.py"]
    - id: INV-2
      statement: "Only pip, pipx, and uv dependency-install commands recognized by the existing default subprocess owner receive the longer install bound; environment creation and every installed probe retain DEFAULT_TIMEOUT_SECONDS."
      applies_to: ["scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py"]
    - id: INV-3
      statement: "An exceeded bound remains a return-code-124 failure with sanitized finite timeout detail that the existing per-installer and aggregate diagnostics preserve."
      applies_to: ["scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py"]
    - id: INV-4
      statement: "The existing --timeout-seconds operator control, single-installer mode, exact-wheel provenance, isolated state, recovery JSON, and socket-denial contracts remain compatible."
      applies_to: ["scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py"]
    - id: INV-5
      statement: "Readiness, workflow, gate inventory, runtime modules, package metadata, dependencies, public docs, and release/publication state remain unchanged."
      applies_to: ["scripts/release_install_metadata_smoke.py"]
  risks:
    - id: RISK-1
      risk: "A global timeout increase could let ordinary probes stall longer and weaken failure detection."
      mitigation: "Introduce one install-specific constant and classify only the existing pip, pipx, and uv dependency-install command shapes in the default subprocess owner."
    - id: RISK-2
      risk: "A timeout seam change could make mocks pass while the real subprocess still uses the old bound."
      mitigation: "Test the effective timeout used by _default_run_subprocess for all four install command shapes, an ordinary probe, and an explicit override."
    - id: RISK-3
      risk: "The aggregate could lose the installer identity when an install times out."
      mitigation: "Drive a bounded timeout through the existing aggregate result path and assert installer-prefixed timeout diagnostics."
    - id: RISK-4
      risk: "Changing callable signatures could break existing single-installer test seams or --timeout-seconds behavior."
      mitigation: "Keep injected runner calls unchanged; classify only inside _default_run_subprocess and preserve the existing explicit --timeout-seconds override."
  verification:
    - id: VER-1
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
      proves: "With CANDIDATE_SHA bound to the current HEAD, the canonical readiness owner builds the exact candidate and emits passing evidence only after all four cold-capable installer contours and installed safety probes complete."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-2
      owner: configured_runner
      command: "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json"
      proves: "The canonical aggregate installed smoke exercises all four installers, isolated provenance, guarded update recovery, and version-check socket denial through one owner."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-6]
    - id: VER-3
      owner: configured_runner
      command: "python -m pytest tests/test_release_install_metadata_smoke.py -q"
      proves: "The focused owner proves installer-specific timeout selection, unchanged ordinary-probe timing, timeout fail-closed diagnostics, and the retained four-installer safety contracts."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-6]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The canonical release command and declared aggregate installed-smoke coverage remain synchronized without documentation changes."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "Changed script, test, plan, and generated scorecard surfaces contain no private or credential-shaped material."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The generated scorecard pair is current after focused timeout regression changes."
      acceptance_ids: [AC-5]
    - id: VER-7
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured Ruff lint gate accepts the changed release smoke and tests."
      acceptance_ids: [AC-5]
    - id: VER-8
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured Ruff format gate accepts the changed release smoke and tests."
      acceptance_ids: [AC-5]
    - id: VER-9
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts the default subprocess timeout classification without changing injected runner signatures."
      acceptance_ids: [AC-5]
    - id: VER-10
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite preserves golden CLI, workflow, readiness, installed smoke, documentation, and runtime behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical full non-network regression gate remains green after the timeout-boundary repair."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/quality_scorecard.py --check"
        proves: "Generated quality metrics remain synchronized with the changed focused tests."
        acceptance_ids: [AC-5]
---

## Design Notes

- Current HEAD already contains the shared four-installer owner, readiness and CI delegation, isolated provenance checks, three update refusal probes, installed-interpreter sitecustomize socket guard, public release documentation, and focused regression coverage. Preserve those landed owners; this plan repairs only the exact-head cold-install timeout recorded on 2026-08-24.
- Keep every injected subprocess call signature unchanged. Define one clearly named install-only finite bound greater than the current 300-second ordinary bound and classify only the existing pip, pipx, and uv dependency-install command shapes inside _default_run_subprocess.
- Keep venv creation, executable discovery, metadata/module, CLI, alias, Agent Plugin/MCP, no-ChromaDB, recovery-refusal, site-packages discovery, and version-check probes on DEFAULT_TIMEOUT_SECONDS.
- Preserve --timeout-seconds as the existing explicit override for every subprocess. The install-specific bound is the default only when the operator does not provide that option; add no new CLI option or configuration layer.
- Reuse _default_run_subprocess for timeout conversion. A subprocess.TimeoutExpired must still become return code 124 with sanitized text naming the invoked installer executable and the finite number of seconds. Let the existing installer result and aggregate prefix add the canonical installer name.
- Extend tests/test_release_install_metadata_smoke.py in place. Assert the actual default runner selects the install-only bound for all four dependency-install shapes, retains the ordinary bound for a probe, honors an explicit override, and converts an exceeded install into a fail-closed installer result without changing injected runner signatures.
- Regenerate only docs/quality/scorecard.md and docs/quality/scorecard.json with python scripts/quality_scorecard.py --write because the generator counts test functions and test lines.
- Command context basis: all commands run from the repository root. scripts/gate_inventory.py owns the exact configured readiness, aggregate install-smoke, docs-drift, public-safety, Ruff, format, Pyright, scorecard, and full non-network commands. The configured runner binds CANDIDATE_SHA to the current HEAD before VER-1; AC-6 records the equivalent direct operator command.
- docs/quality/incident-class-registry.yaml is absent in this worktree, so no top-level incident_proof block is admitted.
- PLAN did not execute tests, builds, release gates, verification wrappers, or generated-artifact validation.
