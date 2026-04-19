slug: DOTNET-CS-MULTILINE-BASE
round: 1
date: 2026-04-19
commit_range: 564a44b..HEAD
findings:
  - id: F-1
    title: "accumulated.rstrip() check is redundant"
    severity: info
    location: "mempalace/miner.py:2108"
    claim: >
      accumulated is built by concatenating line.rstrip() with next_stripped
      (which is already .strip()), so accumulated.rstrip() is always equivalent
      to accumulated. The .rstrip() call is a no-op. Harmless code smell.
    decision: dismissed

  - id: F-2
    title: "Blank continuation lines between base types are consumed (not re-emitted)"
    severity: info
    location: "mempalace/miner.py:2099-2103"
    claim: >
      When scanning for continuation lines, empty lines are skipped (j += 1,
      continue) and never appended to result. This drops blank lines from the
      output text. Harmless for type extraction since _csharp_type_rels only
      extracts triples and does not use line positions.
    decision: dismissed

  - id: F-3
    title: "case/goto labels ending with ':' could merge a following type declaration into a non-matching line"
    severity: low
    location: "mempalace/miner.py:2096"
    claim: >
      Any line ending with ':' triggers continuation merging. A switch case label
      (case X:) or goto label (Retry:) followed immediately by a type declaration
      would cause the type declaration to be merged, making the merged line fail
      to match _CSHARP_TYPE_REL_MATCHERS (false negative). However, this scenario
      requires invalid C# code — class/struct/interface declarations cannot legally
      appear directly after a case or goto label without enclosing braces. The plan
      risk note explicitly accepted this trade-off.
    decision: dismissed

  - id: F-4
    title: "AC-3 (no-regression) not covered by a new test — verified via full suite run"
    severity: info
    location: "tests/test_kg_extract.py"
    claim: >
      AC-3 states all existing test_cs_* tests must pass. The implementation adds
      4 new tests (AC-1, AC-2, AC-4, AC-5) but no dedicated AC-3 test. Regression
      coverage is provided implicitly by running the full suite (97 passed). The
      BACKLOG resolution text "4 new tests covering AC-1 through AC-5" is slightly
      ambiguous but accurate since AC-3 is a no-regression gate, not a new scenario.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 4
fixes_applied: []
new_backlog: []
