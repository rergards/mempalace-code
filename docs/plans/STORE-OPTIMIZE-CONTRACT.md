---
slug: STORE-OPTIMIZE-CONTRACT
status: completed
authority: non_authoritative
goal: "Make storage optimization an explicit optional capability with typed caller routing"
risk: low
risk_note: "Small API cleanup around existing optimize behavior; no schema, persistence, or default config changes."
files:
  - path: mempalace_code/storage.py
    change: "Define a typed optional safe-optimize capability and OptimizeResult status; add an optimize_store() adapter that calls LanceStore.safe_optimize when supported and otherwise uses the existing raw optimize/no-op fallback with supported=false status."
  - path: mempalace_code/miner.py
    change: "Replace the safe_optimize hasattr branch with optimize_store(); preserve existing success and warning output, backup_first routing, and optimize_after_mine disable behavior."
  - path: mempalace_code/convo_miner.py
    change: "Use the same optimize_store() adapter as miner.py for conversation mining post-flush optimization."
  - path: mempalace_code/watcher.py
    change: "Route _optimize_once through optimize_store() and use OptimizeResult status for done versus skipped output."
  - path: tests/test_storage.py
    change: "Cover optimize_store() for LanceStore success, backup failure, and a DrawerStore without safe_optimize support."
  - path: tests/test_miner.py
    change: "Update mining optimize tests to assert the adapter receives backup_first=True by default and that optimize disabled skips the adapter."
  - path: tests/test_convo_miner.py
    change: "Update conversation mining optimize tests to assert adapter routing instead of direct safe_optimize probing."
  - path: tests/test_watcher.py
    change: "Update _optimize_once tests to cover adapter success, adapter failure, and unsupported/no-op status."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_storage.py::TestSafeOptimize::test_adapter_lance_happy_path_returns_supported_result -q` is run"
    then: "optimize_store() on a healthy LanceStore returns ok=true and supported=true; row count is unchanged; a follow-up get(limit=1) succeeds"
  - id: AC-2
    when: "`python -m pytest tests/test_storage.py::TestSafeOptimize::test_adapter_backup_failure_returns_failed_result_and_skips_optimize -q` is run"
    then: "backup_first=true with create_backup raising OSError returns ok=false and supported=true; the underlying table optimize method is not called"
  - id: AC-3
    when: "`python -m pytest tests/test_storage.py::TestDrawerStoreBaseDefaults::test_optimize_store_unsupported_store_returns_noop_status -q` is run"
    then: "a DrawerStore subclass without safe_optimize returns ok=true and supported=false through optimize_store(), and no backup is attempted"
  - id: AC-4
    when: "`python -m pytest tests/test_miner.py::test_mine_default_calls_optimize_store_backup_first tests/test_convo_miner.py::test_mine_convos_default_calls_optimize_store_backup_first -q` is run"
    then: "mine() and mine_convos() route post-mine optimization through optimize_store(..., backup_first=True) under default config"
  - id: AC-5
    when: "`python -m pytest tests/test_watcher.py::TestOptimizeOnce::test_adapter_failure_prints_skipped tests/test_watcher.py::TestOptimizeOnce::test_unsupported_store_prints_done -q` is run"
    then: "_optimize_once reports skipped for an ok=false adapter result and reports done for the unsupported no-op status without falling through to another optimize call"
  - id: AC-6
    when: "`rg 'hasattr\\([^\\n]*safe_optimize' mempalace_code` is run"
    then: "there is no output; normal optimize paths no longer use untyped safe_optimize hasattr checks"
out_of_scope:
  - "Changing LanceDB optimize, cleanup, backup retention, or post-optimize verification semantics."
  - "Removing LanceStore.safe_optimize or changing its bool return contract for external callers."
  - "Changing ChromaDB legacy storage behavior beyond routing it through the no-op/status adapter."
  - "Changing optimize_after_mine or backup_before_optimize defaults."
---

## Design Notes

- Treat safe optimization as an optional storage capability, not a required DrawerStore method. Add a typed boundary in `storage.py`:
  - `OptimizeResult(ok: bool, supported: bool, message: str = "")`
  - `@runtime_checkable SafeOptimizeStore(Protocol)` with `safe_optimize(palace_path: str, backup_first: bool = False) -> bool`
  - `optimize_store(store: DrawerStore, palace_path: str, backup_first: bool = False) -> OptimizeResult`
- Keep `LanceStore.safe_optimize()` stable and returning `bool`. The adapter converts that bool into an `OptimizeResult` so callers can distinguish failure from unsupported/no-op status without changing the public LanceStore method.
- For stores without `SafeOptimizeStore`, `optimize_store()` should call `store.optimize()` to preserve the legacy fallback. Since `DrawerStore.optimize()` is already a no-op by default, unsupported stores keep current behavior while the returned status makes the no-op explicit.
- Import `optimize_store` into `miner.py`, `convo_miner.py`, and `watcher.py`; remove local `hasattr(..., "safe_optimize")` branches. Caller output should continue to print `done` on `ok=true` and warnings/skips on `ok=false`.
- Tests that currently rely on bare `MagicMock()` having any attribute should be tightened by patching the module-level `optimize_store` seam or using a small spec class. This prevents the old implicit attribute probing from reappearing in tests.
- Keep direct `LanceStore.safe_optimize()` tests that prove backup, retention, and read verification behavior. Add adapter-focused tests beside them rather than replacing storage safety coverage.
- Verification should use targeted tests plus an `rg` assertion for the removed `hasattr` pattern. Full suite is useful but not required for this small contract cleanup.
