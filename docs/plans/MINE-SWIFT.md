---
slug: MINE-SWIFT
goal: "Add Swift (.swift) language support to the code miner with regex-based symbol extraction for classes, structs, enums, protocols, actors, extensions, and functions"
risk: low
risk_note: "Follows established pattern — identical to how Kotlin, C#, Java were added. No existing code changes, only additions."
files:
  - path: mempalace/miner.py
    change: "Add .swift to EXTENSION_LANG_MAP, READABLE_EXTENSIONS; add SWIFT_BOUNDARY regex; add swift to get_boundary_pattern() mapping; add _SWIFT_EXTRACT pattern list; add swift to _LANG_EXTRACT_MAP; add swift to chunk_file() dispatch tuple"
  - path: tests/test_symbol_extract.py
    change: "Add Swift extract_symbol unit tests: class, struct, enum, protocol, actor, extension, func, async func, property wrapper, generics, access modifiers, no-match cases"
  - path: tests/test_miner.py
    change: "Add test_process_file_swift_roundtrip — full mine-and-query cycle on a .swift file"
acceptance:
  - id: AC-1
    when: "A .swift file containing `class UserService { ... }` is mined"
    then: "At least one drawer has language='swift', symbol_type='class', symbol_name='UserService'"
  - id: AC-2
    when: "A .swift file containing `struct Point { ... }` is mined"
    then: "Drawer has symbol_type='struct', symbol_name='Point'"
  - id: AC-3
    when: "A .swift file containing `protocol Codable { ... }` is mined"
    then: "Drawer has symbol_type='protocol', symbol_name='Codable'"
  - id: AC-4
    when: "A .swift file containing `extension Array where Element: Comparable { ... }` is mined"
    then: "Drawer has symbol_type='extension', symbol_name='Array'"
  - id: AC-5
    when: "A .swift file containing `actor DatabaseManager { ... }` is mined"
    then: "Drawer has symbol_type='actor', symbol_name='DatabaseManager'"
  - id: AC-6
    when: "A .swift file containing `public async func fetchData() -> [Item] { ... }` is mined"
    then: "Drawer has symbol_type='function', symbol_name='fetchData'"
  - id: AC-7
    when: "extract_symbol is called with a chunk containing only `let name: String = \"test\"` (a property, not a declaration)"
    then: "Returns ('', '') — properties are not extracted as symbols"
  - id: AC-8
    when: "A .swift file with a class using generics `class Container<T: Codable> { ... }` is mined"
    then: "symbol_name='Container', not 'T' or 'Codable'"
  - id: AC-9
    when: "A .swift file with `@propertyWrapper struct Clamped<Value: Comparable> { ... }` is mined"
    then: "symbol_type='struct', symbol_name='Clamped' (attribute does not break extraction)"
out_of_scope:
  - "Tree-sitter AST parsing for Swift (no tree_sitter_swift grammar in ecosystem yet)"
  - "SwiftUI-specific constructs (View body, modifiers) — these are regular structs/functions to the extractor"
  - "Swift Package Manager manifest parsing (Package.swift) — treated as regular Swift code"
  - "Objective-C interop annotations (@objc, @objcMembers) — captured by generic attribute handling"
---

## Design Notes

- **Regex-only, no tree-sitter.** No `tree_sitter_swift` grammar is available in the Python ecosystem. Swift joins the Java/Kotlin/C# regex tier.

- **Swift access modifiers:** `public`, `private`, `fileprivate`, `internal`, `open`. Declaration modifiers: `final`, `static`, `class` (as modifier on methods), `override`, `mutating`, `nonmutating`, `lazy`, `weak`, `unowned`, `nonisolated`. The extractor must handle arbitrary prefix chains of these.

- **Pattern ordering matters** (same as Kotlin):
  1. `final class` before plain `class` (avoid `final` being swallowed)
  2. `enum` before `extension` (both start with `e`)
  3. `actor` is a first-class type declaration (Swift 5.5+), not a modifier
  4. `protocol` before `func` (protocols contain func signatures that shouldn't match first)
  5. `extension Type` — capture the type name, ignore `where` constraints

- **Attribute lines (`@` prefix):** Swift uses `@propertyWrapper`, `@MainActor`, `@available`, etc. before declarations. The existing `comment_prefixes` lookback in `chunk_code()` already handles `//`, `/*`, `*` — Swift attributes start with `@`, so **no extension needed**: attributes appear on the line immediately before the declaration keyword, and the boundary regex anchors on the keyword line, so the lookback naturally captures the `@` line as a comment-adjacent prefix. The `_SWIFT_EXTRACT` patterns should also tolerate `@\w+\s+` prefixes inline for single-line annotations.

- **Boundary pattern:** Should include `class`, `struct`, `enum`, `protocol`, `actor`, `extension`, `func`, `typealias`. Exclude `var`/`let` properties (too noisy, same rationale as Kotlin excluding `val`/`var`).

- **`comment_prefixes` for Swift:** Swift doc comments use `///` and `/** */`, both already covered by the existing prefix set (`//`, `/*`, `*`, `/**`). No extension needed (unlike C# which needed `[` for attributes).

- **READABLE_EXTENSIONS:** Add `.swift` to the set so the file walker picks up Swift files.

- **Generics handling:** Reuse the Kotlin pattern `(?:<(?:[^<>]|<[^<>]*>)*>\s+)?` for depth-2 generic nesting (`Container<T: Comparable<T>>`).

- **No separate `indirect enum` type:** Swift's `indirect enum` is just an `enum` with a storage hint. The boundary/extract patterns match `enum` regardless of `indirect` prefix, which is correct.
