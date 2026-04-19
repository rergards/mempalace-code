---
slug: DOTNET-CS-MULTILINE-BASE
goal: "Add continuation-line joining to _csharp_type_rels so multi-line base-type declarations produce KG triples"
risk: low
risk_note: "Pure preprocessing step; existing regex patterns and _split_base_list are unchanged. Worst case: over-joined lines that still don't match the strict type-declaration prefixes."
files:
  - path: mempalace/miner.py
    change: "Add _join_continuation_lines helper; call it in _csharp_type_rels after comment stripping"
  - path: tests/test_kg_extract.py
    change: "Add tests for multi-line base-type declarations (colon-on-its-own-line, comma-separated continuation, mixed single+multi)"
acceptance:
  - id: AC-1
    when: "C# class with colon on the declaration line, bases on next line: 'public class Foo :\\n    IBar\\n{ }'"
    then: "(Foo, implements, IBar) triple is produced"
  - id: AC-2
    when: "Multi-line base list with two comma-separated bases on separate lines"
    then: "Both triples are produced (one per base type)"
  - id: AC-3
    when: "All existing test_cs_* tests are run"
    then: "Zero regressions — every test that passed before still passes"
  - id: AC-4
    when: "Interface with colon on declaration line, two bases on continuation lines"
    then: "Two 'extends' triples are produced"
  - id: AC-5
    when: "Record type with multi-line base list"
    then: "Correct implements triple is produced"
out_of_scope:
  - "F# or VB.NET continuation-line handling"
  - "Python type-relationship extraction"
  - "Any change to _CSHARP_TYPE_REL_MATCHERS regex patterns"
  - "Any change to _split_base_list"
---

## Design Notes

- **Where to insert**: in `_csharp_type_rels` (miner.py:2082), immediately after the two `re.sub` comment-stripping lines and before the matcher loop. Do not add it to the module level — this preprocessing is C#-specific.

- **Algorithm**: Scan lines; when the current line (after `rstrip`) ends with `:` or `,`, merge the next non-empty line's stripped content onto the current line with a single space separator. Repeat while the accumulated line still ends with `,`. Stop early if the accumulated line already contains `{` (block open) or `;` (statement terminator) — the base-list truncation that follows will handle the rest. Append each finalized line to the result.

- **Why a separate helper**: Keeping `_join_continuation_lines` as a named function makes it unit-testable in isolation if needed, and keeps `_csharp_type_rels` readable.

- **`:` over-join risk**: Many C# constructs end with `:` (switch `case X:`, goto labels, ternary in some positions). None of those will match `_CSHARP_TYPE_REL_MATCHERS` because the patterns require specific modifier+keyword prefixes. Over-joining these lines is harmless.

- **`,` over-join risk**: Trailing commas appear in method args, object initializers, attribute lists, etc. Again, the patterns are anchored to type-declaration keywords so spurious joins don't produce false triples.

- **Stop condition**: Once `{` is merged in, the `for stop in (" where ", "{", ...)` truncation inside the matcher loop already clips the base list there. No need to prevent joining past `{` — but stopping at `{` avoids very long merged lines in degenerate files. Keep it simple: stop merging when the *next* line's stripped form starts with `{` or is just `;`.

- **Test placement**: Insert the new tests after `test_cs_record_struct_form` (line 815 in test_kg_extract.py) and before the F# section header at line 817. Use the existing `_cs(tmp_path, ...)` helper.
