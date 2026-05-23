---
slug: UPSTREAM-ROOM-MATCH-BOUNDED
goal: "Bound detect_room matching so room keywords do not match inside unrelated words"
risk: low
risk_note: "Small internal routing change with direct unit coverage; main risk is preserving intentional separator-delimited partial matches while blocking raw substrings."
files:
  - path: mempalace_code/mining/projects.py
    change: "Replace detect_room raw substring checks with exact or separator-bounded token matching for path parts, filenames, room names, and room keywords; use bounded keyword counting for content scoring."
  - path: tests/test_miner.py
    change: "Add direct detect_room regression tests for exact matches, separator-bounded matches, substring non-matches, content keyword scoring, and .csproj priority preservation."
acceptance:
  - id: AC-1
    when: "detect_room() is called for project path views/list.py with rooms containing frontend keyword views"
    then: "it returns frontend from the exact folder keyword match."
  - id: AC-2
    when: "detect_room() is called for filenames or path parts such as frontend-panel.py and user-views/detail.py"
    then: "it returns frontend because room names and keywords match as separator-bounded tokens."
  - id: AC-3
    when: "detect_room() is called for interviews/notes.py with frontend keyword views and research keyword interviews"
    then: "it returns research and never routes to frontend through the substring views inside interviews."
  - id: AC-4
    when: "detect_room() scores content containing customer interviews with frontend keyword views and research keyword interviews"
    then: "it returns research and does not count views inside interviews as a frontend keyword hit."
  - id: AC-5
    when: "detect_room() receives a csproj_room_map entry for an ancestor folder that also contains a folder keyword"
    then: "it returns the .csproj-derived room before any path, filename, or content matching."
out_of_scope:
  - "Changing room discovery in room_detector_local.py or FOLDER_ROOM_MAP contents."
  - "Changing scan_project file inclusion, chunking, storage, or drawer metadata."
  - "Changing conversation room detection in convo_miner.py."
  - "Changing public CLI flags or mempalace.yaml room schema."
contract_policy:
  flow: full_spdd
  reason: "Standard behavior-changing fix in the code-mining room router; routing mistakes affect stored drawer room metadata."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Room routing must keep exact folder and filename matches working for configured room names and keywords."
      source: "backlog description"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Room routing must preserve intentional separator-bounded matches such as user-views and frontend-panel."
      source: "backlog description"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Room routing must not match configured names or keywords as raw substrings inside unrelated tokens."
      source: "backlog description and upstream v3.3.5 evidence"
      acceptance_ids: [AC-3, AC-4]
    - id: REQ-4
      statement: ".csproj-derived room mapping must remain the highest-priority routing decision."
      source: "existing detect_room priority contract"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Project room routing"
      kind: "internal"
      paths: ["mempalace_code/mining/projects.py"]
      expected_behavior: "detect_room routes by exact or separator-bounded tokens for folders, filenames, room names, and room keywords, then falls back to bounded content keyword scoring and general."
    - name: "Room routing regression tests"
      kind: "internal"
      paths: ["tests/test_miner.py"]
      expected_behavior: "direct unit tests prove bounded matching accepts intended path/filename/content cases and rejects substring misroutes."
  invariants:
    - id: INV-1
      statement: "detect_room signature, return type, room dict schema, and priority order remain unchanged."
      applies_to: ["mempalace_code/mining/projects.py"]
    - id: INV-2
      statement: ".csproj-derived room mapping continues to run before folder, filename, and content matching."
      applies_to: ["mempalace_code/mining/projects.py"]
    - id: INV-3
      statement: "Files with no bounded match still fall back to general."
      applies_to: ["mempalace_code/mining/projects.py"]
    - id: INV-4
      statement: "mempalace_code.miner keeps exporting detect_room from mempalace_code.mining.projects."
      applies_to: ["mempalace_code/miner.py", "mempalace_code/mining/projects.py"]
  risks:
    - id: RISK-1
      risk: "Removing raw substring checks could break useful matches like user-views or frontend-panel."
      mitigation: "Implement token-sequence matching over alphanumeric tokens split by separators, and cover these examples directly."
    - id: RISK-2
      risk: "Content scoring could still count keywords inside unrelated words if it keeps using str.count()."
      mitigation: "Replace raw count with bounded keyword occurrence counting and add an interviews/views regression."
    - id: RISK-3
      risk: "A helper that treats empty strings or broad fallback room names as candidates could over-route to general."
      mitigation: "Ignore empty candidate tokens and keep general only as normal fallback unless it is explicitly matched."
    - id: RISK-4
      risk: "Refactoring detect_room could accidentally lower .csproj map priority."
      mitigation: "Leave priority 0 untouched and keep the existing .csproj test in the focused regression command."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_miner.py::TestDetectRoomBoundedMatching::test_path_part_exact_keyword_routes_to_frontend -q"
      proves: "exact folder keyword matching still routes to the intended room"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_miner.py::TestDetectRoomBoundedMatching::test_separator_bounded_path_and_filename_matches_route_to_frontend -q"
      proves: "separator-bounded path and filename matches still route by room name and keyword"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_miner.py::TestDetectRoomBoundedMatching::test_interviews_does_not_route_to_frontend_views_keyword -q"
      proves: "views no longer matches as a raw substring inside interviews during path or filename routing"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_miner.py::TestDetectRoomBoundedMatching::test_content_keyword_scoring_uses_bounded_tokens -q"
      proves: "content keyword scoring counts bounded keyword occurrences instead of substrings"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_miner.py::TestDetectRoomCsprojMap::test_csproj_priority_over_folder_keyword -q"
      proves: ".csproj-derived map lookup still takes priority over folder keyword routing"
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_miner.py::TestDetectRoomBoundedMatching tests/test_miner.py::TestDetectRoomCsprojMap tests/test_miner_modules.py::test_projects_module_owns_detect_room -q"
        proves: "focused room-routing behavior, .csproj priority, and miner shim ownership remain intact"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Add small private helpers in `mempalace_code/mining/projects.py`, keeping `detect_room()` as the public internal entrypoint.
- Tokenize matching inputs into lowercase alphanumeric token sequences, treating separators such as hyphen, underscore, dot, slash, whitespace, and other punctuation as boundaries.
- For path parts and filenames, match when candidate tokens and target tokens are equal or when either token sequence appears contiguously inside the other. This preserves bounded cases like `user-views`, `frontend-panel`, and compound configured keywords without accepting `views` inside `interviews`.
- For content scoring, count only bounded candidate token-sequence occurrences in the first 2000 characters. Do not use `str.count()` because it counts substrings inside longer words.
- Keep the .csproj map block exactly ahead of the new helper calls; this task changes fallback matching only.
- Keep room discovery unchanged. The configured `rooms` list remains the only detect_room input source.
