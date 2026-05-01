slug: MINE-DEVOPS-SCAN-COVERAGE
round: 1
date: "2026-05-01"
commit_range: eaf4af3..5225346
findings:
  - id: F-1
    title: "Containerfile / Vagrantfile tests lacked a negative control for KNOWN_FILENAMES handling"
    severity: low
    location: "tests/test_miner.py:1878"
    claim: >
      ``test_scan_project_includes_containerfile`` and ``test_scan_project_includes_vagrantfile``
      both asserted only that the target file appears in the scan output. Their docstrings
      claim coverage "via known filename handling" but the tests had no negative control:
      if the scan_project suffix-check were ever loosened (e.g. dropped the
      ``filename in KNOWN_FILENAMES`` guard so any extensionless file passed through), both
      tests would still pass and the regression would slip. The sibling
      ``test_scan_project_includes_config_files`` test already pins this contract for
      extension-based detection by including ``notes.unknown`` and asserting it is absent;
      the extensionless tests were missing the equivalent control.
    decision: fixed
    fix: >
      Added a sibling ``RandomExtensionless`` file to both tests and asserted it is absent
      from the scan results. This forces the test to fail if scan_project starts accepting
      arbitrary extensionless files, so the tests now genuinely pin the
      ``filename in KNOWN_FILENAMES`` allowlist behavior rather than just any-extensionless
      inclusion. Updated docstrings to call out the negative control.
  - id: F-2
    title: "Diff scope is test-only against a stable, well-covered helper"
    severity: info
    location: "tests/test_miner.py:1829"
    claim: >
      The diff under hardening adds five integration tests against ``scan_project`` for
      DevOps file types (.j2/.jinja2, .conf/.cfg/.ini, .mk, Containerfile, Vagrantfile).
      No production code is touched. ``scan_project`` and the language catalog entries
      are already independently covered by tests/test_lang_detect.py and the existing
      DevOps scan tests. There is no security, performance, or correctness surface in
      the diff itself — it is pure additional verification.
    decision: dismissed
    fix: ""
totals:
  fixed: 1
  backlogged: 0
  dismissed: 1
fixes_applied:
  - "Strengthened test_scan_project_includes_containerfile and test_scan_project_includes_vagrantfile by adding a sibling RandomExtensionless file as a negative control, asserting it is absent so the tests pin KNOWN_FILENAMES allowlist semantics rather than blanket extensionless acceptance."
new_backlog: []
