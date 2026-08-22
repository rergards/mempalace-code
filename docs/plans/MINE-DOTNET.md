---
slug: MINE-DOTNET
status: completed
authority: non_authoritative
goal: "Add F#, VB.NET language support and .NET project/solution file parsing with KG dependency triples to the code miner"
risk: medium
risk_note: "F#/VB.NET language patterns follow proven MINE-CSHARP recipe (low risk), but KG integration during mining is a new pattern — miner.py has never written to the knowledge graph before. XML parsing of project files and regex parsing of .sln files add surface area beyond simple extension-map additions."
files:
  - path: mempalace/miner.py
    change: "Add .fs/.fsi/.vb/.csproj/.fsproj/.vbproj/.sln to EXTENSION_LANG_MAP and READABLE_EXTENSIONS; add FSHARP_BOUNDARY and VBNET_BOUNDARY regexes; register in get_boundary_pattern(); add _FSHARP_EXTRACT and _VBNET_EXTRACT pattern lists; register in _LANG_EXTRACT_MAP; add 'fsharp' and 'vbnet' to chunk_file() dispatch; add .vs/bin/obj to SKIP_DIRS; add parse_dotnet_project_file() and parse_sln_file() functions; extend mine() to call dotnet config parsers, invalidate stale KG triples by source_file, and emit new KG triples"
  - path: mempalace/knowledge_graph.py
    change: "Add invalidate_by_source_file(source_file: str) method — sets valid_to on all active triples whose source_file matches, used by miner before re-adding triples for changed/deleted config files"
  - path: mempalace/cli.py
    change: "In cmd_mine(), instantiate KnowledgeGraph() (default path) and pass to mine() as kg parameter"
  - path: tests/test_lang_detect.py
    change: "Add ('.fs', 'fsharp'), ('.fsi', 'fsharp'), ('.vb', 'vbnet'), ('.csproj', 'xml'), ('.fsproj', 'xml'), ('.vbproj', 'xml'), ('.sln', 'dotnet-solution') to extension-based detection parametrize list"
  - path: tests/test_symbol_extract.py
    change: "Add F# section (module, type, record, discriminated union, let binding, member, interface) and VB.NET section (Class, Module, Structure, Interface, Enum, Sub, Function, Property)"
  - path: tests/test_chunking.py
    change: "Add F# chunking tests (module boundary, let binding boundary, type with members) and VB.NET chunking tests (Class/End Class boundary, Sub/Function boundary)"
  - path: tests/test_miner.py
    change: "Add .fs and .vb roundtrip tests through process_file(); add .csproj/.sln parsing integration tests verifying KG triples are emitted; add SKIP_DIRS test verifying .vs/bin/obj are not scanned"
  - path: tests/test_dotnet_config.py
    change: "New file — unit tests for parse_dotnet_project_file() and parse_sln_file(): XML extraction of PackageReference/ProjectReference/TargetFramework, .sln project list parsing, .sln SolutionFolder filtering (must not emit triples), edge cases (empty files, malformed XML, namespaced MSBuild XML, no references); KG lifecycle tests verifying re-mining a changed .csproj invalidates stale triples before adding new ones"
acceptance:
  - id: AC-1
    when: "Mining a .fs file containing a module declaration"
    then: "Drawer has language='fsharp', symbol_type='module', symbol_name matches the module name"
  - id: AC-2
    when: "Mining a .fs file with a type declaration (type Foo = ...)"
    then: "Extracted with symbol_type='type'"
  - id: AC-3
    when: "Mining a .fs file with a record type"
    then: "Extracted with symbol_type='record'"
  - id: AC-4
    when: "Mining a .fs file with a discriminated union"
    then: "Extracted with symbol_type='union'"
  - id: AC-5
    when: "Mining a .fs file with a let binding (top-level function)"
    then: "Extracted with symbol_type='function'"
  - id: AC-6
    when: "Mining a .fs file with a member function"
    then: "Extracted with symbol_type='method'"
  - id: AC-7
    when: "Mining a .fs file with an interface declaration"
    then: "Extracted with symbol_type='interface'"
  - id: AC-8
    when: "Mining a .vb file with a Class declaration"
    then: "Drawer has language='vbnet', symbol_type='class', symbol_name matches"
  - id: AC-9
    when: "Mining a .vb file with a Module declaration"
    then: "Extracted with symbol_type='module'"
  - id: AC-10
    when: "Mining a .vb file with a Structure declaration"
    then: "Extracted with symbol_type='struct'"
  - id: AC-11
    when: "Mining a .vb file with an Interface declaration"
    then: "Extracted with symbol_type='interface'"
  - id: AC-12
    when: "Mining a .vb file with an Enum declaration"
    then: "Extracted with symbol_type='enum'"
  - id: AC-13
    when: "Mining a .vb file with a Sub or Function"
    then: "Extracted with symbol_type='method'"
  - id: AC-14
    when: "Mining a .vb file with a Property"
    then: "Extracted with symbol_type='property'"
  - id: AC-15
    when: "Mining a .csproj file with PackageReference and ProjectReference elements"
    then: "KG triples emitted: (project, depends_on, Package@Version) for each PackageReference; (project, references_project, ReferencedProjectName) for each ProjectReference — project name derived from path stem"
  - id: AC-16
    when: "Mining a .csproj file with TargetFramework and OutputType"
    then: "KG triples emitted: project targets_framework net8.0, project has_output_type Exe"
  - id: AC-17
    when: "Mining a .sln file with Project entries"
    then: "KG triples emitted: solution contains_project ProjectName for each project listed"
  - id: AC-18
    when: "Querying KG with subject=ProjectName"
    then: "Returns depends_on triples (package dependencies) and references_project triples (project references) as separate predicates"
  - id: AC-19
    when: "Mining a directory containing .vs/, bin/, obj/ subdirectories"
    then: "Those directories are skipped (not scanned)"
  - id: AC-20
    when: "Running `python -m pytest tests/ -x -q` and `ruff check mempalace/ tests/` after all changes"
    then: "All tests pass and lint is clean — no regressions"
out_of_scope:
  - "Tree-sitter F#/VB.NET parsers — no grammars available; regex path only"
  - "F# computation expressions (async { }, task { }) as boundaries — internal to function bodies"
  - "F# active patterns — rare as top-level declarations; may be added later"
  - "F# type providers — compile-time metaprogramming, not structural declarations"
  - "VB.NET WithEvents / Handles clauses — event wiring, not declarations"
  - "VB.NET LINQ query syntax — internal to method bodies"
  - "VB.NET XML literals — embedded XML in code, not structural"
  - "packages.config parsing — legacy NuGet format; PackageReference in .csproj is the modern standard"
  - "Directory.Packages.props / Directory.Build.props — central package management files; add later once basic .csproj parsing is proven"
  - "NuGet .nuspec file parsing — package authoring metadata, not project structure"
  - ".sln nested project folders (SolutionFolder entries) — cosmetic grouping, not dependencies"
  - "Project GUID-to-language mapping from .sln — project type is better extracted from the .csproj/.fsproj/.vbproj extension"
  - "Cross-file partial class linking — same exclusion as MINE-CSHARP"
  - "MCP server changes — no new filter parameters or tools"
  - "entity_detector.py READABLE_EXTENSIONS update — entity detection is prose-only; code files are excluded by design"
---

## Design Notes

- **F# and VB.NET follow the MINE-CSHARP seven-step recipe exactly**: extension map, readable extensions, boundary regex, boundary registration, extraction patterns, extraction map, chunk_file dispatch. No new infrastructure needed for the language support portion.

- **F# boundary patterns.** F# uses significant whitespace and `let`/`type`/`module` keywords. Boundaries at the top-level (column 0):
  1. `module\s+\w+` — module declarations (both `module Foo` and `module Foo =`)
  2. `type\s+\w+` — type declarations (covers records, DUs, classes, interfaces, structs, type abbreviations)
  3. `let\s+(?:rec\s+)?(?:inline\s+)?\w+` — top-level let bindings (functions and values)
  4. `member\s+(?:this|self|x|\w+)\.\w+` — member functions inside type declarations (indented)
  5. `interface\s+\w+` — explicit interface declarations
  6. `exception\s+\w+` — exception type declarations

- **F# extraction patterns.** Ordered most-specific first:
  1. DU: `type\s+(\w+)\s*=\s*\|` or `type\s+(\w+)\s*=\s*\n\s*\|` → `"union"`
  2. Record: `type\s+(\w+)\s*=\s*\{` → `"record"`
  3. Interface: `type\s+(\w+)\s*=\s*interface` or `\[<Interface>\]\s*type\s+(\w+)` → `"interface"`
  4. Module: `module\s+(\w+)` → `"module"`
  5. Exception: `exception\s+(\w+)` → `"exception"`
  6. Type (catch-all): `type\s+(\w+)` → `"type"` — covers classes, structs, type abbreviations
  7. Member: `member\s+(?:\w+)\.(\w+)` → `"method"`
  8. Let binding: `let\s+(?:rec\s+)?(?:inline\s+)?(\w+)` → `"function"`

- **F# indentation.** F# is whitespace-significant. Top-level declarations start at column 0; members are indented. The boundary regex should match both — column-0 declarations split into separate chunks, indented members also split. This is the same pattern as Python.

- **F# signature files (.fsi).** These are interface/header files with the same syntax as .fs but only declarations (no implementations). Same language tag `"fsharp"`, same boundary/extraction patterns apply.

- **VB.NET boundary patterns.** VB.NET uses `End Class`/`End Sub`/etc. block terminators, but boundaries should trigger at the **opening** declaration (same as all other languages):
  1. `(?:Public|Private|Protected|Friend|Protected Friend|Private Protected)?\s*(?:MustInherit|NotInheritable|Partial)?\s*Class\s+\w+` — class declarations
  2. `Module\s+\w+` — module declarations
  3. `(?:Public|Private|Protected|Friend)?\s*Structure\s+\w+` — structures
  4. `(?:Public|Private|Protected|Friend)?\s*Interface\s+\w+` — interfaces
  5. `(?:Public|Private|Protected|Friend)?\s*Enum\s+\w+` — enums
  6. `(?:Public|Private|Protected|Friend|Protected Friend)?\s*(?:Shared\s+)?(?:Overridable\s+|MustOverride\s+|NotOverridable\s+|Overrides\s+|Overloads\s+)?(?:Async\s+)?(?:Sub|Function)\s+\w+` — methods
  7. `(?:Public|Private|Protected|Friend)?\s*(?:Shared\s+)?(?:ReadOnly\s+|WriteOnly\s+)?Property\s+\w+` — properties

- **VB.NET case insensitivity.** VB.NET keywords are case-insensitive (`Public Class` = `public class`). Boundary and extraction regexes should use `re.IGNORECASE`.

- **VB.NET extraction patterns.** Ordered:
  1. `(?:modifiers\s+)*Enum\s+(\w+)` → `"enum"`
  2. `(?:modifiers\s+)*Structure\s+(\w+)` → `"struct"`
  3. `(?:modifiers\s+)*Interface\s+(\w+)` → `"interface"`
  4. `Module\s+(\w+)` → `"module"`
  5. `(?:modifiers\s+)*Class\s+(\w+)` → `"class"`
  6. `(?:modifiers\s+)*Property\s+(\w+)` → `"property"` — before Sub/Function
  7. `(?:modifiers\s+)*(?:Sub|Function)\s+(\w+)` → `"method"`

- **KG integration is a new pattern for the miner.** Currently `mine()` only writes drawers (vector store). This task introduces the first miner->KG bridge. Implementation approach:
  - `parse_dotnet_project_file(filepath: Path) -> list[tuple[str, str, str]]` -- returns list of `(subject, predicate, object)` triples extracted from XML.
  - `parse_sln_file(filepath: Path) -> list[tuple[str, str, str]]` -- returns list of triples from .sln text.
  - `mine()` gains an optional `kg: KnowledgeGraph = None` parameter. When provided, after processing config files, triples are added via `kg.add_triple(subject, predicate, obj, source_file=str(filepath))`.
  - The CLI's `cmd_mine()` instantiates `KnowledgeGraph()` (default path, `~/.mempalace/knowledge_graph.sqlite3`) and passes it to `mine()`. This is the same default path used by MCP server, export, and import -- all callers observe the same graph.
  - Config files (.csproj, .fsproj, .vbproj, .sln) are BOTH chunked as text drawers (for semantic search) AND parsed for KG triples (for structured queries). Dual storage is intentional.

- **KG lifecycle on re-mine and deletion.** The KG schema already stores `source_file` on each triple. A new method `KnowledgeGraph.invalidate_by_source_file(source_file: str)` sets `valid_to = today` on all active triples (where `valid_to IS NULL`) whose `source_file` matches. This uses temporal invalidation (not physical deletion) to preserve history, consistent with the KG's temporal model.
  - **Changed config files**: when `mine()` detects a hash mismatch on a `.csproj`/`.fsproj`/`.vbproj`/`.sln` file, it calls `kg.invalidate_by_source_file(source_file)` before re-parsing and adding new triples.
  - **Deleted config files**: during the stale-file sweep, `mine()` calls `kg.invalidate_by_source_file(stale_path)` for each stale path that has a config extension.
  - **First mine**: no invalidation needed -- triples are added fresh.

- **Project file XML parsing.** Use `xml.etree.ElementTree` (stdlib, no new dependency). Extract:
  - `<PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>` -- `(project_name, "targets_framework", "net8.0")`
  - `<PropertyGroup><OutputType>Exe</OutputType></PropertyGroup>` -- `(project_name, "has_output_type", "Exe")`
  - `<PackageReference Include="Newtonsoft.Json" Version="13.0.3" />` -- `(project_name, "depends_on", "Newtonsoft.Json@13.0.3")`
  - `<ProjectReference Include="../Shared/Shared.csproj" />` -- `(project_name, "references_project", "Shared")` -- referenced project name is the path stem, not the raw path. The full path is searchable via the text drawer.
  - Project name derived from filename stem (e.g., `MyApp.csproj` -> `MyApp`).

- **Solution file parsing.** `.sln` is a text format with `Project("...")` lines:
  ```
  Project("{FAE04EC0-...}") = "MyApp", "MyApp\MyApp.csproj", "{GUID}"
  ```
  Regex: `Project\("[^"]*"\)\s*=\s*"([^"]+)",\s*"([^"]+)"` -- capture group 1 = project name, group 2 = relative path. **Filter**: only emit triples for entries whose path (group 2) ends in `.csproj`, `.fsproj`, or `.vbproj` -- this excludes SolutionFolder entries and other non-project items. Solution name from filename stem. Triples: `(solution_name, "contains_project", project_name)`.

- **SKIP_DIRS additions.** `.vs` (Visual Studio user settings/cache), `bin` (build output), `obj` (intermediate build objects). All three are standard .NET gitignore entries and contain no source code.

- **`bin` and `obj` risk.** These are common directory names. `bin` could exist in non-.NET projects (e.g., `~/bin` scripts). However, `SKIP_DIRS` applies only within the project being mined, and `bin`/`obj` at any depth inside a project are almost always build artifacts. The risk of skipping a legitimate `bin/` source directory is minimal and consistent with how `build`/`dist`/`target` are already skipped.

- **Config file language tagging and chunking.** `.csproj`/`.fsproj`/`.vbproj`/`.sln` files need entries in **both** `EXTENSION_LANG_MAP` and `READABLE_EXTENSIONS`. `EXTENSION_LANG_MAP` entries: `.csproj` -> `"xml"`, `.fsproj` -> `"xml"`, `.vbproj` -> `"xml"`, `.sln` -> `"dotnet-solution"`. Without these, `detect_language()` would return `"unknown"`. Chunked via `chunk_adaptive_lines()` (the default for non-code languages). No dedicated boundary patterns -- these files are typically small enough for one or two chunks.

- **Attribute handling for F#.** F# uses `[<Attribute>]` syntax (note angle brackets inside square brackets). Extend the `chunk_code()` lookback for `fsharp` to recognize `[<` as an attachable prefix, similar to how C# uses `[`.
