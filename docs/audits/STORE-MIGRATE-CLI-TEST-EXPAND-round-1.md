slug: STORE-MIGRATE-CLI-TEST-EXPAND
round: 1
date: 2026-05-01
commit_range: 06034cd..97f62ac
findings:
  - id: F-1
    title: "AC numbering in new test docstrings collides with existing tests in the same class"
    severity: info
    location: "tests/test_cli.py:1288"
    claim: "Existing tests in TestMigrateStorageCommand are labeled AC-1..AC-4. The new tests reuse AC-1, AC-2, AC-3 in their docstrings, which can confuse a reader scanning the class. The labels are coherent within the EXPAND task scope (which has its own three ACs), so the conflict is cosmetic and does not affect behavior."
    decision: dismissed
  - id: F-2
    title: "RuntimeError test does not assert successful-path output is suppressed"
    severity: info
    location: "tests/test_cli.py:1311"
    claim: "After raising RuntimeError, cmd_migrate_storage should not reach the 'Source drawers:' print. The test asserts SystemExit and stderr message, which already implies short-circuit, but does not explicitly verify stdout lacks the success line. Adding a 'Source drawers' not-in-stdout check would harden against a regression where the handler prints and continues. Considered redundant given SystemExit assertion."
    decision: dismissed
  - id: F-3
    title: "embed_model test uses an arbitrary string instead of a known model identifier"
    severity: info
    location: "tests/test_cli.py:1299"
    claim: "Passing 'test-model' verifies passthrough but does not exercise validation in the migrator. Since the migrator is mocked, this is the correct seam — passthrough tests should not assume downstream validation. Flagged as observation only."
    decision: dismissed
totals:
  fixed: 0
  backlogged: 0
  dismissed: 3
fixes_applied: []
new_backlog: []
