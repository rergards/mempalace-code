---
slug: REL-PY314-HOSTED-MATRIX-FAILURE
status: active
authority: non_authoritative
goal: "Align installed-golden public-export evidence with the existing one-shot root launcher while preserving the 26-row release contour."
risk: medium
risk_note: "The change is test-only release evidence, but an over-permissive binding parser could admit a stale or malformed wheel and an over-broad edit could disturb release-blocking installed qualification."
files:
  - path: scripts/release_readiness_gate.py
    change: "Rename the installed root binding to root_main_is_one_shot_main, probe root.main against cli._one_shot_main, and require the exact four-binding document while preserving all surrounding evidence guards."
  - path: tests/test_release_readiness_gate.py
    change: "Update the installed public-export fixture and add exact positive and hostile binding cases for the one-shot root owner and the three unchanged MCP owners."
  - path: docs/quality/scorecard.md
    change: "Regenerate the deterministic human-readable scorecard after focused test-line metrics change."
  - path: docs/quality/scorecard.json
    change: "Regenerate the deterministic machine-readable scorecard after focused test-line metrics change."
acceptance:
  - id: AC-1
    when: "the installed public-export probe and parser receive the exact root_main_is_one_shot_main binding plus the three canonical MCP bindings, and then receive stale-key, false, missing, extra, or changed-MCP variants"
    then: "the exact document is accepted and every hostile variant is rejected as an owner-binding failure"
  - id: AC-2
    when: "the focused release-readiness positive, parser-hostile, provenance, export-reconciliation, and evidence-reconciliation cases run"
    then: "they prove the exact one-shot root owner contract through injected documents while retaining the existing runtime implementation as the sole behavior owner"
  - id: AC-3
    when: "a fresh exact wheel is installed with the supported optional extras and the installed-golden command runs from its protected credential-free offline contour"
    then: "all 26 direct rows pass with exact public exports, CLI inventory, MCP semantics, installed provenance, protected-root isolation, zero network attempts, and immutable source model-cache state"
  - id: AC-4
    when: "the complete macOS and fresh Linux offline suites and the configured static, type, scorecard, architecture, documentation, inventory, public-safety, changed-range secret, artifact, and dependency-report gates run at one exact candidate SHA"
    then: "every required command exits successfully and reports evidence for that same candidate"
out_of_scope:
  - "Changing mempalace_code runtime files, cli.main, cli._one_shot_main, root exports, CLI lifetime, or shutdown behavior."
  - "Changing optional dependency ranges, installer smoke, workflow topology, hosted matrix versions, timeout or retry policy, or the 26-row gate inventory."
  - "Changing installed provenance, output bounds, sanitization, credential filtering, network denial, protected-root isolation, model-cache handling, MCP ownership, or export reconciliation beyond the stale root binding name and predicate."
  - "Editing backlog metadata, provider routing, external AI-client behavior, publication, tags, pushes, or unrelated release work."
contract_policy:
  flow: full_spdd
  reason: "Standard pre-release evidence correction affects a release-blocking exact-wheel gate with strict provenance, isolation, and fail-closed contracts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Installed public-export evidence must identify root.main as cli._one_shot_main and retain the three exact MCP bindings."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Focused tests must accept only the exact new binding document and reject stale, false, missing, extra, provenance-invalid, export-invalid, or reconciliation-invalid evidence."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-3
      statement: "The fresh exact-wheel installed-golden contour must retain all 26 rows and every existing provenance, isolation, offline, and immutability guarantee."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The complete cross-platform offline and configured release-quality evidence must pass at one exact candidate SHA."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "installed public-export evidence owner"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Emit and parse one exact root_main_is_one_shot_main binding alongside the three unchanged MCP bindings before installed export reconciliation."
  invariants:
    - id: INV-1
      statement: "mempalace_code.__getattr__ remains the sole root-launcher owner and continues returning cli._one_shot_main."
      applies_to: ["mempalace_code/__init__.py", "mempalace_code/cli.py"]
    - id: INV-2
      statement: "The three MCP binding predicates, installed owner/export reconciliation, owner and member limits, provenance constraints, and malformed-document rejection remain exact and fail closed."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "The exact-wheel gate retains 26 rows, optional-extra coverage, CLI inventory attribution, MCP semantics, absolute installed provenance, neutral cwd, protected-root isolation, no-network enforcement, bounded sanitization, and source model-cache immutability."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-4
      statement: "Qualification remains credential-free and performs no external AI-client execution, authentication, publication, tag, push, or remote mutation."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "Accepting both the stale and current root binding keys could hide future launcher-owner drift."
      mitigation: "Require exact bindings-key equality and add separate stale, missing, extra, and false hostile documents."
    - id: RISK-2
      risk: "Updating only the positive fixture could leave MCP or reconciliation regressions undetected."
      mitigation: "Keep all three MCP predicates exact and exercise changed-MCP, owner/export, provenance, and direct-evidence hostile paths in the focused test owner."
    - id: RISK-3
      risk: "A narrow evidence repair could accidentally alter the installed-golden row count or isolation contour."
      mitigation: "Limit production-side edits to the existing probe and parser literals, then run the exact-wheel gate and complete configured regression/release gates."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py -q"
      proves: "The complete focused readiness contract accepts the one-shot root owner, rejects every hostile binding and reconciliation shape, and preserves orchestration, bounds, sanitization, and the 26-row fixture."
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "One fresh exact wheel produces 26 of 26 installed-golden PASS rows under the existing optional-extra, provenance, CLI, MCP, protected-root, offline, and immutable-cache contour."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured complete offline suite passes on the macOS candidate and each fresh Linux Python 3.11-3.14 matrix environment at the same exact SHA."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-4
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the bounded evidence and contract changes."
      acceptance_ids: [AC-4]
    - id: VER-5
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the bounded evidence and contract changes."
      acceptance_ids: [AC-4]
    - id: VER-6
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured base type gate accepts the release-readiness evidence path."
      acceptance_ids: [AC-4]
    - id: VER-7
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict type slice remains green."
      acceptance_ids: [AC-4]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The committed deterministic scorecard matches the changed focused-test metrics."
      acceptance_ids: [AC-4]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/architecture_guard.py --root ."
      proves: "The correction adds no runtime owner, service, store, module boundary, or public surface."
      acceptance_ids: [AC-2, AC-4]
    - id: VER-10
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Tracked release commands and Python support declarations remain synchronized."
      acceptance_ids: [AC-4]
    - id: VER-11
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The existing installed-golden command and 26-row gate topology remain canonical and unchanged."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-12
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The planned release evidence and generated scorecard changes contain no private or credential-shaped material."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-13
      owner: configured_runner
      command: "python scripts/gitleaks_scan.py changed-range --base-ref BASE --head-ref HEAD"
      proves: "The exact candidate range contains no maintained secret signature or entropy finding."
      acceptance_ids: [AC-4]
    - id: VER-14
      owner: configured_runner
      command: "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist"
      proves: "The candidate wheel and sdist retain the expected public package members after the evidence-only correction."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-15
      owner: configured_runner
      command: "python scripts/dependency_upgrade_gate.py ci-check --base-ref origin/main"
      proves: "The candidate retains a successful dependency report matching the current dependency contract."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical offline regression suite preserves runtime CLI, MCP, export, shutdown, storage, and unrelated behavior while the installed evidence binding changes."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Rule Zero selects the existing `INSTALLED_EXPORT_PROBE` and `_parse_installed_public_exports` owner in `scripts/release_readiness_gate.py`. Runtime already exposes `root.main` through `mempalace_code.__getattr__` as `cli._one_shot_main`; reverting runtime, adding an adapter, or creating a second evidence owner would increase complexity and violate the supplied boundary.
- Change the probe predicate and parser key together from `root_main_is_cli_main` to `root_main_is_one_shot_main`. Require `root.main is cli._one_shot_main`; do not accept an alias, fallback key, or either binding name conditionally.
- Preserve exact dictionary equality for all four bindings. This single guard rejects the stale key, missing or extra keys, false values, and changes to any MCP binding before owner/export parsing.
- Reshape the existing malformed-document fixture into explicit hostile cases where needed so each decision-changing variant is independently observable: stale root key, current root value false, missing root binding, extra binding, and each changed MCP binding. Retain malformed JSON, owner-count, duplicate owner, checkout provenance, duplicated export, output-limit, extras, and direct-evidence reconciliation cases.
- Keep the runtime modules untouched. Tests construct probe-shaped JSON and call the parser/reconciliation seams; they must not copy `__getattr__`, `_one_shot_main`, or MCP dispatch implementation.
- Preserve `INSTALLED_EXPORT_OUTPUT_LIMIT`, owner/member limits and token rules, candidate-venv provenance, repository exclusion, `INSTALLED_PUBLIC_EXPORTS`, optional-extra reconciliation, evidence-key equality, CLI inventory discovery/attribution, all 26 direct rows, environment filtering, network guard, protected-root snapshots, timeouts, failure sanitization, and model-cache post-state.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with the existing deterministic generator after the focused test file changes. No other documentation or generated artifact is required.
- Reuse ledger: public root launch behavior is complete in `mempalace_code.__getattr__`; installed evidence is stale in `INSTALLED_EXPORT_PROBE` and `_parse_installed_public_exports`; focused contracts already live in `test_installed_optional_extras_exclude_retired_chroma`. Action: extend the existing evidence and test owners, preserve runtime and all sibling gate owners.
- Cheapest decisive falsifier: VER-1 fails if either the stale key remains accepted, the one-shot binding is false or absent, an extra binding is admitted, any MCP binding changes, or export/provenance reconciliation weakens.
- Command context basis: `pyproject.toml` declares Python 3.11-3.14 support and repository-root pytest/Ruff/Pyright tooling; `.claude/skills/verify/INSTRUCTIONS.md`, `scripts/gate_inventory.py`, `.github/workflows/ci.yml`, and `docs/RELEASING.md` expose the exact configured offline, static, scorecard, artifact, installed-golden, and hosted matrix commands. PLAN inspected those declarations and did not execute them.
- No `docs/quality/incident-class-registry.yaml` exists in this tree. This plan corrects stale release evidence without changing runtime behavior or routing/profile state, so no top-level `incident_proof` block applies.
- Rollback is the direct reversal of the four planned files. There is no runtime migration, state repair, compatibility period, dependency change, workflow rollout, or public API delta.
- PLAN does not run tests, builds, release gates, validation wrappers, exact-wheel qualification, generated-artifact checks, external AI clients, Git finalization, source verification, or publication.
