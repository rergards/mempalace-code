---
slug: SPLIT-NAME-REGEX-AND-DISPOSITION-SYNC
status: completed
authority: non_authoritative
goal: "Match configured split-person names as literal case-insensitive whole names even when they contain regex metacharacters."
risk: low
risk_note: "The production change is confined to escaping one configured value at the existing split-person regex boundary, with focused literal, invalid-pattern, compatibility, and empty-config coverage."
files:
  - path: mempalace_code/split_mega_files.py
    change: "Escape each configured person name and use word-character lookarounds for literal case-insensitive whole-name matching, including names with non-word edge characters."
  - path: tests/test_split_mega_files.py
    change: "Add extraction regressions for literal regex metacharacters, invalid raw patterns, and non-word name edges while retaining ordinary-name, username-map, and empty opt-in coverage."
acceptance:
  - id: AC-1
    when: "split person extraction runs with configured names containing literal regex metacharacters, including OBrien (Jr.) and an invalid raw regex whose first character is non-word"
    then: "the exact configured names are detected case-insensitively in normal surrounding whitespace without re.error, and regex-shaped or word-adjacent near-matches are rejected"
  - id: AC-2
    when: "split person extraction runs with ordinary configured names and a configured username_map entry"
    then: "content names and mapped usernames produce exactly the same canonical configured values as before"
  - id: AC-3
    when: "split person extraction runs with no configured names or username mappings against text containing plausible people"
    then: "the result remains empty"
  - id: AC-4
    when: "the focused split and regular-source behavior checks plus the configured non-network repository gate execute after the change"
    then: "literal name matching and existing split, source-safety, and repository behaviors complete successfully"
out_of_scope:
  - "Changing known_names.json schema, loading, caching, tokenization, scan limits, sorting, or username_map semantics."
  - "Changing person detection outside mempalace_code/split_mega_files.py."
  - "Changing split filenames, chunk contents, backup behavior, FIFO/output safety, or regular-source protections."
  - "Editing backlog metadata, disposition state, release bookkeeping, or runner-owned finalization artifacts."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release correctness work changes configured-input handling at a regex boundary used for split filename classification."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Configured split names containing regex metacharacters, including names with non-word first or last characters, must be treated as literal whole names and must not raise regex compilation errors."
      source: "backlog scope and AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Ordinary configured-name matching and exact username-map lookup must retain their current results."
      source: "backlog scope and AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Empty opt-in configuration must continue to produce no detected people."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Focused split and regular-source checks plus the configured non-network suite must validate the completed change."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "split configured-name matcher"
      kind: internal
      paths: ["mempalace_code/split_mega_files.py"]
      expected_behavior: "Escapes each configured name and wraps it with (?<!\\w) and (?!\\w) so metacharacters and non-word name edges match literally and case-insensitively without matching inside larger word tokens."
    - name: "split person-extraction tests"
      kind: internal
      paths: ["tests/test_split_mega_files.py"]
      expected_behavior: "Proves literal special-name matching at word and non-word edges, invalid-pattern safety, ordinary names, exact username mapping, and empty opt-in behavior."
  invariants:
    - id: INV-1
      statement: "Configured names remain returned in their canonical configured spelling and sorted by the existing result contract."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
    - id: INV-2
      statement: "Name matching remains case-insensitive and uses word-character lookarounds that support non-word name edges while preventing matches adjacent to larger word tokens."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
    - id: INV-3
      statement: "Known-names configuration loading and username_map lookup remain unchanged."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
    - id: INV-4
      statement: "Regular-source and generated-output FIFO, symlink, hardlink, directory, descriptor, partial-write, and source-preservation guards remain fail-closed."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
  risks:
    - id: RISK-1
      risk: "Keeping \\b anchors around an escaped value would reject configured names whose first or last character is non-word, while removing boundaries would allow matches inside larger word tokens."
      mitigation: "Apply re.escape only to person, replace the outer boundaries with (?<!\\w) and (?!\\w), and assert mixed-case exact matches plus word-adjacent non-matches for names with word and non-word edges."
    - id: RISK-2
      risk: "Coverage using only balanced metacharacters could miss the re.error failure class."
      mitigation: "Include a configured literal that starts with an unmatched regex metacharacter and assert extraction returns normally with the exact literal match in surrounding whitespace."
    - id: RISK-3
      risk: "A narrow matcher edit could accidentally disturb adjacent username-map, empty-config, or split I/O behavior."
      mitigation: "Retain exact focused assertions and run the split/source-guard slice plus the configured non-network suite."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_split_mega_files.py tests/test_regular_source_guard.py -q"
      proves: "Focused behavior covers literal and invalid-regex configured names with word and non-word edges, ordinary names, username mapping, empty opt-in, regular splitting, and fail-closed source/output paths."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The exact configured non-network repository suite remains green after the split matcher correction."
        acceptance_ids: [AC-2, AC-3, AC-4]
---

## Design Notes

- Change only the configured-name interpolation inside `extract_people()`: pass `person` through `re.escape()`, replace the outer `\b` anchors with `(?<!\w)` and `(?!\w)`, and retain `re.IGNORECASE`. These lookarounds define a whole-name match as a literal configured value with no immediately adjacent word character, so names with non-word edge characters remain matchable.
- Add a case-insensitive exact-match regression for `OBrien (Jr.)` in surrounding whitespace and assert regex-shaped, word-prefixed, and word-suffixed near-matches do not identify it.
- Add a configured value whose first character is an unmatched regex metacharacter, assert its exact literal form matches in surrounding whitespace without `re.error`, and assert a word-adjacent form does not match. Together with `OBrien (Jr.)`, this covers non-word first and last characters.
- Keep the existing ordinary configured-name, username-map, and absent-config tests as exact compatibility checks. Do not modify config loading or module-level `KNOWN_PEOPLE` initialization.
- Preserve all existing split-output and regular-source tests; this task does not alter tokenization, filename construction, source reading, output descriptors, writes, backups, or failure disposition.
- Backlog disposition synchronization is runner-owned finalization and is intentionally absent from implementation paths.
- Command context basis: `pyproject.toml` declares pytest discovery under `tests` and excludes network and slow tests by default; `CLAUDE.md` supplies the exact configured non-network full-suite command. The focused provider command matches the established split plan boundary and includes `tests/test_regular_source_guard.py` because FIFO/output safety is an explicit invariant.
