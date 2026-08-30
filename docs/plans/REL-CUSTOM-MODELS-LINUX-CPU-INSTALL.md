---
slug: REL-CUSTOM-MODELS-LINUX-CPU-INSTALL
goal: "Make Linux custom-model installation use the official CPU PyTorch contour and return bounded ENOSPC recovery from the existing exact-wheel gate."
risk: medium
risk_note: "The change stays inside the existing optional-extra qualification owner, but incorrect platform selection or failure classification could reintroduce multi-gigabyte accelerator resolution or hide a release-blocking install error."
files:
  - path: scripts/release_readiness_gate.py
    change: "Extend the existing optional-extra installer with the Linux CPU PyTorch prerequisite, TMPDIR-aware bounded diagnostics, and one ENOSPC retry while preserving the macOS and default-install contours."
  - path: tests/test_release_readiness_gate.py
    change: "Cover Linux CPU-index command ordering, unchanged macOS installation, decisive generic failures, ENOSPC recovery, output bounds, and private-path redaction through the installed-golden owner."
  - path: docs/AGENT_INSTALL.md
    change: "Document the canonical Linux CPU-only custom-model prerequisite, private spacious TMPDIR setup, install sequence, current-status interpretation, and exact recovery command."
  - path: docs/RELEASING.md
    change: "Document how the exact-wheel owner qualifies the Linux CPU-only custom-model contour and how an operator retries an ENOSPC failure from an owned spacious TMPDIR."
  - path: tests/test_docs_drift_guard.py
    change: "Bind both public documents to the same CPU wheel index, ordered custom-model install contour, scratch-space guidance, and recovery command."
  - path: docs/quality/scorecard.md
    change: "Regenerate the canonical human-readable quality scorecard after focused regression coverage changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the canonical machine-readable quality scorecard from the same generator."
acceptance:
  - id: AC-1
    when: "the public custom-model and release documentation drift checks inspect the Linux installation contour"
    then: "both surfaces name the official PyTorch CPU wheel index, an owner-private spacious TMPDIR, the CPU prerequisite before mempalace-code[custom-models], and one exact recovery command"
  - id: AC-2
    when: "the exact-wheel optional-extra qualification runs with Linux and Darwin platform seams"
    then: "Linux installs PyTorch from the official CPU index before the candidate custom-model extra, while Darwin retains its existing direct extra installation and the default dependency graph is untouched"
  - id: AC-3
    when: "an optional-extra pip subprocess fails generically or with Errno 28 and includes long output plus disposable or private absolute paths"
    then: "the installed-golden JSON reports the failing stage and decisive sanitized bounded diagnostic; Errno 28 reports current status and exactly one TMPDIR-qualified retry command"
  - id: AC-4
    when: "the focused release-readiness and documentation regression command runs"
    then: "CPU-contour selection, ENOSPC recovery, output bounds, private-path redaction, and documentation synchronization all pass"
  - id: AC-5
    when: "the same rebuilt wheel is qualified with the canonical installed-golden command on macOS and Ubuntu 24.04 ARM64 and the canonical install-metadata smoke inspects the ordinary package"
    then: "both exact-wheel runs pass, and the ordinary dependency graph excludes Torch, CUDA, NVIDIA, Triton, and Chroma"
  - id: AC-6
    when: "the existing documentation, public-safety, artifact, static, scorecard, inventory, and full non-network commands run against the implementation"
    then: "all existing gates pass with the same installed-golden command and no added gate, workflow, mode, or release owner"
out_of_scope:
  - "Changing the default FastEmbed/ONNX dependencies, custom-model package metadata, uv.lock, supported embedding models, or model-quality gates."
  - "Adding a second installer, release gate, CI job, service, mode, dependency resolver, persisted state owner, or public API."
  - "Changing macOS custom-model resolution beyond regression coverage, or adding CUDA, GPU, or accelerator installation support."
  - "Editing backlog metadata or performing builds, installs, staging, commits, pushes, tags, publication, remote mutation, credential access, authentication, or external AI-client execution."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release bug changes a release-blocking package-install subprocess and its recovery contract across Linux and macOS."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Canonical public guidance must prescribe the official Linux CPU PyTorch prerequisite and owned spacious TMPDIR recovery before the custom-model extra."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The existing exact-wheel owner must enforce the Linux CPU contour without changing Darwin or the default dependency graph."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Optional-extra failures must retain bounded decisive diagnostics, and ENOSPC must return current status plus one exact retry."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Focused automated regressions must cover platform selection, ENOSPC recovery, output bounds, and path redaction."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "One rebuilt wheel must pass exact-wheel qualification on macOS and Ubuntu ARM64 while the ordinary graph remains free of accelerator and retired-backend packages."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Existing documentation, public-safety, artifact, static, and non-network owners must accept the change without a new gate."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "installed-golden optional-extra installation"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "On Linux, preinstall CPU-only PyTorch from the official index before qualifying the candidate custom-model extra; on failure, return one bounded public-safe result through the existing aggregate row."
    - name: "public custom-model installation guidance"
      kind: internal
      paths: ["docs/AGENT_INSTALL.md"]
      expected_behavior: "Give Linux users one ordered CPU-only installation contour and one exact owned-TMPDIR recovery action."
    - name: "release custom-model qualification guidance"
      kind: internal
      paths: ["docs/RELEASING.md"]
      expected_behavior: "Bind release operators to the same CPU prerequisite and TMPDIR recovery used by the existing exact-wheel owner."
    - name: "generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "Remain current after the focused test additions."
  invariants:
    - id: INV-1
      statement: "scripts/release_readiness_gate.py remains the only exact-wheel and optional-extra qualification owner; the canonical installed-golden command and gate inventory row do not change."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "pyproject.toml and uv.lock remain unchanged, and the ordinary installation continues to exclude Torch, CUDA, NVIDIA, Triton, and Chroma."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "Darwin keeps the current direct candidate-wheel custom-model extra installation and all other optional-extra contours retain their commands, isolation, socket denial, and evidence reconciliation."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-4
      statement: "Failure output remains credential-free, path-sanitized, whitespace-normalized, capped by the existing row limit, and contains exactly one recovery command."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-5
      statement: "No external AI client, authentication, credential access, network service, publication action, CI job, or second release gate is introduced."
      applies_to: ["scripts/release_readiness_gate.py", "docs/AGENT_INSTALL.md", "docs/RELEASING.md"]
  risks:
    - id: RISK-1
      risk: "The candidate extra could still resolve a second accelerator-enabled Torch after the CPU prerequisite."
      mitigation: "Install the prerequisite in the same Linux contour before the candidate extra and assert command order, official index selection, and installed behavior through the existing reconciliation path."
    - id: RISK-2
      risk: "Platform detection could apply Linux-only commands to Darwin or bypass the CPU contour on ARM64 aliases."
      mitigation: "Pass the existing explicit platform seam into optional-extra reconciliation and test Linux plus Darwin boundaries without changing public CLI arguments."
    - id: RISK-3
      risk: "Raw pip output could expose private paths or become too large, while nested recovery handling could emit two retry commands."
      mitigation: "Select only stderr-or-stdout decisive output, reuse the existing sanitizer and row cap, redact protected roots before row construction, and let one failure formatter own recovery selection."
    - id: RISK-4
      risk: "Documentation could drift from executable command ordering or generated scorecards could become stale after tests change."
      mitigation: "Assert shared command tokens and order in the existing docs drift owner, then regenerate both scorecards with their canonical writer."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_custom_models_platform_contours tests/test_release_readiness_gate.py::test_installed_custom_models_install_failure_is_bounded_and_sanitized tests/test_release_readiness_gate.py::test_installed_custom_models_enospc_has_one_owned_tmpdir_retry tests/test_docs_drift_guard.py::test_custom_models_linux_cpu_install_and_recovery_contract -q"
      proves: "The focused behavior owner covers Linux CPU command order, Darwin preservation, generic diagnostics, ENOSPC current status, one retry, bounds, redaction, and synchronized public guidance."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "Using the same rebuilt wheel digest on macOS and Ubuntu 24.04 ARM64 proves the existing exact-wheel gate executes the platform-appropriate optional-extra contour and returns a complete installed_golden_suite PASS."
      acceptance_ids: [AC-2, AC-3, AC-5, AC-6]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json"
      proves: "The canonical ordinary-install smoke preserves the default graph and rejects Torch, CUDA, NVIDIA, Triton, and Chroma."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Canonical custom-model and release instructions remain synchronized with the executable CPU index, command ordering, scratch-space, and recovery contract."
      acceptance_ids: [AC-1, AC-4, AC-6]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "Public documents, diagnostics, and tests contain no private path, credential-shaped value, local-only incident artifact, or unsafe recovery content."
      acceptance_ids: [AC-3, AC-6]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist"
      proves: "The rebuilt wheel and sdist retain the admitted artifact shape after the release-gate-only change."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The canonical installed-golden command and release gate inventory remain unchanged and no second gate is added."
      acceptance_ids: [AC-6]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The canonical scorecard pair matches the implementation tree after regression-test additions."
      acceptance_ids: [AC-4, AC-6]
    - id: VER-9
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the bounded same-owner implementation and tests."
      acceptance_ids: [AC-4, AC-6]
    - id: VER-10
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the source and focused regressions."
      acceptance_ids: [AC-4, AC-6]
    - id: VER-11
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts platform propagation and structured subprocess failure handling."
      acceptance_ids: [AC-2, AC-3, AC-6]
    - id: VER-12
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict type slice remains green."
      acceptance_ids: [AC-6]
    - id: VER-13
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite preserves optional extras, release qualification, dependency boundaries, documentation contracts, and unrelated behavior."
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves all optional-extra, installed-wheel, documentation, and default-runtime behavior."
        acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "No gate command, inventory row, CI owner, or release surface is duplicated."
        acceptance_ids: [AC-6]
---

## Design Notes

- Rule Zero selects `scripts/release_readiness_gate.py::_run_installed_extra_and_export_reconciliation`, which already owns discovery, isolated venv creation, optional-extra installation, direct behavior probes, socket denial, evidence reconciliation, sanitization, and cleanup. Extend its nested install path and pass the existing `platform_name` seam from `_run_installed_golden_wheel`; add no module, installer, workflow, dependency, or gate.
- On Linux only, run `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu` inside the same per-extra venv and credential-free setup environment before `python -m pip install <exact-wheel>[custom-models]`. Keep the candidate extra command authoritative for Sentence Transformers and package provenance. Do not add Torch to project metadata or lock ownership.
- Preserve the current direct `wheel[custom-models]` command on Darwin. Treat `aarch64` and `arm64` as ordinary Linux values under the Linux branch; do not introduce an architecture-specific dependency table or GPU branch.
- Use one small same-file failure formatter for optional-extra install stages. Record the stable stage, subprocess exit status, and the decisive non-empty stderr-or-stdout payload. Replace protected roots before passing the detail to `_make_row`; reuse the shared sanitizer and `_DETAIL_LIMIT` rather than creating a second redaction or truncation policy.
- Classify ENOSPC from `errno.ENOSPC`, `Errno 28`, or the stable `No space left on device` diagnostic. Its result states whether CPU prerequisite or candidate-extra installation failed and emits exactly one retry: `TMPDIR="$HOME/.cache/mempalace/tmp" python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json`. Ensure the caller does not append the ordinary rerun when the specialized recovery is present. Other install failures retain one canonical installed-golden rerun.
- In both public documents, create the private scratch directory first with `install -d -m 700 "$HOME/.cache/mempalace/tmp"`, state that the operator must verify adequate free space on that filesystem, then run the CPU-index prerequisite before `mempalace-code[custom-models]` with the same TMPDIR. Keep a single-line exact recovery command so a stale-context operator repeats the entire safe contour.
- Extend the existing orchestration tests through injected subprocess results. Assert exact command order and index URL on Linux; assert no prerequisite command and the unchanged direct extra command on Darwin; inject long ENOSPC and generic stderr containing `/home/...`, `/tmp/...`, and disposable test roots; require stage/status evidence, no raw path, bounded detail, and exactly one recovery command.
- Keep `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`, `scripts/gate_inventory.py`, the aggregate row ID, and all non-custom optional-extra commands unchanged. The same candidate wheel digest must be used for the macOS and Ubuntu 24.04 ARM64 VER-2 receipts; a receipt from only one host does not satisfy AC-5.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` if the canonical writer reports changed test metrics. Retain no wheel, venv, TMPDIR, palace, cache, or smoke artifact.
- Cheapest decisive falsifier: VER-1 must show that Linux executes the official CPU prerequisite before the exact-wheel extra, Darwin does not, and injected ENOSPC produces one redacted bounded row with the exact TMPDIR retry. Any accelerator index, duplicate retry, raw absolute path, generic-only failure, metadata edit, or second gate fails before cross-platform wheel qualification.
- Command context basis: `pyproject.toml` declares Python 3.11+, pytest, Ruff, Pyright, and the current `sentence-transformers` custom-model extra; `scripts/gate_inventory.py` and `.claude/skills/verify/INSTRUCTIONS.md` provide the exact configured non-network, install-smoke, installed-golden, docs, public, artifact, inventory, scorecard, lint, format, and typecheck command forms. All commands run from the repository root. PLAN inspected these sources and did not execute them.
- Filename discovery found no `docs/quality/incident-class-registry.yaml`; the task changes no listed routing/profile owner, so no registry-matched `incident_proof` block applies.
- PLAN did not run tests, builds, installs, release gates, verification wrappers, scorecard generation, generated-plan validation, source verification, Git finalization, or publication.
