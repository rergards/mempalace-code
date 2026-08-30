---
slug: DOC-AGENT-EXTRAS-INVENTORY
goal: "Keep the AGENTS.md optional-extra inventory synchronized with package metadata."
risk: low
risk_note: "The change is limited to public agent documentation and an existing metadata-derived documentation guard; it does not alter packaging or runtime behavior."
files:
  - path: AGENTS.md
    change: "List every supported project optional extra with concise agent-facing purpose and installation guidance."
  - path: scripts/docs_drift_guard.py
    change: "Require the AGENTS.md optional-extra inventory to contain every metadata-declared extra while retaining stale-extra detection."
  - path: tests/test_docs_drift_guard.py
    change: "Cover complete, missing, and unknown AGENTS.md optional-extra inventories against fixture package metadata."
acceptance:
  - id: AC-1
    when: "The focused documentation drift guard test evaluates an AGENTS.md inventory containing custom-models, dev, spellcheck, treesitter, and watch against matching project.optional-dependencies."
    then: "The guard reports no optional-extra drift and exposes the five metadata-derived extras in deterministic order."
  - id: AC-2
    when: "The focused test removes one declared extra from the AGENTS.md optional-extra inventory and evaluates the fixture."
    then: "The guard returns an AGENTS.md Optional extras diagnostic that names the missing extra."
  - id: AC-3
    when: "The focused test adds an AGENTS.md optional-extra entry that is absent from project.optional-dependencies and evaluates the fixture."
    then: "The guard returns an AGENTS.md Optional extras diagnostic that names the unknown extra as stale."
out_of_scope:
  - "Changing project.optional-dependencies or dependency versions."
  - "Changing README.md or other installation guides whose inventories are already guarded."
  - "Installing extras or exercising their runtime integrations."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: scope, implementation complexity, operational impact, reversibility, and verification cost are small; no auth, data, migration, provider, or pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Treat `project.optional-dependencies` in `pyproject.toml` as the inventory source of truth; do not duplicate a hard-coded canonical list in the guard.
- Extend the existing AGENTS.md comparison in `scripts/docs_drift_guard.py`. Reusing that owner is cheaper and safer than introducing a second documentation checker.
- Parse extras from the bounded `Optional extras` section so unrelated `.[extra]` references elsewhere in AGENTS.md cannot mask an omitted inventory entry.
- Preserve deterministic diagnostics with the affected file, section, drift direction, and sorted extra names.
- Keep each AGENTS.md entry concise: exact `.[extra]` token plus its supported purpose. Retain the existing custom-model boundary pointer rather than duplicating its CPU installation procedure.
- Verify behavior with `python -m pytest tests/test_docs_drift_guard.py -q -k optional_extras` and run the repository documentation drift guard through its existing canonical invocation during implementation validation.
