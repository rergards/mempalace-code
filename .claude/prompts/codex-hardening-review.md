Round __ROUND__: targeted Codex verification for feature "__FEATURE_NAME__" in "__FEATURE_SCOPE__".

Task slug: __TASK_SLUG__
Evidence output path: __OUTPUT_FILE__
Scope source: __SCOPE_SOURCE__
Scoped diff artifact: __SCOPED_DIFF_FILE__
Scoped files manifest: __SCOPED_FILES_FILE__

Goal:
Find high-impact issues in the task-scoped diff without modifying files.
Prioritize signal over volume.

Scope discipline:
- Read first:
  1. scoped diff artifact: `__SCOPED_DIFF_FILE__`
  2. scoped files manifest: `__SCOPED_FILES_FILE__`
  3. previous round report: `docs/audits/__TASK_SLUG__-round-__PREVIOUS_ROUND__.md` if it exists
  4. backlog context: __KNOWN_ISSUES_SCOPE__
- Treat the scoped diff artifact and scoped files manifest as authoritative for this review.
- This review runs in an isolated snapshot that mirrors only scoped files and task-local context. Ignore unrelated repo changes outside that scope.
- __ROUND_FOCUS__
- Stay inside "__FEATURE_SCOPE__" and directly affected dependencies.
- Start from the scoped diff and expand only to code paths it can realistically break.
- Do NOT scan unrelated repo areas or turn this into repo-wide cleanup.

Review bar:
- Report only concrete, current, bounded issues.
- Prioritize user-visible breakage, data/security issues, contract drift, race conditions, and missing regression tests on bug-prone touched paths.
- Do not report formatting, naming, cleanup-only refactors, speculative guards, weak polish nits, or pre-existing out-of-scope issues unless they are P0/P1 or directly causal.
- Zero findings is normal.

Output format:
1. New Findings
2. Known Issues Map Status
3. Evidence Reviewed
4. Residual Risks
5. Convergence Recommendation
6. Suggested Claude Follow-Up

Rules:
- Search strategy: use `rg -l` (list matching files) first to identify
  relevant files, then read or search within specific files. Never run
  unbounded content searches across broad directory trees.
- At most 3 findings unless the feature is clearly unstable.
- Include severity (`P0`-`P3`), confidence (`High` / `Medium` / `Low`), and file:line for each surviving finding.
- Suppress duplicate findings using the previous audit and matching backlog items.
- Keep findings concise and high-signal.
- Do not edit files. Claude will act on your report.
