---
slug: CLI-EXPORT-STDOUT-CLEAN
goal: "Keep `mempalace-code export --out -` stdout pure JSONL"
risk: low
risk_note: "CLI output routing only; no storage format, persistence, or import semantics change."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: single CLI output-routing bug, no auth/data/migration/provider/pipeline boundary, and the fix is confined to command output behavior."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/cli_commands/export_import.py
    change: "Route human progress and summary text to stderr when exporting to stdout so JSONL stays on stdout."
  - path: tests/test_cli.py
    change: "Add CLI-level coverage that `export --out -` emits only JSONL on stdout and sends non-JSON text to stderr."
acceptance:
  - id: AC-1
    when: "Run `mempalace-code --palace <temp-palace> export --out - --only-manual` against a palace with manual drawers."
    then: "stdout begins with a valid JSONL export header record and contains no human progress or summary text."
  - id: AC-2
    when: "Capture stderr from the same `export --out -` command."
    then: "stderr contains the human progress and completion summary lines that used to pollute stdout."
  - id: AC-3
    when: "Pipe `mempalace-code export --out - ...` directly into `mempalace-code import - --dry-run`."
    then: "The pipeline succeeds without filtering, and the import reads the JSONL stream as-is."
  - id: AC-4
    when: "Run `mempalace-code export --out <file>` with a real file path."
    then: "The command still writes the same JSONL export file, and the human-readable progress output remains visible on stderr."
out_of_scope:
  - "Change export/import record format, header schema, or JSONL field ordering."
  - "Alter import deduplication, KG export behavior, or backup/restore commands."
  - "Refactor unrelated CLI commands or global logging configuration."

## Design Notes

- Keep the serializer in `mempalace_code/export.py` unchanged unless the CLI fix exposes an unexpected write path.
- The observable bug is command-layer routing, so the fix should prefer stderr redirection over changing JSONL generation semantics.
- Add the narrowest CLI test that proves stdout is machine-parseable and stderr carries the human text.
- Preserve existing behavior for file-backed exports so this remains a stdout-specific change.
