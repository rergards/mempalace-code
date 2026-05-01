---
slug: STORE-MIGRATE-CLI-TEST-EXPAND
goal: "Add targeted migrate-storage CLI tests for --verify, --embed-model, and RuntimeError exits."
risk: low
risk_note: "Test-only CLI coverage in an existing pytest class; no production behavior changes."
files:
  - path: tests/test_cli.py
    change: "Add three TestMigrateStorageCommand tests for explicit --verify passthrough, --embed-model passthrough, and RuntimeError stderr/exit handling."
acceptance:
  - id: AC-1
    when: "mempalace migrate-storage SRC DST --verify is exercised through the CLI test helper with the migrator patched."
    then: "migrate_chroma_to_lance receives verify=True while the command otherwise uses the existing successful return path."
  - id: AC-2
    when: "mempalace migrate-storage SRC DST --embed-model test-model is exercised through the CLI test helper with the migrator patched."
    then: "migrate_chroma_to_lance receives embed_model='test-model' exactly."
  - id: AC-3
    when: "the patched migrate_chroma_to_lance raises RuntimeError('boom') during migrate-storage dispatch."
    then: "the CLI raises SystemExit with code 1 and writes an Error: boom message to stderr."
out_of_scope:
  - "Production changes in mempalace_code/cli.py or mempalace_code/migrate.py."
  - "Integration migration coverage that requires a real ChromaDB installation."
  - "Changing default migrate-storage option values or output wording outside the RuntimeError assertion."
---

## Design Notes

- Place the tests in `tests/test_cli.py::TestMigrateStorageCommand` next to the existing happy-path, VerificationError, `--backup-dir`, and `--force` coverage.
- Reuse the class-local `_run()` helper so each test exercises argparse wiring through `main()` rather than calling `cmd_migrate_storage()` directly.
- Patch `mempalace_code.migrate.migrate_chroma_to_lance`, matching the existing tests and avoiding optional ChromaDB imports.
- Use `mock_migrate.call_args.kwargs[...]` for the flag passthrough assertions so the tests fail on the specific kwarg regression.
- The RuntimeError test should capture stderr with `capsys` and assert both `SystemExit.code == 1` and the `Error:` prefix.
