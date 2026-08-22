---
slug: MINE-XAML-NAME-ATTR
status: completed
authority: non_authoritative
goal: "Also emit has_named_control triples for plain Name= attribute (WPF CLR shorthand), deduplicating when both x:Name and Name appear on the same element"
risk: low
risk_note: "Self-contained change to one section of parse_xaml_file(); ET attribute lookup is the same mechanism already in use"
files:
  - path: mempalace/miner.py
    change: "Section 3 of parse_xaml_file(): collect x:Name and plain Name= per element into a set before emitting, so duplicates on the same element are suppressed"
  - path: tests/test_kg_extract.py
    change: "Add two tests: plain Name= emits has_named_control; same-value x:Name+Name on one element emits exactly one triple"
acceptance:
  - id: AC-1
    when: "<Button Name=\"myButton\" /> is parsed (no x: prefix)"
    then: "(\"ViewName\", \"has_named_control\", \"myButton\") is in the returned triples"
  - id: AC-2
    when: "<TextBox x:Name=\"myBox\" Name=\"myBox\" /> is parsed (both attributes, same value)"
    then: "exactly one has_named_control triple for \"myBox\" is emitted (no duplicate)"
  - id: AC-3
    when: "all existing test_parse_xaml_* tests are run"
    then: "all pass without modification"
out_of_scope:
  - "Handling the case where x:Name and Name have *different* values on the same element (undefined behavior in WPF — not a real-world scenario)"
  - "Cross-element deduplication of the same control name (preserves existing behavior)"
  - "Any other XAML predicate (binds_viewmodel, references_resource, uses_command)"
---

## Design Notes

- ElementTree exposes `x:Name` as the Clark-notation key `{http://schemas.microsoft.com/winfx/2006/xaml}Name` (already stored in `xname_attr`). The plain `Name=` attribute has no namespace and is simply the string `"Name"` — `elem.get("Name", "")`.
- Per-element deduplication: collect both values into a `set` before appending triples. This naturally handles the same-value case without a separate code path.
- No cross-element `seen_controls` set is needed (mirrors existing behavior where multiple elements can each have a unique x:Name and each produces a triple).
- The docstring in `parse_xaml_file()` should be updated to mention both `x:Name` and plain `Name=`.
- Test fixtures: write inline XAML strings — no need for new module-level constants (fixtures are small enough to be inline in each test function).
