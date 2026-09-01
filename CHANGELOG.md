# Changelog

## Unreleased

## v1.13.5 — 2026-09-01

Patch release for ingest source safety, ChromaDB runtime retirement, explicit
update and install opt-ins, alias target containment, and stricter MCP argument
validation.

### Added

- Non-regular/FIFO ingest source guard (`INGEST-NONREGULAR-SOURCE-GUARD`): sources that are not regular files are rejected before any miner state is mutated.

### Changed

- Installed CLI paths now provide consistent project detection, confirmation output, and machine-reconcilable recovery commands.
- ChromaDB runtime and migration bridge retired: current packages contain no Chroma extras. Retired backend or `migrate-storage` invocations stop before mutation and print the isolated 1.13.4 recovery command. Back up the Chroma source before upgrading; default LanceDB users require no action (`CHROMA-MIGRATION-ADVISORY-SUNSET`).
- `mine-all`, `watch <dir>`, and `watch <dir> schedule` now ignore symlinked project and initialization markers, including `.git`. Replace the symlink with a supported in-project marker — a real `.git` directory or a regular marker file — then rerun the original command (`WATCH-ROOT-PROJECT-MARKER-CLASSIFICATION-REUSE`).
- Update and install flows surface safe opt-in choices explicitly to agents and users (`AGENT-INSTALL-UPDATE-OPT-IN-FLOW`).
- Alias target directory is now contained to the explicitly configured path (`INSTALL-ALIAS-TARGET-CONTAINMENT`).
- Agent instruction rules are installed as a delimited managed block, so reinstalls update the block in place instead of appending a second copy.
- Removed the redundant daily/manual GitHub `Upstream drift` workflow that produced recurring notifications; fail-closed live drift checks remain in the pre-tag and tag-publish release paths (`REL-REMOVE-SCHEDULED-UPSTREAM-DRIFT`).
- Synchronized package, lockfile, README badge, Agent Plugin manifest, and generated quality scorecards on version 1.13.5.

### Fixed

- Public version-tag admission now aggregates active rulesets and stops reporting omitted private bypass data as zero actors. Credential-free checks continue to require restricted creation, update, and deletion while bypass identity remains an owner-verified repository setting.
- Explicit `version-check --check-now` now honors the process-level `MEMPALACE_VERSION_CHECK` kill switch: `0` and invalid values fail closed before PyPI access with a concrete recovery command; persisted opt-out remains overridable when the environment override is absent.
- `mempalace-code init` now rejects symlink, FIFO, socket, and directory destinations for `mempalace.yaml` and enabled `entities.json` output before scanning, then writes regular outputs atomically without changing existing file modes or following a destination swapped after validation (`INIT-CONFIG-IRREGULAR-DESTINATION-GUARD`).
- Split outputs now refuse FIFOs, symlinks, hardlinks, and other unsafe synthesized targets without hanging or following them; partial failure retains the source, reports created outputs, and exits nonzero (`UPSTREAM-POST-3-7-1-DRIFT-REVIEW`).
- Forced restore now stages LanceDB replacement and restores the previous palace when later publication fails. If rollback ownership is lost, the prior Lance tree remains in a reported recovery directory instead of being deleted.
- JSONL export/import now preserves `line_start` and `line_end`, so imported mined drawers remain readable through `mempalace-code read` instead of degrading to stale pointers.
- `install-alias` now binds the legacy `mempalace` command to the actually invoked `mempalace-code` launcher, including pipx/uv symlink launchers and the dedicated `mempalace-code-alias` entry point, even when ambient `PATH` contains another same-named executable.
- MCP tool calls reject non-object and undeclared arguments with JSON-RPC `-32602`, and a malformed request no longer ends the session — the next valid request is still served.
- Degraded CLI and onboarding paths handle malformed or absent input safely.
- The upgrade notice now prints a usable command for ordinary pip installs: a version-pinned `-m pip install --upgrade` bound to the interpreter that is running the check, shown only when the install is classified as plain pip. Managed `uv tool`, `pipx`, and bootstrap-venv installs keep their `mempalace-code update` commands and are never told to pip-upgrade behind their manager's back.

## v1.13.4 — 2026-08-12

Hotfix for the final public release-status verification path.

### Fixed

- The six-surface release status gate now preserves the complete shared
  install-smoke subprocess contract, including JSON-RPC stdin for the installed
  Agent Plugin MCP probe and the configured timeout. A CLI-boundary regression
  prevents future adapter drift.

### Changed

- Synchronized package, lockfile, README badge, and Agent Plugin manifest on
  version 1.13.4 after the immutable v1.13.3 publication.

## v1.13.3 — 2026-08-12

Recovery release for the upstream-drift failure that stopped v1.13.2 before
build and publication.

### Fixed

- The canonical pre-tag release preflight now has an explicit live-upstream
  mode. It fails closed before an immutable tag is created when upstream
  `develop` moved or its read-only head lookup cannot be trusted; the default
  preflight remains deterministic and network-free.
- Documentation drift checks now keep the exact live pre-tag command aligned
  across the release guide, release and release-prep skills, and the upstream
  comparison.

### Changed

- Refreshed the evidence-bounded upstream comparison against upstream 3.7.0 at
  commit `b2104238d4491654f17118d12cf876ac5e41a0cf`, including current embedding,
  date-search, provider, source-adapter, logstream, and Codex-plugin claims.
- Synchronized package, lockfile, README badge, Agent Plugins manifest, and
  generated quality scorecards on version 1.13.3.

## v1.13.2 — 2026-08-11

Patch release for portable Agent Plugins packaging and collision-safe release
identity checks.

### Added

- The installed distribution now includes a portable Agent Plugins 1.0 package,
  an agent-oriented skill, vendored offline schemas, and the stable
  `mempalace-code-mcp` launcher. Its portable `mcp.json` defaults to the four-tool
  `minimal` profile; direct MCP registration supports the `kg`, `code`, `notes`,
  and `full` profiles when a workflow needs a broader surface. Locate the installed
  package with `mempalace-code agent-plugin path`.

### Fixed

- Release preflight now rejects reuse of a version whose existing `v{version}`
  tag resolves to another commit. Missing tags and matching tagged builds remain
  valid, while unexpected Git lookup failures and empty identities fail closed.

## v1.13.1 — 2026-08-10

Patch release for systemd-user scheduled auto-updates.

### Fixed

- Generated systemd-user units now use the admitted absolute `uv` or `pipx`
  manager path under minimal systemd environments. A scheduled run whose exact
  current stable wheel is already installed exits 0 as a no-effect `up-to-date`
  no-op; verified bounds cover its lack of update-log, state-write, palace-file,
  and disk effects. Malformed provenance and unsafe `PATH` characters fail
  closed. Manual apply and actionable scheduled failures remain nonzero.

## v1.13.0 — 2026-08-10

Minor release for MCP protocol compatibility, bounded agent discovery, safer
scoped palace operations, watcher lifecycle stability, and executable release
quality gates.

### Added

- Stable MCP **2026-07-28** negotiation through the official Python MCP SDK 2.x,
  while preserving legacy `initialize` clients and the existing stdio entrypoints.
- Bounded `mempalace-code status --summary` output for agent-safe drawer, taxonomy,
  and storage discovery.
- Subprocess-level golden CLI scenarios covering init, mine, no-op mine, status,
  search, read, export, import, backup, restore, and watch from installed artifacts.
- Canonical architecture, documentation-drift, performance-budget, public-safety,
  package-content, installed-metadata, and workflow-summary gates shared by local
  verification and CI.
- Public-safe quality evidence for every `AUTOPILOT-DEMO-*` item, including the
  enforcing command and real CLI, MCP, package, or API boundary where applicable.
- Compact benchmark fixture facts that keep published token-savings claims tied to
  a reproducible corpus and query set.
- Machine-readable retrieval-quality facts, complete README coverage for all 29 MCP
  tools, and CI compatibility coverage for every supported Python 3.11–3.14 runtime.

### Changed

- Explicit wing and room filters are validated against the palace taxonomy before
  retrieval across CLI, Python, and MCP surfaces. Unknown identifiers return bounded,
  advisory suggestions; valid scopes with no matches remain successful empty results.
- Token-savings documentation now reports the refreshed canonical fixture: 14.5x
  median and 33.8x peak fewer tokens for its 20-query workload.
- PyPI publishing is tag-only, validates tag-to-version and tag-to-main
  provenance, checks wheel/sdist metadata, serializes concurrent release work,
  and creates the GitHub Release only after trusted publishing succeeds.
- Offline guidance now distinguishes standard CLI/MCP operation from the explicit
  low-level `EntityRegistry.research()` Wikipedia lookup.

### Fixed

- Explicit `--palace` backup, restore, mining, and pre-optimize paths now form a
  complete data boundary: absent palace-local KG state is omitted and default-global
  graph data is never imported into a scoped archive.
- True no-op incremental mining proves the no-op before loading the embedder,
  creating an archive, optimizing storage, or growing palace disk usage.
- Watcher runs reuse one warmed store/model lifecycle across remine cycles, keep
  post-warm-up RSS, file descriptors, archives, and disk growth bounded, and shut
  down cleanly on SIGINT.
- Watcher startup rejects dangling or unreadable source symlinks before creating a
  backup or entering a restart loop.
- Search-to-read accepts filesystem-equivalent macOS `/tmp` and `/private/tmp`
  spellings while retaining traversal, ambiguity, and external-path guards.
- Backup archives, JSONL imports, and project configuration failures reject unsafe
  or malformed inputs before mutating palace state.

## v1.12.1 — 2026-07-12

Patch release for named systemd-user watcher coordination in the opt-in updater.

### Fixed

- `mempalace-code update status` and `apply` discover an attributable active named watcher unit, including root-specific units such as `mempalace-watch-srv-dev.service`.
- Discovery refuses before package or service mutation when the watcher is ambiguous, malformed, unrelated, or unavailable.
- Apply and rollback coordinate the exact selected watcher unit.

## v1.12.0 — 2026-07-12

Minor release for the opt-in `mempalace-code update` workflow.

### Added

- Explicit status, check, apply, and disabled-by-default systemd-user scheduler commands for package updates.
- Canonical PyPI provenance checks, extras preservation, exclusive operation leasing, watcher coordination, staged validation, and rollback.

### Changed

- Package metadata, lockfile, README version shield, and updater fixtures now use the v1.12.0 release baseline.

## 2026-06-19 · AUTOPILOT-DEMO-PUBLIC-SAFETY-COMMITTED-MODE

Add committed-tree public-safety scan mode to `scripts/public_safety_scan.py` for release verification that inspects HEAD independently of worktree state.

## v1.11.0 — 2026-06-18

Minor release for release-readiness gates, dependency audit automation, offline
search guards, watcher reliability, and clearer CLI recovery guidance.

### Added

- Code-intelligence demo packet with deterministic public exhibits: generated fixture
  project mined, searched, and read via real CLI with exact commands and normalized
  output captured in `docs/demo/code-intelligence-packet.{md,json}`.
- Generation script `scripts/gen_code_intelligence_packet.py` with `--check` mode
  for drift detection and public-safety validation; wired into `/verify` and CI.
- Comprehensive test suite for packet generation with coverage for output
  normalization, known-answer retrieval assertions, and artifact cleanup.
- Dependency upgrade/audit gate covering proposed dependency changes, current
  resolver audit checks, CI integration, allowlist handling, and documentation.
- Weekly scheduled dependency audit workflow for the current dependency graph.
- Six-surface release publication status gate covering publish remote tags,
  branch tests, PyPI publish workflow status, GitHub Release metadata, PyPI JSON,
  and fresh install smoke.
- Watcher startup readiness markers for `watch_and_mine` and `watch_all`, making
  daemon initialization distinguishable from stale post-recovery log entries.

### Changed

- Human-facing CLI failures now prefer explicit `Next:` recovery guidance across
  search, read, export, backup/restore, watch status, mine-all, compress, health,
  cleanup, and model-fetch flows.
- Pipe-sensitive commands keep machine-readable output clean: `read` failures and
  `export --out -` diagnostics go to stderr, and generated backup/watch schedule
  snippets remain on stdout while install hints go to stderr.
- Legacy Claude Code hook prompts now give concise MCP save contracts instead of
  broad "save everything" instructions, while Codex/Gemini docs point to MCP +
  canonical usage rules.

### Fixed

- `watch_and_mine` and `watch_all` now refuse uninitialized roots before starting
  macOS FSEvents observers, preventing runaway watcher churn on broad local roots.
- Cached Hugging Face model fetch and search paths are guarded by subprocess-level
  offline regressions that catch token warnings or metadata network calls.
- `watch status` now reports the top-level launchd service state instead of
  nested coalition state from `launchctl print`.
- Release status gate no longer requests unsupported `gh release view --json
  isLatest`; latest release is checked through `gh release list`.
- Release install smoke subprocesses are bounded by a timeout so public-surface
  diagnostics cannot hang indefinitely on resolver/network stalls.
- Release gate token sanitization avoids self-matching scanner literals while
  still redacting GitHub and PyPI token-shaped values from diagnostics.
- `search --palace <missing>` now fails with a clear stderr diagnostic instead
  of reporting an empty result set.

### Removed

- Ignored `.tasks/` and `docs/audits/` Autopilot artifacts are no longer tracked
  in the public tree.

## v1.10.4 — 2026-06-06

Patch release for public quality/demo gates after v1.10.3.

### Added

- Deterministic public quality scorecard artifacts under `docs/quality/`, with
  Markdown and JSON output generated by `scripts/quality_scorecard.py`.
- Repo-wide public-safety scanner for tracked and staged files:
  `python scripts/public_safety_scan.py --tracked --staged`.
- Public-safe multi-agent workflow review protocol for future quality work.
- Strict Pyright slice config for stable low-level modules, gated in CI and
  `/verify`.
- Detailed Autopilot demo backlog items for dependency audit CI, release status
  checks, committed-tree public-safety scanning, scorecard metric expansion,
  architecture guards, CLI/MCP contracts, docs drift guards, and workflow
  effectiveness checks.

### Changed

- `/verify` and CI now run public-safety, scorecard freshness, and strict-slice
  typecheck gates in addition to lint, format, tests, and basic Pyright.
- Ruff global ignores were reduced from 33 to 3; older package/test debt remains
  scoped to per-file ignores so new scripts inherit stricter rules.
- Suppression scanning now uses Python tokenization so strings/docstrings that
  mention `# type: ignore` do not count as live suppressions.
- `scripts/quality_scorecard.py --check` now fails when committed scorecard
  artifacts are stale.

### Removed

- `.verify-state` is no longer tracked and is ignored as a local-only verification
  baseline.

## v1.10.3 — 2026-06-05

Follow-up patch for the v1.10.2 release: fixes the hosted test failure, refreshes
audited dependency locks, and removes ignored local task/audit artifacts from
the tracked public repository.

### Fixed

- Project mining now hard-excludes the active palace storage directory from
  scan inputs, preventing LanceDB storage files from being indexed or counted as
  tiny source files when the palace lives inside the project root.

### Changed

- The deprecated `.[chroma]` optional extra is capped below ChromaDB 1.x while
  GHSA-f4j7-r4q5-qw2c affects the available 1.x line.
- `uv.lock` now resolves the default and optional test stacks to audited current
  package versions, including LanceDB 0.33.0 and fixed transitive web stack
  dependencies.

### Removed

- Ignored Autopilot task/audit artifacts and a private local benchmark result
  file are no longer tracked in the public repository.

### Added

- Backlog and release/verification rules for audited dependency upgrades: check
  current and target versions against advisory data, audit a fresh resolver
  environment, and test clean CI-like installs before changing dependency
  ceilings or publishing a release.
- Autopilot demo quality backlog and roadmap covering public scorecards,
  static-analysis ratchets, real CLI/MCP contracts, architecture guards,
  security boundary tests, performance budgets, and docs drift guards.

## v1.10.2 — 2026-06-04

Patch release for the local-first embedding path.

### Fixed

- `restore` now scopes KG writes to the `--palace` path instead of the global
  default.
- `watch` now mines and watches an initialized root directory directly, and
  emits a clear diagnostic when no projects are found.
- Cached `search`, `mine`, and MCP search paths now load the sentence-transformers
  model with local-only resolution first, avoiding Hugging Face metadata requests
  after the setup download has already populated the cache.
- Re-running `mempalace-code fetch-model` on an already cached model now verifies
  the local cache instead of performing an online-capable Hub lookup.
- Suppressed third-party Hugging Face token warnings and weight-loading progress
  during cached model resolution; MemPalace keeps only its own concise status
  output.
- LanceDB optimize and cleanup now re-open the table and verify a fresh handle
  after maintenance. This catches missing-fragment failures that only appear for
  the next process instead of trusting a stale in-memory table handle.
- LanceDB upserts now retry once with a freshly opened table when Lance reports
  a missing fragment from a stale handle during merge-insert.

### Added

- `preflight mirror` CLI command and docs warning that delete-mode rsync against
  palace state can silently remove remote-owned data.
- Regression tests for cached local model resolution, explicit offline mode,
  local filesystem model paths, idempotent `fetch-model`, and forced re-download.
- Backlog item `STORE-HF-CACHED-SEARCH-SUBPROCESS-GUARD` for a future
  socket-blocked subprocess guard covering CLI stdout/stderr and network calls.

### Verified

- Real CLI smokes for cached `fetch-model`, normal search, explicit-offline
  search, and palace health.
- Focused storage and CLI command suites plus the network-marked offline gate.

## v1.10.1 — 2026-05-24

Patch release after the v1.10.0 publish. Focus: real CLI/MCP smoke fixes,
read-only no-embedder paths, and release-check tooling.

### Added

- Disposable `scripts/migrate_storage_smoke.py` release smoke for Chroma -> Lance
  migration. It generates a tiny legacy Chroma source, runs the real
  `migrate-storage` CLI, verifies source/destination counts, checks searchable
  migrated content, and exercises the non-empty destination guard.
- `mempalace_kg_query`, `mempalace_kg_timeline`, and architecture/KG relationship
  outputs now expose `source_file` provenance when it is present.

### Fixed

- MCP `delete_drawer` and `delete_wing` now work after read-only MCP calls in a
  fresh offline home without starting the embedding model or returning a false
  "No palace found".
- Read-only CLI/MCP paths (`status`, `health`, `read`, `export`, backup metadata,
  graph/layer traversal, dry-run maintenance) avoid unnecessary embedder startup.
- `python -m mempalace_code.cli ...` no longer emits the `runpy` warning caused by
  eager package-level CLI imports; the `mempalace-code` console entrypoint remains
  compatible.
- `export --out -` now routes progress and summary text to stderr, keeping stdout
  as pure JSONL so it can be piped directly into `import -`.
- `backup --out FILE create` now writes to the requested archive path instead of
  falling back to the default backups directory.
- `search` now prints the full stored source path so it can be copied into `read`.
  `read` also resolves unique basename and path-suffix matches within a wing.
- Tiny non-empty source files that produce no chunks are reported separately from
  already-filed skips, and unchanged tiny files are skipped on later incremental
  mines via a small per-wing hash sidecar.

### Verified

- Real MCP stdio smoke for delete-after-read and KG provenance.
- Real CLI smoke for export-to-import piping, backup `--out`, source-path read
  discovery, tiny-file mining, migrate-storage happy path/boundary/guard, and
  `python -m mempalace_code.cli` warning removal.
- Full release gate: 2229 tests passed, 4 deselected.

## 2026-05-23 · UPSTREAM-KG-TEMPORAL-VALIDATION

Validate KG temporal inputs (reject inverted validity windows, enforce ISO-8601 dates) and expose `valid_to` and `source_file` on `mempalace_kg_add`.

Current command/package names: the CLI is `mempalace-code`, the import package is
`mempalace_code`, and the MCP module is `python -m mempalace_code.mcp_server`.
Older historical entries may mention legacy `mempalace` names that were valid
when those changes landed.

## v1.10.0 — 2026-05-23

### Changed

- Managed scheduled backups now default to keeping the newest 14 archives.
  `pre_optimize` backups keep their newest-5 default, `manual` backups remain
  unbounded, and explicit `backup_retain_count=0` preserves keep-all semantics
  for every kind.
- Generated scheduled-backup snippets use managed `backup create --kind scheduled`
  archives so scheduled backups participate in kind-aware retention by default.

### Fixed

- Successful `safe_optimize()` runs now perform best-effort verified Lance
  stale-version cleanup after compaction/readability checks, reducing repeat
  backup bloat from old table versions.
- Backup, restore, install, and historical plan docs now consistently describe
  scheduled retention, explicit keep-all behavior, and post-optimize stale-version
  cleanup.

## v1.9.0 — 2026-05-12

### Added

- First-class Lua support in the code miner: `.lua` extension detection, structural
  chunking for `function`, `local function`, `M.method`, and `Class:method`
  declarations, module-table detection, Lua symbol metadata, and
  `code_search(language="lua")` filtering.
- First-pass static Ruby symbol extraction for classes, modules, methods,
  singleton methods, `attr*` declarations, and constants. Rails DSL and
  metaprogramming are intentionally not interpreted.
- First-class Helm indexing for raw charts: `Chart.yaml`, `values*.yaml`, and
  `templates/` YAML/Go-template files are mined as `language="helm"` with chart,
  values, and rendered-object-kind metadata where statically visible. Templates
  are not rendered.
- First-class Ansible indexing for playbooks, role tasks/handlers/defaults/vars,
  and static inventory files as `language="ansible"` with play, task, handler,
  vars, role, and inventory symbol metadata. Jinja expressions and inventory
  semantics are not evaluated.
- Strictly opt-in PyPI new-version checks:
  `mempalace-code version-check --enable/--disable/--status/--check-now`, with
  TTY prompt on first interactive run, interval throttling, stderr-only automatic
  hints, and zero network calls by default.
- Static MCP tool profiles (`full`, `minimal`, `kg`, `code`, `notes`) plus
  `--tools`, `--include`, and `--exclude` startup flags for per-client tool
  subsetting.
- Pyright is now part of the dev dependency set and has a non-gating CI baseline
  job while the existing diagnostics are worked down.

### Changed

- `mempalace_code_search` language and symbol-type hints now include `lua` and
  `local_function`, plus the Ruby, Helm, and Ansible labels/symbol types.
- `mempalace_code_search` now accepts 45 searchable language labels generated
  from the shared miner catalog.
- `cli.py` and `miner.py` were split into focused command/mining modules while
  preserving their public compatibility facades.
- `palace_graph` now uses typed graph payload sets internally.
- Pre-optimize backups are bounded by default to the newest 5 managed archives
  unless `backup_retain_count` is explicitly set; manual and scheduled backups
  remain keep-all by default.
- The release gate collected 2025 tests.

### Fixed

- Added Go and Rust tree-sitter regression tests proving blank-line-detached
  comments/attributes are not absorbed into the following declaration chunk.

## v1.8.1 — 2026-05-03

### Fixed

- Watcher disk-budget skip warnings now print on the first skipped cycle even
  on fresh systems where the monotonic process clock is still below the
  throttle interval.

## v1.8.0 — 2026-05-03

### Added

- LanceDB storage cleanup: `mempalace-code cleanup` reclaims stale Lance
  versions/fragments after optimization, with dry default retention and an
  explicit `--unsafe-now` emergency mode.
- Disk-budget guards for backup and watcher loops. Backups now fail before
  opening archive files when projected post-backup free space would fall below
  the configured floor; watchers skip write cycles while the palace is under
  budget.
- `mempalace-code watch <dir> status` reports free space, palace/backups size,
  configured threshold, and macOS launchd state.
- `code_search(..., rerank="hybrid")` and the MCP `mempalace_code_search`
  `rerank` argument expose BM25-style token-overlap reranking for code search.
- Conversation normalization now covers Gemini CLI JSONL and compacts Claude
  Code tool-use/tool-result blocks.

### Changed

- .NET retrieval benchmark baseline on the pinned CleanArchitecture corpus is
  now R@5 0.900 / R@10 1.000 in vector mode; local hybrid rerank comparison
  measured R@5 1.000 / R@10 1.000 on 2026-05-03.
- Generated `entities.json` files from init/entity detection are skipped during
  project mining by default, unless explicitly force-included.
- `MEMPALACE_BACKUP_MIN_FREE_BYTES` and `backup_min_free_bytes` remain supported
  as compatibility aliases for the newer `backup_disk_min_free_bytes` floor.
- The release gate collected 1769 tests.

### Fixed

- MCP request handling tolerates `params: null`, `arguments: null`,
  notification messages, and client noise keys such as `wait_for_previous`.
- Search/read paths tolerate rows with missing or `None` metadata without
  crashing.

## v1.7.0 — 2026-05-02

### Added

- Architecture extraction mode: `mempalace-code mine` now emits higher-level KG
  facts for .NET (C#, F#, VB.NET) and Python projects, including pattern, layer,
  namespace, and project membership facts.
- Architecture fact refresh is now wing-scoped, so re-mining one project no
  longer invalidates architecture KG facts from other projects in the same
  palace.
- Multi-repo palace sync: `mempalace-code mine-all` now mines multiple initialized
  projects into one palace with one wing per project, explicit `wing:` overrides,
  git-remote/folder wing auto-naming, duplicate-wing rejection before mining, and
  incremental per-repo re-mining by default.
- Release-grade coverage for backup/restore CLI dispatch, storage migration CLI
  passthrough/error handling, Python multi-import dependency extraction,
  devops/config file scanning, benchmark CI gates, watcher rule reloads, and
  tree-sitter detached-comment behavior.

### Changed

- The shipped Python import namespace is `mempalace_code`; docs and generated
  scheduler snippets prefer `mempalace-code` / `python -m mempalace_code` while
  preserving the source-checkout `mempalace.mcp_server` compatibility shim.
- Package metadata now matches the Python 3.11+ support floor.

### Fixed

- Watchers reload `scan_skip_dirs`, `scan_skip_files`, and `scan_skip_globs`
  without restarting `mempalace-code watch`.
- Generated backup/watch scheduler fallbacks no longer reference the legacy
  `python -m mempalace` module path.

## 2026-05-02 · ARCH-EXTRACTION-MODE

Architecture extraction mode: `mempalace-code mine` now runs a post-mining pass
that emits higher-level KG facts for .NET (C#, F#, VB.NET) and Python projects.

### Added

- `mempalace_code/architecture.py` — new module with pattern detection
  (`is_pattern`: Service, Repository, Controller, ViewModel, Factory), layer
  classification (`is_layer`: UI, Business, Data, Infrastructure), namespace
  tagging (`in_namespace`), and project membership (`in_project`).
- `KnowledgeGraph.invalidate_by_source_file` gains an optional `predicates`
  parameter so architecture facts can be refreshed without expiring type
  dependency facts (implements, inherits, depends_on, etc.).
- Architecture config block in `mempalace.yaml` under `architecture:` — supports
  custom `patterns` (name, suffixes, explicit `type_names`) and `layers`
  (name, namespace_globs, type_suffixes, priority). Invalid rule entries are
  silently ignored; the pass continues with built-in defaults.
- KG queries: `entity="Service", direction="incoming"` shows all services;
  `entity="Data", direction="incoming"` shows all data-layer types.

## 2026-05-02 · FUT-MULTI-REPO

Multi-repo palace sync: `mine-all` command mines multiple project directories into one palace with per-repo wing isolation, wing auto-naming from git remote/folder, and incremental per-repo re-mining.

## 2026-05-01 · Recent completed task review

### Added

- `MINE-SCAN-RULES-LIVE-RELOAD`: watcher loops now reload `scan_skip_dirs`,
  `scan_skip_files`, and `scan_skip_globs` between scan cycles, so app-level
  exclude changes take effect without restarting `mempalace-code watch`.
- `QUAL-E2E-REMAINING-MODULES`: end-to-end coverage now includes `convo_miner`,
  `layers`, and `palace_graph` scenarios, including idempotent conversation
  re-mining, tiered context loading, tunnel detection, traversal, and missing-room
  boundary behavior.

### Changed

- `CLEAN-ONBOARDING`: `mempalace-code init` is config-file-first by default;
  interactive guided setup is routed through explicit onboarding paths instead
  of blocking the normal init flow.
- The shipped Python import namespace is now `mempalace_code`. Packaged
  `mempalace-code` installs no longer claim the top-level `mempalace` module,
  allowing same-environment coexistence with upstream/vanilla MemPalace.
- New MCP setup examples use `python -m mempalace_code.mcp_server`. Source
  checkouts keep a minimal `mempalace.mcp_server` shim so older repo-local
  Codex/Autopilot configs with checkout `PYTHONPATH` continue to start.

### Fixed

- `MINE-SCAN-GLOB-DIR-PRUNE`: glob rules that cover an entire generated
  directory now prune that subtree during the walk instead of filtering only
  after file discovery.
- Legacy hook fallbacks and active docs now call `mempalace-code` or
  `python -m mempalace_code`, matching the renamed package.

## 2026-05-01 · MINE-APP-SCAN-EXCLUDES-PR4

App-level scan excludes (`scan_skip_dirs`, `scan_skip_files`, `scan_skip_globs`) implemented in miner and watcher with hardened, tested outputs.

## v1.6.2 — 2026-05-01

### Added

- Shared language catalog for miner detection, `code_search` validation, and MCP language hints.
- `code_search(language=...)` now accepts Kotlin, XML project files, and Perl shebang-detected files, matching mined language labels from the catalog.

### Changed

- The `mempalace_code_search` MCP language description is generated from the same catalog used by search validation, reducing future drift when language support changes.
- PR #4's scan-exclude proposal is split into backlog item `MINE-APP-SCAN-EXCLUDES-PR4` instead of being merged with the catalog refactor.

## v1.6.1 — 2026-04-30

### Added

- Markdown section metadata in mined drawers: heading, heading level, heading path, document section type, and flags for Mermaid diagrams, fenced code blocks, and Markdown tables.
- `search_memories` now returns Markdown section context with each result when available.

### Changed

- Markdown prose chunking treats `#` through `######` headings as section boundaries and preserves section metadata through small-section merges and oversized-section splits.

## v1.6.0 — 2026-04-27

### Added

- Code retrieval benchmark for mempalace itself, with dataset validation and malformed-dataset hardening.
- .NET benchmark release pin: `jasontaylordev/CleanArchitecture` `v7.0.0` at `5a600ab8749c110384bc3bd436b9c67f3067b489`; current baseline is R@5 0.600 / R@10 0.850.

### Changed

- Code mining cleanup defaults: entity detection is opt-in during init, spellcheck is disabled by default for code mining, and emotional extraction is opt-in for conversation mining.
- Search and health paths avoid unnecessary LanceDB vector-column materialization and return full `source_file` paths consistently.
- README and install docs now document `--detect-entities`, its sampling limits, output file, and code-repo caveats.

### Fixed

- ChromaDB count fallbacks for status/taxonomy views.
- Kubernetes YAML separator handling inside block scalars.
- C# expression-bodied property extraction, Java package-private method extraction, Swift distributed actor detection, HCL block boundaries, and JSX/TSX language filters.
- Architecture MCP reference coverage and `extract_reusable` glue classification.

## 2026-04-26 · EXTRACT-REUSABLE-REFERENCES-PROJECT-GLUE

Promote extract_reusable entities to glue when they reference platform projects.

## 2026-04-26 · ARCH-REF-COVERAGE

Add find_references coverage for depended_by and referenced_by relationship categories.

## 2026-04-26 · HEALTH-SCAN-PROJECTION

Use projected metadata scans for health check and recovery probes to avoid vector-column materialization.

## 2026-04-26 · STORE-SEARCH-SOURCE-FILE-FULL-PATH

Return full source_file paths from search_memories to match code_search.

## 2026-04-26 · MINE-LANCE-VECTOR-SCAN

Harden LanceStore metadata scans to avoid vector-column materialization.

## 2026-04-25 · STORE-CHROMA-COUNTBY-FALLBACK

Add ChromaDB count fallbacks so wings, rooms, taxonomy, and status reflect existing drawers.

## 2026-04-25 · TEST-STORAGE-EDGE

Add LanceStore edge-case tests for empty ID lookups and SQL filter operators.

## 2026-04-25 · MINE-K8S-YAML-SEPARATOR

Keep Kubernetes YAML document separators inside block scalar values from splitting manifest chunks.

## 2026-04-25 · CLEAN-EMOTION-EXTRACT

Remove emotional memories from default general extraction while keeping them opt-in for conversation mining.

## 2026-04-25 · CLEAN-SPELLCHECK

Disable spellcheck by default for code mining while keeping conversation mining spellcheck enabled.

## 2026-04-25 · CLEAN-ENTITY-DETECT

Make heuristic people/project detection opt-in during init.

## 2026-04-25 · STORAGE-BACKUP-RETENTION

Prune pre-optimize backup archives according to configurable retention settings.

## 2026-04-25 · MINE-K8S-LARGE-DOC

Propagate Kubernetes manifest symbol metadata across large-document sub-chunks.

## 2026-04-24 · MINE-SWIFT-DISTRIBUTED

Detect Swift distributed actors as mining boundaries and symbols.

## 2026-04-24 · MINE-CSHARP-EXPR-BODY

Detect C# expression-bodied properties as mining boundaries and symbols.

## 2026-04-24 · MINE-JAVA-PKG-PRIVATE-METHODS

Extract package-private Java methods during symbol extraction.

## 2026-04-24 · CODE-SEARCH-LANG-JSX-TSX

Add jsx and tsx code_search language filters for React and TypeScript projects.

## 2026-04-24 · MINE-HCL-BOUNDARY-MODERN

Add Terraform 1.1+ HCL block boundaries for moved, import, check, and removed.

## v1.5.0 — 2026-04-21

### Added

- **5 new languages in the code miner:**
  - **Dart** — classes, mixins, extensions, enums, functions; named/factory constructors, async/await (MINE-DART)
  - **Scala** — classes, case classes, objects, traits, enums, functions; implicits, type aliases, generics, access modifiers (MINE-SCALA)
  - **Kubernetes manifests** — Deployments, Services, ConfigMaps, Secrets, Ingresses, CRDs from `.yaml`/`.yml`, indexed by kind, namespace, name, labels (MINE-K8S)
  - **PHP** — classes, interfaces, traits, enums (PHP 8.1+), functions, methods, namespaces; Laravel / WordPress / Symfony project recognition (MINE-PHP)
  - **Swift** — classes, structs, enums, protocols, functions, properties, extensions, actors, async/await (MINE-SWIFT)
- **2 new MCP tools:**
  - `mempalace_mine` — agents can trigger incremental or full project re-mining without CLI access; returns structured counts of files processed and drawers filed (MCP-MINE-TRIGGER)
  - `mempalace_file_context` — returns all indexed chunks for a specific source file, ordered by `chunk_index`; useful for reviewing what was mined, handling deleted/renamed files, or getting ordered file context without reading from disk (MCP-FILE-CONTEXT)

### Changed

- **LLM usage rules rewritten as LLM-agnostic** — `docs/LLM_USAGE_RULES.md` now targets any MCP-capable agent (Claude Code, Codex, Cursor, Windsurf, Continue, Zed, Aider, …); routing table maps 16 common tasks to the right specialist tool; `MEMPALACE_AGENT_NAME` env var for diary attribution; extended Never list covering destructive-delete guards, diary non-authoritativeness, and absence-from-search-miss; correction recipe added. `docs/AGENT_INSTALL.md` §7.3 synced. README's misleading "AI learns the protocol automatically" claim replaced with a concrete pointer to the usage rules. (LLM-USAGE-RULES)

## v1.4.1 — 2026-04-20

### Changed
- **Docs: hooks are legacy** — MCP tools + usage rules are now the recommended approach for all agents (Claude Code, Codex, Cursor); hooks demoted to optional Claude Code-only extra
- **Docs: unified saving story** — README, AGENT_INSTALL, and hooks README all consistently describe watcher for code mining + MCP for conversation context

## v1.4.0 — 2026-04-19

### Added
- **Watcher quiet mode** — re-mines suppress verbose output; only logs a one-line summary when drawers are actually filed; no-op commits produce zero log noise; optimize skipped on empty batches
- **Per-project `bin/` skip** — `bin/` no longer globally skipped; only excluded when .NET project markers (`.csproj`, `.sln`, `.fsproj`, `.vbproj`) are present (MINE-BIN-SKIP-DIRS)
- **Kotlin nested generic receiver** — `fun <T> List<Pair<K,V>>.ext()` now parsed correctly (MINE-KOTLIN-GENERIC-RECEIVER-NESTED)
- `mine()` now returns stats dict (`files_processed`, `drawers_filed`, `elapsed_secs`)

### Fixed
- **Watcher on-commit detection** — `watchfiles.DefaultFilter` ignores `.git/` by default; on-commit mode now passes `watch_filter=None` so `.git/refs/heads/` changes are detected
- **Watcher log buffering** — flush Python stdout/stderr before restoring file descriptors to prevent mine() output leaking to real stdout
- **HuggingFace/safetensors noise** — suppress BertModel LOAD REPORT and progress bars via OS fd-level redirect during model init

## v1.3.0 — 2026-04-19

First-class C#/.NET support — delivers [rergards/mempalace-code#1](https://github.com/rergards/mempalace-code/issues/1) in full.

### Added
- **C# structural mining** — parse `.cs` files by namespace, class, interface, enum, record, method, property, event; partial class support, XML doc preservation (MINE-CSHARP)
- **.NET solution/project awareness** — `.sln` and `.csproj` parsing with project references, package references, target frameworks; queryable via KG (MINE-DOTNET)
- **F#, VB.NET, XAML mining** — `.fs`/`.fsi`, `.vb`, `.xaml` with structured symbol extraction and code-behind linking (MINE-DOTNET, MINE-XAML, MINE-XAML-NAME-ATTR)
- **Cross-project symbol relationships** — interface implementations, inheritance, type usage stored as KG triples (DOTNET-SYMBOL-GRAPH)
- **C# multi-line base-type declarations** — `class Foo :\n    IBar, IBaz` now parsed correctly (DOTNET-CS-MULTILINE-BASE)
- **6 architecture MCP tools** — `find_implementations`, `find_references`, `show_project_graph`, `show_type_dependencies`, `explain_subsystem`, `extract_reusable` (MCP-ARCH-TOOLS, ARCH-RETRIEVAL, LOGIC-EXTRACTION)
- **Python type extraction to KG** — class inheritance and ABC/Protocol implementations (PY-TYPE-KG)
- **`mine-all` command** — batch mine all projects in a parent directory (MINE-MULTI)
- **`--watch` flag** — auto-incremental re-mining on file changes via watchdog (MINE-WATCH)
- **Auto-organize by .NET structure** — `.sln` creates wing, `.csproj` maps to room (REPO-STRUCTURE-DEFAULTS)
- **.NET benchmark suite** — 20-query R@5/R@10 benchmark targeting CleanArchitecture (BENCH-DOTNET)

### Fixed
- `find_implementations` now includes Python ABC/Protocol subclasses (FIND-IMPL-INHERITS)
- `.gitignore` patterns respected in `--watch` mode (MINE-WATCH-GITIGNORE-CACHE)

### Stats
- 27 MCP tools (was 18)
- 1002 tests (was 527)

## 2026-04-19 · REPO-STRUCTURE-DEFAULTS

Auto-organize wings/rooms by .NET solution/project structure: mining a repo with `.sln` files now creates a wing named after the solution and maps each `.csproj` to a room, using KG project info for defaults and supporting configurable folder-based room detection.

## 2026-04-18 · FIND-IMPL-INHERITS

Fix `mempalace_find_implementations` to include Python ABC/Protocol subclasses: when the queried interface is itself abstract (has an outgoing `implements → ABC/ABCMeta/Protocol` edge), incoming `inherits` triples are now included alongside `implements` triples, so concrete subclasses are returned instead of an empty list.

## 2026-04-18 · MINE-WATCH

Add `--watch` flag to `mempalace mine` for auto-incremental re-indexing: uses `watchdog` to monitor file changes, debounces updates (5s), and only re-indexes modified files — keeping the palace in sync automatically with low CPU overhead when idle.

## 2026-04-18 · PY-TYPE-KG

Add Python type extraction to the knowledge graph in `miner.py`: class inheritance (`class Foo(Bar)` → `extends` triple) and ABC/Protocol implementations are now extracted for Python codebases, making architecture retrieval tools (`find_implementations`, `find_references`, `show_type_dependencies`, `extract_reusable`) functional for Python projects.

## 2026-04-18 · MINE-MULTI

Add `mempalace mine-all <parent-dir>` command for batch multi-project mining: scans immediate subdirectories for project markers (`.git`, `pyproject.toml`, `package.json`, `*.sln`, `go.mod`, `Cargo.toml`, `go.sum`), mines each detected project into its own wing, and reports per-project results with a summary table.

## 2026-04-18 · LOGIC-EXTRACTION

Add `mempalace_extract_reusable` MCP tool: classifies transitive dependencies of a symbol/subsystem as core, platform-specific, or glue, and identifies the minimal public interface needed for safe extraction.

## 2026-04-18 · ARCH-RETRIEVAL

Add `mempalace_explain_subsystem` MCP tool: combines semantic search with KG traversal to answer "how does this subsystem work?" queries, returning entry points, extracted symbols, and expanded relationships.

## 2026-04-18 · MCP-ARCH-TOOLS

Add 4 architecture-oriented MCP tools for .NET type analysis: `mempalace_find_implementations`, `mempalace_find_references`, `mempalace_show_project_graph`, and `mempalace_show_type_dependencies`.

## 2026-04-17 · SKILLS-HOOKS

Add Claude Code skills and hooks from wh40k workflow: 12 skills (`/start`, `/status`, `/verify`, `/palace-health`, `/task-plan`, `/task-hardening`, `/doc-refresh`, `/ship`, `/release`, `/entropy-gc`, `/mine`, `/bench`), 3 shared modules (mode-classification, task-state, commit-checkpoint), Codex review integration, pre-commit verification gate, and edit logging hooks.

## 2026-04-17 · BENCH-DOTNET

Add .NET benchmark suite: `benchmarks/dotnet_bench.py` measures R@5/R@10 retrieval quality on C#/.NET repositories, validates symbol extraction accuracy, and reports embedding/query timing. Integrated with CI for regression detection.

## 2026-04-17 · MINE-XAML

Add XAML and WPF code-behind linking support: `.xaml` files are mined with control hierarchy extraction; `x:Name` references link to code-behind `.xaml.cs` files via KG triples; resource dictionaries and style references are indexed.

## 2026-04-17 · DOTNET-SYMBOL-GRAPH

Cross-project symbol relationships via KG: interface implementations, inheritance, and type usage references are now detected during .NET mining and stored as KG triples, enabling `mempalace_kg_query` to surface all implementers or subclasses of a given type across projects.

## 2026-04-17 · MINE-DOTNET

Add .NET ecosystem support to code miner: F# (`.fs`, `.fsi`), VB.NET (`.vb`), project files (`.csproj`, `.fsproj`, `.vbproj`), and solution files (`.sln`) are now mined with structured symbol extraction and KG triples for project dependencies, package references, and solution structure.

## 2026-04-17 · MINE-CSHARP

Add C# language support to code miner: `.cs` files are now mined with structured symbol extraction for classes, interfaces, structs, enums, records, methods, properties, fields, constructors, and events; namespaces, partial classes, attributes, XML doc comments, and nested types with generic constraints are handled correctly.

## 2026-04-17 · MINE-KOTLIN

Add Kotlin language support to code miner: `.kt` and `.kts` files are now mined with structured symbol extraction for classes, objects, interfaces, functions, properties, data classes, sealed classes, enums, companion objects, extension functions, and coroutine/DSL constructs.

## 2026-04-17 · MINE-JAVA-SMART

Add smart symbol extraction for Java: classes, interfaces, enums, records, methods, fields, and annotations are now extracted as structured drawers instead of plain chunks; generics, inner classes, and annotation types are handled correctly.

## 2026-04-17 · CODE-SEARCH-LANG-PROSE

Add markdown, text, and csv to `SUPPORTED_LANGUAGES` so `code_search(language="markdown"|"text"|"csv")` validates and filters correctly instead of returning an error.

## 2026-04-16 · STORAGE-AUTO-BACKUP

Auto-backup palace before risky operations: `safe_optimize` triggers a backup by default, `backup list` and `backup schedule` subcommands added, and `auto_backup_before_optimize` is enabled out-of-the-box.

## 2026-04-16 · FIX-LANCE-CORRUPT

Detect and recover from missing LanceDB fragment files: `safe_open_table` probes the table with a count query on open and rolls back to the last clean version automatically when fragment corruption is detected.

## 2026-04-14 · MINE-DEVOPS-INFRA

Add DevOps/infrastructure file support to the miner: Terraform (`.tf`, `.tfvars`, `.hcl`), Dockerfiles, Makefiles, Helm templates (`.tpl`), Ansible Jinja2 templates (`.j2`, `.jinja2`), and general config files (`.conf`, `.cfg`, `.ini`) are now scanned and indexed.

## 2026-04-14 · STORE-CHROMA-DELETE-WING-LIMIT

`ChromaStore.delete_wing` now calls `self.get()` instead of `self._col.get()`, so the `limit=10000` wrapper applies. Wings with more drawers than ChromaDB's default page size were silently partially deleted. (ChromaDB is deprecated; cleanup only.)

## 2026-04-14 · STORE-REMOVE-CHROMA-DEFAULT

ChromaStore isolated into `mempalace/_chroma_store.py` with lazy import — ChromaDB is no longer imported unless `.[chroma]` is installed and explicitly selected. Reduces default import time and dependency surface.

## 2026-04-14 · STORE-WHERE-ARROW-OPS

`_where_to_arrow_mask` now handles operator dicts (`$gt`, `$gte`, `$lt`, `$lte`, `$ne`, `$in`) in LanceDB filter translation. Previously only equality filters were supported; comparison and set-membership queries silently returned incorrect results.

## 2026-04-14 · CODE-SEARCH-LANG-CPP

C/C++ language support: `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hxx` extensions recognized by the miner with struct/enum/union/typedef/function symbol extraction for C and class/struct/enum/function extraction for C++. `code_search(language="c")` and `code_search(language="cpp")` now work.

## 2026-04-14 · CODE-SEARCH-LANG-CONFIG

`yaml`, `json`, and `toml` added to `SUPPORTED_LANGUAGES` in searcher.py so `code_search(language="yaml")` etc. return results. These file types were already mined but not filterable by language.

## 2026-04-14 · CODE-SYMBOL-META-GO-TYPES

Go symbol extraction now captures scalar types (`type Foo int`), function types (`type Handler func(...)`), and type aliases (`type ID = string`) in addition to struct/interface/func declarations.

## 2026-04-14 · MINE-EAGER-EMBED-INIT

Embedding model is now loaded eagerly during `MinerConfig` init instead of lazily on first chunk. Prevents a multi-second stall mid-mining when the model loads for the first time.

## 2026-04-14 · CODE-SMART-CHUNK-VAR-BOUNDARY

Non-exported `var` and `let`/`const` declarations at module scope added to `TS_BOUNDARY`, so top-level JS/TS variable declarations start a new chunk instead of being merged into the preceding function.

## 2026-04-14 · LANG-DETECT-GO-VAR-BODY

Removed `var\s+\w+` from `GO_BOUNDARY` — it was matching `var` declarations inside function bodies, causing mid-function chunk splits. Go var blocks are now only boundaries at the package level via `var (` syntax.

## 2026-04-14 · LANG-DETECT-NODEJS-SHEBANG

`detect_language` now recognizes `#!/usr/bin/env node` and similar Node.js shebangs, mapping them to `javascript`. Previously, Node.js scripts without a `.js` extension were classified as unknown.

## 2026-04-14 · CODE-TREESITTER-TS

Tree-sitter AST-aware TypeScript/JavaScript/TSX/JSX chunking: extracts function/class/method/export/import boundaries from the AST; falls back to regex when tree-sitter grammars are unavailable.

## 2026-04-14 · STORE-BACKUP-RESTORE

Add `mempalace backup` and `mempalace restore` CLI commands: backup creates a .tar.gz of the LanceDB lance/ directory plus knowledge_graph.db and a metadata.json (drawer count, wing list, timestamp, version, backend); restore extracts into the palace path with an optional --force flag to overwrite.

## 2026-04-14 · CODE-TREESITTER-EXPAND

Tree-sitter AST-aware Go and Rust chunking: extracts func/type/var/const boundaries for Go and fn/struct/enum/trait/impl/mod boundaries for Rust; falls back to regex when grammars are unavailable.

## 2026-04-14 · CODE-TREESITTER-PYTHON

Tree-sitter AST-aware Python chunking: extracts function/class/method boundaries from `function_definition`, `class_definition`, and `decorated_definition` nodes; falls back to regex when py-tree-sitter is unavailable.

## 2026-04-14 · CODE-TREESITTER-INFRA

Tree-sitter optional infra: `.[treesitter]` extra, grammar download/cache, parser init, and automatic regex fallback when py-tree-sitter is absent or grammar unavailable.

## v1.0.0 — 2026-04-12

First public release of **mempalace-code**, a code-first fork of
[milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace).

### Storage — LanceDB rewrite

- **LanceDB backend** replaces ChromaDB as the default. Crash-safe columnar Arrow storage, no server required.
- **Automatic schema migration** — palaces created by older versions are upgraded transparently on open. No manual migration commands needed.
- **NULL-safe migration defaults** — `CAST('' AS string)` prevents null corruption in existing rows during schema evolution.
- **Table handle reload** after migration — fixes "missing fields" error on multi-drawer writes to migrated palaces.
- ChromaDB retained as optional `[chroma]` extra (deprecated).

### Code mining

- **Language-aware structural chunking** — Python, TypeScript/JavaScript, Go, Markdown. Splits at function/class/type boundaries, not arbitrary line counts.
- **Language detection** — file extension + shebang + content heuristics. 20+ languages recognized.
- **Symbol metadata extraction** — `symbol_name`, `symbol_type`, `language` on every chunk. Enables code-search filtering.
- **Incremental re-mining** — content-hash based. Only changed files are re-chunked. `--full` flag forces rebuild.
- **Batch embedding with upsert** — deduplicates on write, idempotent re-mines. Batched writes reduce LanceDB overhead on large projects.

### MCP tools (18 tools)

- **`mempalace_code_search`** — filter by language, symbol name/type, file glob. Returns symbol metadata.
- **`mempalace_add_drawer`** — now writes `chunker_strategy: "manual_v1"` provenance for backup/restore filtering.
- **`mempalace_delete_wing`** — delete all drawers in a wing.
- AAAK dialect tool removed from default MCP exposure (code preserved, dormant).

### Export / Import

- **`mempalace export`** — JSONL dump with `--only-manual` filter (preserves drawers the miner can't regenerate).
- **`mempalace import`** — restore from JSONL with dedup, dry-run, wing override.
- Streaming via `iter_all()` — no full-table memory load.

### CLI

- **`mempalace init`** — downloads embedding model (~80 MB) explicitly during setup.
- **`mempalace fetch-model`** — pre-download the model for offline use.
- **`mempalace mine --full`** — force full rebuild instead of incremental.
- **`mempalace export / import`** — backup and restore commands.
- **`mempalace diary write / read`** — agent session journals.

### Knowledge graph

- Temporal entity-relationship triples in local SQLite.
- `kg_add`, `kg_query`, `kg_invalidate`, `kg_timeline`, `kg_stats` — all via MCP.

### Quality

- **419 tests** across 15 test files. Every feature acceptance-gated.
- Schema migration regression tests (multi-write, NULL safety, partial migration).
- Storage edge-case tests ($in operator, empty IDs, comparison operators).
- Export/import round-trip tests with dedup verification.

### Docs

- `docs/AGENT_INSTALL.md` — decision-tree runbook for agent-driven installation.
- `docs/UPSTREAM_HARDENING.md` — full audit of upstream claims vs fork status.
- `docs/BACKUP_RESTORE.md` — backup workflow for manual drawers.
- `docs/OFFLINE_USAGE.md` — offline operation guide.
- `benchmarks/BENCHMARKS.md` — methodology caveats for upstream benchmark numbers.

### Upstream issues addressed

- [#469](https://github.com/milla-jovovich/mempalace/issues/469) — ChromaDB version-cliff data deletion → LanceDB, no version-cliff risk.
- [#524](https://github.com/milla-jovovich/mempalace/issues/524) — Silent ONNX model download → explicit `mempalace init` + `fetch-model`.
- [#27](https://github.com/milla-jovovich/mempalace/issues/27) — Unverifiable 100% R@5 claim → removed. AAAK "lossless" claim → labeled lossy.

### License

Changed from MIT to Apache 2.0 for trademark protection and attribution requirements.
