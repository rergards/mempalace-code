slug: PY-MULTI-IMPORT
round: 1
date: "2026-05-01"
commit_range: 41d6869..HEAD
findings:
  - id: F-1
    title: "Regression on 'import os; print()' — semicolon-suffixed import lines emit no triple"
    severity: medium
    location: "mempalace_code/miner.py:3098-3107"
    claim: "Broadening _PY_IMPORT_RE from r'^import\\s+([\\w.]+)' to r'^import\\s+(.+)' captures the entire rest of the line. For 'import os; print()' the captured group becomes 'os; print()'. Comma-split yields one segment 'os; print()' which fails _PY_MODULE_TOKEN_RE (the ';' is not a word char), so no depends_on triple is emitted. The previous regex captured 'os' with [\\w.]+ stopping at ';'. PEP 8 forbids multi-statement lines so this is rare, but it is still a behavioral regression introduced by the multi-module fix."
    decision: fixed
    fix: "Split the captured group on ';' and process only the segment before the first ';'. Restores prior behavior for 'import os; …' (yields 'os'). Added test_py_import_semicolon_first_module to lock the behavior in."
  - id: F-2
    title: "test_py_multi_import_deduplication does not actually exercise list-level dedup"
    severity: low
    location: "tests/test_kg_extract.py:1431-1437 (pre-fix)"
    claim: "The _py helper returns triples_as_set(...). Sets always collapse duplicates, so list-comprehension counting on the set always yields ≤1. The test would pass even if the production 'seen' dedup were removed and the function emitted [(Test, depends_on, os), (Test, depends_on, os)]. AC-4 ('deduplication holds') is therefore not actually verified by this test as originally written."
    decision: fixed
    fix: "Rewrote the test to call extract_type_relationships directly and count occurrences in the raw list, bypassing the set conversion. Now genuinely fails if list-level duplicates leak through."
  - id: F-3
    title: "Pre-existing test_py_import_deduplicated has the same set-conversion blindness"
    severity: info
    location: "tests/test_kg_extract.py:1400-1404"
    claim: "test_py_import_deduplicated also relies on the set-returning _py helper, so it does not actually verify code-level dedup either. This is pre-existing (not introduced by this task), out of scope for PY-MULTI-IMPORT, and the new test_py_multi_import_deduplication now provides the missing list-level coverage."
    decision: dismissed
  - id: F-4
    title: "Tab-separated 'as' alias not stripped"
    severity: info
    location: "mempalace_code/miner.py:3104"
    claim: "segment.split(' as ')[0] uses a literal single space, so 'import os\\tas\\tsystem' would not strip the alias and the whole 'os\\tas\\tsystem' segment fails the module-token regex. Python permits arbitrary whitespace around 'as' but uses a single space in essentially all real code; the formatter (ruff/black) normalizes it. Not worth complicating the regex."
    decision: dismissed
totals:
  fixed: 2
  backlogged: 0
  dismissed: 2
fixes_applied:
  - "Split captured import-line content on ';' so 'import os; print()' continues to yield (module, depends_on, os) — matches pre-PY-MULTI-IMPORT behavior."
  - "Rewrote test_py_multi_import_deduplication to use the raw triple list (not the set helper) so list-level dedup is actually verified."
  - "Added test_py_import_semicolon_first_module to lock in the semicolon-line behavior."
new_backlog: []
