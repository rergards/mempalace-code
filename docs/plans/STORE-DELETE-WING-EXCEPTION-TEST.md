---
slug: STORE-DELETE-WING-EXCEPTION-TEST
goal: "Add a test that verifies tool_delete_wing returns {success: False, error: ...} when LanceStore.delete_wing raises"
risk: low
risk_note: "Test-only change; no production code touched"
files:
  - path: tests/test_mcp_server.py
    change: "Add test_delete_wing_storage_error to TestWriteTools, after test_delete_wing_not_found (line ~337)"
acceptance:
  - id: AC-1
    when: "test_delete_wing_storage_error is run against code that still has the bare except Exception: return 0 in LanceStore.delete_wing"
    then: "Test fails (the error dict path is never reached)"
  - id: AC-2
    when: "test_delete_wing_storage_error is run against the F-002-fixed code (bare except removed)"
    then: "Test passes — tool_delete_wing returns {success: False, error: 'simulated storage failure'}"
  - id: AC-3
    when: "`python -m pytest tests/ -x -q` is run"
    then: "All 284+ tests pass with no regressions"
  - id: AC-4
    when: "`ruff check tests/test_mcp_server.py` is run"
    then: "No lint errors"
out_of_scope:
  - "Any changes to production code (storage.py, mcp_server.py)"
  - "Testing ChromaStore exception paths"
  - "Testing count_rows failure (delete is the simpler, sufficient patch point)"
---

## Design Notes

- Place the new test in `TestWriteTools` immediately after `test_delete_wing_not_found` (~line 337). All delete-wing tests live there.
- The test needs `seeded_collection` so the wing existence pre-check in `tool_delete_wing` (`col.get(where={"wing": wing}, limit=1)`) returns a non-empty result and execution reaches `col.delete_wing(wing)`.
- Call `_get_store()` before patching to prime the module-level singleton. Because `_store` is a module-level singleton that is set once on first call, calling `_get_store()` in the test returns the same object `tool_delete_wing` will use internally — patching `delete_wing` on that object is sufficient.
- Patch `store.delete_wing` (not `store._table.delete`) — avoids reaching into LanceDB internals and tests the contract at the storage interface boundary.
- Use `"project"` as the wing name (present in `seeded_collection`) so the existence check passes.
- Assert both `result["success"] is False` and `"simulated storage failure" in result["error"]` to pin the full contract.

```python
def test_delete_wing_storage_error(self, monkeypatch, config, palace_path, seeded_collection, kg):
    _patch_mcp_server(monkeypatch, config, palace_path, kg)
    from mempalace.mcp_server import tool_delete_wing, _get_store

    store = _get_store()

    def explode(wing):
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(store, "delete_wing", explode)

    result = tool_delete_wing("project")
    assert result["success"] is False
    assert "simulated storage failure" in result["error"]
```
