---
slug: DOTNET-SYMBOL-GRAPH
status: completed
authority: non_authoritative
goal: "Detect interface-implementation and inheritance relationships from C#/F#/VB.NET source files during mining and store them as KG triples queryable via mempalace_kg_query"
risk: medium
risk_note: "Regex-based extraction on C# source is inherently heuristic — relies on I-prefix convention to distinguish interfaces from base classes, and cannot resolve using-aliased or fully-qualified type names. Proven viable by existing CSHARP_BOUNDARY/extract_symbol() pattern."
files:
  - path: mempalace/miner.py
    change: "Add extract_type_relationships() dispatcher + per-language helpers (_csharp_type_rels, _fsharp_type_rels, _vbnet_type_rels). Expand _KG_EXTRACT_EXTENSIONS to include .cs/.fs/.fsi/.vb. Wire new extractor into the KG dispatch block in mine()."
  - path: tests/test_kg_extract.py
    change: "Add test class/functions for C# type relationships (~15 cases incl. record class/struct forms), F# type relationships (~6 cases), VB.NET type relationships (~6 cases), KG lifecycle tests for .cs/.fs/.vb re-mining, multi-project mine+query integration test (AC-12), and incoming-query end-to-end assertions (AC-8/AC-9)."
acceptance:
  - id: AC-1
    when: "A C# file contains `public class Foo : IBar, IBaz`"
    then: "KG contains (Foo, implements, IBar) and (Foo, implements, IBaz) triples"
  - id: AC-2
    when: "A C# file contains `public class Child : ParentClass`"
    then: "KG contains (Child, inherits, ParentClass) triple"
  - id: AC-3
    when: "A C# file contains `public class Svc : BaseService, IDisposable`"
    then: "KG contains (Svc, inherits, BaseService) and (Svc, implements, IDisposable)"
  - id: AC-4
    when: "A C# file contains `public struct Point : IEquatable<Point>`"
    then: "KG contains (Point, implements, IEquatable) — generic parameter stripped"
  - id: AC-5
    when: "A C# file contains `public interface IFoo : IBar, IBaz`"
    then: "KG contains (IFoo, extends, IBar) and (IFoo, extends, IBaz)"
  - id: AC-6
    when: "An F# file contains `type MyClass() = inherit Base()` and `interface IFoo with`"
    then: "KG contains (MyClass, inherits, Base) and (MyClass, implements, IFoo)"
  - id: AC-7
    when: "A VB.NET file contains `Inherits BaseClass` and `Implements IFoo, IBar` inside a Class block"
    then: "KG contains (ClassName, inherits, BaseClass), (ClassName, implements, IFoo), (ClassName, implements, IBar)"
  - id: AC-8
    when: "mempalace_kg_query('IMyInterface', direction='incoming') is called after mining"
    then: "Returns all types with predicate 'implements' pointing to IMyInterface"
  - id: AC-9
    when: "mempalace_kg_query('BaseClass', direction='incoming') is called after mining"
    then: "Returns all types with predicate 'inherits' pointing to BaseClass"
  - id: AC-10
    when: "A .cs file is modified and re-mined"
    then: "Old type-relationship triples from that source_file are invalidated before new ones are added"
  - id: AC-11
    when: "A .cs file is deleted and the stale sweep runs"
    then: "Its type-relationship triples are invalidated"
  - id: AC-12
    when: "Mining a multi-project .NET solution with cross-project interfaces"
    then: "All implementers across projects are discoverable via kg_query on the interface name"
out_of_scope:
  - "Full Roslyn/semantic analysis — regex heuristics only"
  - "Resolving fully-qualified or using-aliased type names (e.g. System.IDisposable stays IDisposable)"
  - "Generic type parameter tracking (List<T> stored as List)"
  - "Nested type relationships (inner classes)"
  - "Cross-file type usage references (method parameters, return types, field types)"
  - "Namespace-qualified entity identity — KG entities are keyed by short type name only (e.g. `IService`). Same-named types from different namespaces/projects will coalesce into one entity node. This is acceptable: it favors recall (all implementers found) over precision, and matches the KG's existing identity model. A future task can add namespace-qualified subjects if disambiguation is needed."
  - "New MCP tools — existing mempalace_kg_query with direction=incoming already satisfies the query use case"
---

## Design Notes

### Extraction strategy

- **C#**: Ordered matcher list (most-specific first, matching `_CSHARP_EXTRACT` style) captures
  type declarations (`record struct`, `record class`, bare `record`, `struct`, `interface`,
  `class`) and the optional base-type list after `:`. The base list is split using a depth-aware
  comma splitter (respects `<>` nesting) and generic suffixes are stripped to yield bare type names.

- **F#**: Scans for `type Name(...) =` declarations, then looks at subsequent indented lines
  for `inherit BaseType(...)` and `interface IFoo with` patterns. Each type declaration's scope
  extends until the next unindented `type` or `module` or EOF.

- **VB.NET**: Scans for `Class|Structure|Interface` declarations, then looks at subsequent
  lines for `Inherits TypeName` and `Implements IFoo, IBar` keywords (case-insensitive).

### Predicate taxonomy

| Declaring type | Base item | Predicate |
|---------------|-----------|-----------|
| class/record | Starts with `I` + uppercase | `implements` |
| class/record | Does not start with `I` + uppercase | `inherits` |
| struct | Any | `implements` (structs cannot inherit classes in C#) |
| interface | Any | `extends` (interface-to-interface inheritance) |

The `I`-prefix heuristic is the standard .NET naming convention (enforced by StyleCop/CA1715).
It covers ~99% of real-world code. Edge cases (e.g. a class named `Ice`) produce a wrong
predicate but the relationship is still recorded — the query still finds it, just under
`implements` instead of `inherits`.

### Regex for C# base-type capture

Uses an ordered matcher list (most-specific first) mirroring the established `_CSHARP_EXTRACT`
pattern in miner.py. This avoids the `record class Config` misparsing that a single regex would
produce.

```python
_CSHARP_TYPE_REL_MATCHERS = [
    # record struct — must precede struct and bare record
    (re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
        r"new|unsafe|readonly)\s+)*"
        r"record\s+struct\s+"
        r"(\w+)"                          # type name
        r"(?:<[^>]*>)?"                   # optional generic params
        r"(?:\s*\([^)]*\))?"              # optional record primary ctor
        r"\s*:\s*"                        # colon separator
        r"(.+)",                          # base list
        re.MULTILINE,
    ), "struct"),
    # record class — must precede class and bare record
    (re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
        r"new|unsafe)\s+)*"
        r"record\s+class\s+"
        r"(\w+)"
        r"(?:<[^>]*>)?"
        r"(?:\s*\([^)]*\))?"
        r"\s*:\s*"
        r"(.+)",
        re.MULTILINE,
    ), "class"),
    # bare record (implicitly a record class)
    (re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
        r"new|unsafe)\s+)*"
        r"record\s+"
        r"(\w+)"
        r"(?:<[^>]*>)?"
        r"(?:\s*\([^)]*\))?"
        r"\s*:\s*"
        r"(.+)",
        re.MULTILINE,
    ), "class"),
    # struct — before class
    (re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
        r"new|unsafe|readonly)\s+)*"
        r"struct\s+"
        r"(\w+)"
        r"(?:<[^>]*>)?"
        r"\s*:\s*"
        r"(.+)",
        re.MULTILINE,
    ), "struct"),
    # interface — before class
    (re.compile(
        r"^\s*(?:(?:public|private|protected|internal|new)\s+)*"
        r"interface\s+"
        r"(\w+)"
        r"(?:<[^>]*>)?"
        r"\s*:\s*"
        r"(.+)",
        re.MULTILINE,
    ), "interface"),
    # class (covers sealed, abstract, static, partial, etc.)
    (re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
        r"new|unsafe)\s+)*"
        r"class\s+"
        r"(\w+)"
        r"(?:<[^>]*>)?"
        r"\s*:\s*"
        r"(.+)",
        re.MULTILINE,
    ), "class"),
]
```

All matchers are tried in order; the first match wins. Each returns (type_name, base_list_str)
plus the type kind from the tuple.

Post-processing on the base list:
1. Truncate at first `where` keyword (generic constraints) or `{` or `//`
2. **Depth-aware comma split**: walk the string tracking `<`/`>` nesting depth; only split on
   commas at depth 0. This correctly handles nested generics like `Dictionary<string, List<int>>`
   where commas inside angle brackets are part of a single type argument, not separators between
   base types.
3. Strip each item's generic suffix: `IEquatable<Point>` → `IEquatable`
4. Strip whitespace, discard empties

The depth-aware splitter is a ~10-line helper (`_split_base_list`), not a parser — it counts
angle brackets and yields segments when it sees a comma at depth 0.

### Integration into mine()

The existing KG dispatch block (miner.py ~L2293) dispatches by extension. Adding `.cs`/`.fs`/`.vb`:

```python
elif filepath.suffix.lower() in (".cs", ".fs", ".fsi", ".vb"):
    triples = extract_type_relationships(filepath)
```

No changes to `_collect_specs_for_file()` or `add_triple()` API.

### Invalidation

`.cs`/`.fs`/`.vb` are added to `_KG_EXTRACT_EXTENSIONS`, so the existing invalidation guards
at L2273 and L2325 automatically cover them — no new invalidation code needed.

### No new MCP tools

`mempalace_kg_query('IMyInterface', direction='incoming')` already returns all subjects with
any predicate pointing to that entity. Filtering by predicate (`implements`, `inherits`,
`extends`) is done client-side from the returned facts list. This is sufficient for the use
case described in the task.

### Test plan

Tests go in `tests/test_kg_extract.py` alongside the existing .NET KG extraction tests:

- **C# (~15 cases)**: single interface, multiple interfaces, class + interfaces,
  struct implementing interface, interface extending interfaces, record with base,
  generic base types stripped, `where` constraints ignored, partial class,
  nested generics (`Dictionary<string, List<int>>`), no base type (no triple emitted),
  comments containing false-positive declarations skipped (inside `/* */` or `//`).
- **F# (~6 cases)**: inherit, single interface, multiple interfaces, no inheritance, type alias (no triple).
- **VB.NET (~6 cases)**: Inherits, single Implements, multi Implements on one line,
  Structure Implements, Interface Inherits, no inheritance.
- **C# record forms (~2 cases)**: `record class Config : IFoo` parsed as class/implements,
  `record struct Point : IEquatable<Point>` parsed as struct/implements. Regression coverage
  for explicit record forms matching `_CSHARP_EXTRACT` behavior.
- **KG lifecycle (~3 cases)**: re-mining .cs invalidates old triples, stale .cs file sweep
  invalidates triples, incremental skip (unchanged hash) does not re-emit triples.
- **Multi-project mine + query (~1 case, covers AC-12)**: mine two separate directories where
  project A defines `interface IService` and project B defines `class MySvc : IService`. After
  mining both, `kg.query_entity("IService", direction="incoming")` returns `MySvc` with
  predicate `implements`.
- **Incoming query assertions (covers AC-8/AC-9)**: at least one test calls
  `kg.query_entity(<interface>, direction="incoming")` and asserts that the returned facts list
  contains the expected subjects and predicates, exercising the actual KG API path end-to-end.
