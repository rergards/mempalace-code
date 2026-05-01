---
slug: ARCH-EXTRACTION-MODE
goal: "Plan a post-mining architecture extraction pass that emits pattern, layer, namespace, and project KG facts."
risk: medium
risk_note: "Touches incremental mining and KG lifecycle; predicate-scoped invalidation is needed to avoid stale or expired unrelated facts."
files:
  - path: mempalace_code/architecture.py
    change: "Add rule loading, symbol inventory, namespace/project clustering, pattern detection, layer detection, and architecture triple generation."
  - path: mempalace_code/knowledge_graph.py
    change: "Add predicate-scoped source-file invalidation so architecture facts can be refreshed without expiring type dependency facts."
  - path: mempalace_code/miner.py
    change: "Run the architecture extraction pass after code KG extraction when KG is available, using project config and source-file provenance."
  - path: tests/test_architecture_extraction.py
    change: "Cover architecture rule parsing, pattern/layer classification, mining integration, stale-fact invalidation, and malformed-rule behavior."
  - path: tests/test_mcp_server.py
    change: "Add MCP-level coverage showing architecture facts are queryable through mempalace_kg_query incoming lookups."
  - path: README.md
    change: "Document architecture extraction config and KG query examples for services and layers."
  - path: CHANGELOG.md
    change: "Record the new architecture extraction mode and queryable KG predicates."
acceptance:
  - id: AC-1
    when: "A fixture .NET project with UserService, UserRepository, UserController, MainViewModel, and OrderFactory is mined with KG enabled."
    then: "mempalace_kg_query(entity='Service', direction='incoming') returns UserService via is_pattern, and entity='Data' returns UserRepository via is_layer."
  - id: AC-2
    when: "mempalace.yaml defines architecture rules that classify AuditHandler as pattern Service and namespace Company.Audit as layer Business."
    then: "After mine --full, KG facts include AuditHandler is_pattern Service and AuditHandler is_layer Business even though the name has no Service suffix."
  - id: AC-3
    when: "architecture rule config contains unsupported shapes such as scalar pattern lists or non-string namespace entries."
    then: "mining completes without an exception and no architecture facts are emitted from the invalid rule entries."
  - id: AC-4
    when: "A previously mined UserService.cs is changed to UserManager.cs and the project is mined again incrementally."
    then: "the old UserService is_pattern Service fact is no longer current, and UserManager has no Service pattern fact."
  - id: AC-5
    when: "A type matches multiple pattern suffixes but multiple layer rules, such as BillingServiceFactory under Company.Infrastructure."
    then: "KG stores both Service and Factory is_pattern facts, but exactly one current is_layer fact selected by configured layer priority."
out_of_scope:
  - "Changing drawer chunk content or summarizing source files."
  - "Replacing the existing type dependency extractors for C#, F#, VB.NET, XAML, or Python."
  - "Adding an external graph database, LLM-based architecture inference, or network calls."
  - "Automatically re-mining solely because mempalace.yaml architecture rules changed in watcher mode."
---

## Design Notes

- Add `mempalace_code/architecture.py` as the implementation boundary for heuristic architecture extraction. Keep miner integration thin and avoid expanding `miner.py` with another large matcher block.
- Inputs should be the project root, current mined file list, resolved wing/project context, `mempalace.yaml` config, and an optional `.csproj` room/project map when `dotnet_structure` is enabled.
- Emit KG triples with source-file provenance:
  - `(<type>, "is_pattern", "Service" | "Repository" | "Controller" | "ViewModel" | "Factory")`
  - `(<type>, "is_layer", "UI" | "Business" | "Data" | "Infrastructure")`
  - `(<type>, "in_namespace", <namespace>)`
  - `(<type>, "in_project", <project>)`
  - `(<namespace>, "in_project", <project>)`
- Keep pattern detection non-exclusive. A type can be both `Service` and `Factory`.
- Keep layer detection exclusive. Use explicit config order first, then default priority; store one current `is_layer` fact per type.
- Default rules should cover common .NET conventions:
  - `Controller`, `ViewModel`, XAML `view`, and `*.UI` / `*.Web` / `*.Presentation` namespaces map to `UI`.
  - `Repository` and `*.Data` / `*.Persistence` namespaces map to `Data`.
  - `Service` and `*.Application` / `*.Domain` namespaces map to `Business`.
  - `*.Infrastructure`, adapters, clients, and framework-facing namespaces map to `Infrastructure`.
- Config should merge over defaults under an `architecture:` block, with `enabled: false` disabling the pass. Invalid rule entries should be ignored with deterministic warnings or test-visible empty output, not process failure.
- Add predicate-scoped invalidation to `KnowledgeGraph.invalidate_by_source_file(source_file, predicates=None)`. Existing callers should keep old behavior when `predicates` is omitted; architecture refresh should invalidate only architecture predicates before re-emitting them.
- Run architecture extraction after per-file KG extraction and before stale-file sweep completes. For deleted files, stale sweep must expire architecture predicates together with existing source-scoped facts.
- Use existing `mempalace_kg_query` for queryability. "Show all services" is `entity="Service", direction="incoming"` filtered to `is_pattern`; "show data layer" is `entity="Data", direction="incoming"` filtered to `is_layer`.
- Tests should prefer direct `KnowledgeGraph` and `mine()` fixtures over CLI subprocesses, with one MCP tool assertion to prove the public query surface.
