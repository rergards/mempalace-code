slug: MINE-HELM
round: 1
date: 2026-05-12
commit_range: b675545..HEAD
findings:
  - id: F-1
    title: "_chunk_helm_values silently drops files when all per-section content is below MIN_CHUNK"
    severity: medium
    location: "mempalace_code/mining/chunkers.py:448"
    claim: >
      When a values.yaml has only flat scalar keys (e.g. replicaCount: 3, namespace: production),
      each section is a single line (~15–25 chars), all below MIN_CHUNK=100. After iterating all
      boundaries, all_chunks remains empty and the function returns []. The entire file is silently
      unindexed even though the total file content is well above MIN_CHUNK. Real-world values files
      with simple configuration (no nested maps) are the most affected.
    decision: fixed
    fix: >
      Added a post-boundary fallback: when all_chunks is empty after processing, check if the
      stripped full content is >= MIN_CHUNK and return a single full-file chunk tagged as
      helm_values with empty symbol_name. Added test
      test_chunk_helm_values_small_sections_fallback_to_full_file in tests/test_miner.py to
      confirm the fallback fires for a 187-char values.yaml with 7 flat scalar keys.

  - id: F-2
    title: "_HELM_VALUES_NAME_RE regex defined identically in two modules"
    severity: low
    location: "mempalace_code/mining/languages.py:16, mempalace_code/mining/chunkers.py:14"
    claim: >
      The pattern r"^values.*\.ya?ml$" is compiled separately in both languages.py and
      chunkers.py. Currently identical, but independent definitions could diverge silently
      if one is changed without the other.
    decision: dismissed
    fix: ~

  - id: F-3
    title: "_extract_helm_template_symbol name regex requires exactly 2-space indent"
    severity: info
    location: "mempalace_code/mining/symbols.py:743"
    claim: >
      r"^\s{2}name:\s*(\S+)" matches only metadata.name indented with exactly 2 spaces.
      4-space-indented YAML (unusual but valid) would silently fall back to kind-only symbol.
      Canonical Kubernetes and Helm YAML uses 2-space indent throughout, so this is not a
      practical regression.
    decision: dismissed
    fix: ~

  - id: F-4
    title: "No direct test for .tpl helper file chunking output"
    severity: info
    location: "tests/test_lang_detect.py:test_tpl_file_in_templates_with_chart_root_detects_helm"
    claim: >
      The .tpl detection test verifies language='helm' for _helpers.tpl but does not verify
      that _chunk_helm_template processes it and returns non-empty chunks. The chunking path
      is exercised indirectly through deployment.yaml template tests, and the routing in
      _chunk_helm is trivially correct (neither Chart.yaml nor values*.yaml match → template).
    decision: dismissed
    fix: ~

totals:
  fixed: 1
  backlogged: 0
  dismissed: 3

fixes_applied:
  - "Added full-file fallback in _chunk_helm_values when all per-section content is below MIN_CHUNK; added test test_chunk_helm_values_small_sections_fallback_to_full_file"

new_backlog: []
