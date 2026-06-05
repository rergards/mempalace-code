---
slug: AUTOPILOT-DEMO-QUALITY-ROADMAP
goal: "Turn mempalace-code into a public demo of Autopilot-driven code quality improvements"
risk: medium
risk_note: "Quality work can become invisible churn unless each task has a measurable baseline, public-safe artifact, and real verification surface."
files:
  - path: docs/BACKLOG.yaml
    change: "Adds the AUTOPILOT DEMO backlog section with scorecard, static-analysis, integration, security, performance, and docs-drift tasks."
  - path: docs/audits/
    note: "Ignored local evidence only; publish sanitized summaries elsewhere."
    change: "Future tasks should store baseline and before/after reports here."
  - path: .claude/skills/verify/INSTRUCTIONS.md
    change: "Future tasks should wire durable demo checks into verify after they exist."
acceptance:
  - id: AC-1
    when: "An Autopilot demo task lands"
    then: "It updates a public quality scorecard with before/after metrics and exact verification commands."
  - id: AC-2
    when: "A quality improvement changes behavior"
    then: "It includes real CLI/MCP/API coverage, not only direct unit calls."
  - id: AC-3
    when: "A cleanup task removes suppressions or restructures code"
    then: "It keeps the diff focused and reports which diagnostics, boundaries, or budgets improved."
  - id: AC-4
    when: "Release notes mention Autopilot quality"
    then: "They cite public repo metrics only: no private paths, internal incidents, private remotes, or host-specific state."
out_of_scope:
  - "Adding product features unrelated to code quality."
  - "Large rewrites without a measurable scorecard improvement."
  - "Marketing copy that is not backed by commands and committed artifacts."
---

## Demo Strategy

The demo should show that Autopilot can improve a real Python package without
destabilizing it. Each task should produce three things:

1. A measurable quality delta.
2. A new or stronger automated gate.
3. A public-safe explanation that a maintainer can audit.

## Suggested Sequence

1. `AUTOPILOT-DEMO-QUALITY-SCORECARD`
   - Establish the baseline first. Later tasks should update it instead of
     inventing their own reporting format.

2. `AUTOPILOT-DEMO-CLI-GOLDEN-SCENARIOS` and `AUTOPILOT-DEMO-MCP-STDIO-CONTRACTS`
   - These make the demo credible because they prove real user surfaces before
     deeper refactors begin.

3. `AUTOPILOT-DEMO-RUFF-RATCHET` and `AUTOPILOT-DEMO-PYRIGHT-STRICT-SLICE`
   - These create visible static-quality deltas without needing broad product
     changes.

4. `AUTOPILOT-DEMO-ARCHITECTURE-GUARD`
   - Once the strict slice is clearer, enforce boundaries so future Autopilot
     batches cannot slowly re-couple layers.

5. `AUTOPILOT-DEMO-SECURITY-BOUNDARY-TESTS`
   - Use the real boundary inventory from the earlier tasks to add abuse-case
     coverage where it matters.

6. `AUTOPILOT-DEMO-PERF-BUDGETS` and `AUTOPILOT-DEMO-DOCS-DRIFT-GUARD`
   - Close the demo loop with maintainability gates that stay useful after the
     initial showcase.

## Initial Public Baseline Signals

- Pyright currently runs in basic mode.
- Ruff has transitional global and per-file ignores in `pyproject.toml`.
- The largest modules include storage, mining chunkers, dialect, watcher, and
  mining symbols.
- Existing tests are broad, but some release-facing proof still benefits from
  real subprocess CLI/MCP contracts and drift guards.

These are not criticisms by themselves. They are the useful visible surfaces for
showing controlled, evidence-backed quality improvement.
