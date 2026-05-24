verdict: READY

gaps: []

notes:
  - task_contract present with mode=standard; contract_policy.flow=full_spdd, sync_gate=required, verification_path=automated.
  - Each acceptance criterion (AC-1..AC-5) has at least one matching verification row (VER-1..VER-5) and at least one regression_plan.checks row (REG-1, REG-2, REG-3) via acceptance_ids.
  - All verification commands and regression_plan commands are concrete runnable shell commands (pytest -k filters, ruff check). No prose-only or "manual:" placeholders.
  - Files list (mempalace_code/storage.py, tests/test_mcp_server.py, tests/test_storage.py) is consistent with the proposed change: open existing Lance table before `_ensure_embedder()` and add unit + real stdio coverage. Confirmed against storage.py:407-457 where `_open_or_create` currently calls `_ensure_embedder()` eagerly on the write path before attempting `db.open_table`.
  - INV-1 explicitly preserves the existing runtime._get_store(create=True) upgrade-from-read-only behavior already exercised by TestDeleteAfterReadUpgrade in tests/test_mcp_server.py:3357 — no contradiction with prior architectural decisions.
  - INV-2/INV-3 keep embedder lazy-init on new-table schema creation and on add/upsert/query vector work, matching existing _embed() usage at storage.py:459-463 and add/upsert calls at storage.py:487-520.
  - Real stdio subprocess test pattern matches the existing TestCliFlags suite in tests/test_mcp_server.py:2430-2489, so the proposed AC-1/AC-2/AC-3 tests have a working precedent for spawning `python -m mempalace_code.mcp_server` with isolated HOME and asserting captured output.
  - Backlog metadata is not listed in files, surfaces, or touched_files; out_of_scope explicitly excludes backlog/archive edits.
  - Risks RISK-1/RISK-2/RISK-3 each have concrete mitigations tied to specific tests or implementation moves.
