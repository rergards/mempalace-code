slug: UPSTREAM-WINDOWS-UTF8-STDIO
phase: polish
date: 2026-05-23
commit_range: 06683cb..HEAD
reverted: false
findings:
  - id: P-1
    title: "Sanity assertion tests property of its own string literal, not the code under test"
    category: defensive
    location: "tests/test_stdio.py:171"
    evidence: 'assert "\\" not in repr(cyrillic), "sanity: Cyrillic chars should not be escape-only"'
    decision: fixed
    fix: >
      Removed the line. The assertion checked that the test's own Python string literal
      "Привет" contained no backslashes — a property of the source encoding, not of any
      code path. It could never fail under normal circumstances; reverting ensure_ascii=False
      would not affect it. The two preceding lines already verify the actual invariant.

  - id: P-2
    title: "RaisingStream.self.calls is initialized but never read or asserted"
    category: structural
    location: "tests/test_stdio.py:32"
    evidence: "self.calls: list[dict[str, Any]] = [] in RaisingStream.__init__; reconfigure() always raises before any append"
    decision: dismissed
    reason: >
      Removing the attribute would create interface asymmetry with FakeStream, potentially
      confusing future readers who expect both fake helpers to share the same shape. The
      harden audit (F-4) already evaluated this and reached the same conclusion. No test
      correctness is gained by removal.

totals:
  fixed: 1
  dismissed: 1
fixes_applied:
  - "Removed dead sanity assertion on string literal in test_mcp_non_ascii_preserved_in_json_rpc (tests/test_stdio.py:171)"
