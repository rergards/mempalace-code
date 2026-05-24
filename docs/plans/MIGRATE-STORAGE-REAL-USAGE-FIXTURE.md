---
slug: MIGRATE-STORAGE-REAL-USAGE-FIXTURE
goal: "Add a disposable Chroma-to-Lance migrate-storage smoke runner and release-check documentation."
risk: low
risk_note: "Adds a gated smoke utility, focused tests, and docs without changing migration or storage runtime behavior."
contract_policy:
  flow: full_spdd
  reason: "Strict migration/release-smoke task touches a deprecated optional storage backend and release verification commands."
  sync_gate: required
  verification_path: automated
files:
  - path: scripts/migrate_storage_smoke.py
    change: "Add a disposable [chroma]-gated smoke runner that generates a tiny Chroma source palace, runs the real migrate-storage CLI, verifies source/destination counts, verifies a searchable migrated drawer, and cleans up temporary artifacts."
  - path: tests/test_migrate_storage_smoke.py
    change: "Add focused tests for the smoke runner's fixture generation, missing-[chroma] gate, non-empty destination guard mode, and cleanup behavior."
  - path: docs/BACKUP_RESTORE.md
    change: "Document the manual release-check command for the disposable migrate-storage smoke, including [chroma] installation, model prefetch, expected output, and cleanup boundary."
acceptance:
  - id: AC-1
    when: "Run `python scripts/migrate_storage_smoke.py --rows 3` in an environment installed with `mempalace-code[chroma]`."
    then: "The script creates a temporary legacy Chroma source, runs the real `python -m mempalace_code.cli migrate-storage ... --verify` command, reports source=3 and destination=3, and reports that CLI search found the migrated unique marker."
  - id: AC-2
    when: "Run `python scripts/migrate_storage_smoke.py --exercise-dst-guard` in an environment installed with `mempalace-code[chroma]`."
    then: "The script pre-seeds the Lance destination, observes the real CLI fail without `--force` with an `already contains rows` message, verifies the destination count remains unchanged, prints a guard-ok marker, and exits 0."
  - id: AC-3
    when: "Run `python scripts/migrate_storage_smoke.py --rows 1` in an environment installed with `mempalace-code[chroma]`."
    then: "The one-row boundary fixture migrates with source=1 and destination=1, and search still finds the single migrated marker."
  - id: AC-4
    when: "Run `python -m pytest tests/test_migrate_storage_smoke.py::test_missing_chroma_reports_chroma_extra -q`."
    then: "The missing-Chroma path reports that the [chroma] extra is required and exits before creating fixture data or invoking the migrate-storage CLI."
  - id: AC-5
    when: "Run the documented-docs grep command from the verification plan."
    then: "The release-check docs include the smoke command, the [chroma] gate, the model-prefetch note, expected source/destination/search evidence, and the temporary cleanup boundary."
out_of_scope:
  - "Changing `migrate_chroma_to_lance()` semantics, CLI arguments, backup behavior, or verification rules."
  - "Committing a binary or persistent Chroma palace fixture."
  - "Making ChromaDB part of the default install path."
  - "Backlog bookkeeping or archive file updates."
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "A release operator must have a tiny disposable fixture-generation command gated by the [chroma] extra."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-3, AC-4]
    - id: REQ-2
      statement: "The smoke must exercise the real public migrate-storage CLI rather than direct function calls."
      source: "backlog scope"
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: REQ-3
      statement: "The smoke must verify source count, destination count, and searchable migrated drawer content."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-3]
    - id: REQ-4
      statement: "The smoke must include a concrete failure-path check for destination refusal without --force."
      source: "strict plan failure-path requirement"
      acceptance_ids: [AC-2]
    - id: REQ-5
      statement: "Release-check documentation must show how to run the disposable smoke and what output proves success."
      source: "backlog acceptance"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "disposable migrate-storage smoke CLI"
      kind: "cli"
      paths: ["scripts/migrate_storage_smoke.py"]
      expected_behavior: "Generate a temporary legacy Chroma source with deterministic fixture content, run the real migrate-storage CLI in a subprocess with version checks disabled, assert counts/search evidence, and remove temporary artifacts."
    - name: "smoke runner tests"
      kind: "internal"
      paths: ["tests/test_migrate_storage_smoke.py"]
      expected_behavior: "Protect the script's optional-extra gate, guard-path assertion, count/search evidence parsing, and cleanup behavior without requiring a committed Chroma database."
    - name: "release smoke documentation"
      kind: "internal"
      paths: ["docs/BACKUP_RESTORE.md"]
      expected_behavior: "Document the [chroma]-gated manual release command, model-prefetch note, expected source/destination/search markers, and disposable temp-path cleanup."
  invariants:
    - id: INV-1
      statement: "The existing migrate-storage CLI options, exit codes, backup default, and --verify semantics must remain unchanged."
      applies_to: ["scripts/migrate_storage_smoke.py", "tests/test_migrate_storage_smoke.py"]
    - id: INV-2
      statement: "The default package install must not import or require chromadb; all Chroma-dependent smoke behavior stays gated behind the optional [chroma] extra."
      applies_to: ["scripts/migrate_storage_smoke.py", "tests/test_migrate_storage_smoke.py", "docs/BACKUP_RESTORE.md"]
    - id: INV-3
      statement: "The smoke must not commit or leave persistent Chroma/Lance fixture data in the repository."
      applies_to: ["scripts/migrate_storage_smoke.py", "docs/BACKUP_RESTORE.md"]
    - id: INV-4
      statement: "Existing unit tests for migrate.py and CLI dispatch remain the source of truth for migration algorithm details."
      applies_to: ["tests/test_migrate.py", "tests/test_cli.py", "tests/test_migrate_storage_smoke.py"]
  risks:
    - id: RISK-1
      risk: "Generating a Chroma fixture through the default embedding function could trigger an unexpected model download before the release smoke reaches migrate-storage."
      mitigation: "Seed Chroma with explicit deterministic embeddings or the existing deterministic test embedding pattern so source fixture creation is local and stable."
    - id: RISK-2
      risk: "A helper that calls migrate_chroma_to_lance directly would miss argparse, subprocess, environment, and CLI output issues."
      mitigation: "Have the smoke runner invoke `python -m mempalace_code.cli migrate-storage` and parse the public output."
    - id: RISK-3
      risk: "Version-check prompts or network checks could pollute subprocess output or hang a release smoke."
      mitigation: "Set `MEMPALACE_VERSION_CHECK=0` for subprocess CLI calls and document that boundary."
    - id: RISK-4
      risk: "Temporary smoke artifacts could remain after a failed run and confuse later release checks."
      mitigation: "Use a TemporaryDirectory-style work area, assert cleanup in tests, and document that the command leaves no repository artifacts."
  verification:
    - id: VER-1
      command: "python scripts/migrate_storage_smoke.py --rows 3"
      proves: "the happy-path disposable smoke runs the real CLI, reports matching source/destination counts, and verifies searchable migrated content"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python scripts/migrate_storage_smoke.py --exercise-dst-guard"
      proves: "the smoke covers the non-empty destination failure path without changing destination row count"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python scripts/migrate_storage_smoke.py --rows 1"
      proves: "the smallest non-empty fixture boundary still migrates and remains searchable"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_migrate_storage_smoke.py::test_missing_chroma_reports_chroma_extra -q"
      proves: "the optional [chroma] gate fails clearly before fixture creation or CLI execution"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "rg --fixed-strings --quiet 'migrate-storage smoke' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet '[chroma]' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet 'scripts/migrate_storage_smoke.py' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet 'source=' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet 'search' docs/BACKUP_RESTORE.md"
      proves: "release-check docs expose the command, optional-extra gate, and expected source/destination/search evidence"
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_migrate.py -q"
        proves: "existing Chroma-to-Lance migration behavior, verification, backups, and empty-source handling remain stable"
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-2
        command: "python -m pytest tests/test_cli.py::TestMigrateStorageCommand -q"
        proves: "existing migrate-storage argparse wiring, passthrough options, output, and error exits remain stable"
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-3
        command: "ruff check scripts/migrate_storage_smoke.py tests/test_migrate_storage_smoke.py"
        proves: "the new smoke runner and focused tests remain lint-clean"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-4
        command: "rg --fixed-strings --quiet 'migrate-storage smoke' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet '[chroma]' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet 'scripts/migrate_storage_smoke.py' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet 'source=' docs/BACKUP_RESTORE.md && rg --fixed-strings --quiet 'search' docs/BACKUP_RESTORE.md"
        proves: "release-check docs continue to expose the smoke command, [chroma] gate, and expected source/destination/search evidence; a future doc edit that drops any of these markers is caught"
        acceptance_ids: [AC-5]
---

## Design Notes

- Prefer a generated fixture over a committed Chroma directory. Chroma persistent stores are version-sensitive and binary-ish; a tiny generated source is easier to review and safer to delete.
- Seed source rows with explicit deterministic embeddings or the existing test embedding pattern so Chroma fixture creation does not call Chroma's default embedding function.
- Keep the smoke runner as a release utility under `scripts/`, not as production migration code. It should import Chroma only after checking availability and should print the install hint for `mempalace-code[chroma]` on failure.
- Invoke the migration through `python -m mempalace_code.cli migrate-storage <src> <dst> --backup-dir <tmp>/backups --verify` with `MEMPALACE_VERSION_CHECK=0` in the subprocess environment.
- Verify search through the public CLI or the same search surface users exercise after migration. The output should include a unique fixture marker so the script can assert the migrated drawer, not merely any row.
- The destination guard mode should pre-seed LanceDB, run migrate-storage without `--force`, assert the CLI fails with the existing "already contains rows" message, and verify the pre-seeded count is unchanged.
- Keep the docs section short: install with the `[chroma]` extra, prefetch the embedding model if the release host is offline, run the smoke command, expect count/search markers, and note that temp artifacts are removed.
