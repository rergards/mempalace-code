---
slug: AUTOPILOT-DEMO-CODE-INTELLIGENCE-PACKET-ACCEPTANCE-FIX
goal: "Close the code-intelligence packet owner-acceptance gaps with durable public-safe evidence, focused lint cleanup, and explicit manual-gate wording."
risk: medium
risk_note: "The task touches generated public artifacts, a generator script, task evidence, and public-safety boundaries; scope is constrained to the existing packet and focused checks."
files:
  - path: docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET.md
    change: "Replace the fallback backlog-recovery stub with a real durable plan for the shipped golden-packet work, including final scope, files touched, design notes, verification, and out-of-scope boundaries."
  - path: docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md
    change: "Add a public-safe durable synthesis of the prior plan-review evidence and fix decisions so evidence no longer exists only in worktree logs or a local-only audit path."
  - path: docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-round-1.md
    change: "Remove the tracked local-only audit artifact after its public-safe content is relocated to docs/task-evidence/."
  - path: scripts/gen_code_intelligence_packet.py
    change: "Add generated owner-acceptance checklist metadata/rendering, require exact MCP request/response pairing with B905-safe zip usage, and reword or encode self-referential token-pattern examples without weakening public-safety checks."
  - path: tests/test_code_intelligence_packet.py
    change: "Add focused tests for owner checklist visibility, JSON/Markdown parity, MCP provenance, missing-checklist failure, exact MCP response count handling, and unchanged public-safety rejection behavior."
  - path: docs/demo/code-intelligence-packet.json
    change: "Regenerate from the generator so the committed JSON includes the owner-acceptance checklist and remains normalized, deterministic, and public-safe."
  - path: docs/demo/code-intelligence-packet.md
    change: "Regenerate from the generator so the Markdown exposes the same owner-acceptance checklist and MCP provenance visible in JSON."
  - path: scripts/quality_scorecard.py
    change: "Clarify the code-intelligence suite description if needed so the scorecard names packet utility/check coverage without implying generator --check is wired into /verify or daily CI."
  - path: docs/quality/README.md
    change: "Reconcile quality docs around packet-check wiring: generator --check remains a manual pre-release gate, while scorecard/verify only cover the focused utility tests and scorecard freshness."
  - path: docs/quality/scorecard.json
    change: "Regenerate after test/doc wording changes so the committed scorecard JSON is fresh and deterministic."
  - path: docs/quality/scorecard.md
    change: "Regenerate alongside scorecard.json so the human-readable scorecard matches the updated repo shape and wording."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_code_intelligence_packet.py::TestOwnerAcceptanceChecklist::test_committed_packet_artifacts_expose_owner_acceptance_checklist -q` is run"
    then: "the committed JSON and Markdown artifacts both show checklist evidence for fixture determinism, JSON/Markdown parity, and MCP stdio provenance"
  - id: AC-2
    when: "`python scripts/gen_code_intelligence_packet.py --check` is run after the artifacts are regenerated"
    then: "the command exits zero, proving fresh generation matches the committed JSON and Markdown artifacts without changing the demo fixture or packet scope"
  - id: AC-3
    when: "`python -m pytest tests/test_code_intelligence_packet.py::TestOwnerAcceptanceChecklist::test_schema_rejects_missing_owner_acceptance_checklist -q` is run"
    then: "packet validation fails with a clear checklist-related error when the owner-acceptance checklist is absent"
  - id: AC-4
    when: "`python -m pytest tests/test_code_intelligence_packet.py::TestMcpExchangeValidation::test_raises_on_extra_mcp_response -q` is run"
    then: "an MCP stdio exchange with more responses than requests fails instead of silently pairing only the first three responses"
  - id: AC-5
    when: "`ruff check scripts/gen_code_intelligence_packet.py tests/test_code_intelligence_packet.py` is run"
    then: "the focused generator/test lint check exits zero, including the B905 zip strictness issue in the MCP request/response pairing loop"
  - id: AC-6
    when: "`python -m pytest tests/test_code_intelligence_packet.py -x -q` is run"
    then: "the packet utility test slice passes across normalization, known-answer validation, schema failure paths, public-safety guards, renderer parity, and MCP subprocess error handling"
  - id: AC-7
    when: "`python -c 'from pathlib import Path; p=Path(\"docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET.md\"); e=Path(\"docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md\"); a=Path(\"docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-round-1.md\"); text=p.read_text(encoding=\"utf-8\"); ev=e.read_text(encoding=\"utf-8\"); assert \"fallback: backlog-recovery\" not in text; assert \"files:\" in text and \"verification\" in text; assert \"F-1\" in ev and \"F-2\" in ev; assert not a.exists()'` is run"
    then: "the old fallback plan is replaced, public-safe review evidence is present, and the tracked local-only audit artifact for this task is gone"
  - id: AC-8
    when: "`python scripts/quality_scorecard.py --check` is run"
    then: "quality scorecard artifacts are fresh, deterministic, and public-safe after the packet test and wording changes"
  - id: AC-9
    when: "`python -c 'import subprocess, sys; p=subprocess.run([\"python\", \"scripts/public_safety_scan.py\", \"--tracked\"], text=True, capture_output=True); out=p.stdout+p.stderr; print(out, end=\"\"); needles=(\"tracked:docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE\", \"tracked:docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET\", \"tracked:docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE\", \"tracked:scripts/gen_code_intelligence_packet.py\"); sys.exit(1 if any(n in out for n in needles) else 0)'` is run"
    then: "the tracked public-safety scan output has no findings on this task's owned surfaces (path-anchored to docs/plans, docs/audits, docs/task-evidence, and scripts/gen_code_intelligence_packet.py); pre-existing tracked .tasks/ phase artifacts and any other nonzero scan output are explicitly outside this task"
  - id: AC-10
    when: "`ruff format --check scripts/gen_code_intelligence_packet.py tests/test_code_intelligence_packet.py` is run"
    then: "the focused generator and packet tests are formatted under the repo's Ruff formatter"
out_of_scope:
  - "Generating a new demo fixture, changing known-answer query intent, changing packet exhibit scope, or adding new MCP/CLI demo surfaces."
  - "Wiring `python scripts/gen_code_intelligence_packet.py --check` into `/verify`, daily CI, or new docs-drift automation."
  - "Changing public-safety scanner rules to weaken detection, adding committed-tree scan mode, or remediating unrelated repo-wide public-safety findings."
  - "Editing docs/BACKLOG.yaml, docs/BACKLOG-archived.yaml, or bookkeep-owned task-resolution metadata."
  - "Broad scorecard expansion beyond freshness and wording required by this packet acceptance fix."
contract_policy:
  flow: full_spdd
  reason: "Standard provider task crossing generated artifacts, public evidence, lint gates, and public-safety boundaries."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The old fallback golden-packet plan must become a durable plan that reflects the shipped design, files touched, verification, and final scope."
      source: "backlog acceptance"
      acceptance_ids: [AC-7]
    - id: REQ-2
      statement: "Prior plan-review evidence must be committed as a durable public-safe artifact outside local-only audit paths."
      source: "backlog acceptance"
      acceptance_ids: [AC-7, AC-9]
    - id: REQ-3
      statement: "The packet artifacts must expose owner-facing checklist evidence for fixture determinism, JSON/Markdown parity, and MCP exhibit provenance."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: REQ-4
      statement: "The generator must pass focused Ruff lint/format checks, including B905-safe exact pairing for MCP request/response validation, without changing packet behavior beyond rejecting malformed extra responses."
      source: "backlog acceptance"
      acceptance_ids: [AC-4, AC-5, AC-10]
    - id: REQ-5
      statement: "Quality docs and scorecard wording must consistently describe generator --check as a manual pre-release gate, not as daily CI or /verify wiring."
      source: "backlog acceptance and quality docs"
      acceptance_ids: [AC-8]
    - id: REQ-6
      statement: "Focused verification must record generator check, packet tests, quality scorecard check, Ruff lint/format checks, and a public-safety boundary showing no task-specific findings."
      source: "backlog acceptance"
      acceptance_ids: [AC-2, AC-5, AC-6, AC-8, AC-9, AC-10]
  surfaces:
    - name: "Golden-packet plan and evidence"
      kind: internal
      paths:
        - "docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET.md"
        - "docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md"
        - "docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-round-1.md"
      expected_behavior: "Replace the fallback stub, relocate the fixed review findings into a public-safe evidence file, and remove this task's tracked local-only audit artifact."
    - name: "Packet generator"
      kind: cli
      paths: ["scripts/gen_code_intelligence_packet.py"]
      expected_behavior: "Generate the same deterministic fixture and exhibits, add owner checklist metadata/rendering, keep public-safety rejection intact, and reject MCP response-count mismatches with strict request/response pairing."
    - name: "Packet tests"
      kind: internal
      paths: ["tests/test_code_intelligence_packet.py"]
      expected_behavior: "Prove checklist visibility, missing-checklist failure, JSON/Markdown parity, MCP provenance, public-safety behavior, and exact MCP response-count handling without running the full mining pipeline in unit tests."
    - name: "Committed packet artifacts"
      kind: internal
      paths:
        - "docs/demo/code-intelligence-packet.json"
        - "docs/demo/code-intelligence-packet.md"
      expected_behavior: "Remain generated from the script and now show the owner checklist in both JSON and Markdown while retaining normalized paths and no timestamps."
    - name: "Quality docs and scorecard"
      kind: internal
      paths:
        - "scripts/quality_scorecard.py"
        - "docs/quality/README.md"
        - "docs/quality/scorecard.json"
        - "docs/quality/scorecard.md"
      expected_behavior: "Keep scorecard artifacts fresh and wording aligned: packet utility tests are part of scorecard/verify, generator --check remains a manual pre-release gate."
  invariants:
    - id: INV-1
      statement: "The demo fixture files, known-answer query catalog intent, search/read/MCP exhibit scope, and normalized public output remain unchanged except for added owner checklist metadata/rendering."
      applies_to:
        - "scripts/gen_code_intelligence_packet.py"
        - "docs/demo/code-intelligence-packet.json"
        - "docs/demo/code-intelligence-packet.md"
    - id: INV-2
      statement: "Generator --check is not wired into /verify, daily CI, or a new docs-drift guard by this task."
      applies_to:
        - "scripts/quality_scorecard.py"
        - "docs/quality/README.md"
        - "docs/quality/scorecard.json"
        - "docs/quality/scorecard.md"
    - id: INV-3
      statement: "Public-safety scanner rules remain at least as strict as before; token/path examples are rewritten or encoded rather than allowlisted."
      applies_to:
        - "scripts/gen_code_intelligence_packet.py"
        - "tests/test_code_intelligence_packet.py"
    - id: INV-4
      statement: "Backlog metadata and archive files stay bookkeep-owned and are not edited during implementation."
      applies_to:
        - "docs/BACKLOG.yaml"
        - "docs/BACKLOG-archived.yaml"
    - id: INV-5
      statement: "All committed evidence and packet artifacts remain public-safe: no private paths, local artifact directories, hostnames, credentials, or raw secret-like sample tokens."
      applies_to:
        - "docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md"
        - "docs/demo/code-intelligence-packet.json"
        - "docs/demo/code-intelligence-packet.md"
  risks:
    - id: RISK-1
      risk: "Hand-editing generated packet artifacts could make JSON and Markdown drift."
      mitigation: "Add checklist data in the generator, regenerate both artifacts, and use generator --check plus artifact visibility tests as the authority."
    - id: RISK-2
      risk: "Relocated review evidence could still trip public-safety rules through local-only paths or raw token examples."
      mitigation: "Use a publishable docs/task-evidence path, delete this task's docs/audits file, and verify tracked scan output contains no task-specific hits."
    - id: RISK-3
      risk: "Fixing B905 with strict zip could hide or misclassify MCP extra-response behavior."
      mitigation: "Assert exact response count and add a focused extra-response failure test before pairing requests and responses."
    - id: RISK-4
      risk: "Docs could imply generator --check is automated in /verify or daily CI, recreating owner confusion."
      mitigation: "Keep quality README and scorecard wording explicit that utility tests are automated but full packet regeneration/check remains a manual pre-release gate."
    - id: RISK-5
      risk: "Public-safety cleanup could expand into unrelated tracked docs/audits findings."
      mitigation: "Only remove or relocate this task's evidence artifact and use a boundary command that fails on task-specific scan hits while recording unrelated findings separately."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_code_intelligence_packet.py::TestOwnerAcceptanceChecklist::test_committed_packet_artifacts_expose_owner_acceptance_checklist -q"
      proves: "Committed packet JSON and Markdown visibly expose owner checklist evidence for determinism, parity, and MCP provenance."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python scripts/gen_code_intelligence_packet.py --check"
      proves: "Fresh generator output matches committed docs/demo/code-intelligence-packet.{json,md}; this command is intentionally a manual pre-release gate rather than a /verify command."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_code_intelligence_packet.py::TestOwnerAcceptanceChecklist::test_schema_rejects_missing_owner_acceptance_checklist -q"
      proves: "The error path rejects packets that omit the owner checklist instead of silently passing incomplete evidence."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_code_intelligence_packet.py::TestMcpExchangeValidation::test_raises_on_extra_mcp_response -q"
      proves: "The MCP boundary rejects extra response envelopes before request/response pairing."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "ruff check scripts/gen_code_intelligence_packet.py tests/test_code_intelligence_packet.py"
      proves: "Focused lint passes, including B905 strict zip coverage on the generator's MCP pairing loop."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_code_intelligence_packet.py -x -q"
      proves: "The focused packet test slice passes across success, failure, and boundary behavior without running a repo-wide suite."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -c 'from pathlib import Path; p=Path(\"docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET.md\"); e=Path(\"docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md\"); a=Path(\"docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-round-1.md\"); text=p.read_text(encoding=\"utf-8\"); ev=e.read_text(encoding=\"utf-8\"); assert \"fallback: backlog-recovery\" not in text; assert \"files:\" in text and \"verification\" in text; assert \"F-1\" in ev and \"F-2\" in ev; assert not a.exists()'"
      proves: "The durable plan/evidence artifacts exist in public-safe locations and this task's local-only audit file is absent."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "python scripts/quality_scorecard.py --check"
      proves: "Scorecard output is fresh, deterministic, and public-safe after the test and wording changes."
      acceptance_ids: [AC-8]
    - id: VER-9
      command: "python -c 'import subprocess, sys; p=subprocess.run([\"python\", \"scripts/public_safety_scan.py\", \"--tracked\"], text=True, capture_output=True); out=p.stdout+p.stderr; print(out, end=\"\"); needles=(\"tracked:docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE\", \"tracked:docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET\", \"tracked:docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE\", \"tracked:scripts/gen_code_intelligence_packet.py\"); sys.exit(1 if any(n in out for n in needles) else 0)'"
      proves: "Tracked public-safety output contains no findings on this task's owned docs/scripts surfaces; the path-anchored needles cannot be tripped by pre-existing tracked .tasks/ phase artifacts, and unrelated pre-existing findings are documented separately."
      acceptance_ids: [AC-9]
    - id: VER-10
      command: "ruff format --check scripts/gen_code_intelligence_packet.py tests/test_code_intelligence_packet.py"
      proves: "Focused generator and packet tests satisfy the repo formatter."
      acceptance_ids: [AC-10]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_code_intelligence_packet.py -x -q"
        proves: "All focused packet generator utility behavior remains stable after checklist, public-safety, and MCP pairing changes."
        acceptance_ids: [AC-1, AC-3, AC-4, AC-6]
      - id: REG-2
        command: "python scripts/gen_code_intelligence_packet.py --check"
        proves: "The committed packet artifacts stay in sync with the generator after regeneration."
        acceptance_ids: [AC-2]
      - id: REG-3
        command: "ruff check scripts/gen_code_intelligence_packet.py tests/test_code_intelligence_packet.py"
        proves: "Focused lint remains clean on the changed generator/test slice."
        acceptance_ids: [AC-5]
      - id: REG-4
        command: "ruff format --check scripts/gen_code_intelligence_packet.py tests/test_code_intelligence_packet.py"
        proves: "Focused formatting remains clean on the changed generator/test slice."
        acceptance_ids: [AC-10]
      - id: REG-5
        command: "python scripts/quality_scorecard.py --check"
        proves: "Quality scorecard artifacts remain fresh and public-safe after test count or suite-description changes."
        acceptance_ids: [AC-8]
      - id: REG-6
        command: "python -c 'import subprocess, sys; p=subprocess.run([\"python\", \"scripts/public_safety_scan.py\", \"--tracked\"], text=True, capture_output=True); out=p.stdout+p.stderr; print(out, end=\"\"); needles=(\"tracked:docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE\", \"tracked:docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET\", \"tracked:docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE\", \"tracked:scripts/gen_code_intelligence_packet.py\"); sys.exit(1 if any(n in out for n in needles) else 0)'"
        proves: "This task's public-safety footprint stays absent from tracked scan output on its owned docs/scripts surfaces; pre-existing tracked .tasks/ artifacts and other unrelated findings are not remediated here."
        acceptance_ids: [AC-9]
      - id: REG-7
        command: "python -c 'from pathlib import Path; p=Path(\"docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET.md\"); e=Path(\"docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md\"); a=Path(\"docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-round-1.md\"); text=p.read_text(encoding=\"utf-8\"); ev=e.read_text(encoding=\"utf-8\"); assert \"fallback: backlog-recovery\" not in text; assert \"files:\" in text and \"verification\" in text; assert \"F-1\" in ev and \"F-2\" in ev; assert not a.exists()'"
        proves: "The durable plan/evidence artifacts and audit-file removal remain stable across regression: the fallback stub stays replaced, public-safe review evidence stays present, and the local-only audit file stays gone."
        acceptance_ids: [AC-7]
---

## Design Notes

- Command context basis: this repo is a root-level Python package with `pyproject.toml` declaring pytest/Ruff config and no package subdirectory workspace. Verification commands therefore run from the repo root with `python`, `ruff`, and direct script paths, matching `.claude/skills/verify/INSTRUCTIONS.md` for core checks while keeping this plan focused.
- Add the owner checklist to the generator's packet data model, then render it into Markdown from the same object. Do not hand-edit `docs/demo/code-intelligence-packet.{json,md}` except through generator output.
- Checklist rows should be stable, short, and artifact-oriented: fixture determinism, JSON/Markdown parity, and MCP stdio provenance. Each row should cite the packet section or JSON keys an owner can inspect after the fact.
- Keep `validate_packet_schema()` responsible for required checklist shape and ids so missing checklist data is a real failure path, not just Markdown polish.
- For JSON/Markdown parity, tests should read committed artifacts and assert the same checklist ids appear in both. This proves the reviewer-facing Markdown and machine artifact carry the same acceptance contract.
- For MCP provenance, preserve the existing three request/response exhibits (`initialize`, `tools/list`, `tools/call`) and assert the method/tool names are visible. The B905 fix should first assert `len(responses) == len(requests)`, then use `zip(..., strict=True)`.
- Do not change the demo fixture files, known-answer query catalog, search/read commands, MCP profile, or model policy. Any generated packet diffs should be limited to the owner checklist and deterministic formatting caused by the generator.
- Move the existing fixed-review content from `docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-round-1.md` into `docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET-review.md`, then delete the tracked `docs/audits/` file for this task. `docs/audits/` is ignored and the public-safety scanner treats it as local-only.
- Reword raw token-pattern examples in comments/tests/evidence with safe split strings or neutral names; do not relax `_SECRET_TOKEN_RE`, `_PRIVATE_PATH_RE`, or repository public-safety scanner rules.
- Quality wording should make the boundary explicit: `tests/test_code_intelligence_packet.py` is automated scorecard/verify coverage, while `python scripts/gen_code_intelligence_packet.py --check` remains a manual pre-release gate because it needs cached embeddings and is slower.
- Backlog archive and task-resolution metadata are intentionally not implementation files. If bookkeep later archives this task, it should use the plan/evidence/verification output from this task, but implementation must not edit `docs/BACKLOG.yaml` or `docs/BACKLOG-archived.yaml`.
- The public-safety command in AC-9/VER-9 intentionally asserts absence of this task's findings rather than full repo success. Its needles are path-anchored to this task's owned surfaces (`tracked:docs/plans/AUTOPILOT-DEMO-CODE-INTELLIGENCE`, `tracked:docs/audits/AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET`, `tracked:docs/task-evidence/AUTOPILOT-DEMO-CODE-INTELLIGENCE`, `tracked:scripts/gen_code_intelligence_packet.py`) rather than bare task slugs. This is required because the prior task's `.tasks/TASK-AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET/harden-*.json` artifacts are already tracked and flagged as `local-only-artifact-path`, and this task's own `.tasks/` phase artifacts may be committed during the flow; a bare-slug needle would self-trip on those. The anchored needles still catch the real targets: today the scan flags `docs/audits/...-round-1.md` (github-pat-prefix + local-only-artifact-path) and `scripts/gen_code_intelligence_packet.py:385` (github-pat-prefix), so the command exits nonzero now and exits zero only after the audit file is removed and the generator's `ghp_` literal is encoded. Pre-existing tracked `.tasks/` and other `docs/audits/` findings are outside this task and must be recorded as a boundary if they still make the raw scan command nonzero.
