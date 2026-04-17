---
slug: DOTNET-SYMBOL-GRAPH
goal: "Detect interface-implementation and inheritance relationships from C#/F#/VB.NET source files during mining and store them as KG triples queryable via mempalace_kg_query"
risk: medium
risk_note: "Regex-based extraction on C# source is inherently heuristic — relies on I-prefix convention to distinguish interfaces from base classes, and cannot resolve using-aliased or fully-qualified type names. Proven viable by existing CSHARP_BOUNDARY/extract_symbol() pattern."
files:
  - path: mempalace/miner.py
    change: "Add extract_type_relationships() dispatcher + per-language helpers (_csharp_type_rels, _fsharp_type_rels, _vbnet_type_rels). Expand _KG_EXTRACT_EXTENSIONS to include .cs/.fs/.fsi/.vb. Wire new extractor into the KG dispatch block in mine()."
  - path: tests/test_kg_extract.py
    change: "Add test class/functions for C# type relationships (~15 cases), F# type relationships (~6 cases), VB.NET type relationships (~6 cases), and KG lifecycle tests for .cs/.fs/.vb re-mining."
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
  - "New MCP tools — existing mempalace_kg_query with direction=incoming already satisfies the query use case"
---

## Design Notes

### Extraction strategy

- **C#**: Regex matches type declarations (`class|struct|interface|record`) and captures the
  optional base-type list after `:`. The base list is split on `,` and generic parameters
  (`<...>`) are stripped to yield bare type names.

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

```python
_CSHARP_TYPE_REL_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
    r"new|unsafe|file)\s+)*"
    r"(class|struct|interface|record)\s+"
    r"(\w+)"                          # type name
    r"(?:<[^>]*>)?"                   # optional generic params
    r"(?:\s*\([^)]*\))?"              # optional record primary ctor
    r"\s*:\s*"                        # colon separator
    r"(.+)",                          # base list (greedy — trimmed later)
    re.MULTILINE,
)
```

Post-processing on the base list:
1. Truncate at first `where` keyword (generic constraints) or `{` or `//`
2. Split on `,`
3. Strip each item's generic suffix: `IEquatable<Point>` → `IEquatable`
4. Strip whitespace, discard empties

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
- **KG lifecycle (~3 cases)**: re-mining .cs invalidates old triples, stale .cs file sweep
  invalidates triples, incremental skip (unchanged hash) does not re-emit triples.
