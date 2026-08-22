---
slug: MINE-ANSIBLE
status: completed
authority: non_authoritative
goal: "Add first-pass static Ansible playbook, role, and inventory indexing to the code miner"
risk: medium
risk_note: "Touches YAML-family language detection, chunk routing, symbol metadata, and code_search/MCP filter contracts; precedence with Helm and Kubernetes must stay stable."
contract_policy:
  flow: full_spdd
  reason: "Standard feature touching the code mining pipeline, stored metadata, and MCP/search filter contracts."
  sync_gate: required
  verification_path: automated
files:
  - path: mempalace_code/language_catalog.py
    change: "Add ansible as a synthetic detected/searchable language and, if needed, add only conservative inventory filename coverage without changing .yaml/.yml/.ini mappings."
  - path: mempalace_code/mining/languages.py
    change: "Detect Ansible playbooks, role files, and inventory files by YAML/INI path and static content context after Helm detection and before broad Kubernetes fallback."
  - path: mempalace_code/mining/chunkers.py
    change: "Add an Ansible chunking branch for playbook plays, tasks, handlers, role references, vars_files, role task/handler files, role vars/defaults files, and file-only inventory chunks while preserving original text."
  - path: mempalace_code/mining/symbols.py
    change: "Add Ansible symbol extraction helpers for play, task, handler, role, vars file, and inventory chunks using existing symbol_name/symbol_type fields."
  - path: mempalace_code/miner.py
    change: "Re-export new Ansible mining helpers needed by focused tests and legacy direct imports."
  - path: mempalace_code/searcher.py
    change: "Allow ansible language searches and Ansible-specific symbol_type filters through code_search validation."
  - path: mempalace_code/mcp/tools/search.py
    change: "Update the code_search symbol_type description so MCP clients can discover Ansible-specific symbol filters."
  - path: tests/test_lang_detect.py
    change: "Add Ansible detection and precedence tests for playbooks, role files, inventory files, plain YAML guards, Kubernetes guards, and Helm precedence."
  - path: tests/test_miner.py
    change: "Add Ansible mine() roundtrip and chunking tests for playbooks, roles, inventory files, vars file paths, modules, and Jinja-delimited raw text."
  - path: tests/test_symbol_extract.py
    change: "Add focused Ansible symbol extraction coverage for play, task, handler, role, vars, and inventory chunks."
  - path: tests/test_language_catalog.py
    change: "Assert ansible is a detected/searchable synthetic language while extension maps stay unchanged."
  - path: tests/test_searcher.py
    change: "Add code_search validation coverage for language='ansible' and Ansible-specific symbol_type filters."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_miner.py::test_mine_ansible_playbook_roundtrip -q` is run against a temp playbook with named plays, hosts, tasks, roles, and vars_files"
    then: "stored drawers include language='ansible' entries whose symbol metadata exposes the play name/hosts, task names/modules, role names, and vars file paths."
  - id: AC-2
    when: "`python -m pytest tests/test_miner.py::test_mine_ansible_role_roundtrip -q` is run against roles/web/tasks/main.yml, roles/web/handlers/main.yml, and roles/web/vars/main.yml"
    then: "stored drawers include language='ansible' entries tied to role web with task, handler, and vars/defaults symbol types."
  - id: AC-3
    when: "`python -m pytest tests/test_miner.py::test_chunk_ansible_tolerates_jinja_delimiters -q` is run against tasks containing {{ }} and {% %} delimiters"
    then: "the file remains indexable as ansible, task module metadata is still extracted, and the stored content keeps the original Jinja delimiters verbatim."
  - id: AC-4
    when: "`python -m pytest tests/test_lang_detect.py::test_plain_yaml_without_ansible_stays_yaml tests/test_lang_detect.py::test_non_ansible_kubernetes_yaml_still_detects_kubernetes tests/test_lang_detect.py::test_helm_chart_detection_still_precedes_ansible -q` is run"
    then: "ordinary YAML remains yaml, ordinary Kubernetes manifests remain kubernetes, and Helm chart-context files remain helm."
  - id: AC-5
    when: "`python -m pytest tests/test_miner.py::test_mine_ansible_inventory_detects_file_only -q` is run against inventory.ini and inventory.yml fixtures"
    then: "inventory files are detected and indexed as language='ansible' with symbol_type='ansible_inventory' without emitting host/group symbols."
  - id: AC-6
    when: "`python -m pytest tests/test_searcher.py::TestAnsibleLanguageSupport -q` is run"
    then: "code_search accepts language='ansible' and Ansible-specific symbol_type filters without validation errors and returns seeded Ansible hits."
out_of_scope:
  - "Executing ansible, ansible-playbook, ansible-inventory, or collection/plugin code."
  - "Resolving variables, facts, defaults precedence, include/import semantics, roles_path, or dynamic role names."
  - "Rendering or evaluating Jinja expressions; delimiters are stored as raw text only."
  - "Parsing inventory host/group semantics beyond detecting and indexing inventory files."
  - "Changing generic YAML chunking, ordinary Kubernetes manifest parsing, or Helm chart/template handling."
  - "Knowledge graph extraction for Ansible dependencies, hosts, variables, or role relationships."
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Ansible playbooks must be detected from static YAML structure and stored as language='ansible'."
      source: "backlog scope and AC-1"
      acceptance_ids: [AC-1, AC-4]
    - id: REQ-2
      statement: "Playbook chunks must expose play name/hosts, task name/module, role references, and vars_files paths through existing symbol metadata."
      source: "backlog extraction scope and AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-3
      statement: "Role directory files must be detected from roles/<role>/tasks, handlers, vars, and defaults path context."
      source: "backlog role directory scope and AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-4
      statement: "Jinja delimiters inside Ansible YAML must be treated as raw text and must not prevent indexing."
      source: "backlog Jinja tolerance scope and AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-5
      statement: "Inventory files must be detected and indexed at file level without parsing host/group semantics."
      source: "backlog inventory test requirement and AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "code_search and MCP metadata must accept Ansible language and Ansible-specific symbol filters."
      source: "search usability for extracted metadata and AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Language catalog"
      kind: "internal"
      paths: ["mempalace_code/language_catalog.py"]
      expected_behavior: "ansible is listed as a synthetic detected/searchable language while YAML, INI, and Helm/Kubernetes labels remain canonical."
    - name: "Language detection"
      kind: "internal"
      paths: ["mempalace_code/mining/languages.py"]
      expected_behavior: "detect_language returns ansible for static playbooks, role files, and inventory files, after Helm path-context detection and before broad K8s content fallback."
    - name: "Chunking and symbols"
      kind: "internal"
      paths: ["mempalace_code/mining/chunkers.py", "mempalace_code/mining/symbols.py", "mempalace_code/miner.py"]
      expected_behavior: "Ansible chunks carry useful symbol_name/symbol_type metadata using existing drawer fields and preserve original YAML/Jinja text."
    - name: "Search and MCP filters"
      kind: "api"
      paths: ["mempalace_code/searcher.py", "mempalace_code/mcp/tools/search.py"]
      expected_behavior: "code_search and MCP schema text accept and advertise Ansible-specific language and symbol filters."
    - name: "Regression coverage"
      kind: "internal"
      paths: ["tests/test_lang_detect.py", "tests/test_miner.py", "tests/test_symbol_extract.py", "tests/test_language_catalog.py", "tests/test_searcher.py"]
      expected_behavior: "Focused tests cover Ansible happy paths, plain YAML/K8s/Helm guards, inventory detection-only behavior, Jinja tolerance, catalog/search exposure, and symbol extraction."
  invariants:
    - id: INV-1
      statement: ".yaml and .yml extension mappings remain yaml, .ini remains ini, and .tpl remains gotemplate outside detected Helm chart paths."
      applies_to: ["mempalace_code/language_catalog.py", "mempalace_code/mining/languages.py"]
    - id: INV-2
      statement: "Helm chart-context files continue to detect as helm and ordinary non-Ansible Kubernetes manifests continue to detect as kubernetes."
      applies_to: ["mempalace_code/mining/languages.py", "mempalace_code/mining/chunkers.py"]
    - id: INV-3
      statement: "Drawer metadata field names, source_file values, source_hash behavior, and chunk_index sequencing remain unchanged."
      applies_to: ["mempalace_code/mining/orchestrator.py", "mempalace_code/mining/chunkers.py"]
    - id: INV-4
      statement: "Ansible support must not execute files, import plugins, resolve variables, query inventories, or evaluate Jinja expressions."
      applies_to: ["mempalace_code/mining/languages.py", "mempalace_code/mining/chunkers.py", "mempalace_code/mining/symbols.py"]
    - id: INV-5
      statement: "Inventory support is detection-only and must not emit host or group symbols."
      applies_to: ["mempalace_code/mining/languages.py", "mempalace_code/mining/chunkers.py", "mempalace_code/mining/symbols.py"]
  risks:
    - id: RISK-1
      risk: "Content heuristics could misclassify generic YAML as Ansible."
      mitigation: "Require recognizable playbook keys, role path context, or conservative inventory filenames/content and add plain YAML guard tests."
    - id: RISK-2
      risk: "Ansible detection could steal Helm templates or Kubernetes manifests from existing specialized chunkers."
      mitigation: "Keep Helm path-context detection first, then Ansible, then Kubernetes fallback, with focused precedence tests."
    - id: RISK-3
      risk: "Unquoted Jinja expressions could make PyYAML parsing fail and drop useful files."
      mitigation: "Use tolerant raw-text scanning and/or sanitized parse helpers only for structure discovery while storing original text verbatim."
    - id: RISK-4
      risk: "Dynamic include/import/role semantics could create misleading symbols."
      mitigation: "Extract only statically visible names/modules/paths and document dynamic semantics as out of scope."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_miner.py::test_mine_ansible_playbook_roundtrip -q"
      proves: "mine() stores Ansible playbook play, task, role, module, and vars_files metadata"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_miner.py::test_mine_ansible_role_roundtrip -q"
      proves: "role directory files are detected and indexed with role task, handler, and vars/defaults symbols"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_miner.py::test_chunk_ansible_tolerates_jinja_delimiters -q"
      proves: "Jinja delimiters do not prevent Ansible chunking and original text remains verbatim"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_lang_detect.py::test_plain_yaml_without_ansible_stays_yaml tests/test_lang_detect.py::test_non_ansible_kubernetes_yaml_still_detects_kubernetes tests/test_lang_detect.py::test_helm_chart_detection_still_precedes_ansible -q"
      proves: "Ansible detection preserves generic YAML, Kubernetes, and Helm precedence"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_miner.py::test_mine_ansible_inventory_detects_file_only -q"
      proves: "inventory files are detected and indexed only as file-level Ansible inventory chunks"
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_searcher.py::TestAnsibleLanguageSupport -q"
      proves: "code_search accepts Ansible language and Ansible-specific symbol_type filters"
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_symbol_extract.py::test_extract_ansible_play_symbol tests/test_symbol_extract.py::test_extract_ansible_task_symbol tests/test_symbol_extract.py::test_extract_ansible_inventory_symbol -q"
      proves: "Ansible symbol extraction handles play, task/module, and inventory-only chunks"
      acceptance_ids: [AC-1, AC-5]
    - id: VER-8
      command: "python -m pytest tests/test_language_catalog.py::test_ansible_in_catalog -q"
      proves: "ansible catalog exposure does not mutate extension or filename boundaries except any explicitly planned conservative inventory filename"
      acceptance_ids: [AC-4, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_lang_detect.py tests/test_miner.py::test_mine_k8s_roundtrip tests/test_miner.py::test_mine_helm_chart_roundtrip tests/test_language_catalog.py tests/test_searcher.py::TestKubernetesLanguageSupport tests/test_searcher.py::TestHelmLanguageSupport -q"
        proves: "existing YAML, Kubernetes, Helm, language catalog, and search validation behavior still works around the new Ansible branch"
        acceptance_ids: [AC-1, AC-4, AC-6]
      - id: REG-2
        command: "ruff check mempalace_code/language_catalog.py mempalace_code/mining/languages.py mempalace_code/mining/chunkers.py mempalace_code/mining/symbols.py mempalace_code/miner.py mempalace_code/searcher.py mempalace_code/mcp/tools/search.py tests/test_lang_detect.py tests/test_miner.py tests/test_symbol_extract.py tests/test_language_catalog.py tests/test_searcher.py"
        proves: "the Ansible mining patch remains lint-clean across touched code and tests"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Keep Ansible separate from generic YAML: playbook/role/inventory context returns `ansible`; unrelated YAML remains `yaml`.
- Detection precedence should be: extension/filename lookup, Helm chart-context override, Ansible static context override, then Kubernetes content override.
- Treat playbooks as top-level YAML lists containing play mappings with keys such as `hosts`, `tasks`, `handlers`, `roles`, or `vars_files`.
- Detect role files from path context under `roles/<role>/{tasks,handlers,vars,defaults}/...`; do not infer role names from dynamic include paths.
- Inventory detection is intentionally shallow: support obvious `inventory.*` fixtures and YAML inventory shapes, but emit only `ansible_inventory` file chunks.
- Do not globally add an extensionless `hosts` filename unless the implementation can prove Ansible context; this avoids indexing unrelated hosts files as source.
- Use existing drawer metadata fields only: `language="ansible"` and symbol types such as `ansible_play`, `ansible_task`, `ansible_handler`, `ansible_role`, `ansible_vars`, and `ansible_inventory`.
- Encode statically visible task module names in `symbol_name` or the chunk text; avoid adding new schema columns for module metadata.
- Prefer PyYAML for parseable files, but keep a raw line-oriented fallback for unquoted Jinja and other tolerated Ansible YAML so files are not dropped.
- Any sanitization used for structure discovery must never replace stored drawer content; drawers must retain the original YAML/Jinja text verbatim.
