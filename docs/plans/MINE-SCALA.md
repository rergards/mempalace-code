---
slug: MINE-SCALA
status: completed
authority: non_authoritative
goal: "Add Scala (.scala, .sc) language support to the code miner with regex-based symbol extraction for classes, case classes, objects, traits, enums, and functions"
risk: low
risk_note: "Follows the established Swift/PHP/Kotlin pattern — additions only, no changes to existing language code. No tree-sitter grammar is required."
files:
  - path: mempalace/miner.py
    change: "Add .scala and .sc to EXTENSION_LANG_MAP (→ 'scala') and to READABLE_EXTENSIONS; add SCALA_BOUNDARY regex; register scala in get_boundary_pattern(); add _SCALA_EXTRACT pattern list with case_class/case_object/object/trait/class/enum/function/type; add 'scala' to _LANG_EXTRACT_MAP; add 'scala' to the chunk_file() code-language tuple; extend comment_prefixes with '@' for scala in chunk_code() (Scala annotation syntax matches Swift)"
  - path: mempalace/searcher.py
    change: "Add 'scala' to SUPPORTED_LANGUAGES; add 'object', 'case_class', 'case_object' to VALID_SYMBOL_TYPES"
  - path: mempalace/mcp_server.py
    change: "Add 'scala' to the mempalace_code_search language description string; add 'object', 'case_class', 'case_object' to the symbol_type description string"
  - path: tests/test_symbol_extract.py
    change: "Add Scala extract_symbol unit tests: class, case class, object, case object, trait, Scala 3 enum, def (with/without access modifiers), type alias, generics, access modifiers (private[scope]), sealed/abstract/final prefix chains, implicit declarations (implicit def → function, implicit class → class), no-match for property lines (val/var), no-match for `given` declarations (intentionally not a boundary)"
  - path: tests/test_miner.py
    change: "Add test_mine_scala_roundtrip — full mine() cycle on a .scala file proving the walker discovers .scala via READABLE_EXTENSIONS and stored drawers have language='scala'"
  - path: tests/test_miner.py
    change: "Add test_mine_scala_script_roundtrip — full mine() cycle on a script.sc file containing a top-level `def greet() = ...`, asserting detect_language returns 'scala' and the resulting drawer has language='scala', symbol_type='function', symbol_name='greet' (closes AC-12)"
  - path: tests/test_chunking.py
    change: "Add test_chunk_code_scala_annotation_attachment — direct chunk_code(..., 'scala', ...) test verifying @tailrec / @main / @deprecated lines attach to the following declaration chunk (not orphaned in the preceding chunk), mirroring existing PHP/C# chunk_code annotation coverage"
  - path: tests/test_lang_detect.py
    change: "Add .scala and .sc to the extension parametrize list in test_extension_detection"
  - path: tests/test_searcher.py
    change: "Add test_code_search_scala_language — verify code_search(language='scala') does not raise validation error; add test_code_search_scala_invalid_language_hint — verify that when code_search is called with an invalid language, the error response's supported_languages list includes 'scala' (mirrors existing searcher hint assertions for prior language additions); add test_code_search_new_symbol_types_scala — verify 'object', 'case_class', 'case_object' are accepted as symbol_type filters"
acceptance:
  - id: AC-1
    when: "A .scala file containing `class UserService { ... }` is mined"
    then: "At least one drawer has language='scala', symbol_type='class', symbol_name='UserService'"
  - id: AC-2
    when: "A .scala file containing `case class Point(x: Int, y: Int)` is mined"
    then: "Drawer has symbol_type='case_class', symbol_name='Point' (NOT 'class')"
  - id: AC-3
    when: "A .scala file containing `object Logger { ... }` is mined"
    then: "Drawer has symbol_type='object', symbol_name='Logger'"
  - id: AC-4
    when: "A .scala file containing `case object Empty` is mined"
    then: "Drawer has symbol_type='case_object', symbol_name='Empty'"
  - id: AC-5
    when: "A .scala file containing `trait Readable { def read(): String }` is mined"
    then: "Drawer has symbol_type='trait', symbol_name='Readable'"
  - id: AC-6
    when: "A .scala file containing `enum Color { case Red, Green, Blue }` (Scala 3) is mined"
    then: "Drawer has symbol_type='enum', symbol_name='Color'"
  - id: AC-7
    when: "A .scala file containing `def fetchUser(id: Long): Future[User] = ...` is mined"
    then: "Drawer has symbol_type='function', symbol_name='fetchUser'"
  - id: AC-8
    when: "A .scala file containing `type Result[A] = Either[Throwable, A]` is mined"
    then: "Drawer has symbol_type='type', symbol_name='Result'"
  - id: AC-9
    when: "extract_symbol is called on a chunk containing only `val name: String = \"test\"` (a property, not a declaration)"
    then: "Returns ('', '') — val/var properties are not extracted as symbols"
  - id: AC-10
    when: "A .scala file with `sealed abstract class Tree[A]` is mined"
    then: "symbol_name='Tree' (generics and prefix modifiers do not break extraction)"
  - id: AC-11
    when: "A .scala file with `@tailrec\\nprivate def loop(n: Int): Int = ...` is mined"
    then: "The resulting chunk for `loop` contains the `@tailrec` annotation line (annotation not orphaned)"
  - id: AC-12
    when: "A file named `script.sc` with a top-level `def greet() = ...` is mined"
    then: "detect_language returns 'scala' and the drawer has language='scala', symbol_type='function', symbol_name='greet'"
  - id: AC-13
    when: "code_search is called with language='scala'"
    then: "Does not return a validation error (language is in SUPPORTED_LANGUAGES)"
  - id: AC-14
    when: "code_search is called with symbol_type='case_class' (or 'object', or 'case_object')"
    then: "Does not return a validation error (symbol_types are in VALID_SYMBOL_TYPES)"
  - id: AC-15
    when: "extract_symbol is called on a Scala 3 `given intOrdering: Ordering[Int] = ...` chunk"
    then: "Returns ('', '') — `given` declarations are intentionally NOT a boundary or symbol (documented exclusion; see Resolved Decisions)"
out_of_scope:
  - "Tree-sitter AST parsing for Scala (no tree_sitter_scala grammar is installed in the ecosystem); regex tier only, matching Kotlin/Swift/PHP"
  - "SBT build files (.sbt) — not in the task scope (`.scala, .sc` only)"
  - "Scala 3 `extension` methods — deferred. Not treated as a first-class boundary in this task; extension method bodies will be mined as ordinary `def` chunks inside the surrounding class/object context (or, if top-level, fall into a preamble chunk). A follow-up task can revisit extension-as-symbol once user demand is clear."
  - "Scala 3 `given` / `using` declarations — `given` is intentionally NOT a boundary (same rationale as `val`/`var` — noisy; see Resolved Decisions). Included here explicitly for unambiguity."
  - "Implicit conversion semantics or pattern-match exhaustiveness — these are analysis concerns, not extraction. (Note: `implicit def` and `implicit class` ARE extracted as `function`/`class` respectively; only the *semantics* are out of scope.)"
  - "Cross-file symbol resolution (companion objects sharing namespace with classes) — each chunk is extracted independently"
  - "Macro annotations and metaprogramming — treated as ordinary annotation syntax"
---

## Design Notes

- **Regex-only, no tree-sitter.** No `tree_sitter_scala` is available in the Python ecosystem. Scala joins the Java/Kotlin/Swift/PHP/C# regex tier.

- **Extensions:** `.scala` (standard) and `.sc` (Ammonite/worksheet scripts, Scala CLI). Both map to language `"scala"`. Script files use the same syntax.

- **Scala 2 vs Scala 3:** regex patterns must cover both:
  - Scala 3 additions that ARE boundaries: `enum`, `opaque type`, `inline` (as modifier on `def`), `open` (as modifier on `class`)
  - Scala 3 additions that are NOT boundaries in this task: `given` (see Resolved Decisions), `extension` (deferred — see `out_of_scope`)
  - Scala 2 implicits: `implicit def`, `implicit class`, `implicit val` — `implicit` is an access-style modifier. `implicit def` and `implicit class` are boundaries; `implicit val` is not (follows the `val` exclusion).

- **Access / declaration modifiers:** `private`, `protected`, `private[scope]`, `protected[scope]`, `final`, `sealed`, `abstract`, `override`, `implicit`, `lazy`, `inline`, `opaque`, `open`. Boundary/extract patterns tolerate arbitrary prefix chains. `private[scope]` bracket-qualifier is matched with `(?:\[[\w.]+\])?`.

- **Pattern ordering (must be strict):**
  1. `case class` before plain `class` — otherwise `class` swallows the case form and emits wrong symbol_type.
  2. `case object` before plain `object`.
  3. `sealed trait` / `abstract class` — handled by the modifier-chain prefix, not separate patterns.
  4. `object` before `trait`/`class` is fine (disjoint anchor keywords).
  5. `type` alias regex must not match `type: String` in parameter lists — anchor to `^` start of line only (after indentation).

- **Symbol types emitted:**
  - `class`, `case_class`, `case_object`, `object`, `trait`, `enum`, `function` (for `def`), `type` (for `type Foo = …`). `case_class`/`case_object` mirror the Kotlin `data_class`/`sealed_class` naming convention so searches remain meaningful.
  - New entries in `VALID_SYMBOL_TYPES`: `object`, `case_class`, `case_object`. `trait`, `enum`, `class`, `function`, `type` already exist.

- **`val` / `var` / `given` are intentionally excluded from boundaries.** Same rationale as Kotlin `val`/`var` and Swift `let`/`var` — too noisy as top-level breaks. Module-level `val` definitions will fall into the preceding chunk (typical for constants).

- **Annotation attachment (`@` prefix):** Scala uses `@tailrec`, `@main`, `@deprecated`, `@inline`, `@SerialVersionUID(1L)`, etc. before declarations. Extend `comment_prefixes` in `chunk_code()` with `"@"` for `canonical == "scala"`, mirroring the Swift handling at miner.py:1775-1778. Reuse the existing Swift-style pure-attribute guard so `@ThreadLocal val x = 0` (an annotation on a val, which is not a boundary) is not greedily swallowed into the next function chunk — simplest path is to share `_SWIFT_PURE_ATTR` (renamed to `_ATTR_ONLY_LINE` or kept Swift-named and reused) OR add a dedicated `_SCALA_PURE_ATTR`. Prefer a separately named `_SCALA_PURE_ATTR = _SWIFT_PURE_ATTR` alias for clarity, no regex duplication.

- **Boundary regex sketch:**
  ```
  ^(?:@\w+(?:\([^)]*\))?\s+)*
  (?:(?:private|protected|public|final|sealed|abstract|override|implicit|lazy|inline|opaque|open|case)(?:\[[\w.]+\])?\s+)*
  (?:case\s+class|case\s+object|class|object|trait|enum|def|type)\s+\w+
  ```
  `case` appears twice: as a type-flavor prefix (`case class`, `case object`) and inside enum bodies (`case Red, Green` — those are not top-level boundaries since they are indented enum cases, so the `^`-anchored boundary is safe).

- **Generics handling:** Scala generics can be bracketed (`[T]`, `[A, B <: Ordered[A]]`) rather than `<…>`. Reuse the Kotlin depth-2 pattern adapted to square brackets: `(?:\[(?:[^\[\]]|\[[^\[\]]*\])*\])?` after the symbol name so `class Container[T <: Comparable[T]]` still extracts `Container`.

- **Type alias vs type parameter:** The `type` extraction regex must require `^` anchoring and a following `=` (`type Name[Params] = …`) so type parameters inside generic brackets or method signatures are never matched.

- **Package declarations (`package foo.bar`)** are NOT boundaries. They are expected at file top and will naturally land in the preamble chunk. No special handling.

- **Integration test goes through `mine()`, not just `process_file()`** — proves `.scala`/`.sc` are in `READABLE_EXTENSIONS` and the file walker picks them up end-to-end. Both extensions get their own roundtrip test (`test_mine_scala_roundtrip` for `.scala`, `test_mine_scala_script_roundtrip` for `.sc`) so AC-12 (`.sc` routing) is verified end-to-end, not just via `detect_language` unit coverage.

- **Direct `chunk_code` coverage for annotations.** In addition to the full-mine annotation test, a focused `chunk_code(..., "scala", ...)` test lives in `tests/test_chunking.py` next to the existing PHP/C# chunk-boundary tests. This catches `@tailrec`/`@main` attachment regressions earlier than the integration layer (shorter signal, no palace/embedding machinery).

## Resolved Decisions

- **`case_class` / `case_object` are first-class symbol types (not flattened to `class`/`object`).** Rationale: in Scala these are semantically distinct (value-based equality, pattern-match-friendly, auto-derived `apply`/`unapply`), and users searching Scala codebases expect to filter by them — matching the Kotlin precedent (`data_class`, `sealed_class`).

- **`object` is added to `VALID_SYMBOL_TYPES`.** Kotlin already emits `object` as a symbol type but the value was not previously registered for API filtering. Adding it here benefits both Scala and Kotlin searches without any code churn.

- **`.sc` joins `.scala`.** Scala CLI and Ammonite scripts are valid Scala; treating them the same removes a foot-gun where users mine a project and wonder why their worksheets are missing.

- **Implicits are not a separate symbol type.** `implicit def foo` emits `function` with name `foo`; `implicit class Wrapper` emits `class` with name `Wrapper`; `implicit val x` is not a boundary (like other `val`s). Creating an `implicit` symbol type would overlap every real declaration kind.

- **`given` (Scala 3) is not a boundary.** `given Ordering[Int] = ...` is conceptually similar to `implicit val` — skipping keeps chunk noise low. Can be revisited if users request it (open a follow-up task). Verified by AC-15: a `given` declaration passed to `extract_symbol` must return `('', '')`.

- **Scala 3 `extension` methods are deferred.** The `extension` keyword (e.g. `extension (s: String) def shout: String = ...`) has distinctive semantics that don't map cleanly to any existing symbol_type, and no clear user signal exists for how it should appear in search results. Rather than guessing a representation now, this task treats `extension` blocks as non-boundaries — the inner `def` will still be chunked as a `function` when present. A follow-up task can add a first-class `extension` symbol_type once the need is concrete. See `out_of_scope` for the explicit deferral.

- **`searcher.py` and `mcp_server.py` are in scope.** Without updating `SUPPORTED_LANGUAGES` / `VALID_SYMBOL_TYPES`, `code_search(language="scala", symbol_type="case_class")` would reject valid Scala queries. MCP description strings are updated to keep client hints aligned with backend validation.
