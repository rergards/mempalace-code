---
slug: CODE-TREESITTER-GO-RUST-DETACH-TEST
goal: "Add negative tests proving detached Go and Rust comments stay out of the following declaration chunk."
risk: low
risk_note: "Test-only change in existing AST chunking coverage; production behavior is unchanged unless the tests expose a real regression."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: the scope is a narrow test-only guard in one file, no auth/data/migration/provider/pipeline boundary is touched, and verification is fully automated."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: tests/test_chunking.py
    change: "Add Go and Rust negative detached-comment tests and extend the local fixtures, if needed, so adaptive merging cannot mask the gap boundary."
acceptance:
  - id: AC-1
    when: "tree-sitter-go is available and the new Go detached-comment test runs against the Go AST fixture"
    then: "the chunk containing the following declaration does not include the detached comment text, and the test passes."
  - id: AC-2
    when: "tree-sitter-rust is available and the new Rust detached-comment test runs against the Rust AST fixture"
    then: "the chunk containing the following declaration does not include the detached comment text, and the test passes."
  - id: AC-3
    when: "the Go and Rust fixture bodies are inspected through the tests'"'"' final chunks"
    then: "the detached comments still appear somewhere in output, but only in the separate comment chunk, not absorbed into the declaration chunk."
  - id: AC-4
    when: "the chunker gap check is removed from either Go or Rust implementation and the new detached-comment tests are re-run"
    then: "the affected test fails because the detached comment is absorbed into the following declaration chunk."
out_of_scope:
  - "Production chunker helper changes unless a new negative test reveals a live regression."
  - "Backlog metadata updates or archive transitions."
  - "Non-AST chunking behavior and unrelated parser fixtures."

## Design Notes

- Reuse the existing Go and Rust positive-attached fixtures as the starting point, then add a blank-line-separated detached comment case for each language.
- Keep the assertion targeted to the chunk containing the following declaration, not a broad file-wide substring search, so the test proves attachment behavior precisely.
- If the detached example bodies are too small and get merged by `adaptive_merge_split`, pad them inside the fixture strings rather than changing the chunking algorithm.
- Preserve the current skip behavior for missing tree-sitter grammars.
