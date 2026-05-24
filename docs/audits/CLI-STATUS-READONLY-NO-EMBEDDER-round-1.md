slug: CLI-STATUS-READONLY-NO-EMBEDDER
round: 1
date: 2026-05-24
commit_range: 08bee9d..52bbb5a
findings:
  - id: F-1
    title: "No exception wrapper around open_store for corrupt-but-existing lance/ directories"
    severity: low
    location: "mempalace_code/mining/orchestrator.py:604"
    claim: >
      The original status() had a try/except around open_store() that caught all exceptions and
      printed "No palace found." The new code replaces it with an os.path.isdir() preflight and
      a store._table is None check. If lancedb.connect() raises for a corrupt-but-existing lance/
      directory, the exception propagates uncaught to the CLI. In practice this is negligible:
      lancedb.connect() almost never raises for an existing directory, and all open_table()
      failures are already caught inside LanceStore._open_or_create with read_only=True.
    decision: dismissed
  - id: F-2
    title: "VER-4 audit: layers.py and palace_graph.py are read-only non-search callers without read_only=True"
    severity: medium
    location: "mempalace_code/layers.py:92,199,265,321,444; mempalace_code/palace_graph.py:35"
    claim: >
      The VER-4 open_store(create=False) audit (required by AC-4) identified layers.py (5 call
      sites) and palace_graph.py (1 call site) as non-search, read-only callers that open the
      store without read_only=True. Both use col.get() / metadata scans that do not require a
      query vector, so they should not need to initialize the embedding model. Users running
      layer generation or graph traversal commands against a populated palace will still pay the
      model startup cost. This is out of scope for this task per the plan contract, so it is
      backlogged rather than fixed here.
    decision: backlogged
    backlog_slug: CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER
totals:
  fixed: 0
  backlogged: 1
  dismissed: 1
fixes_applied: []
new_backlog:
  - slug: CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER
    summary: "Make layers.py and palace_graph.py read-only store opens avoid embedding model startup"
