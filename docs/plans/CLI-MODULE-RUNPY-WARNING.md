---
slug: CLI-MODULE-RUNPY-WARNING
goal: "Remove the runpy RuntimeWarning from `python -m mempalace_code.cli` without changing CLI behavior."
risk: low
risk_note: "Likely a narrow import-path fix with a small regression test surface; no auth, data, migration, or release pipeline changes."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: single-package Python import wiring, no sensitive data, no migrations, no external provider boundary, and no pipeline/runtime ownership change."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/__init__.py
    change: "Stop eagerly importing `mempalace_code.cli` at package import time; keep the public `main` export available without preloading the module."
  - path: tests/test_cli_command_modules.py
    change: "Add a subprocess-level regression test that runs `python -m mempalace_code.cli` and asserts the warning is absent while the CLI still responds normally."
acceptance:
  - id: AC-1
    when: "Run `python -m mempalace_code.cli --help` from a clean interpreter."
    then: "The command prints normal help output and stderr does not contain the runpy RuntimeWarning."
  - id: AC-2
    when: "Run `python -m mempalace_code.cli does-not-exist` from a clean interpreter."
    then: "Argparse reports the unknown subcommand as the only error on stderr; the runpy RuntimeWarning is still absent."
  - id: AC-3
    when: "Import `mempalace_code` and inspect its public API from Python."
    then: "The package still exposes a callable `main` entry point for console-script compatibility."
out_of_scope:
  - "Any CLI command behavior changes unrelated to module execution startup."
  - "Packaging metadata, release scripts, and backlog bookkeeping."
  - "Refactors of the command dispatcher or command modules beyond the import-path fix."
---

## Design Notes

- The warning is expected to come from an eager package import that loads `mempalace_code.cli` before `runpy` executes the module body.
- Keep the fix minimal: preserve `mempalace_code:main` for the console script, but avoid importing the full CLI module during package import.
- Use a subprocess-based regression test so the warning is exercised through the same `python -m` path that produced it in release smoke.
- The regression should check stderr directly; a pure import test is not sufficient because the bug only appears under module execution.
- Keep the package `__init__` import surface lazy enough that `python -m mempalace_code.cli` can execute without `mempalace_code` preloading the module object.
