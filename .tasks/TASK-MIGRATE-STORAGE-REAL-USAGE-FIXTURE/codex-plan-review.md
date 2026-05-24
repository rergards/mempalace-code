verdict: NEEDS_CHANGES

gaps:
  - severity: high
    claim: "AC-5 has no linked regression_plan.checks row. Per strict-plan rules, every acceptance criterion must be referenced by at least one regression check via acceptance_ids."
    evidence: "docs/plans/MIGRATE-STORAGE-REAL-USAGE-FIXTURE.md:123-138 — regression_plan.checks lists REG-1 [AC-1, AC-2, AC-3], REG-2 [AC-1, AC-2, AC-3], REG-3 [AC-1, AC-2, AC-3, AC-4]; AC-5 (release-check docs grep) is not covered."
    suggested_fix: "Add a regression check that re-runs the AC-5 docs grep (e.g. the same `rg --fixed-strings --quiet` chain over docs/BACKUP_RESTORE.md as VER-5) with acceptance_ids: [AC-5], so a future edit that drops the smoke command, [chroma] hint, source/destination markers, or search marker from the docs is caught. Alternatively extend an existing REG row to include AC-5 with a command that actually proves AC-5 (a markdown-content grep, not just `ruff check`)."
