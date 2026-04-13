slug: CODE-TREESITTER-INFRA
round: 1
date: 2026-04-14
commit_range: 5b8b555..0dffa8f
findings:
  - id: F-1
    title: "TypeScript/TSX grammar tests assert unconditionally — no skip guard"
    severity: medium
    location: "tests/test_treesitter.py:108-110,124-127"
    claim: >
      test_get_parser_typescript_returns_parser and test_get_parser_tsx_returns_parser
      assert `parser is not None` unconditionally. If tree-sitter is installed (importorskip
      passes) but the TypeScript grammar fails to load for any reason (ABI mismatch, corrupt
      install), the test errors rather than skipping. The Python grammar tests use
      `if parser is None: pytest.skip(...)` consistently; TypeScript/TSX tests do not.
      Affects treesitter-compat and treesitter-py39 CI jobs.
    decision: fixed
    fix: >
      Added `if parser is None: pytest.skip(...)` guard to both
      test_get_parser_typescript_returns_parser and test_get_parser_tsx_returns_parser,
      consistent with the Python grammar test pattern.

  - id: F-2
    title: "Silent grammar load failure — no diagnostic when [treesitter] extra is installed but grammar broken"
    severity: low
    location: "mempalace/treesitter.py:55-61"
    claim: >
      `get_parser()` uses `except Exception: return None` with no diagnostic output.
      A user who runs `pip install mempalace-code[treesitter]` and has a broken grammar
      (ABI mismatch, partially installed package, wrong Python version) receives silent
      regex fallback with no indication that AST chunking is not active. This defeats
      the purpose of installing the optional extra.
    decision: fixed
    fix: >
      Added `warnings.warn(..., RuntimeWarning)` inside the except block, emitting a
      message with the language name, exception type, and exception message. Also added
      `import warnings` at the top of treesitter.py. Updated
      test_get_parser_returns_none_when_grammar_import_fails to assert the warning is
      emitted (category, language string, exception type present in message).

  - id: F-3
    title: "Version ceiling <0.24 on treesitter extra needs periodic review"
    severity: low
    location: "pyproject.toml:52-56"
    claim: >
      The [treesitter] extra pins tree-sitter>=0.22,<0.24 and grammar packages >=0.23,<0.24.
      Tree-sitter 0.24+ exists and may introduce API changes. As the ecosystem evolves,
      users on newer pip resolvers that prefer latest versions would get dependency
      resolution failures once 0.22/0.23 packages age out. The ceiling is correct for
      the tested API surface but requires maintenance.
    decision: backlogged
    backlog_slug: TREESITTER-VERSION-PINS

  - id: F-4
    title: "No negative cache for failed grammar loads — repeated import retry on every call"
    severity: info
    location: "mempalace/treesitter.py:55-61"
    claim: >
      When a grammar package raises an exception, None is returned but the failure is
      not cached. Subsequent calls to get_parser() for the same broken language will
      retry the loader lambda. In practice Python's import system caches module lookups
      (ModuleNotFoundError path entries), making retries cheap. chunk_code() is called
      once per file in the miner — not a hot path. Performance impact is negligible.
    decision: dismissed

  - id: F-5
    title: "treesitter-py39 CI excludes tree-sitter-python by version marker — expected"
    severity: info
    location: ".github/workflows/ci.yml:44-52"
    claim: >
      The treesitter-py39 job installs .[dev,treesitter] on Python 3.9, but
      tree-sitter-python>=0.23 has `python_version >= '3.10'` marker and is therefore
      excluded. Tests that require the Python grammar correctly skip on 3.9
      (sys.version_info < (3,10) guard). Behavior is intentional and documented in the
      completion summary. No action needed.
    decision: dismissed

totals:
  fixed: 2
  backlogged: 1
  dismissed: 2

fixes_applied:
  - "Added warnings.warn(RuntimeWarning) in get_parser() except block (F-2)"
  - "Added import warnings to treesitter.py (F-2)"
  - "Added if parser is None: pytest.skip() guard to test_get_parser_typescript_returns_parser (F-1)"
  - "Added if parser is None: pytest.skip() guard to test_get_parser_tsx_returns_parser (F-1)"
  - "Strengthened test_get_parser_returns_none_when_grammar_import_fails to assert warning emitted (F-2)"

new_backlog:
  - slug: TREESITTER-VERSION-PINS
    summary: "Periodically review and update tree-sitter version ceilings in [treesitter] extra"
