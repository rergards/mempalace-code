---
slug: MINE-K8S
status: completed
authority: non_authoritative
goal: "Add Kubernetes manifest smart parsing — detect K8s YAML, split multi-doc manifests, and surface kind/name as symbol metadata"
risk: low
risk_note: "Additive only. No existing code paths change; K8s detection is a new branch in detect_language() and chunk_file(). YAML files without apiVersion+kind fall back to chunk_adaptive_lines as before."
files:
  - path: mempalace/miner.py
    change: "Add _is_k8s_manifest(content) helper; add content-based override in detect_language() (after shebang step) to return 'kubernetes' when language=='yaml' and content is a K8s manifest; add 'kubernetes' branch in chunk_file() dispatcher; add _chunk_k8s_manifest(content, source_file) that splits on '---' document separators and applies adaptive_merge_split; add _extract_k8s_symbol(content) that extracts kind and metadata.name; add early-return in extract_symbol() for language=='kubernetes'"
  - path: mempalace/searcher.py
    change: "Add 'kubernetes' to SUPPORTED_LANGUAGES; add K8s resource kinds (deployment, service, configmap, secret, ingress, customresourcedefinition) to VALID_SYMBOL_TYPES"
  - path: mempalace/mcp_server.py
    change: "Add 'kubernetes' to mempalace_code_search language description; add K8s resource kinds to symbol_type description"
  - path: tests/test_miner.py
    change: "Add tests for _chunk_k8s_manifest: single-doc, multi-doc (3 resources), empty-separator skipping, oversized-doc splitting; add test_mine_k8s_roundtrip — full mine() on a temp dir with a Deployment YAML verifying language='kubernetes', symbol_type='deployment', symbol_name='Deployment/my-app'"
  - path: tests/test_symbol_extract.py
    change: "Add K8s extract_symbol tests: Deployment with name, Service with name, resource missing name, CRD kind, no-match for non-k8s YAML chunk"
  - path: tests/test_lang_detect.py
    change: "Add content-based K8s detection tests: K8s YAML content returns 'kubernetes', plain YAML without apiVersion+kind stays 'yaml'; both .yaml and .yml extensions"
  - path: tests/test_searcher.py
    change: "Add test_code_search_kubernetes_language — code_search(language='kubernetes') does not return validation error; add test_code_search_k8s_symbol_types — 'deployment', 'service', 'configmap' are accepted as symbol_type filters"
acceptance:
  - id: AC-1
    when: "A .yaml file containing `apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: nginx\n` is mined"
    then: "At least one drawer has language='kubernetes', symbol_type='deployment', symbol_name='Deployment/nginx'"
  - id: AC-2
    when: "A multi-document YAML file with three `---`-separated resources (Deployment, Service, ConfigMap) is passed to _chunk_k8s_manifest()"
    then: "Exactly 3 non-empty chunks are returned"
  - id: AC-3
    when: "A multi-document YAML with an empty `---\n---` separator is passed to _chunk_k8s_manifest()"
    then: "The empty document produces no chunk (len(chunks) equals the number of non-empty documents)"
  - id: AC-4
    when: "detect_language(Path('deploy.yaml'), k8s_content) is called where k8s_content contains apiVersion and kind fields"
    then: "Returns 'kubernetes'"
  - id: AC-5
    when: "detect_language(Path('pyproject.yaml'), plain_yaml_content) is called where content has no apiVersion/kind fields"
    then: "Returns 'yaml' (falls through to existing adaptive chunking)"
  - id: AC-6
    when: "extract_symbol is called with a chunk containing `kind: ConfigMap` and `metadata:\n  name: app-config` with language='kubernetes'"
    then: "Returns ('ConfigMap/app-config', 'configmap')"
  - id: AC-7
    when: "extract_symbol is called with a chunk containing only `apiVersion: apps/v1` and `kind: Deployment` but no metadata.name"
    then: "Returns ('Deployment', 'deployment') — kind only, no slash-name"
  - id: AC-8
    when: "code_search(query='nginx', language='kubernetes') is called via MCP"
    then: "Returns results dict (no 'error' key with unsupported-language message)"
  - id: AC-9
    when: "code_search(query='redis', symbol_type='deployment') is called"
    then: "Returns results dict without validation error"
out_of_scope:
  - "Full YAML parsing via PyYAML for metadata extraction — regex-based extraction is sufficient and avoids adding a parse-time dep on YAML correctness"
  - "KG entity extraction for K8s resources — no entity relationships added for Deployments, Services, etc."
  - "Helm templates (.tpl) — already handled as generic YAML (added by MINE-DEVOPS-INFRA)"
  - "CRD schema validation or spec-field indexing — only kind/name are extracted as symbols; full spec is in chunk content"
  - "Non-standard YAML indentation (e.g., 4-space metadata.name) — patterns target 2-space standard K8s indentation"
  - "Adding all possible K8s built-in kinds to VALID_SYMBOL_TYPES — only the 6 kinds named in the task description are added; CRD custom kinds are stored but not filterable via symbol_type"
---

## Design Notes

- **Detection heuristic for `_is_k8s_manifest`:** Check for both `^apiVersion:\s` and `^kind:\s` present anywhere in the content (using `re.search` with `re.MULTILINE`). This avoids false positives on Helm values files (which are plain YAML with no `kind:`) and Ansible playbooks (which use `hosts:` not `kind:`).

- **`detect_language` as the integration point:** Content-based K8s detection is added as step 5 in `detect_language()`, after shebang detection, when the resolved language is `"yaml"`. This keeps language resolution centralized and propagates `"kubernetes"` to both `chunk_file()` and `extract_symbol()` without modifying `mine_file()`.

- **`_chunk_k8s_manifest` strategy:**
  1. Split on `re.split(r"(?:^|\n)---\s*(?:\n|$)", content)` to handle both leading and inline separators.
  2. Strip each fragment; skip if less than `MIN_CHUNK` chars.
  3. Apply `adaptive_merge_split` on each surviving fragment (handles oversized ConfigMaps with large data sections).
  4. Re-index `chunk_index` across all resulting chunks.

- **Symbol name format:** `Kind/name` (e.g., `Deployment/my-app`, `Service/redis-svc`). The `symbol_name` holds the combined string; `symbol_type` holds the lowercase kind. This matches the task's "symbol_name (kind/name)" requirement and follows the `Kind/name` convention familiar to `kubectl get`.

- **`_extract_k8s_symbol` regex approach:**
  - Extract `kind` with `re.search(r"^kind:\s*(\w+)", content, re.MULTILINE)`.
  - Extract `name` with `re.search(r"^\s{2}name:\s*(\S+)", content, re.MULTILINE)` — matches the standard 2-space indent under `metadata:`. This avoids false matches on `spec.template.metadata.name` which is indented more deeply.
  - Return `(f"{kind}/{name}", kind.lower())` when both present; `(kind, kind.lower())` when only kind; `("", "")` for neither.

- **`symbol_type` is lowercase:** All existing types in `VALID_SYMBOL_TYPES` are lowercase. K8s kinds are lowercased on extraction (`kind.lower()`) so `code_search(symbol_type="deployment")` works. The original PascalCase `kind` is preserved in `symbol_name` (e.g., `Deployment/my-app`).

- **VALID_SYMBOL_TYPES additions:** `deployment`, `service`, `configmap`, `secret`, `ingress`, `customresourcedefinition`. Custom CRD kinds (e.g., `HelmRelease`, `Certificate`) are stored with `symbol_type=` their lowercase kind but cannot be filtered via `symbol_type=` in `code_search` until added. Users can still search by content.

- **No changes to `_KG_EXTRACT_EXTENSIONS`:** K8s manifests don't contribute entity relationships to the KG. Adding Deployments/Services as KG entities is deferred (potential future MINE-K8S-KG task).
