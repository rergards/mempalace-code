---
slug: REL-INSTALLED-GOLDEN-EXACT-WHEEL
status: completed
authority: non_authoritative
goal: "Make the full existing golden CLI suite a mandatory exact-wheel, offline installed-application release gate."
risk: high
risk_note: "Changes release-readiness and required CI admission; weak provenance or cache handling could admit a broken wheel, while a stale cache contract could block releases."
files:
  - path: scripts/release_readiness_gate.py
    change: "Extend the existing readiness owner with one canonical exact-wheel installed-golden contour: validate the pre-existing MiniLM cache, create one disposable venv, install the wheel with the watch extra, install the interpreter-site network guard, prove package metadata/module/executable provenance, and run the complete existing golden suite from a neutral cwd."
  - path: tests/test_release_readiness_gate.py
    change: "Add hermetic seam tests for exact wheel selection, watch-extra installation, credential-free setup, source-conftest exclusion, provenance, full-suite invocation, incomplete cache preflight, network guard setup, subprocess failure propagation, and sanitized recovery output."
  - path: .github/workflows/ci.yml
    change: "Restore the established MiniLM cache fail-closed in installed-application, build one candidate wheel, retain the separate all-installer metadata/recovery smoke, and invoke the readiness-owned installed-golden contour against that wheel so release-required inherits its result."
  - path: tests/test_release_workflow_admission.py
    change: "Strengthen workflow-shape tests so installed-application restores the exact cache contour, runs both the separate manager matrix and shared installed-golden owner, and remains a fail-closed release-required dependency without provider clients or credentials."
  - path: scripts/gate_inventory.py
    change: "Register the readiness-owned installed-golden command as the canonical installed-application behavior gate while retaining the existing all-installer metadata/recovery smoke as a separate command."
  - path: tests/test_gate_inventory.py
    change: "Prove the installed-golden and manager-matrix commands have distinct owners and that the installed-golden command is synchronized to required CI and release documentation."
  - path: docs/RELEASING.md
    change: "Document exact-wheel installed-golden qualification, the watch extra, offline cache precondition and recovery command, provenance evidence, neutral cwd, and the separate four-installer metadata/recovery matrix."
  - path: tests/test_docs_drift_guard.py
    change: "Extend release-document fixtures to require the canonical installed-golden command, cache recovery, and separation from the four-installer smoke."
acceptance:
  - id: AC-1
    when: "the configured release-readiness command builds one candidate wheel with a populated MiniLM cache and emits JSON"
    then: "the complete golden suite runs through the absolute executable installed from that wheel, and passing rows identify matching distribution metadata, an installed module outside the checkout, and the selected executable outside ambient PATH."
  - id: AC-2
    when: "the source-mode golden command and the readiness-owned installed-golden contour execute tests/test_cli_golden_scenarios.py"
    then: "both exercise its existing init, mine, status, search, read, export, import, backup, restore, watcher, failure, and recovery cases without creating or selecting a second scenario suite."
  - id: AC-3
    when: "installed-golden runs with a populated cache, an absent cache, and an empty/stale model cache in focused fixtures"
    then: "the valid case uses disposable HOME/XDG/cache state, a neutral subprocess cwd, offline flags, and a positively loaded interpreter-site socket guard; invalid cache cases stop before venv installation or CLI mutation and return one concrete cache-provisioning recovery command."
  - id: AC-4
    when: "workflow-shape fixtures inspect installed-application and release-required, and readiness fixtures exercise installed-golden failure"
    then: "CI and release_readiness_gate --check delegate to the same installed-golden owner, while failed, skipped, missing, stale, or absent installed-golden evidence prevents release-required success."
  - id: AC-5
    when: "the installed-application workflow and readiness command are inspected by focused tests and public-safety verification"
    then: "they execute no Codex, Claude, Gemini, provider API, auth, keychain, publication, tag, push, GitHub Release, or PyPI upload operation, and the separate four-installer metadata/recovery smoke remains intact."
  - id: AC-6
    when: "the configured source golden, installed smoke, readiness, workflow, docs-drift, public-safety, Ruff, format, Pyright, and full non-network commands run on the candidate"
    then: "each exits successfully and the readiness JSON contains passing exact-wheel installed-golden evidence rather than a skip, stale marker, or source-mode substitution."
out_of_scope:
  - "Creating a second golden scenario suite, application gate, installer framework, embedding provider, cache downloader, model fetch during qualification, or per-installer full golden run."
  - "Changing runtime CLI, storage, embedding-model selection, watcher behavior, or the four-installer metadata/recovery contracts owned by scripts/release_install_metadata_smoke.py."
  - "Implementation-phase edits to docs/BACKLOG.yaml, docs/BACKLOG-archived.yaml, backlog archives, or runner-owned completion metadata; after verification, the runner-owned bookkeep phase may mark and archive this completed task."
  - "Executing external AI clients, authentication commands, credentials, keychains, provider APIs, publication, tags, commits, pushes, GitHub Releases, or PyPI uploads."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release pipeline work changes exact-wheel application qualification, offline cache admission, and required CI behavior."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The full existing golden suite must execute through one exact candidate-wheel executable with metadata, module, and executable provenance."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Installed qualification must reuse every scenario already owned by tests/test_cli_golden_scenarios.py and create no parallel scenario suite."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Installed golden execution must be isolated, offline, network-denied, and fail before application mutation when the pre-existing model cache is unusable."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Readiness and required CI must invoke one installed-golden owner and fail closed on any non-passing or missing result."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Qualification must remain credential-free and non-publishing, while the lightweight all-installer manager matrix remains separate."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Existing release, workflow, documentation, safety, lint, type, and non-network regression gates must remain green."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Release readiness installed-golden owner"
      kind: cli
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Qualify one exact wheel in one disposable watch-capable environment and expose fail-closed JSON rows consumed by --check and required CI."
    - name: "Required installed-application CI"
      kind: internal
      paths: [".github/workflows/ci.yml"]
      expected_behavior: "Restore the established offline MiniLM cache, retain the separate all-installer smoke, invoke the shared installed-golden owner, and feed the complete job result to release-required."
    - name: "Canonical gate inventory"
      kind: internal
      paths: ["scripts/gate_inventory.py"]
      expected_behavior: "Keep installed-golden qualification and all-installer metadata/recovery smoke as distinct canonical commands and detect tracked-surface drift."
    - name: "Release qualification documentation"
      kind: internal
      paths: ["docs/RELEASING.md"]
      expected_behavior: "Name the exact-wheel command, offline cache precondition and recovery, installed provenance, and separate manager matrix."
  invariants:
    - id: INV-1
      statement: "tests/test_cli_golden_scenarios.py remains the sole golden scenario implementation in both source and installed modes."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-2
      statement: "scripts/release_install_metadata_smoke.py remains the sole four-installer metadata/recovery matrix and does not run the full golden suite per installer."
      applies_to: ["scripts/release_install_metadata_smoke.py", "scripts/release_readiness_gate.py", ".github/workflows/ci.yml"]
    - id: INV-3
      statement: "Qualification reads only a pre-existing all-MiniLM-L6-v2 cache; it never fetches a model during the installed-golden run."
      applies_to: ["scripts/release_readiness_gate.py", ".github/workflows/ci.yml"]
    - id: INV-4
      statement: "Release qualification remains credential-free and cannot execute provider clients, auth probes, tags, pushes, publication, GitHub Release creation, or PyPI upload."
      applies_to: ["scripts/release_readiness_gate.py", ".github/workflows/ci.yml"]
    - id: INV-5
      statement: "Source-mode golden tests retain their deterministic fake embedder and existing neutral-directory behavior."
      applies_to: ["tests/test_cli_golden_scenarios.py"]
  risks:
    - id: RISK-1
      risk: "A wheel path or ambient executable could shadow the exact installed candidate."
      mitigation: "Select exactly one wheel, install its watch extra into one disposable venv, invoke the absolute console path, and compare distribution metadata plus module and executable paths against the wheel environment and checkout."
    - id: RISK-2
      risk: "Offline flags alone could permit an unrelated socket path or an empty cache could fail after creating application state."
      mitigation: "Validate the exact MiniLM cache directory before environment setup and install a positively marked socket guard into the candidate interpreter before any golden subprocess runs."
    - id: RISK-3
      risk: "CI and local readiness could drift into separate installed-golden implementations."
      mitigation: "Expose one readiness-owned command, invoke it from both --check and installed-application, and register its exact text in gate_inventory with workflow/docs fixtures."
    - id: RISK-4
      risk: "Adding the full suite to every installer would multiply runtime and blur manager versus application ownership."
      mitigation: "Run full golden once in the canonical exact-wheel venv and preserve the existing four-installer metadata/recovery smoke unchanged."
  verification:
    - id: VER-1
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
      proves: "The canonical readiness owner builds the exact wheel, retains all-installer smoke, and emits passing installed-golden provenance only after the complete offline suite succeeds."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-2
      owner: configured_runner
      command: "python -m pytest tests/test_cli_golden_scenarios.py -q"
      proves: "The unchanged source-mode owner still exercises the complete golden application, watcher, failure, and recovery contract."
      acceptance_ids: [AC-2, AC-6]
    - id: VER-3
      owner: provider
      command: "PYTHONPATH=. pytest tests/test_release_readiness_gate.py -q"
      proves: "Focused readiness seams cover exact-wheel provenance, watch-extra installation, cache preflight, network denial, complete-suite invocation, recovery output, and failure propagation."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-4
      owner: provider
      command: "PYTHONPATH=. pytest tests/test_release_workflow_admission.py tests/test_gate_inventory.py -q"
      proves: "Workflow and inventory fixtures require the shared installed-golden owner, preserve the separate manager matrix, and keep release-required fail closed."
      acceptance_ids: [AC-4, AC-5, AC-6]
    - id: VER-5
      owner: provider
      command: "actionlint .github/workflows/*.yml"
      proves: "The declared dev actionlint dependency accepts the modified required workflow syntax and action inputs."
      acceptance_ids: [AC-3, AC-4, AC-5]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json"
      proves: "The separate canonical venv, bootstrap-venv, pipx, and uv-tool metadata/recovery matrix remains green and independent of the one full golden run."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Release documentation, canonical inventory, and required workflow retain the same installed-golden and manager-matrix command boundaries."
      acceptance_ids: [AC-4, AC-5, AC-6]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "Changed release, workflow, test, and documentation surfaces contain no private, credential-shaped, or provider-auth material."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-9
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the readiness and test changes."
      acceptance_ids: [AC-6]
    - id: VER-10
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the readiness and test changes."
      acceptance_ids: [AC-6]
    - id: VER-11
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts the exact-wheel orchestration and injected subprocess seams."
      acceptance_ids: [AC-6]
    - id: VER-12
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite preserves golden source mode, installed smoke, readiness, workflow, documentation, and runtime behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical full non-network regression gate remains green after installed-golden release admission becomes mandatory."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/docs_drift_guard.py"
        proves: "Canonical release commands remain synchronized across inventory, workflow, and release documentation."
        acceptance_ids: [AC-4, AC-5, AC-6]
---

## Design Notes

- Reuse `tests/test_cli_golden_scenarios.py` unchanged as the scenario owner. The readiness layer supplies only the installed executable, isolated environment, real offline cache, socket denial, and provenance preflight.
- Extend `scripts/release_readiness_gate.py`; add no sibling application-gate script. Give it one bounded installed-golden entrypoint that `run_readiness(... --check)` and the CI job can both call against an explicit wheel.
- Require exactly one wheel and install `<absolute-wheel>[watch]` into one disposable venv. `watch` is the existing supported extra needed by the golden watch-on-save scenario; do not install `dev`, `treesitter`, or every optional extra into the candidate environment.
- Run pytest from the declared repository dev environment while setting `MEMPALACE_TEST_INSTALLED_CLI` to the venv's absolute `mempalace-code` path and `MEMPALACE_TEST_HF_HOME` to the validated cache root. Run from a disposable neutral command cwd; never add the checkout to the installed interpreter's import path.
- Before venv creation or any CLI subprocess, require `MEMPALACE_TEST_HF_HOME` and the established MiniLM snapshot manifest plus one supported weight file. Missing, incomplete, non-directory, or stale model state emits one bounded recovery such as `HF_HOME=<cache-root> mempalace-code fetch-model`, then exits without running install or application commands.
- Create the venv and install the wheel from the same disposable neutral directory with the existing credential-free environment owner. Run the host pytest harness with `--noconftest` so repository fixtures cannot import the checkout or substitute its deterministic embedder.
- Install the existing interpreter-site socket guard pattern into the candidate venv and require its positive marker before the suite. Keep `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `MEMPALACE_VERSION_CHECK=0`, disposable HOME/XDG values, and no forwarded credential variables for every installed-golden subprocess.
- Provenance must compare the explicit wheel identity with `importlib.metadata.version`, `mempalace_code.__file__`, the venv interpreter, and the absolute console executable. Reject checkout-relative modules, ambient PATH executables, metadata mismatch, multiple wheels, missing console, or missing guard marker before reporting a pass.
- Keep `scripts/release_install_metadata_smoke.py --all-installers` as the four-manager metadata/recovery owner. The required job builds once, runs that lightweight matrix, then runs the full suite once through the canonical venv.
- Restore the same MiniLM cache path/key already used by `model-tests`; required installed-application uses a fail-on-miss restore and prints the same provisioning recovery. It must not fetch the model during qualification.
- Keep `installed-application` in `release-required.needs` and require `success` exactly. Workflow fixtures must also reject removal of either the manager-matrix command or installed-golden command from the job.
- Command context basis: `pyproject.toml` declares Python 3.11+, the `watch` extra, pytest, Ruff, Pyright, actionlint, build, and twine; `scripts/gate_inventory.py` owns the exact configured readiness, installed-smoke, source-golden, docs-drift, public-safety, Ruff, format, Pyright, and full non-network commands.
- PLAN did not execute tests, builds, release gates, verification wrappers, or generated-artifact validation.
