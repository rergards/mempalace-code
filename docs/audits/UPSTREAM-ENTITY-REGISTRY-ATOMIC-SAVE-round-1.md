slug: UPSTREAM-ENTITY-REGISTRY-ATOMIC-SAVE
round: 1
date: 2026-05-23
commit_range: 6b843b4..b019d7f
findings:
  - id: F-1
    title: "Codex P1 import-resolution issue does not apply in this worktree"
    severity: info
    location: "tests/test_entity_registry.py:10"
    claim: "Codex reviewed a snapshot where the installed package shadowed the worktree module, causing tests to import the old save() implementation. In this worktree, mempalace_code.entity_registry resolves to the local file (confirmed via __file__ check and all 4 tests passing with the new os.replace path exercised)."
    decision: dismissed

  - id: F-2
    title: "Raw fd could theoretically leak if os.fdopen raises before taking ownership"
    severity: low
    location: "mempalace_code/entity_registry.py:319"
    claim: "tempfile.mkstemp() returns a raw fd; if os.fdopen() raised an exception before acquiring the fd, tmp_fd would be leaked. With a valid fd and encoding='utf-8', os.fdopen cannot raise in CPython — and if it did, the fd would be orphaned rather than cleaned up by the exception handler."
    decision: dismissed

  - id: F-3
    title: "Parent directory fsync omitted after os.replace"
    severity: info
    location: "mempalace_code/entity_registry.py:327"
    claim: "Strict POSIX crash-safety can require fsyncing the parent directory after a rename to make the new directory entry durable on some filesystems. The current implementation only fsyncs the file content before replacing. The plan contract explicitly scopes this out and the acceptance criteria do not require it."
    decision: dismissed

  - id: F-4
    title: "No test for save() creating nested parent directories"
    severity: info
    location: "mempalace_code/entity_registry.py:313"
    claim: "mkdir(parents=True, exist_ok=True) is called but tests always use tmp_path directly, which already exists. An integration test for a multi-level config_dir path would give more confidence. Risk is very low given stdlib semantics."
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 4
fixes_applied: []
new_backlog: []
