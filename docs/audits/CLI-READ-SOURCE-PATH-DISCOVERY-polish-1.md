slug: CLI-READ-SOURCE-PATH-DISCOVERY
phase: polish
date: 2026-05-24
commit_range: 4a7cdce..295e9f8
reverted: false
findings:
  - id: P-1
    title: "Dead branch: len(alias_matches) > 1 in _resolve_source_file is unreachable"
    category: defensive
    location: "mempalace_code/reader.py:123"
    evidence: >
      _macos_var_aliases(source_file) returns at most {source_file, alias} (2 elements).
      After step 1's exact-match check, source_file is known NOT in candidates.
      Therefore alias_matches = aliases & candidates can contain at most one element (the alias).
      The `if len(alias_matches) > 1` branch can never be entered.
      The harden audit (F-2) noted this but dismissed it without recording a reason.
    decision: fixed
    fix: "Removed the 6-line dead block (lines 123-128 in the pre-polish file)."
totals:
  fixed: 1
  dismissed: 0
fixes_applied:
  - "reader.py: removed unreachable `len(alias_matches) > 1` ambiguous_source block after macOS alias lookup"
