slug: QUAL-OPTIONAL-ANNOTATIONS
round: 1
date: 2026-05-11
commit_range: 5891d19..53465ba
findings:
  - id: F-1
    title: "_is_relevant_change retains Optional[list] style annotation not converted by this task"
    severity: info
    location: "mempalace_code/watcher.py:125"
    claim: >
      The private helper _is_relevant_change still uses Optional[list] = None for include_ignored
      while the public watch_and_mine function in the same file was converted to list | None.
      Both forms are equivalent and correct; the inconsistency is cosmetic only.
    decision: dismissed
    fix: ~

  - id: F-2
    title: "EntityRegistry.load retains Optional[Path] style annotation not converted by this task"
    severity: info
    location: "mempalace_code/entity_registry.py:299"
    claim: >
      EntityRegistry.load() still uses config_dir: Optional[Path] = None while entity_registry.py
      had seed(aliases: dict | None = None) converted. Both forms are equivalent and correct;
      the plan explicitly prohibits converting already-correct Optional[...] unless the declaration
      is being touched for this task.
    decision: dismissed
    fix: ~

  - id: F-3
    title: "normalize_include_paths has no dedicated unit test for None input"
    severity: low
    location: "mempalace_code/miner.py:289"
    claim: >
      The annotation change to normalize_include_paths(include_ignored: list | None) makes the
      None contract explicit, but there is no direct unit test for normalize_include_paths(None).
      The None path is covered indirectly through integration tests (test_mine_all_basic and
      test_watch_passes_respect_gitignore_and_include_ignored) since mine() and scan_project()
      pass include_ignored through to normalize_include_paths. The function body already uses
      include_ignored or [] so there is no regression risk, but a focused unit test would
      pin the contract.
    decision: backlogged
    backlog_slug: QUAL-NORMALIZE-INCLUDE-PATHS-UNIT-TEST

totals:
  fixed: 0
  backlogged: 1
  dismissed: 2

fixes_applied: []

new_backlog:
  - slug: QUAL-NORMALIZE-INCLUDE-PATHS-UNIT-TEST
    summary: >
      Add a focused unit test for normalize_include_paths() covering None, empty list, and
      mixed relative/absolute/comma-separated path inputs. Acceptance: test asserts the returned
      set value for each input class; test_normalize_include_paths_none passes
      normalize_include_paths(None) and asserts result == set(); no existing test behavior changes.
      Description: normalize_include_paths was annotated list | None in QUAL-OPTIONAL-ANNOTATIONS
      but has no direct unit test — indirect integration coverage exists but does not pin the
      None → empty set contract explicitly. Size: XS.
