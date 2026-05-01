slug: STORE-MIGRATE-CLI-TEST
round: 1
date: 2026-05-01
commit_range: e4ffce9..HEAD
findings:
  - id: F-1
    title: "Happy-path test uses identical src/dst counts, masking a swap bug"
    severity: medium
    location: "tests/test_cli.py:1178"
    claim: "return_value=(10, 10) plus 'assert \"10\" in captured.out' would pass even if cmd_migrate_storage swapped src_count and dst_count in its print statement. The print line is 'Source drawers: {src_count}  Destination drawers: {dst_count}' — a swap is a plausible regression and should be detectable."
    decision: fixed
    fix: "Changed return_value to (10, 7) and tightened assertions to 'Source drawers: 10' and 'Destination drawers: 7' so a swap or label mix-up fails the test."
  - id: F-2
    title: "VerificationError test asserts only the prefix, not the message body"
    severity: low
    location: "tests/test_cli.py:1212"
    claim: "Asserting only 'Verification failed:' is on stderr leaves the {e} interpolation untested. A regression that printed a static string with no exception detail would still pass."
    decision: fixed
    fix: "Tightened assertion to 'Verification failed: wing count mismatch' so the exception message reaching stderr is verified."
  - id: F-3
    title: "--verify=True passthrough is untested"
    severity: low
    location: "tests/test_cli.py:1165"
    claim: "Happy-path test asserts verify=False (the default). Argparse store_true wiring for --verify is not exercised by any test. A regression that broke --verify (e.g. dest mismatch) would not be caught."
    decision: backlogged
    backlog_slug: STORE-MIGRATE-CLI-TEST-EXPAND
  - id: F-4
    title: "--embed-model VALUE passthrough is untested"
    severity: low
    location: "tests/test_cli.py:1165"
    claim: "Only embed_model=None (default) is asserted. A regression that dropped --embed-model from the args namespace or hardcoded a different default would not be caught."
    decision: backlogged
    backlog_slug: STORE-MIGRATE-CLI-TEST-EXPAND
  - id: F-5
    title: "RuntimeError exit path in cmd_migrate_storage is untested"
    severity: low
    location: "mempalace/cli.py:526"
    claim: "cmd_migrate_storage has a separate 'except RuntimeError' branch that prints 'Error: {e}' and exits 1. No test triggers it; a regression that removed or broke the handler would not be caught."
    decision: backlogged
    backlog_slug: STORE-MIGRATE-CLI-TEST-EXPAND
  - id: F-6
    title: "--backup-dir / --force tests don't assert other defaults are unaffected"
    severity: info
    location: "tests/test_cli.py:1224"
    claim: "Passthrough tests check the one kwarg they care about but not that, e.g., --backup-dir doesn't accidentally also flip force=True. The happy path covers full defaults, so net coverage is adequate; flagged as observation."
    decision: dismissed
totals:
  fixed: 2
  backlogged: 3
  dismissed: 1
fixes_applied:
  - "Strengthened happy-path assertion: distinct src/dst counts (10, 7) with literal-string output checks so a src/dst swap is detectable."
  - "Strengthened VerificationError assertion: now verifies the exception message body reaches stderr, not just the prefix."
new_backlog:
  - slug: STORE-MIGRATE-CLI-TEST-EXPAND
    summary: "Expand migrate-storage CLI tests: --verify, --embed-model, RuntimeError exit path"
