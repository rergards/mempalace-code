slug: MIGRATE-STORAGE-REAL-USAGE-FIXTURE
round: 1
date: 2026-05-24
commit_range: af7a955..4802c2be5fa718080f7ef3336845aeee35b33dd2
findings:
  - id: F-1
    title: "Vacuously true assertion in test_missing_chroma_exits_before_fixture_creation"
    severity: low
    location: "tests/test_migrate_storage_smoke.py:47"
    claim: >
      The test accepted a `tmp_path` parameter and asserted `list(tmp_path.iterdir()) == []`,
      but the smoke runner never writes to `tmp_path` — it creates its own TemporaryDirectory
      under the system temp path. The assertion was always true regardless of behavior, making
      it a no-op check. The meaningful assertion (exit code == 1) was already present.
    decision: fixed
    fix: >
      Removed the `tmp_path` parameter and the vacuously true assertion. The test now only
      asserts on the exit code, which is the only behavior being verified. Updated the docstring
      to be precise about what is verified ("before entering the TemporaryDirectory block").

  - id: F-2
    title: "--rows 0 accepted by argparse but causes confusing search-step failure"
    severity: low
    location: "scripts/migrate_storage_smoke.py:228"
    claim: >
      The `--rows` argument used `type=int` with no lower-bound validation. Passing `--rows 0`
      would create an empty Chroma collection (0 rows), migrate 0 rows successfully, then fail
      at the search verification step with a message about MARKER_PREFIX not being found —
      an unhelpful error that does not mention the root cause (zero rows seeded, nothing to find).
    decision: fixed
    fix: >
      Replaced `type=int` with a local `_positive_int` validator function defined inside `main()`
      that raises `ArgumentTypeError` for values < 1. Added a corresponding test
      `test_rows_zero_rejected_by_argparse` that verifies `--rows 0` exits non-zero with an
      explanatory error before any fixture creation or CLI invocation.

  - id: F-3
    title: "No subprocess timeout on _run_cli calls"
    severity: info
    location: "scripts/migrate_storage_smoke.py:82"
    claim: >
      `subprocess.run` in `_run_cli` has no `timeout` parameter. A hung subprocess (e.g., the
      CLI waiting for model download or a network check) would cause the smoke to hang
      indefinitely with no feedback.
    decision: dismissed
    fix: ""

totals:
  fixed: 2
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "Removed vacuously true tmp_path assertion from test_missing_chroma_exits_before_fixture_creation"
  - "Added _positive_int argparse validator to enforce --rows >= 1 with a clear error message"
  - "Added test_rows_zero_rejected_by_argparse to cover the new validation"

new_backlog: []
