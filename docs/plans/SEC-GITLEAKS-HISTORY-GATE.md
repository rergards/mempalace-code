---
slug: SEC-GITLEAKS-HISTORY-GATE
status: completed
authority: non_authoritative
goal: "Add maintained Gitleaks credential scanning for changed commit ranges and full public Git history while preserving the existing public-safety release-shape scanner."
risk: high
risk_note: "This changes security CI and release gates; false negatives can leak credentials, while false positives can block publication until baselines are reviewed."
files:
  - path: .gitleaks.toml
    change: "Add the repository Gitleaks configuration, extending the maintained default rule corpus and documenting local allowlist boundaries without disabling entropy or default credential rules."
  - path: security/gitleaks-baseline.yml
    change: "Add a reviewed baseline metadata file with an empty entries list by default; any future entry must include fingerprint, rationale, owner, and review or expiry condition."
  - path: scripts/gitleaks_scan.py
    change: "Add a stdlib wrapper around the Gitleaks CLI for changed-range scans, full-history scans, fixture smokes, redacted summaries, artifact paths, and baseline metadata validation."
  - path: tests/test_gitleaks_scan.py
    change: "Add focused tests for exact changed-range invocation, full-history guards, baseline metadata validation, redaction, synthetic credential fixtures, and scanner ownership boundaries."
  - path: scripts/gate_inventory.py
    change: "Register the Gitleaks changed-range, full-history, and baseline validation gates in the canonical quality/release inventory."
  - path: scripts/quality_scorecard.py
    change: "Expose the new Gitleaks gates and ownership metadata in the quality scorecard without merging them into public_safety coverage."
  - path: tests/test_gate_inventory.py
    change: "Assert the new Gitleaks gates are canonical, categorized, and wired into the expected public CI/release surfaces."
  - path: tests/test_quality_scorecard.py
    change: "Assert the scorecard reports separate public-safety and Gitleaks coverage, including maintained corpus, entropy, changed-range, history, and baseline modes."
  - path: scripts/release_preflight.py
    change: "Add an opt-in --with-gitleaks-history gate to release preflight. It stays off by default because both preflight callers run against a shallow checkout with no scanner installed; release admission for history scanning is the explicit publish.yml step instead."
  - path: tests/test_release_preflight.py
    change: "Assert the opt-in flag runs the Gitleaks history command, keeps it redacted, and fails closed when the command fails, and that the default never requires history scanning it cannot perform."
  - path: .github/workflows/ci.yml
    change: "Add a pinned Gitleaks PR/push changed-range job with full checkout depth, exact base/head range selection, redacted output, SARIF/artifact upload, and baseline validation."
  - path: .github/workflows/publish.yml
    change: "Run the Gitleaks full-history release gate before building or publishing from a tag, with fetch-depth 0 and redacted output."
  - path: .github/workflows/gitleaks-history.yml
    change: "Add a scheduled and workflow_dispatch full-history Gitleaks workflow with pinned actions, fetch-depth 0, redacted summaries, and artifact retention."
  - path: tests/test_workflow_security_gate.py
    change: "Extend workflow security tests to include the new pinned Gitleaks workflow/action references, the local composite action's no-external-uses boundary, and the Dependabot GitHub Actions plus gomod maintenance contracts."
  - path: tools/gitleaks/go.mod
    change: "Add a tool-only Go module that pins the Gitleaks CLI as a direct requirement so the installed version is declared in one dependency-maintained place instead of a mutable go-install tag."
  - path: tools/gitleaks/tools.go
    change: "Add the build-tagged blank import that keeps the Gitleaks module a direct dependency of the tool module so go mod tidy cannot drop it."
  - path: tools/gitleaks/go.sum
    change: "Add the checksum lock for the pinned Gitleaks module graph so installation is verified, not merely tagged."
  - path: .github/actions/gitleaks-gate/action.yml
    change: "Add a repository-local composite action that installs the checksum-locked Gitleaks CLI from tools/gitleaks, stamps and asserts the pinned version, and installs the wrapper's PyYAML dependency, so the three workflows share one installation path."
  - path: .github/dependabot.yml
    change: "Add the gomod ecosystem for /tools/gitleaks with weekly direct-dependency updates so the pinned Gitleaks version is maintained like every other dependency."
  - path: .claude/skills/verify/INSTRUCTIONS.md
    change: "Add the local Gitleaks baseline validation and changed-range verification commands to the public verify surface without replacing the public-safety command."
  - path: docs/quality/scorecard.json
    change: "Regenerate after adding tests and scorecard fields so the committed quality artifact stays fresh."
  - path: docs/quality/scorecard.md
    change: "Regenerate alongside scorecard.json from the same scorecard write command."
acceptance:
  - id: AC-1
    when: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_changed_range_scan_uses_exact_base_head_log_opts_and_fails_on_findings -q is run"
    then: "a changed-range scan invokes Gitleaks only for the supplied base..head commit range and returns nonzero when the scanner reports a new finding"
  - id: AC-2
    when: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_full_history_modes_require_reachable_history_and_fetch_depth_zero_workflows -q is run"
    then: "scheduled and release scan paths require full reachable history, and both workflow checkouts use fetch-depth 0 before running the full-history command"
  - id: AC-3
    when: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_baseline_entries_require_fingerprint_rationale_owner_and_review_condition -q is run"
    then: "baseline or ignore metadata is accepted only when every entry has a fingerprint, rationale, owner, and review or expiry condition"
  - id: AC-4
    when: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_synthetic_fixture_smoke_covers_required_non_live_secret_classes -q is run"
    then: "runtime-generated non-live fixtures cover PyPI tokens, GitHub tokens, AWS access keys, private-key headers, and representative high-entropy strings without storing complete live-looking secrets in tracked source"
  - id: AC-5
    when: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_public_safety_and_gitleaks_own_distinct_detection_classes -q is run"
    then: "tests document that public_safety_scan.py owns release-shape, local-path, provider-residue, and local-only artifact rules while Gitleaks owns maintained credential signatures, entropy findings, and Git-history scanning"
  - id: AC-6
    when: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_gitleaks_logs_sarif_summaries_and_artifacts_are_redacted -q is run"
    then: "Gitleaks logs, SARIF, summaries, and uploaded artifacts contain rule ids, paths, lines, and fingerprints but do not contain complete detected secrets"
  - id: AC-7
    when: "PYTHONPATH=. pytest tests/test_workflow_security_gate.py::test_live_repository_workflows_are_immutably_pinned -q and PYTHONPATH=. pytest tests/test_workflow_security_gate.py::test_dependabot_maintains_github_actions_weekly -q are run"
    then: "the new external Gitleaks action references are pinned to immutable SHAs with adjacent version comments, and the existing weekly GitHub Actions Dependabot path maintains those pins"
out_of_scope:
  - "Replacing scripts/public_safety_scan.py or moving release-shape/local-artifact checks into Gitleaks."
  - "Committing real secrets, complete live-looking credentials, or raw unredacted Gitleaks reports."
  - "Rewriting Git history or removing any historical findings; this task can only baseline reviewed false positives."
  - "Adding third-party Python runtime dependencies for secret scanning."
  - "Changing dependency-upgrade policy, package versions, release publication permissions, or backlog metadata."
contract_policy:
  flow: full_spdd
  reason: "Strict security and CI/release gate task that changes credential scanning, workflow behavior, and public artifact handling."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Pull-request and push checks must reject new Gitleaks findings in the exact changed commit range."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Scheduled and release checks must scan complete reachable public Git history from full-depth checkouts."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Any baseline or ignore entry must be reviewed metadata keyed by fingerprint with rationale, owner, and review or expiry condition."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Synthetic coverage must include PyPI tokens, GitHub tokens, AWS access keys, private-key headers, and representative high-entropy strings without exposing live secrets."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "public_safety_scan.py must continue to own release-shape and local-artifact invariants, and tests must document scanner ownership boundaries."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Gitleaks logs, SARIF, summaries, and artifacts must not print complete detected secrets."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "External scanner/action versions must be immutable in workflows and maintained through the repository GitHub Actions dependency update path."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "Gitleaks configuration"
      kind: internal
      paths: [".gitleaks.toml", "security/gitleaks-baseline.yml"]
      expected_behavior: "Use the maintained default Gitleaks corpus plus entropy detection, keep repository-specific ignores outside scanner rules, and require reviewed metadata for every fingerprint that is allowed to remain."
    - name: "Gitleaks gate wrapper"
      kind: cli
      paths: ["scripts/gitleaks_scan.py"]
      expected_behavior: "Expose changed-range, full-history, fixture-smoke, redaction, and baseline-validation modes; invoke Gitleaks with explicit config, redaction, deterministic report paths, and injectable runners for focused tests."
    - name: "Security gate tests"
      kind: internal
      paths: ["tests/test_gitleaks_scan.py", "tests/test_workflow_security_gate.py"]
      expected_behavior: "Prove changed-range command construction, full-history requirements, baseline schema, fixture coverage, output redaction, scanner ownership boundaries, immutable action pins, and Dependabot maintenance without using live secrets."
    - name: "Canonical gate inventory and scorecard"
      kind: internal
      paths: ["scripts/gate_inventory.py", "scripts/quality_scorecard.py", "tests/test_gate_inventory.py", "tests/test_quality_scorecard.py", "docs/quality/scorecard.json", "docs/quality/scorecard.md"]
      expected_behavior: "Register Gitleaks gates as distinct quality/release coverage and keep committed scorecard artifacts fresh after the new tests and fields land."
    - name: "CI changed-range scan"
      kind: internal
      paths: [".github/workflows/ci.yml"]
      expected_behavior: "On pull_request and push, perform a full-depth checkout, derive the exact base..head range from GitHub event SHAs, validate baseline metadata, run the pinned Gitleaks action/wrapper with redaction, and fail when new findings are reported."
    - name: "Release and scheduled history scans"
      kind: internal
      paths: ["scripts/release_preflight.py", "tests/test_release_preflight.py", ".github/workflows/publish.yml", ".github/workflows/gitleaks-history.yml"]
      expected_behavior: "Run the full-history Gitleaks gate in release preflight, publish-tag checks, and a scheduled workflow, always from a fetch-depth 0 checkout with redacted artifacts."
    - name: "Verify surface"
      kind: internal
      paths: [".claude/skills/verify/INSTRUCTIONS.md"]
      expected_behavior: "Expose the local Gitleaks commands alongside the existing public-safety scan so contributors can run both scanners intentionally."
  invariants:
    - id: INV-1
      statement: "scripts/public_safety_scan.py remains the owner for release-shape, local path, provider residue, and local-only artifact path checks."
      applies_to: ["scripts/public_safety_scan.py", "tests/test_public_safety_scan.py", "scripts/gitleaks_scan.py"]
    - id: INV-2
      statement: "Gitleaks output committed or uploaded by workflows must be redacted and must not contain complete detected secrets."
      applies_to: ["scripts/gitleaks_scan.py", ".github/workflows/ci.yml", ".github/workflows/publish.yml", ".github/workflows/gitleaks-history.yml"]
    - id: INV-3
      statement: "Workflow external action references remain full 40-hex commit SHAs with adjacent version comments, and publish.yml permissions/job boundaries remain exact."
      applies_to: [".github/workflows/ci.yml", ".github/workflows/publish.yml", ".github/workflows/gitleaks-history.yml", "scripts/workflow_security_gate.py"]
    - id: INV-4
      statement: "Synthetic fixture sources may assemble non-live secret-shaped strings at runtime only; tracked source must not contain complete live-looking credentials."
      applies_to: ["tests/test_gitleaks_scan.py", "scripts/gitleaks_scan.py"]
    - id: INV-5
      statement: "Release checks must continue to be non-mutating: no tags, pushes, releases, or history rewrites are performed by the Gitleaks gate."
      applies_to: ["scripts/gitleaks_scan.py", "scripts/release_preflight.py", ".github/workflows/publish.yml"]
  risks:
    - id: RISK-1
      risk: "A shallow checkout could make a full-history scan look successful while scanning only the latest commit."
      mitigation: "Require fetch-depth 0 in scheduled and release workflows, and make the wrapper/report include a full-history preflight that fails when reachable history is incomplete for the requested mode."
    - id: RISK-2
      risk: "A baseline could suppress a real historical leak without review."
      mitigation: "Keep baseline entries in reviewed metadata keyed by fingerprint, validate rationale/owner/review fields in CI, and start with an empty entries list unless implementation finds verified historical false positives."
    - id: RISK-3
      risk: "Scanner output could leak the detected credential while reporting a failure."
      mitigation: "Always pass Gitleaks redaction flags, generate sanitized summaries from structured output, never echo raw match/secret fields, and add tests that plant full fake secrets in runner output and assert they are removed."
    - id: RISK-4
      risk: "The new scanner could duplicate public_safety_scan.py and weaken release-shape coverage by moving local artifact rules into Gitleaks."
      mitigation: "Keep public_safety_scan.py untouched for release-shape checks and add an ownership test covering each scanner's separate responsibility."
    - id: RISK-5
      risk: "Pinned action SHAs could become stale or mutable references could enter new workflows."
      mitigation: "Use existing workflow_security_gate coverage for every new workflow and rely on the current weekly Dependabot GitHub Actions configuration for updates."
    - id: RISK-6
      risk: "Synthetic fixture strings could be mistaken for real secrets by the repository scans."
      mitigation: "Assemble fixture strings only inside temporary directories at runtime, keep tracked test source split into harmless fragments, and verify public_safety/Gitleaks current-tree scans do not see complete fixture secrets."
  verification:
    - id: VER-1
      command: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_changed_range_scan_uses_exact_base_head_log_opts_and_fails_on_findings -q"
      proves: "Provider-owned focused pytest verifies the wrapper constructs an exact base..head Gitleaks range and surfaces a nonzero finding result for PR/push delta checks."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_full_history_modes_require_reachable_history_and_fetch_depth_zero_workflows -q"
      proves: "Provider-owned focused pytest verifies full-history mode rejects incomplete history assumptions and the scheduled/release workflows declare fetch-depth 0 before running it."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_baseline_entries_require_fingerprint_rationale_owner_and_review_condition -q"
      proves: "Provider-owned focused pytest verifies baseline metadata cannot omit fingerprint, rationale, owner, or review/expiry fields."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_synthetic_fixture_smoke_covers_required_non_live_secret_classes -q"
      proves: "Provider-owned focused pytest verifies runtime-only fixture generation covers the required PyPI, GitHub, AWS, private-key, and entropy classes without complete tracked secrets."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_public_safety_and_gitleaks_own_distinct_detection_classes -q"
      proves: "Provider-owned focused pytest verifies scanner ownership boundaries while preserving the existing public_safety_scan.py release-shape contract."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py::test_gitleaks_logs_sarif_summaries_and_artifacts_are_redacted -q"
      proves: "Provider-owned focused pytest verifies structured Gitleaks output is summarized without complete secret values in logs, SARIF, summaries, or artifacts."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "PYTHONPATH=. pytest tests/test_workflow_security_gate.py::test_live_repository_workflows_are_immutably_pinned -q"
      proves: "Provider-owned focused pytest verifies all workflow external uses, including new Gitleaks actions, are pinned to immutable SHAs with adjacent version comments."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "PYTHONPATH=. pytest tests/test_workflow_security_gate.py::test_dependabot_maintains_github_actions_weekly -q"
      proves: "Provider-owned focused pytest verifies the existing GitHub Actions Dependabot path continues to maintain pinned action SHAs and version comments weekly."
      acceptance_ids: [AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "PYTHONPATH=. pytest tests/test_gitleaks_scan.py -q"
        proves: "Provider-owned focused regression covers Gitleaks changed-range, full-history, baseline, fixture, ownership, and redaction behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
      - id: REG-2
        command: "PYTHONPATH=. pytest tests/test_public_safety_scan.py -q"
        proves: "Provider-owned focused regression verifies the existing public-safety scanner still enforces local paths, token prefixes, local-only artifacts, and committed-mode release-shape checks."
        acceptance_ids: [AC-5, AC-6]
      - id: REG-3
        command: "PYTHONPATH=. pytest tests/test_gate_inventory.py::test_required_release_artifact_gates_present tests/test_gate_inventory.py::test_gitleaks_gates_are_canonical_and_wired_into_ci -q"
        proves: "Provider-owned focused regression verifies canonical inventory keeps the existing release gates and adds the Gitleaks gates in the expected CI/release surfaces."
        acceptance_ids: [AC-1, AC-2, AC-7]
      - id: REG-4
        command: "PYTHONPATH=. pytest tests/test_quality_scorecard.py::test_live_scorecard_validates tests/test_quality_scorecard.py::test_scorecard_reports_distinct_public_safety_and_gitleaks_coverage -q"
        proves: "Provider-owned focused regression verifies scorecard schema and committed coverage separate public_safety from Gitleaks scanner coverage."
        acceptance_ids: [AC-5, AC-7]
      - id: REG-5
        command: "PYTHONPATH=. pytest tests/test_release_preflight.py::test_evaluate_accepts_matching_tag_and_passing_local_gates tests/test_release_preflight.py::test_evaluate_runs_gitleaks_history_gate_and_surfaces_failure -q"
        proves: "Provider-owned focused regression verifies release preflight still passes normal local gates and now fails closed on a Gitleaks history failure."
        acceptance_ids: [AC-2, AC-6]
      - id: REG-6
        command: "python scripts/gate_inventory.py --check"
        proves: "Provider-owned focused inventory check verifies new gate command strings are present in tracked public surfaces without relying on broad test wrappers."
        acceptance_ids: [AC-1, AC-2, AC-7]
      - id: REG-7
        command: "python scripts/quality_scorecard.py --check"
        proves: "Provider-owned focused scorecard check verifies docs/quality/scorecard.{json,md} are regenerated after adding new tests and scanner coverage fields."
        acceptance_ids: [AC-4, AC-5, AC-7]
      - id: REG-8
        command: "actionlint .github/workflows/ci.yml .github/workflows/publish.yml .github/workflows/gitleaks-history.yml"
        proves: "Provider-owned static workflow check verifies the edited CI, release, and scheduled Gitleaks workflow YAML syntax; hosted runtime remains proven only by actual GitHub workflow triggers."
        acceptance_ids: [AC-1, AC-2, AC-6, AC-7]
      - id: REG-9
        command: "ruff check scripts/gitleaks_scan.py tests/test_gitleaks_scan.py scripts/gate_inventory.py scripts/quality_scorecard.py scripts/release_preflight.py tests/test_gate_inventory.py tests/test_quality_scorecard.py tests/test_release_preflight.py tests/test_workflow_security_gate.py"
        proves: "Provider-owned focused lint check verifies new and edited Python files satisfy the repository Ruff gate."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-10
        command: "ruff format --check scripts/gitleaks_scan.py tests/test_gitleaks_scan.py scripts/gate_inventory.py scripts/quality_scorecard.py scripts/release_preflight.py tests/test_gate_inventory.py tests/test_quality_scorecard.py tests/test_release_preflight.py tests/test_workflow_security_gate.py"
        proves: "Provider-owned focused format check verifies new and edited Python files satisfy the repository Ruff format gate."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
---

## Design Notes

- Keep `scripts/public_safety_scan.py` unchanged as the public release-shape owner. Gitleaks adds maintained credential signatures, entropy detection, and Git-history scanning; it does not become the owner for local paths, provider residue, `.tasks/`, `.protocols/`, `.verify-state`, `.codex-local/`, or `docs/audits/`.
- Add a small repo wrapper rather than embedding workflow-only shell fragments. The wrapper gives tests an injectable runner, one redaction path, one baseline validator, and stable local commands for gate inventory and release preflight.
- Gitleaks configuration should extend the maintained default rule corpus and avoid broad path allowlists. If default Gitleaks coverage lacks one required synthetic class, add the smallest custom rule for that class and document why it is repository-specific.
- Use runtime-generated synthetic fixtures. Tests can assemble strings such as GitHub, PyPI, AWS, private-key, and entropy examples inside a temporary Git repo from harmless tracked fragments, then assert the wrapper expects those classes. Do not commit complete token strings or raw scanner reports.
- Baseline handling starts empty unless implementation discovers verified historical false positives during the first full-history run. If entries are required, store reviewed metadata in `security/gitleaks-baseline.yml` and derive any scanner ignore file from fingerprints only. A finding can be ignored only when metadata includes fingerprint, rationale, owner, and review or expiry condition.
- Changed-range mode should take explicit `--base-ref` and `--head-ref` values. In GitHub Actions, use pull-request base/head SHAs for `pull_request` and before/current SHAs for `push`; an all-zero or unresolvable base must fail closed or fall back to full-history scan, never to a successful empty range.
- Full-history mode should be used by the scheduled workflow and release path only. Those workflows must use `actions/checkout` with `fetch-depth: 0` before scanning so Gitleaks can inspect complete reachable public history.
- Always pass Gitleaks redaction options and summarize only rule id, file, line, commit/fingerprint, and counts. Do not print raw `Secret`, `Match`, unredacted SARIF snippets, or complete generated fixture values.
- Register three canonical gates: changed-range scan for PR/push, full-history scan for release/scheduled, and baseline validation. Keep the command strings short enough that gate_inventory parity can match workflow surfaces with dynamic SHA arguments around them.
- The workflow security gate already enforces full 40-hex SHA pins plus adjacent version comments for external actions, and `.github/dependabot.yml` already schedules weekly GitHub Actions updates. New Gitleaks actions should follow that existing immutable-pin pattern.
- Add the Gitleaks full-history command to `scripts/release_preflight.py` through the existing injectable `run` pattern. The release workflow already uses full-depth checkout; update any CI/package release-preflight caller that now needs history or keep history gated to the tag/release path with an explicit argument covered by tests.
- Regenerate `docs/quality/scorecard.json` and `docs/quality/scorecard.md` after adding the tests and scorecard fields. `python scripts/quality_scorecard.py --check` is a CI gate and will fail on stale committed artifacts.
- Verification command context is based on current project metadata and surfaces: Python 3.11+ pytest project, Ruff-managed `scripts/` and `tests/`, GitHub Actions workflows under `.github/workflows/`, canonical gate inventory in `scripts/gate_inventory.py`, and committed scorecard freshness enforced by `scripts/quality_scorecard.py --check`.
