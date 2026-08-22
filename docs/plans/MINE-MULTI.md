---
slug: MINE-MULTI
status: completed
authority: non_authoritative
goal: "Add `mempalace mine-all <parent-dir>` CLI command that scans immediate subdirectories for project markers, mines each into its own wing, and reports a summary"
risk: low
risk_note: "Composes existing mine() function in a loop. No storage schema changes, no new dependencies. Project detection is simple file-existence checks. Wing naming uses subprocess git-remote call with folder-name fallback. All new code is in cli.py and a thin helper in miner.py. Existing mine path is unchanged."
files:
  - path: mempalace/miner.py
    change: "Add detect_projects(parent_dir) function that scans immediate subdirectories for PROJECT_MARKERS (.git, pyproject.toml, package.json, Cargo.toml, go.mod, *.sln, pom.xml, build.gradle). Returns list of dicts including an 'initialized' boolean indicating whether mempalace.yaml or mempal.yaml exists. Add derive_wing_name(project_dir) function that tries `git remote get-url origin` to extract repo name, falls back to folder name normalized to snake_case. Both are pure helpers with no side effects."
  - path: mempalace/cli.py
    change: "Add `mine-all` subcommand with argparse wiring. Arguments: dir (positional), --dry-run, --force, --palace, --no-gitignore, --include-ignored, --agent. Handler cmd_mine_all() iterates detect_projects(), derives wing names, and for each project: (1) skips with warning if not initialized (no mempalace.yaml/mempal.yaml), (2) skips if wing exists in palace (unless --force), (3) calls mine() in a try/except (BaseException, re-raising KeyboardInterrupt) to isolate failures including SystemExit from load_config(). In --dry-run mode, store is never opened -- only project detection and wing derivation are performed. Prints per-project status line and final summary (found/mined/skipped/errored). Exit code: 0 if all succeeded or skipped, 1 if any errors. Add entry to dispatch dict and update module docstring command list."
  - path: tests/test_cli.py
    change: "Add TestMineAllCommand class with tests: test_mine_all_basic (3 initialized subdirs with .git + mempalace.yaml, mock mine(), verify called 3 times with correct wing names), test_mine_all_dry_run (--dry-run prints projects without calling mine() or opening store), test_mine_all_skip_existing (wing already in palace skips project unless --force), test_mine_all_force_remines (--force passes through), test_mine_all_no_projects (empty dir prints 'no projects found'), test_mine_all_error_continues (one mine() raises, others still mined, summary shows error), test_mine_all_skips_uninitialized (subdir with .git but no mempalace.yaml is skipped with warning), test_mine_all_exit_code_zero_on_success (exit code 0 when all mined/skipped), test_mine_all_exit_code_one_on_error (exit code 1 when any project errors), test_mine_all_system_exit_caught (mine() raising SystemExit is caught and reported, not propagated)."
  - path: tests/test_miner.py
    change: "Add TestDetectProjects class: test_detect_finds_git_dirs, test_detect_finds_pyproject, test_detect_finds_package_json, test_detect_skips_non_project_dirs, test_detect_no_recurse (nested projects not detected), test_detect_reports_initialized_flag (projects with mempalace.yaml have initialized=True, those without have initialized=False). Add TestDeriveWingName class: test_wing_from_git_remote_https, test_wing_from_git_remote_ssh, test_wing_fallback_folder_name, test_wing_name_normalization (spaces, hyphens to underscores)."
acceptance:
  - id: AC-1
    when: "Running `mempalace mine-all ~/dev` where ~/dev has 3 initialized subdirs (each with .git and mempalace.yaml)"
    then: "All 3 projects are mined, each into its own wing named from git remote or folder name"
  - id: AC-2
    when: "Running `mempalace mine-all ~/dev --dry-run`"
    then: "Output lists detected projects with derived wing names and initialization status; no mining occurs; no palace/store files are created or opened"
  - id: AC-3
    when: "Running `mempalace mine-all ~/dev` and one project's wing already exists in the palace"
    then: "That project is skipped with a 'skipped (wing exists)' message; other projects are mined"
  - id: AC-4
    when: "Running `mempalace mine-all ~/dev --force` and one project's wing already exists"
    then: "All projects are mined including the one with an existing wing"
  - id: AC-5
    when: "Running `mempalace mine-all ~/dev` and one project's mine() raises an exception"
    then: "Error is caught and reported; remaining projects are still mined; summary shows 1 error"
  - id: AC-6
    when: "Summary is printed after mine-all completes"
    then: "Shows: 'Found X projects, mined Y, skipped Z, errors W'"
  - id: AC-7
    when: "A subdirectory has no project markers (.git, pyproject.toml, package.json, etc.)"
    then: "It is not detected as a project and is not mined"
  - id: AC-8
    when: "Running `python -m pytest tests/ -x -q` and `ruff check mempalace/ tests/`"
    then: "All tests pass and lint is clean"
  - id: AC-9
    when: "A subdirectory has project markers but no mempalace.yaml/mempal.yaml"
    then: "It is detected but skipped with a warning message suggesting `mempalace init <dir>`; mine() is never called for it"
  - id: AC-10
    when: "All projects are mined or skipped successfully (no errors)"
    then: "Exit code is 0"
  - id: AC-11
    when: "One or more projects error during mining"
    then: "Exit code is 1 and the summary includes error details"
out_of_scope:
  - "Recursive descent into nested projects (only immediate children of parent-dir)"
  - "Parallel mining (sequential for v1)"
  - "Auto-detection of monorepo subprojects (e.g. Lerna workspaces, Cargo workspaces)"
  - "Auto-running `mempalace init` for uninitialized projects -- mine() already handles missing mempalace.yaml with a clear error"
  - "MCP tool for mine-all -- CLI only"
  - "Changes to the existing mine() function signature or behavior"
---

## Design Notes

### Project detection: `detect_projects(parent_dir) -> list[dict]`

- Scan only immediate children of `parent_dir` (no os.walk recursion -- just `os.listdir` + `os.path.isdir`)
- A directory is a project if it contains any of these markers:
  - `.git/` (directory)
  - `pyproject.toml`, `setup.py`, `setup.cfg` (Python)
  - `package.json` (Node.js)
  - `Cargo.toml` (Rust)
  - `go.mod` (Go)
  - `*.sln`, `*.csproj` (.NET)
  - `pom.xml`, `build.gradle`, `build.gradle.kts` (JVM)
  - `Gemfile` (Ruby)
  - `composer.json` (PHP)
- Returns `[{"path": "/abs/path", "markers": [".git", "pyproject.toml"], "initialized": true}]` sorted by folder name
- `initialized` is True if `mempalace.yaml` or `mempal.yaml` exists in the directory
- Hidden directories (starting with `.`) are skipped as candidate projects

### Wing name derivation: `derive_wing_name(project_dir) -> str`

- Try `git -C <dir> remote get-url origin` (subprocess, timeout=5s)
- Parse URL: `https://github.com/user/repo.git` -> `repo`, `git@github.com:user/repo.git` -> `repo`
- Strip trailing `.git` suffix
- Fallback: folder basename
- Normalize: lowercase, replace `-` and spaces with `_`, strip non-alphanumeric/underscore chars
- The result matches the convention used by `room_detector_local.py:detect_rooms_local()` which does `project_path.name.lower().replace(" ", "_").replace("-", "_")`

### Skip-existing detection

- Before mining a project, check if wing already has drawers in the palace via `store.count_by("wing")`
- Call `count_by` once before the loop (not per-project) to avoid repeated full-table scans
- If wing name exists in the count dict and `--force` is not set, skip with message
- **Dry-run**: skip store access entirely -- do not call `open_store()` or `count_by()`. `open_store()` calls `os.makedirs(palace_path, exist_ok=True)` unconditionally, which would create palace directories and violate the dry-run contract (AC-2). In dry-run mode, the wing-exists column in the output shows "?" (unknown) since the store is not consulted

### Error isolation

- Each project is mined in a `try/except BaseException` block, re-raising `KeyboardInterrupt` so Ctrl-C still works
- This catches both `Exception` subclasses and `SystemExit` -- the latter is critical because `load_config()` in `miner.py` calls `sys.exit(1)` (raises `SystemExit`, not `Exception`) when `mempalace.yaml` is missing
- However, the primary defense against missing config is the **preflight check**: `detect_projects()` reports `initialized` status, and `cmd_mine_all()` skips uninitialized projects before calling `mine()`. The `BaseException` catch is a safety net for unexpected `sys.exit()` calls deeper in the stack
- Errors are collected as `(project_name, error_message)` tuples
- After all projects, print error details before the summary line
- Exit code: 0 if all succeeded or skipped, 1 if any errors occurred

### mempalace.yaml requirement

- `mine()` calls `load_config()` which requires `mempalace.yaml` in the project dir
- `load_config()` calls `sys.exit(1)` when the config is missing, raising `SystemExit` (not `Exception`)
- **Preflight check**: `cmd_mine_all()` checks `project["initialized"]` before calling `mine()`. Uninitialized projects are skipped with a warning: `"skipped (not initialized -- run: mempalace init <dir>)"`
- This means `mine()` is never called for projects without config, avoiding the `SystemExit` entirely in the happy path
- The `BaseException` safety net in the error isolation block handles any unexpected `sys.exit()` deeper in `mine()`
- Users should run `mempalace init <dir> --yes` on each project before `mine-all`, or the command can be extended later with `--auto-init`

### CLI argparse structure

- New top-level subcommand `mine-all` (not `mine --all`) to keep the mine subparser clean
- Shares most flags with `mine`: `--dry-run`, `--force`, `--no-gitignore`, `--include-ignored`, `--agent`, `--palace`
- Does NOT inherit `--mode convos`, `--wing`, `--limit`, `--extract`, `--full` (these are per-project concerns)
- `--force` in mine-all context means **only** "re-mine even if wing exists" (bypass wing-exists skipping). It does NOT imply `--full` (which means `incremental=False`, rebuild all chunks). These are orthogonal concerns: `--force` controls which projects are selected, `--full` on the per-project `mine` command controls how deeply they are re-indexed. mine-all does not expose `--full`; users who need a full rebuild should run `mempalace mine <dir> --full` on individual projects
- Must add `"mine-all": cmd_mine_all` to the dispatch dict in `main()` (`cli.py:1107-1124`)
- Must update the module docstring command list so `mine-all` appears in `mempalace --help` output
