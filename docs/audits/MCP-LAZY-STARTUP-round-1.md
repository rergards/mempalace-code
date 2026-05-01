slug: MCP-LAZY-STARTUP
round: 1
date: "2026-05-01"
commit_range: 2bbd1d7..5ca9179
findings:
  - id: F-1
    title: "AC-1 and AC-5 import-blockers use deprecated find_module — silently no-op on Python 3.12+"
    severity: high
    location: "tests/test_mcp_server.py:2199,2332"
    claim: >
      The `_Blocker` and `_MinerBlocker` test helpers expose `find_module(self, name, path)` and
      `load_module(self, name)` to deny torch / sentence_transformers / mempalace_code.miner
      imports. Python 3.4 deprecated these legacy meta-path APIs and Python 3.12 stopped
      consulting them entirely — only `find_spec(name, path, target)` is invoked by the import
      machinery. Verified locally on the project's pinned 3.14 venv:
      `class _B: def find_module(...): ...; sys.meta_path.insert(0, _B()); import json` succeeds
      with the message "NOT blocked — find_module is deprecated".

      Consequence: AC-1 and AC-5 are no-op assertions on the supported Python versions. They
      would still pass even if mcp_server.py reverted the lazy imports and pulled torch eagerly
      at import time. AC-1 is the central regression gate for this whole task, so this
      undermines the test guarantee the task description specifically calls for.
    decision: fixed
    fix: >
      Switched both helpers to the modern `find_spec(self, name, path=None, target=None)` API
      that raises ImportError for blocked names. Added defense-in-depth assertions that check
      `sys.modules` post-call so the test fails if torch / sentence_transformers / miner is
      pulled in even by a future blocker bypass. AC-5 was additionally moved into a subprocess
      because in-process execution can't observe miner-not-imported when an earlier test has
      already imported the module — the subprocess test now also asserts the
      "Directory not found" error message rather than just `success is False`, so the early
      validation path is the one being exercised.
  - id: F-2
    title: "convo_miner.py import order regressed I001"
    severity: low
    location: "mempalace_code/convo_miner.py:21"
    claim: >
      `from .miner import get_batch_size, add_drawers_batch` lists names out of alphabetical
      order, which `ruff check` flags with I001. `ruff check` is part of the project
      lint gate so this would have blocked CI.
    decision: fixed
    fix: "Reordered to `from .miner import add_drawers_batch, get_batch_size`."
  - id: F-3
    title: "Dead branch in LanceStore._open_or_create read-only path"
    severity: info
    location: "mempalace_code/storage.py:333-335"
    claim: >
      `_open_or_create` contains `if self._read_only: if self._db is None: return None`, but
      `__init__` already early-returns with `_table = None` when `read_only=True` and the lance
      directory is missing — so `_open_or_create` is never invoked with `_db is None`. The
      branch is unreachable defensive code. Not a bug, just a minor code-smell observation.
    decision: dismissed
  - id: F-4
    title: "_ensure_embedder fd leak under fd-table exhaustion"
    severity: info
    location: "mempalace_code/storage.py:315-317"
    claim: >
      The setup sequence opens devnull, then `os.dup(1)`, then `os.dup(2)` before the try
      block. If `os.dup(2)` raises (EMFILE), `devnull` and `old_stdout` leak. This is the same
      observation dismissed in MCP-MINE-TRIGGER round 1 F-2 — it requires the process to be
      out of fds, at which point bigger problems exist. Refactoring `_ensure_embedder`
      reintroduced the exact same shape, so the original dismissal stands.
    decision: dismissed

totals:
  fixed: 2
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Replaced legacy find_module/load_module test blockers with find_spec; added sys.modules post-checks; moved AC-5 into a subprocess so a polluted sys.modules from earlier tests cannot mask a regression."
  - "Reordered imports in convo_miner.py to satisfy ruff I001."

new_backlog: []
