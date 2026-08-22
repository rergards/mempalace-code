---
slug: PY-TYPE-KG
status: completed
authority: non_authoritative
goal: "Add Python type extraction to miner.py so that mining Python projects populates KG with class inheritance, ABC/Protocol implementation, and import dependency triples"
risk: low
risk_note: "Follows well-established pattern from C#/F#/VB.NET extractors; regex-based, no new dependencies; existing KG infra and arch tools unchanged"
files:
  - path: mempalace/miner.py
    change: "Add _python_type_rels() function, add .py to _KG_EXTRACT_EXTENSIONS, extend extract_type_relationships() dispatch"
  - path: tests/test_kg_extract.py
    change: "Add Python type-relationship extraction tests (class inheritance, multiple inheritance, ABC, Protocol, imports, edge cases, KG integration)"
acceptance:
  - id: AC-1
    when: "A .py file contains `class Foo(Bar):`"
    then: "extract_type_relationships returns (Foo, inherits, Bar)"
  - id: AC-2
    when: "A .py file contains `class Foo(Bar, Baz):`"
    then: "extract_type_relationships returns (Foo, inherits, Bar) and (Foo, inherits, Baz)"
  - id: AC-3
    when: "A .py file contains `class Foo(ABC):`"
    then: "extract_type_relationships returns (Foo, implements, ABC)"
  - id: AC-4
    when: "A .py file contains `class Foo(Protocol):`"
    then: "extract_type_relationships returns (Foo, implements, Protocol)"
  - id: AC-5
    when: "A .py file contains `from foo.bar import baz`"
    then: "extract_type_relationships returns (module_name, depends_on, foo.bar)"
  - id: AC-6
    when: "A .py file contains `import foo`"
    then: "extract_type_relationships returns (module_name, depends_on, foo)"
  - id: AC-7
    when: "A class declaration appears inside a `#` comment"
    then: "No triples are emitted for that line"
  - id: AC-8
    when: "A .py file contains `class Foo:` (no bases)"
    then: "No inheritance triples are emitted for Foo"
  - id: AC-9
    when: "`class Foo(Generic[T], Protocol):` with generic brackets"
    then: "Generic suffix is stripped: (Foo, inherits, Generic) and (Foo, implements, Protocol)"
  - id: AC-10
    when: "metaclass=ABCMeta in base list"
    then: "Keyword argument is skipped, not treated as a base class"
  - id: AC-11
    when: "`mempalace mine` runs on a Python project with a KG instance"
    then: "KG is populated with Python type triples; `kg.query_entity('Foo')` returns the inherits/implements facts"
  - id: AC-12
    when: "A .py file is modified and re-mined"
    then: "Stale Python type triples are invalidated before new ones are added"
  - id: AC-13
    when: "Existing C#/F#/VB.NET type extraction tests are run"
    then: "All pass unchanged (no regression)"
  - id: AC-14
    when: "A .py file is deleted and incremental mine (stale sweep) runs"
    then: "All Python KG triples sourced from that file are invalidated"
  - id: AC-15
    when: "After mining a Python project, an incoming KG query on a base class"
    then: "Returns the Python subclass(es) via inherits predicate (end-to-end architecture-query path)"
out_of_scope:
  - "Full AST parsing (stick to regex like .NET extractors)"
  - "Dynamic type inference or runtime type resolution"
  - "Third-party library type resolution (e.g., resolving whether a base is an ABC defined in another package)"
  - "Multiline class declarations spanning parentheses across lines (single-line regex covers >95% of real Python)"
  - "Dataclass/attrs struct-like detection (no clear KG predicate; can be added later)"
  - "Type alias extraction (`TypeAlias`, `TypeVar`)"
  - "Triple-quoted string/docstring suppression (only `#` line comments are stripped, matching .NET line-comment approach; class patterns inside docstrings are rare and accepted as false positives for v1)"
  - "Module name collisions across packages (module subject is filename stem or parent dir for `__init__.py` — can collide; acceptable for single-project mining scope)"
---

## Design Notes

- **Function**: Add `_python_type_rels(filepath: Path) -> list` following the exact same structure as `_csharp_type_rels`, `_fsharp_type_rels`, and `_vbnet_type_rels`. Returns `list[tuple[str, str, str]]` of (subject, predicate, object).

- **Class extraction regex**: Match `^class Name(bases):` at any indentation. Strip `#` line comments first (same approach as C# stripping `//` comments). Use a single compiled regex:
  ```
  ^\s*class\s+(\w+)\s*\(([^)]*)\)\s*:
  ```

- **Base list parsing**: Split by comma, strip whitespace, strip generic brackets (`Generic[T]` -> `Generic`), skip keyword args (`metaclass=...`, `total=...`).

- **Predicate assignment** (consistent with .NET conventions):
  - Base is `ABC`, `ABCMeta`, or `Protocol` -> `implements`
  - All other bases -> `inherits`
  - No `extends` for Python (Python has no interface-extends-interface concept)

- **Import extraction regex**: Two patterns, both emit `depends_on` (not `imports`) so that architecture tools (`find_references`, `extract_reusable`) surface them via existing `EXPANSION_PREDICATES` without mcp_server changes:
  - `^import (dotted.name)` -> `(module, depends_on, dotted.name)`
  - `^from (dotted.name) import ...` -> `(module, depends_on, dotted.name)`
  - Module name derived from filename stem (`foo.py` -> `foo`, `__init__.py` -> parent directory name). Note: this can collide across packages; acceptable for single-project scope (see out_of_scope).
  - Skip relative imports (`from . import x`, `from ..foo import bar`) — these are internal and noisy

- **Registration points**:
  1. Add `.py` to `_KG_EXTRACT_EXTENSIONS` frozenset
  2. Add `if ext == ".py": return _python_type_rels(filepath)` in `extract_type_relationships()`
  3. No changes needed in `mine()` — the existing `elif ext in (...): triples = extract_type_relationships(filepath)` block just needs `.py` added to the condition, OR simply adding `.py` to the set that triggers `extract_type_relationships` (lines 2616-2617)

- **mine() integration**: The `.py` extension must be handled in the KG extraction block (lines 2610-2621). Add `.py` alongside `.cs`, `.fs`, `.fsi`, `.vb` in the condition on line 2616 that calls `extract_type_relationships()`.

- **Docstring update**: Update `extract_type_relationships()` docstring (currently says ".NET source files" and lists only C#/F#/VB.NET) to include Python and the `depends_on` predicate.

- **Tests**: Add to `tests/test_kg_extract.py` following the existing `_cs()` / `_fs()` / `_vb()` helper pattern. Create a `_py(tmp_path, content)` helper. Test categories: simple inheritance, multiple inheritance, ABC, Protocol, imports (depends_on), metaclass kwarg, generics, comments, no-base class, integration with mine+KG, deleted-file stale sweep (AC-14, mirror `test_cs_stale_sweep_invalidates_triples`), and incoming-query end-to-end (AC-15, mirror `test_cs_incoming_query_base_class`).
