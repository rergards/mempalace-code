---
slug: RELEASE-DIRECT-INSTALLED-DIARY-BLANK-INPUTS
status: completed
authority: non_authoritative
goal: "Move blank diary required-field refusals into the existing direct exact-wheel installed gate while retaining one thin source-test consumer."
risk: medium
risk_note: "The change is small and test-only at the product boundary, but it modifies the release-blocking exact-wheel qualification path and its fail-closed selector."
files:
  - path: scripts/release_readiness_gate.py
    change: "Add one direct installed diary blank-field scenario to the existing exact-wheel owner and exclude only its thin source consumer from transitional pytest."
  - path: tests/test_release_readiness_gate.py
    change: "Cover the new direct scenario matrix, fail-closed result, environment/provenance arguments, orchestration row, and exact transitional selector clause."
  - path: tests/test_cli_golden_scenarios.py
    change: "Retain the four-case parametrized source consumer while delegating scenario execution and assertions to the release-owned implementation."
acceptance:
  - id: AC-1
    when: "The installed-golden gate receives the exact candidate wheel and a populated offline model cache."
    then: "It invokes the candidate wheel's absolute console executable from a neutral cwd in the existing offline, credential-free, socket-denied environment."
  - id: AC-2
    when: "The direct diary refusal scenario runs its input matrix."
    then: "It exercises empty and whitespace-only values for --agent and --entry twice each while retaining the existing --topic input."
  - id: AC-3
    when: "Any blank diary matrix invocation completes."
    then: "It requires exit code 2, empty stdout, exact option-specific stderr guidance, absent palace post-state after each attempt, bounded public-safe output, and no repository or non-disposable artifacts."
  - id: AC-4
    when: "Source and exact-wheel installed qualification collect the diary blank-field case."
    then: "The parametrized source test remains a thin consumer of the release-owned scenario, and transitional installed pytest excludes exactly that test with no broader selector change."
  - id: AC-5
    when: "Implementation qualification and review complete for this release-gate increment."
    then: "Focused source checks, the full non-network suite, static and public gates, a fresh exact-wheel direct run, and independent Rule Zero, correctness, and security reviews all succeed."
out_of_scope:
  - "Valid diary writes, recovery matrices, non-regular sources, fixture shape, inventory, and Linux hosted behavior."
  - "Product behavior, package interfaces, new runners or scenario frameworks, and changes outside the existing installed-golden owner."
  - "Publication, remote mutation, AI-client invocation, credential access, backlog metadata, and adjacent release scenarios."
contract_policy:
  flow: full_spdd
  reason: "Strict work changes a release-blocking provider pipeline and must preserve exact-wheel provenance, isolation, and fail-closed orchestration."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The existing installed-golden owner directly executes the four blank diary required-field cases twice through the exact candidate console."
      source: "Current backlog contract AC-1 and AC-2"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Every refused invocation proves deterministic streams, exit status, zero palace post-state, bounded output, and disposable containment."
      source: "Current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-3
      statement: "The source parametrization delegates to the release-owned scenario and only that test is added to the transitional installed selector exclusions."
      source: "Current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-4
      statement: "The scoped source, repository, static/public, exact-wheel, and independent review gates complete before admission."
      source: "Current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Direct exact-wheel installed diary refusal scenario"
      kind: internal
      paths: [scripts/release_readiness_gate.py]
      expected_behavior: "Own the repeated four-case diary refusal matrix, return one bounded PASS or fail-closed row, and run before transitional pytest through the exact installed console and existing isolated environment."
  invariants:
    - id: INV-1
      statement: "The diary command's product behavior and valid-write path remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_cli_golden_scenarios.py]
    - id: INV-2
      statement: "The matrix retains the existing empty --topic argument while varying only --agent or --entry and its paired valid value."
      applies_to: [scripts/release_readiness_gate.py, tests/test_cli_golden_scenarios.py]
    - id: INV-3
      statement: "All existing direct installed scenarios and every pre-existing transitional pytest selector clause remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-4
      statement: "The exact-wheel gate remains offline, credential-free, socket-denied, neutral-cwd, public-safe, and confined to disposable roots."
      applies_to: [scripts/release_readiness_gate.py]
  risks:
    - id: RISK-1
      risk: "The direct scenario could duplicate assertions and leave two behavior owners."
      mitigation: "Move the matrix and assertions into the release gate, expose one reusable function, and reduce the parametrized source test to argument setup plus delegation."
    - id: RISK-2
      risk: "A broad selector edit could silently remove unrelated installed coverage."
      mitigation: "Append one exact negative clause and assert the complete selector string in the release-readiness orchestration test."
    - id: RISK-3
      risk: "A refusal could pass while creating palace state, leaking output, touching the repository, or attempting a socket."
      mitigation: "Use the existing environment, snapshot, output-sanitization, and network-attempt owners and fail the direct row on any drift or attempt."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_diary_blank_required_fields_scenario tests/test_cli_golden_scenarios.py::test_diary_write_rejects_blank_required_fields_without_poststate -q"
      proves: "The release-owned matrix and thin source consumer cover all four empty/whitespace cases, repeated refusal, exact diagnostics, and absent post-state."
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The configured direct gate runs the exact candidate console from its neutral, offline, credential-free, socket-denied contour and reports the diary scenario before the narrowed transitional suite."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The configured full source suite preserves existing CLI, storage, release-gate, and scenario-consumer behavior."
        acceptance_ids: [AC-4, AC-5]
      - id: REG-2
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The configured static lint gate accepts the scoped release owner and tests."
        acceptance_ids: [AC-5]
      - id: REG-3
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The configured format gate accepts the scoped release owner and tests."
        acceptance_ids: [AC-5]
      - id: REG-4
        owner: configured_runner
        command: "python scripts/public_safety_scan.py --tracked --staged"
        proves: "The configured public-safety gate finds no private paths, secret-like material, or local-only evidence in the change."
        acceptance_ids: [AC-3, AC-5]
      - id: REG-5
        owner: configured_runner
        command: "python scripts/quality_scorecard.py --check"
        proves: "The configured scorecard remains structurally current after the test-owner move."
        acceptance_ids: [AC-5]
      - id: REG-6
        owner: configured_runner
        command: "python scripts/architecture_guard.py --root ."
        proves: "The configured architecture guard confirms that the change stays inside the existing release-gate owner."
        acceptance_ids: [AC-4, AC-5]
---

## Design Notes

- Rule Zero comparison selects extension of `scripts/release_readiness_gate.py`, which already owns exact-wheel console provenance, neutral cwd, offline flags, credential removal, socket-attempt evidence, bounded row output, repository snapshots, disposable cleanup, and fail-closed orchestration. Deletion or selector-only simplification loses required direct evidence. Replacing the source test without a thin consumer loses source-mode coverage. A same-owner module adds a file and interface without reducing this four-case lifecycle, while a new service, state owner, or architectural boundary adds rollout, operation, rollback, and removal costs with no current acceptance benefit. Keeping the matrix beside the existing scenarios changes the fewest owners and paths, uses the current rollback path, and removes the old assertion body; the cheapest falsifier is duplicate scenario ownership, assertions retained in the source consumer, or any CLI invocation count other than four cases repeated twice.
- Add one `_run_installed_diary_blank_required_fields_scenario` beside the existing direct scenarios. Keep the four tuples as data accepted by this function so the parametrized source test calls the same owner without retaining assertions or subprocess policy.
- Run the new direct scenario in `_run_installed_golden_wheel` before transitional pytest, stop on its first failed row, include its PASS row in successful output, and extend the existing orchestration stubs/assertions accordingly.
- Build each invocation as `--palace <absent-palace> diary write <blank-option> <value> <other-option> <valid-value> --topic ""`; execute attempts 0 and 1 for each tuple through the supplied absolute console and neutral cwd.
- Reuse the existing subprocess runner, environment, forbidden-output checks, stable repository snapshot, socket-attempt log, sanitization, timeout, and row helpers. Do not add another isolation or result framework.
- After each invocation require return code 2, empty stdout, exactly `Error: <option> must not be blank.` plus the existing retry guidance on stderr, and an absent palace path. Any mismatch returns one sanitized failed row with the canonical installed-golden recovery command.
- Add exactly `and not test_diary_write_rejects_blank_required_fields_without_poststate` to the current `-k` expression. Preserve the source-only fixture-shape consumer and every other clause byte-for-byte.
- The focused provider command uses exact pytest node IDs and collects all parametrized cases without a `-k` filter. Configured commands are copied from `scripts/gate_inventory.py`; `pyproject.toml` declares pytest and the repository layout requires running them from the repository root.
- Independent Rule Zero, correctness, and security reviews remain Autopilot review-phase evidence after implementation. They do not become shell pseudo-commands or new repository artifacts in this plan.
- Cheapest falsifier: the focused orchestration test fails if the direct row is absent, the source test retains its own scenario logic, or the transitional selector changes by anything other than the single exact negative clause.
