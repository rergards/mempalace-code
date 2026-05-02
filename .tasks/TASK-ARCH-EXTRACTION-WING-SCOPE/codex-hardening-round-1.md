**1. New Findings**

1. `P2` / Confidence: `High` / [mempalace_code/knowledge_graph.py](/private/var/folders/jw/lhsrh3md3zn1gx15pt4g54th0000gn/T/tmp.R1CBY2MXjW/mempalace_code/knowledge_graph.py:262)  
   `invalidate_arch_by_project_root()` uses raw `source_file LIKE ?` for path-prefix matching. SQLite treats `_` and `%` in project paths as wildcards, so mining `/tmp/a_b` can also expire arch facts under sibling `/tmp/aXb`. I verified this with a local repro: both the intended root file and sibling file were expired.

2. `P2` / Confidence: `High` / [mempalace_code/miner.py](/private/var/folders/jw/lhsrh3md3zn1gx15pt4g54th0000gn/T/tmp.R1CBY2MXjW/mempalace_code/miner.py:3595)  
   Existing KG rows emitted before this change with legacy source sentinel `__arch_ns_project__` are never expired by the new scoped invalidation, which only passes `__arch_ns_project__:<wing>`. After upgrade, stale namespace `in_project` rows can remain current when a namespace is deleted or architecture is disabled. I verified a legacy sentinel row remains `valid_to IS NULL`.

**2. Known Issues Map Status**

No prior report was present at `docs/audits/ARCH-EXTRACTION-WING-SCOPE-round-0.md`. Matching backlog context read: `docs/plans/ARCH-EXTRACTION-WING-SCOPE.md`. No duplicate findings suppressed.

**3. Evidence Reviewed**

Reviewed scoped diff and files manifest, touched implementation files, relevant tests, and the task plan. Attempted targeted pytest, but collection imported `mempalace_code` from `/Users/rerg/dev/mempalace` instead of this scoped snapshot, so tests could not run here.

**4. Residual Risks**

Windows path separators are not covered by the current `/`-based SQL prefix pattern. That may be addressed alongside the escaped-prefix fix.

**5. Convergence Recommendation**

Do another implementation round. The main behavior is close, but the raw `LIKE` path match and legacy sentinel migration gap can both leave the feature failing its core “preserve other wings / expire current wing” contract.

**6. Suggested Claude Follow-Up**

Escape `LIKE` metacharacters and use an explicit `ESCAPE` clause, or avoid `LIKE` for path prefixes. Add regression coverage for roots containing `_` and `%`. Add a migration-compatible expiry path for legacy `__arch_ns_project__` rows, ideally scoped by `in_project` object/wing rather than expiring all legacy sentinel rows globally.