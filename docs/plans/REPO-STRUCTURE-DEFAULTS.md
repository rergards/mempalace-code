---
slug: REPO-STRUCTURE-DEFAULTS
status: completed
authority: non_authoritative
goal: "Auto-derive wing from .sln and rooms from .csproj when dotnet_structure is enabled"
risk: low
risk_note: "Additive only — existing configs without dotnet_structure key are unaffected"
files:
  - path: mempalace/miner.py
    change: "Add _detect_sln_wing(), _build_csproj_room_map(); thread csproj_room_map through detect_room() and _collect_specs_for_file(); apply both in mine() when dotnet_structure config key is set"
  - path: mempalace/room_detector_local.py
    change: "Detect .sln/.csproj in detect_rooms_local(); propose project names as rooms; set dotnet_structure: true in saved config when .sln is found"
  - path: tests/test_miner.py
    change: "Add tests for _detect_sln_wing, _build_csproj_room_map, detect_room with csproj priority, and mine() end-to-end with dotnet_structure=true"
acceptance:
  - id: AC-1
    when: "A directory with a root-level .sln file is mined with dotnet_structure: true and no --wing override"
    then: "The wing is set to the normalized .sln stem (e.g. MySolution.sln → mysolution)"
  - id: AC-2
    when: "A .cs file lives inside a folder that contains a .csproj (e.g. MyProject/Foo.cs) and dotnet_structure: true"
    then: "The drawer's room is set to the normalized project name (e.g. MyProject.csproj → myproject)"
  - id: AC-3
    when: "--wing override is provided alongside dotnet_structure: true"
    then: "The CLI override wins; .sln-derived wing is ignored"
  - id: AC-4
    when: "A file does not fall under any .csproj folder"
    then: "detect_room() falls through to existing folder/keyword/content logic (no regression)"
  - id: AC-5
    when: "mempalace init is run on a .NET repo with a .sln file"
    then: "mempalace.yaml is saved with dotnet_structure: true and rooms derived from .csproj names"
  - id: AC-6
    when: "mempalace.yaml has no dotnet_structure key (existing configs)"
    then: "Behavior is identical to current — no wing or room changes"
  - id: AC-7
    when: "Multiple .sln files exist at the project root"
    then: "The .sln containing the most project entries is chosen; ties broken alphabetically"
out_of_scope:
  - "Non-.NET languages — Python, JS, TS, Go, Rust room assignment unchanged"
  - "Nested .sln files (only root-level .sln considered for wing)"
  - "SolutionFolder entries in .sln (already excluded by parse_sln_file)"
  - "ARCH-EXTRACTION-MODE (layer/pattern detection — separate task)"
  - "CLI flag --dotnet-structure (config-only in this iteration)"
---

## Design Notes

### New helpers in `miner.py`

**`_detect_sln_wing(project_path: Path) -> str | None`**
- Glob `project_path/*.sln` (root level only — not recursive)
- If zero results: return `None`
- If one result: return `_normalize_wing_name(sln.stem)`
- If multiple: pick the one with the most `contains_project` triples (call `parse_sln_file()` on each); tie-break alphabetically
- Returns normalized string ready to use as wing

**`_build_csproj_room_map(project_path: Path) -> dict[Path, str]`**
- `glob("**/*.csproj") + glob("**/*.fsproj") + glob("**/*.vbproj")` relative to project_path
- For each file: key = `file.parent.resolve()`, value = `_normalize_room_name(file.stem)`
- Normalize: lowercase, replace `.` and `-` and ` ` with `_`, strip non-alnum/underscore
- Returns `{folder_path: room_name}` — used for O(1) ancestor lookup per file

### Modifications to `detect_room()`

Add optional `csproj_room_map: dict[Path, str] | None = None` parameter.

Insert as **Priority 0** (before existing Priority 1):
```python
if csproj_room_map:
    # Walk from file's parent up to project root, return first match
    check = filepath.parent.resolve()
    while check != project_path and check != check.parent:
        if check in csproj_room_map:
            return csproj_room_map[check]
        check = check.parent
    if project_path in csproj_room_map:
        return csproj_room_map[project_path]
```
This handles deeply nested files (e.g. `MyProject/Controllers/HomeController.cs` → `MyProject/` → room `myproject`).

### Threading through `_collect_specs_for_file()`

Add `csproj_room_map: dict | None = None` parameter, pass to `detect_room()`. The call site in `mine()` passes the map (built once before the loop).

### Modifications to `mine()`

After `wing = wing_override or config["wing"]`:
```python
dotnet_structure = config.get("dotnet_structure", False)
csproj_room_map = {}
if dotnet_structure:
    if not wing_override:
        sln_wing = _detect_sln_wing(project_path)
        if sln_wing:
            wing = sln_wing
    csproj_room_map = _build_csproj_room_map(project_path)
```

### Modifications to `room_detector_local.py`

**`detect_rooms_local()`**: Before the folder-scan, check for `.csproj`/`.fsproj`/`.vbproj` files:
```python
csproj_files = list(project_path.glob("**/*.csproj")) + ...
if csproj_files:
    rooms = _rooms_from_csproj(csproj_files, project_path)
    source = ".csproj projects"
    dotnet_structure = True
```

**New `_rooms_from_csproj(files, project_path)`** helper:
- De-duplicate project names, normalize to room name
- Return room list with `{"name": ..., "description": "Files from <ProjectName>/", "keywords": [...]}`
- Always append "general" fallback

**`save_config()`**: Accept optional `dotnet_structure: bool = False` param; include in yaml output when True.

### Room name normalization

Same rule for both helpers: `stem.lower().replace(".", "_").replace("-", "_").replace(" ", "_")` then strip non-alnum/underscore. E.g.:
- `MyApp` → `myapp`
- `MyApp.Infrastructure` → `myapp_infrastructure`
- `My-Project.Api` → `my_project_api`

### No schema change to drawers

Room values from .csproj are just strings assigned the same way as today — no new metadata fields, no migration needed.

### Test plan (test_miner.py additions)

- `test_detect_sln_wing_single`: tmp dir with one `.sln` → correct normalized wing
- `test_detect_sln_wing_multi`: tmp dir with two `.sln` files (different project counts) → picks the one with more projects
- `test_detect_sln_wing_none`: no `.sln` → returns None
- `test_build_csproj_room_map`: two `.csproj` files in different sub-dirs → correct map
- `test_detect_room_csproj_priority`: file under `.csproj` dir → map takes priority over folder keyword
- `test_detect_room_csproj_no_match`: file outside any project dir → falls through to existing logic
- `test_mine_dotnet_structure_wing`: full `mine()` with `dotnet_structure: true`, asserts wing from `.sln`
- `test_mine_dotnet_structure_rooms`: full `mine()` with `dotnet_structure: true`, asserts rooms from `.csproj`
- `test_mine_dotnet_structure_wing_override`: `--wing` override wins over `.sln` detection
- `test_mine_dotnet_structure_off`: `dotnet_structure` absent → no change in behavior
