---
slug: CHROMA-MIGRATION-ADVISORY-SUNSET
status: completed
authority: non_authoritative
goal: "Remove ChromaDB from the release while retaining one safe retirement and pre-upgrade recovery path."
risk: high
risk_note: "This removes a published optional dependency and migration implementation while changing release-critical CI, installed-package behavior, and legacy-palace recovery guidance."
files:
  - path: pyproject.toml
    change: "Remove the chroma-migration and deprecated chroma extras plus obsolete migration-only Pyright exclusions."
  - path: uv.lock
    change: "Regenerate the lock so ChromaDB, its migration-only transitive graph, and both retired extras are absent without changing unrelated dependency selections."
  - path: mempalace_code/storage.py
    change: "Keep Chroma-only marker detection and Lance precedence, replace install-current-bridge guidance with one advisory retirement message and isolated 1.13.4 recovery command, and remove the obsolete ChromaStore export and migration-only parameters/constants."
  - path: mempalace_code/cli.py
    change: "Keep migrate-storage as a compatibility tombstone whose help and permissive legacy argument shape route stale or incomplete calls to the retirement message without filesystem access."
  - path: mempalace_code/cli_commands/maintenance.py
    change: "Replace migration dispatch with a deterministic nonzero retirement response shared with storage detection; ignore accepted legacy arguments and perform no reads or writes."
  - path: mempalace_code/config.py
    change: "Remove the migration-only Chroma collection-name configuration surface and generated default entry."
  - path: mempalace_code/reader.py
    change: "Remove ChromaStore from the current DrawerStore examples."
  - path: mempalace_code/layers.py
    change: "Describe the current palace store as LanceDB-only."
  - path: mempalace_code/updater.py
    change: "Stop inferring the removed chroma extra from an ambient chromadb installation so update commands remain installable after retirement."
  - path: mempalace_code/_chroma_store.py
    change: "Delete the packaged ChromaDB adapter."
  - path: mempalace_code/migrate.py
    change: "Delete the packaged ChromaDB-to-LanceDB migration implementation."
  - path: mempalace_code/legacy_optional/chroma.py
    change: "Delete the optional Chroma import gateway and install hint."
  - path: mempalace_code/legacy_optional/__init__.py
    change: "Delete the now-empty migration-only package marker."
  - path: .github/workflows/ci.yml
    change: "Remove the Chroma migration job and its release-required dependencies while preserving the Python 3.11-3.14 default-install matrix and every unrelated release-critical job."
  - path: scripts/migrate_storage_smoke.py
    change: "Delete the obsolete Chroma-dependent migration smoke owner."
  - path: scripts/release_admission_checks.py
    change: "Remove the retired Chroma migration job from the canonical release-critical job set."
  - path: scripts/release_readiness_gate.py
    change: "Remove Chroma extra installation/migration probes and replace the installed migrate-storage scenario with exact tombstone, no-mutation, and package-dependency evidence."
  - path: scripts/quality_scorecard.py
    change: "Remove the deleted migration smoke from the known integration-suite inventory."
  - path: scripts/architecture_guard.py
    change: "Remove the retired legacy_optional layer and deleted migration owners from the production import topology."
  - path: scripts/docs_drift_guard.py
    change: "Reject current Chroma extras, current-bridge install guidance, and duplicate recovery text while allowing bounded historical/upstream evidence."
  - path: scripts/upstream_comparison_guard.py
    change: "Change the fork-current storage capability from migration-bridge-only to fully retired Chroma support."
  - path: tests/test_cli.py
    change: "Replace migration dispatch tests with retirement help/output, missing or malformed input, repeated invocation, legacy-option, and zero-mutation coverage."
  - path: tests/test_storage_lance.py
    change: "Update Chroma-only and mixed-palace tests for the new recovery message, absent public ChromaStore symbol, unchanged Lance precedence, and no mutation."
  - path: tests/test_chroma_import_errors.py
    change: "Delete superseded import-gateway and ChromaStore-stub tests after consolidating retirement coverage under CLI and storage owners."
  - path: tests/test_migrate.py
    change: "Delete tests for the removed migration implementation."
  - path: tests/test_migrate_storage_smoke.py
    change: "Delete tests for the removed migration smoke."
  - path: tests/test_config.py
    change: "Remove expectations for the retired Chroma collection-name configuration."
  - path: tests/test_version_check.py
    change: "Remove the obsolete Chroma collection-name key from configuration fixtures."
  - path: tests/test_updater.py
    change: "Prove that ambient chromadb is ignored and cannot reappear in a generated update package spec."
  - path: tests/test_pyright_optional_dependencies.py
    change: "Assert that default and optional package metadata contain no Chroma bridge files, extras, or dependency exclusions."
  - path: tests/test_dependency_upgrade_gate.py
    change: "Replace current Chroma-extra fixtures and hold-policy expectations with the remaining optional-extra matrix and explicit no-chromadb audit assertions."
  - path: tests/test_release_readiness_gate.py
    change: "Update release-gate fixtures for removed Chroma extras/job/smoke and assert the retained tombstone plus installed-artifact no-chromadb evidence."
  - path: tests/test_release_install_metadata_smoke.py
    change: "Update expected installed extras to exclude chroma and chroma-migration while retaining the blocked-import runtime probe."
  - path: tests/test_quality_scorecard.py
    change: "Remove the deleted migration smoke from expected known-suite inventory."
  - path: tests/test_architecture_guard.py
    change: "Remove legacy_optional-specific topology fixtures and retain the storage/mining-to-CLI/MCP boundary checks."
  - path: tests/test_docs_drift_guard.py
    change: "Update documentation fixtures and add rejection coverage for current Chroma extras or current-release migration guidance."
  - path: tests/test_upstream_comparison_guard.py
    change: "Update current fork capability assertions for retired Chroma support while preserving upstream and historical evidence."
  - path: docs/dependency-upgrade-reports/v1.13.5-release.json
    change: "Regenerate current-hash public dependency evidence for default, dev, and every remaining optional extra with no chromadb finding or resolver row."
  - path: docs/quality/scorecard.json
    change: "Regenerate the machine-readable scorecard after deleting migration-only suites."
  - path: docs/quality/scorecard.md
    change: "Regenerate the human-readable scorecard from the same source."
  - path: docs/quality/upstream-comparison.json
    change: "Regenerate fork-current storage capabilities without the Chroma migration bridge claim."
  - path: AGENTS.md
    change: "Replace current migration-extra and bridge policy with the supported retirement and isolated 1.13.4 recovery boundary."
  - path: CONTRIBUTING.md
    change: "Remove Chroma dependency-maintenance instructions and state that new releases carry no Chroma extra."
  - path: README.md
    change: "Remove Chroma install extras and current bridge examples; retain one retirement recovery command and historical upstream comparison."
  - path: mempalace_code/README.md
    change: "Update package architecture from an active one-way bridge to fully LanceDB-only current releases."
  - path: docs/BACKUP_RESTORE.md
    change: "Replace the obsolete migration smoke runbook with a fail-closed legacy-palace recovery section requiring a backup and the isolated 1.13.4 command."
  - path: docs/DEPENDENCY_UPGRADE_GATE.md
    change: "Remove the Chroma 1.x hold/current-extra policy and update examples to the remaining optional-extra surfaces."
  - path: docs/UPDATES.md
    change: "Remove Chroma extras from preserved update selections and document the pre-upgrade recovery boundary."
  - path: docs/WHY_THIS_FORK.md
    change: "Describe ChromaDB as historical and retired from current packages, with the bounded last-bridge recovery route."
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Update current fork storage capability to LanceDB-only with no packaged Chroma bridge while retaining upstream/historical facts."
  - path: docs/release-admission-rulesets.md
    change: "Remove the retired Chroma migration CI job from the documented release-required set."
  - path: CHANGELOG.md
    change: "Correct the current v1.13.5 entry to describe complete bridge retirement while preserving older historical release entries."
acceptance:
  - id: AC-1
    when: "Fresh default, dev, and every remaining optional-extra resolver is audited and the v1.13.5 report is verified against the final pyproject.toml and uv.lock hashes."
    then: "Every resolver and advisory row succeeds, no resolved package is chromadb, and current-hash report verification exits zero."
  - id: AC-2
    when: "The final wheel and sdist are inspected and exercised through package import, CLI, MCP, watcher, backup, and representative LanceDB paths with chromadb imports blocked."
    then: "The artifacts contain no removed bridge modules or chromadb dependency, and all ordinary installed behavior remains successful."
  - id: AC-3
    when: "mempalace-code migrate-storage or automatic Chroma-only palace detection is invoked with complete, missing, malformed, repeated, stale legacy-option, or mixed Lance/Chroma inputs."
    then: "Chroma paths exit nonzero before mutation with one retirement/advisory message, a backup requirement, and exactly one isolated recovery command using mempalace-code[chroma]==1.13.4; mixed valid Lance palaces continue to open as LanceDB without marker mutation."
  - id: AC-4
    when: "Repository, package metadata, built artifacts, CI topology, quality inventory, and current public documentation are inspected after the sunset."
    then: "Chroma extras, lock entries, packaged bridge code, smoke owners, public exports, current install suggestions, duplicate recovery guidance, and generated residue are absent; the current changelog is accurate while older changelog entries, archived reports, and upstream evidence remain historical."
  - id: AC-5
    when: "Focused regressions, fresh Python 3.11-3.14 resolution, the configured offline suite, Ruff, both Pyright contours, architecture/docs/scorecard/public-safety/Gitleaks gates, artifact qualification, and direct exact-wheel installed paths run for the final candidate."
    then: "Every required check exits zero; recovery for a failed implementation remains restoring only the reviewed task files, with no palace, backup, or archive deletion."
out_of_scope:
  - "Parsing ChromaDB files directly or adding a replacement migration library, service, store, parser, waiver, or advisory suppression."
  - "Automatically converting, deleting, modifying, or cleaning any user palace, Chroma marker, backup, archive, or destination."
  - "Rewriting historical changelog entries, archived dependency reports, benchmark evidence, or upstream facts that accurately describe past releases."
  - "Changing LanceDB schema, retrieval, embeddings, MCP contracts, watcher behavior, backup format, or unrelated dependency versions."
  - "Backlog bookkeeping, version bumping, commits, tags, publication, deployment, or release finalization."
contract_policy:
  flow: full_spdd
  reason: "Standard release-security and data-migration retirement task spanning package metadata, fail-closed recovery behavior, CI admission, and installed artifacts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Current release dependency and resolver surfaces must contain no chromadb package or Chroma extra."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Ordinary source and installed-artifact LanceDB behavior must remain intact with the retired bridge absent."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2, AC-5]
    - id: REQ-3
      statement: "The retained CLI and Chroma-only detection owners must fail before mutation with one deterministic retirement and 1.13.4 recovery contract."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "All superseded Chroma migration implementation, packaging, CI, smoke, export, and current-documentation surfaces must be removed without rewriting historical evidence."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The final candidate must satisfy focused, configured, hosted-version, security, artifact, and exact-wheel qualification contours."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Chroma retirement boundary"
      kind: api
      paths: ["mempalace_code/storage.py"]
      expected_behavior: "Chroma-only detection raises the stable retirement error before mutation; valid LanceDB state has precedence over a stale Chroma marker."
    - name: "migrate-storage tombstone"
      kind: cli
      paths: ["mempalace_code/cli.py", "mempalace_code/cli_commands/maintenance.py"]
      expected_behavior: "Legacy invocations terminate deterministically with the shared recovery contract and never import ChromaDB or touch source/destination paths."
    - name: "Package dependency contract"
      kind: internal
      paths: ["pyproject.toml", "uv.lock"]
      expected_behavior: "The release exposes only remaining supported extras and resolves no chromadb package."
    - name: "Release qualification topology"
      kind: internal
      paths: [".github/workflows/ci.yml", "scripts/release_admission_checks.py", "scripts/release_readiness_gate.py"]
      expected_behavior: "Release admission no longer requires a Chroma job and instead proves absence plus retained tombstone and Lance behavior."
    - name: "Current support documentation"
      kind: internal
      paths: ["AGENTS.md", "README.md", "docs/BACKUP_RESTORE.md", "docs/DEPENDENCY_UPGRADE_GATE.md"]
      expected_behavior: "Current docs offer one safe pre-upgrade recovery route and never suggest a Chroma extra from the current release."
  invariants:
    - id: INV-1
      statement: "No command introduced or changed by this task deletes or modifies a palace, Chroma marker, backup, archive, or migration destination."
      applies_to: ["mempalace_code/storage.py", "mempalace_code/cli.py", "mempalace_code/cli_commands/maintenance.py"]
    - id: INV-2
      statement: "A valid LanceDB store remains authoritative when a stale chroma.sqlite3 marker is also present."
      applies_to: ["mempalace_code/storage.py", "tests/test_storage_lance.py"]
    - id: INV-3
      statement: "Core imports, CLI, MCP, watcher, backup, and LanceDB behavior remain free of Chroma imports and behavior changes."
      applies_to: ["pyproject.toml", "mempalace_code/storage.py", "scripts/release_readiness_gate.py"]
    - id: INV-4
      statement: "Historical changelog, archived reports, benchmark evidence, and upstream descriptions remain historical evidence rather than current support claims."
      applies_to: ["README.md", "docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-5
      statement: "The recovery text names a required backup and exactly one isolated command pinned to mempalace-code[chroma]==1.13.4; it never recommends a current Chroma extra."
      applies_to: ["mempalace_code/storage.py", "docs/BACKUP_RESTORE.md", "README.md"]
  risks:
    - id: RISK-1
      risk: "Removing the bridge without a usable tombstone could strand a user on a legacy palace or invite an unsafe current dependency install."
      mitigation: "Keep the existing CLI and detection owners, centralize one message, require backup, and pin the isolated command to the last public bridge release."
    - id: RISK-2
      risk: "Legacy or malformed calls could reach filesystem setup before the retirement response."
      mitigation: "Make the CLI tombstone independent of path validity and assert missing, arbitrary, repeated, and legacy-option inputs leave all paths absent or byte-identical."
    - id: RISK-3
      risk: "Removing the dedicated CI job could weaken release evidence."
      mitigation: "Retain the four-version default matrix and move absence/tombstone assertions into existing package, installed-golden, dependency-audit, and focused regression owners."
    - id: RISK-4
      risk: "The lock or generated report could retain transitive Chroma residue or become stale after metadata edits."
      mitigation: "Regenerate both from final pyproject.toml, run fresh all-extra audit resolution, and verify report hashes plus installed artifact metadata."
    - id: RISK-5
      risk: "Broad text removal could erase valid historical or upstream evidence."
      mitigation: "Scope drift guards to current-support surfaces and preserve explicitly historical changelog, archived report, benchmark, and upstream records."
  verification:
    - id: VER-1
      owner: provider
      command: "python scripts/dependency_upgrade_gate.py current-audit --out-dir dependency-audit-output"
      proves: "Fresh default, dev, and every remaining optional-extra resolver is advisory-clean and contains no chromadb package."
      acceptance_ids: [AC-1]
    - id: VER-2
      owner: provider
      command: "python scripts/dependency_upgrade_gate.py verify-report docs/dependency-upgrade-reports/v1.13.5-release.json --root ."
      proves: "The regenerated successful report matches the final pyproject.toml and uv.lock hashes."
      acceptance_ids: [AC-1]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json"
      proves: "Default installers expose only supported extras and ordinary package, CLI, and LanceDB paths avoid chromadb imports."
      acceptance_ids: [AC-2, AC-4]
    - id: VER-4
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
      proves: "Hosted Python 3.11-3.14 results, built artifacts, direct exact-wheel scenarios, remaining release-critical jobs, and the tombstone behavior qualify the exact candidate."
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
    - id: VER-5
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured complete offline suite preserves CLI, MCP, watcher, backup, LanceDB, packaging, docs, and release-gate behavior."
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The retained and removed Python surfaces satisfy the configured lint contract."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The final Python tree satisfies the configured formatting contract."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-8
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The default typecheck succeeds without migration-only exclusions or chromadb installed."
      acceptance_ids: [AC-2, AC-4, AC-5]
    - id: VER-9
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict typecheck contour remains green."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-10
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "Generated scorecards match the removal of obsolete migration suites and retain every other quality surface."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-11
      owner: configured_runner
      command: "python scripts/architecture_guard.py --root ."
      proves: "The production import graph contains no deleted migration owner or dead legacy_optional layer and preserves active boundaries."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-12
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "Current docs, generated evidence, and planned files contain no private or orchestration residue."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-13
      owner: configured_runner
      command: "python scripts/gitleaks_scan.py changed-range --base-ref BASE --head-ref HEAD"
      proves: "The reviewed change range contains no secret material."
      acceptance_ids: [AC-5]
    - id: VER-14
      owner: provider
      command: "python scripts/dependency_upgrade_gate.py ci-check --base-ref origin/main"
      proves: "The release dependency gate accepts exactly one successful current-hash report and retains fail-closed evidence admission."
      acceptance_ids: [AC-1, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_cli.py::TestMigrateStorageCommand tests/test_storage_lance.py::TestDetectBackend tests/test_storage_lance.py::TestOpenStoreFactory -q"
        proves: "The CLI tombstone, Chroma-only detection, repeated and malformed calls, mixed Lance precedence, and no-mutation boundary behave deterministically."
        acceptance_ids: [AC-3]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_excludes_retired_chroma_extras tests/test_release_readiness_gate.py::test_installed_optional_extras_exclude_retired_chroma -q"
        proves: "Current audit and release qualification enumerate only remaining extras and reject Chroma residue."
        acceptance_ids: [AC-1, AC-2, AC-4]
      - id: REG-3
        owner: provider
        command: "python -m pytest tests/test_docs_drift_guard.py::test_current_chroma_support_and_duplicate_recovery_are_rejected tests/test_upstream_comparison_guard.py -q"
        proves: "Current support guidance cannot reintroduce a Chroma extra or duplicate recovery path while historical/upstream evidence stays valid."
        acceptance_ids: [AC-4]
---

## Design Notes

- Behavioral owners: `mempalace_code/cli.py` plus `mempalace_code/cli_commands/maintenance.py` own the public command; `mempalace_code/storage.py` owns Chroma-only detection and the single recovery message. Extend these owners and delete the bridge modules. A replacement parser, adapter, package, or service adds complexity and is forbidden by scope.
- Use one exact recovery command everywhere: `uvx --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify`. State that the source must be backed up before upgrade and that 1.13.4 is the last public bridge release. Do not mention an installable Chroma extra for the current version.
- Preserve the `migrate-storage` command name for stale automation. Make source and destination positionals optional at parse time and continue accepting its previous flags so missing, arbitrary, or old invocations reach the same tombstone. The handler must inspect none of their values, import no bridge module, print one stderr message, and exit nonzero.
- Keep detection order `lance/` before `chroma.sqlite3`. A Chroma-only marker raises the shared retirement error before directory creation or embedding initialization. A mixed directory opens the valid Lance store and leaves the marker untouched.
- Remove `mempalace_code/_chroma_store.py`, `mempalace_code/migrate.py`, `mempalace_code/legacy_optional/`, their direct tests/smoke, both extras, and the resulting lock graph. Remove the public `storage.ChromaStore` stub and migration-only configuration/argument surfaces rather than retaining dead compatibility owners.
- Remove `chroma-migration-bridge` from both CI and `RELEASE_CRITICAL_CI_JOBS`; preserve all other jobs and the exact Python 3.11-3.14 matrix. Existing package and installed-golden owners absorb negative dependency, tombstone, and Lance regression evidence.
- Regenerate `uv.lock`, the v1.13.5 dependency report, scorecards, and current upstream-comparison data only after source/metadata changes settle. The report must enumerate default, dev, spellcheck, treesitter, and watch as declared at implementation time; it must contain no Chroma extra or chromadb package row.
- Current-support docs and the current v1.13.5 changelog entry contain the retirement state and one recovery command per user-facing surface. Older changelog entries, dependency reports, benchmark artifacts, `NOTICE`, and bounded upstream evidence remain unchanged when they accurately describe history or upstream.
- Command context basis: repository-root Python commands and the exact lint, format, pytest, Pyright, scorecard, architecture, public-safety, and Gitleaks contours come from `pyproject.toml`, `pyrightconfig.strict.json`, `.claude/skills/verify/INSTRUCTIONS.md`, and the current release plans. The exact-candidate readiness command is the configured runner owner for hosted matrix and direct-wheel evidence.
- Cheapest decisive falsifier: after metadata/lock regeneration, any `chromadb` row in the fresh current audit, wheel metadata, sdist/wheel members, or installed optional-extra inventory rejects the implementation before release qualification.
