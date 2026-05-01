slug: CI-CACHING-TEST-ENV-BRANCH
round: 1
date: 2026-05-01
commit_range: aa5641a..d379c64
findings:
  - id: F-1
    title: "test_e2e.py retains an inline copy of the same branch logic, not exercised by the new helper test"
    severity: low
    location: "tests/test_e2e.py:445-451"
    claim: "The CI-cache vs tmp-cache selection logic in test_offline.py was extracted into _configure_hf_home and parametrized over both branches. test_e2e.py::test_offline_gate still has its own inline copy of the same six-line branch. If that copy drifts (e.g. forgetting mkdir or setenv) the new helper test will not catch it, since the helper test exercises only the helper. The task explicitly permits 'test_offline.py and/or test_e2e.py', and the duplicated logic is correct today, so this is a maintainability observation rather than a defect."
    decision: dismissed
  - id: F-2
    title: "Helper mkdir does not pass exist_ok=True"
    severity: info
    location: "tests/test_offline.py:30"
    claim: "Path(hf_home).mkdir() will raise FileExistsError if tmp_path/hf already exists. With pytest's per-test tmp_path fixture this can never happen, and the behavior matches the pre-refactor inline code byte-for-byte, so this is not a regression."
    decision: dismissed
  - id: F-3
    title: "CI-cache branch does not assert the helper leaves the configured directory absent on disk"
    severity: info
    location: "tests/test_offline.py:50-53"
    claim: "When MEMPALACE_TEST_HF_HOME is set, the test verifies HF_HOME points at the configured path and that no tmp_path/hf was created. It does not assert the configured CI path itself is left untouched (the real CI job creates it via actions/cache). Adding such an assertion would over-specify behavior — the helper's contract is that it does not create the directory in this branch, which is already covered by 'not (tmp_path / \"hf\").exists()'. No change needed."
    decision: dismissed
totals:
  fixed: 0
  backlogged: 0
  dismissed: 3
fixes_applied: []
new_backlog: []
