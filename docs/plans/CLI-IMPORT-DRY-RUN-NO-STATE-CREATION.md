---
slug: CLI-IMPORT-DRY-RUN-NO-STATE-CREATION
status: completed
authority: non_authoritative
goal: "Make import dry-run preview counts and deduplication without creating or modifying palace, knowledge-graph, temporary, or model/cache state"
risk: medium
risk_note: "The change is narrow but controls a release-blocking CLI storage boundary; incorrect initialization could either mutate preview state or change live import and dedup behavior."
files:
  - path: mempalace_code/cli_commands/export_import.py
    change: "Open a read-only non-creating store and lazy KG proxy only for dry-run, while preserving current write-capable initialization for live imports."
  - path: tests/test_cli.py
    change: "Add focused public-CLI regressions for absent and existing state, malformed input, explicit palace and skip-KG boundaries, repeated dry-runs, preview counts/deduplication, and live import writes."
acceptance:
  - id: AC-1
    when: "import --dry-run processes valid drawer and KG records with isolated absent explicit palace and default KG destinations"
    then: "the command reports preview counts and creates no directories, Lance state, SQLite files, temporary files, embedding-model state, or cache files"
  - id: AC-2
    when: "import --dry-run processes new and duplicate records against seeded existing palace and global KG state"
    then: "the command reports the same imported, duplicate, and KG preview counts on repeated runs while filesystem snapshots and palace/KG health remain unchanged"
  - id: AC-3
    when: "import preview is exercised with malformed input, explicit --palace, --skip-kg, an absent destination, and duplicate invocation"
    then: "malformed input exits before any store or KG object opens, skip-KG reports no KG imports, and every preview invocation leaves all selected state unchanged"
  - id: AC-4
    when: "the same valid import is run without --dry-run against absent palace and KG destinations"
    then: "the existing live path creates the palace and KG state and persists the expected drawer and triple"
out_of_scope:
  - "Changing import_jsonl parsing, preview counting, deduplication thresholds, warning text, or write semantics."
  - "Adding a preview backend, no-op store/KG implementation, CLI option, configuration field, or parallel import path."
  - "Changing export, mining, watcher, backup/restore, storage backend, embedding model, or KG schema behavior."
  - "Changing the historical KG destination selected by live import."
contract_policy:
  flow: full_spdd
  reason: "Standard release-blocking bug at a CLI and persistent-state boundary requires explicit behavioral contracts and regression proof."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Import dry-run must preview valid drawer and KG records without creating any state when palace and KG destinations are absent."
      source: "backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Import dry-run must preserve preview counts and dedup behavior against existing state without changing that state."
      source: "backlog AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Malformed input and dry-run boundary combinations must fail or preview before any state-opening mutation can occur."
      source: "backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Live import must retain its existing create-and-write behavior."
      source: "backlog AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "import command handler"
      kind: cli
      paths: ["mempalace_code/cli_commands/export_import.py"]
      expected_behavior: "Dry-run passes the validated records to the existing import engine with non-creating read-only palace access and a non-instantiated KG proxy; live import keeps write-capable objects."
    - name: "import CLI regression coverage"
      kind: internal
      paths: ["tests/test_cli.py"]
      expected_behavior: "Public CLI invocations prove preview output, deduplication, failure ordering, repeat safety, filesystem immutability, and live writes."
  invariants:
    - id: INV-1
      statement: "Validated records continue through import_jsonl as the single implementation of import counting, deduplication, warnings, and writes."
      applies_to: ["mempalace_code/cli_commands/export_import.py"]
    - id: INV-2
      statement: "Live import continues to open the palace with create=True and construct the existing writable KnowledgeGraph destination."
      applies_to: ["mempalace_code/cli_commands/export_import.py"]
    - id: INV-3
      statement: "Malformed file and stdin JSONL continue to be fully buffered and rejected before palace or KG initialization."
      applies_to: ["mempalace_code/cli_commands/export_import.py", "tests/test_cli.py"]
    - id: INV-4
      statement: "Duplicate detection remains enabled unless --skip-dedup is supplied, with its current similarity threshold and count semantics."
      applies_to: ["mempalace_code/cli_commands/export_import.py", "tests/test_cli.py"]
  risks:
    - id: RISK-1
      risk: "A missing-palace preview could initialize the embedder or create Lance directories while attempting deduplication."
      mitigation: "Use the existing read_only LanceStore stub, whose query returns empty results before embedding when no table exists; guard model initialization and snapshot an isolated process temporary directory in the absent-state CLI test."
    - id: RISK-2
      risk: "Avoiding KG construction could accidentally suppress dry-run triple counts."
      mitigation: "Pass the existing LazyKnowledgeGraph proxy so import_jsonl sees a KG target for counting but never invokes SQLite during dry-run."
    - id: RISK-3
      risk: "A shared initialization change could make live imports read-only or lazy and stop persistence."
      mitigation: "Branch only object construction on args.dry_run and verify a non-dry-run invocation creates and writes both stores."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_cli.py::TestImportDryRunReadOnly -q"
      owner: provider
      proves: "The public CLI covers absent and existing state, preview counts and deduplication, malformed and skip-KG boundaries, repeated preview immutability, and unchanged live writes."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_cli.py::TestImportMissingFile -q"
        owner: provider
        proves: "Existing missing-file recovery output and valid-file entry into the live storage path remain compatible with the initialization change."
        acceptance_ids: [AC-3, AC-4]
---

## Design Notes

- In `cmd_import`, keep the existing missing-file guard and full `read_jsonl` buffering before every storage object is selected.
- For `args.dry_run`, call `open_store(palace_path, create=False, read_only=True)`. A missing palace returns the existing table-less LanceStore stub; its `query()` returns empty dedup results before `_ensure_embedder()`, so preview neither creates the palace nor initializes model/cache state.
- For dry-run KG inclusion, use the existing `LazyKnowledgeGraph` with the same default path semantics as `KnowledgeGraph()`. `import_jsonl` checks that the KG argument is present, increments triple counts, and returns before calling `add_triple`, so SQLite is never opened. Keep `kg=None` for `--skip-kg`.
- For non-dry-run, retain `open_store(palace_path, create=True)` and `KnowledgeGraph()` exactly as the current live path uses them.
- Do not change `import_jsonl`; it already owns preview counts, duplicate queries, warning behavior, and the dry-run guards around drawer/KG writes.
- Add one focused `TestImportDryRunReadOnly` class in `tests/test_cli.py`. Set `HOME` to the test directory so the default KG and possible caches are observable. Pre-create an isolated process temporary directory, bind `TMPDIR`, `TMP`, and `TEMP` to it, and set Python's cached `tempfile.tempdir` to the same path before invoking the CLI. Create the JSONL fixture before the baseline snapshot, include both the test directory and isolated temporary directory in recursive file-name-and-byte snapshots, and assert both snapshots remain unchanged after each preview.
- Seed existing-state cases before snapshotting, record `health_check()` and KG stats before/after, and include one duplicate plus one new drawer so reported `imported_drawers`, `skipped_duplicates`, and `imported_triples` are all asserted.
- Patch `LanceStore._get_embedder` to fail in the absent-state case. Existing-state dedup requires embeddings by contract, so use the repository's deterministic test embedder there and prove palace/KG filesystem and health stability instead.
- Patch the store and KG constructors in the malformed-input case and assert they are not called. Exercise explicit `--palace`, `--skip-kg`, missing state, and two identical dry-run invocations through `main()` rather than calling the handler directly.
- The verification commands run from the repository root with the Python pytest configuration in `pyproject.toml`; the focused class/node IDs keep provider-owned checks bounded and unfiltered.
