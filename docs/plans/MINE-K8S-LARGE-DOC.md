---
slug: MINE-K8S-LARGE-DOC
status: completed
authority: non_authoritative
goal: "Preserve Kubernetes kind/name symbol metadata across every sub-chunk of an oversized manifest document."
risk: low
risk_note: "The change is limited to Kubernetes chunk metadata propagation and one focused miner test."
files:
  - path: mempalace/miner.py
    change: "Update _chunk_k8s_manifest so oversized sub-chunks from one Kubernetes document carry the document-level kind/name metadata even when later chunk content lacks those fields."
  - path: tests/test_miner.py
    change: "Add a large Kubernetes manifest fixture/test proving all sub-chunks expose the same symbol_type and symbol_name."
acceptance:
  - id: AC-1
    when: "_chunk_k8s_manifest processes a single Kubernetes document larger than HARD_MAX that splits into multiple chunks"
    then: "every returned chunk can be symbol-extracted as symbol_type='deployment' and symbol_name='Deployment/<name>'"
  - id: AC-2
    when: "_chunk_k8s_manifest processes a Kubernetes-like YAML document without a kind field"
    then: "all returned chunks continue to extract empty symbol_type and symbol_name"
  - id: AC-3
    when: "_chunk_k8s_manifest processes a multi-document YAML file containing an oversized document and a normal-sized document"
    then: "chunk_index values remain sequential across all returned chunks and each document's chunks retain only that document's own symbol metadata"
out_of_scope:
  - "Changing generic adaptive_merge_split behavior for non-Kubernetes languages."
  - "Fixing YAML document separator parsing inside block scalar values."
  - "Changing storage schema or public search APIs."
---

## Design Notes

- Keep the behavior local to `_chunk_k8s_manifest`; other chunkers should keep receiving plain `adaptive_merge_split` output.
- Extract the document-level Kubernetes symbol once from each stripped YAML document before calling `adaptive_merge_split`.
- Attach or preserve enough metadata on each returned Kubernetes chunk for downstream mining to emit the same `symbol_name` and `symbol_type` for every sub-chunk from that document.
- Do not infer symbols for documents where `_extract_k8s_symbol` currently returns empty values; those documents should remain empty-symbol chunks.
- The test should build a manifest with `kind:` and `metadata.name:` near the top plus enough body data and split boundaries after the header to force multiple chunks beyond `HARD_MAX`.
- Include a multi-document edge check so propagation cannot leak symbol metadata from an oversized document into a following resource.
