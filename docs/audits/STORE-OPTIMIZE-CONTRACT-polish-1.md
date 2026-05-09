slug: STORE-OPTIMIZE-CONTRACT
phase: polish
date: 2026-05-09
commit_range: 4546c75..8c78e8a
reverted: false
findings:
  - id: P-1
    title: "Duplicate test: test_mine_default_calls_optimize_store_backup_first"
    category: structural
    location: "tests/test_miner.py:2131"
    evidence: "Identical setup and assertions as test_mine_default_calls_safe_optimize_backup_first directly above it; also contained a redundant `import tempfile` when the module already imports it at line 3; used a defensive positional-args fallback in the assertion that can never trigger since optimize_store is always called with backup_first as a keyword."
    decision: fixed
    fix: "Removed the entire duplicate test function."

  - id: P-2
    title: "Duplicate test: test_mine_convos_default_calls_optimize_store_backup_first"
    category: structural
    location: "tests/test_convo_miner.py:92"
    evidence: "Identical setup and assertions as test_mine_convos_default_calls_safe_optimize_backup_first directly above it; same defensive positional-args fallback."
    decision: fixed
    fix: "Removed the entire duplicate test function."

  - id: P-3
    title: "Duplicate test: test_adapter_failure_prints_skipped"
    category: structural
    location: "tests/test_watcher.py:1013"
    evidence: "Same OptimizeResult(ok=False) patch and same _optimize_once call as test_backup_gate_rejected_skips_optimize; assertion is strictly weaker ('skipped' vs 'skipped (backup gate failed)')."
    decision: fixed
    fix: "Removed the duplicate test function."

  - id: P-4
    title: "Duplicate test: test_unsupported_store_prints_done"
    category: structural
    location: "tests/test_watcher.py:1030"
    evidence: "_optimize_once does not inspect result.supported, so OptimizeResult(ok=True, supported=False) exercises the same code path as test_backup_gate_success_prints_done which already asserts 'done'."
    decision: fixed
    fix: "Removed the duplicate test function."

  - id: P-5
    title: "Trivial OptimizeResult docstring restates the class name"
    category: verbal
    location: "mempalace_code/storage.py:192"
    evidence: "\"\"\"Result returned by optimize_store().\"\"\" — the class name OptimizeResult already communicates this; the docstring adds no information."
    decision: fixed
    fix: "Removed the docstring."

totals:
  fixed: 5
  dismissed: 0
fixes_applied:
  - "Removed duplicate test test_mine_default_calls_optimize_store_backup_first from test_miner.py (also removed its internal duplicate import tempfile and defensive positional-args assertion)."
  - "Removed duplicate test test_mine_convos_default_calls_optimize_store_backup_first from test_convo_miner.py."
  - "Removed duplicate test test_adapter_failure_prints_skipped from test_watcher.py."
  - "Removed duplicate test test_unsupported_store_prints_done from test_watcher.py."
  - "Removed trivial docstring from OptimizeResult dataclass in storage.py."
