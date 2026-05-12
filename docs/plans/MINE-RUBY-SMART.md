---
slug: MINE-RUBY-SMART
goal: "Add smart Ruby symbol extraction for ordinary .rb source"
risk: low
risk_note: "Scoped regex/catalog change in one extractor table plus focused unit tests; no storage, API, or migration surface."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: single-file extractor logic, no auth/data/migration/provider/pipeline boundary, no external services, and no destructive rollout steps."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/mining/symbols.py
    change: "Replace the placeholder Ruby extraction entry with regex patterns for classes, modules, methods, attr_* declarations, and constants, preserving nested scope and common singleton-method forms."
  - path: tests/test_symbol_extract.py
    change: "Add Ruby coverage for classes, nested module/class scopes, instance and singleton methods, attr_accessor/attr_reader/attr_writer, constants, and an out-of-scope guard case."
acceptance:
  - id: AC-1
    when: "running `python -m pytest tests/test_symbol_extract.py -q`"
    then: "Ruby cases for class, module, method, attr_*, and constant extraction all pass."
  - id: AC-2
    when: "running a focused Ruby snippet through `extract_symbol()` in the test module"
    then: "nested module/class input returns the outer namespace symbol first, not a generic chunk or the inner definition."
  - id: AC-3
    when: "running a Ruby snippet that uses an out-of-scope DSL-style call such as `has_many` or `before_action`"
    then: "the extractor does not invent a symbol for that DSL line and still returns the first supported declaration when one is present."
out_of_scope:
  - "Rails DSL semantics beyond ordinary class/module/method/attr_/constant syntax"
  - "Dynamic metaprogramming inference such as `define_method` or runtime constant generation"
  - "Changes to file classification, chunking boundaries, or non-Ruby languages"
---

## Design Notes

- Keep Ruby extraction in the existing language-to-pattern table so miner behavior stays catalog-driven.
- Order Ruby patterns from most specific to least specific: class/module first, then method, then `attr_*`, then constants.
- Match nested constant paths and nested module/class declarations with regexes that tolerate `Foo::Bar`-style names.
- Treat singleton methods as first-class Ruby methods, including `def self.name` and common predicate/bang suffixes.
- Accept comma-separated `attr_reader`, `attr_writer`, and `attr_accessor` declarations as ordinary attribute symbols.
- Do not attempt Rails DSL inference; the plan is to keep the extractor conservative and only recognize explicit Ruby syntax.
