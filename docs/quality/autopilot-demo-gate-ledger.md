# AUTOPILOT-DEMO Gate Ledger

Public-safe pass/gap ledger for every archived AUTOPILOT-DEMO backlog item.

Each entry lists: enforcing gate command, before/after metrics, and behavioral evidence.
No timestamps, local absolute paths, private data, or task-internal state.

Source: `docs/quality/autopilot-demo-gate-ledger.json`

---

## AUTOPILOT-DEMO-QUALITY-SCORECARD — PASS

**Summary:** Deterministic public quality scorecard for Autopilot cleanup progress.

**Enforcing gate:** `python scripts/quality_scorecard.py --check`

**Before:** No machine-readable quality snapshot; progress was prose-only.

**After:** `scripts/quality_scorecard.py` emits Markdown+JSON; `--check` gates shape, determinism, and public-safety in CI and `/verify`; baseline committed to `docs/quality/`.

**Behavioral evidence:** Two runs against the same tree produce byte-identical output. `--check` exits nonzero when shape or public-safety invariants are violated.

---

## AUTOPILOT-DEMO-PUBLIC-SAFETY-GATE — PASS

**Summary:** Repo-wide public-safety gate for tracked and staged files.

**Enforcing gate:** `python scripts/public_safety_scan.py --tracked --staged`

**Before:** No automated guard against committing tokens, local paths, or private remotes.

**After:** Scanner runs in CI and `/verify`; matched content is redacted; `.verify-state` is local-only.

**Behavioral evidence:** Exits 1 when any tracked or staged file contains a token/path/remote pattern. Output never prints matched text verbatim.

---

## AUTOPILOT-DEMO-RUFF-RATCHET — PASS

**Summary:** Reduce transitional Ruff ignores without broad style-only churn.

**Enforcing gate:** `ruff check mempalace_code/ tests/ scripts/`

**Before:** 33 global Ruff ignores covering historical suppression debt.

**After:** 3 global Ruff ignores; remaining debt scoped to per-file ignores; new scripts inherit stricter rule set.

**Behavioral evidence:** `ruff check` exits 0 with no new inline suppressions. Per-file ignore count is stable.

---

## AUTOPILOT-DEMO-PYRIGHT-STRICT-SLICE — PASS

**Summary:** Strict Pyright slice for stable low-level modules.

**Enforcing gate:** `python -m pyright -p pyrightconfig.strict.json`

**Before:** Only basic Pyright mode; no strict-mode coverage.

**After:** `pyrightconfig.strict.json` covers `version.py`, `mcp_tool_profiles.py`, `disk_budget.py`; wired into CI and `/verify`.

**Behavioral evidence:** `python -m pyright -p pyrightconfig.strict.json` exits 0 from the declared dev environment.

---

## AUTOPILOT-DEMO-WORKFLOW-REVIEW-PROTOCOL — PASS

**Summary:** Public-safe adversarial Claude workflow protocol for repo quality work.

**Enforcing gate:** `python scripts/workflow_review_protocol_guard.py --check`

**Before:** No public documentation of multi-agent quality-review workflow.

**After:** `docs/quality/workflow-review-protocol.md` documents adversarial review workflow; linked from `docs/quality/README.md`.

**Behavioral evidence:** Guard validates the protocol document for required sections and actionable language.

---

## AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET — PASS

**Summary:** Deterministic public-safe code-intelligence packet from real MemPalace CLI output.

**Enforcing gate:** `python scripts/gen_code_intelligence_packet.py --check`

**Before:** No deterministic code-intelligence demo artifact; demo claims were not reproducible.

**After:** `scripts/gen_code_intelligence_packet.py` produces `docs/demo/code-intelligence-packet.{md,json}`; 464-line test suite validates normalization, known-answer queries, check-mode drift, and cleanup.

**Behavioral evidence:** `--check` exits nonzero when committed packet drifts from freshly generated output. Tests cover known-answer retrieval against a synthetic fixture palace.

---

## AUTOPILOT-DEMO-CODE-INTELLIGENCE-PACKET-ACCEPTANCE-FIX — PASS

**Summary:** Close owner-acceptance blockers on the code-intelligence golden packet.

**Enforcing gate:** `python scripts/gen_code_intelligence_packet.py --check`

**Before:** Scanner-flagged token literal in source; audit evidence at non-public path; missing owner-acceptance checklist.

**After:** Token literal encoded; audit evidence at public-safe path; owner-acceptance checklist added; B905 zip strictness fixed.

**Behavioral evidence:** Public-safety scan passes on committed source. Packet generator `--check` exits 0. All 12 test suite verifications pass.

---

## AUTOPILOT-DEMO-PUBLIC-SAFETY-COMMITTED-MODE — PASS

**Summary:** Explicit committed-tree public-safety scan mode for release verification.

**Enforcing gate:** `python scripts/public_safety_scan.py --committed --tracked --staged`

**Before:** Gate only covered tracked/staged files; HEAD blobs were unchecked before release.

**After:** `--committed` mode scans HEAD blobs via git objects; redacted failure output; pre-commit vs release-readiness distinction documented.

**Behavioral evidence:** Exits 0 on clean repository with all three selectors active. Four fixture tests prove clean HEAD, secret redaction, local-only artifact rejection, and deleted-worktree boundary.

---

## AUTOPILOT-DEMO-MCP-STDIO-CONTRACTS — PASS

**Summary:** Real MCP stdio contract tests for profiles, tool discovery, and representative tool calls.

**Enforcing gate:** `python -m pytest tests/test_mcp_server.py::TestMCPStdioContracts -q`

**Before:** MCP server tests covered unit handlers only; no real stdio subprocess integration tests.

**After:** `TestMCPStdioContracts` class with 5 real stdio tests: full/default discovery, minimal profile filtering, include/exclude precedence, hidden-tool error, invalid-profile startup.

**Behavioral evidence:** Tests launch the MCP server as a real subprocess and exchange JSON-RPC over stdio. All 5 contract tests pass without network access.

---

## AUTOPILOT-DEMO-SCORECARD-METRIC-EXPANSION — PASS

**Summary:** Expanded quality scorecard metrics for gates that matter to the public demo.

**Enforcing gate:** `python scripts/quality_scorecard.py --check`

**Before:** Schema v1 lacked strict-slice, public-safety, and demo-gate metrics.

**After:** Schema v2 adds strict-slice coverage, public-safety gate status, and demo-gate inventory; 12 new tests; committed artifacts regenerated.

**Behavioral evidence:** `python scripts/quality_scorecard.py --check` exits 0 with v3 schema and all required metric sections present.

---

## AUTOPILOT-DEMO-DOCS-DRIFT-GUARD — PASS

**Summary:** Automated docs drift guard for CLI commands, MCP tools, optional extras, and release gates.

**Enforcing gate:** `python scripts/docs_drift_guard.py`

**Before:** No automated check that public docs matched actual CLI commands, MCP tools, optional extras, or release gate workflow names.

**After:** Guard validates argparse-derived CLI inventory, MCP tools/profiles, optional extras, release workflow names, and canonical verification commands against public docs.

**Behavioral evidence:** Guard exits 1 with per-surface diff when any documented command or tool name diverges from live source. Live docs aligned.

---

## AUTOPILOT-DEMO-CLI-GOLDEN-SCENARIOS — PASS

**Summary:** Subprocess-level golden CLI scenarios proving real user workflows.

**Enforcing gate:** `python -m pytest tests/test_cli_golden_scenarios.py -q`

**Before:** CLI tests covered unit handlers; no subprocess-level golden scenario coverage.

**After:** `tests/test_cli_golden_scenarios.py` covers init, mine, status, search, read, export, import, backup, restore plus guard paths as real subprocess invocations.

**Behavioral evidence:** All golden scenarios run as real subprocess calls. Tests exit 0 when CLI behaves as documented and fail on guard path violations.

---

## AUTOPILOT-DEMO-SECURITY-BOUNDARY-TESTS — PASS

**Summary:** Focused abuse-case tests for paths, archives, JSONL, YAML, and command preflight.

**Enforcing gate:** `python -m pytest tests/ -q -m "not needs_network" -k security_boundary`

**Before:** No dedicated security-boundary tests for path traversal, malformed JSONL, invalid config, or command preflight abuse.

**After:** `BackupArchiveError`/`unsafe_archive_member`, `JsonlInputError`/`malformed_jsonl`, `InvalidProjectConfigError`/`invalid_project_config`, and `security_boundary_*` tests in place.

**Behavioral evidence:** All `security_boundary_*` tests pass. Abuse cases raise the documented exception types.

---

## AUTOPILOT-DEMO-ARCHITECTURE-GUARD — PASS

**Summary:** Import-boundary guard preventing core modules from depending on CLI, MCP, or optional backend layers.

**Enforcing gate:** `python scripts/architecture_guard.py --root .`

**Before:** No import-boundary enforcement; accidental cross-layer imports were undetected.

**After:** Guard enforces layer isolation; tests validate allowed/forbidden import pairs; wired into CI and `/verify`.

**Behavioral evidence:** Guard exits 1 when any core module imports a CLI, MCP, or optional layer. Four contract-named tests cover boundary enforcement.

---

## AUTOPILOT-DEMO-PYRIGHT-STRICT-SLICE-EXPANSION — PASS

**Summary:** Expanded strict Pyright slice to config, reader, and mining/scanner modules.

**Enforcing gate:** `python -m pyright -p pyrightconfig.strict.json`

**Before:** Strict slice covered 3 modules (version.py, mcp_tool_profiles.py, disk_budget.py).

**After:** Strict slice expanded to 6 modules: added config.py, reader.py, mining/scanner.py with typed boundaries.

**Behavioral evidence:** `python -m pyright -p pyrightconfig.strict.json` exits 0 with all 6 modules in the strict include list.

---

## AUTOPILOT-DEMO-PERF-BUDGETS — PASS

**Summary:** Deterministic performance budgets for mining, search, read, and maintenance on synthetic fixtures.

**Enforcing gate:** `python benchmarks/demo_perf_budgets.py --check --ci`

**Before:** No performance gates; latency could regress silently between releases.

**After:** Hard latency budgets enforced on synthetic fixtures; 10 unit tests validate budget enforcement logic.

**Behavioral evidence:** `--check --ci` exits nonzero when any operation exceeds its budget. All 10 unit tests and 6 scorecard tests pass.

---

## AUTOPILOT-DEMO-WORKFLOW-EFFECTIVENESS-GUARD — PASS

**Summary:** Lightweight guard that workflow review summaries are actionable rather than ceremonial.

**Enforcing gate:** `python -m pytest tests/test_workflow_review_protocol.py -q`

**Before:** Workflow review summaries had no enforced structure; ceremonial wording satisfied the form without actionable findings.

**After:** Guard validates required sections, actionable language, and absence of vague approval phrases; 33 tests pass.

**Behavioral evidence:** All 33 workflow review guard tests pass. Protocol document updated to replace insufficient phrasing.

---

## AUTOPILOT-DEMO-END-TO-END-GATE-CLOSURE — PASS

**Summary:** Canonicalize all AUTOPILOT-DEMO gates, add built-artifact inspection, installed-provenance smoke, and a public evidence ledger.

**Enforcing gate:** `python scripts/release_readiness_gate.py --check --json`

**Before:** Gate commands scattered across CLAUDE.md, CI YAML, and scorecard metadata; no canonical single source; built artifacts not inspected before release; install smoke used sys.executable -m pipx.

**After:** `scripts/gate_inventory.py` is the single canonical source; `release_artifact_gate.py` inspects wheel/sdist member lists; `release_readiness_gate.py` orchestrates build+artifact+smoke; install smoke discovers pipx via PATH and Homebrew fallback.

**Behavioral evidence:** `gate_inventory.py --check` exits 0 when CI and `/verify` docs match all canonical commands. Artifact gate rejects `.codex-local`, `.tasks`, `.protocols`, caches, `.verify-state`, and confirms wheel and sdist both pass `twine check`. Install smoke reports `package_metadata`/`module_version`/`cli_version_check` agreement from a disposable venv and a pipx install discovered independently of the target interpreter. At task closure, `release_readiness_gate.py --check --json` returned `ok`; the separately executed basic and strict Pyright, public safety, scorecard, docs-drift, architecture, performance budget, and full non-network pytest gates also passed.
