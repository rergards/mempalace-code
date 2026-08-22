---
slug: MINE-K8S-YAML-SEPARATOR
status: completed
authority: non_authoritative
goal: "Split Kubernetes manifests only on real YAML document separators, not block scalar content."
risk: low
risk_note: "The change is isolated to Kubernetes manifest chunking and focused miner regression tests."
files:
  - path: mempalace/miner.py
    change: "Replace regex-based Kubernetes document splitting with a small YAML-aware splitter that ignores --- lines while inside literal or folded block scalar values."
  - path: tests/test_miner.py
    change: "Add Kubernetes chunking regression tests for ConfigMap/Secret-style block scalars containing --- and for normal top-level document separators."
acceptance:
  - id: AC-1
    when: "_chunk_k8s_manifest processes a ConfigMap whose data value is a literal block scalar containing a line that is exactly ---"
    then: "it returns one ConfigMap chunk and that chunk content still contains the embedded --- line"
  - id: AC-2
    when: "_chunk_k8s_manifest processes a Secret or ConfigMap with a folded block scalar containing an indented --- line followed by another top-level Kubernetes document"
    then: "it returns one chunk for the first resource and one chunk for the following resource, with no extra chunk created from the embedded ---"
  - id: AC-3
    when: "_chunk_k8s_manifest processes the existing three-resource Kubernetes fixture separated by top-level --- lines"
    then: "it still returns exactly the Deployment, Service, and ConfigMap chunks with sequential chunk_index values"
  - id: AC-4
    when: "_chunk_k8s_manifest processes documents separated by empty top-level separators such as --- followed by another ---"
    then: "empty documents continue to be skipped and only real resource chunks are returned"
out_of_scope:
  - "Changing Kubernetes language detection rules."
  - "Changing _extract_k8s_symbol behavior or supported Kubernetes resource kinds."
  - "Replacing PyYAML parsing or adaptive_merge_split for non-Kubernetes YAML."
---

## Design Notes

- Keep the fix local to `_chunk_k8s_manifest`; `chunk_file()` should continue dispatching Kubernetes content the same way.
- Avoid the current regex split because it has no YAML context and treats block scalar payload lines as document boundaries.
- Implement a small line scanner for Kubernetes document boundaries:
  - Split only on top-level `---` separator lines, allowing surrounding whitespace.
  - Track literal and folded block scalar headers (`|`, `>`, and chomping/indent indicators such as `|-`, `>2`) using indentation.
  - While inside a block scalar, treat more-indented content lines, blank lines, and comments as part of the current document; do not split on an embedded `---`.
  - Leave block-scalar mode once indentation returns to the parent level, then resume recognizing real document separators.
- Keep existing empty-document skipping and `chunk_index` re-numbering semantics unchanged.
- Tests should call `_chunk_k8s_manifest()` directly and inspect returned chunk counts, chunk contents, `symbol_name`, `symbol_type`, and `chunk_index` values.
