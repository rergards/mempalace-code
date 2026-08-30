---
slug: REL-MINILM-PUBLIC-CORPUS-PIN
goal: "Make the existing MiniLM compatibility command run offline from the public fixture and the exact installed candidate distribution without Git-history inputs."
risk: medium
risk_note: "The change removes an unreachable release input, but import isolation, strict fixture validation, and actionable failures must remain correct in the required exact-wheel job."
files:
  - path: benchmarks/code_retrieval_bench.py
    change: "Replace Git archive and historical-code execution with strict validation of the existing compatibility fixture and direct local-only embedding through storage imported from the active installed distribution."
  - path: benchmarks/retrieval_quality_facts.json
    change: "Remove the obsolete public_reproducible_compatibility block that names the unreachable commit and historical corpus contract."
  - path: benchmarks/README.md
    change: "Document the self-contained former-runtime fixture check, installed-distribution binding, offline cache prerequisite, and one-command recovery behavior."
  - path: .github/workflows/ci.yml
    change: "Make installed-application use a one-parent checkout for both architectures while retaining exact-wheel installation, cache seeding, and the existing compatibility command."
  - path: tests/test_code_retrieval_bench.py
    change: "Replace historical-archive tests with fixture-schema, metric-drift, installed-root, offline, bounded-output, missing-cache, and malformed-fixture command coverage."
  - path: tests/test_release_workflow_admission.py
    change: "Bind the installed-application contract to a one-parent checkout and the unchanged exact-wheel, credential-free compatibility step."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic quality scorecard after the test changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable quality scorecard after the test changes."
acceptance:
  - id: AC-1
    when: "python benchmarks/code_retrieval_bench.py --check-minilm-runtime-compatibility runs from a clean one-parent public squash checkout with the canonical cache prepared and network access disabled"
    then: "the command completes without git fetch, git archive, or resolution of an unreachable Git object"
  - id: AC-2
    when: "the compatibility command runs after the candidate wheel is installed while the checkout also contains mempalace_code source"
    then: "mempalace_code.storage resolves inside the installed candidate distribution and _FastEmbedder runs with local_files_only=True"
  - id: AC-3
    when: "the committed compatibility fixture is loaded or a focused case changes its schema, model identifier, revision, dimensions, texts, former vectors, paired cosine threshold, similarity-matrix delta, or neighbor order"
    then: "the unchanged fixture is accepted and every malformed or drifted bound fact fails closed"
  - id: AC-4
    when: "the direct compatibility command runs against the exact installed wheel with a prepared cache, a missing cache, or a malformed fixture"
    then: "success prints one bounded PASS status, while each failure prints one bounded ERROR status with exactly one actionable recovery command"
  - id: AC-5
    when: "the candidate source and built artifacts are inspected after the change"
    then: "they contain the single existing fixture and no historical source tree, generated benchmark result, credential, external AI client, network fallback, new dependency, or second benchmark owner"
  - id: AC-6
    when: "focused benchmark, embedding-runtime, and workflow-contract checks plus the configured artifact, documentation, public-safety, Ruff, scorecard, actionlint, and full non-network gates run on the candidate"
    then: "every declared check exits zero"
out_of_scope:
  - "Changing the canonical MiniLM model, revision, cache layout, dimensions, compatibility thresholds, fixture contents, or FastEmbed storage owner."
  - "Adding a fixture, benchmark executable, dependency, network recovery path, generated benchmark result, or executable historical package tree."
  - "Changing installer/golden behavior, cache provisioning, release admission topology, or non-MiniLM benchmark modes."
  - "Editing backlog metadata or performing runner-owned staging, commits, pushes, publication, source verification, or release bookkeeping."
contract_policy:
  flow: full_spdd
  reason: "This standard release-blocker changes an executable compatibility gate and its installed-distribution boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Compatibility execution must be self-contained in a one-parent public checkout and independent of Git history."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Compatibility embedding must use the exact installed candidate storage owner in local-files-only mode."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The existing former-runtime fixture must be the complete strict compatibility contract."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The direct command must emit one bounded success or actionable failure status."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The release shape must add no parallel fixture, runtime, network, credential, dependency, or generated-result owner."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Focused and configured release-quality gates must remain green."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "MiniLM compatibility benchmark CLI"
      kind: cli
      paths: ["benchmarks/code_retrieval_bench.py"]
      expected_behavior: "Load and validate the existing public fixture, bind imports to the installed distribution, embed offline through _FastEmbedder, and emit one bounded result."
    - name: "MiniLM retrieval facts"
      kind: store
      paths: ["benchmarks/retrieval_quality_facts.json"]
      expected_behavior: "Retain historical benchmark headline facts without carrying the obsolete executable Git-history compatibility contract."
    - name: "Installed-application compatibility step"
      kind: internal
      paths: [".github/workflows/ci.yml"]
      expected_behavior: "Prove the compatibility command from a one-parent checkout after exact-wheel installation and canonical cache preparation."
    - name: "MiniLM compatibility documentation"
      kind: internal
      paths: ["benchmarks/README.md"]
      expected_behavior: "Describe the public fixture, offline installed-runtime contour, bounded output, and recovery commands truthfully."
  invariants:
    - id: INV-1
      statement: "The committed minilm_runtime_compatibility_fixture.json bytes, model identity, revision, dimensions, former vectors, and thresholds remain unchanged."
      applies_to: ["benchmarks/minilm_runtime_compatibility_fixture.json", "tests/test_code_retrieval_bench.py"]
    - id: INV-2
      statement: "The historical 469-chunk benchmark headline remains historical evidence and is not claimed as a rerun by the compatibility command."
      applies_to: ["benchmarks/retrieval_quality_facts.json", "benchmarks/README.md"]
    - id: INV-3
      statement: "Compatibility embedding uses mempalace_code.storage._FastEmbedder(local_files_only=True) and performs no network fallback."
      applies_to: ["benchmarks/code_retrieval_bench.py", "tests/test_code_retrieval_bench.py"]
    - id: INV-4
      statement: "The installed-application job retains exact-wheel installation, credential-free cache seeding, both architecture rows, and release-required ownership."
      applies_to: [".github/workflows/ci.yml", "tests/test_release_workflow_admission.py"]
  risks:
    - id: RISK-1
      risk: "Executing the repository script can prepend checkout source and silently measure it instead of the wheel."
      mitigation: "Select compatibility mode before repository-path injection, resolve distribution metadata, and fail unless imported storage is contained by that distribution root."
    - id: RISK-2
      risk: "A permissive fixture reader can accept partial, mistyped, non-finite, or dimensionally inconsistent evidence."
      mitigation: "Validate the exact schema and types, reject booleans as numbers, require finite normalized vectors and dimensions/count consistency, and compare all bound compatibility metrics and order."
    - id: RISK-3
      risk: "Removing historical execution can leave stale Git-history promises in facts, docs, tests, or checkout configuration."
      mitigation: "Delete the obsolete facts block and archive helpers, update the single documentation paragraph, make checkout depth one, and assert absence of Git archive/fetch behavior."
    - id: RISK-4
      risk: "Raw dependency exceptions or fixture details can produce noisy, non-actionable release logs."
      mitigation: "Map missing cache and fixture failures to bounded BenchError messages with one context-free recovery command each."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_code_retrieval_bench.py tests/test_embedding_runtime.py tests/test_release_workflow_admission.py -q"
      proves: "The focused happy, failure, and boundary cases cover fixture binding, local-only installed ownership, one-parent workflow shape, and bounded recovery output."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: provider
      command: "python benchmarks/code_retrieval_bench.py --check-minilm-runtime-compatibility"
      proves: "With the implementation-phase prepared cache and exact candidate install, the public command executes the real FastEmbed runtime offline and emits its bounded compatibility status."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist"
      proves: "The configured artifact gate accepts the built candidate and excludes local-only or unexpected release members."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Public benchmark and release documentation remain synchronized with canonical commands."
      acceptance_ids: [AC-6]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "Changed public files contain no credential, private path, or local-only evidence."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "Python benchmark and test changes satisfy the configured lint gate."
      acceptance_ids: [AC-6]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "Python benchmark and test changes satisfy the configured formatting gate."
      acceptance_ids: [AC-6]
    - id: VER-8
      owner: configured_runner
      command: "actionlint .github/workflows/*.yml"
      proves: "The one-parent installed-application workflow remains syntactically valid."
      acceptance_ids: [AC-1, AC-6]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The deterministic quality artifacts match the final source and test inventory."
      acceptance_ids: [AC-6]
    - id: VER-10
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured full suite preserves unrelated package and release behavior."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/test_code_retrieval_bench.py tests/test_embedding_runtime.py tests/test_release_workflow_admission.py -q"
        proves: "The complete focused slice preserves normal retrieval modes, real-cache compatibility, and installed-application admission around the rewritten command."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Rule Zero selects replacement inside `benchmarks/code_retrieval_bench.py`: the existing fixture already contains the former-runtime vectors and all compatibility thresholds, so the Git archive, temporary historical source tree, sentence-transformers adapter, and history-recovery helper are superseded owners to delete.
- Dispatch compatibility mode before adding the repository root to `sys.path`. Normal benchmark modes keep their existing source-checkout imports. Compatibility mode imports `mempalace_code.storage` through the installed distribution, resolves both paths, and refuses any storage module outside the distribution package root.
- Load only `benchmarks/minilm_runtime_compatibility_fixture.json`. Validate exact top-level and nested keys; schema version; canonical model alias, identifier, revision, and sequence length; `normalized: true`; five non-empty texts; 384 dimensions; five finite numeric vectors of exactly 384 values; and complete neighbor-order permutations. Treat booleans, NaN, infinity, missing/extra fields, duplicate neighbors, and shape drift as malformed.
- Compute current vectors once with `_FastEmbedder(local_files_only=True)`. Require finite 384-dimensional normalized vectors, minimum paired cosine, maximum full similarity-matrix delta, and exact deterministic neighbor order with index tie-breaking. The command must not write a benchmark result.
- Keep CLI output to one line. Success reports `PASS MiniLM runtime compatibility` with bounded fixture/model/count/dimension facts. Missing-cache failure reports one `mempalace-code fetch-model` recovery command; malformed or drifted committed-fixture failure reports one `git restore benchmarks/minilm_runtime_compatibility_fixture.json` recovery command. Do not echo raw dependency tracebacks, vectors, paths, environment values, or repeated recovery text.
- Remove `public_reproducible_compatibility` from `benchmarks/retrieval_quality_facts.json`; the top-level 2026-04-09 metrics remain untouched. Update the existing README compatibility paragraph to name the fixture-based check and stop claiming full history or a reconstructed 466-chunk corpus.
- Set installed-application checkout `fetch-depth: 1` for both matrix rows. Keep the current exact wheel install, fixture-keyed cache, credential-free seed, x64 compatibility execution, and downstream installer/golden ordering. Update the focused workflow test to reject architecture-dependent full history.
- Use temporary mutated fixture copies in tests; do not edit or duplicate the canonical fixture. Subprocess coverage should construct competing checkout and installed-package roots and prove that storage comes from the installed root even when checkout source is importable.
- Compare evidence: c296d37f and 79921474 hardened the wrong owner by moving the pin and validating historical-corpus facts; 2d7b03f4 only documented that approach; 87571bdc removed its plan. Reuse none of their commit pin, archive path, adapter, measured corpus facts, or changelog claim.
- Command context basis: all commands run from repository root. `pyproject.toml` declares pytest and Ruff; `scripts/gate_inventory.py`, `.claude/skills/verify/INSTRUCTIONS.md`, and `.github/workflows/ci.yml` provide the exact configured artifact, docs, public-safety, lint, format, actionlint, scorecard, and full non-network commands. The direct compatibility command runs only after the candidate wheel and canonical cache are prepared. No incident-class registry exists in this checkout, so no incident proof block applies.
- PLAN performed bounded source, manifest, workflow, fixture-shape, test, and named historical-commit inspection. It ran no tests, builds, benchmarks, gates, wrappers, network fetches, or release commands.
