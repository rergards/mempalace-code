slug: CLEAN-ONBOARDING
phase: polish
date: 2026-05-01
commit_range: 09f83be..c7dfd34
reverted: false
findings:
  - id: P-1
    title: "import yaml repeated inside 3 test methods"
    category: volume
    location: "tests/test_cli.py:173,222,267 (pre-fix)"
    evidence: "`import yaml` appeared inline in test_init_default_writes_config_without_prompt, test_init_flat_project_generates_general_room_without_prompt, and test_init_yes_compatibility_is_non_interactive"
    decision: fixed
    fix: "Moved import yaml to module level; removed the three in-method import statements"

  - id: P-2
    title: "Ephemeral task reference (AC-7) embedded in comment"
    category: verbal
    location: "mempalace/cli.py:102"
    evidence: "# Validate directory before any side effects — must precede entity scanning (AC-7)"
    decision: fixed
    fix: "Removed the '(AC-7)' suffix; the ordering constraint explanation is useful but the task ID will rot"

  - id: P-3
    title: "AC-X references in TestInitNonInteractiveOnboarding class and inline comments"
    category: verbal
    location: "tests/test_cli.py:151,157,183,198,209,229,252,274 (pre-fix)"
    evidence: "Class docstring read 'AC-1 through AC-7: config-file-first init...'; 7 test methods preceded by '# AC-N: ...' comments"
    decision: fixed
    fix: "Replaced class docstring with plain description; removed all 7 inline AC-N comments — test method names already convey intent"

  - id: P-4
    title: "_raise_if_called helper defined 3 times inline"
    category: structural
    location: "tests/test_cli.py:165,216,259 (pre-fix)"
    evidence: "Identical single-use local function pattern copied across three test methods"
    decision: fixed
    fix: "Replaced each inline function definition with side_effect=AssertionError('...') directly in the patch() call"

  - id: P-5
    title: "'# Pass 1:' implies a sequence that does not exist"
    category: verbal
    location: "mempalace/cli.py:113 (pre-fix)"
    evidence: "# Pass 1: opt-in people/project detection from file content"
    decision: fixed
    fix: "Removed comment; the enclosing 'if detect_entities_enabled:' block already conveys the conditional branch"

  - id: P-6
    title: "Comment restates detect_rooms_local call"
    category: verbal
    location: "mempalace/cli.py:131 (pre-fix)"
    evidence: "# Detect rooms from folder structure"
    decision: fixed
    fix: "Removed comment; detect_rooms_local() is self-describing"

  - id: P-7
    title: "Comment restates entities.json write"
    category: verbal
    location: "mempalace/cli.py:122 (pre-fix)"
    evidence: "# Save confirmed entities to <project>/entities.json for the miner"
    decision: fixed
    fix: "Removed comment; entities_path assignment and json.dump make the action obvious"

  - id: P-8
    title: "detect_rooms_local docstring explains obvious semantics of interactive param"
    category: verbal
    location: "mempalace/room_detector_local.py:317-318"
    evidence: "By default (interactive=False) rooms are accepted automatically without prompting. / Pass interactive=True to invoke the room review/edit/add prompt."
    decision: fixed
    fix: "Removed the two lines restating what interactive=False/True means; kept the backward-compat note about the yes parameter which is non-obvious"

  - id: P-9
    title: "detect_rooms_local docstring backward-compat note for yes parameter"
    category: verbal
    location: "mempalace/room_detector_local.py:319"
    evidence: "The yes parameter is accepted for backward compatibility; it maps to interactive=False."
    decision: dismissed
    reason: "Non-obvious API contract — callers passing yes=True (from old scripts) need to know it is now a no-op; correct place to document it"

totals:
  fixed: 8
  dismissed: 1
fixes_applied:
  - "Moved 'import yaml' to module level in tests/test_cli.py (3 in-method imports removed)"
  - "Stripped '(AC-7)' ephemeral task reference from validation comment in cli.py"
  - "Replaced TestInitNonInteractiveOnboarding class docstring and 7 inline '# AC-N:' comments with plain description"
  - "Inlined 3 _raise_if_called() definitions as side_effect=AssertionError(...) in patch() calls"
  - "Removed '# Pass 1:' comment restating detect_entities_enabled branch in cli.py"
  - "Removed '# Detect rooms from folder structure' comment restating detect_rooms_local call in cli.py"
  - "Removed '# Save confirmed entities ...' comment restating json.dump block in cli.py"
  - "Removed two obvious lines from detect_rooms_local docstring explaining interactive param semantics"
