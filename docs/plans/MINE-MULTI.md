---
slug: MINE-MULTI
goal: "Add `mempalace mine-all <parent-dir>` CLI command that scans immediate subdirectories for project markers, mines each into its own wing, and reports a summary"
risk: low
risk_note: "Composes existing mine() function in a loop. No storage schema changes, no new dependencies. Project detection is simple file-existence checks. Wing naming uses subprocess git-remote call with folder-name fallback. All new code is in cli.py and a thin helper in miner.py. Existing mine path is unchanged."
files:
  - path: mempalace/miner.py
    change: "Add detect_projects(parent_dir) function that scans immediate subdirectories for PROJECT_MARKERS (.git, pyproject.toml, package.json, Cargo.toml, go.mod, *.sln, pom.xml, build.gradle). Add derive_wing_name(project_dir) function that tries `git remote get-url origin` to extract repo name, falls back to folder name normalized to snake_case. Both are pure helpers with no side effects."
  - path: mempalace/cli.py
    change: "Add `mine-all` subcommand with argparse wiring. Arguments: dir (positional), --dry-run, --force, --palace, --no-gitignore, --include-ignored, --agent. Handler cmd_mine_all() iterates detect_projects(), derives wing names, calls existing mine() for each project (with wing_override=derived_name). Prints per-project status line and final summary (found/mined/skipped/errored). Projects with existing wings are skipped unless --force. Errors in one project do not abort others (try/except per project, collect errors for summary)."
  - path: tests/test_cli.py
    change: "Add TestMineAllCommand class with tests: test_mine_all_basic (3 subdirs with .git, mock mine(), verify called 3 times with correct wing names), test_mine_all_dry_run (--dry-run prints projects without calling mine()), test_mine_all_skip_existing (wing already in palace skips project unless --force), test_mine_all_force_remines (--force passes through), test_mine_all_no_projects (empty dir prints 'no projects found'), test_mine_all_error_continues (one mine() raises, others still mined, summary shows error)."
  - path: tests/test_miner.py
    change: "Add TestDetectProjects class: test_detect_finds_git_dirs, test_detect_finds_pyproject, test_detect_finds_package_json, test_detect_skips_non_project_dirs, test_detect_no_recurse (nested projects not detected). Add TestDeriveWingName class: test_wing_from_git_remote_https, test_wing_from_git_remote_ssh, test_wing_fallback_folder_name, test_wing_name_normalization (spaces, hyphens to underscores)."
acceptance:
  - id: AC-1
    when: "Running `mempalace mine-all ~/dev` where ~/dev has 3 subdirs with .git markers"
    then: "All 3 projects are mined, each into its own wing named from git remote or folder name"
  - id: AC-2
    when: "Running `mempalace mine-all ~/dev --dry-run`"
    then: "Output lists detected projects with derived wing names; no mining occurs; no palace modifications"
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
- Returns `[{"path": "/abs/path", "markers": [".git", "pyproject.toml"]}]` sorted by folder name
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

### Error isolation

- Each project is mined in a `try/except Exception` block
- Errors are collected as `(project_name, error_message)` tuples
- After all projects, print error details before the summary line
- Exit code: 0 if all succeeded or skipped, 1 if any errors occurred

### mempalace.yaml requirement

- `mine()` calls `load_config()` which requires `mempalace.yaml` in the project dir
- Projects without `mempalace.yaml` will fail with a clear error from `load_config()` (prints "No mempalace.yaml found, run mempalace init")
- This error is caught by the per-project try/except and reported as a skipped-with-error project
- Users should run `mempalace init <dir> --yes` on each project before `mine-all`, or the command can be extended later with `--auto-init`

### CLI argparse structure

- New top-level subcommand `mine-all` (not `mine --all`) to keep the mine subparser clean
- Shares most flags with `mine`: `--dry-run`, `--force`, `--no-gitignore`, `--include-ignored`, `--agent`, `--palace`
- Does NOT inherit `--mode convos`, `--wing`, `--limit`, `--extract`, `--full` (these are per-project concerns)
- `--force` in mine-all context means "re-mine even if wing exists" (not the same as mine's `--full` which means "rebuild all chunks")
