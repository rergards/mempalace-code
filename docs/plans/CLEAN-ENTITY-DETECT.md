---
slug: CLEAN-ENTITY-DETECT
status: completed
authority: non_authoritative
goal: "Make mempalace init skip heuristic entity detection unless explicitly enabled"
risk: low
risk_note: "Small CLI/config behavior change around an optional pre-mining scan, with focused tests for defaults, opt-in, and invalid config fallback."
files:
  - path: mempalace/cli.py
    change: "Add --detect-entities to init and run scan_for_detection/detect_entities/confirm_entities only when the flag or config enables it."
  - path: mempalace/config.py
    change: "Add entity_detection config property with false default and bool parsing consistent with existing config flags."
  - path: tests/test_cli.py
    change: "Cover init default skip behavior, explicit CLI opt-in, --yes non-interactive opt-in, and config-enabled detection."
  - path: tests/test_config.py
    change: "Cover entity_detection default, config true/false parsing, and invalid value fallback."
  - path: README.md
    change: "Update init examples/help text so entity detection is documented as opt-in."
  - path: docs/AGENT_INSTALL.md
    change: "Update non-interactive install guidance so --yes no longer implies entity detection output."
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_cli.py -k 'init_default_skips_entity_detection' is run"
    then: "mempalace init <dir> --skip-model-download completes without calling scan_for_detection or creating entities.json."
  - id: AC-2
    when: "python -m pytest tests/test_cli.py -k 'init_detect_entities_runs_scan' is run"
    then: "mempalace init <dir> --detect-entities --skip-model-download calls scan_for_detection/detect_entities and writes entities.json when confirmed entities are returned."
  - id: AC-3
    when: "python -m pytest tests/test_cli.py -k 'init_yes_without_detect_entities_skips_scan' is run"
    then: "mempalace init <dir> --yes --skip-model-download does not call entity detection and does not prompt for entity confirmation."
  - id: AC-4
    when: "python -m pytest tests/test_cli.py -k 'init_config_entity_detection_true_runs_scan' is run with config.json containing entity_detection true"
    then: "mempalace init <dir> --skip-model-download runs entity detection even without --detect-entities."
  - id: AC-5
    when: "python -m pytest tests/test_config.py -k 'entity_detection_invalid_falls_back_false' is run with config.json containing an invalid entity_detection value"
    then: "MempalaceConfig().entity_detection resolves to False."
out_of_scope:
  - "Changing entity_detector.py heuristics or scoring."
  - "Removing entity detection support."
  - "Changing conversation mining entity extraction."
  - "Migrating existing user config files."
---

## Design Notes

- Keep entity detection available but off by default for code-first initialization.
- Add `--detect-entities` to `mempalace init`; it should force detection regardless of config.
- Add `entity_detection` to the generated default `config.json` as `false`, and expose `MempalaceConfig.entity_detection`.
- Reuse the existing optional bool parser in `config.py`; invalid config/env-like values should fall back to `False` rather than enabling scans accidentally.
- In `cmd_init`, instantiate `MempalaceConfig` once, resolve `detect_entities_enabled = args.detect_entities or config.entity_detection`, and skip the entire `entity_detector` import/work path when false.
- Preserve current opt-in behavior when detection is enabled: scan files, classify entities, call `confirm_entities(..., yes=args.yes)`, and write `<project>/entities.json` only for non-empty confirmed people/projects.
- Leave `onboarding.run_onboarding(auto_detect=True)` unchanged unless implementation finds `mempalace init` still routes through it; the CLI path currently uses `room_detector_local.detect_rooms_local`.
- Update AGENT_INSTALL expectations: `mempalace init "<MINE_PATH>" --yes` should pass based on successful config/room setup, not `Entities saved` or `No entities detected` output.
