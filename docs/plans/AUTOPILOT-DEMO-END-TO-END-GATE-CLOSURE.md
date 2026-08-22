---
slug: AUTOPILOT-DEMO-END-TO-END-GATE-CLOSURE
status: completed
authority: non_authoritative
goal: "Make AUTOPILOT-DEMO quality gates enforce canonical commands, built artifacts, and neutral installed behavior."
risk: high
risk_note: "Touches CI, release gates, package artifacts, installed CLI/MCP smokes, public-safety scanning, Pyright policy, and public evidence; false negatives can publish broken artifacts and false positives can block releases."
files:
  - path: scripts/gate_inventory.py
    change: "Add the tracked canonical quality/release command inventory and a parity checker for CI, local verify docs, release docs, scorecard metadata, and tracked public gate surfaces; report ignored local autopilot.toml drift as evidence only, not as an edited surface."
  - path: tests/test_gate_inventory.py
    change: "Add hermetic tests for missing, stale, duplicated, and mismatched gate rows across Ruff, format, pytest marker selection, basic/strict Pyright, public safety, scorecard, docs drift, architecture, performance, package build, artifact inspection, and installed smoke."
  - path: scripts/quality_scorecard.py
    change: "Consume the canonical inventory for verification command metadata and expose release/artifact/installed-smoke gate coverage without duplicating command strings."
  - path: tests/test_quality_scorecard.py
    change: "Update scorecard tests for the expanded inventory, release/artifact gate metadata, and freshness validation."
  - path: scripts/docs_drift_guard.py
    change: "Validate the expanded canonical command inventory against tracked public docs and skills, including docs drift, performance, package build, artifact inspection, and installed smoke rows."
  - path: tests/test_docs_drift_guard.py
    change: "Add fixtures proving docs drift fails when any expanded canonical command or gate claim is missing or stale."
  - path: scripts/public_safety_scan.py
    change: "Keep tracked, staged, and committed modes fail-closed while avoiding scanner-triggering literal fixtures in committed source and preserving redacted output."
  - path: tests/test_public_safety_scan.py
    change: "Add combined tracked/staged/committed success and failure fixtures that prove secret detection, local-only path rejection, and no committed scanner-triggering literal."
  - path: scripts/release_artifact_gate.py
    change: "Add an artifact member scanner for built wheel and sdist archives that requires both distribution types, rejects local-only control artifacts and caches, and delegates metadata validation to twine check."
  - path: tests/test_release_artifact_gate.py
    change: "Add archive fixture tests for clean wheel/sdist artifacts, .codex-local, .tasks, .protocols, docs/audits, .verify-state, caches, missing wheel, missing sdist, and twine-check failure reporting."
  - path: scripts/release_install_metadata_smoke.py
    change: "Extend install smoke to accept a built wheel, prove module/CLI/MCP import provenance outside the checkout, discover pipx as an external executable including Homebrew paths, and keep isolated venv coverage."
  - path: tests/test_release_install_metadata_smoke.py
    change: "Add mocked tests for wheel install, venv provenance, pipx executable discovery independent of sys.executable, Homebrew path fallback, CLI failure, MCP failure, and sanitized diagnostics."
  - path: scripts/release_readiness_gate.py
    change: "Add one documented release-readiness command that runs the canonical gate inventory, builds artifacts in a controlled output directory, runs twine check, artifact inspection, and installed smoke, then exits nonzero on any failed row."
  - path: tests/test_release_readiness_gate.py
    change: "Add deterministic subprocess-seam tests for all-green readiness, single canonical command failure, artifact inspection failure, install smoke failure, JSON output, and public-safe blocker details."
  - path: .github/workflows/ci.yml
    change: "Align tracked CI jobs with the canonical inventory and route package/artifact/installed-smoke validation through the release readiness or artifact gate commands."
  - path: .github/workflows/publish.yml
    change: "Use the same artifact inspection and readiness boundaries before trusted publishing while preserving tag-only publish semantics."
  - path: .github/PULL_REQUEST_TEMPLATE.md
    change: "Replace stale verification checklist commands with the canonical command inventory or the single release-readiness command."
  - path: .claude/skills/verify/INSTRUCTIONS.md
    change: "Update local verify instructions to name the expanded canonical command inventory and release/artifact gates without claiming ignored autopilot.toml as a tracked surface."
  - path: .claude/skills/release/SKILL.md
    change: "Require the release-readiness command, artifact gate, and installed-smoke provenance evidence before release-ready or shipped wording."
  - path: CLAUDE.md
    change: "Update public-safe project guidance for the expanded verification boundary and built-artifact release readiness command."
  - path: docs/RELEASING.md
    change: "Document the single release-readiness command, artifact inspection, built wheel/sdist smoke, pipx executable discovery, and neutral-directory CLI/MCP provenance checks."
  - path: docs/quality/README.md
    change: "Explain the canonical gate inventory, scorecard coverage, AUTOPILOT-DEMO ledger workflow, and public-safety/artifact boundaries."
  - path: docs/quality/autopilot-demo-gate-ledger.md
    change: "Add a public-safe pass/gap ledger for every archived AUTOPILOT-DEMO item with before/after metrics, exact commands, behavioral evidence, and enforcing gate."
  - path: docs/quality/autopilot-demo-gate-ledger.json
    change: "Add machine-readable ledger data used by tests and scorecard generation."
  - path: docs/quality/scorecard.json
    change: "Regenerate after gate inventory, ledger, and release/artifact metadata changes."
  - path: docs/quality/scorecard.md
    change: "Regenerate alongside scorecard.json."
  - path: pyproject.toml
    change: "Add explicit sdist exclude policy for local-only control artifacts and adjust Pyright/dev metadata only as needed for the declared environment."
  - path: pyrightconfig.strict.json
    change: "Keep strict-slice coverage aligned with the fixed typed surfaces and scorecard metadata."
  - path: mempalace_code/version.py
    change: "Preserve version single-source behavior while supporting installed provenance checks that cannot be shadowed by a checkout pyproject."
  - path: mempalace_code/_chroma_store.py
    change: "Fix optional Chroma typing without changing the runtime ImportError contract when the extra is absent."
  - path: mempalace_code/migrate.py
    change: "Fix optional Chroma migration typing without importing the optional dependency in default installs."
  - path: mempalace_code/watcher.py
    change: "Fix optional watchfiles typing without changing missing-extra diagnostics or watcher behavior."
  - path: mempalace_code/cli.py
    change: "Remove or narrow basic Pyright issues around version-check/update command flow while preserving CLI behavior."
  - path: tests/test_pyright_optional_dependencies.py
    change: "Add focused optional-dependency tests for absent/present Chroma, watchfiles, and spellcheck boundaries that explain why default installs type-check without optional extras."
  - path: tests/test_installed_artifact_behavior.py
    change: "Add built-wheel installed CLI and MCP smoke tests that run from a neutral directory and assert import provenance points at the installed artifact, not the checkout."
  - path: tests/test_autopilot_demo_gate_ledger.py
    change: "Validate the ledger covers every archived AUTOPILOT-DEMO item and that each entry names commands, before/after metrics or gap rationale, behavioral evidence, and enforcing gate."
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_gate_inventory.py -q and python scripts/gate_inventory.py --check are run"
    then: "the canonical inventory and parity checker cover Ruff, formatting, basic and strict Pyright, the intended pytest marker set, public safety, scorecard, docs drift, architecture, performance, package build, artifact inspection, and installed smoke across tracked CI, local verification, scorecard metadata, and release documentation."
  - id: AC-2
    when: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\" and python -m pyright -p pyrightconfig.strict.json are run from the declared dev environment"
    then: "both type checks exit 0 and focused optional-dependency tests document the Chroma/watchfiles/spellcheck handling."
  - id: AC-3
    when: "python scripts/public_safety_scan.py --committed --tracked --staged and python -m pytest tests/test_public_safety_scan.py -q are run"
    then: "all live scan modes pass on the repository, while fixtures still prove redacted secret detection and local-only artifact path rejection without committing a scanner-triggering literal."
  - id: AC-4
    when: "python scripts/release_readiness_gate.py --artifact-only --json and python -m pytest tests/test_release_artifact_gate.py -q are run"
    then: "wheel and sdist artifacts both pass twine check and artifact inspection rejects .codex-local, task state, protocol state, caches, .verify-state, and operator audit residue."
  - id: AC-5
    when: "python -m pytest tests/test_release_install_metadata_smoke.py -q is run"
    then: "the release install smoke covers built-wheel venv installs, discovers a working pipx executable independently of the target Python module set, and includes Homebrew pipx layout fallback."
  - id: AC-6
    when: "python -m pytest tests/test_installed_artifact_behavior.py -q is run"
    then: "installed CLI and MCP smokes run from a neutral directory and prove package/module/entrypoint provenance points to the built artifact rather than the checkout."
  - id: AC-7
    when: "python -m pytest tests/test_autopilot_demo_gate_ledger.py -q is run"
    then: "every archived AUTOPILOT-DEMO item has a public-safe ledger row with exact commands, before/after metrics or explicit gap rationale, behavioral evidence, and the enforcing gate."
  - id: AC-8
    when: "python -m pytest tests/test_release_readiness_gate.py -q and python scripts/release_readiness_gate.py --check --json are run"
    then: "fixture failures prove any canonical gate or artifact check blocks readiness, and the live repository command exits 0 with machine-readable all-green status after remediation."
out_of_scope:
  - "Editing docs/BACKLOG.yaml, docs/BACKLOG-archived.yaml, backlog archives, or runner-owned completion metadata."
  - "Editing, staging, publishing, or force-adding ignored autopilot.toml; it is evidence input only."
  - "Editing CHANGELOG.md; runner finalization owns completion metadata."
  - "Changing package version, creating tags, pushing, publishing to PyPI, creating GitHub Releases, or changing release secrets/environments."
  - "Weakening public-safety scanner token/path detection or allowlisting real private artifacts."
  - "Running network-backed model tests or publishing code-intelligence packet regeneration as part of routine daily CI."
contract_policy:
  flow: full_spdd
  reason: "Strict release/pipeline task crossing verification topology, CI, packaging, installed behavior, public safety, and evidence ledgers."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Tracked gate claims must be derived from one canonical command inventory or fail a parity fitness test when any public surface drifts."
      source: "AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Basic and strict Pyright must pass in the declared dev environment while optional dependencies remain optional at runtime and documented in tests."
      source: "AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Public-safety tracked, staged, and committed modes must pass the repository and still detect secrets/local-only artifacts in fixtures."
      source: "AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Built wheel and sdist artifacts must be inspected directly and must reject local-only control artifacts before release."
      source: "AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Release install smoke must validate built-wheel venv installs and pipx installs through a discovered executable, including Homebrew layouts."
      source: "AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Installed CLI and MCP checks must run outside the checkout and prove import provenance from the installed built artifact."
      source: "AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "Archived AUTOPILOT-DEMO work must have a public-safe evidence ledger with commands, metrics, behavior, and enforcing gates."
      source: "AC-7"
      acceptance_ids: [AC-7]
    - id: REQ-8
      statement: "One documented release-readiness command must fail when any canonical or artifact check fails and pass only after all remediations are green."
      source: "AC-8"
      acceptance_ids: [AC-8]
  surfaces:
    - name: "Canonical gate inventory"
      kind: cli
      paths:
        - "scripts/gate_inventory.py"
        - "tests/test_gate_inventory.py"
        - "scripts/quality_scorecard.py"
        - "scripts/docs_drift_guard.py"
      expected_behavior: "Provide one tracked source for canonical command rows and fail tracked public-surface drift while treating ignored autopilot.toml as read-only evidence."
    - name: "CI and public verification docs"
      kind: internal
      paths:
        - ".github/workflows/ci.yml"
        - ".github/workflows/publish.yml"
        - ".github/PULL_REQUEST_TEMPLATE.md"
        - ".claude/skills/verify/INSTRUCTIONS.md"
        - ".claude/skills/release/SKILL.md"
        - "CLAUDE.md"
        - "docs/RELEASING.md"
        - "docs/quality/README.md"
      expected_behavior: "Repeat or invoke the canonical commands only through tracked public surfaces that the parity checker can validate."
    - name: "Type-check and optional dependencies"
      kind: internal
      paths:
        - "pyproject.toml"
        - "pyrightconfig.strict.json"
        - "mempalace_code/_chroma_store.py"
        - "mempalace_code/migrate.py"
        - "mempalace_code/watcher.py"
        - "mempalace_code/cli.py"
        - "tests/test_pyright_optional_dependencies.py"
      expected_behavior: "Pyright basic and strict checks pass without forcing optional extras into default runtime imports."
    - name: "Public-safety scanner"
      kind: cli
      paths:
        - "scripts/public_safety_scan.py"
        - "tests/test_public_safety_scan.py"
      expected_behavior: "Tracked, staged, and committed scans pass live repository content and continue to reject redacted fixture leaks."
    - name: "Artifact and release readiness gates"
      kind: cli
      paths:
        - "scripts/release_artifact_gate.py"
        - "tests/test_release_artifact_gate.py"
        - "scripts/release_readiness_gate.py"
        - "tests/test_release_readiness_gate.py"
      expected_behavior: "Build, twine, artifact-member inspection, and readiness orchestration fail closed and emit machine-readable blockers."
    - name: "Installed artifact behavior"
      kind: cli
      paths:
        - "scripts/release_install_metadata_smoke.py"
        - "tests/test_release_install_metadata_smoke.py"
        - "tests/test_installed_artifact_behavior.py"
        - "mempalace_code/version.py"
      expected_behavior: "Neutral-directory venv, pipx, CLI, and MCP smokes prove installed artifact provenance and version agreement."
    - name: "AUTOPILOT-DEMO evidence ledger"
      kind: internal
      paths:
        - "docs/quality/autopilot-demo-gate-ledger.md"
        - "docs/quality/autopilot-demo-gate-ledger.json"
        - "tests/test_autopilot_demo_gate_ledger.py"
        - "docs/quality/scorecard.json"
        - "docs/quality/scorecard.md"
      expected_behavior: "Publish a public-safe pass/gap ledger for archived AUTOPILOT-DEMO items and keep scorecard artifacts fresh."
  invariants:
    - id: INV-1
      statement: "Backlog metadata, backlog archives, CHANGELOG.md, and ignored autopilot.toml remain outside implementation scope."
      applies_to:
        - "docs/BACKLOG.yaml"
        - "docs/BACKLOG-archived.yaml"
        - "CHANGELOG.md"
        - "autopilot.toml"
    - id: INV-2
      statement: "Public-safety scanner output must stay redacted and must not print matched secret/token/path content."
      applies_to:
        - "scripts/public_safety_scan.py"
        - "tests/test_public_safety_scan.py"
    - id: INV-3
      statement: "Optional dependencies stay opt-in; default install must not require ChromaDB, watchfiles, autocorrect, or tree-sitter."
      applies_to:
        - "pyproject.toml"
        - "mempalace_code/_chroma_store.py"
        - "mempalace_code/migrate.py"
        - "mempalace_code/watcher.py"
    - id: INV-4
      statement: "Release readiness and status gates remain read-only with respect to remotes, tags, GitHub Releases, PyPI publication, and repository history."
      applies_to:
        - "scripts/release_readiness_gate.py"
        - "scripts/release_artifact_gate.py"
        - "scripts/release_install_metadata_smoke.py"
        - ".github/workflows/publish.yml"
    - id: INV-5
      statement: "Built artifact smokes must execute outside the source checkout and must fail when import provenance points back to the checkout."
      applies_to:
        - "scripts/release_install_metadata_smoke.py"
        - "tests/test_installed_artifact_behavior.py"
    - id: INV-6
      statement: "Scorecard and ledger artifacts remain deterministic, public-safe, and free of timestamps, local absolute paths, tokens, private remotes, and task-local paths."
      applies_to:
        - "scripts/quality_scorecard.py"
        - "docs/quality/autopilot-demo-gate-ledger.md"
        - "docs/quality/autopilot-demo-gate-ledger.json"
        - "docs/quality/scorecard.json"
        - "docs/quality/scorecard.md"
  risks:
    - id: RISK-1
      risk: "Adding another command table could worsen drift instead of closing it."
      mitigation: "Make the new inventory importable by scorecard/docs-drift/readiness code and add fixtures where any stale copy fails."
    - id: RISK-2
      risk: "Release readiness could become slow or flaky by running all gates unconditionally."
      mitigation: "Keep the readiness command deterministic, use temp build output, expose JSON row results, and let CI call it at release/package boundaries rather than every user CLI run."
    - id: RISK-3
      risk: "Artifact inspection could miss local-only files because wheel and sdist layouts differ."
      mitigation: "Inspect archive member names for both wheel and sdist, require both distribution types, and test each forbidden prefix against both formats."
    - id: RISK-4
      risk: "Pipx smoke could accidentally depend on the release script's Python having the pipx module."
      mitigation: "Resolve a pipx executable with PATH plus Homebrew candidates and test that sys.executable -m pipx is not required."
    - id: RISK-5
      risk: "Pyright fixes could import optional packages or weaken runtime missing-extra errors."
      mitigation: "Use TYPE_CHECKING, protocols, or guarded imports and add absent-extra tests for the same runtime error messages."
    - id: RISK-6
      risk: "Ledger work could become historical rewriting."
      mitigation: "Audit archived AUTOPILOT-DEMO rows into a new pass/gap ledger and keep backlog archives unchanged."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_gate_inventory.py -q"
      proves: "Canonical gate inventory covers all required quality/release rows and fails on stale tracked public surfaces."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python scripts/gate_inventory.py --check"
      proves: "The live tracked tree has no canonical command drift across CI, local verify docs, release docs, and scorecard metadata."
      acceptance_ids: [AC-1, AC-8]
    - id: VER-3
      command: "python -m pytest tests/test_pyright_optional_dependencies.py -q"
      proves: "Optional dependency boundaries remain documented and tested while supporting Pyright success."
      acceptance_ids: [AC-2]
    - id: VER-4
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "Configured-runner canonical basic Pyright gate passes from the declared dev environment."
      acceptance_ids: [AC-2]
    - id: VER-5
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "Configured-runner canonical strict Pyright slice passes."
      acceptance_ids: [AC-2]
    - id: VER-6
      command: "python -m pytest tests/test_public_safety_scan.py -q"
      proves: "Public-safety fixtures cover clean and failing tracked/staged/committed modes without committed scanner-triggering literals."
      acceptance_ids: [AC-3]
    - id: VER-7
      command: "python scripts/public_safety_scan.py --committed --tracked --staged"
      proves: "The live repository passes all public-safety source selectors together."
      acceptance_ids: [AC-3]
    - id: VER-8
      command: "python -m pytest tests/test_release_artifact_gate.py -q"
      proves: "Artifact inspection rejects every forbidden local-only member and reports missing wheel/sdist and twine failures."
      acceptance_ids: [AC-4]
    - id: VER-9
      command: "python scripts/release_readiness_gate.py --artifact-only --json"
      proves: "Built wheel and sdist pass build, twine, and artifact member inspection as a runnable release boundary."
      acceptance_ids: [AC-4, AC-8]
    - id: VER-10
      command: "python -m pytest tests/test_release_install_metadata_smoke.py -q"
      proves: "Install smoke covers built-wheel venv installs, pipx executable discovery, Homebrew fallback, failures, and sanitized diagnostics."
      acceptance_ids: [AC-5]
    - id: VER-11
      command: "python -m pytest tests/test_installed_artifact_behavior.py -q"
      proves: "Installed CLI and MCP smokes run from a neutral directory and fail on checkout provenance."
      acceptance_ids: [AC-6]
    - id: VER-12
      command: "python -m pytest tests/test_autopilot_demo_gate_ledger.py -q"
      proves: "The public ledger covers every archived AUTOPILOT-DEMO item with commands, metrics or gap rationale, behavior, and enforcing gate."
      acceptance_ids: [AC-7]
    - id: VER-13
      command: "python -m pytest tests/test_release_readiness_gate.py -q"
      proves: "Readiness orchestration fails when any canonical, artifact, or install-smoke row fails and emits public-safe JSON blockers."
      acceptance_ids: [AC-8]
    - id: VER-14
      command: "python scripts/release_readiness_gate.py --check --json"
      proves: "The live repository passes the single documented release-readiness command after remediation."
      acceptance_ids: [AC-1, AC-4, AC-5, AC-6, AC-8]
    - id: VER-15
      command: "python scripts/quality_scorecard.py --check"
      proves: "Scorecard artifacts are fresh, deterministic, public-safe, and reflect the expanded gates and ledger."
      acceptance_ids: [AC-1, AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "Configured lint gate remains green after scripts, tests, and Pyright fixes."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-2
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "Configured format gate remains green for changed Python surfaces."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-3
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "Configured pytest marker selection covers the complete intended non-network suite after all gate changes."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-4
        command: "python scripts/docs_drift_guard.py"
        proves: "Public docs, skills, release docs, scorecard metadata, and canonical command inventory remain synchronized."
        acceptance_ids: [AC-1, AC-8]
      - id: REG-5
        command: "python scripts/architecture_guard.py --root ."
        proves: "Architecture boundary guard remains part of the canonical release topology and still passes."
        acceptance_ids: [AC-1]
      - id: REG-6
        command: "python benchmarks/demo_perf_budgets.py --check --ci"
        proves: "Performance budgets remain a hard canonical gate and still pass after readiness wiring."
        acceptance_ids: [AC-1]
      - id: REG-7
        command: "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist"
        proves: "The artifact gate remains runnable against an existing built dist directory and enforces wheel/sdist content policy."
        acceptance_ids: [AC-4]
      - id: REG-8
        command: "python scripts/release_install_metadata_smoke.py --install-spec . --json"
        proves: "Checkout install smoke still validates metadata/module/CLI agreement from a neutral directory."
        acceptance_ids: [AC-5, AC-6]
---

## Design Notes

- Command context basis: `pyproject.toml` declares pytest, Pyright, Ruff, and optional extras; `.github/workflows/ci.yml` currently runs separate test, lint, package, typecheck, and performance jobs; `.claude/skills/verify/INSTRUCTIONS.md` is the local verify surface; `scripts/quality_scorecard.py` already owns the current partial verification command table.
- `autopilot.toml` is intentionally excluded from `files`, `touched_files`, and expected implementation edits because the task-local planner constraints mark it as ignored local input. The tracked parity checker should report whether the ignored file is stale when present, but remediation must be through tracked scripts, tests, CI, and public docs.
- Prefer one importable inventory module over copying command tuples between `quality_scorecard.py`, `docs_drift_guard.py`, CI assertions, and release docs. The inventory should preserve exact command strings and stable IDs so scorecard JSON and docs drift tests can compare byte-for-byte.
- The intended pytest command is the non-network suite with the explicit marker expression `not needs_network`. Do not silently narrow it to only the current Autopilot subset or broaden it into network/model-backed tests.
- Artifact inspection should build into a controlled temporary or cleaned output directory and inspect archive member names directly. Wheel and sdist have different layouts, so test forbidden prefixes against both.
- Release install smoke should treat pipx as an external tool executable. Try PATH first, then Homebrew-style `/opt/homebrew/bin/pipx` and `/usr/local/bin/pipx` candidates; do not require `sys.executable -m pipx`.
- Installed provenance evidence should include the interpreter path, console script path, imported module file, distribution metadata location when available, and probe working directory. JSON output must sanitize private paths or replace them with relative/provenance classifications.
- The AUTOPILOT-DEMO ledger is evidence, not backlog rewriting. Read archived AUTOPILOT-DEMO keys to prove coverage, but keep backlog archives unchanged and place public evidence under `docs/quality/`.
- Broad commands in the regression plan are the canonical configured-runner commands after this task lands. Focused pytest rows in verification provide implementer-owned behavior proof for new gates and error paths.
