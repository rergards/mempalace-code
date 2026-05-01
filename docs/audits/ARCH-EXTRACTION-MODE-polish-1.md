slug: ARCH-EXTRACTION-MODE
phase: polish
date: 2026-05-02
commit_range: 1e1aaa5..b8401ef
reverted: false
findings:
  - id: P-1
    title: "Redundant local variable type annotations"
    category: volume
    location: "mempalace_code/architecture.py:202,283,343"
    evidence: "results: list = [], matched: list = [], seen_ns_project: set = set() — type hints on local variables are unusual in Python and add no tool or reader value"
    decision: fixed
    fix: "Dropped the `: list` / `: set` annotation from all three locals"

  - id: P-2
    title: "Redundant is-None guard before isinstance check"
    category: structural
    location: "mempalace_code/architecture.py:115,141"
    evidence: "_parse_patterns and _parse_layers each had `if raw is None: return list(DEFAULT_*)` immediately followed by `if not isinstance(raw, list): return list(DEFAULT_*)`. None is not a list, so the first check is a strict subset of the second."
    decision: fixed
    fix: "Removed the `if raw is None` branch from both _parse_patterns and _parse_layers; the isinstance check covers it"

  - id: P-3
    title: "_FS_NAMESPACE_RE is an identical duplicate of _CS_NAMESPACE_RE"
    category: structural
    location: "mempalace_code/architecture.py:184"
    evidence: "Both compiled the same pattern r'^\\s*namespace\\s+([\\w.]+)' with re.MULTILINE — C# and F# share identical namespace syntax"
    decision: fixed
    fix: "Deleted _FS_NAMESPACE_RE; _scan_fs now reuses _CS_NAMESPACE_RE"

totals:
  fixed: 3
  dismissed: 0
fixes_applied:
  - "Removed type annotations from local variables results, matched, seen_ns_project in architecture.py"
  - "Collapsed redundant is-None guard into isinstance check in _parse_patterns and _parse_layers"
  - "Deleted duplicate _FS_NAMESPACE_RE; _scan_fs reuses _CS_NAMESPACE_RE"
