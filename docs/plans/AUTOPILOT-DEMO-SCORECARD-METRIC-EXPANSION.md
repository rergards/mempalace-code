---
slug: AUTOPILOT-DEMO-SCORECARD-METRIC-EXPANSION
goal: "Expand the deterministic quality scorecard with public-demo gate metrics."
risk: medium
risk_note: "The change is stdlib-only and localized, but it bumps a CI-gated generated artifact schema and must preserve byte-identical output."
files:
  - path: scripts/quality_scorecard.py
    change: "Add strict-slice, public-safety coverage, and optional demo-gate collectors; render and validate the new schema deterministically."
  - path: tests/test_quality_scorecard.py
    change: "Cover new metrics, absent optional gates, malformed metric validation, and committed artifact freshness, plus a test asserting mcp_stdio_contracts equals the TestMCPStdioContracts method count in tests/test_mcp_server.py and a test that demo-gate collectors spawn no subprocess on the absent-gate path."
  - path: docs/quality/README.md
    change: "Define every new metric and how demo tasks should cite before/after deltas."
  - path: docs/quality/scorecard.json
    change: "Regenerate machine-readable scorecard output with the expanded metrics."
  - path: docs/quality/scorecard.md
    change: "Regenerate human-readable scorecard output with the expanded metrics."
acceptance:
  - id: AC-1
    when: "python scripts/quality_scorecard.py --format json is run in the current repository"
    then: "the JSON includes strict-slice file_count and sorted paths from pyrightconfig.strict.json, and includes tracked, staged, and committed public-safety scan modes"
  - id: AC-2
    when: "the JSON scorecard is inspected in the current repository"
    then: "demo gate metrics report dependency audit as present, MCP stdio contract count (sourced from the TestMCPStdioContracts suite in tests/test_mcp_server.py) as greater than zero, and architecture/docs-drift/CLI-golden gates with deterministic absent-or-present status"
  - id: AC-3
    when: "scorecard validation receives a malformed expanded metric shape such as a missing committed public-safety mode or non-integer scenario count"
    then: "validation fails with an actionable shape error instead of silently accepting the output"
  - id: AC-4
    when: "optional demo-gate scripts or suites are absent from the repository"
    then: "the scorecard still renders deterministic public-safe output with absent status and without running heavyweight demo generation, network calls, tests, or subprocess gates"
  - id: AC-5
    when: "python scripts/quality_scorecard.py --check is run after regenerating docs/quality artifacts"
    then: "the check validates schema shape, deterministic JSON, public-safety, and freshness of the committed Markdown and JSON artifacts"
  - id: AC-6
    when: "docs/quality/README.md is inspected"
    then: "it defines strict-slice, public-safety coverage, demo-gate, and dependency-audit scorecard metrics plus citation guidance for future demo deltas"
out_of_scope:
  - "Implementing the architecture guard, CLI golden scenario suite, docs drift guard, or performance budget gate."
  - "Changing CI workflows, /verify command lists, release gate behavior, or dependency audit logic."
  - "Running model-backed code-intelligence packet generation as part of scorecard --check."
  - "Editing backlog metadata or backlog archives."
contract_policy:
  flow: full_spdd
  reason: "Standard Autopilot demo task changes a CI-gated public artifact and its behavioral validation contract."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The scorecard must expose strict Pyright slice count and paths from pyrightconfig.strict.json."
      source: "backlog acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The scorecard must expose public-safety scan coverage for tracked, staged, and committed-tree modes."
      source: "backlog acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-3
      statement: "The scorecard must expose deterministic public-demo gate metrics for optional architecture, CLI golden, MCP stdio, docs drift, and dependency audit gates."
      source: "backlog acceptance"
      acceptance_ids: [AC-2, AC-4]
    - id: REQ-4
      statement: "Malformed expanded scorecard sections must be rejected by validation."
      source: "AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-5
      statement: "Generated scorecard artifacts and README definitions must stay fresh, public-safe, and usable as before/after evidence."
      source: "backlog acceptance"
      acceptance_ids: [AC-5, AC-6]
  surfaces:
    - name: "quality scorecard generator"
      kind: internal
      paths: ["scripts/quality_scorecard.py"]
      expected_behavior: "Build expanded stdlib-only metrics from repo-local config, scripts, tests, and docs; never call network, model-backed, or heavyweight verification commands."
    - name: "quality scorecard tests"
      kind: internal
      paths: ["tests/test_quality_scorecard.py"]
      expected_behavior: "Assert success, absent-gate edge cases, malformed-shape failure paths, and artifact freshness for the expanded schema."
    - name: "quality scorecard docs"
      kind: internal
      paths: ["docs/quality/README.md", "docs/quality/scorecard.json", "docs/quality/scorecard.md"]
      expected_behavior: "Document and publish the expanded public-safe scorecard metrics in generated Markdown and JSON."
  invariants:
    - id: INV-1
      statement: "Scorecard output remains deterministic, timestamp-free, absolute-path-free, and public-safe."
      applies_to: ["scripts/quality_scorecard.py", "docs/quality/scorecard.json", "docs/quality/scorecard.md"]
    - id: INV-2
      statement: "scripts/quality_scorecard.py remains stdlib-only and does not import mempalace_code or require package installation."
      applies_to: ["scripts/quality_scorecard.py"]
    - id: INV-3
      statement: "The scorecard check remains a cheap shape/freshness/public-safety gate and does not execute heavyweight demo packet generation or model-backed checks."
      applies_to: ["scripts/quality_scorecard.py"]
    - id: INV-4
      statement: "Existing verification_commands stay verbatim-identical to .claude/skills/verify/INSTRUCTIONS.md unless a separate verify/CI task changes that contract."
      applies_to: ["scripts/quality_scorecard.py", ".claude/skills/verify/INSTRUCTIONS.md"]
  risks:
    - id: RISK-1
      risk: "Schema expansion could make committed docs/quality artifacts stale and fail CI."
      mitigation: "Bump schema deliberately, regenerate scorecard.md/json, and keep --check plus freshness tests as verification gates."
    - id: RISK-2
      risk: "Optional future gates could be confused with required current gates."
      mitigation: "Use explicit present/status/count fields and document absent status as a baseline metric, not a release blocker."
    - id: RISK-3
      risk: "Parsing gate status from source text could be brittle."
      mitigation: "Prefer stable file/config presence and AST test-function counting over ad hoc prose scraping."
  verification:
    - id: VER-1
      command: >-
        python -c 'import json, subprocess, sys; data=json.loads(subprocess.check_output([sys.executable,"scripts/quality_scorecard.py","--format","json"])); strict=data["pyright"]["strict_slice"]; assert strict["file_count"] == len(strict["paths"]) and "mempalace_code/disk_budget.py" in strict["paths"]; public=data["public_safety"]; assert {"tracked","staged","committed"} <= set(public["modes"])'
      proves: "Rendered JSON exposes strict-slice and all public-safety modes from the current repo config and scan script."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: >-
        python -c 'import ast, json, subprocess, sys; data=json.loads(subprocess.check_output([sys.executable,"scripts/quality_scorecard.py","--format","json"])); gates=data["demo_gates"]; assert gates["dependency_audit"]["status"] == "present"; tree=ast.parse(open("tests/test_mcp_server.py", encoding="utf-8").read()); cls=next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "TestMCPStdioContracts"); expected=sum(1 for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test")); assert gates["mcp_stdio_contracts"]["count"] == expected > 0; assert "architecture_guard" in gates and "docs_drift_guard" in gates and "cli_golden_scenarios" in gates'
      proves: "Rendered JSON reports current and absent optional demo gate metrics deterministically, and the MCP stdio contract count is sourced from the TestMCPStdioContracts suite (not the test_stdio.py transport helpers, which would yield a different count)."
      acceptance_ids: [AC-2, AC-4]
    - id: VER-3
      command: >-
        python -m pytest tests/test_quality_scorecard.py -q -k "strict_slice or public_safety_modes or demo_gates or mcp_stdio_contract or malformed_expanded_metric or no_subprocess"
      proves: "Focused unit tests cover new collectors, the class-scoped MCP stdio contract count equalling the TestMCPStdioContracts method count, malformed-shape failure behavior, and the no-subprocess absent-gate path."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-4
      command: "python scripts/quality_scorecard.py --check"
      proves: "The expanded scorecard remains deterministic, public-safe, and in sync with committed artifacts."
      acceptance_ids: [AC-5]
    - id: VER-5
      command: >-
        python -c 'from pathlib import Path; text=Path("docs/quality/README.md").read_text(encoding="utf-8"); required=["Strict slice","Public-safety scan coverage","Demo gates","dependency audit"]; missing=[term for term in required if term not in text]; assert not missing, missing'
      proves: "README definitions cover the new metric families and citation guidance."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_quality_scorecard.py -q"
        proves: "Existing and new scorecard unit tests still pass, including deterministic rendering, public-safety, validation, and artifact freshness."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
      - id: REG-2
        command: "python scripts/quality_scorecard.py --check"
        proves: "The generated artifacts remain fresh after the schema expansion."
        acceptance_ids: [AC-5]
---

## Design Notes

- Command context basis: this repo is a Python project with pytest configured in `pyproject.toml`; existing scorecard tests load `scripts/quality_scorecard.py` directly and verify committed artifact freshness, so focused verification can stay in `tests/test_quality_scorecard.py`.
- Keep the new collectors pure functions of tracked repository files: `pyrightconfig.strict.json`, `scripts/public_safety_scan.py`, known script/test/workflow paths, and generated `docs/quality` artifacts.
- Bump `SCHEMA_VERSION` because the machine-readable `scorecard.json` shape changes.
- Add a `pyright.strict_slice` object rather than replacing the existing top-level Pyright mode fields. Include sorted `paths`, `file_count`, and whether `include` and `strict` arrays match.
- Add a top-level `public_safety` object with supported modes and command strings for `tracked`, `staged`, and `committed`; this is metadata coverage only and must not execute the scan during normal rendering.
- Add a top-level `demo_gates` object with stable keys:
  - `architecture_guard`: status based on the future guard script/config path.
  - `cli_golden_scenarios`: count from a future golden scenario test file when present, otherwise absent with count 0.
  - `mcp_stdio_contracts`: count of `test*` methods in the `TestMCPStdioContracts` class in `tests/test_mcp_server.py` — the MCP stdio *contract* suite landed by AUTOPILOT-DEMO-MCP-STDIO-CONTRACTS (currently 5). Do **not** source this from `tests/test_stdio.py`: that file is the Windows UTF-8 stdio transport-helper suite (9 functions, mostly stream reconfigure/encoding) and is already tracked separately as the `mcp_stdio` entry in `_KNOWN_SUITES` (scripts/quality_scorecard.py:79). Counting it would report a semantically wrong number that still passes a bare `count > 0` check.
  - `docs_drift_guard`: status based on the future docs drift guard script/test path.
  - `dependency_audit`: status based on `scripts/dependency_upgrade_gate.py` and `.github/workflows/dependency-audit.yml`.
- For counts, reuse the existing AST-based test-function counting where it fits (whole-file `test*` functions via `_count_test_functions`, scripts/quality_scorecard.py:280). That helper counts every `test*` function in a file, so it would over-count the hundreds of tests in `test_mcp_server.py`; add a small class-scoped AST counter (count `test*` methods inside a named `ClassDef`) and use it for `mcp_stdio_contracts`. Avoid string matching on test names.
- Do not add heavyweight checks to `run_check`; it should continue to build twice, validate shape, scan rendered output, and compare committed artifacts.
- `docs/quality/scorecard.md` should add compact sections rather than duplicating long command output; the JSON remains the detailed machine source.
- To make the AC-4 / INV-3 no-subprocess guarantee observable (not just documented), add a unit test that the demo-gate collectors perform only file-presence and AST reads — e.g. monkeypatch `subprocess.run` / `subprocess.check_output` / `subprocess.Popen` to raise and assert rendering still succeeds with deterministic absent-or-present output.
