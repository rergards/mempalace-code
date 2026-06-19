---
slug: AUTOPILOT-DEMO-PUBLIC-SAFETY-COMMITTED-MODE
goal: "Add a committed-tree public-safety scan mode for release checks that inspect HEAD independently of worktree state."
risk: medium
risk_note: "Small standard-library script change, but the git source selection is release-facing and must not confuse HEAD, staged, and worktree snapshots."
files:
  - path: scripts/public_safety_scan.py
    change: "Add an explicit committed-tree source mode that scans blobs and local-only paths from HEAD with redacted failure output."
  - path: tests/test_public_safety_scan.py
    change: "Add focused fixture tests for committed-mode success, redacted failure, deleted-worktree boundary behavior, and tracked/staged compatibility."
  - path: docs/quality/README.md
    change: "Document when to use tracked/staged scans versus committed-tree scans for release readiness."
  - path: .claude/skills/release/SKILL.md
    change: "Add the committed-tree public-safety scan to the release verification checklist before publishing or after merge."
acceptance:
  - id: AC-1
    when: "python scripts/public_safety_scan.py --committed is run in a repository whose HEAD contains no public-safety hits"
    then: "the command exits 0 and prints an OK summary naming committed mode and the committed file snapshot count."
  - id: AC-2
    when: "HEAD contains a secret-like token or a local-only artifact path"
    then: "python scripts/public_safety_scan.py --committed exits non-zero and reports only source, line, column, and rule id without printing the matched secret or path content."
  - id: AC-3
    when: "a tracked local-only path exists in HEAD but the worktree copy has been deleted"
    then: "python scripts/public_safety_scan.py --tracked exits 0 while python scripts/public_safety_scan.py --committed exits non-zero for the committed path."
  - id: AC-4
    when: "release and quality documentation are inspected"
    then: "they show --tracked --staged as the pre-commit scan and --committed as the before-release or after-merge scan."
out_of_scope:
  - "CHANGELOG.md updates; changelog and bookkeep automation own task completion notes."
  - "Backlog metadata edits or archive changes."
  - "Quality scorecard metric expansion for public-safety coverage fields; that is a separate P2 backlog item."
  - "Adding committed-tree mode to every edit-time /verify or CI lint run unless a future task decides that cost and semantics are appropriate."
contract_policy:
  flow: full_spdd
  reason: "Strict Autopilot task with a release-verification behavior change and public-safety failure semantics."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The public-safety scan must support an explicit mode that scans exactly the committed tree at HEAD."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: REQ-2
      statement: "The existing tracked and staged scan behavior must remain available for pre-commit use."
      source: "backlog acceptance"
      acceptance_ids: [AC-3, AC-4]
    - id: REQ-3
      statement: "Committed-tree public-safety failures must remain redacted to rule id and file position."
      source: "backlog acceptance"
      acceptance_ids: [AC-2]
    - id: REQ-4
      statement: "Release-facing docs must distinguish pre-commit tracked/staged scans from committed-tree release scans."
      source: "backlog acceptance"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "public-safety scan CLI"
      kind: cli
      paths: ["scripts/public_safety_scan.py"]
      expected_behavior: "Add a --committed source selector that reads paths and blobs from HEAD, prefixes hit sources as committed:<path>, and keeps existing --tracked/--staged semantics."
    - name: "public-safety scan tests"
      kind: internal
      paths: ["tests/test_public_safety_scan.py"]
      expected_behavior: "Cover clean committed HEAD success, committed leak rejection, deleted-worktree boundary behavior, and no regression to staged redaction checks."
    - name: "quality documentation"
      kind: internal
      paths: ["docs/quality/README.md"]
      expected_behavior: "Explain that --tracked --staged is the edit-time/pre-commit check and --committed is the release-readiness check for HEAD after merge."
    - name: "release workflow docs"
      kind: internal
      paths: [".claude/skills/release/SKILL.md"]
      expected_behavior: "Require the committed-tree public-safety scan as a release verification step before publishable release claims."
  invariants:
    - id: INV-1
      statement: "Existing --tracked and --staged flags must keep scanning worktree and index snapshots and must remain combinable as today."
      applies_to: ["scripts/public_safety_scan.py", "tests/test_public_safety_scan.py"]
    - id: INV-2
      statement: "Failure output must not print matched secret values, absolute local paths, or raw leak snippets."
      applies_to: ["scripts/public_safety_scan.py", "tests/test_public_safety_scan.py"]
    - id: INV-3
      statement: "The scan script must remain standard-library only and runnable from the repository root with python."
      applies_to: ["scripts/public_safety_scan.py", "docs/quality/README.md", ".claude/skills/release/SKILL.md"]
  risks:
    - id: RISK-1
      risk: "Using worktree file reads for committed mode would miss or falsely include uncommitted changes."
      mitigation: "Read committed paths and blobs through git HEAD objects, and test the deleted-worktree boundary."
    - id: RISK-2
      risk: "Tests that commit fixture data can fail on machines without global git author config."
      mitigation: "Use per-command git -c user.name and -c user.email options in fixture commits."
    - id: RISK-3
      risk: "Release docs could make the committed scan look like a replacement for pre-commit staged scanning."
      mitigation: "Document both commands side by side with distinct use cases."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_public_safety_scan.py -q"
      proves: "Focused behavior for committed HEAD success, redacted committed failures, deleted-worktree boundary behavior, and tracked/staged compatibility from the repo-root pytest configuration."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      command: "python scripts/public_safety_scan.py --committed"
      proves: "The release-facing CLI mode runs from the repo root against the current HEAD and reports committed-mode OK output on a public-safe tree."
      acceptance_ids: [AC-1]
    - id: VER-3
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The existing pre-commit public-safety command remains runnable and public-safe after the change."
      acceptance_ids: [AC-4]
    - id: VER-4
      command: "rg -n \"[-][-]committed\" docs/quality/README.md && rg -n \"[-][-]committed\" .claude/skills/release/SKILL.md"
      proves: "Both release-facing docs reference the new --committed mode. The bracketed pattern matches the literal --committed flag, which is absent from both files in the pre-change tree, so a passing check distinguishes the documented post-change state from today's repository (the old alternation passed on the unchanged repo because --tracked --staged already appears in docs/quality/README.md)."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "rg -n \"before release|after merge|release readiness|release-readiness\" docs/quality/README.md .claude/skills/release/SKILL.md"
      proves: "The committed-tree scan is documented as the before-release/after-merge release-readiness check alongside the pre-commit --tracked --staged scan. This framing text is absent from the pre-change tree, so the check fails until AC-4's use-case distinction is actually written."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_public_safety_scan.py -q"
        proves: "Focused regression coverage for committed-mode clean-HEAD success (the OK summary naming committed mode and the snapshot count), existing staged leak detection, and redacted output, while adding committed-mode cases. Running the whole file re-asserts the committed-mode success test that proves AC-1."
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-2
        command: "python scripts/public_safety_scan.py --tracked --staged"
        proves: "The original edit-time scan command still passes on the repository after implementation."
        acceptance_ids: [AC-4]
---

## Design Notes

- Implement `--committed` as another source selector in `scripts/public_safety_scan.py`; when used alone it scans exactly `HEAD`, independent of staged and unstaged files.
- Use git object reads for committed mode: enumerate committed paths from `git ls-tree -r -z --name-only HEAD` and read content with `git show HEAD:<path>` or an equivalent HEAD-object command. Do not read committed-mode bytes from the worktree.
- Keep hit summaries redacted and consistent with existing output, using `committed:<relative-path>:line:column: rule-id`.
- Run path-policy checks against committed relative paths before blob reads so committed `.tasks/`, `.protocols/`, `.codex-local/`, `.verify-state`, and `docs/audits/` paths fail even when their contents are otherwise harmless.
- Add fixture commits with explicit per-command git author config so tests do not depend on global developer machine settings.
- The command context basis is current repo metadata: `pyproject.toml` configures pytest under `tests/`, and `scripts/public_safety_scan.py` is a standard-library script invoked from the repository root. The planned verification commands intentionally do not use package installation or network access.
- Do not wire `--committed` into `.github/workflows/ci.yml` or `.claude/skills/verify/INSTRUCTIONS.md` in this task. Existing `--tracked --staged` remains the edit-time gate; release docs get the committed-tree command for publishable HEAD checks.
