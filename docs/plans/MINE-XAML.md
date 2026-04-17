---
slug: MINE-XAML
goal: "Add XAML file parsing with view-name symbol extraction and KG triples linking code-behind, ViewModel, named controls, and resource references"
risk: medium
risk_note: "XAML XML parsing follows the proven .csproj pattern, but XAML binding expressions use a mini-language ({Binding}, {StaticResource}) requiring regex extraction from attribute values. XAML namespace handling (x:Class, x:Name) adds surface area. KG integration reuses the MINE-DOTNET pattern — low risk there."
files:
  - path: mempalace/miner.py
    change: "Add .xaml to EXTENSION_LANG_MAP ('xaml') and READABLE_EXTENSIONS; add .xaml to _DOTNET_CONFIG_EXTENSIONS (rename to _KG_EXTRACT_EXTENSIONS for clarity); add parse_xaml_file() function that extracts KG triples (code-behind link, DataContext ViewModel, x:Name controls, resource references, command bindings); extend mine() KG dispatch to call parse_xaml_file for .xaml; add _XAML_EXTRACT pattern list for view-name symbol extraction from x:Class attribute; register in _LANG_EXTRACT_MAP"
  - path: tests/test_dotnet_config.py
    change: "Rename to tests/test_kg_extract.py; add XAML parsing tests: x:Class extraction, code-behind triple, DataContext element binding, DataContext d:DesignInstance binding, x:Name control triples, StaticResource/DynamicResource reference triples, Command binding triples, edge cases (no x:Class, empty file, malformed XML, XAML with only resources), KG lifecycle (re-mining invalidates stale XAML triples)"
  - path: tests/test_lang_detect.py
    change: "Add ('.xaml', 'xaml') to extension-based detection parametrize list"
  - path: tests/test_miner.py
    change: "Add .xaml roundtrip test through process_file() asserting language='xaml', symbol_name matches view name from x:Class, and KG triples emitted for code-behind link"
acceptance:
  - id: AC-1
    when: "Mining a .xaml file containing x:Class='MyApp.MainWindow'"
    then: "Drawer has language='xaml', symbol_name='MainWindow', symbol_type='view'"
  - id: AC-2
    when: "Mining a .xaml file with x:Class attribute"
    then: "KG triple emitted: (MainWindow, 'has_code_behind', 'MainWindow.xaml.cs') derived from naming convention (filename + .cs)"
  - id: AC-3
    when: "Mining a .xaml file with element-style DataContext: <Window.DataContext><local:MainViewModel /></Window.DataContext>"
    then: "KG triple emitted: (MainWindow, 'binds_viewmodel', 'MainViewModel')"
  - id: AC-4
    when: "Mining a .xaml file with d:DataContext='{d:DesignInstance Type=vm:MainViewModel}'"
    then: "KG triple emitted: (MainWindow, 'binds_viewmodel', 'MainViewModel')"
  - id: AC-5
    when: "Mining a .xaml file with x:Name='txtUsername' on a TextBox"
    then: "KG triple emitted: (MainWindow, 'has_named_control', 'txtUsername')"
  - id: AC-6
    when: "Mining a .xaml file with {StaticResource MyStyle} in an attribute"
    then: "KG triple emitted: (MainWindow, 'references_resource', 'MyStyle')"
  - id: AC-7
    when: "Mining a .xaml file with {DynamicResource ThemeBrush}"
    then: "KG triple emitted: (MainWindow, 'references_resource', 'ThemeBrush')"
  - id: AC-8
    when: "Mining a .xaml file with Command='{Binding SaveCommand}'"
    then: "KG triple emitted: (MainWindow, 'uses_command', 'SaveCommand')"
  - id: AC-9
    when: "Mining a .xaml file with no x:Class attribute"
    then: "View name falls back to filename stem; triples still emitted for named controls and resources"
  - id: AC-10
    when: "Re-mining a directory where a .xaml file changed (hash mismatch)"
    then: "Stale KG triples from the old .xaml are invalidated before new triples are added"
  - id: AC-11
    when: "Running `python -m pytest tests/ -x -q` and `ruff check mempalace/ tests/` after all changes"
    then: "All tests pass and lint is clean — no regressions"
out_of_scope:
  - "Deep XAML binding expression parser — only simple {Binding PropertyName} and {StaticResource Key} patterns; complex multi-binding, converter, and fallback expressions are not parsed"
  - "XAML structural chunking (XML-element-aware splitting) — XAML files use chunk_adaptive_lines(); they are typically small enough for a few chunks"
  - "Resource dictionary cross-file linking — ResourceDictionary.MergedDictionaries references other XAML files; tracked by KG but not followed transitively"
  - "Custom markup extension parsing — only built-in extensions (Binding, StaticResource, DynamicResource) are recognized"
  - "XAML namespace resolution to CLR types — x:Name and local:ClassName use namespace prefixes that map to CLR namespaces via xmlns declarations; resolving the full CLR type requires tracking those mappings, which is out of scope"
  - "Attached property and attached event extraction — DockPanel.Dock, etc. are not tracked as relationships"
  - "Style/Template TargetType linking — linking a Style's TargetType to a control type class"
  - "BAML (compiled XAML) parsing — binary format, not source code"
  - "MCP server changes — no new filter parameters or tools"
  - "Boundary regex or code-aware chunking for XAML — XAML is not a programming language; adaptive line chunking is appropriate"
---

## Design Notes

- **XAML files are XML markup, not code.** Unlike C#/F#/VB.NET, XAML doesn't have function/class boundaries. Files are chunked via `chunk_adaptive_lines()` (the default for non-code languages). No `XAML_BOUNDARY` regex or `chunk_code()` dispatch needed. The primary value is in KG triple extraction (cross-file linking), not structural chunking.

- **Symbol extraction from XAML.** The meaningful "symbol" for a XAML file is the view name, extracted from the root element's `x:Class` attribute:
  ```xml
  <Window x:Class="MyApp.Views.MainWindow" ...>
  ```
  The `x:Class` attribute contains a fully-qualified CLR name. Extract the short name (last segment after `.`): `"MainWindow"`. Symbol type: `"view"`. If `x:Class` is absent (e.g., resource dictionaries, merged dictionaries), fall back to the filename stem.

- **`_XAML_EXTRACT` pattern list.** One pattern that matches `x:Class="Namespace.ClassName"` in the chunk content and extracts the class short name. Registered in `_LANG_EXTRACT_MAP` under `"xaml"`. Pattern:
  ```python
  _XAML_EXTRACT = [
      (re.compile(r'x:Class="(?:[\w.]+\.)?(\w+)"'), "view"),
  ]
  ```
  Only the first chunk (containing the root element) will match this pattern. Subsequent chunks will get `("", "")` — this is correct behavior; named controls are tracked via KG triples, not symbol extraction.

- **`parse_xaml_file(filepath: Path) -> list` — new function.** Uses `xml.etree.ElementTree` (stdlib). Returns `(subject, predicate, object)` triples. Subject is always the view name (from `x:Class` or filename stem). Extracts:

  1. **Code-behind link**: `(view_name, "has_code_behind", "ViewName.xaml.cs")` — derived from naming convention: the `.xaml` filename with `.cs` appended. Only emitted if a `.xaml.cs` file exists adjacent to the `.xaml` file (check with `filepath.with_suffix('.xaml.cs').exists()`). This avoids phantom triples for resource dictionaries or XAML files without code-behind.

  2. **ViewModel from element DataContext**: Walk the XML tree for elements whose tag ends with `.DataContext` (property element syntax). The child element's tag (stripped of namespace) is the ViewModel class name:
     ```xml
     <Window.DataContext>
         <local:MainViewModel />
     </Window.DataContext>
     ```
     Extract: `(view_name, "binds_viewmodel", "MainViewModel")`.

  3. **ViewModel from d:DataContext attribute**: Regex on raw file content (not parsed XML, because `d:DataContext` uses markup extension syntax that ET doesn't parse):
     ```
     d:DataContext="{d:DesignInstance (?:Type=)?(?:[\w]+:)?(\w+)"
     ```
     Extract: `(view_name, "binds_viewmodel", "MainViewModel")`.

  4. **Named controls (x:Name)**: Walk the XML tree. The `x:Name` attribute is in the XAML namespace `http://schemas.microsoft.com/winfx/2006/xaml`. Look for `{...}Name` attributes on all elements:
     ```xml
     <TextBox x:Name="txtUsername" />
     ```
     Extract: `(view_name, "has_named_control", "txtUsername")`.

  5. **Resource references**: Regex on raw content for `{StaticResource key}` and `{DynamicResource key}`:
     ```
     \{(?:Static|Dynamic)Resource\s+(\w+)\}
     ```
     Extract unique keys: `(view_name, "references_resource", "MyStyle")`. Deduplicate — a resource may be referenced many times in one file.

  6. **Command bindings**: Regex on raw content for `Command="{Binding commandName}"`:
     ```
     Command\s*=\s*"\{Binding\s+(?:Path=)?(\w+)\}"
     ```
     Extract: `(view_name, "uses_command", "SaveCommand")`. Also handle `Command="{Binding Path=SaveCommand}"` form.

- **View name extraction logic.** Shared between `parse_xaml_file` and `_XAML_EXTRACT`:
  1. Parse XML, get root element
  2. Look for `x:Class` attribute — try both `{http://schemas.microsoft.com/winfx/2006/xaml}Class` (namespace-resolved) and raw attribute scan in first 5 lines (fallback for namespace edge cases)
  3. If found, extract short name: `"MyApp.Views.MainWindow"` -> `"MainWindow"`
  4. If not found, use `filepath.stem` (e.g., `App.xaml` -> `"App"`)

- **`_KG_EXTRACT_EXTENSIONS` rename.** The current `_DOTNET_CONFIG_EXTENSIONS` set holds `.csproj`, `.fsproj`, `.vbproj`, `.sln`. Adding `.xaml` makes the name misleading — XAML is not a config file. Rename to `_KG_EXTRACT_EXTENSIONS` (used in 4 places in `mine()`). Add `.xaml` to the set. Update the dispatch in `mine()`:
  ```python
  if filepath.suffix.lower() == ".sln":
      triples = parse_sln_file(filepath)
  elif filepath.suffix.lower() == ".xaml":
      triples = parse_xaml_file(filepath)
  else:
      triples = parse_dotnet_project_file(filepath)
  ```

- **XAML namespace handling.** XAML files declare XML namespaces like:
  ```xml
  xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
  xmlns:local="clr-namespace:MyApp.ViewModels"
  xmlns:d="http://schemas.microsoft.com/expression/blend/2008"
  ```
  `ElementTree` resolves these, so `x:Name` appears as `{http://schemas.microsoft.com/winfx/2006/xaml}Name`. The parser must look for the full namespace URI, not the `x:` prefix (which is just a convention). Define a constant:
  ```python
  _XAML_NS = "http://schemas.microsoft.com/winfx/2006/xaml"
  ```

- **Hybrid parsing approach (ET + regex).** `xml.etree.ElementTree` is used for structured XML traversal (x:Class, x:Name, DataContext elements). Regex is used for attribute values that contain markup extensions (`{Binding ...}`, `{StaticResource ...}`, `{DynamicResource ...}`, `d:DataContext="..."`) because ET does not parse XAML markup extensions — they are opaque string values to the XML parser.

- **Chunking strategy.** XAML files go through `chunk_adaptive_lines()` — the `else` branch in `chunk_file()`. No explicit dispatch entry needed. The `"xaml"` language tag is not added to the `chunk_code()` branch. This is deliberate: XAML is markup, not code; blank-line-based adaptive splitting produces reasonable chunks for XML content.

- **Test file rename.** `tests/test_dotnet_config.py` becomes `tests/test_kg_extract.py` to reflect the broader scope (XAML is not a .NET config file). All existing imports (`from mempalace.miner import parse_dotnet_project_file, parse_sln_file`) are preserved; `parse_xaml_file` is added. Existing test functions are unchanged.

- **XAML test fixtures.** Minimal WPF-style XAML covering the main extraction targets:
  ```xml
  <Window x:Class="MyApp.MainWindow"
          xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
          xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
          xmlns:d="http://schemas.microsoft.com/expression/blend/2008"
          xmlns:local="clr-namespace:MyApp.ViewModels"
          d:DataContext="{d:DesignInstance Type=local:MainViewModel}">
      <Grid>
          <TextBox x:Name="txtUsername" Style="{StaticResource InputStyle}" />
          <Button Content="Save" Command="{Binding SaveCommand}"
                  Background="{DynamicResource ThemeBrush}" />
      </Grid>
  </Window>
  ```
  This single fixture exercises: x:Class, d:DataContext, x:Name, StaticResource, DynamicResource, Command binding.

- **Real-world reference.** The acceptance criteria mention open-rpa/openrpa as a WPF project to validate against. This is a post-implementation smoke test, not an automated test fixture.
