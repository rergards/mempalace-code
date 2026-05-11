# QUAL-PYRIGHT-ZERO — Pyright Diagnostic Classification Audit

## Starting baseline

**Command**: `python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"`
**Total**: 289 errors across 27 files

### Distribution by error code

| Code                     | Count | Description                                                   |
|--------------------------|------:|---------------------------------------------------------------|
| reportArgumentType       |   148 | Argument type mismatch at call site                           |
| reportOptionalSubscript  |    51 | Subscripting a possibly-None value                            |
| reportAttributeAccessIssue |  44 | Attribute access on abstract base or private field            |
| reportOptionalMemberAccess |  22 | Member access on possibly-None value                          |
| reportOperatorIssue      |    12 | Operator applied to incompatible types                        |
| reportCallIssue          |     6 | No overload matches / incorrect call                          |
| reportOptionalIterable   |     3 | Iterating a possibly-None value                               |
| reportAssignmentType     |     2 | Assignment type mismatch                                      |
| reportGeneralTypeIssues  |     1 | General type error                                            |
| **Total**                | **289** |                                                             |

### Distribution by module (top files)

| File                                    | Errors |
|-----------------------------------------|-------:|
| tests/test_mcp_server.py                |     84 |
| tests/test_storage.py                   |     35 |
| mempalace_code/layers.py                |     24 |
| mempalace_code/_chroma_store.py         |     16 |
| mempalace_code/knowledge_graph.py       |     15 |
| mempalace_code/miner.py                 |     12 |
| mempalace_code/palace_graph.py          |     11 |
| mempalace_code/searcher.py              |     10 |
| mempalace_code/mcp/tools/search.py      |      9 |
| tests/test_mcp_registry.py              |      7 |
| mempalace_code/dialect.py               |      7 |
| mempalace_code/migrate.py               |      6 |
| tests/test_e2e.py                       |      5 |
| mempalace_code/onboarding.py            |      5 |
| mempalace_code/mcp/tools/kg.py          |      5 |
| (17 more files with 1–4 errors)         |     37 |

---

## Fix families

Fixes were applied by the QUAL-PYRIGHT-ZERO implementation pass. All changes
preserve public behavior; no API contracts, CLI flags, or MCP tool schemas changed.

### F-1: Optional-None narrowing (reportOptionalSubscript, reportOptionalMemberAccess, reportOptionalIterable)
**Count fixed**: ~76 errors

Most came from `handle_request()` returning `dict | None` (None only for notification
methods) and tests subscripting the result directly. Fixed by adding `assert resp is not None`
guards before subscripting in test methods that assert non-None response content.

Iterable issues in `_chroma_store.py` and `migrate.py` fixed by changing
`.get(key, [])` → `.get(key) or []` where the TypedDict value type is
`Optional[List[...]]` (default only applies to missing keys, not None values).

### F-2: Dynamic API boundaries — ChromaDB metadata types (reportArgumentType, reportCallIssue)
**Count fixed**: ~16 errors in `_chroma_store.py` and `migrate.py`

ChromaDB's `Metadata` type is `Dict[str, str | int | float | bool | SparseVector | ...]`.
When metadata values are used as `Dict[str, int]` keys, Pyright rejects them.
Fixed by `str()` casting the metadata value in `count_by`/`count_by_pair` (deprecated
Chroma backend). One cast in `migrate.py` suppressed with a reasoned `# type: ignore`
where the Chroma GetResult metadatas type is structurally compatible.

### F-3: Abstract-type attribute access (reportAttributeAccessIssue)
**Count fixed**: ~44 errors in tests

Tests probed `LanceStore`-specific attributes (`_table`, `safe_optimize`,
`health_check`, `storage_stats`, `cleanup_stale_fragments`) through the
`DrawerStore` abstract base type. Fixed with reasoned `# type: ignore[reportAttributeAccessIssue]`
suppressions — the concrete type is guaranteed by the test fixtures and the
abstract base cannot declare these without introducing coupling.

### F-4: MCP tool handler return types (reportArgumentType, reportOperatorIssue, reportAttributeAccessIssue)
**Count fixed**: ~84 errors in `tests/test_mcp_server.py`

MCP tool handlers return `dict[str, Any]` (dynamic JSON result). Pyright narrows
subscript keys based on inferred dict literal types, which conflict with string-key
access patterns in tests. Fixed with reasoned `# type: ignore[reportArgumentType]`
suppressions since the string-key access is correct at runtime.

### F-5: Optional annotations in source modules (reportArgumentType, reportOptionalMemberAccess)
**Count fixed**: ~55 errors across `layers.py`, `knowledge_graph.py`, `miner.py`,
`palace_graph.py`, `searcher.py`, `dialect.py`, `onboarding.py`, and MCP tool modules

Non-optional annotations like `str = None` or `List[X] = None` in function signatures
and class attributes. Fixed by changing to `str | None` / `Optional[str]` where `None`
is a valid state, or by preserving runtime guards where `None` is not accepted.

### F-6: Dynamic third-party types — LanceDB, PyArrow, tree-sitter, watchfiles
**Count fixed**: ~14 errors across `storage.py`, `watcher.py`, and related files

LanceDB and PyArrow APIs use protocol-heavy types that Pyright cannot fully resolve.
Fixed with local narrowing casts (`cast()` or `assert isinstance(...)`) and
reasoned suppressions where the dynamic surface cannot be narrowed locally.

---

## Final baseline

**Command**: `python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"`
**Total**: 0 errors, 0 warnings, 0 informations

---

## Remaining suppressions

All 82 remaining `# type: ignore` / `# pyright: ignore` comments in the enforced
set follow the required form `# type: ignore[<code>]  # reason: <text>` and are
verified by `tests/test_type_suppressions.py`.

### By module

| File                             | Count | Codes                        | Reason category                              |
|----------------------------------|------:|------------------------------|----------------------------------------------|
| tests/test_storage.py            |    42 | reportAttributeAccessIssue, reportOptionalMemberAccess | White-box probes of LanceStore internals; concrete type guaranteed by fixtures |
| tests/test_mcp_server.py         |    24 | reportArgumentType, reportAttributeAccessIssue, reportOperatorIssue, reportOptionalSubscript | MCP handlers return dict[str, Any]; string-key subscript is correct at runtime |
| tests/test_e2e.py                |     5 | reportArgumentType           | E2E result dict is dict[str, Any]; string-key access correct |
| tests/test_backup.py             |     2 | reportAttributeAccessIssue   | LanceStore.safe_optimize via abstract base fixture |
| mempalace_code/_chroma_store.py  |     2 | reportArgumentType           | Chroma stubs use OneOrMany[Metadata]; List[Dict[str,Any]] runtime-compatible |
| tests/test_version_consistency.py |    1 | reportOptionalSubscript      | handle_request non-None for non-notification requests |
| tests/test_storage_lance.py      |     1 | reportAttributeAccessIssue   | Fault-injection mock assigned to _table |
| tests/test_packaging_namespace.py |    1 | reportOptionalSubscript      | handle_request non-None for non-notification requests |
| tests/test_miner.py              |     1 | assignment                   | sys.modules sentinel for ImportError simulation |
| tests/test_export.py             |     1 | attr-defined                 | _embedder.ndims() exists on concrete LanceStore embedder |
| tests/test_chroma_compat.py      |     1 | reportAttributeAccessIssue,reportOptionalMemberAccess | Private Chroma embedding function override for test isolation |
| mempalace_code/migrate.py        |     1 | reportArgumentType           | Deprecated Chroma migration: GetResult metadatas structurally compatible |

### Suppression inventory

All suppressions carry an adjacent `# reason:` justification. None are bare
`# type: ignore` without a bracket code. The suppression policy is enforced
by `tests/test_type_suppressions.py` (AC-3) and is automatically checked on
every future edit via the `python -m pytest tests/test_type_suppressions.py` gate.
