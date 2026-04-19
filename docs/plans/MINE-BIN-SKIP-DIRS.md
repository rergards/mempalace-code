---
slug: MINE-BIN-SKIP-DIRS
goal: "Skip bin/ only for .NET projects by detecting .csproj/.sln markers in scan_project()"
risk: low
risk_note: "Narrowly scoped — touches one constant and one function; covered by existing+new tests"
files:
  - path: mempalace/miner.py
    change: "Remove 'bin' from SKIP_DIRS; add _is_dotnet_project() helper; update scan_project() dirs filter to conditionally skip bin/ when .NET markers are detected"
  - path: tests/test_miner.py
    change: "Update test_skip_dirs_dotnet() to add a .csproj in project root; add test_bin_dir_not_skipped_non_dotnet() for the non-.NET happy path"
acceptance:
  - id: AC-1
    when: "scan_project() is called on a dir containing bin/run.sh with no .NET marker files present"
    then: "bin/run.sh appears in the returned file list"
  - id: AC-2
    when: "scan_project() is called on a dir containing MyApp.csproj at root and bin/Debug/App.dll"
    then: "bin/Debug/App.dll does NOT appear in the returned file list"
  - id: AC-3
    when: "scan_project() is called on a dir containing Solution.sln at root and bin/Release/output.dll"
    then: "bin/Release/output.dll does NOT appear in the returned file list"
  - id: AC-4
    when: "scan_project() is called on a dir containing only obj/cache.py and no .NET markers"
    then: "obj/cache.py does NOT appear in the returned file list (obj/ remains globally skipped)"
out_of_scope:
  - "entity_detector.py SKIP_DIRS — separate module with no 'bin' entry; unchanged"
  - "convo_miner.py SKIP_DIRS — conversation miner; unchanged"
  - "room_detector_local.py SKIP_DIRS — init-time room detection; unchanged"
  - "mempalace.yaml dotnet_structure flag — scan_project() detection is file-system based, not config-based"
---

## Design Notes

- **Remove `"bin"` from `SKIP_DIRS`** (line ~161 in `miner.py`). Keep `"obj"` — only .NET uses `obj/` for build intermediates.

- **Add `_is_dotnet_project(project_path: Path) -> bool` helper** near `should_skip_dir()`. Detection strategy: glob for `.sln` at root level OR `.csproj`/`.fsproj`/`.vbproj` at root level OR one level deep. One-level-deep covers the standard .NET layout (`Solution.sln` at root, `Project/Project.csproj` in subdirectory). Use early-exit generator approach: `next(project_path.glob(pat), None) is not None`.

  ```python
  _DOTNET_MARKERS = ("*.sln", "*.csproj", "*.fsproj", "*.vbproj",
                     "*/*.csproj", "*/*.fsproj", "*/*.vbproj")

  def _is_dotnet_project(project_path: Path) -> bool:
      return any(next(project_path.glob(pat), None) is not None
                 for pat in _DOTNET_MARKERS)
  ```

- **Modify `scan_project()`**: compute `dotnet_project = _is_dotnet_project(project_path)` once before the `os.walk` loop. In the `dirs[:] =` filter, change the skip condition from `should_skip_dir(d)` to `should_skip_dir(d) or (dotnet_project and d == "bin")`. The `should_skip_dir` function signature is unchanged.

- **Update `test_skip_dirs_dotnet()`**: add `write_file(project_root / "MyApp.csproj", ...)` (a minimal but non-empty `.csproj` file) so `_is_dotnet_project()` fires. The existing assertions remain valid.

- **New test `test_bin_dir_not_skipped_non_dotnet()`**: create a temp dir with `bin/run.sh` (content ≥ 20 lines to clear minimum-length filter if applicable) and no .NET files. Assert `bin/run.sh` is in `scanned_files(...)`. Also assert `obj/skip.py` is still not included (obj/ remains global).

- `_is_dotnet_project` is called once per `scan_project()` invocation, not per-directory, so the glob overhead is O(1) per mine call — not per directory traversal step.
