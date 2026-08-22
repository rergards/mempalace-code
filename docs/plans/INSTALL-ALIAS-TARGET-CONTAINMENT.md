---
slug: INSTALL-ALIAS-TARGET-CONTAINMENT
status: completed
authority: non_authoritative
goal: "Honor explicit install-alias --target-dir as the alias mutation boundary."
risk: medium
risk_note: "Small CLI behavior change, but it touches fail-closed alias installation and PATH collision semantics."
contract_policy:
  flow: full_spdd
  reason: "Standard safety task for a CLI install mutation boundary used by degraded actors and post-install automation."
  sync_gate: required
  verification_path: automated
files:
  - path: mempalace_code/cli_commands/alias.py
    change: "Branch explicit target-dir handling so only the requested target alias path controls success, idempotence, and collision refusal; preserve default PATH alias behavior."
  - path: tests/test_cli.py
    change: "Add focused install_legacy_alias unit coverage for explicit-target creation/idempotence, PATH alias suppression regression, target collision refusal, and default idempotence."
  - path: tests/test_cli_golden_scenarios.py
    change: "Add a real CLI subprocess containment scenario from a neutral working directory with disposable HOME/PATH/bin directories."
acceptance:
  - id: AC-1
    when: "An explicit --target-dir install runs with a disposable canonical mempalace-code executable and an empty target, or with a preexisting correct alias in that target."
    then: "The command succeeds only with a mempalace alias under the requested target directory, and that alias resolves to the canonical executable."
  - id: AC-2
    when: "An explicit --target-dir install runs while PATH already contains a correct mempalace alias in another directory."
    then: "The command creates or returns the requested target alias instead of reporting the existing PATH alias as the result."
  - id: AC-3
    when: "An explicit --target-dir install finds a regular file, unrelated symlink, or otherwise incorrect mempalace entry at the requested target path."
    then: "The command exits fail-closed, reports the target collision, and leaves the existing target entry unchanged."
  - id: AC-4
    when: "The default install-alias path runs without --target-dir while PATH already contains a correct mempalace alias for mempalace-code."
    then: "The command remains idempotent and returns the existing PATH alias without creating a duplicate."
  - id: AC-5
    when: "The real CLI subprocess containment test runs from a neutral working directory with disposable HOME, PATH, source bin, target bin, and user-bin directories."
    then: "The requested target bin receives the alias, the preexisting PATH alias remains unchanged, and the disposable user-bin directory remains untouched."
out_of_scope:
  - "Rename console scripts, change argparse options, or change mempalace-code-alias entry point wiring."
  - "Change canonical executable discovery beyond preserving the existing PATH-first and argv0 fallback behavior."
  - "Overwrite, delete, or repair conflicting aliases outside the requested explicit target."
  - "Change default no-target PATH collision refusal semantics for unrelated mempalace commands."
  - "Update docs/BACKLOG.yaml, backlog archives, release notes, or task bookkeeping."
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "An explicit target directory must be the only alias path that controls install-alias success and mutation."
      source: "current backlog contract AC-1, AC-2, AC-3"
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: REQ-2
      statement: "A correct mempalace alias elsewhere on PATH must not suppress explicit-target alias creation."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Default install-alias behavior without --target-dir must remain idempotent for an existing correct PATH alias."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-4
      statement: "CLI-level proof must exercise containment from a neutral directory using disposable paths only."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Alias installer"
      kind: cli
      paths: ["mempalace_code/cli_commands/alias.py"]
      expected_behavior: "When target_dir is explicit, inspect alias_dir/mempalace first and ignore mempalace aliases elsewhere on PATH for success or collision decisions; when target_dir is absent, keep the existing PATH alias check."
    - name: "In-process alias tests"
      kind: internal
      paths: ["tests/test_cli.py"]
      expected_behavior: "Unit tests prove explicit-target success, target idempotence, PATH-alias regression coverage, target collision refusal, and default idempotence without subprocess overhead."
    - name: "Real CLI containment test"
      kind: cli
      paths: ["tests/test_cli_golden_scenarios.py"]
      expected_behavior: "A subprocess test runs install-alias from a neutral cwd with temporary HOME/PATH/bin directories and proves the target bin is the only mutated bin directory."
  invariants:
    - id: INV-1
      statement: "Canonical mempalace-code discovery stays PATH-first with the existing sys.argv[0] fallback and existing error when no canonical executable is found."
      applies_to: ["mempalace_code/cli_commands/alias.py"]
    - id: INV-2
      statement: "Default install-alias without target_dir still returns a correct PATH mempalace alias and still refuses an unrelated PATH mempalace command."
      applies_to: ["mempalace_code/cli_commands/alias.py", "tests/test_cli.py"]
    - id: INV-3
      statement: "Existing target entries are never overwritten; correct existing target symlinks remain idempotent."
      applies_to: ["mempalace_code/cli_commands/alias.py", "tests/test_cli.py"]
    - id: INV-4
      statement: "Same-directory aliases remain relative symlinks to mempalace-code, and cross-directory aliases remain symlinks to the resolved canonical executable."
      applies_to: ["mempalace_code/cli_commands/alias.py", "tests/test_cli.py"]
    - id: INV-5
      statement: "Tests must use temporary HOME, PATH, source bin, target bin, and user-bin directories and must not touch the operator's real bin directories."
      applies_to: ["tests/test_cli.py", "tests/test_cli_golden_scenarios.py"]
  risks:
    - id: RISK-1
      risk: "Keeping the global PATH alias check ahead of target inspection would reproduce the false success."
      mitigation: "Split explicit-target and default branches before checking shutil.which(LEGACY_CLI_ALIAS), with AC-2 unit and subprocess coverage."
    - id: RISK-2
      risk: "Ignoring target collisions while bypassing PATH checks could overwrite an unrelated file or symlink."
      mitigation: "Always inspect alias_path for exists or is_symlink before creating it, and add AC-3 fail-closed tests."
    - id: RISK-3
      risk: "Changing default behavior while fixing explicit targets could break existing idempotent installs."
      mitigation: "Keep the no-target branch behaviorally equivalent and add AC-4 regression coverage."
    - id: RISK-4
      risk: "A subprocess proof could accidentally use the checkout cwd or real user bin directory."
      mitigation: "Use the existing golden CLI environment isolation helpers, run from a temp neutral cwd, and assert the disposable user-bin remains untouched."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_cli.py::TestLegacyAlias::test_explicit_target_dir_creates_alias_even_when_correct_alias_exists_elsewhere tests/test_cli.py::TestLegacyAlias::test_explicit_target_dir_accepts_existing_correct_target_alias -q"
      proves: "Explicit target_dir creates or returns the requested target alias and a correct PATH alias elsewhere does not suppress that target."
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_cli.py::TestLegacyAlias::test_explicit_target_dir_refuses_conflicting_target_entry -q"
      proves: "An incorrect target alias path fails closed without overwriting the existing entry."
      acceptance_ids: [AC-3]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_cli.py::TestLegacyAlias::test_default_install_alias_returns_existing_correct_path_alias -q"
      proves: "Default install-alias remains idempotent for an existing correct PATH alias."
      acceptance_ids: [AC-4]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_install_alias_explicit_target_containment_from_neutral_directory -q"
      proves: "The real CLI subprocess honors explicit target containment from a neutral cwd and leaves the disposable user-bin untouched; in installed mode this exercises the installed console script."
      acceptance_ids: [AC-1, AC-2, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_cli.py::TestLegacyAlias -q"
        proves: "The focused alias unit suite covers default creation, default collision refusal, explicit target containment, and default idempotence together."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_cli_command_modules.py::test_cli_module_exports_stable_entry_points tests/test_cli_command_modules.py::test_alias_module_exports tests/test_cli_command_modules.py::test_install_legacy_alias_is_same_object_as_in_alias_module -q"
        proves: "CLI exports and the alias module entry points remain wired to the same install_legacy_alias implementation."
        acceptance_ids: [AC-4]
      - id: REG-3
        owner: provider
        command: "python -m pytest tests/test_cli_golden_scenarios.py::test_install_alias_explicit_target_containment_from_neutral_directory -q"
        proves: "The subprocess-level containment scenario remains covered by the CLI golden test surface."
        acceptance_ids: [AC-5]
---

## Design Notes

- Current behavior in `mempalace_code/cli_commands/alias.py` resolves the canonical `mempalace-code`, computes `alias_path`, then checks `shutil.which("mempalace")` before inspecting `alias_path`. That ordering lets a correct alias elsewhere on PATH satisfy an explicit target request without touching the requested target.
- Keep `_resolve_canonical_cli()` unchanged. The bug is in alias-boundary selection, not canonical executable discovery.
- Implement the fix by branching on `target_dir is None` before consulting the existing PATH alias. The default branch should keep the current PATH idempotence and conflict behavior. The explicit-target branch should decide only from `alias_dir / "mempalace"`.
- In the explicit-target branch, inspect `alias_path.exists() or alias_path.is_symlink()` before creating parent directories or the new symlink. A correct target alias returns `alias_path`; any incorrect target entry raises the existing fail-closed collision style.
- Preserve symlink shape: when the alias and canonical executable are in the same directory, create a relative symlink to `mempalace-code`; otherwise create a symlink to the resolved canonical path.
- Test context basis: `pyproject.toml` declares `tests` as pytest testpaths and filters `needs_network`/`slow`. Planned commands therefore use focused repository-root `python -m pytest ... -q` invocations.
- The golden CLI containment test should avoid the real user environment by using disposable `HOME`, `PATH`, source bin, target bin, and user-bin directories. Run from a temp neutral cwd, create a fake canonical `mempalace-code` on PATH, create a correct `mempalace` alias in a different PATH directory, then invoke `install-alias --target-dir <target-bin>`.
- The subprocess assertion should verify stdout reports the target alias path, `target-bin/mempalace` resolves to the canonical executable, the preexisting PATH alias still resolves to the same canonical executable, and the disposable user-bin has no `mempalace` entry.
- `docs/quality/incident-class-registry.yaml` is not present in this worktree, so there is no registry-matched incident proof block for this isolated CLI alias safety plan.
