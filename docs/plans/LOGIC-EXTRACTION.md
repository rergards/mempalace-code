---
slug: LOGIC-EXTRACTION
goal: "Add MCP tool mempalace_extract_reusable that classifies transitive dependencies of a symbol/project as core, platform, or glue and identifies the minimal public interface for extraction"
risk: low
risk_note: "Composes existing KG query primitives (query_entity, query_relationship) with a BFS traversal pattern already proven in type_dependency_chain. No schema changes, no new storage, no new dependencies. Classification logic is pure pattern-matching on KG predicate names and entity values. Same architectural pattern as tool_explain_subsystem (thin handler composing existing primitives). Limitation: KG entities are matched by exact short name — same-name types in different namespaces are not coalesced."
files:
  - path: mempalace/mcp_server.py
    change: "Add tool_extract_reusable() handler. Algorithm: (1) query root entity via _kg.query_entity, (2) BFS-expand outgoing edges following EXPANSION_PREDICATES, filtering to current facts only via fact['current'] (matching tool_explain_subsystem pattern), (3) classify each entity as core/platform/glue — entities whose name matches PLATFORM_PACKAGE_PREFIXES are classified as platform directly (leaf package nodes); other entities are classified by their outgoing deps/predicates, (4) detect glue nodes (implement core-classified interfaces AND have platform deps), (5) extract boundary interfaces (implements-only, not inherits) at core-platform edges. Add TOOLS dict entry with input_schema. Update module docstring tool inventory. Add PLATFORM_PACKAGE_PREFIXES, PLATFORM_FRAMEWORK_MARKERS, PLATFORM_KG_PREDICATES module-level constants."
  - path: tests/test_mcp_server.py
    change: "Add TestExtractReusable class to the existing TestArchTools suite (or as a sibling class). Tests: pure core graph (no platform deps) classifies all as core; pure platform graph classifies as platform with evidence; mixed graph detects glue at interface boundary (implements-only, not inherits); empty KG returns valid empty response; cycle-safe traversal; max_depth caps expansion; boundary_interfaces lists the core interfaces implemented by glue nodes; entity not in KG returns empty graph, no error; solution-level input expands contained projects; package leaf nodes (e.g. System.Windows.Forms@8.0) classified as platform by name; expired KG facts excluded from traversal and classification; tool appears in tools/list."
acceptance:
  - id: AC-1
    when: "mempalace_extract_reusable(entity='MyService') and KG has (MyService, implements, IService), (MyService, inherits, BaseService), and none have platform deps"
    then: "All three entities classified as 'core' in the graph partition"
  - id: AC-2
    when: "KG has (WpfView, depends_on, 'Microsoft.WindowsDesktop.App.WPF@*') and (WpfView, binds_viewmodel, MainViewModel)"
    then: "WpfView classified as 'platform' with evidence listing the platform package dependency and the binds_viewmodel predicate"
  - id: AC-3
    when: "KG has (GlueAdapter, implements, IService) where IService is core-classified, and (GlueAdapter, depends_on, 'System.Windows.Forms@*')"
    then: "GlueAdapter classified as 'glue' (via `implements` IService + platform dep); boundary_interfaces includes IService with GlueAdapter as implementor"
  - id: AC-4
    when: "Entity has no facts in the KG"
    then: "Returns {entity, graph: {core: [], platform: [], glue: []}, boundary_interfaces: [], summary: {total_entities: 0, core_count: 0, platform_count: 0, glue_count: 0, boundary_interface_count: 0}} -- no error"
  - id: AC-5
    when: "KG has circular references (TypeA depends_on TypeB, TypeB depends_on TypeA)"
    then: "Traversal terminates without infinite loop; both entities appear exactly once"
  - id: AC-6
    when: "mempalace_extract_reusable(entity='MyService', max_depth=1) and KG has depth-3 chain"
    then: "Only direct (depth-1) dependencies are included; deeper nodes are omitted"
  - id: AC-7
    when: "KG has expired relationships (valid_to set) for the target entity"
    then: "Expired relationships are excluded from traversal and classification"
  - id: AC-8
    when: "mempalace_extract_reusable appears in tools/list MCP response"
    then: "Has name, description, and inputSchema with entity (required) and max_depth (optional)"
  - id: AC-9
    when: "Running `python -m pytest tests/ -x -q` and `ruff check mempalace/ tests/`"
    then: "All tests pass and lint is clean"
  - id: AC-10
    when: "KG has a solution with contained projects having mixed platform/core deps"
    then: "Solution-level query expands through contains_project to analyze each project's dependencies"
out_of_scope:
  - "Source code analysis or import scanning -- classification uses only existing KG data (pre-mined deps, frameworks, XAML bindings)"
  - "Custom platform pattern configuration -- static built-in patterns for .NET/WPF/MAUI/Xamarin; extend later if other ecosystems need it"
  - "Visualization output (Mermaid, DOT) -- returns structured JSON; rendering is the caller's job"
  - "New CLI command -- MCP-only tool"
  - "Drawer content scanning for import statements -- relies on KG triples from miner (parse_dotnet_project_file, parse_xaml_file, extract_type_relationships)"
  - "Changes to knowledge_graph.py -- BFS traversal lives in the handler following the arch-tool pattern; type_dependency_chain is not modified"
  - "Scoring or ranking of reusability -- binary classification only (core/platform/glue)"
  - "Short-name entity coalescing across namespaces -- KG entities are matched by exact name as stored; same-name types in different namespaces are treated as distinct entities"
---

## Design Notes

### Composition pattern: KG-only traversal and classification

Like `tool_explain_subsystem`, this handler lives in `mcp_server.py` and composes existing KG primitives. Unlike `explain_subsystem`, it does **not** use the vector store (no semantic search). All data comes from the knowledge graph, which already contains:
- Package dependencies (`depends_on`) from `parse_dotnet_project_file()`
- Framework targets (`targets_framework`) from `parse_dotnet_project_file()`
- Type relationships (`implements`, `inherits`, `extends`) from `extract_type_relationships()`
- XAML bindings (`binds_viewmodel`, `has_code_behind`, `has_named_control`, `references_resource`, `uses_command`) from `parse_xaml_file()`
- Solution membership (`contains_project`) from `parse_sln_file()`
- Project references (`references_project`) from `parse_dotnet_project_file()`

### Algorithm

```
tool_extract_reusable(entity, max_depth=3):
  1. BFS from entity following EXPANSION_PREDICATES (outgoing only):
     {depends_on, references_project, implements, inherits, extends, contains_project}
     Cycle-safe via visited set. Caps at max_depth.
     At each node, call _kg.query_entity(name, direction="outgoing") and filter
     to current facts only via `fact["current"]` — matching the pattern used by
     tool_explain_subsystem and type_dependency_chain. Expired facts are skipped
     entirely (not traversed, not classified).
     Collect: {entity_name: {depth, current_outgoing_facts[]}}

  2. Classify each entity:
     a. FIRST: if the entity name itself matches PLATFORM_PACKAGE_PREFIXES
        (e.g. "System.Windows.Forms@8.0"), classify as "platform" directly.
        These are leaf package nodes with no outgoing KG facts of their own.
     b. Otherwise, check outgoing depends_on objects against PLATFORM_PACKAGE_PREFIXES
     c. Check targets_framework (via query_entity) against PLATFORM_FRAMEWORK_MARKERS
     d. Check for PLATFORM_KG_PREDICATES (binds_viewmodel, has_code_behind, etc.)
     → If any of b/c/d match: "platform" (record matching evidence)
     → If no match: "core" (tentative)

  3. Promote core→glue:
     For each tentatively-core entity:
       If it `implements` a core-classified interface
       AND (it depends_on a platform-classified entity OR has platform deps):
         Reclassify as "glue"
     (Glue = bridge between core interface and platform implementation)
     Note: only `implements` triggers glue promotion, not `inherits`.
     Base-class inheritance is implementation detail, not a swappable contract.

  4. Extract boundary interfaces:
     For each glue entity, collect the core interfaces it `implements`.
     These are the "minimal public interface" for extraction —
     the contracts that allow swapping the platform implementation.
     Only `implements` relationships qualify; `inherits` (base classes)
     are excluded because they represent implementation coupling, not contracts.

  5. Return {entity, graph: {core, platform, glue}, boundary_interfaces, summary}
```

### Platform detection constants

```python
PLATFORM_PACKAGE_PREFIXES = (
    "System.Windows.",
    "Microsoft.WindowsDesktop.",
    "Microsoft.Maui.",
    "Xamarin.",
    "Avalonia.",
    "System.Drawing.",
)

PLATFORM_FRAMEWORK_MARKERS = (
    "-windows", "-android", "-ios", "-macos", "-maccatalyst", "-tizen",
)

PLATFORM_KG_PREDICATES = frozenset({
    "binds_viewmodel",
    "has_code_behind",
    "has_named_control",
    "references_resource",
    "uses_command",
})
```

These are intentionally conservative. Only indicators that clearly signal UI/platform coupling are included. The prefixes use `str.startswith` matching (not fnmatch) to avoid false positives. Package leaf nodes (entities that match `PLATFORM_PACKAGE_PREFIXES` by name) are classified as `platform` directly, since they have no outgoing KG facts of their own.

### Traversal vs type_dependency_chain

`type_dependency_chain()` walks up (ancestors) and down (descendants) using a fixed set of type predicates. This tool's BFS is **outgoing-only** and uses a broader predicate set that includes package deps and project references. The pattern is similar (BFS with visited set and depth cap) but the semantics differ enough to keep them separate.

### Response structure

```python
{
    "entity": "MyApp",
    "graph": {
        "core": [
            {"entity": "IService", "depth": 2, "via": "implements"}
        ],
        "platform": [
            {"entity": "System.Windows.Forms@*", "depth": 1,
             "evidence": ["package name matches platform prefix System.Windows."]}
        ],
        "glue": [
            {"entity": "WinFormsAdapter", "depth": 1,
             "core_interfaces": ["IService"],
             "platform_deps": ["System.Windows.Forms@*"]}
        ]
    },
    "boundary_interfaces": [
        {"interface": "IService",  # implements-only; inherits excluded
         "implemented_by": [
             {"entity": "WinFormsAdapter", "classification": "glue"}
         ]}
    ],
    "summary": {
        "total_entities": 4,
        "core_count": 1,
        "platform_count": 1,
        "glue_count": 1,
        "boundary_interface_count": 1
    }
}
```

### Test fixture design

Tests use the existing `kg` fixture and `_patch_mcp_server` helper. The `dotnet_kg` fixture from `TestArchTools` provides a good base; extend it with platform-specific deps for the new tests:

```python
@pytest.fixture
def extraction_kg(self, kg):
    # Core types
    kg.add_triple("IService", "extends", "IDisposable")
    # Core implementation
    kg.add_triple("CoreService", "implements", "IService")
    # Platform deps
    kg.add_triple("WpfView", "depends_on", "Microsoft.WindowsDesktop.App.WPF@8.0")
    kg.add_triple("WpfView", "binds_viewmodel", "MainViewModel")
    # Glue (implements core interface + has platform dep)
    kg.add_triple("WinFormsAdapter", "implements", "IService")
    kg.add_triple("WinFormsAdapter", "depends_on", "System.Windows.Forms@8.0")
    # Project-level
    kg.add_triple("MyApp", "references_project", "CoreLib")
    kg.add_triple("MyApp", "targets_framework", "net8.0-windows")
    kg.add_triple("MySolution", "contains_project", "MyApp")
    kg.add_triple("MySolution", "contains_project", "CoreLib")
    kg.add_triple("CoreLib", "targets_framework", "netstandard2.0")
    return kg
```
