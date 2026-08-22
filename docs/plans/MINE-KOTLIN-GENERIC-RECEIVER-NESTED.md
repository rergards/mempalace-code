---
slug: MINE-KOTLIN-GENERIC-RECEIVER-NESTED
status: completed
authority: non_authoritative
goal: "Fix Kotlin fun regex to support depth-2 generic nesting in type-param bounds and receiver types"
risk: low
risk_note: "Single regex change in extract-only path; no storage or chunking logic touched; all 23 existing Kotlin tests must remain green"
files:
  - path: mempalace/miner.py
    change: "Replace [^>]+ with (?:[^<>]|<[^<>]*>)* in both the type-params and receiver-type slots of the fun pattern in _KOTLIN_EXTRACT"
  - path: tests/test_symbol_extract.py
    change: "Add two new Kotlin tests: type-param bound nesting (Comparable<T>) and nested receiver (Map<String, List<Int>>)"
acceptance:
  - id: AC-1
    when: "extract_symbol('fun <T : Comparable<T>> List<T>.sorted(): List<T>\\n', 'kotlin') is called"
    then: "returns ('sorted', 'function')"
  - id: AC-2
    when: "extract_symbol('fun Map<String, List<Int>>.flatten(): List<Int>\\n', 'kotlin') is called"
    then: "returns ('flatten', 'function')"
  - id: AC-3
    when: "all 23 existing test_kotlin_* tests in tests/test_symbol_extract.py are run"
    then: "all 23 pass without modification"
  - id: AC-4
    when: "extract_symbol('fun <T> identity(value: T): T = value\\n', 'kotlin') is called (simple type param — existing behaviour)"
    then: "returns ('identity', 'function')"
  - id: AC-5
    when: "extract_symbol('fun <T> List<T>.mapNotNull(transform: (T) -> T?): List<T> {\\n', 'kotlin') is called (single-level generic receiver — existing behaviour)"
    then: "returns ('mapNotNull', 'function')"
out_of_scope:
  - "Depth-3 or deeper generic nesting (e.g. Map<String, Map<Int, List<Long>>>)"
  - "KOTLIN_BOUNDARY chunking regex — only extract_symbol is affected"
  - "Any other language's extract patterns"
  - "Java, C#, or other language fun/method regexes"
---

## Design Notes

- **Root cause**: The `fun` pattern at `miner.py:869` uses `[^>]+` in two positions:
  1. `(?:<[^>]+>\s+)?` — type-parameter block (e.g. `<T : Comparable<T>>`).
     `[^>]+` stops at the `>` inside the nested `<T>`, so the outer `>` never closes properly.
  2. `(?:\w+(?:<[^>]+>)?\.)?` — receiver type (e.g. `Map<String, List<Int>>`).
     Same issue: `[^>]+` halts at the `>` ending `<Int>`, stranding `.flatten` unreachable.

- **Fix**: Replace each `[^>]+` with `(?:[^<>]|<[^<>]*>)*` — "any non-angle char, OR a balanced depth-1 inner pair". This correctly handles depth-2 nesting in both positions.

  Before:
  ```python
  r"...fun\s+(?:<[^>]+>\s+)?(?:\w+(?:<[^>]+>)?\.)?(\w+)"
  ```
  After:
  ```python
  r"...fun\s+(?:<(?:[^<>]|<[^<>]*>)*>\s+)?(?:\w+(?:<(?:[^<>]|<[^<>]*>)*>)?\.)?(\w+)"
  ```

- **Depth-2 is sufficient** for all realistic Kotlin patterns in the task scope:
  - `<T : Comparable<T>>` — outer `<…>` contains one inner `<T>` → depth 2.
  - `Map<String, List<Int>>` — outer `<…>` contains one inner `<Int>` → depth 2.
  - Triple nesting (`Map<K, Map<A, List<V>>>`) is explicitly out of scope.

- **No other patterns change**: `KOTLIN_BOUNDARY`, class/interface/object/typealias patterns, and all other language extractors are untouched.

- **Test placement**: Add the two new tests directly after `test_kotlin_generic_extension_fun_type_param_extracted` (line 766) so all generic-fun tests are grouped together.
