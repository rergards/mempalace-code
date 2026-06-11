---
slug: RELEASE-PUBLICATION-STATUS-GATE
goal: "Add an executable release-status gate that must pass every public publication surface before a release is called shipped."
risk: medium
risk_note: "Touches release-operator automation, hosted GitHub/PyPI status interpretation, and public release wording; false positives can block releases and false negatives can advertise an incomplete release."
files:
  - path: scripts/release_status_gate.py
    change: "Add a stdlib-only release status gate that checks the expected version against the publish remote tag, branch Tests workflow, Publish to PyPI workflow, GitHub Release metadata, PyPI JSON release files, and an optional fresh no-cache install smoke; emit human and JSON summaries with nonzero exit on any blocker."
  - path: tests/test_release_status_gate.py
    change: "Add mocked unit and CLI tests for all-green status, missing/red public surfaces, version mismatches, draft/prerelease releases, PyPI cache edge cases, install-smoke failures, JSON output, and sanitized blocker reporting."
  - path: .claude/skills/release/SKILL.md
    change: "Replace the ad hoc hosted-status checklist with the release-status gate command and require its pass/fail summary before the skill reports a release as shipped."
  - path: docs/quality/scorecard.json
    change: "Regenerate the deterministic quality scorecard after adding release-status gate tests."
  - path: docs/quality/scorecard.md
    change: "Regenerate the human-readable quality scorecard alongside the JSON artifact."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_release_status_gate.py::test_gate_passes_when_all_public_surfaces_match -q` is run"
    then: "the gate exits successfully only after confirming the requested version is present on the publish remote tag, latest non-draft GitHub Release, PyPI JSON with wheel and sdist files, successful branch Tests workflow, successful Publish to PyPI workflow, and successful no-cache install smoke."
  - id: AC-2
    when: "`python -m pytest tests/test_release_status_gate.py::test_gate_fails_and_lists_blockers_when_public_surfaces_diverge -q` is run"
    then: "any missing tag, red hosted workflow, missing GitHub Release, stale PyPI version, missing distribution file, or failed install smoke produces a nonzero result and a blocker list instead of a shipped summary."
  - id: AC-3
    when: "`python -m pytest tests/test_release_status_gate.py::test_gate_rejects_version_and_release_metadata_edge_cases -q` is run"
    then: "the gate rejects pyproject/requested-version mismatches, draft releases, prerelease releases unless explicitly allowed, and older PyPI latest versions even if some release files exist."
  - id: AC-4
    when: "`python -m pytest tests/test_release_status_gate.py::test_gate_handles_transient_public_lookup_errors_without_private_leaks -q` is run"
    then: "GitHub CLI, git remote, PyPI JSON, and pip smoke lookup errors are reported as sanitized public blockers without raw tokens, local temp paths, or private remotes."
  - id: AC-5
    when: "`python -m pytest tests/test_release_status_gate.py::test_gate_json_output_is_machine_readable_and_surface_complete -q` is run"
    then: "`--json` output contains the overall ok flag, version, and one status row per required public surface so Autopilot or a release operator can gate on it programmatically."
  - id: AC-6
    when: "`rg 'release_status_gate.py|Release status gate|Remaining blockers|not shipped' .claude/skills/release/SKILL.md` is run"
    then: "the release workflow documents the gate command and says a release is not shipped when any blocker remains."
out_of_scope:
  - "Publishing, tagging, bumping versions, creating GitHub Releases, or uploading packages."
  - "Changing GitHub workflow triggers, trusted-publishing credentials, environments, or repository secrets."
  - "Replacing the existing release-prep version and changelog workflow."
  - "Adding network calls to normal mempalace-code user CLI startup or runtime behavior."
  - "Editing docs/BACKLOG.yaml or backlog archives; bookkeep owns backlog completion metadata."
contract_policy:
  flow: full_spdd
  reason: "Strict release/pipeline task where a wrong status claim can publish or advertise an incomplete package."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Release shipped status must be computed from independent public publication surfaces rather than branch CI alone."
      source: "backlog description and AC-1"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "The gate must fail closed with actionable blockers when any public surface is missing, stale, red, or unreachable."
      source: "backlog description and AC-2"
      acceptance_ids: [AC-2, AC-4]
    - id: REQ-3
      statement: "Version and release metadata boundaries must prevent stale, draft, prerelease, or mismatched releases from being reported as shipped."
      source: "CLAUDE.md release-status lesson and AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The release workflow must call the gate and report blockers before using shipped/latest language."
      source: "backlog description and AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-5
      statement: "Machine-readable output must expose every required public surface for operator and Autopilot gating."
      source: "AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Release status gate script"
      kind: cli
      paths: ["scripts/release_status_gate.py"]
      expected_behavior: "Run from the repo root, derive or accept the expected package version, query the publish remote, GitHub Actions, GitHub Release, PyPI JSON, and optional pip install smoke, then exit 0 only when all required public surfaces agree."
    - name: "Release status tests"
      kind: internal
      paths: ["tests/test_release_status_gate.py"]
      expected_behavior: "Mock subprocess and HTTP seams so all public-surface combinations are deterministic and no live GitHub, PyPI, or pip network calls run in unit tests."
    - name: "Release workflow skill"
      kind: internal
      paths: [".claude/skills/release/SKILL.md"]
      expected_behavior: "Instruct release operators to run the gate during hosted verification and to report exact blockers instead of calling a release shipped when the gate fails."
    - name: "Quality scorecard artifacts"
      kind: internal
      paths: ["docs/quality/scorecard.json", "docs/quality/scorecard.md"]
      expected_behavior: "Keep the existing CI scorecard freshness check green after adding the focused release-status tests."
  invariants:
    - id: INV-1
      statement: "The gate is read-only: it must not create tags, push remotes, create releases, upload distributions, edit files, or modify backlog metadata."
      applies_to: ["scripts/release_status_gate.py", ".claude/skills/release/SKILL.md"]
    - id: INV-2
      statement: "Normal end-user CLI commands such as init, mine, search, status, and version-check must not gain release-status network calls."
      applies_to: ["scripts/release_status_gate.py", "mempalace_code/cli.py"]
    - id: INV-3
      statement: "Public status output must avoid private local paths, private remotes, credentials, tokens, raw command environments, and temporary resolver directories."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py", ".claude/skills/release/SKILL.md"]
    - id: INV-4
      statement: "PyPI JSON remains the authoritative package-index check; stale simple-index or pip-index output must not override PyPI JSON evidence."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
    - id: INV-5
      statement: "GitHub Actions runtime status remains a hosted fact; local tests prove parser/gate behavior but not that a future hosted workflow run has completed."
      applies_to: ["scripts/release_status_gate.py", ".claude/skills/release/SKILL.md"]
  risks:
    - id: RISK-1
      risk: "The gate could report shipped when only branch CI is green but PyPI or GitHub Release is stale."
      mitigation: "Require independent status rows for branch Tests, publish workflow, tag, GitHub Release metadata, PyPI JSON files, and install smoke; fail closed on any missing row."
    - id: RISK-2
      risk: "GitHub CLI output shape or unsupported fields could make status checks flaky."
      mitigation: "Use documented `gh run list` and `gh release view` JSON fields, keep parsing isolated, and cover malformed/missing field cases in tests."
    - id: RISK-3
      risk: "Network or PyPI propagation delay could produce ambiguous release state."
      mitigation: "Return explicit transient blockers and prefer PyPI JSON plus no-cache install smoke over `pip index versions`; release operators can rerun the read-only gate after propagation."
    - id: RISK-4
      risk: "A fresh install smoke could be slow or unwanted for diagnostic runs."
      mitigation: "Make install smoke enabled for release-shipped gating by default, but provide an explicit diagnostic-only skip flag whose output cannot be labeled fully shipped."
    - id: RISK-5
      risk: "Status output could leak local paths from subprocess errors."
      mitigation: "Sanitize command errors before rendering and add regression tests that inject fake tokens, private remotes, and temp paths."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_release_status_gate.py::test_gate_passes_when_all_public_surfaces_match -q"
      proves: "All required public surfaces must agree before the gate returns success."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_release_status_gate.py::test_gate_fails_and_lists_blockers_when_public_surfaces_diverge -q"
      proves: "Missing, stale, or red publication surfaces are blocking and visible."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_release_status_gate.py::test_gate_rejects_version_and_release_metadata_edge_cases -q"
      proves: "Version mismatch, draft, prerelease, and older-PyPI boundaries fail closed."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_release_status_gate.py::test_gate_handles_transient_public_lookup_errors_without_private_leaks -q"
      proves: "Lookup failures produce sanitized blockers without private data."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_release_status_gate.py::test_gate_json_output_is_machine_readable_and_surface_complete -q"
      proves: "JSON output exposes every required surface and overall status for automation."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "rg 'release_status_gate.py|Release status gate|Remaining blockers|not shipped' .claude/skills/release/SKILL.md"
      proves: "The release skill invokes the gate and forbids shipped wording while blockers remain."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_release_status_gate.py -q"
        proves: "The focused release-status suite covers success, blocker, edge-case, sanitized-error, and JSON-output behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-2
        command: "python scripts/release_status_gate.py --help"
        proves: "The operator-facing gate exposes a runnable CLI without contacting public services."
        acceptance_ids: [AC-5]
      - id: REG-3
        command: "ruff check scripts/release_status_gate.py tests/test_release_status_gate.py && ruff format --check scripts/release_status_gate.py tests/test_release_status_gate.py"
        proves: "The new script and tests satisfy repository lint and formatting gates."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-4
        command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
        proves: "The new script/tests do not break the repository type gate."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-5
        command: "python scripts/quality_scorecard.py --check"
        proves: "Quality scorecard artifacts were regenerated after adding release-status tests."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-6
        command: "rg 'release_status_gate.py|Release status gate|Remaining blockers|not shipped' .claude/skills/release/SKILL.md"
        proves: "Release workflow documentation continues to use the gate before shipped claims."
        acceptance_ids: [AC-6]
---

## Design Notes

- Use a new stdlib-only script under `scripts/` because this is release-operator tooling, not normal end-user package runtime. The existing `ci.yml` lint job already checks `scripts/`, and `pyproject.toml` config covers `tests/`.
- Command context basis: `pyproject.toml` declares pytest/ruff/pyright dev tooling, `.github/workflows/ci.yml` runs `ruff check mempalace_code/ tests/ scripts/`, and `.github/workflows/publish.yml` names the public publish workflow `Publish to PyPI`.
- Default command shape should be similar to `python scripts/release_status_gate.py --version X.Y.Z --repo rergards/mempalace-code --branch main --remote publish`. It may derive `--version` from `pyproject.toml` when omitted, but explicit version is safer in release logs.
- Required surfaces for a fully shipped result:
  - `git ls-remote --tags <remote> refs/tags/vX.Y.Z` returns the release tag;
  - `gh run list --repo <repo> --branch main --workflow Tests --json ...` finds a completed successful branch run for the release branch or commit;
  - `gh run list --repo <repo> --workflow "Publish to PyPI" --json ...` finds a completed successful publish run for the version tag or release event;
  - `gh release view vX.Y.Z --repo <repo> --json tagName,isDraft,isPrerelease,isLatest,publishedAt,url,targetCommitish` returns the expected tag and non-draft status;
  - `https://pypi.org/pypi/mempalace-code/json` reports `info.version == X.Y.Z` and release files include both wheel and sdist for `X.Y.Z`;
  - fresh install smoke succeeds with `python -m pip install --no-cache-dir mempalace-code==X.Y.Z` in a disposable venv.
- Keep subprocess and HTTP seams injectable. Unit tests should not call live GitHub, PyPI, or pip; live publication verification is the operator's explicit gate run during release.
- Treat install smoke skips as diagnostic-only. If an operator passes a skip flag, the result should mark install smoke as skipped and avoid a fully shipped/ok status unless a separate `--allow-partial` diagnostic mode is used.
- Use PyPI JSON as the authoritative index check. Do not depend on `pip index versions` because prior release work saw cache/simple-index lag after a successful publication.
- Output should have two stable forms: concise human summary for release logs and `--json` with `ok`, `version`, `surfaces`, and `blockers` for automation.
- Sanitization should redact obvious token prefixes, absolute local home/temp paths, and private remote URLs from rendered blocker messages while preserving the public service and high-level failure cause.
- Update `.claude/skills/release/SKILL.md` so Step 6 calls the script first and uses the script's blocker list in the final output. Manual `gh`/PyPI commands can remain as fallback diagnostics, but the release should not be called shipped without the gate passing.
- Regenerate the quality scorecard after adding tests because `python scripts/quality_scorecard.py --check` is part of CI and its metrics depend on tracked test files.
