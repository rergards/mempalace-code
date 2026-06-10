verdict: NEEDS_CHANGES

gaps:
  - severity: critical
    claim: "Plan file does not exist — there is nothing to review"
    evidence: "docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md is absent. Verified via direct read (file-not-found), `find . -iname '*FSEVENTS*'` (no matches outside .git), and a clean `git status`. The docs/plans/ directory contains 100+ other task plans but not this one. The task exists only as a backlog entry (docs/BACKLOG.yaml:117-128, status: open) committed in 2c2716f 'docs: backlog macOS watch runaway guard'."
    suggested_fix: "Run the planning phase for WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD to produce docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md before requesting plan review. The plan was never written (or was never committed to this worktree branch)."
  - severity: high
    claim: "Required `task_contract:` front matter is absent (standard mode requires it)"
    evidence: "Consequence of the missing plan file; no YAML front matter exists at all."
    suggested_fix: "Include a `task_contract:` canvas in the new plan's YAML front matter, with acceptance criteria mapped 1:1 to runnable `verification:` rows via acceptance_ids."
  - severity: high
    claim: "No `regression_plan:` exists despite the task being behavior-changing (watch startup guards, default pruning/warnings for high-churn directories, launchd/schedule generation changes)"
    evidence: "docs/BACKLOG.yaml:124-126 — acceptance items require new refusal/guard behavior in watch startup and schedule generation, which changes existing `watch`/`watch-all`/schedule-render behavior in mempalace_code/watcher.py and cli.py."
    suggested_fix: "The new plan must include `regression_plan:` with runnable check commands (e.g. `python -m pytest tests/ -k watcher` style rows) covering each acceptance criterion via acceptance_ids."
  - severity: medium
    claim: "Backlog acceptance criterion 1 is documentation/investigation-phrased ('document the root cause class in a public-safe plan') and must be translated into an observable artifact in the plan"
    evidence: "docs/BACKLOG.yaml:123"
    suggested_fix: "In the plan, make this criterion verifiable — e.g. a named plan/docs section plus a grep-based public-safety check (no private paths/hostnames) — rather than 'document/investigate' prose."

notes: |
  Review context for the planner:
  - The backlog entry (docs/BACKLOG.yaml:117-128) is well-formed and the six acceptance
    items are implementable. The repo has the expected touch points: mempalace_code/watcher.py
    (watch_and_mine, watch_all, launchd/cron schedule rendering per CLAUDE.md) and
    mempalace_code/cli.py (watch command), plus tests/ for watcher coverage. A future plan
    should list those files explicitly, must NOT list docs/BACKLOG.yaml as a provider-owned
    or touched file (backlog completion belongs to bookkeep), and must keep all examples
    public-safe per the backlog's own constraint (no private machine paths, hostnames, or
    incident history).
  - Verdict is NEEDS_CHANGES solely because the plan artifact is missing; no judgment is
    made on an implementation approach since none was proposed.
