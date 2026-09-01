---
slug: COMPRESS-RETRY-IDEMPOTENT-RECOVERY
status: completed
authority: non_authoritative
goal: "Make compression retries idempotent, reversible, and explicit about invalid or empty scopes."
risk: high
risk_note: "The command performs lossy in-place writes; ordering mistakes could re-compress content, mutate before backup or filter validation, or report success before durable post-state is proven."
files:
  - path: mempalace_code/cli_commands/query.py
    change: "Validate an explicit wing before mutation, partition drawers by existing compression metadata, back up before pending live writes, skip completed drawers on every retry, verify stored post-state, and print bounded recovery/output counts."
  - path: tests/test_cli.py
    change: "Add focused command regressions for identical and partial retries, mixed pending/compressed scopes, dry-run, backup and verification ordering, recovery output, unknown wings, and valid empty scopes."
  - path: tests/test_cli_golden_scenarios.py
    change: "Add a direct subprocess scenario for source and exact-wheel modes that proves live retry byte stability, managed backup/recovery output, searchability, unknown-wing refusal, and mixed-scope behavior."
acceptance:
  - id: AC-1
    when: "an immediate identical direct fresh-wheel compress retry targets drawers completed by the first invocation"
    then: "the retry exits 0, performs zero drawer-content changes, creates no additional backup, and reports the already compressed drawers as skipped"
  - id: AC-2
    when: "a selected wing contains both never-compressed and already compressed drawers"
    then: "only never-compressed drawers are compressed and every previously compressed drawer remains byte-for-byte stable"
  - id: AC-3
    when: "compress --dry-run selects pending and already compressed drawers"
    then: "it reports pending and skipped counts separately, previews only pending compression, and leaves drawer content, metadata, and backup state unchanged"
  - id: AC-4
    when: "the first live compression invocation has at least one pending drawer"
    then: "one managed backup completes before the first upsert, output gives its archive path and one runnable restore command, and success is printed only after all intended drawer content and compression metadata are re-read and verified"
  - id: AC-5
    when: "a live mixed-scope invocation partially succeeds and a retry processes the same scope in a different or repeated order"
    then: "the retry skips every completed drawer, processes only remaining pending drawers, and cannot compress completed content again"
  - id: AC-6
    when: "compress receives an explicit unknown wing in a non-empty palace or receives a valid scope with zero selected drawers"
    then: "the unknown wing exits 2 before backup or upsert, names the supplied filter, and prints the existing status/taxonomy discovery command; the valid empty scope exits 0 with truthful no-op guidance"
  - id: AC-7
    when: "focused, full non-network, and exact-wheel direct application checks exercise compression"
    then: "existing per-drawer and total output, compression metadata, searchability, managed-backup retention, dry-run read-only behavior, and installed-console provenance remain successful"
out_of_scope:
  - "Changing Dialect compression, token estimation, chunking, mining, search ranking, or drawer IDs."
  - "Adding a compressor, compression format/version, metadata field, storage abstraction, CLI flag, release gate, or alternate recovery mechanism."
  - "Changing backup archive format, restore semantics, retention policy, taxonomy rules, or discovery wording owned by their existing modules."
  - "Editing backlog metadata, release bookkeeping, or runner-owned finalization artifacts."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release fix changes a lossy state-writing CLI path and must coordinate retry state, validation, backup, recovery, post-state verification, and installed application behavior."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "An identical retry must be a byte-stable no-op that reports completed drawers as skipped."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "A mixed scope must compress only drawers without existing compression state."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Dry-run must distinguish pending and completed drawers without changing palace or backup state."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Every live invocation with pending writes must create a recoverable backup before mutation and verify the resulting stored state before success."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Partial, repeated, or reordered retries must resume from persisted per-drawer completion state."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "An unknown explicit wing must fail before mutation while a valid empty selection remains a truthful success."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "Existing compression, storage, backup, search, and exact-wheel contracts must remain intact."
      source: "current backlog contract AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "compression retry and recovery command"
      kind: cli
      paths: ["mempalace_code/cli_commands/query.py"]
      expected_behavior: "The existing command validates scope, classifies persisted drawer state, previews or mutates only pending drawers, backs up before live writes, and verifies/report post-state through one control path."
  invariants:
    - id: INV-1
      statement: "Dialect.compress and Dialect.compression_stats remain the sole compression and per-drawer accounting owners; final totals continue to sum only drawers processed by the invocation."
      applies_to: ["mempalace_code/cli_commands/query.py"]
    - id: INV-2
      statement: "The existing compression_ratio and original_tokens fields remain the only persisted completion evidence; storage schema and metadata defaults do not change."
      applies_to: ["mempalace_code/cli_commands/query.py"]
    - id: INV-3
      statement: "Dry-run opens storage read-only and performs no backup, upsert, metadata change, or embedder initialization."
      applies_to: ["mempalace_code/cli_commands/query.py", "tests/test_cli.py"]
    - id: INV-4
      statement: "Unknown-wing diagnostics continue to come from the shared taxonomy validator and formatter without rewriting or broadening the supplied filter."
      applies_to: ["mempalace_code/cli_commands/query.py"]
    - id: INV-5
      statement: "Backup creation and restoration continue through create_backup and the existing restore CLI, including current managed retention and palace-local KG scoping."
      applies_to: ["mempalace_code/cli_commands/query.py", "tests/test_cli.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-6
      statement: "The exact-wheel scenario continues to use the existing isolated environment, neutral cwd, absolute installed console, offline model cache, and executable provenance checks."
      applies_to: ["tests/test_cli_golden_scenarios.py"]
  risks:
    - id: RISK-1
      risk: "Default-valued metadata could be mistaken for completed state or a completed drawer could be admitted to compression again."
      mitigation: "Centralize the existing metadata-state predicate in cmd_compress, test pending/completed mixtures and reordered inputs, and assert completed bytes never reach Dialect.compress or store.upsert."
    - id: RISK-2
      risk: "A validation or backup failure could occur after the first destructive upsert."
      mitigation: "Validate explicit taxonomy and complete one managed palace-local backup before entering the existing upsert loop; assert call order and zero mutation on both failures."
    - id: RISK-3
      risk: "A partial write could make a blind retry compress the already-updated prefix again."
      mitigation: "Persist completion metadata in each existing atomic drawer upsert and recompute pending state from a fresh store read on every invocation."
    - id: RISK-4
      risk: "The command could print success while an upsert was lost or stored content differs from the intended compressed value."
      mitigation: "Re-read the exact pending IDs after the loop, compare ID, document, and compression metadata post-state, and exit nonzero with the same restore command on mismatch."
    - id: RISK-5
      risk: "In-process mocks could pass while the installed console still recompresses drawers or emits unusable recovery output."
      mitigation: "Exercise live apply, retry, unknown wing, restore command shape, backup count, byte snapshots, and search through the existing source/exact-wheel subprocess harness."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_cli.py::TestCompressRetryIdempotentRecovery tests/test_cli_golden_scenarios.py::test_cli_golden_compress_retry_idempotent_recovery -q"
      proves: "Focused in-process and direct source-console checks cover identical and partial retries, mixed scopes, dry-run, backup/upsert/verification ordering, recovery output, unknown and empty scopes, byte stability, and searchability."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The configured exact-wheel owner runs the same direct compression scenario through the installed console with isolated state and executable provenance."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The configured full non-network suite preserves existing dialect, compression output/accounting, metadata, storage, taxonomy, backup/restore retention, search, and CLI behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
---

## Design Notes

- Keep all production changes in `cmd_compress`. Before opening the live write handle or creating a backup, call the existing palace-path taxonomy validator for an explicit `--wing`; render its existing payload to stderr and exit 2 on an unknown wing. Preserve the validator's current empty/degraded-taxonomy boundary so an empty palace remains the existing no-op path.
- Read the selected rows once per invocation and partition them into `pending` and `already_compressed` using the existing compression metadata written by this command. Treat positive `original_tokens` or non-default `compression_ratio` as completed evidence. Do not infer completion from compressed-looking text and do not add a schema field.
- Print deterministic selected, pending, and skipped counts. Dry-run renders per-drawer previews and aggregate totals for `pending` only, states that completed drawers were skipped, and keeps the current `dry run -- nothing stored` marker. When no pending drawers remain, print a bounded successful no-op and omit backup/upsert work.
- In live mode with pending drawers, reuse `create_backup()` before the first upsert and pass the palace-local KG path used by the backup CLI for an explicit palace. Use the existing managed manual backup/retention path. A backup failure exits 1 with zero upserts.
- Build one shell-safe recovery command from the resolved palace and returned archive: `mempalace-code --palace <palace> restore <archive> --force`. Print the archive and command immediately after backup completion so a later partial failure still exposes recovery. Reuse the same command in mutation or post-state failure diagnostics.
- Retain sequential per-drawer upserts and write the existing `compression_ratio` and `original_tokens` metadata in the same call as compressed content. This makes each completed drawer independently recognizable after partial execution. On retry, load current storage state again and skip those IDs regardless of row order.
- After all intended upserts, fetch the exact pending IDs with documents and metadata. Require the same ID set, intended compressed bytes, and intended compression metadata before printing `Stored`/verified-success output. A missing or divergent row exits 1 and points to the already-created restore command.
- Extend `tests/test_cli.py` beside `TestCompressTokenAccounting`. Use one bounded fake store with configurable row order, upsert failure, read-back mismatch, and call tracing. Prove unknown-wing and backup failures precede upsert, dry-run performs neither backup nor upsert, mixed selection sends only pending rows to Dialect, immediate retry creates no backup, and partial/reordered retry never reprocesses completed bytes.
- Add one installed-capable subprocess test to `tests/test_cli_golden_scenarios.py`. Mine a disposable project, run live compression, record drawer and backup bytes, rerun identically, and assert unchanged bytes plus skipped output and no new archive. Add an uncompressed drawer to the same wing for mixed-state proof, verify the old compressed bytes remain stable, search remains usable, the first backup exists, recovery output names the real archive, and an unknown wing exits 2 without changing palace/backups.
- Reuse the existing token-accounting assertions for output totals and the existing backup suite/full regression for archive retention. Do not duplicate backup format, restore, taxonomy suggestion, or installed-wheel implementation tests in the new focused class.
- Command context basis: `pyproject.toml` declares Python 3.11+, pytest under `tests`, and the `mempalace-code` console entry point; `tests/test_cli_golden_scenarios.py` already switches to the absolute installed executable; `scripts/gate_inventory.py` owns VER-2 and REG-1 byte-for-byte.
- `docs/quality/incident-class-registry.yaml` is absent in this checkout, so this runtime fix has no registry-matched `incident_proof` block.
- PLAN did not run tests, builds, verification wrappers, installed smokes, or generated-plan validation.
