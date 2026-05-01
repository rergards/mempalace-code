slug: ARCH-EXTRACTION-MODE
round: 1
date: "2026-05-02"
commit_range: 1f8f6dd..HEAD
findings:
  - id: F-1
    title: "Disabling architecture mode leaves prior arch facts active"
    severity: high
    location: "mempalace_code/miner.py:3578-3597"
    claim: >
      The architecture cleanup (kg.invalidate_by_predicates(ARCH_PREDICATES)) was nested
      inside the `if arch_cfg.get("enabled", True)` guard. When a project was first mined
      with architecture defaults (enabled) and later re-mined after the user set
      `architecture: {enabled: false}` in mempalace.yaml, the miner skipped both the
      invalidation and the re-emission. Existing `is_pattern`, `is_layer`, `in_namespace`,
      and `in_project` triples therefore remained queryable, contradicting the documented
      behaviour that `enabled: false` disables the pass. Originally surfaced by the
      Codex hardening review as P1.
    decision: fixed
    fix: >
      Moved kg.invalidate_by_predicates(list(ARCH_PREDICATES)) outside the enabled guard
      so stale arch facts are always expired before deciding whether to re-emit. Emission
      remains gated on enabled. Added regression test
      TestMiningIntegration.test_disabling_architecture_expires_prior_facts that mines once
      with defaults, asserts UserService is current as a Service pattern, then flips
      architecture.enabled to false, re-mines, and asserts UserService is no longer current.

  - id: F-2
    title: "Global arch invalidation can wipe arch facts emitted for other wings"
    severity: low
    location: "mempalace_code/miner.py:3589"
    claim: >
      kg.invalidate_by_predicates(ARCH_PREDICATES) expires every active arch triple in
      the KG, regardless of which wing produced it. If a user mines wing A and then
      mines wing B (wings share a single KG by default), wing A's arch facts are
      expired during B's mine and only B's facts are re-emitted. The mine-all command
      iterates wings sequentially so each wing eventually re-emits, but standalone
      sequential single-wing mines lose cross-wing facts until each wing is mined
      again. Not exercised by current tests; not raised by Codex.
    decision: backlogged
    backlog_slug: ARCH-EXTRACTION-WING-SCOPE

  - id: F-3
    title: "Pyright pre-existing diagnostics in miner.py"
    severity: info
    location: "mempalace_code/miner.py:97,187,534,1661,2636,3369,3374,3515,3520"
    claim: >
      A diagnostic sweep flagged pre-existing typing issues (None passed to non-Optional
      params, unresolved torch import, etc.) in miner.py. None are in the architecture
      pass diff and none are introduced by this task; recording for visibility only.
    decision: dismissed
    fix: ~

totals:
  fixed: 1
  backlogged: 1
  dismissed: 1

fixes_applied:
  - "miner.py: always invalidate ARCH_PREDICATES before deciding whether to re-emit, so disabling architecture in config expires prior facts"
  - "test_architecture_extraction.py: regression test asserting `enabled: false` on second mine expires arch facts emitted on the first mine"

new_backlog:
  - slug: ARCH-EXTRACTION-WING-SCOPE
    summary: "Scope architecture pass invalidation to the current wing instead of a global KG sweep"
