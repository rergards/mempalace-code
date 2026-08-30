---
slug: REL-MINILM-PUBLIC-CORPUS-PIN
goal: "Make the existing MiniLM compatibility gate self-contained in public squash candidates, with the fixture as its sole semantic authority."
risk: medium
risk_note: "This release-blocking runtime gate already has the correct owner, but fixture parsing and installed-runtime evidence must fail closed without reintroducing Git-history or package-shadow dependencies."
files:
  - path: benchmarks/code_retrieval_bench.py
    change: "Keep the existing installed _FastEmbedder path, remove duplicated fixture facts, reject duplicate JSON keys, and validate the immutable fixture and inert generation provenance through its compact integrity binding."
  - path: tests/test_code_retrieval_bench.py
    change: "Add focused happy, malformed, duplicate-key, provenance, installed-root, bounded-output, and no-history/no-execution coverage around the existing compatibility command."
  - path: benchmarks/README.md
    change: "Document generation_command as inert provenance, the five-text claim boundary, installed-distribution binding, offline cache prerequisite, and bounded recovery behavior."
  - path: docs/quality/scorecard.md
    change: "Regenerate the deterministic human-readable quality scorecard after focused test changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the deterministic machine-readable quality scorecard after focused test changes."
acceptance:
  - id: AC-1
    when: "the installed-application compatibility command runs offline from a fetch-depth-one public squash checkout with the canonical cache prepared"
    then: "it completes without git fetch, git archive, or resolution of an unreachable Git object"
  - id: AC-2
    when: "the compatibility command runs after the exact candidate wheel is installed while checkout source is also importable"
    then: "mempalace_code.storage resolves inside the active installed distribution and _FastEmbedder runs with local_files_only=True"
  - id: AC-3
    when: "the canonical fixture or focused malformed variants are loaded"
    then: "schema, model identifier and revision, dimensions, texts, former vectors, paired cosine, similarity-matrix delta, neighbor order, duplicate keys, non-finite values, and byte drift are accepted only when the complete bound fixture is valid"
  - id: AC-4
    when: "fixture provenance and public documentation are checked"
    then: "generation_command is validated as bound inert data that the release gate never executes, and the documented compatibility claim is limited to five texts"
  - id: AC-5
    when: "the direct command runs against the exact installed wheel with a prepared cache, a missing cache, or a malformed fixture"
    then: "success prints one bounded PASS status, while each failure prints one bounded ERROR status with exactly one actionable recovery command"
  - id: AC-6
    when: "the candidate source and built artifacts pass release-shape inspection"
    then: "they contain one compatibility fixture and no historical source tree, generated benchmark result, credential, external AI client, network fallback, new dependency, or second benchmark owner"
  - id: AC-7
    when: "focused benchmark and embedding-runtime checks plus installed-application contract, artifact, documentation, public-safety, Ruff, scorecard, actionlint, and full non-network gates run"
    then: "every declared check exits zero"
out_of_scope:
  - "Changing the canonical fixture bytes, MiniLM model, revision, cache layout, dimensions, former vectors, compatibility thresholds, or storage embedder owner."
  - "Adding another fixture, benchmark executable, dependency, network recovery path, generated benchmark result, or executable historical package tree."
  - "Changing installer/golden behavior, cache provisioning, release admission topology, or non-MiniLM benchmark modes."
  - "Editing backlog metadata or performing runner-owned staging, commits, pushes, publication, source verification, or release bookkeeping."
contract_policy:
  flow: full_spdd
  reason: "This strict release-blocker hardens an executable compatibility gate and its installed-distribution and fixture-trust boundaries."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
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
      statement: "The existing former-runtime fixture must be the single strict semantic contract and malformed or drifted input must fail closed."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The fixture generation command must remain validated inert provenance and the public claim must stay bounded to five texts."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The direct exact-wheel command must emit one bounded success or actionable failure status."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "The release shape must add no parallel fixture, runtime, network, credential, dependency, historical-tree, or generated-result owner."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "Focused behavior checks and configured release-quality gates must remain green."
      source: "current backlog contract AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "MiniLM compatibility benchmark CLI"
      kind: cli
      paths: ["benchmarks/code_retrieval_bench.py"]
      expected_behavior: "Load the single public fixture strictly, import storage from the installed distribution, embed offline through _FastEmbedder, compare all bound compatibility facts, and emit one bounded result."
    - name: "MiniLM compatibility documentation"
      kind: internal
      paths: ["benchmarks/README.md"]
      expected_behavior: "State the five-text evidence boundary, inert provenance, installed-runtime contour, offline prerequisite, and one-command recovery behavior."
  invariants:
    - id: INV-1
      statement: "The committed minilm_runtime_compatibility_fixture.json bytes and all model, text, vector, and threshold facts remain unchanged."
      applies_to: ["benchmarks/minilm_runtime_compatibility_fixture.json", "benchmarks/code_retrieval_bench.py", "tests/test_code_retrieval_bench.py"]
    - id: INV-2
      statement: "Compatibility embedding continues to use mempalace_code.storage._FastEmbedder(local_files_only=True) without a network fallback."
      applies_to: ["benchmarks/code_retrieval_bench.py", "tests/test_embedding_runtime.py"]
    - id: INV-3
      statement: "The installed-application job retains its one-parent checkout, exact-wheel installation, credential-free cache seed, architecture matrix, and release-required ownership."
      applies_to: [".github/workflows/ci.yml", "tests/test_release_workflow_admission.py"]
    - id: INV-4
      statement: "The historical 469-chunk retrieval result remains historical evidence and is not presented as output of the five-text compatibility gate."
      applies_to: ["benchmarks/retrieval_quality_facts.json", "benchmarks/README.md"]
  risks:
    - id: RISK-1
      risk: "Checkout source can shadow the exact installed wheel and make the gate measure the wrong runtime."
      mitigation: "Preserve compatibility dispatch before checkout path injection, resolve active distribution metadata, and reject storage modules outside that distribution root."
    - id: RISK-2
      risk: "Permissive JSON parsing or duplicated Python constants can create a second semantic owner or silently overwrite fixture facts."
      mitigation: "Reject duplicate keys at every object level, derive texts from the fixture, validate shape and numeric finiteness, and bind the canonical bytes with one compact digest."
    - id: RISK-3
      risk: "The provenance command could be mistaken for a release-gate action or expand the compatibility claim."
      mitigation: "Treat it only as validated fixture data, assert that the gate never executes it, and document the five-text boundary explicitly."
    - id: RISK-4
      risk: "Failure handling can leak dependency exceptions or produce ambiguous recovery guidance."
      mitigation: "Keep one-line BenchError output with one context-specific recovery command and no traceback, vectors, paths, or environment values."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_code_retrieval_bench.py tests/test_embedding_runtime.py tests/test_release_workflow_admission.py -q"
      proves: "Focused happy, failure, and boundary cases cover one-parent execution, installed ownership, strict fixture/provenance handling, bounded output, and the unchanged runtime/workflow contracts."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
    - id: VER-2
      owner: provider
      command: "python benchmarks/code_retrieval_bench.py --check-minilm-runtime-compatibility"
      proves: "After the implementation phase prepares the exact candidate install and canonical cache, the public command executes the real installed FastEmbed runtime offline and emits its bounded compatibility status."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-5]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Public benchmark documentation remains synchronized and preserves the inert-provenance and five-text claim boundary."
      acceptance_ids: [AC-4, AC-7]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist"
      proves: "Built candidate artifacts exclude local-only, historical, generated, and unexpected release members."
      acceptance_ids: [AC-6, AC-7]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "Changed public files contain no credentials, private paths, or local-only evidence."
      acceptance_ids: [AC-6, AC-7]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "Changed tests and existing Python owners satisfy the configured lint gate."
      acceptance_ids: [AC-7]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "Changed tests and existing Python owners satisfy the configured formatting gate."
      acceptance_ids: [AC-7]
    - id: VER-8
      owner: configured_runner
      command: "actionlint .github/workflows/*.yml"
      proves: "The preserved one-parent installed-application workflow remains syntactically valid."
      acceptance_ids: [AC-1, AC-7]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The deterministic quality artifacts match the final source and test inventory."
      acceptance_ids: [AC-7]
    - id: VER-10
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured full suite preserves unrelated package, benchmark, and release behavior."
      acceptance_ids: [AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_code_retrieval_bench.py -q"
        proves: "The complete benchmark-owner test module preserves ordinary retrieval behavior while hardening compatibility parsing and execution."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Rule Zero keeps `benchmarks/code_retrieval_bench.py` as the sole command owner and `benchmarks/minilm_runtime_compatibility_fixture.json` as the sole semantic-data owner. The current tree already removes Git archive/fetch execution, binds imports to the installed distribution, uses local-only `_FastEmbedder`, and runs CI from a one-parent checkout; preserve those foundations and harden only the remaining fixture boundary.
- Remove the `_MINILM_TEXTS` copy from Python. Read the five non-empty texts from the fixture, validate their generic shape and vector count/dimensions, and let the existing SHA-256 binding authenticate the exact canonical bytes, including model facts, texts, vectors, thresholds, neighbor order, and `generation_command`.
- Parse JSON with an object-pairs hook that rejects duplicate keys in top-level and nested objects before normal schema checks. Continue rejecting booleans as numbers, NaN/infinity, missing or extra keys, wrong dimensions/counts, non-normalized vectors, incomplete neighbor permutations, and byte drift.
- Validate `generation_command` as a non-empty string within the digest-bound fixture. Never pass it to `exec`, `eval`, a shell, `subprocess`, an import hook, or another execution surface. Add tests that mutate provenance and inject duplicate keys without editing or copying the canonical fixture.
- Keep compatibility output to one line. Success reports only fixture/model/text-count/dimensions. Missing cache, missing or shadowed install, and malformed or drifted fixture each report one bounded error and one recovery command without tracebacks, vectors, environment data, or repeated guidance.
- Update the existing README paragraph to state that `generation_command` records how former vectors were produced and is never executed by the gate. State that the observable claim covers exactly the five fixture texts and their bound pairwise/neighbor metrics; it does not rerun the historical 469-chunk retrieval benchmark.
- Do not modify the fixture, workflow, retrieval facts, embedding storage owner, dependencies, or release topology. Existing `tests/test_embedding_runtime.py` and `tests/test_release_workflow_admission.py` remain regression evidence for real-cache behavior and the exact-wheel one-parent job.
- Regenerate `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with their existing deterministic writer after the test inventory changes; do not hand-edit metric values.
- Treat c296d37f, 79921474, 2d7b03f4, and 87571bdc as historical evidence only. Reuse none of their unreachable commit pin, Git archive/recovery implementation, historical package tree, duplicated corpus facts, or changelog claim.
- Command context basis: all verification commands run from the repository root. `pyproject.toml` defines pytest and Ruff; `scripts/gate_inventory.py`, `.claude/skills/verify/INSTRUCTIONS.md`, and `.github/workflows/ci.yml` provide the exact configured artifact, docs, public-safety, lint, format, actionlint, scorecard, and full non-network commands. The direct compatibility command runs only after the exact wheel and canonical cache are prepared. No `docs/quality/incident-class-registry.yaml` exists in this checkout, so no incident proof block applies.
- PLAN performed bounded source, fixture, test, workflow, manifest, verification-inventory, documentation, and named historical-commit inspection. It ran no tests, builds, benchmarks, gates, wrappers, network fetches, or release commands.
