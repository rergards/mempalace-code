slug: AUTOPILOT-DEMO-PUBLIC-SAFETY-COMMITTED-MODE
round: 1
date: "2026-06-19"
commit_range: 764dc56..HEAD
findings:
  - id: F-1
    title: "Committed-mode secret test missing source-prefix assertion"
    severity: low
    location: "tests/test_public_safety_scan.py:117"
    claim: >
      test_committed_mode_secret_rejected_and_redacted checked rule_id and token
      redaction but did not assert that the hit was attributed to
      "committed:leak.txt". A regression that produced the hit under a wrong source
      tag (e.g. "staged:leak.txt") would pass the test undetected. The analogous
      local-only-artifact test (test_committed_mode_local_only_artifact_path_rejected)
      correctly checked the committed: prefix, making the inconsistency a real
      coverage gap for the new committed-mode source tagging.
    decision: fixed
    fix: >
      Added `assert "committed:leak.txt" in err` before the existing
      github-token-prefix and redaction assertions in
      test_committed_mode_secret_rejected_and_redacted. All 9 tests pass after the
      change.

  - id: F-2
    title: "scanned counter incremented for path-hit files in committed mode but not staged mode"
    severity: info
    location: "scripts/public_safety_scan.py:204"
    claim: >
      In committed mode, when _path_policy_hit fires, scanned is incremented before
      continuing to the next file. In staged mode the increment comes after the
      content read, so a path-hit file is only counted if its blob is also readable.
      The inconsistency is harmless: scanned appears only in the OK summary, which
      is printed only when the hits list is empty. When there is a path hit the exit
      code is 1 regardless of the counter value.
    decision: dismissed

  - id: F-3
    title: "No test for --committed combined with --tracked or --staged"
    severity: low
    location: "tests/test_public_safety_scan.py"
    claim: >
      The committed, tracked, and staged source selectors are independent branches
      in scan_git_sources and can be combined. A combined run scans the same file
      under two source prefixes, producing separate hits per source. There is no
      test covering this combination. The plan's INV-1 only requires tracked/staged
      remain combinable; combined-mode coverage for committed is a follow-up gap.
    decision: backlogged
    backlog_slug: PUBLIC-SAFETY-SCAN-COMBINED-MODE-TEST

totals:
  fixed: 1
  backlogged: 1
  dismissed: 1

fixes_applied:
  - "Added committed source-prefix assertion to test_committed_mode_secret_rejected_and_redacted"

new_backlog:
  - slug: PUBLIC-SAFETY-SCAN-COMBINED-MODE-TEST
    summary: "Add combined --committed --tracked/--staged test to verify dual-source scan output"
