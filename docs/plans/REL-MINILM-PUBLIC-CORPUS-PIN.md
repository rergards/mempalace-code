---
slug: REL-MINILM-PUBLIC-CORPUS-PIN
goal: "Pin MiniLM compatibility to a measured corpus commit available from the public repository."
risk: medium
risk_note: "The change is small and stays inside the existing benchmark owner, but incorrect provenance or copied metrics would keep the required exact-wheel release job broken or make its quality evidence false."
files:
  - path: benchmarks/retrieval_quality_facts.json
    change: "Replace the private-only corpus pin with the selected public-history commit and record its freshly measured query count, chunk count, R@5, R@10, measurement date, unchanged headline boundary, and reproduction command."
  - path: benchmarks/code_retrieval_bench.py
    change: "Extend the existing compatibility-contract validation for the measured provenance fields and remove the stale literal 466-chunk help text while preserving public-history refusal, offline execution, and installed-runtime ownership."
  - path: tests/test_code_retrieval_bench.py
    change: "Bind tests to the public pin and freshly measured facts; cover successful validation, unavailable-history refusal, malformed provenance, count and quality drift, installed-runtime delegation, and separation from the 469-chunk headline."
  - path: benchmarks/README.md
    change: "Update the compatibility-corpus count and measured quality wording from the same committed facts while retaining the explicit statement that the 469-chunk headline was not rerun."
acceptance:
  - id: AC-1
    when: "the committed reproduction command runs in a fresh full clone of https://github.com/rergards/mempalace-code.git and the selected pin and superseded private-only SHA are queried with git cat-file"
    then: "the selected commit resolves from public history, the superseded SHA is absent, and no private commit or replacement tree is needed or published"
  - id: AC-2
    when: "the exact candidate wheel is installed in the hosted x64 installed-application job, the established MiniLM cache is seeded, network access is disabled, and python benchmarks/code_retrieval_bench.py --check-minilm-runtime-compatibility runs"
    then: "the historical public corpus is embedded through the active wheel's canonical FastEmbed owner and the command exits zero with PASS MiniLM runtime compatibility"
  - id: AC-3
    when: "the compatibility command measures the selected public corpus and focused fixtures inject an unavailable pin, changed query or chunk counts, or R@5/R@10 below the committed minima"
    then: "the successful output matches the committed measured query count, chunk count, R@5, and R@10; every injected provenance or metric drift fails closed; the 469-chunk headline remains explicitly unrereun; and the hosted x64 installed-application job succeeds"
out_of_scope:
  - "Publishing, grafting, rebasing, or otherwise exposing 3ad086bfd15bab032e86bef3e9deec207c13c17b or its private/local tree."
  - "Changing the canonical MiniLM model, cache layout, FastEmbed owner, query dataset, benchmark algorithm, or installed-application workflow topology."
  - "Replacing measured values with the current source SHA or copying the old 466-chunk values without executing the compatibility benchmark."
  - "Claiming that benchmarks/results_embed_ab_2026-04-09.json or its 469-chunk headline corpus was rerun."
  - "Editing backlog metadata or performing runner-owned commits, pushes, publication, source verification, or release bookkeeping."
contract_policy:
  flow: full_spdd
  reason: "Standard release-quality work changes a measured benchmark contract consumed by an exact-wheel required CI path."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The compatibility corpus pin must resolve from a fresh public clone without publishing the superseded private commit or tree."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The exact installed candidate wheel must run the compatibility benchmark offline against the established seeded MiniLM cache."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The public corpus query count, chunk count, R@5, and R@10 must be freshly measured, committed as provenance, and enforced fail closed without altering the historical 469-chunk claim."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "MiniLM public reproducibility facts"
      kind: store
      paths: ["benchmarks/retrieval_quality_facts.json"]
      expected_behavior: "Own the immutable public corpus pin, exact measured facts, minimum quality gates, reproduction command, and explicit 469-headline non-rerun boundary."
    - name: "MiniLM compatibility benchmark CLI"
      kind: cli
      paths: ["benchmarks/code_retrieval_bench.py"]
      expected_behavior: "Resolve and archive only the pinned public commit, run its miner offline through the active installed distribution, and reject unavailable history or contract drift."
    - name: "MiniLM compatibility documentation"
      kind: internal
      paths: ["benchmarks/README.md"]
      expected_behavior: "Report the measured public-corpus facts and reproduction boundary without changing the separate 469-chunk historical headline."
  invariants:
    - id: INV-1
      statement: "The top-level 469-chunk, R@5 0.95, and R@10 1.0 headline remains historical evidence and public_reproducible_compatibility.headline_469_corpus_rerun remains false."
      applies_to: ["benchmarks/retrieval_quality_facts.json", "benchmarks/README.md", "tests/test_code_retrieval_bench.py"]
    - id: INV-2
      statement: "An unavailable or non-exact commit continues to stop before archive extraction or embedding with one truthful history-recovery command."
      applies_to: ["benchmarks/code_retrieval_bench.py", "tests/test_code_retrieval_bench.py"]
    - id: INV-3
      statement: "Compatibility embedding remains offline and delegates only to mempalace_code.storage._FastEmbedder(local_files_only=True) from the active installed distribution."
      applies_to: ["benchmarks/code_retrieval_bench.py", "tests/test_code_retrieval_bench.py"]
    - id: INV-4
      statement: "The existing x64 installed-application checkout, exact-wheel installation, cache seed, credential-free environment, and release-required dependency remain the execution contour."
      applies_to: [".github/workflows/ci.yml", "tests/test_release_workflow_admission.py"]
  risks:
    - id: RISK-1
      risk: "A locally visible commit could be mistaken for public history again."
      mitigation: "Use 66ff5a61f2c335b3827050df287839f89effb15b as the measured candidate only after confirming it in the fresh public clone's main ancestry; retain the hosted full-history checkout as executable proof."
    - id: RISK-2
      risk: "Counts or recall thresholds could be copied from the superseded corpus instead of measured on the replacement."
      mitigation: "Run the exact compatibility command with the candidate wheel and seeded cache, commit its query/chunk/R@5/R@10 output as distinct measured facts, and bind fixtures and docs to those values."
    - id: RISK-3
      risk: "A generic current-tree update could overwrite the separate 469-chunk historical headline."
      mitigation: "Limit edits to public_reproducible_compatibility, retain headline_469_corpus_rerun=false, and keep an explicit fixture assertion over the top-level headline fields."
  verification:
    - id: VER-1
      owner: provider
      command: "python benchmarks/code_retrieval_bench.py --check-minilm-runtime-compatibility"
      proves: "In the hosted fresh-clone, exact-wheel, seeded-cache, offline context already defined by installed-application, the public pin resolves and the active installed runtime reproduces the committed query count, chunk count, and quality minima."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_code_retrieval_bench.py -q"
      proves: "The focused benchmark contract accepts the measured public corpus, rejects unavailable history and metric drift, uses the installed FastEmbed owner, and preserves the 469-chunk boundary."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_release_workflow_admission.py -q"
      proves: "The hosted installed-application contour still uses full history on x64, installs the exact wheel, seeds the established cache without credentials, runs the compatibility command, and gates release-required."
      acceptance_ids: [AC-2, AC-3]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_code_retrieval_bench.py -q"
        proves: "Existing benchmark modes, recovery wording, contract parsing, installed-runtime delegation, and fail-closed compatibility validation remain intact around the new public pin."
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_release_workflow_admission.py -q"
        proves: "The unchanged required installed-application workflow retains its exact-wheel, offline-cache, x64 full-history, and release admission boundaries."
        acceptance_ids: [AC-2, AC-3]
---

## Design Notes

- Reuse `public_reproducible_compatibility` and `run_minilm_runtime_compatibility`; add no new benchmark script, corpus copy, fixture owner, cache path, or CI job.
- Use `66ff5a61f2c335b3827050df287839f89effb15b` as the bounded replacement candidate. Current repository evidence places it in `publish/main` history and shows it is the earliest public commit containing `benchmarks/embed_ab_bench.py` and `benchmarks/results_embed_ab_2026-04-09.json`. The implementation must confirm the same ancestry from a fresh public clone before recording results.
- Measure through the exact candidate wheel and current compatibility adapter with the established seeded cache and offline variables. Record the observed query count, chunk count, R@5, and R@10; do not assume the old 466/20/0.95/1.0 compatibility values survive the public-tree differences.
- Extend the JSON row with explicit measured R@5/R@10 and measurement date while retaining separate minimum fields for the release gate. The runner should require the complete typed row and compare executable output to exact counts and quality minima.
- Keep the selected commit immutable. A branch name may document reachability during measurement, but it must not replace the commit as corpus identity.
- Preserve the existing missing-history decision: exact `rev-parse <sha>^{commit}` equality is required before archive creation, shallow clones recover with `git fetch --unshallow`, and complete clones name the public repository plus commit.
- Replace the argparse help string's literal `466` with contract-neutral wording so future measured corpus changes cannot leave stale CLI help. Update `benchmarks/README.md` from the committed measurement in the same change.
- The hosted `installed-application` job already supplies the decisive command context: x64 uses `fetch-depth: 0`, builds one wheel, installs that exact wheel, seeds the canonical cache, and runs the compatibility command before the installer matrix. No workflow edit is justified unless implementation finds that current shape no longer matches this inspected contract.
- Tests should keep the current top-level headline assertion and add a direct unavailable-pin seam around `run_minilm_runtime_compatibility`, plus malformed/missing measured-field cases. Do not replace executable benchmark evidence with mocked metric fixtures.
- PLAN inspected manifests, workflow shape, public-tracking refs, benchmark owners, and focused tests. It did not run tests, builds, benchmarks, verification wrappers, network fetches, or release commands.
