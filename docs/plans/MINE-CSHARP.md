---
slug: MINE-CSHARP
goal: "Add regex-based smart chunking and symbol extraction for C# (.cs) to miner.py"
risk: low
risk_note: "Additive change only — new patterns and dispatch entries; no existing language paths modified. Follows proven Kotlin/Java pattern."
files:
  - path: mempalace/miner.py
    change: "Add .cs to EXTENSION_LANG_MAP and READABLE_EXTENSIONS, add CSHARP_BOUNDARY, register in get_boundary_pattern(), add _CSHARP_EXTRACT, register in _LANG_EXTRACT_MAP, add 'csharp' to chunk_file() dispatch"
  - path: tests/test_symbol_extract.py
    change: "Add C# test section covering class, struct, interface, record, enum, sealed class, abstract class, static class, partial class, method, async method, static method, generic method, constructor, property, event, indexer, operator, nested type, XML doc preservation, attribute attachment, and chunking edge cases"
  - path: tests/test_lang_detect.py
    change: "Add ('.cs', 'csharp') to the extension-based detection parametrize list"
acceptance:
  - id: AC-1
    when: "Mining a .cs file containing a class declaration"
    then: "Drawer has language='csharp', symbol_type='class', symbol_name matches the class name"
  - id: AC-2
    when: "Mining a .cs file with a struct declaration"
    then: "Extracted with symbol_type='struct'"
  - id: AC-3
    when: "Mining a .cs file with a record declaration (record class or record struct)"
    then: "Extracted with symbol_type='record'"
  - id: AC-4
    when: "Mining a .cs file with an interface"
    then: "Extracted with symbol_type='interface'"
  - id: AC-5
    when: "Mining a .cs file with an enum"
    then: "Extracted with symbol_type='enum'"
  - id: AC-6
    when: "Mining a .cs file with a method (public, static, async, generic)"
    then: "Extracted with symbol_type='method'; async and generic methods captured correctly"
  - id: AC-7
    when: "Mining a .cs file with properties (auto-property with get/set)"
    then: "Extracted with symbol_type='property'"
  - id: AC-8
    when: "Mining a .cs file with an event declaration"
    then: "Extracted with symbol_type='event'"
  - id: AC-9
    when: "Mining a .cs file with a constructor"
    then: "Extracted with symbol_type='constructor'; symbol_name matches the class name"
  - id: AC-10
    when: "Mining a .cs file with [Attribute]-prefixed declarations"
    then: "Attributes stay attached to the declaration chunk; symbol extracted from the declaration, not the attribute"
  - id: AC-11
    when: "Mining a .cs file with XML doc comments (/// lines)"
    then: "XML docs preserved in the drawer content as part of the chunk"
  - id: AC-12
    when: "Mining a .cs file with partial class declarations"
    then: "Partial class extracted with symbol_type='class'; partial keyword does NOT create spurious boundary splitting"
  - id: AC-13
    when: "Running existing test suite after changes"
    then: "All existing tests pass — no regressions"
out_of_scope:
  - "Tree-sitter C# parser — not in pyproject.toml; regex path only"
  - "Partial class cross-linking (tracking all parts of a partial class across files) — downstream enhancement"
  - "Region (#region / #endregion) detection — regions are IDE-only folding markers, not semantic"
  - "Delegate declarations — rare as standalone top-level constructs; may be added later"
  - "LINQ query expressions inside methods — internal to method bodies, not declarations"
  - "Preprocessor directives (#if, #define) — build config, not semantic declarations"
  - "MCP server changes — no new filter parameters"
  - "Field extraction (bare field declarations without accessors) — too noisy as boundaries; fields merge well with adjacent declarations"
  - "Namespace as a boundary — namespaces wrap entire files; splitting there would create one chunk per file which is the default anyway"
---

## Design Notes

- **Follows the MINE-KOTLIN / MINE-JAVA pattern exactly.** Same four-step recipe: boundary regex, extraction patterns, map registrations, dispatcher update.

- **`EXTENSION_LANG_MAP` — add one entry (~line 37, after `.kts`):**
  ```
  ".cs": "csharp",
  ```

- **`READABLE_EXTENSIONS` — add `.cs` (~line 99, after `.kts`).**

- **`CSHARP_BOUNDARY` — add after `KOTLIN_BOUNDARY` (~line 539).** Match stripped lines (C# members are indented inside classes/namespaces). Patterns:

  1. **Type declarations:** `(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*(?:class|struct|interface|record)\s+\w+` — covers `class`, `struct`, `interface`, `record`, `record class`, `record struct`, `partial class`, `sealed class`, `abstract class`, `static class`. The `partial` modifier is included in the prefix group so `partial class Foo` matches as a single declaration, not a separate boundary.

  2. **Enum:** `(?:(?:public|private|protected|internal|new)\s+)*enum\s+\w+` — C# enums use bare `enum`, not `enum class`.

  3. **Methods/constructors:** `(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe|async|partial)\s+)+(?:[\w<>\[\],?\s]+\s+)?(\w+)\s*[\(<]` — requires at least one modifier to avoid matching field declarations. The trailing `[\(<]` matches either `(` for methods/constructors or `<` for generic methods. Note: constructors don't have a return type, so the return type group is optional.

  4. **Properties:** `(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe)\s+)+[\w<>\[\],?\s]+\s+\w+\s*\{` — properties end with `{` (for `get;set;` block), distinguishing them from fields (which end with `;` or `=`).

  5. **Events:** `(?:(?:public|private|protected|internal|static|virtual|override|sealed|new|abstract)\s+)*event\s+` — the `event` keyword is the anchor.

  **Deliberately excludes:**
  - Namespace declarations — they wrap entire files; splitting at namespace boundaries would produce one chunk per namespace, which is the default file-level chunk anyway.
  - Bare field declarations (`private int _x;`) — too noisy as boundaries; they merge well with adjacent declarations.
  - Using directives (`using System;`) — import-like; not structural declarations.
  - `#region`/`#endregion` — IDE folding markers, not semantic structure.

- **`get_boundary_pattern()` — add `"csharp"` and `".cs"` entries (~line 572).**

- **`_CSHARP_EXTRACT` — add after `_KOTLIN_EXTRACT` (~line 765).** Ordered most-specific first. Patterns use `re.MULTILINE` + one capture group for symbol name:

  1. `record\s+struct\s+(\w+)` → `"record"` — must precede plain `record` and `struct`
  2. `record\s+class\s+(\w+)` → `"record"` — must precede plain `record` and `class`
  3. `record\s+(\w+)` → `"record"` — bare `record Foo` (implicitly a class)
  4. `(?:modifiers\s+)*enum\s+(\w+)` → `"enum"` — before class/struct
  5. `(?:modifiers\s+)*struct\s+(\w+)` → `"struct"` — before class (struct is more specific)
  6. `(?:modifiers\s+)*interface\s+(\w+)` → `"interface"` — before class
  7. `(?:modifiers\s+)*class\s+(\w+)` → `"class"` — covers sealed, abstract, static, partial, etc.
  8. `(?:modifiers\s+)*event\s+[\w<>\[\],?\s]+\s+(\w+)` → `"event"` — before methods (event keyword is unique anchor)
  9. `(?:modifiers\s+)*(\w+)\s*\(` where name matches class context → `"constructor"` — detect constructors by matching `ClassName(` pattern. Since extract_symbol works on chunks that typically start with the constructor, check if the matched name is preceded by modifier-only lines (no return type). Alternative: use a dedicated regex that matches `modifiers ClassName(` where ClassName is on the same line with no return type token before it.
  10. `(?:modifiers\s+)+[\w<>\[\],?\s]+\s+(\w+)\s*\{` → `"property"` — must be after methods; anchored by trailing `{` and requires at least one modifier
  11. `(?:modifiers\s+)+(?:[\w<>\[\],?\s]+\s+)?(\w+)\s*[\(<]` → `"method"` — general method/constructor catch-all; requires at least one modifier

  **Modifier prefix for C#:** `(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe|async|partial|readonly)\s+)*`

  **Constructor vs method disambiguation:** Constructors have no return type — the pattern is `modifiers ClassName(`. Methods have a return type — `modifiers ReturnType MethodName(`. Since extract_symbol scans the full chunk, the most reliable approach is: check if the captured name in a `method` match also appears as a type declaration keyword earlier in the chunk. However, the simpler approach (used by Java) is to rely on boundary splitting: constructors appear inside class chunks and the class itself is the primary symbol. For standalone constructor chunks (when a class has many members), the method pattern will capture the constructor name, and we accept `symbol_type='method'` for constructors as a pragmatic simplification.

  **Revised approach for constructors:** Add a dedicated constructor pattern that matches `modifiers ClassName(` where there is no return type between the modifiers and the name. This is `(?:modifiers\s+)+(\w+)\s*\(` — same as method but WITHOUT the return type group. Place it AFTER the method pattern and use a heuristic: if the method pattern's captured name equals a class/struct name found earlier in the chunk, reclassify as constructor. **Simpler alternative:** Just use a separate regex that checks for absence of return type: `^(?:(?:public|private|protected|internal|static|extern|unsafe)\s+)+(\w+)\s*\(` — this works because constructors have modifiers followed directly by the name and `(`, with no type in between. Place this BEFORE the general method pattern.

- **`_LANG_EXTRACT_MAP` — add `"csharp": _CSHARP_EXTRACT`** (~line 778).

- **`chunk_file()` dispatch — add `"csharp"` to the first branch** (~line 826):
  ```python
  if language in ("python", "typescript", "javascript", "tsx", "jsx", "go", "rust", "java", "kotlin", "csharp"):
  ```

- **XML doc comments (`///`).** These are leading comments like Python docstrings. The existing `chunk_code()` logic already preserves leading comment lines that are attached to a declaration (they stay in the same chunk because the boundary match happens at the declaration line, and content before the first boundary is part of the preceding chunk or header). XML docs naturally stay with their declarations because they immediately precede them. No special handling needed.

- **Attributes (`[Attribute]`).** Attributes are like Java annotations (`@Override`). They appear on lines before the declaration. The existing boundary regex does NOT match attribute-only lines (`[Serializable]`), so attributes naturally stay attached to the declaration in the same chunk. No special handling needed.

- **Partial classes.** `partial` is included in the modifier prefix for type declarations. `partial class Foo` matches the boundary and extracts as `("Foo", "class")`. Cross-file linking of partial class parts is explicitly out of scope.

- **Generic constraints.** `where T : IComparable` appears after the declaration signature, on the same or following lines. Since boundaries match at the start of declarations and chunks extend until the next boundary, generic constraints naturally stay within the declaration chunk. No special regex needed.

- **Nested types.** C# supports nested classes/structs/enums inside classes. Since boundaries match against stripped lines, a nested `public class Inner {` inside an outer class will match the boundary and create a separate chunk. This is correct behavior — nested types are distinct symbols.

- **`is_ts_js` check in `chunk_code`.** C# must NOT be in this set; it uses stripped-line matching (same as Java/Kotlin/Python/Go).

- **Tests structure.** New `# C#` section at the bottom of `tests/test_symbol_extract.py`, after Kotlin. One test function per symbol type, plus chunking edge cases:
  - `test_csharp_class` — `public class UserService {`
  - `test_csharp_struct` — `public struct Point {`
  - `test_csharp_interface` — `public interface IRepository<T> {`
  - `test_csharp_enum` — `public enum Color { Red, Green, Blue }`
  - `test_csharp_record` — `public record Person(string Name, int Age);`
  - `test_csharp_record_struct` — `public record struct Coordinate(double X, double Y);`
  - `test_csharp_sealed_class` — `public sealed class Singleton {`
  - `test_csharp_abstract_class` — `public abstract class Shape {`
  - `test_csharp_static_class` — `public static class Extensions {`
  - `test_csharp_partial_class` — `public partial class Generated {`
  - `test_csharp_method` — `public void Process(string input) {`
  - `test_csharp_static_method` — `public static int Calculate(int a, int b) {`
  - `test_csharp_async_method` — `public async Task<string> FetchAsync() {`
  - `test_csharp_generic_method` — `public T Convert<T>(object input) where T : class {`
  - `test_csharp_constructor` — `public UserService(ILogger logger) {`
  - `test_csharp_property` — `public string Name { get; set; }`
  - `test_csharp_event` — `public event EventHandler<EventArgs> OnChanged;`
  - `test_csharp_attribute_prefixed_method` — `[HttpGet]\npublic IActionResult Index() {` → `("Index", "method")`
  - `test_csharp_xml_doc_attached` — `/// <summary>` lines stay in chunk
  - `test_csharp_field_not_extracted` — `private int _count;` → `("", "")`
  - `test_csharp_using_not_extracted` — `using System;` → `("", "")`
  - `test_csharp_chunk_nested_class_boundary` — nested class creates separate chunk
  - `test_csharp_chunk_class_with_methods` — class + methods split into boundary-driven chunks
