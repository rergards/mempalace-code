---
slug: CLI-SEARCH-BOUNDED-AGENT-FALLBACK
status: completed
authority: non_authoritative
goal: "Add an explicit compact CLI search format with bounded verbatim previews, exact source metadata, and safe read recovery while preserving default and MCP contracts."
risk: medium
risk_note: "The product change is local and reversible, but malformed legacy metadata or incomplete exact-wheel coverage could emit an unsafe recovery command or admit an unbounded agent fallback."
files:
  - path: mempalace_code/cli.py
    change: "Add the explicit compact search option without changing the default search arguments or result count semantics."
  - path: mempalace_code/cli_commands/query.py
    change: "Pass the compact-mode selection through the existing CLI search handler while preserving blank-query and taxonomy error behavior."
  - path: mempalace_code/searcher.py
    change: "Extend the existing print formatter with the 300-character compact preview, exact metadata, usable line-range checks, and shell-safe read recovery output."
  - path: tests/test_cli.py
    change: "Cover parser/handler wiring, default behavior, compact selection, result boundaries, blank input, and unknown-wing failure behavior."
  - path: tests/test_searcher.py
    change: "Cover compact output bounds, exact metadata, safe and unavailable recovery cases, hostile legacy metadata, and unchanged full default output."
  - path: scripts/release_readiness_gate.py
    change: "Extend the existing installed workflow roundtrip with compact success and one unknown-wing check while preserving its default full-search/full-read proof through the exact candidate-wheel console."
  - path: tests/test_release_readiness_gate.py
    change: "Cover the shared installed workflow predicates for legacy full search/read, compact recovery, bounded diagnostics, and failure behavior."
  - path: tests/test_cli_golden_scenarios.py
    change: "Exercise the shared installed workflow, including compact search and recovery, through the existing thin source-mode consumer."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing public quality scorecard after required source and test line changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable quality scorecard after required source and test line changes."
acceptance:
  - id: AC-1
    when: "an installed `mempalace-code search` is run with compact mode and `--results 3` against seeded hits containing long documents and usable metadata"
    then: "it returns at most three 300-character verbatim previews in a bounded payload and preserves each hit's wing, room, similarity, exact source_file, and available line range"
  - id: AC-2
    when: "compact hits contain usable or malformed line/source/wing metadata, including missing, blank, non-string, placeholder `?`, non-positive, reversed, and non-numeric values"
    then: "only hits with a usable line range and nonblank non-placeholder string source_file and wing receive one shell-copyable `mempalace-code read` command; every other hit reports recovery unavailable without inventing a command or range"
  - id: AC-3
    when: "search runs without compact mode or the existing programmatic and MCP search surfaces return a hit"
    then: "the CLI still prints the complete verbatim document by default and the programmatic and MCP result contracts remain unchanged"
  - id: AC-4
    when: "the exact candidate wheel is exercised by the installed-golden search scenario"
    then: "compact search passes through the installed console and the packaged minimal MCP skill remains byte-for-byte unchanged, leaving global fallback rollout to its linked owner task"
  - id: AC-5
    when: "focused CLI/search evidence, installed compact success and unknown-wing paths, the full non-network suite, public-safety scan, exact-wheel suite, and release-readiness gate run for the implementation"
    then: "all checks pass; unknown wing exits 2 with bounded actionable stderr; and no release, credential, external-AI, or remote mutation occurs"
out_of_scope:
  - "Editing or verifying the owner-managed global MemPalace skill or changing its deployment state."
  - "Editing the packaged minimal MCP skill, MCP schemas, or MCP/programmatic search result shapes."
  - "Changing embeddings, storage, ranking, model startup, search limits, or startup performance."
  - "Adding a service, cache, search engine, formatter module, dependency, performance gate, or architecture boundary."
  - "Editing backlog metadata or performing staging, commit, push, publication, release, credential access, or external AI-client execution."
contract_policy:
  flow: full_spdd
  reason: "This standard release-blocking CLI behavior change spans public formatting and exact-wheel qualification under rules-heavy recovery and compatibility constraints."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The installed compact CLI path must return no more than the requested three bounded verbatim previews with exact source metadata."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Compact recovery commands must be emitted only from usable line ranges and safe nonblank string source and wing metadata."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Default CLI full-text output and all programmatic and MCP search contracts must remain unchanged."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The exact wheel must expose the compact CLI contract without changing the packaged minimal MCP skill."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused, direct installed, full non-network, public-safety, exact-wheel, and release-readiness evidence must qualify the implementation."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "CLI search formatting"
      kind: cli
      paths: ["mempalace_code/cli.py", "mempalace_code/cli_commands/query.py", "mempalace_code/searcher.py"]
      expected_behavior: "Select compact formatting explicitly, reuse the existing search query and result path, and print bounded previews with exact metadata and guarded read recovery."
    - name: "exact-wheel compact search qualification"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Exercise legacy full search/read plus compact search/recovery for mined, imported, and restored palaces, with one unknown-wing failure, inside the existing isolated candidate-wheel contour."
  invariants:
    - id: INV-1
      statement: "Search without compact mode continues to print the complete stored document with the existing headings, source path, similarity, and exit behavior."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/cli_commands/query.py", "mempalace_code/searcher.py"]
    - id: INV-2
      statement: "search_memories, code_search, MCP tools, storage queries, ranking, embeddings, and model initialization remain unchanged."
      applies_to: ["mempalace_code/searcher.py"]
    - id: INV-3
      statement: "Blank-query rejection, positive --results validation, taxonomy validation, no-results success, and search failure recovery retain their current status codes and output channels."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/cli_commands/query.py", "mempalace_code/searcher.py"]
    - id: INV-4
      statement: "The packaged minimal MCP skill and all owner-managed global files remain unchanged by repository implementation and qualification."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-5
      statement: "Installed qualification retains exact-wheel provenance, neutral cwd, offline and credential-free execution, socket denial, bounded sanitization, and disposable cleanup."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "Legacy or hostile metadata could cause a fabricated range, malformed shell command, or formatter exception."
      mitigation: "Validate types and stripped values, require positive ordered endpoints, quote every command argument, and emit a fixed unavailable marker for every failed predicate."
    - id: RISK-2
      risk: "Compact implementation could truncate default output or alter MCP/programmatic results."
      mitigation: "Keep compact selection explicit at the print formatter boundary and add side-by-side default full-text and unchanged API/MCP regression evidence."
    - id: RISK-3
      risk: "Source-only tests could pass while the candidate wheel omits or miswires the compact flag."
      mitigation: "Extend the existing exact-wheel scenario and assert installed console provenance, compact payload predicates, and unknown-wing exit behavior."
    - id: RISK-4
      risk: "A nominal preview bound could still allow too many document bodies into the agent fallback."
      mitigation: "Reuse the exact Layer3 300-character truncation rule and prove the owner rollout command's `--results 3` contour through direct installed output size and hit-count assertions."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_searcher.py::TestSearchCompactCLI tests/test_cli.py::TestSearchCompactMode tests/test_release_readiness_gate.py::test_installed_workflow_happy_path_fails_closed tests/test_cli_golden_scenarios.py::test_cli_golden_workflow_happy_path -q"
      proves: "Focused source and installed-seam evidence covers bounded compact success, metadata guards, default preservation, parser wiring, and unknown-wing failure."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel suite exposes compact search through the installed console and records both success and unknown-wing predicates without touching the packaged skill."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-3
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured full non-network suite preserves CLI, programmatic search, MCP, metadata, and unrelated behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The implementation and tests contain no private global-skill content, credentials, private paths, or unsafe release material."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-5
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
      proves: "The canonical release-readiness gate accepts the same candidate after static, artifact, install, and public-safety qualification."
      acceptance_ids: [AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The complete configured regression contour retains default CLI full text, MCP and programmatic contracts, and all adjacent behavior."
        acceptance_ids: [AC-3, AC-5]
      - id: REG-2
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The existing formatter extension and test changes satisfy the configured lint gate without a new module or dependency."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-5]
      - id: REG-3
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The bounded implementation and qualification changes satisfy the configured format gate."
        acceptance_ids: [AC-5]
---

## Design Notes

- Extend `searcher.search`, the current CLI formatting owner. Add only an explicit boolean formatting selection from `cli.py` through `cmd_search`; keep query construction, storage access, ranking, and result-count behavior shared.
- Reuse Layer3's preview boundary exactly: strip the document, replace embedded newlines with spaces, and when length exceeds 300 characters emit the first 297 characters plus `...`. Preserve document text verbatim apart from this whitespace flattening and truncation.
- Compact-mode safety depends on the caller's existing `--results` bound. The linked global owner uses `--compact --results 3`; do not add a second result-limit policy or silently rewrite `--results`.
- Print the exact stored `source_file` value for valid strings; do not reduce it to a basename. Print a line range only when both endpoints are integer-like positive values and `end >= start`. Malformed values must not escape the formatter.
- Emit exactly one copyable recovery command per eligible hit: `mempalace-code --palace <palace> read <source_file> --start <start> --end <end> --wing <wing>`. Shell-quote palace, source, and wing arguments. Eligibility requires source_file and wing to be strings whose stripped values are non-empty and not `?`, plus the usable range predicate. Emit a fixed `Recovery: unavailable` line otherwise.
- Keep the default formatter byte-compatible for representative full-text fixtures. Do not route default output through compact helpers, change the programmatic result dictionaries, or touch MCP files.
- Extend `_run_installed_workflow_happy_path_scenario` rather than adding another release-gate owner or setup. Preserve its default `--results 10` search and full read proof, then add compact search and executable recovery for mined, imported, and restored palaces. Prove one unknown wing exits 2 with clean bounded stderr and no traceback. Preserve the existing non-positive `--results` rows.
- The installed-golden command comes from `scripts/gate_inventory.py`; the full non-network, public-safety, Ruff, and format commands are the repository's configured verification surface. The focused provider command targets only the new search and installed-scenario cases.
- Exact-wheel PASS is the repository handoff boundary. The linked owner task may then update the installed global fallback; this implementation neither reads nor writes that global file.
