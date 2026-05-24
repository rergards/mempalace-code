slug: CLI-MODULE-RUNPY-WARNING
round: 1
date: 2026-05-24
commit_range: 828aa9d..HEAD
findings:
  - id: F-1
    title: "__getattr__ missing return type annotation"
    severity: info
    location: "mempalace_code/__init__.py:15"
    claim: >
      The module-level __getattr__ function has no return type annotation. Pyright
      infers the return type correctly and reports zero errors, so this is purely a
      readability observation with no runtime impact.
    decision: dismissed

  - id: F-2
    title: "Redundant _RUNPY_WARNING check when -W error is active"
    severity: info
    location: "tests/test_cli_command_modules.py:26"
    claim: >
      In test_no_runpy_warning_on_help and test_no_runpy_warning_on_unknown_command,
      the explicit `_RUNPY_WARNING not in result.stderr` assertion is logically
      covered by the returncode check when -W error is used: if the warning fires,
      Python raises RuntimeWarning, exits non-zero, and the returncode assertion
      already catches it. The redundant assertion is not harmful — it makes the
      failure message self-documenting — but it is not strictly necessary.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 2
fixes_applied: []
new_backlog: []
