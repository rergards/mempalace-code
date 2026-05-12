slug: CLI-OPT-IN-VERSION-CHECK
phase: polish
date: 2026-05-12
commit_range: b603088..fa78a53
reverted: false
findings:
  - id: P-1
    title: "Needless lambda wrappers around fetch_latest_version"
    category: volume
    location: "mempalace_code/version_check.py:266, mempalace_code/version_check.py:301, mempalace_code/cli_commands/version_check.py:58"
    evidence: "lambda: fetch_latest_version() — fetch_latest_version takes only keyword-with-defaults args, so the lambda wrapper adds no value"
    decision: fixed
    fix: "Replaced `lambda: fetch_latest_version()` with `fetch_latest_version` directly in all three call sites"
totals:
  fixed: 1
  dismissed: 0
fixes_applied:
  - "Remove needless lambda wrappers: `lambda: fetch_latest_version()` → `fetch_latest_version` (3 sites)"
