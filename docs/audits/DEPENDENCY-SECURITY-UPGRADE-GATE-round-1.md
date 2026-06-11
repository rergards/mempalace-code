slug: DEPENDENCY-SECURITY-UPGRADE-GATE
round: 1
date: 2026-06-11
commit_range: a6e7b12..b269a16
findings:
  - id: F-1
    title: "verify-report accepts reports with empty or failed resolver_audits"
    severity: high
    location: "scripts/dependency_upgrade_gate.py:520"
    claim: >
      cmd_verify_report checked top-level status == "success" and advisory rows
      but never validated that resolver_audits is non-empty or that every entry
      has status == "success". ci-check delegates report validation to verify-report,
      so a hash-matching report with empty or failed resolver evidence would pass CI,
      violating the "fresh resolver audits before lock refresh" contract. The unit
      test fixture also codified this gap by passing an empty resolver_audits list
      to the "good" report case.
    decision: fixed
    fix: >
      Added validation in cmd_verify_report that (1) resolver_audits is non-empty
      and (2) every audit row has status == "success". Updated the test good-report
      fixture to include a proper passing audit entry. Added two new tests:
      test_verify_report_rejects_empty_resolver_audits and
      test_verify_report_rejects_failed_resolver_audit.

  - id: F-2
    title: "Stale uv.lock silently produces unknown current versions instead of failing"
    severity: medium
    location: "scripts/dependency_upgrade_gate.py:394"
    claim: >
      When a direct dependency had no matching entry in uv.lock, _enumerate_deps
      recorded current_version as "unknown" and cmd_audit silently skipped it for
      advisory querying (the current-version check was guarded by != "unknown").
      The plan contract requires a clear failure when a direct dependency cannot be
      matched. A stale or incomplete lockfile could therefore produce a passing audit
      report without ever querying the current version of some direct dependencies.
    decision: fixed
    fix: >
      Added a guard in cmd_audit after _enumerate_deps: if any direct dependency
      has current_version == "unknown", the command prints a clear error naming the
      package and group and returns 1 before reaching advisory queries or resolver
      audits. Added test_audit_fails_when_direct_dep_missing_from_lockfile.

  - id: F-3
    title: "workflow_dispatch triggers dependency-upgrade-gate with empty base-ref, causing spurious fail-closed"
    severity: medium
    location: ".github/workflows/ci.yml:102"
    claim: >
      The dependency-upgrade-gate job ran unconditionally for all triggers including
      workflow_dispatch. The base-ref expression only handled pull_request
      (github.event.pull_request.base.sha) and push (github.event.before). On
      workflow_dispatch, github.event.before is empty, making the expression evaluate
      to an empty string. The script then fails to resolve the ref and fails closed,
      forcing every manual run to fail unless a dependency-upgrade report happened to
      be present. Manual runs have no meaningful base ref to diff against and should
      not be blocked by the dependency gate.
    decision: fixed
    fix: >
      Added `if: github.event_name != 'workflow_dispatch'` to the
      dependency-upgrade-gate job. The gate now runs only on pull_request and push
      triggers where a meaningful base ref exists.

totals:
  fixed: 3
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "cmd_verify_report now rejects reports with empty or failed resolver_audits"
  - "cmd_audit now fails closed when any direct dependency is absent from uv.lock"
  - "dependency-upgrade-gate CI job skips workflow_dispatch to avoid spurious fail-closed"
  - "Test good-report fixture updated to include a passing resolver audit entry"
  - "Three new tests added: empty resolver_audits, failed resolver audit, stale lockfile"
  - "Quality scorecard regenerated after new test additions"

new_backlog: []
