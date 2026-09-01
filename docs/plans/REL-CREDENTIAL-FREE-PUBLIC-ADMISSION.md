---
status: completed
authority: non_authoritative
slug: REL-CREDENTIAL-FREE-PUBLIC-ADMISSION
goal: "Route every default release-admission public lookup through one bounded credential-free stdlib GET transport."
risk: high
risk_note: "The change replaces every live evidence path used to admit or report a public release; a permissive transport or incomplete adapter could leak ambient credentials or make unsafe evidence appear complete."
files:
  - path: scripts/release_public_read.py
    change: "Add the single stdlib transport and endpoint adapters for fixed GitHub, PyPI, files.pythonhosted.org, and reviewed-upstream GET surfaces."
  - path: scripts/release_admission_checks.py
    change: "Replace gh/git/http command seams with normalized public-query inputs while preserving pure fail-closed admission predicates and bounded remediations."
  - path: scripts/release_preflight.py
    change: "Wire live release and upstream checks to the shared public-read owner; retain only local Git and local subprocess execution."
  - path: scripts/release_readiness_gate.py
    change: "Remove default gh, public git, and duplicate urlopen clients and inject the shared public-read query seam into admission rows."
  - path: scripts/release_status_gate.py
    change: "Use normalized public queries for refs, workflow runs/jobs, releases, PyPI metadata, artifacts, and provenance while preserving local verifier subprocesses."
  - path: scripts/upstream_comparison_guard.py
    change: "Delegate the fixed reviewed-upstream branch-head GET to the shared transport and remove its duplicate urllib client."
  - path: scripts/docs_drift_guard.py
    change: "Expose and enforce the credential-free public-read boundary as a canonical release documentation fact."
  - path: .github/workflows/publish.yml
    change: "Remove GH_TOKEN from read-only admission and replace admission-only network fetches with the credential-free public-read path while isolating the GitHub Release mutation job."
  - path: docs/RELEASING.md
    change: "Document the fixed public targets, credential-free admission path, local-Git boundary, and separately authorized mutation commands."
  - path: docs/release-admission-rulesets.md
    change: "Replace stale gh/git/token lookup descriptions with exact public GET surfaces and the fail-closed transport contract."
  - path: tests/test_release_public_read.py
    change: "Add sterile transport, endpoint-schema, boundedness, redirect, credential-source, and target-validation regressions."
  - path: tests/test_release_preflight.py
    change: "Update live admission fixtures to the public-query seam and prove default live paths cannot launch gh or network Git."
  - path: tests/test_release_readiness_gate.py
    change: "Cover normalized public admission wiring and process-launch traps without weakening existing readiness rows."
  - path: tests/test_release_status_gate.py
    change: "Map every status endpoint schema and preserve exact-SHA, artifact, provenance, remediation, and local verifier behavior through the new seam."
  - path: tests/test_upstream_comparison_guard.py
    change: "Cover the fixed upstream adapter plus rejected alternate repository, host, port, userinfo, and malformed response cases."
  - path: tests/test_release_ruleset_contract.py
    change: "Update ruleset fixtures for list/detail public-query adapters and retain pagination and fail-closed contract coverage."
  - path: tests/test_release_workflow_admission.py
    change: "Assert publish admission has no read-only GH_TOKEN, network git fetch, gh launch, or mutation-owner crossover."
  - path: tests/test_docs_drift_guard.py
    change: "Require synchronized credential-free public-read claims in both release documents."
  - path: docs/quality/scorecard.md
    change: "Regenerate the canonical human-readable scorecard after release regression coverage changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the canonical machine-readable scorecard from the same source tree."
acceptance:
  - id: AC-1
    when: "the sterile transport suite exercises allowed and adversarial requests through its local HTTP fixtures"
    then: "only bounded HTTPS GETs to approved endpoint shapes succeed, with fixed headers, no credential/proxy/cookie/netrc/redirect behavior, one timeout, no retries, bounded bodies/errors, and fail-closed malformed or ambiguous responses"
  - id: AC-2
    when: "focused preflight, readiness, status, admission, and upstream guard tests run with gh and network-git launch traps"
    then: "all five consumers use normalized public queries and no default admission path launches gh, git ls-remote, or a fallback equivalent"
  - id: AC-3
    when: "the endpoint adapter schema matrix runs for release admission and status fixtures"
    then: "check runs, fixed workflow runs/jobs, releases/latest/tag, main rules, ruleset list/detail, matching refs with bounded annotated-tag peeling, public main, fixed upstream head, and PyPI metadata/distribution/provenance reads map exactly to existing predicate inputs"
  - id: AC-4
    when: "repo, package, ref, and URL validation fixtures supply traversal, alternate target, userinfo, port, scheme, host, and malformed values"
    then: "every unsupported value is rejected before the local HTTP fixture observes a request, while local Git-only checks continue to use the local repository"
  - id: AC-5
    when: "the publish workflow contract test inspects every admission and GitHub Release step"
    then: "read-only admission receives no GH_TOKEN and performs no network git fetch, while the existing GitHub Release mutation remains confined to its separately authorized job and step"
  - id: AC-6
    when: "sterile tests seed token/config/HOME/XDG/SSH/proxy/netrc/cookie/auth traps and exercise redirects, timeout, 403, 429, 5xx, malformed schema/JSON, pagination, traversal, alternate authority, and oversized bodies"
    then: "no seeded credential source or forbidden process/header is observed and every adverse case returns a bounded fail-closed result"
  - id: AC-7
    when: "exact response-schema fixtures cover every adapter and remediation strings contain gh or git command text"
    then: "each adapter accepts only its declared schema and remediation text remains inert output that cannot trigger a process"
  - id: AC-8
    when: "the docs drift and release ruleset contract checks inspect RELEASING and release-admission-rulesets"
    then: "both documents state the credential-free public-read boundary and place all publication or mutation commands behind separate explicit authorization"
  - id: AC-9
    when: "the focused release suites and configured non-network, Ruff, type, workflow-security, docs-drift, scorecard, public-safety, and gate-inventory checks run from the repository root"
    then: "all checks exit zero, generated scorecards are current, installed-wheel gates remain represented, and the canonical gate inventory is unchanged"
  - id: AC-10
    when: "the credential and process-launch sentinel suite observes any credential source, Authorization/Cookie header, redirect, unbounded read, gh process, or network git process"
    then: "the suite fails and blocks completion with the observed forbidden behavior named"
out_of_scope:
  - "Publishing, pushing, tagging, rerunning workflows, changing GitHub settings, or performing any public mutation."
  - "Reading, classifying, copying, authenticating with, or transmitting real credentials, keychains, tokens, or paid-account state."
  - "Changing local Git identity checks, local verifier subprocesses, release predicate outcomes, remediation prose, repository/package targets, or gate inventory."
  - "Adding a dependency, service, durable state owner, retry system, generic HTTP client, or support for arbitrary repositories, packages, or URLs."
  - "Editing backlog metadata or archive files."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release security refactor changes provider and transport boundaries across the release-admission pipeline."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "One shared stdlib owner must enforce the complete bounded credential-free public GET policy."
      source: "current backlog contract AC-1 and AC-10"
      acceptance_ids: [AC-1, AC-10]
    - id: REQ-2
      statement: "Every default release consumer must use normalized public queries without gh or network-git fallback."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Adapters must preserve every existing GitHub, PyPI, distribution, provenance, ref, and upstream evidence schema."
      source: "current backlog contract AC-3 and AC-7"
      acceptance_ids: [AC-3, AC-7]
    - id: REQ-4
      statement: "Only the current fixed repository, package, ref, and upstream targets may reach the network."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Hosted read-only admission must be credential-free and remain isolated from publication mutation."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Sterile runtime and structural tests must prove no ambient credential or forbidden process/header path is reachable."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "Public release documentation and drift guards must state the new authority boundary."
      source: "current backlog contract AC-8"
      acceptance_ids: [AC-8]
    - id: REQ-8
      statement: "Existing release and quality gates must remain green without changing the gate inventory."
      source: "current backlog contract AC-9"
      acceptance_ids: [AC-9]
  surfaces:
    - name: "release public-read transport"
      kind: internal
      paths: ["scripts/release_public_read.py"]
      expected_behavior: "Own fixed target validation, credential-free urllib opener construction, bounded GET execution, and endpoint-specific response adapters."
    - name: "release admission predicates"
      kind: internal
      paths: ["scripts/release_admission_checks.py"]
      expected_behavior: "Consume normalized adapter results while remaining pure admission logic with no command or HTTP ownership."
    - name: "release preparation and reporting CLIs"
      kind: cli
      paths: ["scripts/release_preflight.py", "scripts/release_readiness_gate.py", "scripts/release_status_gate.py", "scripts/upstream_comparison_guard.py"]
      expected_behavior: "Route public evidence through one injected query seam, retain local-only Git and verifier subprocesses, and preserve current rows and exit behavior."
    - name: "hosted publication workflow"
      kind: internal
      paths: [".github/workflows/publish.yml"]
      expected_behavior: "Run pre-mutation admission without GH_TOKEN or network git and retain mutation credentials only in the existing publication owner."
    - name: "release boundary documentation"
      kind: internal
      paths: ["docs/RELEASING.md", "docs/release-admission-rulesets.md", "scripts/docs_drift_guard.py"]
      expected_behavior: "Describe and enforce the fixed credential-free public-read boundary and separate mutation authority."
    - name: "release transport and consumer regressions"
      kind: internal
      paths: ["tests/test_release_public_read.py", "tests/test_release_preflight.py", "tests/test_release_readiness_gate.py", "tests/test_release_status_gate.py", "tests/test_upstream_comparison_guard.py", "tests/test_release_ruleset_contract.py", "tests/test_release_workflow_admission.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "Provide hermetic behavior, schema, credential-sentinel, process-sentinel, workflow-shape, and documentation-drift evidence."
    - name: "generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "Remain synchronized with the changed regression inventory through the existing generator."
  invariants:
    - id: INV-1
      statement: "Release predicates keep their existing row names, statuses, remediation text, ordering, and fail-closed decisions."
      applies_to: ["scripts/release_admission_checks.py", "scripts/release_preflight.py", "scripts/release_readiness_gate.py", "scripts/release_status_gate.py"]
    - id: INV-2
      statement: "Local HEAD, worktree, tag-object, candidate-ref, artifact, digest, and official-verifier operations remain local and bounded by their existing owners."
      applies_to: ["scripts/release_preflight.py", "scripts/release_readiness_gate.py", "scripts/release_status_gate.py"]
    - id: INV-3
      statement: "The fixed public repository is rergards/mempalace-code, the fixed package is mempalace-code, and the reviewed upstream target remains the manifest-owned MemPalace/mempalace develop branch."
      applies_to: ["scripts/release_public_read.py", "scripts/upstream_comparison_guard.py"]
    - id: INV-4
      statement: "The GitHub Release mutation job retains its existing explicit contents-write authority and no read-only transport code enters that mutation path."
      applies_to: [".github/workflows/publish.yml"]
    - id: INV-5
      statement: "The canonical gate inventory and installed-wheel release gates remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "docs/RELEASING.md"]
    - id: INV-6
      statement: "No external AI client, credential command, provider/model call, dependency, service, durable state, retry, or generic network target is introduced."
      applies_to: ["scripts/release_public_read.py", "scripts/release_preflight.py", "scripts/release_readiness_gate.py", "scripts/release_status_gate.py", "scripts/upstream_comparison_guard.py", ".github/workflows/publish.yml"]
  risks:
    - id: RISK-1
      risk: "urllib defaults could silently consult proxies, redirects, cookies, auth, netrc, or environment-derived configuration."
      mitigation: "Construct one explicit opener with forbidden handlers absent or disabled and test it under seeded ambient traps and redirect responses."
    - id: RISK-2
      risk: "A generic URL or interpolated repo/package value could escape the approved public targets."
      mitigation: "Expose endpoint-specific query objects, validate all components before opening a connection, and reject userinfo, ports, traversal, alternate hosts, schemes, and identifiers."
    - id: RISK-3
      risk: "Replacing gh and git output could alter schema names, pagination semantics, annotated-tag resolution, or newest-run selection."
      mitigation: "Map each REST response to the current normalized predicate schema and retain exact per-endpoint success, malformed, pagination, and ordering fixtures."
    - id: RISK-4
      risk: "A body without a trustworthy Content-Length could exceed memory or logs."
      mitigation: "Apply an endpoint-specific maximum, reject excessive declared lengths, read at most limit plus one, reject overflow, and bound decoded diagnostics."
    - id: RISK-5
      risk: "Workflow cleanup could remove credentials from the authorized GitHub Release mutation path or leave them on read-only admission."
      mitigation: "Assert job/step authority separately: no admission token or network fetch, unchanged mutation job permissions and mutation-only GH_TOKEN."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_public_read.py -q"
      proves: "The shared transport and every endpoint adapter enforce the allowed target, method, header, credential, redirect, timeout, size, pagination, schema, and process boundaries."
      acceptance_ids: [AC-1, AC-3, AC-4, AC-6, AC-7, AC-10]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_release_preflight.py tests/test_release_readiness_gate.py tests/test_release_status_gate.py tests/test_upstream_comparison_guard.py tests/test_release_ruleset_contract.py -q"
      proves: "All release consumers preserve current behavior through normalized public queries and fail closed without gh or network-git fallback."
      acceptance_ids: [AC-2, AC-3, AC-4, AC-6, AC-7, AC-10]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_release_workflow_admission.py -q"
      proves: "publish.yml removes credentials and network Git from read-only admission while preserving the separate mutation job."
      acceptance_ids: [AC-5, AC-6, AC-7, AC-10]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py -q"
      proves: "Both public release documents carry synchronized credential-free and separate-mutation authority claims."
      acceptance_ids: [AC-8]
    - id: VER-5
      owner: provider
      command: "python -m pytest tests/test_gate_inventory.py -q"
      proves: "The canonical gate inventory and installed-wheel gate entries remain structurally unchanged and valid."
      acceptance_ids: [AC-9]
    - id: VER-6
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The exact configured non-network suite preserves repository behavior and covers all release-gate regressions."
      acceptance_ids: [AC-9]
    - id: VER-7
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The exact configured lint gate accepts the new transport, consumers, and tests."
      acceptance_ids: [AC-9]
    - id: VER-8
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The exact configured format gate accepts all Python changes."
      acceptance_ids: [AC-9]
    - id: VER-9
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The exact configured type gate accepts transport/query types and consumer seams."
      acceptance_ids: [AC-9]
    - id: VER-10
      owner: configured_runner
      command: "actionlint .github/workflows/*.yml"
      proves: "The exact configured workflow syntax gate accepts the credential and fetch changes."
      acceptance_ids: [AC-5, AC-9]
    - id: VER-11
      owner: provider
      command: "python -m pytest tests/test_release_workflow_admission.py -q"
      proves: "The focused workflow-admission contract suite finds no credential or permission regression across the publish workflow's admission and mutation jobs."
      acceptance_ids: [AC-5, AC-6, AC-9]
    - id: VER-12
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The exact configured docs-drift command accepts the new canonical public-read claims."
      acceptance_ids: [AC-8, AC-9]
    - id: VER-13
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The canonical generated scorecard pair is current after test changes."
      acceptance_ids: [AC-9]
    - id: VER-14
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The exact configured public-safety gate finds no private path, secret-shaped content, or local-only artifact in the change."
      acceptance_ids: [AC-6, AC-9]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_release_public_read.py tests/test_release_preflight.py tests/test_release_readiness_gate.py tests/test_release_status_gate.py tests/test_upstream_comparison_guard.py tests/test_release_ruleset_contract.py tests/test_release_workflow_admission.py tests/test_docs_drift_guard.py -q"
        proves: "One focused release-only regression pass covers transport, all consumers, hosted wiring, and synchronized documentation without live network or credentials."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-10]
---

## Design Notes

- Rule Zero outcome: public evidence remains required, so deletion cannot satisfy admission. Extending `release_admission_checks.py` would merge I/O ownership into the pure predicate owner. A same-directory `release_public_read.py` module has one distinct responsibility and replaces three default seams and two duplicate urllib clients without a dependency, service, store, or durable contract.
- Remove superseded `_run_gh`, public `git ls-remote`, and default `urlopen` implementations after all consumers use the new query seam. Keep local `git rev-parse`, tag-object, worktree, and candidate-ref operations in their current owners. No compatibility fallback may launch the removed clients.
- Keep the transport API endpoint-specific. Do not expose a general `get(url)` to release consumers. Query constructors accept only the fixed repository/package/upstream identities and validated SHA, branch, tag, ruleset ID, run ID, version, and filename components required by current admission.
- The GitHub adapter set covers check-runs; fixed Tests, Publish to PyPI, and Dependency Audit workflow runs; exact publish-run jobs; release list/latest/tag data; effective main rules; ruleset list/detail; `git/matching-refs/tags/v` with a bounded annotated-tag object peel; the public main commit; and the manifest-owned upstream branch head.
- The PyPI adapter set covers `pypi.org/pypi/mempalace-code/json`, exact provenance documents, and only distribution URLs supplied by validated PyPI metadata on `files.pythonhosted.org`. Require HTTPS, default port only, empty userinfo, no traversal or ambiguous escaping, and endpoint-specific response limits.
- Construct one opener that bypasses environment proxies and cannot source auth, cookies, netrc, or redirect credentials. Send only fixed `User-Agent` and endpoint-appropriate `Accept`; reject any outgoing `Authorization` or `Cookie` header. Use GET, one timeout, no retries, no redirect following, and bounded diagnostics that never echo response bodies or environment values.
- Treat `Content-Length` as an early upper-bound check, not as permission for an unbounded read. Reject malformed, negative, conflicting, or excessive lengths; read at most the endpoint limit plus one byte when length is absent or smaller; reject overflow and incomplete declared bodies before parsing.
- Preserve the existing predicate schemas rather than rewriting admission decisions. Adapters normalize REST snake_case fields to the current GitHub CLI-shaped keys where required, retain parsed timestamp ordering, and surface pagination ambiguity whenever the configured bound cannot prove completeness.
- Annotated-tag resolution follows a bounded peel chain and accepts only 40-hex object IDs and commit termination. Cycles, excess depth, missing objects, duplicate refs, mixed targets, or truncated matching-ref results fail closed.
- Keep remediation strings as data. Tests install subprocess sentinels and include `gh` and `git` in remediation output to prove no parser or runner treats the prose as an executable recovery action.
- In `publish.yml`, replace admission-only `git fetch origin main` with the public main-commit adapter and remove `GH_TOKEN` from both pre-mutation admission steps. Keep local tag resolution from the checkout. The `github-release` job retains `contents: write` and its mutation-only token for the existing release reconcile step; its admission step remains credential-free.
- Regenerate only the existing scorecard pair because the generator counts test functions. Do not edit `scripts/gate_inventory.py`; `tests/test_gate_inventory.py` and its focused command are the cheapest proof that the inventory did not change.
- Command context basis: all commands run from the repository root. `pyproject.toml` configures pytest, Ruff, Pyright, actionlint, and zizmor; `scripts/gate_inventory.py` supplies the exact configured full-suite, lint, format, type, workflow, docs-drift, scorecard, and public-safety commands retained above.
- No `incident_proof` block applies because `docs/quality/incident-class-registry.yaml` is absent in this worktree.
- Cheapest decisive falsifier: any sentinel observes an ambient credential source, `Authorization` or `Cookie`, a redirect, a body read beyond its limit, `gh`, or network Git during read-only admission. That observation blocks completion even if predicate outputs otherwise match.
- PLAN did not execute tests, builds, release gates, verification wrappers, scorecard generation, network admission, or publication actions.
