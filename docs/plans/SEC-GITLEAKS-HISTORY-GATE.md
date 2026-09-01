---
slug: SEC-GITLEAKS-HISTORY-GATE
status: active
authority: non_authoritative
goal: "Restore compact machine-checked suppression governance and real-binary detector/redaction assurance without changing the native Gitleaks scan owner."
risk: high
risk_note: "A false negative can admit leaked credentials; unsafe fixture retention can create a new secret-shaped artifact."
files:
  - path: .gitleaksignore
    change: "Add strict machine-readable review metadata immediately before every existing exact fingerprint without changing fingerprint values."
  - path: scripts/gitleaks_scan.py
    change: "Validate exact suppressions and config before every scan; add explicit validate-baseline and disposable five-class fixture-smoke commands."
  - path: tests/test_gitleaks_scan.py
    change: "Cover generic metadata parsing, forbidden broad suppressions, pre-scan ordering, five-class SARIF proof, cleanup, and workflow ordering."
  - path: .github/workflows/ci.yml
    change: "Run fixture-smoke after the pinned installer and before the changed-range scan."
  - path: .github/workflows/gitleaks-history.yml
    change: "Run fixture-smoke after the pinned installer and before the scheduled full-history scan."
  - path: .github/workflows/publish.yml
    change: "Run fixture-smoke after the pinned installer and before the release full-history scan."
  - path: scripts/quality_scorecard.py
    change: "Inventory validate-baseline, fixture-smoke, reviewed metadata, and five-class fixture coverage."
  - path: docs/quality/scorecard.json
    change: "Regenerate from the scorecard owner."
  - path: docs/quality/scorecard.md
    change: "Regenerate from the scorecard owner."
  - path: docs/BACKLOG.yaml
    change: "Keep the release blocker open and update it to the compact implementation and remaining qualification truth."
acceptance:
  - id: AC-1
    text: "Every repository scan validates .gitleaksignore metadata and .gitleaks.toml suppression policy before invoking Gitleaks."
  - id: AC-2
    text: "Each native suppression is one exact fingerprint immediately preceded by strict JSON metadata with nonempty owner and rationale plus a review_condition or nonexpired ISO expiry."
  - id: AC-3
    text: "Orphan, incomplete, duplicate, expired, malformed, globbed, regex/broad, rule-disabled, or allowlisted suppression state fails closed with bounded diagnostics."
  - id: AC-4
    text: "fixture-smoke accepts Gitleaks exit 1 only when redacted SARIF proves the PyPI, GitHub, AWS access-key, private-key, and mempalace-high-entropy-assignment files and rule ids."
  - id: AC-5
    text: "Fixture source, Git worktree, and SARIF live in one TemporaryDirectory outside the checkout and upload paths; cleanup occurs on success and failure, and complete generated values never enter retained SARIF or logs."
  - id: AC-6
    text: "CI, scheduled history, and publish run fixture-smoke after the existing pinned installer and before their repository scan; validate-baseline remains manual and is not a standalone workflow step."
  - id: AC-7
    text: "Exact-ref validation, shallow-history rejection, changed-range and full-history semantics, pinned installation, native ignore use, redaction, SARIF uploads, bounded output, and all other release gates remain in place."
---

# Compact reviewed plan

## Outcome

The existing native launcher regains the two missing assurance predicates: reviewed exact-fingerprint suppressions and a real-binary five-class detector/redaction smoke. Parent qualification decides closure; the backlog item remains active until required local and hosted evidence is complete.

## Rule Zero evidence

- Behavioral owner: `scripts/gitleaks_scan.py` already constructs every repository scan, applies native `.gitleaksignore`, requests full redaction, and writes SARIF.
- Suppression owner: `.gitleaksignore` already carries native exact fingerprints consumed directly by Gitleaks. Adjacent JSON comments add review state without a second baseline or derivation step.
- Workflow owners: the existing CI, scheduled-history, and publish jobs already install the pinned binary and run their repository scan. One fixture step in each preserves ordering and release topology.
- Inventory owner: `scripts/gate_inventory.py` already owns quality/release command strings and verify surfaces. The scorecard consumes those gates instead of creating a second registry.
- Delete/simplify comparison: leaving the compact launcher unchanged omits two current acceptance predicates. Restoring the old wrapper or deleted release machinery adds parallel state, dependencies, and release owners.
- Extend/replace comparison: bounded functions in the existing launcher reuse its runner, paths, redaction flags, and error contract. Replacement has greater regression and removal cost with no acceptance benefit.
- Architecture boundary: no new service, durable store, dependency, scanner, workflow, credential route, or publication route is introduced.
- Rollback/removal: the added commands, metadata comments, tests, and three workflow steps are local and reversible. Native fingerprint values and scan commands remain stable.

## Implementation

1. Parse `.gitleaks.toml` with stdlib `tomllib`; reject imported `[extend].path` or `[extend].url` sources before recursively rejecting allowlist and rule-disablement capability.
2. Parse `.gitleaksignore` generically. Require physical adjacency between one strict metadata object and one exact fingerprint; validate all fields, expiry, path shape, and uniqueness.
3. Call that validator before artifact creation and before every repository or fixture Gitleaks invocation. Expose the same validator as `validate-baseline` for manual use only.
4. Generate five non-live values and PEM markers at runtime, write one class per file in a disposable Git repository, and invoke the installed binary with the repository config, native ignore file, full redaction, and SARIF output.
5. Treat scanner exit 1 as provisional. Bound and parse SARIF, reject complete generated values, and require every filename plus its expected rule id before success.
6. Run `fixture-smoke` immediately after the existing installer in all three workflows. Keep fixture data outside `${{ runner.temp }}/gitleaks/**`, the only Gitleaks artifact upload contour.
7. Register both assurance commands in `scripts/gate_inventory.py`; put fixture-smoke on the verify surface, keep validate-baseline manual, and make the scorecard consume the canonical commands.
8. Extend focused tests, regenerate scorecards, and update the active backlog truth.

## Drunk-user and drunk-LLM path

- Current status: `validate-baseline` reports suppression policy; `fixture-smoke` reports detector/redaction health; repository scan modes retain their current output.
- One action: run `python scripts/gitleaks_scan.py validate-baseline` before reviewing a suppression change, or run `python scripts/gitleaks_scan.py fixture-smoke` after installing Gitleaks.
- Authority: the commands read repository policy and create only disposable fixture state; they do not modify Git history, credentials, remotes, or release state.
- Recovery: fix the named metadata/config line or reinstall the version pinned by `tools/gitleaks/go.mod`, then rerun the same command.
- Retry safety: fixture state has one temporary owner and is removed by context-manager cleanup on every return or exception.

## Cheapest falsifiers

1. Insert an unreviewed or globbed fingerprint in a temporary test root. `validate_baseline` must fail before `_run` or artifact creation.
2. Add an imported config, allowlist, or disabled rule to a temporary config. Validation must fail before Gitleaks.
3. Run the installed real binary with `fixture-smoke`. Exit 1 is accepted only after all five filename/rule pairs appear in redacted SARIF.
4. Remove one SARIF result or insert one complete generated value in mocked SARIF. The command must fail with a bounded diagnostic and remove its temporary root.
5. Statistically inspect each workflow: installer index must precede fixture-smoke, which must precede the repository scan; `validate-baseline` must be absent.

## Verification boundary

Implementation verification runs focused pytest, real `validate-baseline`, real `fixture-smoke`, a safe reachable changed range, Actionlint, focused Ruff check and format check, scorecard freshness, public safety, and targeted scorecard tests. Full history, the full non-network suite, and hosted workflow execution remain parent qualification to avoid duplicate release work. A local Gitleaks version may differ from the `tools/gitleaks/go.mod` pin and must be reported; workflow installation remains authoritative for hosted evidence.

## Forbidden restoration

Do not restore the former wrapper, `security/gitleaks-baseline.yml`, PyYAML, `release_direct_application_gate.py`, `workflow_security_gate.py`, or any deleted release machinery. Do not add credential access, external AI-client execution, a second workflow, a second scanner owner, broad allowlists, or changed fingerprint values.
