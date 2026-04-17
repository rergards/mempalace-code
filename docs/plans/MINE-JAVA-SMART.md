---
slug: MINE-JAVA-SMART
goal: "Add regex-based smart chunking and symbol extraction for Java to miner.py"
risk: low
risk_note: "Additive change only — new patterns and a dispatch entry; no existing language paths touched"
files:
  - path: mempalace/miner.py
    change: "Add JAVA_BOUNDARY, register in get_boundary_pattern(), add _JAVA_EXTRACT, register in _LANG_EXTRACT_MAP, dispatch Java to chunk_code() in chunk_file()"
  - path: tests/test_symbol_extract.py
    change: "Add Java test section covering class, interface, enum, record, annotation type, method, generics, annotations-prefixed method"
---

## Design Notes

- **No tree-sitter dependency.** `tree-sitter-java` is not in pyproject.toml and is out of scope. `get_parser("java")` returns `None`, so `chunk_code()` falls through to the existing regex path. All that's needed is `JAVA_BOUNDARY` + `_JAVA_EXTRACT`.

- **`JAVA_BOUNDARY` — add after `RUST_BOUNDARY` (~line 509).** Match stripped lines (Java methods are indented inside classes — same as Python/Go). Include:
  1. Type declarations: `(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*(?:class|interface|enum|record)\s+\w+`
  2. Annotation types: `(?:(?:public|protected)\s+)?@interface\s+\w+`
  3. Method/constructor: `(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|transient|volatile)\s+)+(?:<[^>]+>\s+)?[\w<>\[\],]+(?:\[\])*\s+\w+\s*\(`
  4. Annotations: `@\w+` — mirrors Python's `@decorator` in PY_BOUNDARY; tiny annotation-only chunks (e.g. `@Override`) are below `TARGET_MIN` and get merged into the following method chunk by `adaptive_merge_split`.

  The existing comment lookback in `chunk_code` already handles `//` and `/* */` — Java's two comment forms.

- **`get_boundary_pattern()` — add `"java"` entry (~line 543).** No extension key needed; EXTENSION_LANG_MAP already maps `.java` → `"java"`.

- **`_JAVA_EXTRACT` — add after `_CPP_EXTRACT` (~line 648).** Ordered most-specific first (same as all other languages). Patterns use `re.MULTILINE` and one capture group for the symbol name. Order:
  1. `@interface` → `"annotation"` — must precede `class` to avoid false "class" match on `interface`-like suffix
  2. `record` → `"record"` — Java 16+; matched before `class` since `record Foo()` doesn't start with `class`
  3. `interface` → `"interface"`
  4. `enum` → `"enum"`
  5. `class` → `"class"` — handles `abstract`, `final`, `sealed`, `non-sealed`, inner classes
  6. method/constructor → `"method"` — requires at least one modifier keyword (public/private/protected/static/...) to avoid matching local variable declarations; optional generic type parameter before return type

  Capture group grabs bare symbol name only (no generics, no `<T>`).

- **`_LANG_EXTRACT_MAP` — add `"java": _JAVA_EXTRACT`** (~line 660).

- **`chunk_file()` dispatch — add `"java"` to the first branch** (~line 698):
  ```python
  if language in ("python", "typescript", "javascript", "tsx", "jsx", "go", "rust", "java"):
  ```
  Since `chunk_code()` already falls back to `chunk_adaptive_lines` when `get_boundary_pattern()` returns `None`, adding `"java"` here is safe even before the boundary pattern is added — but both changes land together.

- **`is_ts_js` check in `chunk_code`** — Java must NOT be in this set; it uses stripped-line matching (same as Python/Go), which correctly handles indented methods inside class bodies.

- **Modifier keyword list for methods.** Include: `public`, `private`, `protected`, `static`, `final`, `abstract`, `synchronized`, `native`, `default`, `transient`, `volatile`, `strictfp`. Requiring at least one modifier (`+` quantifier) prevents the method pattern from matching field initializers or local variable assignments.

- **Generic type parameters.** The class name capture `class\s+(\w+)` grabs `HashMap` from `class HashMap<K, V>` — correct. The method extraction optional `(?:<[^>]+>\s+)?` handles `<T> Optional<T> findById(...)` — the capture group grabs only `findById`.

- **Tests structure.** New `# JAVA` section at the bottom of `tests/test_symbol_extract.py`. One test function per symbol type, matching the style of existing sections:
  - `test_java_class` — `public class UserService {`
  - `test_java_abstract_class` — `public abstract class BaseEntity {`
  - `test_java_interface` — `public interface Repository<T> {`
  - `test_java_enum` — `public enum Status { ACTIVE, INACTIVE }`
  - `test_java_record` — `public record Point(int x, int y) {`
  - `test_java_annotation_type` — `public @interface Component {`
  - `test_java_method_public` — `public void processRequest(...) {`
  - `test_java_method_private_static` — `private static void helper() {`
  - `test_java_method_generic` — `public <T> Optional<T> findById(Long id) {`
  - `test_java_annotation_prefixed_method` — chunk starting with `@Override\npublic String toString() {` must return `("toString", "method")`
  - `test_java_inner_class` — `private static class Builder {` (stripped)
  - `test_java_unknown_returns_empty` — verify `"java"` no longer returns `("", "")`; and `"ruby"` still returns `("", "")`
