---
slug: SCHEDULE-SNIPPET-INVOKED-LAUNCHER-PROVENANCE
status: completed
authority: non_authoritative
goal: "Render backup and watch schedules plus recovery guidance with the canonical launcher selected by the current invocation."
risk: medium
risk_note: "The change affects commands persisted into launchd or cron and must preserve quoting, library fallbacks, and non-mutating schedule rendering."
files:
  - path: mempalace_code/cli_commands/alias.py
    change: "Expose the existing invoked canonical-launcher resolution as the single reusable provenance owner while preserving alias installation behavior and fail-closed sibling validation."
  - path: mempalace_code/backup.py
    change: "Make backup schedule rendering prefer the invoked canonical launcher before the existing PATH/module fallback and retain explicit binary overrides and shell/XML quoting."
  - path: mempalace_code/watcher.py
    change: "Make watch schedule rendering prefer the invoked canonical launcher before the existing PATH/module fallback and retain root validation, explicit overrides, and shell/XML quoting."
  - path: mempalace_code/cli_commands/backup_restore.py
    change: "Resolve one selected launcher for backup schedule output and use it in the rendered command and actionable re-render/install guidance with explicit palace, frequency, and plist targets."
  - path: mempalace_code/cli_commands/watch.py
    change: "Resolve one selected launcher for watch schedule output and use it in the rendered command and actionable re-render/install guidance with safely quoted watch-root and plist targets."
  - path: tests/test_cli.py
    change: "Extend the existing alias-provenance tests for the reusable resolver, including absolute, relative, symlinked, dedicated-entry-point, ambient-shadow, and missing-sibling cases."
  - path: tests/test_backup.py
    change: "Add backup renderer and command-handler regressions for invoked-launcher precedence, safe spaced paths, deterministic non-mutating output, explicit override compatibility, and selected-launcher guidance."
  - path: tests/test_watcher.py
    change: "Add watch renderer and command-handler regressions for invoked-launcher precedence, safe spaced paths, deterministic non-mutating output, root guards, and selected-launcher guidance."
  - path: tests/test_cli_golden_scenarios.py
    change: "Exercise both schedule commands through the absolute exact-wheel CLI from a neutral directory with a conflicting PATH, including deterministic output and recovery-guidance assertions."
acceptance:
  - id: AC-1
    when: "an absolute installed mempalace-code is invoked while PATH resolves mempalace-code to a different executable"
    then: "backup and watch launchd or cron snippets name the invoked installed launcher and contain no ambient launcher path"
  - id: AC-2
    when: "schedule rendering is reached through a symlinked canonical launcher or the dedicated mempalace-code-alias entry point"
    then: "the existing provenance contract selects the invocation-preserving canonical launcher or its executable canonical sibling rather than a conflicting PATH entry"
  - id: AC-3
    when: "the selected launcher, palace path, watch root, or output target contains spaces or shell-significant characters"
    then: "the rendered cron command and launchd plist preserve each value as one executable argument without interpolation or truncation"
  - id: AC-4
    when: "either schedule command is rendered twice against unchanged inputs and scheduler state is inspected before and after"
    then: "stdout and guidance are byte-identical and no plist, crontab, launchd job, backup, watcher, or other scheduler state is created or changed"
  - id: AC-5
    when: "backup or watch schedule output displays its refusal, re-render, installation, or recovery guidance"
    then: "every executable command uses the same selected launcher and safely names the explicit palace, watch root, frequency, and destination path applicable to that command"
  - id: AC-6
    when: "the freshly built candidate wheel is installed and its absolute mempalace-code executable runs from a neutral directory with a conflicting PATH"
    then: "both backup schedule and watch schedule execute directly through that wheel and satisfy launcher, target, determinism, guidance, and no-mutation assertions"
  - id: AC-7
    when: "the dedicated mempalace-code-alias launcher is invoked without an executable canonical mempalace-code sibling while PATH contains an ambient mempalace-code"
    then: "resolution fails non-zero with an actionable missing-sibling error and emits no schedule snippet using the ambient executable"
out_of_scope:
  - "Installing, loading, unloading, removing, or otherwise mutating launchd jobs, crontabs, backups, or watcher processes."
  - "Changing schedule frequencies, launchd labels, cron timing, watcher root classification, backup retention, or update-scheduler behavior."
  - "Creating a second launcher resolver, scheduler renderer, installed-wheel harness, or release gate."
  - "Changing unrelated recovery messages outside backup schedule and watch schedule command output."
  - "Implementation-phase edits to docs/BACKLOG.yaml, docs/BACKLOG-archived.yaml, or runner-owned completion metadata."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release work changes launcher provenance at persisted scheduler-command and recovery-guidance boundaries."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Backup and watch schedule snippets must use the canonical launcher selected by the current invocation instead of an unrelated PATH executable."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Symlinked and dedicated installed entry points must retain the existing canonical-sibling provenance and fail-closed behavior."
      source: "current backlog contract AC-2 and failure-path requirement"
      acceptance_ids: [AC-2, AC-7]
    - id: REQ-3
      statement: "Rendered commands and guidance must preserve launcher and target paths safely across cron and launchd representations."
      source: "current backlog contract AC-3 and AC-5"
      acceptance_ids: [AC-3, AC-5]
    - id: REQ-4
      statement: "Schedule rendering must remain deterministic and read-only."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The exact candidate wheel must directly exercise both affected schedule commands from a neutral directory under PATH conflict."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "invoked launcher provenance"
      kind: internal
      paths: ["mempalace_code/cli_commands/alias.py"]
      expected_behavior: "One existing resolver identifies an absolute or relative invoked canonical CLI, maps the dedicated alias installer to its executable canonical sibling, and rejects a missing sibling before PATH fallback."
    - name: "backup schedule CLI"
      kind: cli
      paths: ["mempalace_code/backup.py", "mempalace_code/cli_commands/backup_restore.py"]
      expected_behavior: "Rendered backup commands and their actionable guidance consistently use one selected launcher with explicit, safely represented schedule targets."
    - name: "watch schedule CLI"
      kind: cli
      paths: ["mempalace_code/watcher.py", "mempalace_code/cli_commands/watch.py"]
      expected_behavior: "Rendered watch commands and their actionable guidance consistently use one selected launcher while preserving watch-root admission guards."
  invariants:
    - id: INV-1
      statement: "Explicit mempalace_bin arguments to render_schedule and render_watch_schedule continue to win and remain safely quoted."
      applies_to: ["mempalace_code/backup.py", "mempalace_code/watcher.py"]
    - id: INV-2
      statement: "When no installed invocation can be established, existing PATH and python -m mempalace_code renderer fallbacks remain available to direct library callers."
      applies_to: ["mempalace_code/backup.py", "mempalace_code/watcher.py", "mempalace_code/cli_commands/alias.py"]
    - id: INV-3
      statement: "Schedule commands only print snippets and guidance; --install continues to refuse mutation."
      applies_to: ["mempalace_code/cli_commands/backup_restore.py", "mempalace_code/cli_commands/watch.py"]
    - id: INV-4
      statement: "Watch schedule root classification and backup schedule frequency/platform validation remain unchanged."
      applies_to: ["mempalace_code/backup.py", "mempalace_code/watcher.py"]
    - id: INV-5
      statement: "Legacy alias creation keeps its collision, target-directory, and invocation-preserving symlink contracts."
      applies_to: ["mempalace_code/cli_commands/alias.py"]
  risks:
    - id: RISK-1
      risk: "A shared resolver could change direct-library fallback behavior when sys.argv does not identify an installed launcher."
      mitigation: "Prefer invoked provenance only when the existing validator proves it; otherwise preserve the current PATH and python-module fallbacks and their tests."
    - id: RISK-2
      risk: "Using a correct path with unsafe shell or XML representation could still produce an unusable or injectable scheduled command."
      mitigation: "Retain shlex quoting and XML escaping, then execute bounded fake-launcher commands extracted from cron/plist fixtures with spaced and shell-significant paths."
    - id: RISK-3
      risk: "Renderer output and recovery guidance could resolve independently and disagree under PATH conflict."
      mitigation: "Resolve once at each CLI boundary, pass the same value into the renderer, and format all associated guidance from that value."
    - id: RISK-4
      risk: "Installed-wheel assertions could accidentally exercise the checkout or ambient launcher."
      mitigation: "Extend the existing exact-wheel golden owner, retain its installed-module provenance preflight and neutral cwd, and prepend a conflicting executable directory to PATH."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_cli.py tests/test_backup.py tests/test_watcher.py tests/test_cli_golden_scenarios.py -q"
      proves: "The affected existing test owners exercise invoked and fallback resolution, sibling failure, both renderers, quoting, deterministic read-only output, explicit targets, and selected-launcher guidance without test-name filtering."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-7]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The exact configured installed-golden gate builds its neutral execution environment and directly runs the golden backup and watch schedule scenarios through the absolute candidate-wheel launcher."
      acceptance_ids: [AC-1, AC-3, AC-4, AC-5, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The exact configured non-network suite preserves alias installation, CLI dispatch, schedule formats, root guards, backups, watchers, and installed-golden orchestration."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
---

## Design Notes

- Keep `mempalace_code/cli_commands/alias.py` as the launcher-provenance owner. Make its invoked canonical resolver reusable; do not add a generic utility module or a second resolver.
- Resolve launcher provenance before consulting `PATH`. Absolute and slash-containing relative `mempalace-code` invocations preserve their invocation path; `mempalace-code-alias` resolves only to the executable sibling named `mempalace-code` and retains its existing missing-sibling error.
- At each CLI schedule boundary, resolve once and pass that exact launcher into the renderer. Use the same quoted value for refusal, re-render, installation, and recovery guidance so stdout and stderr cannot select different executables.
- Preserve renderer compatibility: an explicit `mempalace_bin` wins; a direct library call without a provable installed invocation retains the established PATH lookup and `sys.executable -m mempalace_code` fallback.
- Keep command construction as data until the existing cron shell-command and launchd XML boundaries. Apply `shlex.quote` once per launcher or target value and XML-escape the completed launchd shell command once.
- Recovery and re-render guidance must state concrete inputs instead of depending on conversational context: backup guidance includes launcher, `--palace`, frequency, and plist target; watch guidance includes launcher, watch root, and plist target.
- Add no scheduler installation code. Determinism fixtures compare repeated stdout/stderr and a bounded filesystem snapshot; installed-golden coverage invokes only rendering and the existing `--install` refusal path.
- Extend `tests/test_cli_golden_scenarios.py` because it already owns neutral-directory source and exact-wheel CLI subprocess behavior. In installed mode, place an executable ambient `mempalace-code` earlier on `PATH`, invoke both schedule commands through `_CLI`, and assert the absolute candidate launcher appears while the ambient path does not.
- Use fake executable launchers for shell-execution assertions so the spaced-path cron/plist checks record argv without creating a backup, watcher, plist, cron entry, or launchd job.
- Command context basis: `pyproject.toml` declares pytest and Python 3.11+, while `scripts/gate_inventory.py` defines the exact installed-golden and full non-network configured-runner commands recorded above. The provider command runs the four affected existing test files unfiltered.
- PLAN did not execute tests, builds, verification wrappers, scheduler commands, or generated-plan validation.
