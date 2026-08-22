---
slug: CODE-SEARCH-LANG-PROSE
status: completed
authority: non_authoritative
goal: "Add markdown, text, csv to SUPPORTED_LANGUAGES so code_search language= filter accepts prose and data drawers"
risk: low
risk_note: "Purely additive change to a whitelist; no existing behaviour changes"
files:
  - path: mempalace/searcher.py
    change: "Add 'markdown', 'text', 'csv' to SUPPORTED_LANGUAGES set under a new '# prose / data' comment block"
  - path: mempalace/mcp_server.py
    change: "Append 'markdown, text, csv' to the language description string in mempalace_code_search input schema"
  - path: tests/test_mcp_server.py
    change: "Add test_code_search_prose_languages_in_hint (hint regression guard) and test_code_search_markdown_language (AC-1 live filter test)"
acceptance:
  - id: AC-1
    when: "code_search(language='markdown') is called with a palace containing a markdown drawer"
    then: "Returns a results dict with no 'error' key and at least one hit"
  - id: AC-2
    when: "code_search(language='text') and code_search(language='csv') are called (any palace)"
    then: "Neither returns a validation error — both pass the SUPPORTED_LANGUAGES guard"
  - id: AC-3
    when: "code_search(language='notareal') is called"
    then: "'markdown', 'text', 'csv' all appear in result['supported_languages']"
  - id: AC-4
    when: "ruff check + ruff format --check run on modified files"
    then: "No violations"
out_of_scope:
  - "Changes to miner.py — EXTENSION_LANG_MAP already maps .md/.txt/.csv correctly"
  - "Changing VALID_SYMBOL_TYPES"
  - "Adding any new miner file-type support"
---

## Design Notes

- `SUPPORTED_LANGUAGES` in `searcher.py:157` is the sole validation gate for `code_search`. The three new strings must be added there; no other backend change is needed.
- The miner already emits `language="markdown"` for `.md`, `language="text"` for `.txt`, and `language="csv"` for `.csv` via `EXTENSION_LANG_MAP` (confirmed in miner.py). Drawers with these languages already exist in production palaces but are currently unreachable via `code_search(language=...)`.
- Group the new values under a `# prose / data` comment in `SUPPORTED_LANGUAGES`, consistent with the existing section comments (`# web`, `# data / query`, `# config`, `# devops / infrastructure`).
- MCP schema description at `mcp_server.py:663–666` is informational only; append `markdown, text, csv` to the example list so callers know these values are valid.
- Test pattern to follow: `test_code_search_yaml_language` (line 560) for the live-filter test, and `test_code_search_devops_languages_in_hint` (line 753) for the hint regression guard. Seed one markdown drawer inline (same pattern as yaml test) for the live-filter test.
- No migration needed: LanceDB stores language as a string metadata field; no schema change.
- `text` and `csv` are uncommon for `code_search` (no symbol extraction) but the validation gate should not block them — users may legitimately filter drawers mined from `.txt`/`.csv` data files.
