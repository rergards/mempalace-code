---
slug: FORMAT-MINING-RUFF-DRIFT
status: completed
authority: non_authoritative
goal: "Reformat the two mining modules flagged by Ruff without changing behavior."
risk: low
risk_note: "Format-only edits in two isolated Python files; no logic, data, or interface changes."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: format-only, no auth/data/migration/provider/pipeline boundary, and no semantic changes."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/mining/chunkers.py
    change: "Apply Ruff formatting only."
  - path: mempalace_code/mining/symbols.py
    change: "Apply Ruff formatting only."
acceptance:
  - id: AC-1
    when: "ruff format --check mempalace_code/mining/chunkers.py mempalace_code/mining/symbols.py runs"
    then: "it exits 0 with no reformat needed for either file"
  - id: AC-2
    when: "ruff check mempalace_code/mining/chunkers.py mempalace_code/mining/symbols.py runs"
    then: "it exits 0 and reports no new lint findings in the two scoped files"
  - id: AC-3
    when: "the two files are inspected after formatting"
    then: "only whitespace / layout changes are present, with no semantic edits"
out_of_scope:
  - "Any benchmark or script lint findings reported by broader ruff checks"
  - "Any files outside mempalace_code/mining/chunkers.py and mempalace_code/mining/symbols.py"
  - "Any code behavior, extraction rules, or tests"
---

## Design Notes

- Keep the change strictly formatter-driven; do not hand-edit expressions or regexes.
- Preserve import ordering and existing line wrapping conventions as produced by Ruff.
- Do not expand scope to the older `ruff check .` findings that live outside these two files.
