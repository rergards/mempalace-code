---
slug: FIX-LANCE-CORRUPT
status: completed
authority: non_authoritative
goal: "Detect LanceDB fragment corruption and recover via version rollback; surface errors instead of silent empty results."
risk: medium
risk_note: "Touches storage probe surface, MCP read tools, and CLI. Recovery path uses LanceDB's native table.restore() (documented, non-destructive rollback). Dry-run is the default for the recovery CLI. Pre-existing cmd_repair is preserved as the deep-rebuild fallback."
files:
  - path: mempalace/storage.py
    change: "Add LanceStore.health_check() -> dict and LanceStore.recover_to_last_working_version(dry_run: bool) -> dict. health_check() probes count_rows + head(1) + count_by_pair('wing','room'); classifies fragment-missing errors by message substring. recover_to_last_working_version() walks list_versions() newest→oldest, checkout() + probe each, and calls restore(v) on the newest working version when dry_run=False."
  - path: mempalace/cli.py
    change: "Add cmd_health (new) and sub.add_parser('health'). Extend cmd_repair with --dry-run and a new --rollback path that calls recover_to_last_working_version() before the existing extract-and-rebuild fallback. Register both in the dispatch dict and the module docstring."
  - path: mempalace/mcp_server.py
    change: "Replace bare try/except: pass in tool_status / tool_list_wings / tool_list_rooms / tool_get_taxonomy with a shared _degraded_response helper. When count() > 0 but taxonomy/count_by raises, return {..., 'error': 'palace degraded', 'diagnosis': <short reason>, 'hint': 'Run: mempalace health && mempalace repair --rollback --dry-run'}."
  - path: tests/test_storage.py
    change: "Add TestLanceHealth: (1) healthy store → health_check returns ok=True; (2) a corrupted store (simulated by renaming a data file under lance/) → health_check returns ok=False with the error surfaced; (3) recover_to_last_working_version(dry_run=True) reports the candidate version but leaves current version unchanged; (4) recover_to_last_working_version(dry_run=False) restores a readable version (only when list_versions has ≥2 healthy versions — otherwise returns recovered=False)."
  - path: tests/test_mcp_server.py
    change: "Add tests that monkeypatch store.count_by_pair to raise and verify tool_status returns an 'error' + 'hint' (not silent empty wings/rooms). Verify total_drawers still populates from count()."
  - path: tests/test_cli.py
    change: "Add test_health_command_healthy_palace (exit 0, stdout mentions 'ok') and test_repair_rollback_dry_run (invokes cmd_repair with --dry-run --rollback on a healthy palace; exit 0; no palace mutation)."
acceptance:
  - id: AC-1
    when: "LanceStore.health_check() is called on a healthy palace"
    then: "returns {'ok': True, 'total_rows': N, 'current_version': V, 'errors': []}; no exception propagates"
  - id: AC-2
    when: "LanceStore.health_check() is called on a palace with a renamed/missing fragment file under lance/"
    then: "returns {'ok': False, 'errors': [...]} with at least one error whose 'kind' is 'fragment_missing' or 'read_failed'; no exception propagates"
  - id: AC-3
    when: "recover_to_last_working_version(dry_run=True) is called on a corrupted store with at least one healthy prior version"
    then: "returns {'recovered': False, 'candidate_version': V, 'dry_run': True}; the table's current version is unchanged"
  - id: AC-4
    when: "recover_to_last_working_version(dry_run=False) is called on a corrupted store with at least one healthy prior version"
    then: "returns {'recovered': True, 'restored_to': V, 'rows_after': N}; health_check() on the same store afterwards returns ok=True"
  - id: AC-5
    when: "`mempalace health` is run on a healthy palace"
    then: "exit code 0; stdout contains 'ok' and the total drawer count"
  - id: AC-6
    when: "`mempalace repair --rollback --dry-run` is run on a palace"
    then: "exit code 0; no data modification; stdout shows the candidate version (or 'no healthy prior version')"
  - id: AC-7
    when: "tool_status() is called and count() > 0 but count_by_pair raises"
    then: "response includes 'error' and 'hint' keys (not {wings: {}, rooms: {}} with no diagnosis); total_drawers still reflects count()"
out_of_scope:
  - "Active auto-repair on MCP read paths (read-only server; recovery requires explicit CLI invocation)."
  - "Changing the default of optimize_after_mine / backup_before_optimize — already covered by STORAGE-SAFE-OPTIMIZE."
  - "Adding post-optimize re-verification beyond what safe_optimize already does (head(1) + count_rows) — out-of-scope per STORAGE-SAFE-OPTIMIZE design notes."
  - "Rewriting the existing cmd_repair extract-and-rebuild path. --rollback is additive; the existing behavior remains the default when --rollback is not passed."
  - "Backup retention/rotation for pre_optimize_*.tar.gz — tracked separately as STORAGE-BACKUP-RETENTION."
  - "ChromaStore health/recovery — ChromaDB is deprecated; no probe needed there."
  - "A generic DrawerStore.health_check() abstract method — LanceStore-only for now; callers gate with hasattr()."
  - "Binary search across versions. A linear newest→oldest walk with an early-exit probe is simpler and correct for the realistic version-count range (< ~100 in practice)."
---

## Design Notes

- **Detection vs. recovery are separate methods.** `health_check()` is read-only and side-effect-free. `recover_to_last_working_version()` mutates the table only when `dry_run=False` (via `table.restore(v)`, LanceDB's documented rollback primitive — not a destructive operation; it creates a new version pointing at the old manifest).

- **Probe shape.** A probe must touch each failure surface the 2026-04-16 incident exposed:
  1. `count_rows()` — cheap, touches manifest
  2. `head(1).to_pydict()` — touches at least one fragment's data
  3. `to_arrow().select(["wing", "room"])` streamed through `count_by_pair`-style group-by — touches every fragment's metadata columns
  Missing the third surface is what made the incident silent: `count()` worked while `count_by_pair` failed. The probe must exercise all three.

- **Error classification (best-effort).** LanceDB raises generic exceptions (`OSError`, `lance.LanceError`, etc.) whose `str(e)` typically contains `"No such file"` / `"object not found"` / `"IO error"` for fragment-missing cases. Classify by substring match into `{fragment_missing, read_failed, schema_error, other}`, always include the verbatim `str(e)` in the result. Do NOT over-invest in perfect classification; users care about "something is broken and what do I do next".

- **Version walk.** `table.list_versions()` returns a list of version dicts newest-last (per LanceDB docs). Walk in reverse. For each version prior to current:
  - `table.checkout(v['version'])`
  - run the probe
  - on success, record `candidate_version = v['version']` and break
  - on failure, continue
  After walking, if a candidate exists and `dry_run=False`: `table.restore(candidate_version)` and re-open the table handle so subsequent reads use the restored head. Always `checkout_latest()` (or equivalent) in a finally block when aborting a dry-run walk — a leftover checkout would leave the handle pinned to a historical version and mislead callers.

- **No destructive fallback in this task.** If `recover_to_last_working_version` finds no healthy version, return `{"recovered": False, "candidate_version": None}`. The existing `cmd_repair` extract-and-rebuild path is the human-driven last resort; this task wires rollback as the first-try recovery before that path. The existing path requires a readable table (it calls `store.count()` and `store.get()` up front) — so in the flow we call `rollback → if rolled back stop; else fall through to existing rebuild`, which is fine because the rebuild path will simply fail loudly on an unreadable table (per STORE-DELETE-WING hardening precedent: no more silent `except Exception: return 0`).

- **MCP surfacing.** The immediate user-facing fix is that `tool_status` today returns `{total_drawers: N, wings: {}, rooms: {}}` with no hint that anything is wrong (`try/except pass` at mcp_server.py:82–89 and the three sibling tools). Replace with: when the taxonomy call raises and `count()` succeeded, return `{..., "error": "palace degraded: <short message>", "hint": "Run: mempalace health && mempalace repair --rollback --dry-run"}`. The MCP surface stays read-only — it never auto-repairs. This matches the read-only server contract established elsewhere.

- **Test seams.**
  - For AC-2 (corrupted store): use `tempfile.mkdtemp()` to build a palace, insert a few drawers, close the store, then `os.rename()` a data file under `lance/mempalace_drawers.lance/data/*.lance` to simulate a missing fragment. Re-open the store and call `health_check()`. Do NOT delete — rename lets the fixture be torn down cleanly.
  - For AC-4: the same setup, but insert drawers in two phases with a `store.optimize()` (or at least another write) in between so that `list_versions()` has ≥2 versions. Corrupt a fragment from the latest write's file set so rolling back to the prior version is actually recoverable. If platform/LanceDB version makes this hard to stage deterministically, guard the test with `pytest.skip` and keep AC-3 (dry-run, no mutation) as the always-runnable coverage.
  - For AC-7: in `test_mcp_server.py`, monkeypatch the store's `count_by_pair` to raise `RuntimeError("fragment missing")`; assert the returned dict has `error` and `hint`. Do NOT patch `_get_store` — the singleton caching at mcp_server.py:48–62 means a real store must be opened; patch the method on the store instance after retrieval.

- **No auto-backup on recover.** `restore(v)` is itself reversible via another `restore()`; no tar backup is added on this path. The `cmd_repair` extract-and-rebuild path retains its existing `palace.backup` copytree behavior untouched.

- **Signal surface.** Exceptions inside `health_check` are caught and recorded; the method itself never raises (contract: returns a structured report). Exceptions inside `recover_to_last_working_version` during the version walk are caught per-version and recorded; exceptions from the final `restore()` call do propagate, since a failed restore is a terminal condition the caller must see.

- **CLI argparse shape.**
  - `mempalace health [--json]` — new parser. Default output is human-readable; `--json` emits the raw dict for scripting.
  - `mempalace repair [--dry-run] [--rollback]` — extend existing `p_repair`. `--rollback` selects the version-restore path; without it, the existing extract-and-rebuild path runs unchanged. `--dry-run` only has meaning with `--rollback` in this iteration; when passed to the rebuild path without rollback, print a message saying dry-run is not supported for full rebuild and exit 2.

- **Backlog spin-off.** If error classification turns out to need more granularity during implementation (e.g., distinguishing disk-full mid-write from post-hoc deletion), capture as `FIX-LANCE-CORRUPT-CLASSIFY` via `backlog add`.
