---
slug: MINE-CSHARP-EXPR-BODY
goal: "Detect C# expression-bodied properties as chunk boundaries and property symbols"
risk: low
risk_note: "Additive regex expansion in existing C# miner patterns with focused symbol and chunking regression tests."
files:
  - path: mempalace/miner.py
    change: "Extend the CSHARP_BOUNDARY and _CSHARP_EXTRACT property regexes so a property name followed by either `{` or `=>` is detected."
  - path: tests/test_symbol_extract.py
    change: "Add C# extract_symbol coverage for expression-bodied properties and retain field-like non-property guards."
  - path: tests/test_chunking.py
    change: "Add C# chunk_code coverage proving expression-bodied property declarations create structural boundaries."
acceptance:
  - id: AC-1
    when: "extract_symbol('public int Count => _items.Count;\\n', 'csharp') is called"
    then: "returns ('Count', 'property')"
  - id: AC-2
    when: "extract_symbol('private int _count;\\n', 'csharp') is called after the regex change"
    then: "returns ('', '') rather than treating the field as a property"
  - id: AC-3
    when: "A padded C# class containing adjacent expression-bodied properties `Count` and `Name` is passed to chunk_code(..., 'csharp', 'Catalog.cs')"
    then: "the output includes declaration chunks beginning at both `public int Count =>` and `public string Name =>`"
  - id: AC-4
    when: "An expression-bodied property with preceding XML documentation is passed through chunk_code(..., 'csharp', 'Catalog.cs')"
    then: "the XML documentation lines remain in the same chunk as the expression-bodied property declaration"
out_of_scope:
  - "C# method, constructor, event, class, record, struct, interface, or enum regex changes."
  - "Tree-sitter support for C#."
  - "Changing chunk sizing thresholds or adaptive_merge_split behavior."
  - "Symbol extraction for C# fields."
---

## Design Notes

- Keep the change inside the existing C# regex-based miner path in `mempalace/miner.py`; `.cs` files already route to `CSHARP_BOUNDARY` and `_CSHARP_EXTRACT`.
- Change only the property terminator portion from a hard `{` requirement to an alternation that accepts `{` or `=>` immediately after optional whitespace following the property name.
- Preserve the requirement for at least one C# member modifier so local variables and ordinary field declarations do not become boundaries.
- Keep the property extractor ordered before the method extractor. Expression-bodied property names are followed by `=>`, so they should not be captured as methods, but the existing order is still the least risky path.
- Add symbol tests near the existing C# property and field tests in `tests/test_symbol_extract.py`.
- Add chunking tests near the existing C# chunking tests in `tests/test_chunking.py`, using padded fixtures above the chunk minimum so separate detected boundaries are observable after `adaptive_merge_split()`.
