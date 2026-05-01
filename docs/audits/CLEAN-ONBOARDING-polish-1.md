slug: CLEAN-ONBOARDING
phase: polish
date: 2026-05-01
commit_range: 09f83be..da773d1
reverted: false
findings:
  - id: P-1
    title: "import yaml repeated inside 3 test methods"
    category: volume
    location: "tests/test_cli.py:174,219,261"
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
    title: "'# Pass 1:' implies a sequence that does not exist"
    category: verbal
    location: "mempalace/cli.py:113"
    evidence: "# Pass 1: opt-in people/project detection from file content"
    decision: fixed
    fix: "Removed comment; the enclosing 'if detect_entities_enabled:' block already conveys the conditional branch"

  - id: P-4
    title: "Comment restates function name"
    category: verbal
    location: "mempalace/cli.py:131"
    evidence: "# Detect rooms from folder structure"
    decision: fixed
    fix: "Removed comment; detect_rooms_local() is self-describing"

  - id: P-5
    title: "Comment restates immediately following save code"
    category: verbal
    location: "mempalace/cli.py:122"
    evidence: "# Save confirmed entities to <project>/entities.json for the miner"
    decision: fixed
    fix: "Removed comment; entities_path assignment and json.dump make the action obvious"

  - id: P-6
    title: "detect_rooms_local docstring explains yes backward-compat semantics"
    category: verbal
    location: "mempalace/room_detector_local.py:315"
    evidence: "The yes parameter is accepted for backward compatibility; it maps to interactive=False."
    decision: dismissed
    reason: "Non-obvious API contract — callers passing yes=True (from old scripts) need to know it is now a no-op; this is the correct place to document it"

  - id: P-7
    title: "Nested with-patch blocks in two tests"
    category: volume
    location: "tests/test_cli.py:232,243"
    evidence: "test_onboarding_command_dispatches_guided_flow and test_init_does_not_call_run_onboarding use nested with patch instead of comma-separated form"
    decision: dismissed
    reason: "Established pytest style; readability gain does not outweigh diff noise"

totals:
  fixed: 5
  dismissed: 2
fixes_applied:
  - "Moved 'import yaml' to module level in tests/test_cli.py (3 in-method imports removed)"
  - "Stripped '(AC-7)' ephemeral task reference from validation comment in cli.py"
  - "Removed '# Pass 1:' comment restating detect_entities_enabled branch in cli.py"
  - "Removed '# Detect rooms from folder structure' comment restating detect_rooms_local call in cli.py"
  - "Removed '# Save confirmed entities ...' comment restating json.dump block in cli.py"
