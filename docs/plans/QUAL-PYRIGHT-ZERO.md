---
slug: QUAL-PYRIGHT-ZERO
goal: "Make Pyright exit 0 locally and run as a failing CI gate for the configured package and tests."
risk: high
risk_note: "The cleanup crosses many source and test files and promotes CI from advisory to gating; most edits should be type-boundary narrowing, but runtime behavior can regress if annotations replace real guards."
files:
  - path: docs/audits/QUAL-PYRIGHT-ZERO-pyright-classification.md
    change: "Record the starting Pyright diagnostic groups by module/fix family, the final zero-baseline summary, and any remaining justified suppression inventory."
  - path: mempalace_code/
    change: "Fix Pyright diagnostics in the configured source package with local narrowing, protocols, TypedDicts, optional annotations, and narrow dynamic-boundary casts where behavior is unchanged."
  - path: tests/
    change: "Fix Pyright diagnostics in the configured tests and add focused suppression-policy coverage so unreasoned type suppressions are rejected. Concretely add `tests/test_type_suppressions.py` (scanner over `mempalace_code/` and `tests/` for any line containing `type: ignore` or `pyright: ignore`) and a negative fixture at `tests/fixtures/unreasoned_suppression.py` that the scanner is asserted to reject. Accepted suppression form is `# (type|pyright): ignore[<code>]  # reason: <text>` matching the regex `r\"#\\s*(?:type|pyright):\\s*ignore\\[[^\\]\\s]+\\]\\s*#\\s*reason:\\s*\\S\"`; bare `# type: ignore` without a `[code]` and without a `# reason:` justification is rejected. The fixture lives under `tests/fixtures/` and is excluded from the scanner's enforced set (it is asserted-rejected by the test itself)."
  - path: pyproject.toml
    change: "Keep Pyright configuration aligned with the gating command; do not hide configured source/test diagnostics with broad excludes or disabled reportMissingImports."
  - path: .github/workflows/ci.yml
    change: "Remove the Pyright typecheck step's continue-on-error guard once the local baseline is clean, keeping the resolved-interpreter command aligned with local docs."
  - path: CLAUDE.md
    change: "Update the type-checking guidance from a non-gating baseline to the clean gating Pyright command."
acceptance:
  - id: AC-1
    when: "The implementer runs `python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\"` from the project dev environment."
    then: "Pyright exits 0 and reports 0 errors for the configured `mempalace_code` and `tests` include set."
  - id: AC-2
    when: "The CI workflow's `typecheck` job is inspected after the Pyright baseline is clean."
    then: "The Pyright step uses the same resolved-interpreter command and has no `continue-on-error`, so a future Pyright diagnostic fails the job."
  - id: AC-3
    when: "`python -m pytest tests/test_type_suppressions.py -q` is run."
    then: "The suppression scanner accepts all current suppressions with nearby reasons and its negative fixture rejects an unreasoned `type: ignore` or `pyright: ignore` line."
  - id: AC-4
    when: "The Pyright config and developer guidance are inspected after the cleanup."
    then: "`mempalace_code` and `tests` remain included, missing imports remain reported, no broad ignore/exclude is added for configured files, and `CLAUDE.md` no longer describes Pyright as non-gating."
out_of_scope:
  - "Raising `typeCheckingMode` beyond `basic` or adding new type-strictness goals after the baseline is clean."
  - "Broad file-level ignores, repo-wide diagnostic disables, or excluding `mempalace_code` / `tests` to make the gate pass."
  - "Behavioral refactors of storage, mining, MCP, CLI, search, backup, or watcher logic beyond what is required to preserve existing behavior while narrowing types."
  - "Backlog completion, backlog archive edits, publishing, or release workflow changes."
contract_policy:
  flow: full_spdd
  reason: "Standard task that changes a CI quality gate and many typed source/test boundaries."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The configured Pyright baseline must be clean in the project dev environment."
      source: "Backlog scope and AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "CI must treat Pyright diagnostics as failures instead of advisory output."
      source: "Backlog scope and AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Any remaining type suppression must be intentionally justified near the suppression."
      source: "Backlog scope and AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Pyright config, developer docs, and the CI command must describe the same clean gating surface."
      source: "Backlog scope and AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Pyright source package"
      kind: internal
      paths: ["mempalace_code/"]
      expected_behavior: "Source package remains functionally compatible while all configured Pyright diagnostics are fixed with local type-boundary changes."
    - name: "Pyright test package"
      kind: internal
      paths: ["tests/"]
      expected_behavior: "Tests remain behaviorally equivalent while mocks, private test probes, and helper fixtures become Pyright-clean."
    - name: "Type-check configuration"
      kind: internal
      paths: ["pyproject.toml"]
      expected_behavior: "Configuration keeps the intended include set and import-reporting behavior; changes must align the gate, not relax it away."
    - name: "CI typecheck gate"
      kind: internal
      paths: [".github/workflows/ci.yml"]
      expected_behavior: "The typecheck job runs Pyright as a normal failing step after installation of the same optional extras needed for analysis."
    - name: "Typing guidance and audit trail"
      kind: internal
      paths: ["CLAUDE.md", "docs/audits/QUAL-PYRIGHT-ZERO-pyright-classification.md"]
      expected_behavior: "Developer guidance names the gating command and the audit records diagnostic families plus any justified suppressions."
  invariants:
    - id: INV-1
      statement: "The configured Pyright include set must continue to cover both package code and tests."
      applies_to: ["pyproject.toml"]
    - id: INV-2
      statement: "Missing runtime imports must not be hidden by disabling `reportMissingImports` or by excluding configured files."
      applies_to: ["pyproject.toml", ".github/workflows/ci.yml"]
    - id: INV-3
      statement: "Public CLI, MCP, storage, mining, search, backup, and watcher behavior must not change as a side effect of type cleanup."
      applies_to: ["mempalace_code/", "tests/"]
    - id: INV-4
      statement: "Optional extras remain optional for base package installation; type fixes must not introduce a new mandatory runtime dependency."
      applies_to: ["pyproject.toml", "mempalace_code/"]
  risks:
    - id: RISK-1
      risk: "Annotations may widen or narrow accepted runtime inputs instead of documenting the real contract."
      mitigation: "Prefer guard-preserving local narrowing and `T | None` only where `None` is an existing valid state; run focused regression tests for touched modules."
    - id: RISK-2
      risk: "Dynamic LanceDB, PyArrow, tree-sitter, watchfiles, and test-mock APIs may encourage broad suppressions."
      mitigation: "Contain dynamic APIs behind small protocols, TypedDicts, helper functions, or one-line casts with nearby reasons."
    - id: RISK-3
      risk: "CI can appear gated while still being advisory because `continue-on-error` remains on the Pyright step."
      mitigation: "Add an explicit workflow inspection check for the typecheck block and remove the guard only after AC-1 is satisfied."
    - id: RISK-4
      risk: "A broad repo-wide cleanup can mask behavior regressions in storage, mining, MCP, or CLI paths."
      mitigation: "Group diagnostics by module/fix family first, then run the nearest focused tests plus the full suite before committing implementation."
  verification:
    - id: VER-1
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The full configured Pyright surface is clean with the same interpreter resolution used by CI."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: |-
        python - <<'PY'
        from pathlib import Path
        import yaml

        data = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
        job = data["jobs"]["typecheck"]
        steps = job["steps"]
        assert all("continue-on-error" not in step for step in steps), (
            "typecheck job must not carry continue-on-error on any step"
        )
        pyright_steps = [
            step for step in steps
            if "python -m pyright --pythonpath" in step.get("run", "")
            and "import sys; print(sys.executable)" in step.get("run", "")
        ]
        assert pyright_steps, "typecheck job must run the resolved-interpreter Pyright command"
        PY
      proves: "The CI typecheck job uses the resolved-interpreter Pyright command as a normal failing step (structural YAML parse, robust to job reordering)."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_type_suppressions.py -q"
      proves: "Current suppressions are justified and an unreasoned suppression fixture is rejected."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: |-
        python - <<'PY'
        from pathlib import Path
        import tomllib

        pyproject = tomllib.loads(Path("pyproject.toml").read_text())
        pyright = pyproject["tool"]["pyright"]
        assert pyright["include"] == ["mempalace_code", "tests"]
        assert pyright.get("reportMissingImports") is True
        assert "exclude" not in pyright or not set(pyright["exclude"]) & {"mempalace_code", "tests"}
        guide = Path("CLAUDE.md").read_text()
        assert "python -m pyright --pythonpath" in guide
        assert "non-gating" not in guide
        PY
      proves: "The configured analysis boundary and developer guidance remain aligned with the clean gate."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: |-
        python - <<'PY'
        from pathlib import Path

        audit = Path("docs/audits/QUAL-PYRIGHT-ZERO-pyright-classification.md")
        assert audit.exists(), "classification audit must be written"
        text = audit.read_text()
        assert text.strip(), "classification audit must not be empty"
        # Required sections so the audit cannot be a one-line placeholder.
        for marker in ("Starting baseline", "Fix families", "Final baseline", "Remaining suppressions"):
            assert marker in text, f"audit missing required section: {marker}"
        PY
      proves: "The Pyright classification audit deliverable is present and structured (starting baseline, fix families, final baseline, remaining suppressions) so the type-cleanup trail is durable."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_storage.py tests/test_storage_lance.py -q"
        proves: "Storage add/read, schema, health, recovery, cleanup, and LanceDB edge behavior remain unchanged after type-boundary edits."
        acceptance_ids: [AC-1]
      - id: REG-2
        command: "python -m pytest tests/test_miner.py tests/test_chunking.py tests/test_architecture_extraction.py tests/test_symbol_extract.py -q"
        proves: "Mining, chunking, symbol extraction, and architecture KG behavior remain unchanged after annotation and narrowing edits."
        acceptance_ids: [AC-1]
      - id: REG-3
        command: "python -m pytest tests/test_cli.py tests/test_mcp_server.py tests/test_mcp_registry.py tests/test_e2e.py -q"
        proves: "CLI, MCP dispatch/registry, and public integration flows remain unchanged after test/source typing fixes."
        acceptance_ids: [AC-1]
      - id: REG-4
        command: "python -m pytest tests/ -x -q"
        proves: "The package's existing non-network behavior remains green across modules after the broad cleanup."
        acceptance_ids: [AC-1]
      - id: REG-5
        command: "ruff check mempalace_code/ tests/ && ruff format --check mempalace_code/ tests/"
        proves: "Typing edits preserve the repo's lint and formatting rules without unrelated style churn."
        acceptance_ids: [AC-1]
      - id: REG-6
        command: |-
          python - <<'PY'
          from pathlib import Path
          import yaml

          data = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
          job = data["jobs"]["typecheck"]
          steps = job["steps"]
          assert all("continue-on-error" not in step for step in steps)
          assert any(
              "python -m pyright --pythonpath" in step.get("run", "")
              and "import sys; print(sys.executable)" in step.get("run", "")
              for step in steps
          )
          PY
        proves: "The CI typecheck job stays gated on Pyright with the resolved-interpreter command on subsequent edits (mirrors VER-2 as a regression guard on AC-2)."
        acceptance_ids: [AC-2]
      - id: REG-7
        command: "python -m pytest tests/test_type_suppressions.py -q"
        proves: "The suppression-policy scanner continues to accept justified `# (type|pyright): ignore[<code>]  # reason: ...` suppressions and to reject the unreasoned-fixture negative case on future edits."
        acceptance_ids: [AC-3]
      - id: REG-8
        command: |-
          python - <<'PY'
          from pathlib import Path
          import tomllib

          pyproject = tomllib.loads(Path("pyproject.toml").read_text())
          pyright = pyproject["tool"]["pyright"]
          assert pyright["include"] == ["mempalace_code", "tests"]
          assert pyright.get("reportMissingImports") is True
          assert "exclude" not in pyright or not set(pyright["exclude"]) & {"mempalace_code", "tests"}
          guide = Path("CLAUDE.md").read_text()
          assert "python -m pyright --pythonpath" in guide
          assert "non-gating" not in guide
          audit = Path("docs/audits/QUAL-PYRIGHT-ZERO-pyright-classification.md")
          assert audit.exists() and audit.read_text().strip()
          PY
        proves: "Pyright config, developer guidance, and audit trail stay aligned with the clean gate on subsequent edits (mirrors VER-4/VER-5 as a regression guard on AC-4)."
        acceptance_ids: [AC-4]
---

## Design Notes

- First implementation step: run `python -m pyright --outputjson --pythonpath "$(python -c 'import sys; print(sys.executable)')"` in the real dev environment and write a short classification to `docs/audits/QUAL-PYRIGHT-ZERO-pyright-classification.md`.
- Group diagnostics before editing:
  - Optional-`None` contracts: change to `T | None` only where `None` is already accepted; otherwise add or preserve a runtime guard.
  - Dynamic dependency surfaces: LanceDB, PyArrow, tree-sitter, watchfiles, sentence-transformers, and optional Chroma should be isolated with protocols, local helpers, or narrowly scoped casts.
  - Test-only probes: prefer typed fixtures, `Protocol`/`TypedDict` test doubles, or reasoned one-line casts over broad ignores.
  - Import resolution: keep CI installing `.[dev,chroma,spellcheck,treesitter]`; do not silence missing imports in config.
- Do not commit a raw 300-line Pyright dump. The audit `docs/audits/QUAL-PYRIGHT-ZERO-pyright-classification.md` must contain the four section headings `Starting baseline`, `Fix families`, `Final baseline`, and `Remaining suppressions` (asserted by VER-5/REG-8), grouped by module and fix family, with final count and suppression inventory.
- Suppression format is mechanically checkable. The accepted single line form is:
  - `# type: ignore[<rule>]  # reason: <text>` or
  - `# pyright: ignore[<rule>]  # reason: <text>`
  - Required regex (case-sensitive): `r"#\s*(?:type|pyright):\s*ignore\[[^\]\s]+\]\s*#\s*reason:\s*\S"`.
  - Rejected: bare `# type: ignore` or `# pyright: ignore` without `[<rule>]`; any suppression without `# reason:` followed by non-whitespace; rule lists with whitespace inside the brackets.
- The suppression-policy test `tests/test_type_suppressions.py` walks `mempalace_code/` and `tests/` (excluding the `tests/fixtures/` directory), asserts every `type: ignore` / `pyright: ignore` line matches the accepted regex, and additionally loads `tests/fixtures/unreasoned_suppression.py` to assert the scanner rejects that file.
- Remove `.github/workflows/ci.yml` `continue-on-error` only after the full local Pyright command exits 0.
- `CLAUDE.md` currently says the type check is a "baseline currently non-gating in CI"; update that wording after the gate is real.
- Avoid treating `ruff` or pytest success as the core deliverable. They are regression guards around the behavior-preserving type cleanup; the deliverable is the clean Pyright gate.
