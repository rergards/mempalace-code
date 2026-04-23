---
slug: MINE-HCL-BOUNDARY-MODERN
goal: "Treat Terraform 1.1+ moved/import/check/removed blocks as HCL chunk boundaries"
risk: low
risk_note: "Single additive regex expansion with focused tests; existing fallback behavior for non-block HCL/Terraform content should remain unchanged."
files:
  - path: mempalace/miner.py
    change: "Add moved, import, check, and removed to HCL_BOUNDARY so modern Terraform top-level blocks participate in regex structural chunking."
  - path: tests/test_chunking.py
    change: "Add Terraform/HCL chunking tests for modern block boundaries and no-boundary fallback behavior."
acceptance:
  - id: AC-1
    when: "A padded .tf fixture containing top-level moved, import, check, and removed blocks is passed to chunk_code(..., 'terraform', 'main.tf')"
    then: "The result contains separate chunks whose stripped contents start with each of moved, import, check, and removed."
  - id: AC-2
    when: "A padded .tf fixture mixes legacy resource/module/output blocks with modern moved/import/check/removed blocks"
    then: "chunk_code(..., '.tf', 'main.tf') preserves all legacy and modern block starts as structural split points."
  - id: AC-3
    when: "A .tfvars-style assignment-only fixture with no top-level HCL block keywords is passed to chunk_code(..., 'terraform', 'terraform.tfvars')"
    then: "The output matches chunk_adaptive_lines() for the same content and does not split on assignment names such as moved or import."
out_of_scope:
  - "Tree-sitter parsing for HCL or Terraform."
  - "Symbol extraction for Terraform/HCL blocks."
  - "Changing Terraform language detection, scan_project coverage, or supported language lists."
  - "Reworking adaptive_merge_split sizing thresholds."
---

## Design Notes

- Update only `HCL_BOUNDARY`; keep the existing `get_boundary_pattern()` mapping unchanged because Terraform, `.tf`, `.tfvars`, HCL, and `.hcl` already route to this pattern.
- Add the new keywords to the same alternation as the existing Terraform top-level blocks: `resource`, `data`, `module`, `variable`, `output`, `locals`, `provider`, and `terraform`.
- Keep the `\s+` requirement after the keyword so similarly named identifiers such as `moved_block` or assignment keys in `.tfvars` do not become boundaries.
- Use padded fixtures above `TARGET_MIN` in tests so `adaptive_merge_split()` keeps each detected top-level block visible as an independent chunk.
- Cover the failure/no-match path by comparing assignment-only `.tfvars` content with `chunk_adaptive_lines()`, confirming the regex expansion does not introduce false semantic boundaries.
