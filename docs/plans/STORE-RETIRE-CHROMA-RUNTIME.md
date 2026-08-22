---
slug: STORE-RETIRE-CHROMA-RUNTIME
status: completed
authority: non_authoritative
goal: "Retire ChromaDB runtime storage while preserving a one-way ChromaDB-to-LanceDB migration bridge."
risk: high
risk_note: "This is a breaking storage/API retirement across runtime selection, optional dependencies, CI, release gates, and migration safety."
contract_policy:
  flow: full_spdd
  reason: "Strict storage/security migration task with a breaking runtime boundary, package metadata changes, and data-preserving migration requirements."
  sync_gate: required
  verification_path: automated
files:
  - path: mempalace_code/storage.py
    change: "Remove general ChromaDB runtime selection, remove the ChromaStore compatibility re-export, keep LanceDB default/explicit behavior, detect Chroma-only palaces, and raise one stable migration-required error with the migrate-storage command, backup behavior, and migration extra."
  - path: mempalace_code/_chroma_store.py
    change: "Narrow the ChromaDB wrapper to a private migration adapter and remove runtime-backend wording or runtime-only helper behavior that is no longer supported."
  - path: mempalace_code/legacy_optional/chroma.py
    change: "Redefine the optional Chroma loader as a migration-only dependency gateway with the same precise missing-extra hint used by migrate-storage."
  - path: mempalace_code/legacy_optional/__init__.py
    change: "Update package documentation from optional backend compatibility to migration-only legacy helpers."
  - path: mempalace_code/migrate.py
    change: "Route all Chroma-specific imports through the migration boundary, preserve source backup/verification behavior, and report missing migration dependencies with the migration-extra install hint."
  - path: mempalace_code/cli.py
    change: "Update migrate-storage help text to describe the migration-only bridge and preferred migration extra."
  - path: mempalace_code/config.py
    change: "Reword the legacy collection-name property so it is described as migrate-storage compatibility rather than active runtime backend configuration."
  - path: pyproject.toml
    change: "Rename or redefine the optional Chroma dependency as migration-only, keep a deprecated compatibility alias if packaging supports it, remove Chroma from ordinary typecheck requirements, and exclude Chroma-only bridge files from default Pyright."
  - path: uv.lock
    change: "Refresh package metadata after optional-extra changes without changing unrelated runtime dependency ranges."
  - path: .github/workflows/ci.yml
    change: "Remove the full-suite chroma-compat runtime job, add a smaller migration-only installed-artifact bridge job while supported, and stop installing ChromaDB for unrelated typecheck."
  - path: scripts/migrate_storage_smoke.py
    change: "Update the smoke to use the migration-only extra wording, continue disposable fixture generation, verify source preservation, counts, backup creation, searchability, and non-empty destination refusal."
  - path: scripts/docs_drift_guard.py
    change: "Teach optional-extra documentation checks to handle migration-only Chroma wording and hyphenated extras, and fail on public docs that advertise Chroma as a runtime backend."
  - path: scripts/release_install_metadata_smoke.py
    change: "Add installed-artifact ordinary-runtime probes that block accidental chromadb imports during package import, CLI help, and LanceDB-only runtime operations."
  - path: tests/test_storage_lance.py
    change: "Replace Chroma runtime detection expectations with Chroma-only migration-required failure, mixed LanceDB precedence, explicit backend rejection, and unchanged LanceDB default/explicit behavior."
  - path: tests/test_storage.py
    change: "Keep representative LanceDB add/search/delete/health coverage aligned with the unchanged default runtime behavior."
  - path: tests/test_chroma_import_errors.py
    change: "Replace absent-extra runtime compatibility tests with stable runtime-retired errors for storage.ChromaStore and open_store(..., backend='chroma') that do not import chromadb."
  - path: tests/test_chroma_compat.py
    change: "Remove runtime ChromaStore compatibility coverage that no longer represents supported product behavior."
  - path: tests/test_migrate.py
    change: "Keep Chroma-to-Lance migration coverage focused on the bridge, including happy path, backup creation, verification failure, missing dependency hint, and source preservation."
  - path: tests/test_migrate_storage_smoke.py
    change: "Update smoke tests for migration-only extra wording, backup/source-preservation evidence, one-row boundary, missing dependency gate, and destination refusal."
  - path: tests/test_cli.py
    change: "Update migrate-storage CLI help/dispatch assertions and add user-facing legacy-palace failure coverage through ordinary CLI paths where appropriate."
  - path: tests/test_pyright_optional_dependencies.py
    change: "Expand default-install and source-boundary checks so normal runtime modules never top-level import chromadb and Chroma-only bridge files stay outside ordinary Pyright."
  - path: tests/test_docs_drift_guard.py
    change: "Update optional-extra fixtures and add regressions that fail when README, CLAUDE, release/update docs, or verify guidance describe ChromaDB as a runtime backend."
  - path: tests/test_dependency_upgrade_gate.py
    change: "Update ChromaDB advisory-boundary fixtures to the migration-only extra name and compatibility alias while preserving the GHSA-f4j7-r4q5-qw2c hold."
  - path: tests/test_release_install_metadata_smoke.py
    change: "Add mocked installed-artifact probes proving ordinary import/help/Lance-only paths do not load chromadb."
  - path: tests/test_installed_artifact_behavior.py
    change: "Cover neutral-directory installed-artifact behavior for the new no-chromadb ordinary-runtime probe."
  - path: README.md
    change: "Update install extras, fork comparison, and CLI command text so ChromaDB is named only as a migration input or historical upstream/default evidence."
  - path: mempalace_code/README.md
    change: "Update package architecture wording so the runtime palace is LanceDB-only and ChromaDB appears only as the migration bridge input."
  - path: CLAUDE.md
    change: "Update public project guidance from deprecated optional Chroma runtime backend to migration-only extra and bridge policy."
  - path: docs/BACKUP_RESTORE.md
    change: "Update migrate-storage docs and smoke instructions to the migration-only extra, source backup behavior, source preservation, and runtime-retirement failure guidance."
  - path: docs/DEPENDENCY_UPGRADE_GATE.md
    change: "Update ChromaDB hold policy so the capped dependency is described as isolated migration input rather than an optional runtime backend."
  - path: docs/UPDATES.md
    change: "Update retained-extra wording so updates preserve the migration-only Chroma dependency only when present, without advertising runtime backend support."
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Update current fork capability tags/text from optional ChromaDB backend support to LanceDB-only runtime plus Chroma-to-Lance migration bridge, preserving historical upstream evidence."
  - path: docs/quality/upstream-comparison.json
    change: "Regenerate current fork capability tags to remove ChromaDB optional-runtime support and add migration-bridge-only evidence."
  - path: .claude/skills/verify/INSTRUCTIONS.md
    change: "Update dependency-change guidance so ChromaDB checks refer to the migration-only extra and focused bridge tests, not runtime compatibility."
  - path: docs/quality/scorecard.json
    change: "Regenerate quality scorecard data after removing runtime compatibility tests and adding migration/runtime-boundary coverage."
  - path: docs/quality/scorecard.md
    change: "Regenerate the human-readable scorecard alongside scorecard.json."
acceptance:
  - id: AC-1
    when: "Default and explicit LanceDB palaces are exercised through representative storage, CLI, MCP, backup, and search flows."
    then: "They keep the same persisted rows, query results, metadata counts, health output, and read-only behavior as before the Chroma runtime retirement."
  - id: AC-2
    when: "A normal wheel or sdist install is probed from a neutral directory while chromadb imports are blocked, covering package import, CLI help, and LanceDB-only runtime operations."
    then: "The ordinary runtime probe succeeds and reports no attempted chromadb import."
  - id: AC-3
    when: "open_store(..., backend='chroma') is called, or a directory containing only chroma.sqlite3 is opened through auto-detection."
    then: "The call fails before mutation with a stable actionable message naming mempalace-code migrate-storage SRC DST --verify, default backup behavior, and the migration extra."
  - id: AC-4
    when: "mempalace-code migrate-storage SRC DST --verify runs against a disposable legacy ChromaDB fixture with the migration extra installed."
    then: "It is the only supported bridge, creates the existing backup, migrates to LanceDB, verifies counts and searchable marker content, and leaves the source row count/content unchanged."
  - id: AC-5
    when: "migrate-storage or the disposable migration smoke runs without the Chroma migration dependency installed."
    then: "It exits nonzero before fixture or destination mutation and prints the precise migration-extra install hint."
  - id: AC-6
    when: "A palace directory contains a valid LanceDB store and a stale or empty chroma.sqlite3 marker."
    then: "open_store() selects LanceDB without warning, chromadb import, or Chroma marker mutation."
  - id: AC-7
    when: "The focused Chroma retirement and migration tests are run."
    then: "They cover Chroma-only detection, mixed-directory precedence, explicit backend rejection, missing migration dependency, successful installed-artifact migration, verification failure, backup creation, and source preservation."
  - id: AC-8
    when: ".github/workflows/ci.yml is inspected after implementation."
    then: "The full-suite chroma-compat runtime job and runtime compatibility tests are absent, and a smaller migration-only job remains while the bridge is supported."
  - id: AC-9
    when: "Dependency, security, docs, quality, and release guards are run or inspected."
    then: "They describe ChromaDB only as isolated migration input, and core plus unrelated optional installs do not resolve chromadb."
  - id: AC-10
    when: "Post-landing repository verification is inspected."
    then: "Its report includes passing complete non-network pytest, Ruff, format, Pyright basic/strict, architecture guard, docs drift guard, build/Twine checks, package-content gates, neutral-directory install smoke, and focused migration smoke evidence."
out_of_scope:
  - "Deleting local, user, or historical ChromaDB palaces, backups, archives, benchmark files, or empty marker files."
  - "Removing the one-way ChromaDB-to-LanceDB migration bridge in this change."
  - "Reimplementing ChromaDB persistence parsing through direct SQLite, HNSW, or backup reconstruction."
  - "Changing LanceDB schema, embedding model, retrieval ranking, mining, backup archive format, or updater mutation gates beyond optional-extra wording."
  - "Rewriting historical benchmark results or upstream issue evidence where the text is clearly historical."
  - "Publishing, tagging, version-bumping, changelog finalization, backlog bookkeeping, or release announcement work."
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "LanceDB remains the only normal runtime storage backend, with default and explicit Lance behavior unchanged."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Ordinary runtime imports and installed-artifact smoke paths must not import or require chromadb."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2, AC-9]
    - id: REQ-3
      statement: "Explicit Chroma backend requests and Chroma-only palace auto-detection must fail closed with the stable migration command and backup/extra guidance."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3, AC-5, AC-7]
    - id: REQ-4
      statement: "migrate-storage remains the sole supported one-way ChromaDB-to-LanceDB bridge and must preserve backup, verification, searchability, and source preservation evidence."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4, AC-7]
    - id: REQ-5
      statement: "Mixed directories with a valid LanceDB store and stale Chroma marker must prefer LanceDB silently and without mutation."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6, AC-7]
    - id: REQ-6
      statement: "CI and runtime compatibility tests must stop treating ChromaDB as a runtime backend, while retaining focused installed-artifact migration coverage."
      source: "current backlog contract AC-8"
      acceptance_ids: [AC-8, AC-10]
    - id: REQ-7
      statement: "Dependency, docs, quality, and release surfaces must describe ChromaDB only as migration input and keep core/unrelated optional installs free of chromadb."
      source: "current backlog contract AC-9"
      acceptance_ids: [AC-2, AC-9, AC-10]
    - id: REQ-8
      statement: "The post-landing runner gate must prove the full non-network, style, type, architecture, docs, build, package, install-smoke, and migration-smoke set."
      source: "current backlog contract AC-10"
      acceptance_ids: [AC-10]
  surfaces:
    - name: "Runtime storage factory"
      kind: "api"
      paths: ["mempalace_code/storage.py", "tests/test_storage_lance.py", "tests/test_storage.py"]
      expected_behavior: "LanceDB remains the only open_store runtime result; explicit chroma and Chroma-only auto-detect fail closed with migration guidance; mixed LanceDB directories keep Lance precedence."
    - name: "Private migration bridge"
      kind: "internal"
      paths: ["mempalace_code/_chroma_store.py", "mempalace_code/legacy_optional/chroma.py", "mempalace_code/legacy_optional/__init__.py", "mempalace_code/migrate.py", "tests/test_migrate.py"]
      expected_behavior: "ChromaDB imports exist only behind migrate-storage and continue to read legacy rows into LanceDB with backup, verify, and source-preservation behavior."
    - name: "CLI migration command"
      kind: "cli"
      paths: ["mempalace_code/cli.py", "tests/test_cli.py", "scripts/migrate_storage_smoke.py", "tests/test_migrate_storage_smoke.py"]
      expected_behavior: "migrate-storage remains the public bridge command and all ordinary CLI paths inherit the runtime-retired failure boundary without loading chromadb."
    - name: "Packaging and dependency metadata"
      kind: "internal"
      paths: ["pyproject.toml", "uv.lock", "tests/test_pyright_optional_dependencies.py", "tests/test_dependency_upgrade_gate.py"]
      expected_behavior: "ChromaDB is optional migration-only metadata, ordinary typecheck/default installs do not resolve it, and advisory bounds stay capped while GHSA-f4j7-r4q5-qw2c applies."
    - name: "CI and release gates"
      kind: "internal"
      paths: [".github/workflows/ci.yml", "scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py", "tests/test_installed_artifact_behavior.py", ".claude/skills/verify/INSTRUCTIONS.md"]
      expected_behavior: "CI removes full runtime compatibility coverage, keeps bridge-only installed migration coverage, and release/install smokes prove normal runtime paths do not import chromadb."
    - name: "Public docs and drift guards"
      kind: "internal"
      paths: ["README.md", "mempalace_code/README.md", "CLAUDE.md", "docs/BACKUP_RESTORE.md", "docs/DEPENDENCY_UPGRADE_GATE.md", "docs/UPDATES.md", "docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json", "scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "Current support wording is LanceDB-only runtime plus migration bridge; historical benchmark/upstream evidence remains but no docs advertise ChromaDB runtime support."
    - name: "Quality artifacts"
      kind: "internal"
      paths: ["docs/quality/scorecard.json", "docs/quality/scorecard.md"]
      expected_behavior: "Committed quality scorecards match the changed test and script shape after retirement."
  invariants:
    - id: INV-1
      statement: "No user data, legacy palace directory, backup archive, benchmark evidence, or empty Chroma marker is deleted by this task."
      applies_to: ["mempalace_code/storage.py", "mempalace_code/migrate.py", "scripts/migrate_storage_smoke.py"]
    - id: INV-2
      statement: "mempalace-code migrate-storage remains one-way ChromaDB source to LanceDB destination and keeps its backup-by-default behavior."
      applies_to: ["mempalace_code/migrate.py", "mempalace_code/cli.py", "scripts/migrate_storage_smoke.py"]
    - id: INV-3
      statement: "LanceDB schema, embedding model, query ranking, backup archive format, mining behavior, and MCP protocol behavior remain unchanged."
      applies_to: ["mempalace_code/storage.py", "mempalace_code/migrate.py", "tests/test_storage.py", "tests/test_storage_lance.py"]
    - id: INV-4
      statement: "Normal CLI, MCP, watcher, mining, status, backup, export, search, and read-only operations must not import chromadb."
      applies_to: ["mempalace_code/storage.py", "tests/test_pyright_optional_dependencies.py", "scripts/release_install_metadata_smoke.py"]
    - id: INV-5
      statement: "Historical benchmark and upstream-comparison evidence may keep historical ChromaDB references when clearly marked as past or upstream evidence."
      applies_to: ["README.md", "docs/UPSTREAM_COMPARISON.md", "docs/UPSTREAM_HARDENING.md", "docs/quality/upstream-comparison.json"]
    - id: INV-6
      statement: "No version bump, changelog finalization, backlog metadata update, tag, publish, or source-finalization command is part of provider implementation."
      applies_to: ["pyproject.toml", "README.md", "CLAUDE.md"]
  risks:
    - id: RISK-1
      risk: "A Chroma-only palace could be opened as writable through auto-detect and expose users to deprecated ChromaDB data-loss/security risk."
      mitigation: "Make _detect_backend classify Chroma-only paths as migration-required and add explicit tests that no destination/source mutation happens on failure."
    - id: RISK-2
      risk: "Removing runtime Chroma imports could accidentally remove the migration bridge."
      mitigation: "Keep Chroma imports inside mempalace_code.migrate and the private legacy_optional gateway, and retain migration unit plus installed-artifact smoke coverage."
    - id: RISK-3
      risk: "A stale chroma.sqlite3 marker in a valid LanceDB palace could block healthy palaces."
      mitigation: "Preserve LanceDB precedence in detection and add a mixed-directory regression that asserts no warning, chromadb import, or marker mutation."
    - id: RISK-4
      risk: "Typecheck or installed-artifact smokes could silently keep chromadb in ordinary runtime environments."
      mitigation: "Remove ChromaDB from unrelated CI installs, exclude only Chroma-only bridge files from default Pyright, and add neutral-directory import-blocker smokes."
    - id: RISK-5
      risk: "Public docs and dependency guards could continue advertising a deprecated runtime backend."
      mitigation: "Update docs drift fixtures and dependency gate tests so current-support text is migration-only and the GHSA ceiling remains tied to bridge input."
    - id: RISK-6
      risk: "Deleting runtime compatibility tests could reduce useful migration evidence."
      mitigation: "Replace runtime ChromaStore tests with migration bridge tests that prove backup creation, verification failure, missing dependency hints, installed smoke, and source preservation."
  verification:
    - id: VER-1
      owner: provider
      command: "python scripts/release_readiness_gate.py --check --json"
      proves: "Building the wheel and sdist, checking them with Twine, inspecting package content, and running the neutral-directory installed-artifact smokes all pass, and each smoke's ordinary-runtime probe imports the package, runs CLI help, and opens a LanceDB store with chromadb imports blocked."
      acceptance_ids: [AC-2, AC-10]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_storage_lance.py::TestDetectBackend tests/test_storage_lance.py::TestOpenStoreFactory -q"
        proves: "Focused storage factory coverage verifies LanceDB default/explicit behavior, Chroma-only fail-closed detection, mixed-directory Lance precedence, and explicit backend rejection."
        acceptance_ids: [AC-1, AC-3, AC-6, AC-7]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_chroma_import_errors.py tests/test_pyright_optional_dependencies.py -q"
        proves: "Runtime-retired import errors and default-install no-chromadb boundaries stay stable without requiring the Chroma migration extra."
        acceptance_ids: [AC-2, AC-3, AC-5, AC-7, AC-9]
      - id: REG-3
        owner: provider
        command: "python -m pytest tests/test_migrate.py tests/test_migrate_storage_smoke.py -q"
        proves: "Focused migration bridge coverage preserves happy path, backup creation, source preservation, verification failure, missing dependency hint, and smoke boundaries."
        acceptance_ids: [AC-4, AC-5, AC-7]
      - id: REG-4
        owner: provider
        command: "python -m pytest tests/test_docs_drift_guard.py tests/test_dependency_upgrade_gate.py -q"
        proves: "Docs/dependency guard fixtures enforce migration-only Chroma wording, optional-extra metadata, and the ChromaDB advisory hold."
        acceptance_ids: [AC-8, AC-9]
      - id: REG-5
        owner: provider
        command: "python -m pytest tests/test_release_install_metadata_smoke.py tests/test_installed_artifact_behavior.py -q"
        proves: "Installed-artifact smoke logic proves ordinary package import, help, and Lance-only runtime probes do not import chromadb from a neutral directory."
        acceptance_ids: [AC-2, AC-9, AC-10]
      - id: REG-6
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The configured complete non-network pytest gate remains green after runtime retirement and migration bridge updates."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10]
      - id: REG-7
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The configured Ruff lint gate remains green for runtime, migration, docs-guard, release-smoke, and test changes."
        acceptance_ids: [AC-10]
      - id: REG-8
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The configured format gate remains green for changed package, tests, and scripts."
        acceptance_ids: [AC-10]
      - id: REG-9
        owner: configured_runner
        command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
        proves: "The configured basic Pyright gate passes without installing ChromaDB for ordinary runtime/typecheck."
        acceptance_ids: [AC-2, AC-9, AC-10]
      - id: REG-10
        owner: configured_runner
        command: "python -m pyright -p pyrightconfig.strict.json"
        proves: "The configured strict Pyright slice remains green and excludes optional Chroma-only bridge modules."
        acceptance_ids: [AC-9, AC-10]
      - id: REG-11
        owner: configured_runner
        command: "python scripts/architecture_guard.py --root ."
        proves: "The configured architecture guard keeps protected storage/mining layers free of static legacy_optional and ChromaDB imports."
        acceptance_ids: [AC-2, AC-9, AC-10]
      - id: REG-12
        owner: configured_runner
        command: "python scripts/docs_drift_guard.py"
        proves: "The configured docs drift guard confirms current public docs describe ChromaDB only as migration input and keep optional-extra docs in sync."
        acceptance_ids: [AC-8, AC-9, AC-10]
---

## Design Notes

- Use one Chroma retirement message for all runtime surfaces. The text should name `mempalace-code migrate-storage SRC DST --verify`, state that the command creates a source backup by default, and name the migration extra. Keep it concise enough for CLI stderr.
- Keep backend detection as a path classifier. A `lance/` directory wins over `chroma.sqlite3`; a Chroma-only directory raises the migration-required error; an empty directory still creates or opens LanceDB.
- Remove `storage.ChromaStore` as a compatibility re-export. A failure stub is acceptable if it produces the same actionable retirement message and does not import `mempalace_code.legacy_optional.chroma` or chromadb.
- Keep Chroma-specific imports behind `mempalace_code.migrate` and the private legacy optional gateway. Normal runtime modules should import `storage.py` without reaching `_chroma_store.py`.
- Treat `_chroma_store.py` as a private migration adapter. It can use ChromaDB APIs to read legacy collections for migration tests and smoke fixtures, but public runtime operations must not instantiate it through `open_store()`.
- Prefer a new `chroma-migration` optional extra for docs and error hints if package metadata supports it. Keep `chroma` as a deprecated alias only if needed for existing users and updater retention.
- Remove the `chroma-compat` full-suite job. The replacement CI proof should install the migration extra only for focused bridge and installed-artifact migration smoke coverage.
- Do not add direct SQLite/HNSW parsing or a second migration implementation. Existing `migrate_chroma_to_lance()` remains the single conversion owner.
- Update docs and guards by separating current support from history. Historical benchmark and upstream issue references may keep ChromaDB wording when they clearly describe measured history or upstream behavior.
- Command context basis: the configured core verification commands are the canonical rows in `scripts/quality_scorecard.py` and `.claude/skills/verify/INSTRUCTIONS.md`. `VER-1` deliberately does not restate them — the regression checks `REG-6` through `REG-12` already own the pytest, Ruff, format, Pyright, architecture-guard, and docs-drift halves of `AC-10`, so `VER-1` covers only the artifact and installed-smoke evidence no other row produces.
- Do not edit backlog metadata or `CHANGELOG.md` in implementation. Task bookkeeping and release-note/changelog decisions are made at finalization.
