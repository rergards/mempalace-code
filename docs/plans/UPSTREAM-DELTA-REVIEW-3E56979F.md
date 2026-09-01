---
slug: UPSTREAM-DELTA-REVIEW-3E56979F
status: completed
authority: non_authoritative
goal: "Refresh the canonical upstream comparison through dfba59b0 by classifying the exact 11-commit delta without importing upstream-only runtime or release behavior."
risk: medium
risk_note: "The task changes release-admission evidence; an omitted surface or overstated fork equivalence could allow v1.13.5 to proceed against an incomplete upstream review."
files:
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Advance the reviewed snapshot, pinned links, exact-range inventory, capability wording, and evidence-backed dispositions through upstream dfba59b0."
  - path: docs/quality/upstream-comparison.json
    change: "Advance the machine-readable pin and mirror the exact source, capability, and disposition evidence for the same range."
acceptance:
  - id: AC-1
    when: "the refreshed manifest and canonical comparison output are inspected"
    then: "the manifest pins develop at dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0, moves 3e56979fb456c7478a4b57414027873bd78f2d37 to previous_commit, uses 2026-08-24 review dates, and updates every pinned source URL and compare ref consistently."
  - id: AC-2
    when: "the immutable 3e56979fb456c7478a4b57414027873bd78f2d37...dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0 range is reconciled with the refreshed comparison output"
    then: "every changed upstream surface has one explicit adopt, already-covered, not-applicable, or defer decision with current fork source or test evidence."
  - id: AC-3
    when: "the upstream sync deletion-corroboration fix is compared with destructive fork commands and owners"
    then: "the absence of a matching sync or prune owner is recorded as not applicable and no speculative implementation is planned."
  - id: AC-4
    when: "the logstream and shared-brain additions plus upstream plugin-count and release-instruction corrections are reconciled with current fork capabilities"
    then: "fork claims and runtime remain unchanged unless an exact existing fork surface requires a factual comparison correction."
  - id: AC-5
    when: "the live comparison guard, documentation drift guard, combined tracked/staged/committed public-safety scan, and focused upstream-comparison tests are run"
    then: "all four commands exit zero for the synchronized dfba59b0 snapshot, while focused guard coverage continues to reject stale pins, malformed live responses, and inconsistent dispositions."
  - id: AC-6
    when: "the implementation command and artifact evidence is inspected"
    then: "it contains no external AI client, credential access, publication action, tag, push, GitHub-setting mutation, or PyPI mutation."
out_of_scope:
  - "Adding sync, prune, logstream, shared-brain, mesh, live-hub, or upstream plugin-manifest runtime to the fork."
  - "Changing scripts/upstream_comparison_guard.py, focused tests, release tooling, or generated quality artifacts unless target-repository validation first proves a required owner change and the plan is revised."
  - "Editing backlog metadata, creating a release candidate commit, moving a public branch, tagging, publishing, or changing GitHub or PyPI settings."
  - "Running upstream code, external AI clients, credential checks, or upstream/fork interoperability benchmarks."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release review controls evidence used to unblock publication and must fail closed on upstream drift or incomplete classification."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Both canonical artifacts must advance from the prior full SHA to the requested live develop SHA with synchronized dates, source links, and compare range."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Every behavior-bearing or claim-bearing surface in the exact 11-commit delta must receive one existing closed-set disposition backed by primary upstream evidence and current fork evidence where applicable."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The sync deletion-corroboration fix must be classified against the fork's actual destructive-command inventory without inventing a sync or prune owner."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Upstream-only logstream, shared-brain, plugin-manifest, and release-document changes must not alter fork runtime or fork capability counts."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The refreshed comparison must satisfy the live, static, documentation, public-safety, and focused fail-closed checks named by the release gate."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "The review must remain read-only outside its two documentation artifacts and use no credentialed, publication, or external-AI operation."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "canonical upstream comparison"
      kind: internal
      paths: ["docs/UPSTREAM_COMPARISON.md"]
      expected_behavior: "Publishes the dfba59b0 snapshot, exact 11-commit range, primary-source links, capability corrections, and one visible disposition per changed surface group."
    - name: "upstream comparison manifest"
      kind: store
      paths: ["docs/quality/upstream-comparison.json"]
      expected_behavior: "Machine-checkably mirrors the snapshot, source links, current capability inventories, and closed-set delta decisions consumed by the existing comparison guard."
  invariants:
    - id: INV-1
      statement: "LanceDB remains the sole fork runtime backend and ChromaDB remains one-way migration input only."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-2
      statement: "The fork continues to advertise 29 direct MCP tools and exactly four tools in its portable minimal Agent Plugin profile; upstream's corrected 44-tool plugin wording is recorded only as an upstream claim."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-3
      statement: "No sync, prune, logstream, shared-brain, mesh, live-hub, or upstream plugin-manifest capability is attributed to the fork without an existing implementation owner and predicate."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-4
      statement: "All upstream claims remain limited to immutable public sources and repository review; the artifacts make no runtime, benchmark, or interoperability claim."
      applies_to: ["docs/UPSTREAM_COMPARISON.md"]
    - id: INV-5
      statement: "The manifest and document advance together, with every tracked source URL pinned to dfba59b0 and the compare URL spanning 3e56979f through dfba59b0."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
  risks:
    - id: RISK-1
      risk: "The 16 changed paths could be collapsed too coarsely and hide one behavior or advertised-surface change."
      mitigation: "Inventory all 11 commits and group every changed path under sync safety, changelog placement, shared-brain guidance, plugin metadata, or release instructions before assigning one disposition."
    - id: RISK-2
      risk: "The upstream deletion fix could be mislabeled as equivalent local protection even though the fork has no matching sync/prune lifecycle."
      mitigation: "Use the existing irrelevant category for the not-applicable fork boundary, record the bounded owner search, and leave local_predicates empty instead of claiming equivalence."
    - id: RISK-3
      risk: "Changing upstream's plugin count from 36 to 44 could accidentally overwrite the fork's independent 29-tool and four-tool claims."
      mitigation: "Update only upstream capability wording and pin fork counts to existing MCP and Agent Plugin tests."
    - id: RISK-4
      risk: "Upstream release instructions could be copied into the fork despite different entry points and package layout."
      mitigation: "Classify the upstream release-doc correction as upstream-only and cite the fork's existing mcp_launcher entry point and packaged minimal-profile contract without changing fork release docs."
    - id: RISK-5
      risk: "A partial pin refresh could leave stale source URLs, dates, compare refs, or document/manifest dispositions."
      mitigation: "Update both owning artifacts atomically and retain the live guard, focused fail-closed tests, docs drift guard, and public-safety gate."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python scripts/upstream_comparison_guard.py --check-live --json"
      proves: "The canonical artifacts agree on the dfba59b0 live pin, previous pin, dates, compare range, pinned sources, capabilities, and all recorded dispositions."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: "PYTHONPATH=. pytest tests/test_upstream_comparison_guard.py -q"
      proves: "Focused hermetic behavior accepts a synchronized snapshot and rejects stale pins, broken compare ranges, stale source links, missing or duplicate decisions, invalid local predicates, live drift, malformed replies, and fetch failure."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The configured documentation gate reports no cross-document contract drift after upstream-only wording and capability evidence are refreshed."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged --committed"
      proves: "The release-scope scan finds no credential-shaped values, private paths, orchestration residue, or unsafe tracked/staged/committed artifact content; the command inventory contains no publication or external-AI operation."
      acceptance_ids: [AC-5, AC-6]
  regression_plan:
    applies: false
    no_behavior_change_exception: "The implementation changes only the canonical comparison document and manifest; it imports no runtime behavior, and the existing focused guard plus configured documentation and public-safety gates cover their fail-closed data contract."
    checks: []
---

## Design Notes

- Use the immutable range `3e56979fb456c7478a4b57414027873bd78f2d37...dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0`. It contains exactly 11 commits and 16 changed paths.
- Preserve the guard's existing categories: `adopted`, `equivalent-local`, `migration-only`, `deferred`, and `irrelevant`. Map the backlog terms `adopt`, `already-covered`, `defer`, and `not-applicable` to those established schema values; do not add synonyms to the manifest.
- Advance `previous_commit` to `3e56979fb456c7478a4b57414027873bd78f2d37`, `commit` to `dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0`, and set both `reviewed_date` and `previous_reviewed_date` to `2026-08-24`. Refresh the compare URL, tree link, every tracked blob URL, capability source, and both document snapshot fields in the same edit.
- Account for the full path inventory in five groups: sync deletion safety (`mempalace/cli.py`, `mempalace/service.py`, `mempalace/sync.py`, `tests/test_sync.py`, `website/reference/mcp-tools.md`); changelog placement (`CHANGELOG.md`); shared-brain/logstream guidance (`website/guide/shared-brain.md`); plugin descriptions (`.claude-plugin/*`, `.codex-plugin/*`, `.cursor-plugin/*` changed in the range); and upstream release instructions (`docs/RELEASING.md`). A changed path may be evidenced by the immutable compare token when it is not promoted into `tracked_source_paths`.
- Classify the sync corroboration change as not applicable through the existing `irrelevant` category. The bounded owner search found no `sync_palace`, `sync --apply`, `removable_ids`, `unresolved_by_source`, or `_classify_drawer` owner under `mempalace_code/`, `tests/`, or `scripts/`. The fork's explicit drawer/wing delete tools and Lance stale-fragment cleanup are direct operator-selected actions; they do not infer deletion from source-file reachability and therefore do not share the upstream sync contract. Record that distinction without representing the upstream fix as `equivalent-local` or `adopted`.
- Keep the shared-brain watcher corrections deferred with the existing no-logstream/no-replication fork stance. The added upstream guidance covers wake filters, separate watcher and inbox cursors, batch replay, NDJSON envelopes, and resume semantics, none of which has a fork runtime owner.
- Correct the upstream plugin capability from 36 to 44 wherever the manifest and document currently attribute 36 to the pinned Codex plugin. Classify the description-only correction as irrelevant to the fork's independent direct/full 29-tool and portable minimal four-tool contracts; do not attach local predicates that imply equivalent implementation.
- Classify the upstream `mcp_proxy` and root `.mcp.json` release-instruction correction as upstream-only. The fork owns `mempalace-code-mcp = mempalace_code.mcp_launcher:main` in `pyproject.toml` and the packaged minimal profile in `mempalace_code/agent_plugin/mcp.json`; this review does not change fork release instructions or plugin layout.
- Retain old delta decisions only when they still describe the current cumulative fork/upstream comparison and their pinned sources are refreshed. Replace prior-range-only rows with the smallest complete set that accounts for this exact range; do not duplicate unchanged capability prose as new decisions.
- If classification reveals a release-critical fork incompatibility with an existing owner, stop before runtime edits and revise the plan with that owner, focused behavioral acceptance, and regression coverage. Do not expand this documentation-only task in place.
- Command context basis: the repository-root stdlib guard is the established comparison owner; `.github/workflows/upstream-drift.yml` owns the exact live command; `tests/test_upstream_comparison_guard.py` is the one focused configured-runner suite; and `scripts/gate_inventory.py` records the documentation and combined release public-safety commands. No package-directory prefix or container workdir is required.
