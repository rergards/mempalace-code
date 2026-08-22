---
slug: MINE-KOTLIN
status: completed
authority: non_authoritative
goal: "Add regex-based smart chunking and symbol extraction for Kotlin (.kt, .kts) to miner.py"
risk: low
risk_note: "Additive change only — new patterns and dispatch entries; no existing language paths modified"
files:
  - path: mempalace/miner.py
    change: "Add .kt/.kts to EXTENSION_LANG_MAP and READABLE_EXTENSIONS, add KOTLIN_BOUNDARY, register in get_boundary_pattern(), add _KOTLIN_EXTRACT, register in _LANG_EXTRACT_MAP, add 'kotlin' to chunk_file() dispatch"
  - path: tests/test_symbol_extract.py
    change: "Add Kotlin test section covering class, data class, sealed class, object, companion object, interface, enum class, fun, suspend fun, extension fun, typealias, and edge cases (annotation-prefixed, property-not-extracted, chunking)"
acceptance:
  - id: AC-1
    when: "Mining a .kt file containing a data class"
    then: "Drawer has language='kotlin', symbol_name='Point', symbol_type='data_class'"
  - id: AC-2
    when: "Mining a .kt file with a sealed class hierarchy"
    then: "Sealed class extracted with symbol_type='sealed_class'"
  - id: AC-3
    when: "Mining a .kt file with an object declaration"
    then: "Object extracted with symbol_type='object'"
  - id: AC-4
    when: "Mining a .kt file with companion object"
    then: "Companion object does NOT create a spurious boundary splitting the enclosing class"
  - id: AC-5
    when: "Mining a .kt file with suspend fun and extension fun"
    then: "Both extracted with symbol_type='function'; extension fun captures the function name (not receiver)"
  - id: AC-6
    when: "Mining a .kt file with enum class"
    then: "Extracted with symbol_type='enum'"
  - id: AC-7
    when: "Mining a .kts Gradle script"
    then: "File is recognized (language='kotlin') and chunked via chunk_code, not adaptive fallback"
  - id: AC-8
    when: "Running existing test suite after changes"
    then: "All existing tests pass — no regressions"
  - id: AC-9
    when: "Mining a .kt file with a typealias"
    then: "Extracted with symbol_type='typealias'"
  - id: AC-10
    when: "Mining a .kt file with an interface"
    then: "Extracted with symbol_type='interface'"
out_of_scope:
  - "Tree-sitter Kotlin parser — tree-sitter-kotlin is not in pyproject.toml; regex path only"
  - "DSL builder detection — DSL builders are plain functions/lambdas; no special symbol type needed"
  - "Coroutine scope detection (launch, async blocks) — these are function calls, not declarations"
  - "Property extraction (val/var) — top-level val/var are rarely the primary anchor of a chunk; may be added later"
  - "Multiplatform expect/actual — out of scope for initial support"
  - "MCP server changes — no new filter parameters"
---

## Design Notes

- **Follows the MINE-JAVA-SMART pattern exactly.** Java was added with `JAVA_BOUNDARY` + `_JAVA_EXTRACT` + dispatch entries. Kotlin follows the same four-step recipe: boundary regex, extraction patterns, map registrations, dispatcher update.

- **`EXTENSION_LANG_MAP` — add two entries (~line 35, after `.java`):**
  ```
  ".kt": "kotlin",
  ".kts": "kotlin",
  ```

- **`READABLE_EXTENSIONS` — add `.kt` and `.kts` (~line 95, after `.java`).**

- **`KOTLIN_BOUNDARY` — add after `JAVA_BOUNDARY` (~line 522).** Match stripped lines (Kotlin members are indented inside classes, same as Java/Python/Go). Patterns:

  1. **Type declarations:** `(?:(?:public|internal|protected|private|abstract|final|open|sealed|data|inner|value|annotation)\s+)*(?:class|interface|object)\s+\w+` — covers `class`, `data class`, `sealed class`, `inner class`, `value class`, `annotation class`, `object`, `interface`. Note: `sealed interface` (Kotlin 1.5+) is also matched since `sealed` is in the modifier list and `interface` is a keyword.

  2. **Enum class:** `(?:(?:public|internal|protected|private)\s+)*enum\s+class\s+\w+` — Kotlin enums use `enum class`, not bare `enum`.

  3. **Functions:** `(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*fun\s+` — matches `fun`, `suspend fun`, `inline fun`, `override fun`, extension functions, etc. Requires the `fun` keyword, which prevents matching property declarations or arbitrary expressions.

  4. **Typealias:** `(?:(?:public|internal|protected|private)\s+)*typealias\s+\w+` — top-level type aliases.

  **Deliberately excludes:**
  - `companion object` as a standalone boundary — companion objects are nested inside classes and splitting there would break the enclosing class chunk. They are handled as part of the class body. The `object` keyword in pattern (1) only matches standalone/named `object Foo` declarations.
  - `val`/`var` properties — too noisy as boundaries; top-level properties are typically small and merge well with adjacent declarations.

- **`get_boundary_pattern()` — add `"kotlin"` and `".kt"` entries (~line 551).** Maps to `KOTLIN_BOUNDARY`.

- **`_KOTLIN_EXTRACT` — add after `_JAVA_EXTRACT` (~line 705).** Ordered most-specific first. Patterns use `re.MULTILINE` + one capture group for symbol name:

  1. `data\s+class\s+(\w+)` → `"data_class"` — must precede plain `class`
  2. `sealed\s+class\s+(\w+)` → `"sealed_class"` — must precede plain `class`
  3. `sealed\s+interface\s+(\w+)` → `"sealed_interface"` — must precede plain `interface`
  4. `enum\s+class\s+(\w+)` → `"enum"` — Kotlin's `enum class`
  5. `companion\s+object` → `"companion_object"` — no name capture (companion objects are typically unnamed); returns `("", "companion_object")`
  6. `object\s+(\w+)` → `"object"` — standalone object declarations
  7. `(?:modifiers\s+)*interface\s+(\w+)` → `"interface"`
  8. `(?:modifiers\s+)*class\s+(\w+)` → `"class"` — covers `abstract class`, `open class`, `inner class`, `value class`, `annotation class`
  9. `(?:modifiers\s+)*fun\s+(?:\w+\.)?(\w+)` → `"function"` — captures function name; for extension functions like `fun String.isEmpty()`, captures `isEmpty` (not `String`). The optional `\w+\.` handles the receiver type prefix.
  10. `typealias\s+(\w+)` → `"typealias"`

  Modifier prefix for patterns 7-9: `(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*`

  **Companion object pattern note:** The extraction pattern for `companion object` is in the list but `KOTLIN_BOUNDARY` does NOT split on `companion object`. This means `companion object` only appears as part of an enclosing class chunk. `extract_symbol()` will match the *class* declaration first (higher priority), which is the correct behavior — the companion object content stays inside the class chunk.

- **`_LANG_EXTRACT_MAP` — add `"kotlin": _KOTLIN_EXTRACT`** (~line 717).

- **`chunk_file()` dispatch — add `"kotlin"` to the first branch** (~line 756):
  ```python
  if language in ("python", "typescript", "javascript", "tsx", "jsx", "go", "rust", "java", "kotlin"):
  ```

- **`is_ts_js` check in `chunk_code`** — Kotlin must NOT be in this set; it uses stripped-line matching (same as Java/Python/Go), correctly handling indented members.

- **Extension function receiver types.** The extraction regex `fun\s+(?:\w+\.)?(\w+)` handles simple receivers like `String.isEmpty()`. Generic receivers like `List<T>.first()` are matched by `fun\s+(?:[\w<>,\s]+\.)?(\w+)` — but the simpler pattern covers the 90% case. Use `[\w<>,?\s]+\.` only if generic receivers are common in test corpus. Start simple.

- **Tests structure.** New `# KOTLIN` section at the bottom of `tests/test_symbol_extract.py`, after Java. One test function per symbol type:
  - `test_kotlin_class` — `class UserService {`
  - `test_kotlin_data_class` — `data class Point(val x: Int, val y: Int)`
  - `test_kotlin_sealed_class` — `sealed class Result {`
  - `test_kotlin_sealed_interface` — `sealed interface State`
  - `test_kotlin_object` — `object Database {`
  - `test_kotlin_interface` — `interface Repository<T> {`
  - `test_kotlin_enum_class` — `enum class Color { RED, GREEN, BLUE }`
  - `test_kotlin_fun` — `fun process(input: String): String {`
  - `test_kotlin_suspend_fun` — `suspend fun fetchData(): List<Item> {`
  - `test_kotlin_extension_fun` — `fun String.isPalindrome(): Boolean {`
  - `test_kotlin_annotation_prefixed_fun` — `@JvmStatic\nfun create(): Builder {` → `("create", "function")`
  - `test_kotlin_typealias` — `typealias UserId = String`
  - `test_kotlin_private_class` — `private class Internal {`
  - `test_kotlin_property_not_extracted` — `val name: String = "test"` → `("", "")`
  - `test_kotlin_chunk_no_spurious_companion_boundary` — class with companion object stays in one chunk
  - `test_kotlin_chunk_class_with_two_funs` — class with two `fun` → at most 2 content chunks
