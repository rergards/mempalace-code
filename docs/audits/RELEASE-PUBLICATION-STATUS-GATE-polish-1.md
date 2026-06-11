slug: RELEASE-PUBLICATION-STATUS-GATE
phase: polish
date: 2026-06-11
commit_range: 771d631..7ccc9c6
reverted: false
findings:
  - id: P-1
    title: "Spurious SIM115 noqa on function with no file-open call"
    category: verbal
    location: "tests/test_release_status_gate.py:123"
    evidence: >
      `def run_gh(args: list[str]) -> ...:  # noqa: SIM115  # reason: sequential checks on same arg list`
      — SIM115 is "Use context handler for opening files"; no `open()` exists in this function.
      The reason comment misidentifies the rule as being about sequential if-checks.
    decision: fixed
    fix: "Removed `# noqa: SIM115  # reason: sequential checks on same arg list` from the line."
totals:
  fixed: 1
  dismissed: 0
fixes_applied:
  - "Removed spurious SIM115 noqa and incorrect reason comment from _gh_no_runs inner function"
