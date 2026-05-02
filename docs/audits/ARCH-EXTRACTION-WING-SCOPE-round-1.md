slug: ARCH-EXTRACTION-WING-SCOPE
round: 1
date: "2026-05-02"
commit_range: 9ccfb8c..HEAD
findings:
  - id: F-1
    title: "Unescaped SQL LIKE wildcards in project_root path expire sibling-wing arch facts"
    severity: high
    location: "mempalace_code/knowledge_graph.py:247"
    claim: >
      invalidate_arch_by_project_root() built its prefix pattern as
      ``resolved_root + "/%"`` and passed it straight to ``source_file LIKE ?``.
      SQLite treats ``_`` and ``%`` in the LIKE operand as wildcards, so a
      project root containing either character also matches sibling roots
      whose names happen to satisfy the wildcard pattern. Verified locally:
      a project root ``/tmp/a_b`` plus sibling ``/tmp/aXb`` both match the
      LIKE pattern, so wing scoping silently leaks across roots that share
      a wildcard-collision parent. Surfaced by Codex hardening review (P2).
    decision: fixed
    fix: >
      Escape SQL LIKE metacharacters in the resolved root before substitution
      and add an explicit ``ESCAPE '\\'`` clause. The substitution order is
      ``\\`` first, then ``%``, then ``_``, so the escape character itself is
      escaped before its uses. Added regression test
      TestPredicatesFilter.test_project_root_with_like_wildcards_does_not_match_siblings
      that asserts mining ``/tmp/.../a_b`` and ``/tmp/.../p%t`` does not expire
      sibling rows under ``/tmp/.../aXb`` and ``/tmp/.../pANYt``.
  - id: F-2
    title: "Legacy pre-WING-SCOPE namespace→project sentinel rows orphaned after upgrade"
    severity: medium
    location: "mempalace_code/miner.py:3596 (call site); legacy data shape"
    claim: >
      Pre-WING-SCOPE releases (the just-shipped v1.7.0 ARCH-EXTRACTION-MODE
      pass) stored namespace→project triples with a single shared sentinel
      ``source_file = '__arch_ns_project__'`` that does not include the wing
      name. The new wing-scoped invalidation only matches
      ``__arch_ns_project__:<wing>``, so legacy rows persist forever as
      orphaned ``current`` facts after upgrade — if a namespace is later
      removed or architecture is disabled, the legacy fact never expires.
      Verified locally: a seeded legacy row remains ``valid_to IS NULL`` after
      a mine. Surfaced by Codex hardening review (P2).
    decision: fixed
    fix: >
      Added KnowledgeGraph.invalidate_legacy_arch_ns_project_for_wing(legacy_sentinel,
      wing_name) which expires only legacy rows whose ``source_file`` equals
      the bare sentinel AND whose ``predicate='in_project'`` AND whose
      ``object`` resolves to the current wing. Wired into miner.py to run
      alongside invalidate_arch_by_project_root. Other wings' legacy rows are
      preserved until they are themselves mined, matching the wing-scoping
      contract. Added regression test
      TestMiningIntegration.test_legacy_ns_project_sentinel_expired_for_current_wing_only
      that seeds two legacy rows (alpha + beta), mines alpha, and asserts only
      the alpha row is expired.
  - id: F-3
    title: "Pre-existing pyright diagnostics in knowledge_graph.py and miner.py"
    severity: info
    location: "mempalace_code/knowledge_graph.py:49,98,116,117,119,120,170,199,224,225 ; mempalace_code/miner.py:97,187,534,1661,2636,3369,3374,3515,3520"
    claim: >
      Diagnostic sweep flagged pre-existing typing issues (``None`` defaults
      on non-Optional parameters, unresolved ``torch`` import, etc.). None
      were introduced by this task and none are inside the wing-scoping
      diff; they predate the round and are visible because the harness runs
      pyright across the modified file. Recording for visibility only.
    decision: dismissed
    fix: ~
totals:
  fixed: 2
  backlogged: 0
  dismissed: 1
fixes_applied:
  - "knowledge_graph.py: invalidate_arch_by_project_root now escapes _ and % in the resolved root and uses an explicit ESCAPE '\\\\' clause so sibling-wing paths cannot match the LIKE prefix"
  - "knowledge_graph.py: new invalidate_legacy_arch_ns_project_for_wing helper retires pre-WING-SCOPE namespace→project sentinel rows scoped by in_project object"
  - "miner.py: arch pass now invokes the legacy migration helper after the wing-scoped invalidation so upgraded users converge on wing-scoped sentinels as each wing is mined"
  - "test_architecture_extraction.py: added TestPredicatesFilter.test_project_root_with_like_wildcards_does_not_match_siblings (paths with _ and % wildcards) and TestMiningIntegration.test_legacy_ns_project_sentinel_expired_for_current_wing_only (legacy migration scoping)"
new_backlog: []
