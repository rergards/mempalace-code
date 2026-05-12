---
slug: MINE-HELM
goal: "Add first-pass Helm chart indexing to the code miner without rendering templates"
risk: medium
risk_note: "Touches language detection, chunk routing, symbol metadata, and search filter validation; scope is additive but YAML/Kubernetes precedence must stay intact."
files:
  - path: mempalace_code/language_catalog.py
    change: "Add helm as a synthetic detected/searchable language without changing .yaml, .yml, or .tpl extension mappings."
  - path: mempalace_code/mining/languages.py
    change: "Detect Helm chart files by path context: Chart.yaml, chart-root values*.yaml, and files under templates/ when an ancestor Chart.yaml exists; keep non-chart YAML and Kubernetes detection unchanged."
  - path: mempalace_code/mining/chunkers.py
    change: "Add a Helm chunking branch that indexes Chart.yaml as one chart chunk, values YAML by top-level value paths, and templates by raw YAML document/resource chunks while tolerating Go template delimiter lines."
  - path: mempalace_code/mining/symbols.py
    change: "Add Helm symbol extraction helpers for chart metadata, values top-level paths, and visible template kind/name metadata."
  - path: mempalace_code/miner.py
    change: "Re-export new Helm mining helpers needed by focused tests and legacy direct imports."
  - path: mempalace_code/searcher.py
    change: "Allow helm language searches and helm_chart/helm_values symbol_type filters through code_search validation."
  - path: mempalace_code/mcp/tools/search.py
    change: "Update the code_search symbol_type description so MCP clients can discover Helm-specific symbol filters."
  - path: tests/test_lang_detect.py
    change: "Add Helm path-context detection tests and guard tests showing non-chart values.yaml remains yaml and ordinary Kubernetes YAML remains kubernetes."
  - path: tests/test_miner.py
    change: "Add Helm chunking and mine() roundtrip coverage for Chart.yaml metadata, values top-level paths, and templated Deployment manifests."
  - path: tests/test_symbol_extract.py
    change: "Add focused extract_symbol coverage for Helm chart chunks, values chunks, template resources, and templated-name fallback."
  - path: tests/test_language_catalog.py
    change: "Assert helm is a detected/searchable synthetic language while extension maps stay unchanged."
  - path: tests/test_searcher.py
    change: "Add code_search validation coverage for language='helm' and Helm-specific symbol_type filters."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_miner.py::test_mine_helm_chart_roundtrip -q` is run against a temp chart containing Chart.yaml, values.yaml, and templates/deployment.yaml"
    then: "stored drawers include language='helm' entries for HelmChart/<chart name>, values.<top-level key>, and Deployment/<visible metadata.name>, with Chart.yaml content retaining version and dependencies."
  - id: AC-2
    when: "`python -m pytest tests/test_miner.py::test_chunk_helm_values_top_level_paths -q` is run against a padded values.yaml fixture"
    then: "the Helm chunker returns chunks tagged with symbol_type='helm_values' and symbol_name values such as values.image and values.service."
  - id: AC-3
    when: "`python -m pytest tests/test_miner.py::test_chunk_helm_template_tolerates_go_template_delimiters -q` is run against a Deployment template with {{ }} control blocks and a templated metadata.name"
    then: "the template produces a helm chunk with symbol_type='deployment' and symbol_name='Deployment' instead of falling back to anonymous generic YAML chunks."
  - id: AC-4
    when: "`python -m pytest tests/test_lang_detect.py::test_non_chart_values_yaml_remains_yaml tests/test_lang_detect.py::test_non_chart_kubernetes_yaml_still_detects_kubernetes -q` is run"
    then: "a values.yaml without chart context remains language='yaml', and a normal non-Helm Kubernetes manifest remains language='kubernetes'."
  - id: AC-5
    when: "`python -m pytest tests/test_searcher.py::TestHelmLanguageSupport -q` is run"
    then: "code_search accepts language='helm', symbol_type='helm_chart', and symbol_type='helm_values' without validation errors and returns seeded Helm hits."
out_of_scope:
  - "Running `helm template`, rendering templates, substituting values, or evaluating Go template expressions."
  - "Helm schema validation, chart dependency resolution, repository lookups, or lockfile semantics."
  - "Inferring resource names hidden behind template expressions beyond kind-only fallback."
  - "Changing generic YAML chunking, ordinary Kubernetes manifest parsing, or gotemplate handling outside detected Helm chart paths."
  - "Knowledge graph extraction for chart dependencies or Kubernetes resource relationships."
contract_policy:
  flow: full_spdd
  reason: "Standard feature touching the code mining pipeline, stored metadata, and MCP/search filter contracts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Helm chart files must be detected from chart path context and stored as language='helm'."
      source: "backlog scope and AC-1"
      acceptance_ids: [AC-1, AC-4]
    - id: REQ-2
      statement: "Chart.yaml drawers must expose the chart name as symbol metadata while preserving version and dependency YAML in verbatim content."
      source: "backlog chart metadata acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-3
      statement: "values.yaml must expose top-level value paths as searchable Helm value symbols."
      source: "backlog values paths scope"
      acceptance_ids: [AC-2]
    - id: REQ-4
      statement: "Helm template manifests must be chunked by raw resource documents and extract visible kind/name without rendering templates."
      source: "backlog template resource scope"
      acceptance_ids: [AC-1, AC-3]
    - id: REQ-5
      statement: "code_search and MCP metadata must accept Helm language and Helm-specific symbol filters."
      source: "search usability for extracted metadata"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Language catalog"
      kind: "internal"
      paths: ["mempalace_code/language_catalog.py"]
      expected_behavior: "helm is listed as a synthetic detected/searchable language while extension mappings remain canonical for generic YAML and gotemplate files."
    - name: "Language detection"
      kind: "internal"
      paths: ["mempalace_code/mining/languages.py"]
      expected_behavior: "detect_language returns helm only for chart-context files and leaves plain YAML and non-chart Kubernetes precedence intact."
    - name: "Chunking and symbols"
      kind: "internal"
      paths: ["mempalace_code/mining/chunkers.py", "mempalace_code/mining/symbols.py", "mempalace_code/miner.py"]
      expected_behavior: "Helm chart, values, and template chunks carry useful symbol_name/symbol_type metadata without changing drawer schema."
    - name: "Search and MCP filters"
      kind: "api"
      paths: ["mempalace_code/searcher.py", "mempalace_code/mcp/tools/search.py"]
      expected_behavior: "code_search and MCP schema text accept and advertise Helm-specific language and symbol filters."
    - name: "Regression coverage"
      kind: "internal"
      paths: ["tests/test_lang_detect.py", "tests/test_miner.py", "tests/test_symbol_extract.py", "tests/test_language_catalog.py", "tests/test_searcher.py"]
      expected_behavior: "Focused tests cover Helm happy paths, non-chart guards, templated delimiters, catalog/search exposure, and symbol extraction."
  invariants:
    - id: INV-1
      statement: ".yaml and .yml extension mappings remain yaml; .tpl remains gotemplate outside detected Helm chart paths."
      applies_to: ["mempalace_code/language_catalog.py", "mempalace_code/mining/languages.py"]
    - id: INV-2
      statement: "Non-chart Kubernetes manifests with apiVersion and kind continue to detect as kubernetes and use existing K8s chunking."
      applies_to: ["mempalace_code/mining/languages.py", "mempalace_code/mining/chunkers.py"]
    - id: INV-3
      statement: "Drawer metadata field names, source_file values, source_hash behavior, and chunk_index sequencing remain unchanged."
      applies_to: ["mempalace_code/mining/orchestrator.py", "mempalace_code/mining/chunkers.py"]
    - id: INV-4
      statement: "Helm support must not execute files, call external Helm binaries, fetch dependencies, or evaluate template expressions."
      applies_to: ["mempalace_code/mining/languages.py", "mempalace_code/mining/chunkers.py", "mempalace_code/mining/symbols.py"]
  risks:
    - id: RISK-1
      risk: "Path-context detection could classify unrelated values.yaml files as Helm."
      mitigation: "Require Chart.yaml context for values/template files and add non-chart guard tests."
    - id: RISK-2
      risk: "Helm templates containing Go delimiters could break YAML splitting or symbol extraction."
      mitigation: "Keep parsing regex/raw-text based, ignore template-only lines, and test {{ }} control-block templates."
    - id: RISK-3
      risk: "Adding helm as searchable language without symbol filter updates could make extracted metadata hard to query."
      mitigation: "Add helm to the catalog and add helm_chart/helm_values to code_search validation plus MCP schema text."
    - id: RISK-4
      risk: "Helm detection could preempt existing Kubernetes behavior for ordinary manifests."
      mitigation: "Only return helm inside chart context and keep a focused Kubernetes non-chart regression test."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_miner.py::test_mine_helm_chart_roundtrip -q"
      proves: "mine() stores Helm chart metadata, values paths, and visible template resource metadata as language='helm'"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_miner.py::test_chunk_helm_values_top_level_paths -q"
      proves: "values.yaml top-level paths become helm_values symbols"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_miner.py::test_chunk_helm_template_tolerates_go_template_delimiters -q"
      proves: "Go template delimiters do not force Helm templates into anonymous generic chunks"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_lang_detect.py::test_non_chart_values_yaml_remains_yaml tests/test_lang_detect.py::test_non_chart_kubernetes_yaml_still_detects_kubernetes -q"
      proves: "Helm path-context detection preserves plain YAML and ordinary Kubernetes behavior"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_searcher.py::TestHelmLanguageSupport -q"
      proves: "code_search accepts Helm language and Helm-specific symbol_type filters"
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_symbol_extract.py::test_extract_helm_chart_symbol tests/test_symbol_extract.py::test_extract_helm_template_visible_name tests/test_symbol_extract.py::test_extract_helm_template_templated_name_falls_back_to_kind -q"
      proves: "Helm symbol extraction handles chart metadata, visible template names, and templated-name fallback"
      acceptance_ids: [AC-1, AC-3]
    - id: VER-7
      command: "python -m pytest tests/test_language_catalog.py::test_catalog_preserves_current_detection_labels tests/test_language_catalog.py::test_catalog_keeps_non_extension_boundaries_explicit -q"
      proves: "helm catalog exposure does not mutate extension or filename boundaries"
      acceptance_ids: [AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_lang_detect.py tests/test_miner.py::test_mine_k8s_roundtrip tests/test_miner.py::test_chunk_k8s_three_docs_produces_three_chunks tests/test_language_catalog.py tests/test_searcher.py::TestKubernetesLanguageSupport -q"
        proves: "existing YAML, Kubernetes, language catalog, and search validation behavior still works around the new Helm branch"
        acceptance_ids: [AC-1, AC-4, AC-5]
      - id: REG-2
        command: "ruff check mempalace_code/language_catalog.py mempalace_code/mining/languages.py mempalace_code/mining/chunkers.py mempalace_code/mining/symbols.py mempalace_code/miner.py mempalace_code/searcher.py mempalace_code/mcp/tools/search.py tests/test_lang_detect.py tests/test_miner.py tests/test_symbol_extract.py tests/test_language_catalog.py tests/test_searcher.py"
        proves: "the Helm mining patch remains lint-clean across touched code and tests"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Keep Helm separate from Kubernetes: chart-context files return `helm`; ordinary manifests continue to return `kubernetes`.
- Detect chart context by walking ancestors for `Chart.yaml`; `Chart.yaml` itself is always Helm, while `values*.yaml` and `templates/*.{yaml,yml,tpl}` require a chart root.
- Do not parse or render Go templates. Treat `{{ ... }}` as raw text, skip template-only control lines for resource symbol extraction, and fall back to kind-only symbols when `metadata.name` is templated.
- Use existing drawer metadata fields only: `language="helm"`, `symbol_type="helm_chart"` for Chart.yaml, `symbol_type="helm_values"` for values paths, and lowercase resource kind for templates.
- Keep Chart.yaml content verbatim so version and dependencies remain indexed without adding schema fields.
- Chunk values YAML by top-level keys, using `values.<key>` as `symbol_name`; if parsing fails, fall back to adaptive line chunks tagged as Helm.
- Reuse the existing YAML document splitter behavior for templates where possible so block scalars and `---` separators keep K8s-compatible semantics.
- Preserve the miner shim as the test-facing compatibility surface for new Helm helpers, matching the current Kubernetes helper pattern.
