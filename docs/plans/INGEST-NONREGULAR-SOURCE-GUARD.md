---
slug: INGEST-NONREGULAR-SOURCE-GUARD
status: completed
authority: non_authoritative
goal: "Reject symlinked and non-regular project or conversation sources by default before ingest mutation."
risk: high
risk_note: "The fix changes the default filesystem trust boundary across direct mine, conversations, mine-all, and watcher while preserving descriptor race protection and stale-store cleanup."
files:
  - path: mempalace_code/source_io.py
    change: "Classify candidates from non-following metadata, report the exact source kind, and make descriptor opens reject source symlinks without weakening non-blocking regular-file validation."
  - path: mempalace_code/mining/scanner.py
    change: "Replace the opt-in valid-symlink path with default regular-source classification, record path plus actual source kind, and return only ordinary regular files."
  - path: mempalace_code/mining/orchestrator.py
    change: "Reconcile the legacy skip_invalid_source_symlinks plumbing with the unconditional scanner contract and retain the existing walked-set stale drawer sweep for rejected sources."
  - path: mempalace_code/convo_miner.py
    change: "Apply the same default non-following source classification to conversation discovery before normalization or store access."
  - path: mempalace_code/watcher.py
    change: "Render generic rejected-source diagnostics with the actual source kind and use the same unconditional mine contract at startup and re-index entry paths."
  - path: tests/test_regular_source_guard.py
    change: "Invert the obsolete valid-symlink contract and cover FIFO, socket, directory, and symlink rejection, exact kind diagnostics, hard timeouts, regular controls, and descriptor race guards."
  - path: tests/test_miner.py
    change: "Replace opt-in symlink expectations with default rejection, duplicate-drawer prevention, regular incremental no-op proof, and stale rejected-source sweep coverage."
  - path: tests/test_convo_miner.py
    change: "Cover default conversation-source symlink rejection while preserving regular conversation discovery."
  - path: tests/test_watcher.py
    change: "Update startup and re-index coverage for generic source-kind diagnostics, unconditional rejection, continued watch-loop entry, and stale drawer cleanup delegation."
  - path: tests/test_cli_golden_scenarios.py
    change: "Extend the existing real CLI guard scenario with a same-extension symlink, exact FIFO/symlink diagnostics, search assertions, incremental re-index cleanup, and mine-all/watcher path evidence usable in source and installed-wheel modes."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable quality scorecard after the accepted test changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable quality scorecard after the accepted test changes."
acceptance:
  - id: AC-1
    when: "the focused regular-source guard exercises FIFO, Unix socket, extension-shaped directory, and source-symlink candidates under hard parent timeouts"
    then: "every candidate is rejected promptly before hashing, content read, embedding, or store mutation, while the regular control is processed"
  - id: AC-2
    when: "a project contains a regular source and a same-extension symlink to that source and is mined through the production entry point"
    then: "storage and search contain only the regular source path and never create a drawer for the symlink path"
  - id: AC-3
    when: "a project containing only accepted regular sources is mined and then mined again unchanged in incremental mode"
    then: "the first mine files the regular source and the second mine remains the existing zero-drawer, no-embedder-warmup no-op"
  - id: AC-4
    when: "direct project mine, conversation mine, mine-all, and watcher startup or re-index receive equivalent regular and rejected candidates"
    then: "all four entry paths apply the same default classification and only ordinary regular sources reach their ingest owner"
  - id: AC-5
    when: "the configured installed-golden gate builds and installs the exact candidate wheel, invokes its absolute mempalace-code executable, and runs the guarded project scenario"
    then: "FIFO and same-extension symlink inputs are rejected and search reports only the regular source from the installed artifact"
  - id: AC-6
    when: "the scanner or watcher reports rejected FIFO, socket, directory, and symlink paths"
    then: "each bounded diagnostic contains the exact path and its actual source kind, and no FIFO is labeled as a symlink"
  - id: AC-7
    when: "a drawer previously stored under a path that is replaced by or now resolves as a rejected source is followed by an unlimited incremental re-index"
    then: "the existing walked-set sweep removes that stale source path from storage and subsequent search cannot return it"
out_of_scope:
  - "Changing embeddings, chunking, search ranking, storage schema, or source_file metadata for accepted regular files."
  - "Adding a second scanner, a new release gate, a new dependency, or another stale-drawer cleanup route."
  - "Changing init marker, entity detection, split-file, backup, restore, or publication workflows beyond effects of the shared descriptor safety invariant."
  - "Editing backlog metadata, staging, committing, tagging, pushing, publishing, or running release qualification during implementation."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release filesystem and ingest-pipeline behavior change with store mutation and installed-artifact evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Project and conversation discovery reject FIFO, socket, directory, and every source symlink before ingest work."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-1, AC-2, AC-4"
      acceptance_ids: [AC-1, AC-2, AC-4]
    - id: REQ-2
      statement: "Accepted regular sources retain current first-mine and incremental no-op behavior."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-3
      statement: "The installed candidate executable proves the source guard through real mine and search commands."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-4
      statement: "Rejected-source diagnostics identify the exact path and actual filesystem source kind."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-5
      statement: "Unlimited incremental re-index removes stored drawers whose source path is no longer accepted."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "Regular-source classification and reads"
      kind: internal
      paths: ["mempalace_code/source_io.py"]
      expected_behavior: "Non-following classification names the candidate kind and descriptor opening rejects symlinks and non-regular nodes without blocking."
    - name: "Project ingestion"
      kind: internal
      paths: ["mempalace_code/mining/scanner.py", "mempalace_code/mining/orchestrator.py"]
      expected_behavior: "All project callers receive only ordinary regular paths, and the existing unlimited incremental sweep deletes previously stored rejected paths."
    - name: "Conversation ingestion"
      kind: internal
      paths: ["mempalace_code/convo_miner.py"]
      expected_behavior: "Conversation discovery applies the same source classification before normalization and mutation."
    - name: "Watcher ingestion diagnostics"
      kind: cli
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "Watcher startup and re-index use the unconditional project guard and print bounded path-plus-kind diagnostics."
  invariants:
    - id: INV-1
      statement: "Actual reads remain descriptor-validated and non-blocking for unsafe filesystem node types and replacement races."
      applies_to: ["mempalace_code/source_io.py"]
    - id: INV-2
      statement: "Accepted regular files keep their original source path, content, hash, chunking, room, and embedding behavior."
      applies_to: ["mempalace_code/mining/scanner.py", "mempalace_code/mining/orchestrator.py", "mempalace_code/convo_miner.py"]
    - id: INV-3
      statement: "Gitignore, force-include, scan-rule, hard-exclude, limit, dry-run, and watcher-loop behavior remain unchanged apart from rejected source classification."
      applies_to: ["mempalace_code/mining/scanner.py", "mempalace_code/mining/orchestrator.py", "mempalace_code/watcher.py"]
    - id: INV-4
      statement: "Stale source deletion stays owned by the orchestrator walked-set sweep and remains disabled for limited scans."
      applies_to: ["mempalace_code/mining/orchestrator.py"]
  risks:
    - id: RISK-1
      risk: "A path can change from a checked regular file to a symlink or FIFO before open."
      mitigation: "Keep non-following discovery checks plus descriptor-level rejection and retain hard-timeout race tests."
    - id: RISK-2
      risk: "Removing opt-in symlink semantics can leave watcher, mine-all, or direct mine on divergent defaults."
      mitigation: "Make the scanner contract unconditional, reconcile the legacy argument at its orchestrator owner, and exercise every entry path."
    - id: RISK-3
      risk: "A rejected path already present in storage can survive if the incremental fast path treats the scan as unchanged."
      mitigation: "Prove rejected stored paths participate in the existing deleted-path decision and walked-set sweep before no-op return."
    - id: RISK-4
      risk: "Generic watcher wording can misclassify non-symlink nodes or flood output."
      mitigation: "Classify from non-following metadata and retain the existing bounded diagnostic preview."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_regular_source_guard.py -q"
      proves: "FIFO, socket, directory, and symlink candidates reject promptly with exact path/kind evidence while regular and descriptor-race controls remain valid."
      acceptance_ids: [AC-1, AC-6]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_miner.py::test_mine_regular_source_noop_and_rejected_source_sweep -q"
      proves: "A same-extension source symlink creates no duplicate, regular incremental no-op remains unchanged, and a formerly stored rejected path is swept."
      acceptance_ids: [AC-2, AC-3, AC-7]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_convo_miner.py::test_scan_convos_rejects_source_symlinks_by_default tests/test_watcher.py::TestWatcherStartupSourceGuard -q"
      proves: "Conversation and watcher paths share the project guard's unconditional classification and watcher diagnostics remain bounded and kind-accurate."
      acceptance_ids: [AC-4, AC-6, AC-7]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_cli_non_regular_source_guard -q"
      proves: "Real source-mode CLI mine, mine-all, watcher, conversation, re-index, and search commands enforce the guard end to end."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-6, AC-7]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/release_readiness_gate.py --installed-golden-wheel \"$WHEEL\" --json"
      proves: "The canonical exact-wheel gate invokes the installed executable from a neutral directory and reruns the guarded mine/search scenario offline."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_regular_source_guard.py tests/test_convo_miner.py::test_scan_convos_rejects_source_symlinks_by_default -q"
        proves: "The shared source-I/O and conversation classification boundary retains hard-timeout, descriptor, diagnostic, and regular-file behavior."
        acceptance_ids: [AC-1, AC-4, AC-6]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_miner.py::test_mine_regular_source_noop_and_rejected_source_sweep tests/test_watcher.py::TestWatcherStartupSourceGuard -q"
        proves: "Project and watcher regressions preserve regular no-op behavior and use the existing stale-source cleanup owner."
        acceptance_ids: [AC-2, AC-3, AC-4, AC-7]
      - id: REG-3
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The canonical non-network suite preserves all accepted ingest, storage, watcher, and CLI behavior after the default contract change."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-6, AC-7]
---

## Design Notes

- Reuse `source_io.py` as the single filesystem authority. Classify with non-following metadata so a symlink is always a symlink even when its target is regular; keep non-blocking open plus descriptor validation for FIFO/socket/race safety, and use the platform's no-follow facility where available with an equivalent identity check fallback.
- Reuse `scan_project()` for direct mine, mine-all, and watcher. The legacy `skip_invalid_source_symlinks` argument must no longer enable a second contract: preserve call compatibility only if removal would break callers, document it as behaviorally redundant, and remove symlink-only branching and prose.
- Reuse the existing diagnostic collection shape at the scanner/watcher boundary, generalized to `path` plus actual `kind`. Preserve the current bounded watcher preview and provide one recovery action: remove or replace the reported node with an ordinary regular file, then rerun the same mine/watch command.
- Reuse the orchestrator's `_any_deleted` check and `existing_hashes - walked_paths` sweep. A source symlink excluded from the new walked set must prevent the incremental early return and be deleted through `delete_by_source_files`; do not add a watcher-side delete or storage migration.
- Update the existing tests that currently assert readable source symlinks are accepted. Regular source paths remain unresolved and unchanged; source symlink paths become rejected even when they point inside the project or share an allowed extension with a regular target.
- Extend `test_cli_non_regular_source_guard` because `scripts/release_readiness_gate.py` already runs the full golden scenario file against the exact installed wheel via `MEMPALACE_TEST_INSTALLED_CLI`. Do not change release scripts or add an install harness.
- Command context basis: `pyproject.toml` declares the repository-root pytest layout and excludes network/slow tests by default; `scripts/gate_inventory.py` owns the exact installed-golden command and the release readiness layer builds one wheel, installs it into a disposable venv, verifies provenance, and invokes the golden suite from a neutral directory.
- No `incident_proof` block applies because this checkout has no `docs/quality/incident-class-registry.yaml` registry.
- PLAN did not execute tests, builds, release gates, verification wrappers, or generated-plan validation.
