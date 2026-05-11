verdict: NEEDS_CHANGES

gaps:
  - severity: high
    claim: "AC-2, AC-3, and AC-4 each lack a `regression_plan.checks` row linked via `acceptance_ids`. All five regression checks (REG-1..REG-5) point to `[AC-1]` only, so the contract rule that every acceptance criterion must have at least one `regression_plan.checks` row is violated."
    evidence: "docs/plans/QUAL-PYRIGHT-ZERO.md:152-171 (regression_plan.checks all carry `acceptance_ids: [AC-1]`); acceptance ids defined at docs/plans/QUAL-PYRIGHT-ZERO.md:20-31"
    suggested_fix: "Add (or extend existing) regression_plan.checks rows so AC-2, AC-3, and AC-4 each appear in at least one `acceptance_ids` list. Concretely: bind the CI-inspection check that re-runs VER-2's parser to AC-2, the suppression-policy pytest (`python -m pytest tests/test_type_suppressions.py -q`) to AC-3, and the pyproject/CLAUDE.md alignment check from VER-4 to AC-4 (or duplicate them as REG-6/REG-7/REG-8). This proves these gating-surface ACs stay green on future edits, not just AC-1's behavior surface."
  - severity: medium
    claim: "AC-3 requires `tests/test_type_suppressions.py` and a negative fixture, but the plan never names the fixture path or the suppression-syntax contract the test must enforce. The file does not exist today, so an implementer must invent both the policy and the fixture layout from the design notes alone."
    evidence: "docs/plans/QUAL-PYRIGHT-ZERO.md:26-28 (AC-3) and design notes at docs/plans/QUAL-PYRIGHT-ZERO.md:183 (`# type: ignore[code]  # reason: ...`); `tests/test_type_suppressions.py` absent on disk"
    suggested_fix: "Either add the fixture file path (e.g. `tests/fixtures/unreasoned_suppression.py`) and the exact accepted-form regex/policy to the plan body, or list both files explicitly under the `tests/` files entry with the contract the scanner enforces. This removes the ambiguity about whether `# type: ignore` without `[code]` is allowed and prevents a brittle test."
  - severity: medium
    claim: "VER-2's heredoc parses ci.yml by string-splitting on the literal `  typecheck:` and `\\n  model-tests:` markers. If a future edit reorders jobs (e.g., moves `model-tests` above `typecheck` or renames it), or if `typecheck:` appears as a substring in another step name, the assertion silently passes or crashes. The plan should either pin a more robust parse (PyYAML) or note the structural assumption."
    evidence: "docs/plans/QUAL-PYRIGHT-ZERO.md:115-126; .github/workflows/ci.yml:65-79 (typecheck job currently followed by model-tests job)"
    suggested_fix: "Replace the string-split with a YAML load — e.g. `data = yaml.safe_load(...); job = data['jobs']['typecheck']; assert all('continue-on-error' not in step for step in job['steps']); assert any('python -m pyright --pythonpath' in step.get('run','') for step in job['steps'])`. This survives reordering and is what a reader expects from a CI-shape assertion."
  - severity: low
    claim: "The audit file `docs/audits/QUAL-PYRIGHT-ZERO-pyright-classification.md` is listed as a deliverable surface but no acceptance criterion or verification command checks that it exists or contains the required diagnostic-family / suppression inventory. It can be silently skipped without failing any gate."
    evidence: "docs/plans/QUAL-PYRIGHT-ZERO.md:7-8 (file entry) and docs/plans/QUAL-PYRIGHT-ZERO.md:79-82 (surfaces); no AC/VER references the audit"
    suggested_fix: "Either add an AC/VER pair that asserts the audit file exists and is non-empty (or contains required section headers), or move the audit out of the contract surfaces and treat it as a design-notes artifact rather than a deliverable."
