slug: MINE-KOTLIN-GENERIC-RECEIVER-NESTED
round: 1
date: 2026-04-19
commit_range: ea350dd..66acbe1
findings:
  - id: F-1
    title: "Depth-3+ generic nesting not handled by fun regex"
    severity: info
    location: "mempalace/miner.py:870"
    claim: >
      The pattern (?:[^<>]|<[^<>]*>)* handles depth-2 nesting (one level of inner
      angle brackets) but silently returns ("", "") for depth-3+ cases such as
      `fun <T : Collection<List<Int>>> T.process()`. This is intentional per the task
      scope ("handle depth-2 nesting") and the comment in the code acknowledges it.
      Depth-3 Kotlin generic bounds are rare in practice.
    decision: dismissed

  - id: F-2
    title: "Missing test: modifier + depth-2 type-param bound combined"
    severity: low
    location: "tests/test_symbol_extract.py:786"
    claim: >
      AC-1 tests `fun <T : Comparable<T>>` without any modifier. A regression in
      the modifier pattern could break `inline fun <T : Comparable<T>> …` without
      being caught. The modifier path and the new type-param pattern have separate
      failure modes.
    decision: fixed
    fix: "Added test_kotlin_generic_fun_modifier_with_nested_type_param asserting
          ('sortedDesc', 'function') for `inline fun <T : Comparable<T>> List<T>.sortedDesc()`"

  - id: F-3
    title: "Missing test: type params AND nested receiver in same signature"
    severity: low
    location: "tests/test_symbol_extract.py:786"
    claim: >
      AC-1 tests type-param section alone; AC-2 tests receiver section alone. No test
      exercises a signature where both sections use the new (?:[^<>]|<[^<>]*>)* pattern
      simultaneously, e.g. `fun <T> Map<String, List<T>>.flatMap()`.
    decision: fixed
    fix: "Added test_kotlin_generic_fun_type_params_and_nested_receiver asserting
          ('flatMap', 'function') for `fun <T> Map<String, List<T>>.flatMap(): List<T>`"

  - id: F-4
    title: "_optimize_once silently swallows all exceptions"
    severity: info
    location: "mempalace/watcher.py:243"
    claim: >
      The helper catches bare Exception and prints a skipped message, which could mask
      a missing palace or corrupt store. However, this is a best-effort post-batch
      optimization; the mine() calls before it have already succeeded, so skipping
      optimize on error is acceptable behavior. The user sees a skipped message in
      the console.
    decision: dismissed

totals:
  fixed: 2
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Added test_kotlin_generic_fun_modifier_with_nested_type_param to cover modifier + depth-2 type-param bound"
  - "Added test_kotlin_generic_fun_type_params_and_nested_receiver to cover combined type params + nested receiver"

new_backlog: []
