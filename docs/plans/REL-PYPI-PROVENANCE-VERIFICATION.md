---
slug: REL-PYPI-PROVENANCE-VERIFICATION
status: completed
authority: non_authoritative
goal: "Make verified PyPI provenance for every exact-version distribution a required post-publication release-status surface."
risk: medium
risk_note: "The change is read-only but release-blocking: an incomplete identity check could accept forged provenance, while verifier or propagation errors can hold a valid release open."
files:
  - path: scripts/release_status_gate.py
    change: "Add a required PyPI provenance surface that enumerates the exact-version wheel and sdist files, creates a disposable verifier environment from the frozen uv.lock resolution, invokes the pinned official verifier, validates the expected repository, publish-workflow, and trusted-publisher environment identity for every file, and emits only bounded sanitized status/remediation data."
  - path: tests/test_release_status_gate.py
    change: "Add hermetic verifier-result fixtures and gate tests for complete provenance, missing or extra attestations, repository/workflow/environment identity and digest mismatches, verifier/setup errors, bounded JSON, and sanitized diagnostics."
  - path: pyproject.toml
    change: "Add the official PyPI attestation verifier as an exact-pinned release/dev tool in both existing dev dependency declarations."
  - path: uv.lock
    change: "Lock the verifier and its resolved dependency artifacts so the established dependency audit and upgrade path owns reproducibility and maintenance."
  - path: docs/RELEASING.md
    change: "Document provenance as a required post-publication fact and record the first-release live read-only verification command and evidence boundary."
  - path: .claude/skills/release/SKILL.md
    change: "Add the provenance row to the canonical release-status surface list and require the live status gate to pass before shipped language or candidate-branch retirement."
  - path: tests/test_release_skill_contract.py
    change: "Extend the release-procedure contract to require the provenance surface and the bounded first-release live verification instruction."
  - path: tests/test_release_workflow_admission.py
    change: "Pin the publication invariant: the existing official trusted-publishing action remains commit-pinned and publication does not gain signing keys, duplicate signatures, GitHub build attestations, or SBOM generation."
  - path: docs/quality/scorecard.json
    change: "Regenerate the deterministic machine-readable quality scorecard after the provenance implementation and test changes."
  - path: docs/quality/scorecard.md
    change: "Regenerate the deterministic human-readable quality scorecard after the provenance implementation and test changes."
acceptance:
  - id: AC-1
    when: "the hermetic all-green release-status scenario supplies exact-version PyPI metadata for every wheel and sdist plus successful official-verifier results bound to rergards/mempalace-code, .github/workflows/publish.yml, and the release trusted-publisher environment"
    then: "the gate reports the PyPI provenance surface as ok only after every enumerated public distribution is cryptographically verified against that identity."
  - id: AC-2
    when: "the provenance fixture matrix supplies missing provenance, a repository, workflow, or trusted-publisher environment identity mismatch, an unattested extra file, a digest mismatch, or a verifier failure"
    then: "each scenario makes release completion fail closed with the PyPI provenance surface listed as a blocker."
  - id: AC-3
    when: "the release dependency and workflow contract suites inspect the executable verifier specification, lock metadata, and Actions used by the release path"
    then: "the verifier has one exact version owned by the existing dependency/lock maintenance path and every release Action remains immutable-SHA pinned."
  - id: AC-4
    when: "the release-status CLI renders successful and failed provenance fixtures through its JSON output"
    then: "it emits one stable provenance surface with bounded file counts/names, status, and one remediation while excluding credentials, local paths, raw verifier output, and complete provenance documents."
  - id: AC-5
    when: "the focused status and release-procedure suites run without public network access"
    then: "all automated provenance cases consume hermetic verifier fixtures and the release procedure contains one exact-version live read-only status-gate verification for the first release after landing."
  - id: AC-6
    when: "the publish-workflow contract suite inspects the post-change publication job"
    then: "Trusted Publishing through the existing official PyPI action remains the sole automatic attestation-generation path, with GitHub build attestations and SBOM generation absent."
out_of_scope:
  - "Publishing, republishing, deleting, yanking, signing, or otherwise mutating a PyPI distribution."
  - "Changing the trusted-publisher configuration, release environment, OIDC permissions, or repository secrets."
  - "Adding long-lived signing keys, duplicate signature formats, GitHub build attestations, or SBOM generation."
  - "Changing end-user mempalace-code runtime dependencies or adding provenance checks to normal CLI startup."
  - "Editing docs/BACKLOG.yaml or backlog archives; runner bookkeeping owns backlog metadata."
contract_policy:
  flow: full_spdd
  reason: "Strict release and supply-chain task whose fail-open behavior could certify an unexpected publisher or unattested public artifact."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Every wheel and sdist published for the requested version must have cryptographically valid PyPI provenance from the expected repository, publish workflow, and trusted-publisher environment."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Incomplete artifacts, invalid provenance, unexpected identities, digest mismatches, and verifier failures must block shipped status."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The official verifier and release Actions must be reproducibly pinned through maintained dependency surfaces."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Machine-readable provenance evidence must stay bounded, sanitized, and actionable."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Automated tests must be hermetic while the first post-landing release retains one documented live read-only verification."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Trusted Publishing remains the only automatic attestation generator; build attestations and SBOMs stay deferred."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Post-publication status gate"
      kind: cli
      paths: ["scripts/release_status_gate.py"]
      expected_behavior: "Resolve the complete exact-version PyPI file set, create the disposable verifier environment in locked/frozen mode from uv.lock without re-resolving transitive dependencies, verify every file with the official verifier against repository rergards/mempalace-code, workflow .github/workflows/publish.yml, and trusted-publisher environment release, and include a required bounded pypi_provenance row in human and JSON gate results. A stale, missing, or unusable lock fails the surface closed."
    - name: "Verifier dependency lock"
      kind: internal
      paths: ["pyproject.toml", "uv.lock"]
      expected_behavior: "Provide one exact verifier version and lock resolution through the repository's existing dev-tool dependency, audit, and upgrade path."
    - name: "Release operator procedure"
      kind: internal
      paths: ["docs/RELEASING.md", ".claude/skills/release/SKILL.md"]
      expected_behavior: "Treat provenance as a required shipped-status row and preserve one first-release live read-only verification step."
    - name: "Hermetic release contracts"
      kind: internal
      paths: ["tests/test_release_status_gate.py", "tests/test_release_skill_contract.py", "tests/test_release_workflow_admission.py"]
      expected_behavior: "Exercise verifier outcomes without network access and prevent release procedure, pinning, and trusted-publication invariants from drifting."
    - name: "Deterministic quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.json", "docs/quality/scorecard.md"]
      expected_behavior: "Regenerate the committed deterministic quality scorecard pair after the approved implementation and test changes."
      acceptance_ids: [AC-5]
  invariants:
    - id: INV-1
      statement: "The status gate remains read-only and never publishes, signs, deletes, yanks, or edits public artifacts or repository settings."
      applies_to: ["scripts/release_status_gate.py", "docs/RELEASING.md", ".claude/skills/release/SKILL.md"]
    - id: INV-2
      statement: "The official pypa/gh-action-pypi-publish trusted-publishing step remains the sole automatic producer of PyPI attestations and stays commit-SHA pinned."
      applies_to: [".github/workflows/publish.yml", "tests/test_release_workflow_admission.py"]
    - id: INV-3
      statement: "PyPI JSON remains the exact-version public file inventory; verification must cover the full inventory rather than a hard-coded wheel/sdist pair."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
    - id: INV-4
      statement: "Verifier subprocess output, attestation bundles, credentials, environments, and local temporary paths never pass through to human or JSON release-status output."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
    - id: INV-5
      statement: "The verifier remains release/dev tooling and does not enter the package's runtime dependency set or normal user CLI paths."
      applies_to: ["pyproject.toml", "uv.lock", "scripts/release_status_gate.py"]
  risks:
    - id: RISK-1
      risk: "Checking only one expected wheel and sdist could miss an unattested extra file added to the exact release."
      mitigation: "Derive the canonical filename/digest set from the exact-version PyPI JSON response and require a one-to-one successful verifier result for every entry."
    - id: RISK-2
      risk: "A valid signature from another repository, workflow, or trusted-publisher environment could be accepted as sufficient provenance."
      mitigation: "Bind verification to rergards/mempalace-code, .github/workflows/publish.yml, and the release environment and reject missing, ambiguous, or mismatched publisher identity."
    - id: RISK-3
      risk: "Verifier output or provenance documents could make release JSON unbounded or leak execution details."
      mitigation: "Convert verifier results at the subprocess seam into bounded filename/count/status facts, sanitize failures, and expose exactly one remediation."
    - id: RISK-4
      risk: "Verifier or dependency drift could make identical releases verify differently over time."
      mitigation: "Use one exact pin in both existing dev dependency declarations, update uv.lock, create the disposable verifier environment only from that frozen locked resolution, and contract-test pin, lock, and execution-path agreement."
    - id: RISK-5
      risk: "PyPI propagation or verifier installation failure could be confused with invalid provenance."
      mitigation: "Fail closed with an error status and one rerun remediation; keep the distinction observable without weakening shipped status."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_release_status_gate.py -q"
      proves: "Hermetic gate scenarios cover all-artifact success, every required fail-closed case, locked/frozen uv.lock-backed verifier environment creation without transitive re-resolution, rejection of stale or unusable lock state, bounded JSON, and sanitized verifier errors."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      owner: provider
    - id: VER-2
      command: "python -m pytest tests/test_release_skill_contract.py -q"
      proves: "The executable release procedure names the provenance surface and the first-release live read-only verification boundary."
      acceptance_ids: [AC-5]
      owner: provider
    - id: VER-3
      command: "python -m pytest tests/test_release_workflow_admission.py -q"
      proves: "The official publish Action remains immutable-pinned and Trusted Publishing stays the sole attestation generator without build attestations or SBOMs."
      acceptance_ids: [AC-3, AC-6]
      owner: provider
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_release_status_gate.py -q"
        proves: "The focused release-status regression module preserves the existing post-publication surfaces while adding the required fail-closed provenance surface."
        acceptance_ids: [AC-1, AC-2, AC-4, AC-5]
        owner: provider
      - id: REG-2
        command: "python scripts/release_install_metadata_smoke.py --install-spec . --json"
        proves: "The existing disposable install-metadata smoke still proves installed package metadata, module version, and CLI status agree after the release-status change."
        acceptance_ids: [AC-5]
        owner: provider
      - id: REG-3
        command: "python scripts/public_safety_scan.py --tracked --staged"
        proves: "The configured public-safety gate rejects publishable local paths and credential-shaped data across tracked and staged release artifacts."
        acceptance_ids: [AC-4, AC-5]
        owner: configured_runner
---

## Design Notes

- Preserve `scripts/release_status_gate.py` as the single post-publication owner. Add `pypi_provenance` to `REQUIRED_SURFACES` immediately after `pypi_json`; a skipped or errored provenance row keeps overall `ok` false.
- Reuse the exact-version `releases[version]` list already fetched from PyPI JSON. Normalize each public filename, package type, and advertised SHA-256 digest, reject malformed or duplicate entries, and compare that complete set one-to-one with verifier results. Do not stop after finding one wheel and one sdist.
- Use the maintained official `pypi-attestations` verifier. Add one reviewed exact version to both existing dev dependency declarations in `pyproject.toml` and resolve its full dependency closure into `uv.lock`. Have the status gate create its temporary verifier environment through uv's locked/frozen project path, targeting the temporary environment and refusing lock updates or dependency re-resolution, then invoke the verifier from that environment. A missing, stale, or unusable lock is a setup blocker. Keep the verifier outside runtime `project.dependencies`.
- Bind successful results to repository `rergards/mempalace-code`, workflow `.github/workflows/publish.yml`, and trusted-publisher environment `release`. Treat any missing or mismatched repository, workflow, or environment attribute, multiple ambiguous publisher results, extra or absent filenames, and any digest disagreement as blockers even when the verifier process exits zero.
- Keep the parent gate stdlib-only and inject the verifier subprocess seam like the existing install smoke. Convert the child result into a small internal structure before rendering; never copy stdout, stderr, Sigstore bundles, transparency-log material, claims, tokens, or environment data into the surface detail.
- The provenance surface should report only the package/version, verified file count, bounded filenames, and expected repository/workflow/environment on success. Every failure path gets the existing `SurfaceResult` shape and exactly one remediation: wait for PyPI propagation or fix the published provenance condition, then rerun the same read-only status gate.
- Unit and CLI tests must stub PyPI JSON, locked/frozen environment creation, and verifier execution. Assert that environment creation consumes `uv.lock` without lock mutation or transitive re-resolution and fails closed for stale or unusable lock state. Include fixture rows for multiple wheels, the sdist, an unattested extra file, missing provenance, repository mismatch, workflow mismatch, trusted-publisher environment mismatch, digest mismatch, malformed/oversized verifier output, verifier nonzero exit, install/setup error, and injected token/path text.
- Keep `.github/workflows/publish.yml` unchanged unless implementation reveals a direct contract-test gap. Its official publish Action already produces PEP 740 attestations through the `release` environment and `id-token: write`; this task verifies those attestations after publication and does not add another generator.
- Update the marked release-status table in `.claude/skills/release/SKILL.md`. In both operator surfaces, state that the first release after landing must run the normal exact-version, exact-SHA `release_status_gate.py` command against public PyPI without mutation and retain its bounded `pypi_provenance` row as live evidence.
- Command context basis: `pyproject.toml` supplies pytest and the duplicated dev-tool dependency surfaces, `uv.lock` is the repository lock/checksum owner, and the three selected pytest modules already isolate status-gate behavior, release-skill drift, and publish-workflow security without requiring live services.
- GitHub build attestations and SBOMs remain deferred. Record no new follow-up task unless a measured consumer or compliance requirement changes that boundary.
