slug: QUAL-E2E-REMAINING-MODULES
phase: polish
date: 2026-05-01
commit_range: 3d3d594..32ac9b0
reverted: false
findings:
  - id: P-1
    title: "Inline AC-XX: task-ref prefixes in section comments"
    category: verbal
    location: "tests/test_e2e.py:577-782"
    evidence: >
      14 inline comments like `# AC-10: all stored drawers carry the expected provenance metadata`,
      `# AC-12: wake_up() = L0 + L1 must be strictly larger than L0 alone`, etc.
      AC refs belong in the PR description; function docstrings already capture the AC mapping.
      These prefixes will be meaningless to future maintainers.
    decision: fixed
    fix: "Stripped `AC-XX: ` prefix from all 14 inline section comments; descriptive text retained."

  - id: P-2
    title: "Implementation-internal detail in test setup comment"
    category: verbal
    location: "tests/test_e2e.py:549-550"
    evidence: >
      `# 3 user turns ensures chunk_exchanges() takes the exchange-pair path after normalize.`
      Names an internal function `chunk_exchanges()` that a reader of the test has no context for.
      The WHY is that multiple turns are needed, not the internal function name.
    decision: fixed
    fix: "Collapsed two-line comment to: `# Synthetic Claude.ai JSON export — flat messages list, 3 user/assistant turns.`"

totals:
  fixed: 2
  dismissed: 0
fixes_applied:
  - "Stripped AC-XX: task-ref prefixes from 14 inline section comments across all 3 new test functions"
  - "Replaced two-line implementation-detail comment with single-line setup description"
