---
slug: REL-DEPENDENCY-AUDIT-1-13-5
status: completed
authority: non_authoritative
goal: "Generate one public-safe v1.13.5 dependency audit report that matches the current dependency-file hashes and clears the release gate."
risk: medium
risk_note: "The deliverable is a generated report, but an incomplete resolver surface or stale advisory result could falsely clear a security-sensitive release gate."
files:
  - path: docs/dependency-upgrade-reports/v1.13.5-release.json
    change: "Add the successful sanitized report produced by the existing dependency upgrade gate for the current pyproject.toml and uv.lock, covering default, dev, chroma, and chroma-migration resolver audits."
acceptance:
  - id: AC-1
    when: "the new report is checked with python scripts/dependency_upgrade_gate.py verify-report docs/dependency-upgrade-reports/v1.13.5-release.json --root ."
    then: "verification exits zero and confirms that the successful report matches the current pyproject.toml and uv.lock hashes"
  - id: AC-2
    when: "the resolver_audits array in the generated report is queried"
    then: "it contains successful rows for the default runtime install, dev tooling, chroma compatibility alias, and chroma-migration install surfaces"
  - id: AC-3
    when: "the repository public-safety scan inspects the generated report and surrounding tracked or staged content"
    then: "it reports no private paths, hostnames, credentials, tokens, resolver caches, or raw advisory/resolver output"
  - id: AC-4
    when: "python scripts/dependency_upgrade_gate.py ci-check --base-ref origin/main is run with the new report present, and the focused missing/stale-report guard scenario is exercised"
    then: "the live current-hash gate exits zero while the guard still exits nonzero for missing, stale, or unsuccessful audit evidence"
out_of_scope:
  - "Changing dependency bounds, pyproject.toml, or uv.lock; a failed advisory or resolver audit is reported as a blocker instead of authorizing an unplanned dependency change."
  - "Changing scripts/dependency_upgrade_gate.py, its tests, dependency audit documentation, or CI workflow behavior."
  - "Auditing unchanged optional extras such as spellcheck, watch, or treesitter beyond their direct-dependency enumeration in the report."
  - "Editing backlog metadata, archive files, or runner-owned completion state."
contract_policy:
  flow: full_spdd
  reason: "Strict release-security task whose generated evidence controls dependency admission."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The committed v1.13.5 report must have success status and hashes equal to the current pyproject.toml and uv.lock."
      source: "current backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Fresh resolver audits must cover the default runtime install, dev tooling group, deprecated chroma alias, and preferred chroma-migration extra."
      source: "current backlog AC-2 and current dependency diff from origin/main"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Committed advisory and resolver evidence must remain public-safe and bounded to structured package, version, advisory, hash, status, and sanitized summary fields."
      source: "current backlog AC-3 and CLAUDE.md public-safety policy"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The existing CI dependency gate must accept the current report against origin/main without weakening its missing, stale, or unsuccessful-report failure behavior."
      source: "current backlog AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "v1.13.5 dependency audit evidence"
      kind: store
      paths: ["docs/dependency-upgrade-reports/v1.13.5-release.json"]
      expected_behavior: "Provide the single successful, current-hash, public-safe report consumed by verify-report and ci-check, with resolver success for default, dev, chroma, and chroma-migration."
  invariants:
    - id: INV-1
      statement: "pyproject.toml and uv.lock content and hashes remain unchanged while producing and validating the report."
      applies_to: ["pyproject.toml", "uv.lock"]
    - id: INV-2
      statement: "The Chroma migration bridge and deprecated alias remain capped at chromadb>=0.5.0,<1 while GHSA-f4j7-r4q5-qw2c affects the available 1.x line."
      applies_to: ["pyproject.toml", "docs/dependency-upgrade-reports/v1.13.5-release.json"]
    - id: INV-3
      statement: "Exactly one report matches the current pyproject.toml and uv.lock hashes, preserving ci-check's unambiguous evidence contract."
      applies_to: ["docs/dependency-upgrade-reports/v1.13.5-release.json"]
    - id: INV-4
      statement: "No private machine, resolver, credential, token, hostname, or raw subprocess data is committed."
      applies_to: ["docs/dependency-upgrade-reports/v1.13.5-release.json"]
  risks:
    - id: RISK-1
      risk: "A manifest that omits a changed group or extra could produce an incomplete resolver matrix."
      mitigation: "Set changed_groups to runtime and dev, changed_extras to chroma and chroma-migration, and assert the exact resolver_audits extras matrix in the generated report."
    - id: RISK-2
      risk: "The report could be generated before the final dependency files and become stale."
      mitigation: "Generate after confirming clean dependency-file scope, then run verify-report and ci-check against the unchanged current files."
    - id: RISK-3
      risk: "Live OSV, package resolution, or pip-audit findings could make the current contract unsafe."
      mitigation: "Keep the gate fail-closed; retain no successful report and return the exact advisory or resolver blocker for a separately scoped dependency decision."
    - id: RISK-4
      risk: "Resolver or advisory diagnostics could leak local execution details into a public artifact."
      mitigation: "Commit only the gate's structured JSON output and run the existing tracked/staged public-safety scan before handoff."
  verification:
    - id: VER-1
      command: "python scripts/dependency_upgrade_gate.py verify-report docs/dependency-upgrade-reports/v1.13.5-release.json --root ."
      proves: "The report schema, success status, current pyproject.toml hash, current uv.lock hash, resolver presence, and resolver success all satisfy the existing gate."
      acceptance_ids: [AC-1]
      owner: provider
    - id: VER-2
      command: "jq -e '(.resolver_audits | map(.extras)) == [[], [\"dev\"], [\"chroma\"], [\"chroma-migration\"]] and all(.resolver_audits[]; .status == \"success\")' docs/dependency-upgrade-reports/v1.13.5-release.json"
      proves: "The generated artifact contains exactly the required successful default/runtime, dev-tooling, deprecated Chroma alias, and preferred Chroma migration resolver surfaces."
      acceptance_ids: [AC-2]
      owner: provider
    - id: VER-3
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The configured repository scanner rejects local paths, credential-shaped values, and orchestration residue in public tracked or staged artifacts."
      acceptance_ids: [AC-3]
      owner: configured_runner
    - id: VER-4
      command: "python scripts/dependency_upgrade_gate.py ci-check --base-ref origin/main"
      proves: "The release dependency gate finds exactly one successful report matching the current dependency contract and exits zero against the requested public base."
      acceptance_ids: [AC-4]
      owner: provider
    - id: VER-5
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_ci_check_requires_fresh_report_before_pyproject_or_lock_change -q"
      proves: "The unchanged existing gate still fails for absent, stale, or incomplete report evidence and passes only after matching successful evidence is present."
      acceptance_ids: [AC-4]
      owner: provider
  regression_plan:
    applies: false
    no_behavior_change_exception: "The only repository change is a generated audit evidence JSON consumed by unchanged gate code; the focused fail-closed verification row covers the existing behavioral boundary."
    checks: []
---

## Design Notes

- Reuse `scripts/dependency_upgrade_gate.py audit`; do not hand-author the report or add a parallel audit path.
- Create a phase-local transient target manifest. Set `changed_groups` to `runtime` and `dev`, and `changed_extras` to `chroma` and `chroma-migration`. Populate every required target from the exact current version in `uv.lock`; identical current/target versions are intentional because this task audits the already-selected v1.13.5 contract.
- Run the audit with slug `v1.13.5-release`. The existing resolver planner yields the ordered matrix `default`, `dev`, `chroma`, `chroma-migration`; each disposable environment installs `pip-audit` and the corresponding project surface without modifying the developer environment.
- The default resolver row is the runtime-install proof. The dev row covers changed release/security tooling. Both Chroma rows are required because `chroma` remains a deprecated compatibility alias while `chroma-migration` is the preferred bridge extra.
- Accept only a `status: success` report. If OSV blocks any selected target, the audit writes no report. If any resolver audit fails, the emitted blocked report is failure evidence and must not replace the successful deliverable; stop with the exact package/advisory or install-surface blocker.
- Keep `pyproject.toml` and `uv.lock` byte-identical throughout. Any remediation that changes their bounds or resolution requires a new scoped decision and a regenerated report for the resulting hashes.
- Preserve the report schema used by existing files under `docs/dependency-upgrade-reports`: hashes, direct dependency rows, advisory IDs/status, and sanitized resolver summaries only. Do not copy OSV bodies, pip output, temp paths, caches, hostnames, credentials, or environment data.
- Command context basis: the repository documents Python as the gate entrypoint; `verify-report` and `ci-check` are the established focused CLI checks, `jq` is available in the provider environment for exact JSON matrix inspection, and the configured runner owns the existing tracked/staged public-safety command.
