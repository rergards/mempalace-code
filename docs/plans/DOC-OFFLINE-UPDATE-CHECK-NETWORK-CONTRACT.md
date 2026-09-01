---
slug: DOC-OFFLINE-UPDATE-CHECK-NETWORK-CONTRACT
status: completed
authority: non_authoritative
goal: "Correct the offline guide so explicit updater metadata refreshes are identified as network operations."
risk: low
risk_note: "The change is limited to an existing documentation contract and does not alter update or network behavior."
contract_policy:
  flow: lite_compact
  reason: "Scope, reversibility, coupling, operational impact, and verification are all low; no auth, data, migration, provider, or pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: docs/OFFLINE_USAGE.md
    change: "Replace the overbroad network guarantee with an exact boundary for offline-safe commands, version checks, explicit updater commands, and the version-check kill switch."
  - path: scripts/docs_drift_guard.py
    change: "Extend the existing offline-disclosure owner with the updater, kill-switch, and recovery markers."
  - path: tests/test_docs_drift_guard.py
    change: "Prove each required offline-disclosure marker fails closed when removed."
acceptance:
  - id: AC-1
    when: "The rendered Version Checks and Offline Guarantees section is inspected for the normal offline path."
    then: "It still states that the named core CLI commands and MCP tools run offline after model setup, without claiming that every CLI operation is network-free."
  - id: AC-2
    when: "The rendered section is inspected for explicit update operations."
    then: "It identifies `update status` and `update check` as read-only operations that refresh canonical PyPI metadata, and it does not describe read-only as offline."
  - id: AC-3
    when: "The rendered section is inspected for an unavailable network or airgapped environment."
    then: "It warns that explicit updater metadata refreshes can fail when PyPI is unavailable and gives a concrete offline-safe recovery choice: avoid those commands until connectivity is available."
  - id: AC-4
    when: "The rendered kill-switch guidance is inspected with `MEMPALACE_VERSION_CHECK=0` in scope."
    then: "It limits the variable's guarantee to automatic and explicit version checks and states that it does not block updater PyPI requests or direct `EntityRegistry.research()` calls."
out_of_scope:
  - "Changing updater, version-check, MCP, or entity-research runtime behavior."
  - "Adding an offline mode or extending `MEMPALACE_VERSION_CHECK` to updater commands."
  - "Rewriting the updater workflow in docs/UPDATES.md."
---

## Design Notes

- Preserve the current offline guarantee for the enumerated core commands and ordinary MCP tools after the embedding model is cached.
- Replace “the only optional network activity” and “no network calls, ever” with bounded statements that account for all documented exceptions.
- State that `mempalace-code update status` and `mempalace-code update check` contact the fixed canonical PyPI metadata endpoint even though they do not install packages or persist update state.
- Include `mempalace-code update apply --yes` and scheduled update execution in the broader network-capable updater boundary because target provenance and installation require network access; keep detailed updater behavior in docs/UPDATES.md.
- Keep the existing automatic version-check cadence, telemetry boundary, `--check-now` behavior, and direct `EntityRegistry.research()` exception intact.
- Give airgapped operators one self-contained rule: set `MEMPALACE_VERSION_CHECK=0` and avoid explicit updater commands and direct research calls while offline.
- Validate the final wording with focused rendered-text or bounded `rg` output that proves the normal, failure, and kill-switch boundaries without relying on source implementation inspection.
