# New Findings

1. **P1 / High - CI accepts reports whose resolver audits failed or are absent.**  
   `cmd_verify_report` only checks top-level `status == "success"` and advisory target rows; it never validates that `resolver_audits` is non-empty or that every resolver audit row has `status == "success"` (`scripts/dependency_upgrade_gate.py:520`, `scripts/dependency_upgrade_gate.py:523`). `ci-check` then delegates matching reports directly to this verifier (`scripts/dependency_upgrade_gate.py:650`). A dependency PR can therefore pass CI with a hash-matching report that says top-level success while containing failed or empty resolver evidence, which violates the gate's "fresh resolver audits before lock refresh" contract. The current unit test codifies this gap by passing an empty `resolver_audits` list in the "good" report fixture (`tests/test_dependency_upgrade_gate.py:395`).

2. **P1 / Medium - Stale or incomplete `uv.lock` can still produce a passing audit report.**  
   Direct dependencies missing from `uv.lock` are recorded as `"unknown"` (`scripts/dependency_upgrade_gate.py:151`) and then skipped for current-version advisory querying (`scripts/dependency_upgrade_gate.py:394`). There is no validation that each direct dependency has a lockfile version, nor that a targeted upgrade is reflected in `uv.lock`. That means a pyproject dependency change can be audited and reported against an unchanged or incomplete lockfile hash, allowing CI to pass without enforcing the documented "refresh uv.lock before the report" requirement. The task plan explicitly calls for a clear failure when a direct dependency cannot be matched, but no test covers this stale-lock path.

3. **P2 / Medium - The new CI job breaks manual `workflow_dispatch` runs.**  
   The workflow still supports `workflow_dispatch` (`.github/workflows/ci.yml:8`), but the new dependency gate job runs unconditionally and passes a base ref expression that only handles pull requests and pushes (`.github/workflows/ci.yml:102`). On manual dispatch, `github.event.before` is not a valid push base ref, so `ci-check` fails closed and then requires a dependency-upgrade report even for clean manual test/model-test runs. The docs describe CI behavior only for pull requests and pushes, so the job should either be skipped for `workflow_dispatch` or given a valid manual base-ref strategy.

# Known Issues Map Status

- Previous round report `docs/audits/DEPENDENCY-SECURITY-UPGRADE-GATE-round-0.md`: not present in this snapshot.
- Matching backlog/task context read: `docs/plans/DEPENDENCY-SECURITY-UPGRADE-GATE.md`.
- No duplicate findings were suppressed from prior audit context.

# Evidence Reviewed

- Scoped diff: `.tasks/TASK-DEPENDENCY-SECURITY-UPGRADE-GATE/codex-hardening-round-1.diff`
- Scoped files manifest: `.tasks/TASK-DEPENDENCY-SECURITY-UPGRADE-GATE/codex-hardening-round-1-files.txt`
- Task plan/backlog context: `docs/plans/DEPENDENCY-SECURITY-UPGRADE-GATE.md`
- Implementation: `scripts/dependency_upgrade_gate.py`
- Tests: `tests/test_dependency_upgrade_gate.py`
- Workflow: `.github/workflows/ci.yml`
- Docs: `docs/DEPENDENCY_UPGRADE_GATE.md`
- Verification run: `python -m pytest tests/test_dependency_upgrade_gate.py -q` -> `17 passed`

# Residual Risks

- Hosted GitHub Actions runtime behavior was not executed; the workflow finding is based on static event/ref semantics and the script's fail-closed behavior.
- The isolated snapshot does not include `pyproject.toml`, `uv.lock`, or a Git repository, so stale-lock behavior was reviewed from implementation logic rather than exercised against the full repo files.

# Convergence Recommendation

Do not converge yet. The current implementation can pass the dependency gate without valid resolver evidence and can accept a stale/incomplete lockfile report, which are core security-gate contract failures.

# Suggested Claude Follow-Up

Tighten `verify-report` and audit validation before the next round:

- Reject reports with empty `dependencies`, empty `advisory_results`, or empty `resolver_audits` when dependency files changed.
- Reject any resolver audit row whose status is not `"success"`.
- Fail `audit` when any direct dependency is missing from `uv.lock`, and add a regression test for pyproject changes with stale or incomplete lockfile data.
- Handle `workflow_dispatch` explicitly: skip `dependency-upgrade-gate` for manual runs or require/pass a valid manual `base-ref`.
