---
slug: AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET
goal: "Generate deterministic public-safe CLI and MCP code-intelligence packet artifacts from a synthetic fixture."
risk: medium
risk_note: "The task exercises real CLI and MCP subprocess surfaces and committed generated artifacts; determinism, cleanup, and public-safety gates must be explicit."
contract_policy:
  flow: full_spdd
  reason: "Standard Autopilot demo task with generated artifacts, real CLI/MCP integration evidence, CI wiring, and public-safety constraints."
  sync_gate: required
  verification_path: automated
files:
  - path: scripts/code_intelligence_packet.py
    change: "Add a deterministic packet generator with --write and --check modes that builds a temporary polyglot fixture, runs real MemPalace CLI commands against a disposable palace, runs one MCP stdio subprocess exhibit, normalizes output, validates known-answer hits, scans rendered output for public-safety, and cleans temp artifacts."
  - path: docs/demo/code-intelligence-packet.md
    change: "Commit the generated human-readable packet with fixture inventory, exact commands/JSON-RPC requests, normalized verbatim CLI output, known-answer search exhibits, source-slice evidence, and one minimal MCP stdio exhibit."
  - path: docs/demo/code-intelligence-packet.json
    change: "Commit the generated machine-readable packet with stable schema, fixture inventory, normalized commands/requests/responses, known-answer assertions, MCP exhibit, and public-safe metadata."
  - path: tests/test_code_intelligence_packet.py
    change: "Add focused tests for output normalization, JSON shape, known-answer miss failure, --check drift detection, public-safety rejection, MCP stdio subprocess use, and temp cleanup."
  - path: scripts/quality_scorecard.py
    change: "Add code-intelligence packet status to the quality scorecard and include the packet check in canonical verification commands."
  - path: tests/test_quality_scorecard.py
    change: "Assert the scorecard reports the packet artifact/check and stays in parity with /verify commands."
  - path: docs/quality/scorecard.md
    change: "Regenerate the committed scorecard after adding the packet metric and verification command."
  - path: docs/quality/scorecard.json
    change: "Regenerate the committed JSON scorecard after adding the packet metric and verification command."
  - path: docs/quality/README.md
    change: "Document how the code-intelligence packet check fits the quality scorecard and regeneration workflow."
  - path: .claude/skills/verify/INSTRUCTIONS.md
    change: "Add the packet --check command to the core /verify table with an explicit timeout."
  - path: .github/workflows/ci.yml
    change: "Run the packet check in CI after the package and runtime dependencies are installed, keeping lint-only scorecard checks stdlib-compatible."
acceptance:
  - id: AC-1
    when: "`python scripts/code_intelligence_packet.py --check` is run"
    then: "it regenerates the synthetic fixture packet in a temp workspace, verifies the committed Markdown and JSON artifacts are fresh, validates public-safety, and exits 0 with a `code-intelligence-packet: OK` summary."
  - id: AC-2
    when: "`python scripts/code_intelligence_packet.py --check` inspects the generated JSON"
    then: "the JSON includes fixture inventory, exact CLI commands, three to five known-answer search exhibits, one source-slice exhibit, and one MCP stdio exhibit covering initialize, code-profile tools/list, and read-only mempalace_code_search."
  - id: AC-3
    when: "`python -m pytest tests/test_code_intelligence_packet.py::test_known_answer_miss_fails_generation -q` is run"
    then: "a deliberately wrong expected symbol or file makes generation fail before artifacts are written."
  - id: AC-4
    when: "`python -m pytest tests/test_code_intelligence_packet.py::test_normalized_output_is_machine_independent -q` is run"
    then: "normalized packet output contains placeholder paths, stable ordering, no timestamps or timings, and rounded or omitted similarity scores."
  - id: AC-5
    when: "`python -m pytest tests/test_code_intelligence_packet.py::test_public_safety_rejects_private_rendered_paths -q` is run"
    then: "rendered Markdown or JSON containing private absolute paths or token-like strings is rejected with a nonzero generator error."
  - id: AC-6
    when: "`python -m pytest tests/test_code_intelligence_packet.py::test_temp_artifacts_are_cleaned_after_generation -q` is run"
    then: "fixture project, disposable palace, temporary MCP config/HOME, and generated comparison outputs are removed after success and after expected failure."
  - id: AC-7
    when: "`python -m pytest tests/test_code_intelligence_packet.py::test_check_mode_detects_committed_artifact_drift -q` is run"
    then: "--check reports stale committed packet artifacts and exits nonzero when regenerated content differs."
  - id: AC-8
    when: "`python scripts/quality_scorecard.py --check` is run"
    then: "the committed scorecard is fresh, public-safe, and reports the code-intelligence packet check as an available verification surface."
out_of_scope:
  - "Backlog metadata edits or archive bookkeeping."
  - "Full CLI golden scenario matrices covered by AUTOPILOT-DEMO-CLI-GOLDEN-SCENARIOS."
  - "Full MCP profile/contract matrices covered by AUTOPILOT-DEMO-MCP-STDIO-CONTRACTS."
  - "Performance budgets, token-savings claims, or benchmark threshold changes."
  - "Changing the default embedding model, storage schema, search ranking policy, or benchmark gate."
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The repo must contain a deterministic public-safe code-intelligence packet in Markdown and JSON."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2, AC-4, AC-5]
    - id: REQ-2
      statement: "Packet evidence must come from real MemPalace CLI command execution against a generated synthetic fixture and disposable palace."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-3
      statement: "Packet evidence must include one real MCP stdio subprocess exhibit, not only direct handler calls."
      source: "backlog acceptance"
      acceptance_ids: [AC-2]
    - id: REQ-4
      statement: "Known-answer query misses must fail generation before artifacts are published."
      source: "backlog acceptance"
      acceptance_ids: [AC-3]
    - id: REQ-5
      statement: "Generated outputs must be machine-independent and public-safe."
      source: "backlog acceptance"
      acceptance_ids: [AC-4, AC-5]
    - id: REQ-6
      statement: "Check mode must detect committed artifact drift and remove temporary generation artifacts."
      source: "backlog acceptance"
      acceptance_ids: [AC-6, AC-7]
    - id: REQ-7
      statement: "The quality scorecard and verification workflow must expose the packet check."
      source: "backlog acceptance"
      acceptance_ids: [AC-8]
  surfaces:
    - name: "packet generator CLI"
      kind: "cli"
      paths: ["scripts/code_intelligence_packet.py"]
      expected_behavior: "Build a synthetic polyglot project in a temporary directory, invoke real `python -m mempalace_code.cli` commands with version checks disabled and deterministic demo embedding isolation, run a scoped MCP stdio subprocess, normalize outputs, validate known-answer hits, and write or check committed artifacts."
    - name: "public packet artifacts"
      kind: "internal"
      paths: ["docs/demo/code-intelligence-packet.md", "docs/demo/code-intelligence-packet.json"]
      expected_behavior: "Expose exact commands/requests and normalized verbatim outputs without private paths, timestamps, secrets, local machine identifiers, or performance claims."
    - name: "packet tests"
      kind: "internal"
      paths: ["tests/test_code_intelligence_packet.py"]
      expected_behavior: "Cover behavior of generator normalization, shape validation, known-answer guard, public-safety guard, stale-artifact check, MCP stdio invocation, and cleanup without relying on external repositories or network."
    - name: "quality scorecard"
      kind: "internal"
      paths: ["scripts/quality_scorecard.py", "tests/test_quality_scorecard.py", "docs/quality/scorecard.md", "docs/quality/scorecard.json", "docs/quality/README.md"]
      expected_behavior: "Report packet artifact/check availability and keep committed scorecard outputs fresh and public-safe."
    - name: "verification wiring"
      kind: "internal"
      paths: [".claude/skills/verify/INSTRUCTIONS.md", ".github/workflows/ci.yml"]
      expected_behavior: "Run the packet check through /verify and CI in an environment with package runtime dependencies installed."
  invariants:
    - id: INV-1
      statement: "The default embedding model remains all-MiniLM-L6-v2 and benchmark gate policy is unchanged; any deterministic demo embedder must be scoped to the packet generator's isolated subprocess environment."
      applies_to: ["scripts/code_intelligence_packet.py", "mempalace_code/storage.py", "CLAUDE.md"]
    - id: INV-2
      statement: "Packet artifacts must not contain absolute local paths, private hostnames, credentials, temp directories, timestamps, timings, or token-like strings."
      applies_to: ["docs/demo/code-intelligence-packet.md", "docs/demo/code-intelligence-packet.json", "scripts/code_intelligence_packet.py"]
    - id: INV-3
      statement: "The task must not expand into full CLI or MCP contract suites; it includes only the packet's minimal command/query/read/MCP exhibits."
      applies_to: ["scripts/code_intelligence_packet.py", "tests/test_code_intelligence_packet.py"]
    - id: INV-4
      statement: "Generated fixture projects and disposable palaces stay temporary and are never committed."
      applies_to: ["scripts/code_intelligence_packet.py", "tests/test_code_intelligence_packet.py"]
    - id: INV-5
      statement: "Existing CLI, MCP, storage, search, and public-safety behavior remains backward compatible."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/mcp_server.py", "mempalace_code/storage.py", "scripts/public_safety_scan.py"]
  risks:
    - id: RISK-1
      risk: "Real CLI output can include temp paths, timings, similarity jitter, or machine-specific formatting that makes committed artifacts drift."
      mitigation: "Normalize path roots to placeholders, strip timing lines, sort exhibits explicitly, and round or omit similarity scores before rendering."
    - id: RISK-2
      risk: "Using direct handler calls would not prove the public CLI/MCP surfaces."
      mitigation: "Run CLI commands through `python -m mempalace_code.cli` subprocesses and MCP through `python -m mempalace_code.mcp_server --profile=code` over stdin/stdout; add tests that fail if subprocess execution is bypassed."
    - id: RISK-3
      risk: "A deterministic demo embedding path could be mistaken for a model benchmark or production search change."
      mitigation: "Keep it inside the generator's temporary subprocess bootstrap, label packet metadata as a deterministic demo fixture, and keep model/ranking code unchanged."
    - id: RISK-4
      risk: "Committed artifacts could leak local paths or secrets from command output."
      mitigation: "Apply the existing rendered public-safety scan to Markdown and JSON before writing, during --check, and in focused rejection tests."
    - id: RISK-5
      risk: "CI packet generation could be too expensive or depend on a missing model cache."
      mitigation: "Use a tiny generated fixture, disable version checks, avoid network, scope deterministic embedding to the generator, and place the CI command after package dependencies are installed."
  verification:
    - id: VER-1
      command: "python scripts/code_intelligence_packet.py --check"
      proves: "committed packet artifacts are fresh, deterministic, public-safe, include real CLI/MCP exhibits, and pass known-answer guards"
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      command: "python -m pytest tests/test_code_intelligence_packet.py::test_known_answer_miss_fails_generation -q"
      proves: "generation fails before writing artifacts when an expected symbol or file is absent from top results"
      acceptance_ids: [AC-3]
    - id: VER-3
      command: "python -m pytest tests/test_code_intelligence_packet.py::test_normalized_output_is_machine_independent -q"
      proves: "normalization removes machine-dependent paths, ordering, timestamps, timings, and unstable score detail"
      acceptance_ids: [AC-4]
    - id: VER-4
      command: "python -m pytest tests/test_code_intelligence_packet.py::test_public_safety_rejects_private_rendered_paths -q"
      proves: "public-safety rules reject unsafe rendered Markdown or JSON before publish"
      acceptance_ids: [AC-5]
    - id: VER-5
      command: "python -m pytest tests/test_code_intelligence_packet.py::test_temp_artifacts_are_cleaned_after_generation -q"
      proves: "successful and expected-failure generation leaves no fixture project, palace, temp HOME, MCP config, or comparison artifacts behind"
      acceptance_ids: [AC-6]
    - id: VER-6
      command: "python -m pytest tests/test_code_intelligence_packet.py::test_check_mode_detects_committed_artifact_drift -q"
      proves: "--check fails when regenerated packet content differs from committed artifacts"
      acceptance_ids: [AC-7]
    - id: VER-7
      command: "python scripts/quality_scorecard.py --check"
      proves: "the committed scorecard is fresh, public-safe, deterministic, and includes the packet verification surface"
      acceptance_ids: [AC-8]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_cli.py tests/test_mcp_server.py tests/test_stdio.py -q"
        proves: "existing CLI dispatch, MCP handler behavior, and stdio transport behavior remain stable while the packet adds only focused subprocess exhibits"
        acceptance_ids: [AC-1, AC-2]
      - id: REG-2
        command: "python -m pytest tests/test_code_intelligence_packet.py tests/test_quality_scorecard.py -q"
        proves: "new generator behavior and scorecard wiring are covered together"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-3
        command: "ruff check scripts/code_intelligence_packet.py tests/test_code_intelligence_packet.py scripts/quality_scorecard.py tests/test_quality_scorecard.py"
        proves: "new and touched Python files are lint-clean"
        acceptance_ids: [AC-1, AC-8]
      - id: REG-4
        command: "ruff format --check scripts/code_intelligence_packet.py tests/test_code_intelligence_packet.py scripts/quality_scorecard.py tests/test_quality_scorecard.py"
        proves: "new and touched Python files are formatted"
        acceptance_ids: [AC-1, AC-8]
      - id: REG-5
        command: "python scripts/public_safety_scan.py --tracked --staged"
        proves: "tracked and staged public files, including generated demo artifacts, contain no private local paths or token-like strings"
        acceptance_ids: [AC-5]
---

## Design Notes

- Keep the packet generator under `scripts/` with `--write`, `--check`, and optional `--out-dir` for tests. `--write` writes only the committed packet paths by default; `--check` regenerates in a temporary directory and compares exact Markdown/JSON content against the committed artifacts.
- Build the fixture project entirely at runtime. Use stable relative file names such as `src/orchestrator.py`, `web/router.ts`, `cmd/worker.go`, `docs/architecture.md`, and `README.md`; include unique identifiers in each target symbol so known-answer checks can assert exact file/symbol hits.
- Write a `mempalace.yaml` into the generated fixture instead of relying on interactive init. The packet can still include mine/status/search/read CLI output as the "real CLI output" surface; full init workflow coverage belongs to adjacent CLI golden-scenario work.
- Invoke CLI exhibits as subprocesses through `python -m mempalace_code.cli`, not imported functions. Set `MEMPALACE_VERSION_CHECK=0`, isolated `HOME`/`USERPROFILE`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `MEMPALACE_OPTIMIZE_AFTER_MINE=0`, and a disposable palace path.
- To keep normal CI offline and deterministic, scope any deterministic demo embedder to the generator's temporary subprocess bootstrap. Do not change the default storage model or public model policy. Mark packet metadata clearly so the artifacts are code-intelligence exhibits, not embedding benchmark claims.
- Normalize command output before rendering: replace temp project/palace/home roots with placeholders, remove `Time:` and embedding batch duration fields, sort inventory and result rows where the source surface is unordered, and either round similarity to a stable precision or omit it from assertions.
- Known-answer checks should fail on both file and symbol expectations. Each query should assert the expected hit appears in the top result set and record the matched `source_file`, `symbol_name`, `symbol_type`, and `language` in JSON.
- Use one source-slice exhibit from the public CLI `read` command, choosing a stable function/class range from the fixture. The packet should show the exact command and the normalized output.
- Start the MCP exhibit with `python -m mempalace_code.mcp_server --profile=code`, send newline-delimited JSON-RPC requests for `initialize`, `tools/list`, and `tools/call` using read-only `mempalace_code_search`, then terminate by closing stdin and waiting with a timeout.
- The MCP exhibit should assert that `tools/list` includes `mempalace_code_search` and omits write-oriented tools such as `mempalace_add_drawer` under the code profile. Keep this to one minimal exhibit so it does not duplicate the full MCP contracts backlog item.
- Reuse `scripts/public_safety_scan.py` rendered-text rules from the generator instead of duplicating regexes. The generator should scan both Markdown and JSON before printing/writing and should report rule ids without echoing unsafe matched text.
- Update scorecard wiring after the packet artifacts exist: add the packet check to `_VERIFICATION_COMMANDS`, add a packet artifact/check metric or suite entry, update `docs/quality/scorecard.*`, and keep `tests/test_quality_scorecard.py::test_verification_commands_match_verify_skill` passing by adding the same command to `/verify`.
- CI should run `python scripts/code_intelligence_packet.py --check` in a job step after `pip install -e ".[dev,treesitter]"`, not in the lint job that intentionally installs only Ruff for stdlib-only checks.
