slug: MCP-LAZY-STARTUP
phase: polish
date: 2026-05-01
commit_range: 2bbd1d7..07204f9
reverted: false
findings:
  - id: P-1
    title: "Single-use bool temporaries + redundant isinstance in _get_store"
    category: volume
    location: "mempalace_code/mcp_server.py:88-91"
    evidence: |
      table_missing = isinstance(new_store, LanceStore) and new_store._table is None
      if table_missing:
          db_absent = isinstance(new_store, LanceStore) and new_store._db is None
      The second isinstance re-evaluates what table_missing already established; table_missing
      and db_absent are single-use bools that add no clarity.
    decision: fixed
    fix: |
      Collapsed into nested ifs with a single isinstance guard that Pyright can use for
      type narrowing. Removed both single-use intermediates.

  - id: P-2
    title: "Dead _db is None guard in _open_or_create read_only branch"
    category: defensive
    location: "mempalace_code/storage.py:334"
    evidence: |
      if self._read_only:
          if self._db is None:   # unreachable — __init__ already returned early
              return None
      __init__ sets self._db = None and returns before calling _open_or_create, so
      _db is always non-None when the read_only branch of _open_or_create runs.
    decision: dismissed
    reason: |
      _open_or_create is a private method with no other callers today, but the guard
      costs a single attribute lookup and provides safety if the call graph ever changes.
      The benefit of removing it is negligible.

  - id: P-3
    title: "_get_kg docstring restates code"
    category: verbal
    location: "mempalace_code/mcp_server.py:61"
    evidence: |
      def _get_kg():
          """Return the KnowledgeGraph singleton, creating it on first call."""
      The function body makes both facts obvious.
    decision: dismissed
    reason: "One-line docstrings on lazy-singleton helpers are a common, harmless Python convention; removing offers no meaningful improvement."

totals:
  fixed: 1
  dismissed: 2
fixes_applied:
  - "Collapsed _get_store table_missing/db_absent bools into direct isinstance + nested if, removing redundant type check and two single-use temporaries (mcp_server.py:88-96)"
