---
slug: REL-STATUS-VERIFIER-CREDENTIAL-FREE-ENV
status: completed
authority: non_authoritative
goal: "Run every PyPI provenance subprocess with the existing credential-free environment and disposable process state."
risk: medium
risk_note: "The patch is confined to one release-verifier path, but an incomplete environment boundary could expose credentials or make the release gate unusable across supported platforms."
files:
  - path: scripts/release_status_gate.py
    change: "Derive one provenance environment from the existing install-smoke owner, add disposable user/temp roots, and pass explicit base or VIRTUAL_ENV-extended copies to all four subprocess contours."
  - path: tests/test_release_status_gate.py
    change: "Capture effective environments for uv lock, uv venv, uv sync, and pypi-attestations; prove ambient secrets and PYTHONPATH are excluded while required portable state and failure behavior remain."
  - path: docs/quality/scorecard.md
    change: "Regenerate the canonical human-readable quality scorecard after focused test coverage changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the canonical machine-readable quality scorecard from the same generator."
acceptance:
  - id: AC-1
    when: "the focused provenance environment regression runs with a spy on the loaded install-smoke module"
    then: "check_pypi_provenance obtains its base subprocess environment once from the existing _credential_free_env owner"
  - id: AC-2
    when: "a successful provenance check and a verifier-error case capture uv lock, uv venv, uv sync, and pypi-attestations subprocess calls"
    then: "every call has an explicit isolated env and the error case retains the existing fail-closed surface result"
  - id: AC-3
    when: "synthetic API, OAuth, credential, arbitrary-marker, and PYTHONPATH values are installed in the parent environment before provenance verification"
    then: "none of those names or values appears in any captured subprocess environment"
  - id: AC-4
    when: "the captured environments are inspected on the supported host"
    then: "PATH plus present locale, certificate, and platform values are preserved; HOME, USERPROFILE, TMPDIR, and XDG roots are disposable; only uv sync receives the required VIRTUAL_ENV"
  - id: AC-5
    when: "the focused and complete release-status tests, configured non-network suite, Ruff lint and format, scorecard freshness, and runner diff checks are executed"
    then: "all checks pass and the implementation diff contains only the planned source, test, and generated scorecard paths"
  - id: AC-6
    when: "the isolated provenance regressions exercise all subprocess seams with synthetic credential-shaped parent state"
    then: "the gate reads no credential values, invokes no AI/provider client, and performs no publication or other public mutation"
out_of_scope:
  - "Changing public GitHub lookups, provenance identity rules, artifact download or digest behavior, or release-status interfaces."
  - "Adding a helper, module, dependency, service, environment contract, or second credential-filtering owner."
  - "Inspecting, classifying, copying, authenticating with, or otherwise using real credentials or paid-account state."
  - "Editing backlog metadata or invoking AI clients, publication, push, tag, release, or any remote mutation."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release security fix changes subprocess isolation at a release credential boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The provenance path must reuse the existing credential-free environment owner."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Every provenance subprocess must receive an explicit isolated environment on success and failure paths."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Ambient credential-shaped variables, arbitrary markers, and PYTHONPATH must not cross the provenance subprocess boundary."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Portable execution values and disposable state roots must remain available, with VIRTUAL_ENV limited to uv sync."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused, configured, formatting, scorecard, and diff gates must accept the bounded change."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Verification must remain credential-free and must not invoke provider clients or public mutation."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "PyPI provenance subprocess environment"
      kind: internal
      paths: ["scripts/release_status_gate.py"]
      expected_behavior: "All uv and official-verifier calls derive explicit environments from the already loaded install-smoke credential-free owner and disposable provenance roots."
    - name: "Generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "The existing scorecard pair remains current after provenance regression coverage changes."
  invariants:
    - id: INV-1
      statement: "scripts/release_install_metadata_smoke.py::_credential_free_env remains the single credential-free base-environment owner and is not modified or duplicated."
      applies_to: ["scripts/release_status_gate.py"]
    - id: INV-2
      statement: "Provenance package pinning, frozen uv sync, publisher identity, digest checks, bounded verifier output, remediation, and status classification remain unchanged."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
    - id: INV-3
      statement: "PATH, present LANG/LC_ALL, SSL_CERT_FILE/SSL_CERT_DIR, SYSTEMROOT/WINDIR, and disposable HOME/USERPROFILE/TMPDIR/XDG behavior remain portable."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
    - id: INV-4
      statement: "VIRTUAL_ENV is absent from uv lock, uv venv, and pypi-attestations environments and is added only to the copy used by uv sync --active."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
    - id: INV-5
      statement: "No credential inspection, AI-client execution, public mutation, interface change, or dependency change is introduced."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
  risks:
    - id: RISK-1
      risk: "One subprocess could retain implicit inheritance while the other three use isolated environments."
      mitigation: "Capture and assert the effective env for each command class, including every verifier invocation."
    - id: RISK-2
      risk: "Reusing one mutable dict could leak VIRTUAL_ENV backward into lock/venv calls or forward into the verifier."
      mitigation: "Keep one immutable-by-convention base dict and create a dedicated copy only for uv sync."
    - id: RISK-3
      risk: "Over-filtering could remove PATH, certificates, locale, or Windows platform values required by uv or the verifier."
      mitigation: "Assert allowed portable values from _credential_free_env and disposable state roots while rejecting all injected ambient markers."
    - id: RISK-4
      risk: "A new test function changes scorecard metrics and leaves committed generated artifacts stale."
      mitigation: "Regenerate both canonical scorecards with their existing generator and run its exact freshness check."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_status_gate.py -q"
      proves: "The focused module covers the credential-free owner call, explicit environments for all four subprocess contours, ambient-value exclusion, portable/disposable state, sync-only VIRTUAL_ENV, and retained fail-closed provenance behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-2
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The canonical scorecard pair matches the implementation tree after focused test changes."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The exact configured non-network suite preserves release-status, install-smoke, CLI, MCP, and package behavior around the environment-boundary change."
        acceptance_ids: [AC-2, AC-4, AC-5, AC-6]
      - id: REG-2
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The exact configured lint gate accepts the source and regression-test changes."
        acceptance_ids: [AC-5]
      - id: REG-3
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The exact configured format gate accepts the source and regression-test changes."
        acceptance_ids: [AC-5]
---

## Design Notes

- Keep `scripts/release_status_gate.py::check_pypi_provenance` as the behavior owner. Load the already used sibling install-smoke module and call its `_credential_free_env()` once inside the provenance temporary-directory lifetime; add no helper or second filtering policy.
- Extend that base dict in place only with provenance-local `HOME`, `USERPROFILE`, `TMPDIR`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, and `XDG_DATA_HOME` paths under `temp_root`, creating the directories before subprocess execution. Preserve the base owner's PATH, locale, certificate, and platform allowlist exactly.
- Pass the base environment explicitly to `uv lock --check`, `uv venv`, and every `pypi-attestations verify` call. Build `sync_env = dict(base_env)`, add only `VIRTUAL_ENV=str(venv)`, and pass that copy to `uv sync --active`; remove the current `os.environ.copy()` path.
- Extend the existing provenance recording test or add one tightly scoped regression that spies on `_credential_free_env`, injects representative API/OAuth/token names, `PYTHONPATH`, and a neutral marker into `os.environ`, and captures dict copies during each subprocess callback. Assert names and values are absent rather than enumerating or reading any real credential.
- Cover the error path by returning a verifier failure through the existing mock seam and asserting both the unchanged fail-closed result and the verifier's explicit isolated environment. Keep all HTTP and subprocess seams mocked; tests must make no public lookup, package install, provider-client, or mutation call.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with `python scripts/quality_scorecard.py --write`; the generator counts test functions and owns both files.
- Rule Zero: deletion would remove required provenance verification; a new helper would duplicate the existing owner. Reusing `_credential_free_env` at the current call site changes one runtime owner and one test owner with no new interface, state owner, dependency, or lifecycle. The cheapest falsifier is any captured subprocess environment containing an injected marker or lacking an explicit env.
- Command context basis: all commands run from the repository root. `pyproject.toml` configures pytest and Ruff; `scripts/gate_inventory.py` declares the exact full non-network, Ruff lint, Ruff format, and scorecard commands retained as configured-runner rows. Runner finalization separately owns `git diff --check` and changed-path inspection against the four planned files.
- `docs/quality/incident-class-registry.yaml` is absent in this worktree, so no registry-matched `incident_proof` block applies.
- PLAN did not execute tests, builds, release gates, verification wrappers, scorecard generation, or diff validation.
