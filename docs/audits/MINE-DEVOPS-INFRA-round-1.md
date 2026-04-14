slug: MINE-DEVOPS-INFRA
round: 1
date: 2026-04-14
commit_range: 45d1252..10a1751
findings:
  - id: F-1
    title: "HCL_BOUNDARY regex missing Terraform 1.1+ top-level block types"
    severity: low
    location: "mempalace/miner.py:514"
    claim: >
      HCL_BOUNDARY only covers Terraform 0.x/1.0 block types (resource, data, module,
      variable, output, locals, provider, terraform). Terraform 1.1+ introduced moved {},
      import {} (1.5), check {} (1.5), and removed {} (1.7) as valid top-level blocks.
      Files using only these newer blocks fall back to chunk_adaptive_lines, producing
      less semantically clean splits. Not a crash — the fallback works — but chunking
      quality degrades for modern Terraform codebases.
    decision: backlogged
    backlog_slug: MINE-HCL-BOUNDARY-MODERN

  - id: F-2
    title: "scan_project integration tests missing for .j2/.conf/.ini/.mk/Containerfile/Vagrantfile"
    severity: low
    location: "tests/test_miner.py:1219"
    claim: >
      MINE-DEVOPS-INFRA added scan_project tests for Terraform, Dockerfile, and Makefile
      (AC-1 through AC-3). The remaining new file types — .j2, .jinja2, .conf, .cfg, .ini,
      .mk, Containerfile, and Vagrantfile — have no integration-level scan_project coverage.
      They are covered by detect_language unit tests, but a regression in READABLE_EXTENSIONS
      or KNOWN_FILENAMES for these types would go undetected until a real mine fails.
    decision: backlogged
    backlog_slug: MINE-DEVOPS-SCAN-COVERAGE

  - id: F-3
    title: "chunk_file has two branches that both call chunk_code — redundant elif"
    severity: info
    location: "mempalace/miner.py:697"
    claim: >
      The terraform/hcl branch in chunk_file() is identical to the general code branch
      (both call chunk_code(content, language, source_file)). Merging them would simplify
      the dispatcher with no behavior change.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 2
  dismissed: 1

fixes_applied: []

new_backlog:
  - slug: MINE-HCL-BOUNDARY-MODERN
    summary: "Extend HCL_BOUNDARY to cover Terraform 1.1+ block types (moved, import, check, removed)"
  - slug: MINE-DEVOPS-SCAN-COVERAGE
    summary: "Add scan_project integration tests for .j2/.conf/.ini/.mk/Containerfile/Vagrantfile"
