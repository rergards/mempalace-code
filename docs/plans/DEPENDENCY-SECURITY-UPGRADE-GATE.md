---
slug: DEPENDENCY-SECURITY-UPGRADE-GATE
goal: "Make dependency upgrades repeatable, audited, and resistant to compromised target versions"
risk: medium
risk_note: "Dependency refreshes can silently change storage layout, transitive web stacks, model packages, and optional legacy backends; stale local locks can hide CI failures."
files:
  - path: pyproject.toml
    change: "Keep optional dependency bounds away from advisory-affected ranges; ChromaDB remains <1 while GHSA-f4j7-r4q5-qw2c affects current 1.x releases."
  - path: uv.lock
    change: "Refresh only after advisory checks and clean resolver tests pass."
  - path: .claude/skills/release/SKILL.md
    change: "Require dependency audit and clean resolver checks before release when bounds or lockfiles change."
  - path: .claude/skills/verify/INSTRUCTIONS.md
    change: "Route dependency changes through audit plus hosted-CI-equivalent clean environment checks."
acceptance:
  - id: AC-1
    when: "A dependency bound or uv.lock is changed"
    then: "The current and target versions for direct runtime, dev, and affected optional dependencies are listed from package metadata."
  - id: AC-2
    when: "A package target is selected"
    then: "OSV or an equivalent advisory source has been checked for both current and target versions, and affected target ranges are not adopted."
  - id: AC-3
    when: "The lockfile is refreshed"
    then: "pip-audit or an equivalent resolver-level audit passes on a fresh default install and any optional extras whose bounds changed."
  - id: AC-4
    when: "The dependency change is prepared for release"
    then: "A clean pip environment matching GitHub Actions runs the relevant test surface, including storage/miner tests for LanceDB changes and chroma-compat tests for ChromaDB changes."
out_of_scope:
  - "Removing deprecated ChromaDB support."
  - "Changing the default embedding model."
  - "Guaranteeing supply-chain integrity beyond published advisory databases, package metadata, resolver output, and test coverage."
---

## Current Findings - 2026-06-05

- `lancedb` latest `0.33.0` is usable after the miner hard-excludes the active palace storage directory from project scans.
- The default, non-chroma dependency set can be refreshed safely after audit and clean resolver tests.
- ChromaDB 1.x is not safe to adopt at this time: GHSA-f4j7-r4q5-qw2c affects the available `chromadb` 1.x line through `1.5.9`.
- `.[chroma]` remains a deprecated legacy backend and should stay capped below 1.x until a fixed 1.x release exists and the chroma-compat job passes in a clean environment.

## Required Procedure

1. Resolve package targets from PyPI metadata for direct runtime, dev, and optional dependencies.
2. Query OSV or an equivalent advisory database for current and target versions before changing bounds.
3. Reject or hold any target range with an active vulnerability affecting the chosen version.
4. Refresh `uv.lock` only after bounds are chosen.
5. Audit a fresh resolved environment, not only the developer's existing `.venv`.
6. Run clean pip tests matching GitHub Actions so local lock staleness and resolver drift are visible before release.
