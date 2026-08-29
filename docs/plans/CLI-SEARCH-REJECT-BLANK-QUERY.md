---
slug: CLI-SEARCH-REJECT-BLANK-QUERY
status: completed
authority: non_authoritative
goal: "Reject blank CLI search queries with a usage error before semantic-search model loading"
risk: low
risk_note: "The change is a local CLI input guard with focused regression coverage and no programmatic search contract change."
files:
  - path: mempalace_code/cli_commands/query.py
    change: "Validate the CLI query before importing or invoking the semantic-search path; emit a bounded stderr error and exit 2 for blank input."
  - path: tests/test_cli.py
    change: "Cover empty, whitespace-only, and nonblank CLI queries, including proof that invalid input cannot reach the lazy search/model path."
acceptance:
  - id: AC-1
    when: "the CLI search command receives an empty-string query"
    then: "it exits 2, names `query`, prints one concrete nonblank `mempalace-code search` retry command on stderr, and does not import or invoke the semantic-search path"
  - id: AC-2
    when: "the CLI search command receives a query containing only spaces, tabs, or newlines"
    then: "it produces the same bounded exit-2 error and concrete retry command as an empty query and does not load the search model"
  - id: AC-3
    when: "the CLI search command receives a query containing at least one non-whitespace character, including a query with surrounding whitespace"
    then: "it passes the original query unchanged to the existing semantic-search path and preserves the current successful result behavior"
out_of_scope:
  - "Changing validation or behavior of the programmatic search and MCP APIs"
  - "Trimming, normalizing, or otherwise rewriting valid CLI query text"
  - "Repairing previously stored blank diary drawers"
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: scope is two existing files, behavior is one local CLI guard, verification is focused and deterministic, rollout is reversible, and operational impact is bounded; no auth, data, migration, provider, or pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Place the blank-query predicate at the first executable line of `cmd_search`, before the lazy `searcher` import, palace configuration lookup, storage access, or model initialization.
- Treat `args.query.strip() == ""` as invalid. Use the predicate only for rejection; pass valid `args.query` through unchanged.
- Reuse the existing CLI blank-input failure shape: a concise field-naming stderr error, one concrete nonblank retry command, and `SystemExit(2)`.
- Add focused CLI regression cases alongside the existing search command tests. Use a sentinel around the lazy semantic-search boundary so empty and whitespace-only cases prove early rejection without constructing a palace or loading an embedding model.
- Keep `searcher.search` and `searcher.search_memories` unchanged because the requested contract is CLI-specific.
