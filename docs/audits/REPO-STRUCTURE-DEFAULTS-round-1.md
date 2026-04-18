slug: REPO-STRUCTURE-DEFAULTS
round: 1
date: 2026-04-19
commit_range: 490921f..HEAD
findings:
  - id: F-1
    title: "process_file dry-run output ignores csproj_room_map — wrong room printed"
    severity: low
    location: "mempalace/miner.py:1864"
    claim: >
      process_file() did not accept csproj_room_map, so its dry_run=True code path
      called _collect_specs_for_file without the map. For .NET repos with
      dotnet_structure=True, the [DRY RUN] print showed the folder/keyword-matched
      room instead of the csproj-derived room, misleading users previewing the mine.
      The room_counts tally in mine() used a separate detect_room call with the map
      (correct), but the per-file output was wrong.
    decision: fixed
    fix: >
      Added optional csproj_room_map parameter to process_file(); threaded it through
      to both _collect_specs_for_file call sites (dry_run and normal paths). Updated
      the mine() dry_run call site to pass csproj_room_map.

  - id: F-2
    title: "Normalization logic duplicated between room_detector_local.py and miner.py"
    severity: low
    location: "mempalace/room_detector_local.py:98"
    claim: >
      _rooms_from_csproj() in room_detector_local.py contained an inline copy of the
      normalization logic from _normalize_room_name() in miner.py (lowercase, replace
      ./- /space with underscore, strip non-alnum). The two implementations were in
      sync but could silently diverge if one was updated without the other.
    decision: fixed
    fix: >
      Replaced the inline normalization in _rooms_from_csproj with a call to
      _normalize_room_name imported from .miner. Removed the now-unused `import re`
      from room_detector_local.py.

  - id: F-3
    title: "_normalize_wing_name drops dots in .sln stems instead of converting to underscores"
    severity: info
    location: "mempalace/miner.py:2931"
    claim: >
      _normalize_wing_name does not replace dots before stripping special chars, so a
      .sln stem like My.Solution yields wing "mysolution" instead of "my_solution".
      _normalize_room_name (for .csproj stems) correctly converts dots to underscores.
    decision: dismissed
    fix: ~

  - id: F-4
    title: "_build_csproj_room_map uses unrestricted recursive glob, not SKIP_DIRS-aware"
    severity: info
    location: "mempalace/miner.py:2965"
    claim: >
      _build_csproj_room_map and detect_rooms_local use project_path.glob("**/*.csproj")
      without filtering SKIP_DIRS. In theory this could include generated or vendored
      project files. In practice, .csproj files are not placed in obj/bin/packages
      directories, so the risk is negligible.
    decision: dismissed
    fix: ~

totals:
  fixed: 2
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Added csproj_room_map parameter to process_file() so dry-run output reflects correct .NET room routing"
  - "Replaced duplicated normalization in _rooms_from_csproj with import of _normalize_room_name from miner.py; removed unused import re"

new_backlog: []
