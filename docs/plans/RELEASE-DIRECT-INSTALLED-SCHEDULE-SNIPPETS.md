---
slug: RELEASE-DIRECT-INSTALLED-SCHEDULE-SNIPPETS
status: completed
authority: non_authoritative
goal: "Correct the release-owned schedule scenario for renderer-specific path semantics while keeping its thin source test outside transitional exact-wheel pytest selection."
risk: medium
risk_note: "The patch is confined to release qualification, but a shared path-normalization assumption can falsely reject a correct wheel or admit the wrong backup/watch renderer behavior."
files:
  - path: scripts/release_readiness_gate.py
    change: "Qualify backup against its lexical absolute palace path, qualify watch against its canonical root, and retain the schedule thin-consumer exclusion from the transitional pytest selector."
  - path: tests/test_release_readiness_gate.py
    change: "Add a symlink-alias falsifier for the two renderer path contracts and update exact-wheel selector/orchestration assertions."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable scorecard after test-line metrics change."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable scorecard after test-line metrics change."
acceptance:
  - id: AC-1
    when: "the exact candidate wheel console runs the schedule scenario from a neutral cwd while PATH starts with a failing ambient mempalace-code launcher"
    then: "every invocation uses the absolute candidate console and the ambient launcher records zero execution"
  - id: AC-2
    when: "backup and watch schedule previews are each rendered twice for quoted disposable targets"
    then: "each pair is byte-identical, safely quotes the candidate console and its expected target, names the correct scheduler, and leaves state unchanged"
  - id: AC-3
    when: "the palace and watch roots are reached through a filesystem alias whose lexical absolute and canonical paths differ"
    then: "backup emits shlex.quote(os.path.abspath(str(palace))) while watch emits shlex.quote(str(watch_root.resolve())), and each case rejects the other token"
  - id: AC-4
    when: "each schedule command is retried with unsupported --install"
    then: "it exits 2 with empty stdout, bounded sanitized diagnostics, the renderer-specific expected path, and byte-identical disposable and repository post-state"
  - id: AC-5
    when: "the exact-wheel owner reaches its transitional pytest command after the direct schedule row passes"
    then: "test_installed_schedule_snippets_bind_to_invoked_launcher remains a thin source-suite consumer and its negative selector clause remains present while every other clause is unchanged"
  - id: AC-6
    when: "the configured non-network suite, static/public release gates, fresh exact-wheel installed rows, and independent review run"
    then: "all required evidence passes inside the credential-free, offline, disposable-data, non-publishing boundary"
out_of_scope:
  - "Changing backup, watch, launcher-resolution, quoting, scheduler-name, or --install product behavior."
  - "Changing tests/test_cli_golden_scenarios.py beyond verifying that its existing function remains a thin consumer."
  - "Changing composite workflow, diary/path behavior, recovery matrices, non-regular sources, fixture shape, inventory, Linux hosted behavior, dependencies, or adjacent installed scenarios."
  - "Installing or mutating ambient scheduler, service, user-home, repository product data, or other non-disposable state."
  - "Editing backlog metadata or performing commit, push, tag, release, publication, remote mutation, credential access, authentication, or external AI-client invocation."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release correction changes release-blocking exact-wheel evidence under renderer-specific path, provenance, no-mutation, and credential-free constraints."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The direct scenario must invoke only the absolute candidate console from a neutral cwd under hostile PATH shadowing."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Backup and watch previews must be deterministic, safely quoted, scheduler-specific, and non-mutating."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Backup must retain lexical os.path.abspath semantics while watch retains canonical Path.resolve semantics."
      source: "current backlog contract AC-3 and observed fresh-wheel falsifiers"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Unsupported installation must fail with bounded sanitized evidence and unchanged post-state."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The stable source test must remain a thin consumer outside transitional installed pytest selection without changing other clauses."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Configured regression, static/public, fresh exact-wheel, and independent review evidence must remain green."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "direct installed schedule-snippet qualification"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Use one scenario owner with per-case expected rendered targets, execute it directly and through the existing thin source consumer, and return bounded installed-golden evidence."
  invariants:
    - id: INV-1
      statement: "The backup and watch renderer implementations and their public CLI contracts remain unchanged."
      applies_to: ["mempalace_code/backup.py", "mempalace_code/watcher.py", "mempalace_code/cli_commands/backup_restore.py", "mempalace_code/cli_commands/watch.py"]
    - id: INV-2
      statement: "Candidate-wheel installation, absolute console/module provenance, watch extra, socket guard, credential-free offline environment, neutral cwd, timeouts, and outer disposable root remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "test_installed_schedule_snippets_bind_to_invoked_launcher keeps its stable name and existing thin call-plus-row-assertion body."
      applies_to: ["tests/test_cli_golden_scenarios.py"]
    - id: INV-4
      statement: "The negative selector clause for test_installed_schedule_snippets_bind_to_invoked_launcher and all other transitional clauses remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-5
      statement: "Qualification performs no ambient scheduler installation, credential access, authentication, external AI-client execution, Git mutation, remote mutation, or publication."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "One universal resolve or abspath rule can reject the correct renderer-specific output on macOS path aliases."
      mitigation: "Carry an explicit expected rendered target per scenario and use a symlink alias that makes the lexical and canonical tokens observably different."
    - id: RISK-2
      risk: "A permissive assertion could accept both target spellings and miss a renderer regression."
      mitigation: "Require the owner-specific quoted token and reject the alternate token independently for backup and watch."
    - id: RISK-3
      risk: "Selecting the thin test in installed pytest could duplicate the release-owned scenario and disturb adjacent transitional ownership."
      mitigation: "Retain its exact negative clause, preserve the thin consumer unchanged, and assert the complete selector plus direct-row order."
    - id: RISK-4
      risk: "Failure or refusal branches could leak transient paths or mutate disposable/repository state."
      mitigation: "Retain bounded sanitization, forbidden-output checks, ambient marker checks, semantic snapshots, cleanup proof, and one canonical recovery command."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_schedule_snippet_scenario_fails_closed tests/test_release_readiness_gate.py::test_installed_golden_uses_watch_extra_provenance_neutral_cwd_and_safe_env tests/test_cli_golden_scenarios.py::test_installed_schedule_snippets_bind_to_invoked_launcher -q"
      proves: "Focused existing owners distinguish lexical backup and canonical watch paths, preserve hostile/failure guards, keep the source consumer thin, and prove the selector exclusion."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The fresh exact wheel executes the direct schedule row and its selected thin source consumer through the absolute installed console from the neutral contour."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-3
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured non-network suite preserves renderer, CLI, source-golden, release-orchestration, and unrelated behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The correction stays inside the existing installed-golden gate and adds no inventory or public command surface."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Tracked release command declarations remain synchronized."
      acceptance_ids: [AC-6]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The bounded diff contains no private path, credential-shaped, authenticated-provider, or publication material."
      acceptance_ids: [AC-4, AC-6]
    - id: VER-7
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the release-owner correction and tests."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-8
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the bounded implementation."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-9
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts per-case path expectations and evidence flow."
      acceptance_ids: [AC-3, AC-6]
    - id: VER-10
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict slice remains green."
      acceptance_ids: [AC-6]
    - id: VER-11
      owner: configured_runner
      command: "python scripts/architecture_guard.py --root ."
      proves: "The correction introduces no service, store, helper framework, or ownership boundary."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-12
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The committed deterministic scorecard matches changed test metrics."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves schedule rendering, refusal, release orchestration, and unrelated non-network behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "No second gate command, mode, inventory entry, or public runner is introduced."
        acceptance_ids: [AC-5, AC-6]
---

## Design Notes

- Rule Zero selects a correction inside `scripts/release_readiness_gate.py`, the existing exact-wheel and schedule-scenario owner. Product renderer changes would violate the supplied contracts; a shared normalization helper would recreate the false assumption; a new runner or module would add a parallel owner.
- Current source already has one `_run_installed_schedule_snippet_scenario`, one direct `_run_installed_golden_wheel` call, and a thin stable consumer in `tests/test_cli_golden_scenarios.py`. Preserve those owners, change only the per-case expected target, and keep the thin consumer excluded from transitional installed pytest.
- Extend each scenario tuple with its expected rendered path: backup uses `shlex.quote(os.path.abspath(str(palace)))`; watch uses `shlex.quote(str(watch_root.resolve()))`. Keep executable provenance canonical via the supplied absolute console.
- Build the falsifier with a symlink alias under the disposable root so lexical absolute and resolved target strings differ on every platform. For each case, require its expected token and reject the other renderer's token; retain spaces and shell metacharacters to exercise quoting.
- Keep two preview invocations and one `--install` refusal per renderer. Preserve byte comparison, scheduler labels, clean bounded streams, ambient marker non-execution, semantic scenario/repository snapshots, cleanup, sanitized FAIL rows, and exactly one installed-golden rerun command.
- Retain `and not test_installed_schedule_snippets_bind_to_invoked_launcher` in the existing transitional `-k` expression. Keep its exact-string unit assertion aligned; do not rename or edit the thin source test, reorder other clauses, or alter adjacent direct rows.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` because the scorecard derives test line metrics from the tracked tree. No other documentation or generated artifact changes.
- Rollback is the direct reversal of these four paths. There is no migration, compatibility shim, persisted-state change, runtime rollout, or public API delta.
- Cheapest decisive falsifier: VER-1 uses one aliased target to demand lexical backup output and canonical watch output while rejecting the converse; it also proves the selector exclusion and existing failure matrix before fresh-wheel qualification.
- Command context basis: `pyproject.toml` declares repository-root pytest and the non-network default; `.claude/skills/verify/INSTRUCTIONS.md`, `scripts/quality_scorecard.py`, `scripts/gate_inventory.py`, and `docs/RELEASING.md` expose the exact configured full-suite, static/public, scorecard, and exact-wheel commands. PLAN inspected these files and did not execute any planned command.
- No `docs/quality/incident-class-registry.yaml` exists in the current tree. This release-test correction does not change runtime routing or a registry-class surface, so no `incident_proof` block applies.
- Independent review is runner-owned phase evidence required by AC-6. PLAN does not represent it as a shell row and does not run tests, builds, verification wrappers, exact-wheel qualification, reviews, generated-plan validation, Git finalization, source verification, or publication.
