---
slug: STORE-HF-CACHED-SEARCH-SUBPROCESS-GUARD
goal: "Add a non-network subprocess regression guard for cached HuggingFace model fetch and search paths"
risk: low
risk_note: "Test-only guard around existing local-first model loading; main risk is fragile subprocess fixture isolation."
files:
  - path: tests/test_offline.py
    change: "Add subprocess tests that exercise cached fetch-model and search with fake sentence-transformers/HuggingFace modules, blocked sockets, call logging, and stdout/stderr warning assertions."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_offline.py::test_cached_fetch_model_subprocess_guard -q` is run"
    then: "the fetch-model subprocess exits 0 against a prepared HF_HOME cache, records only a local_files_only=True SentenceTransformer load, records no socket or HuggingFace metadata events, and captured stdout/stderr contain no HuggingFace token-warning text"
  - id: AC-2
    when: "`python -m pytest tests/test_offline.py::test_cached_search_subprocess_guard -q` is run"
    then: "the search subprocess exits 0 against a seeded Lance palace, records only local_files_only=True model initialization for the query embedder, records no socket or HuggingFace metadata events, and captured stdout/stderr contain no HuggingFace token-warning text"
  - id: AC-3
    when: "`python -m pytest tests/test_offline.py::test_offline_search_subprocess_no_online_retry_on_local_cache_error -q` is run"
    then: "the search subprocess fails with the fake local-cache error while HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1, and the event log shows no online-capable SentenceTransformer load, socket connection, or HuggingFace metadata attempt"
  - id: AC-4
    when: "`python -m pytest tests/test_offline.py::test_force_fetch_model_subprocess_setup_boundary_allows_online_load -q` is run"
    then: "the --force setup subprocess records exactly one online-capable model load for the intentional refresh path while still suppressing HuggingFace token-warning text from captured stdout/stderr"
out_of_scope:
  - "Changing the default embedding model, vector dimensions, benchmark gates, or model-upgrade policy"
  - "Downloading real HuggingFace models or adding a needs_network dependency to the guard"
  - "Changing LanceDB schema, search ranking, mining, MCP, backup, or ChromaDB behavior"
  - "Changing backlog metadata or archiving this task"
contract_policy:
  flow: full_spdd
  reason: "Standard task guarding offline/model-loading side effects on public CLI search and fetch-model paths"
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Cached fetch-model must verify the already prepared model in a subprocess without online-capable model resolution, HuggingFace metadata calls, socket use, or token-warning output."
      source: "backlog description and AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Cached semantic search must initialize its query embedder in a subprocess through the local cache only, without metadata calls, socket use, or token-warning output."
      source: "backlog description and AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "When explicit offline flags are set and the cached model cannot be loaded, search must surface the local-load failure instead of retrying an online-capable metadata path."
      source: "failure-path guard"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The guard must preserve the intentional setup boundary where fetch-model --force can perform an online-capable refresh while still keeping third-party token-warning text quiet."
      source: "boundary guard"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Offline subprocess guard"
      kind: "internal"
      paths: ["tests/test_offline.py"]
      expected_behavior: "non-network pytest cases spawn public CLI subprocesses, prepend fake model/HF modules plus socket blocking via PYTHONPATH, and fail on online metadata events or HuggingFace token-warning output."
  invariants:
    - id: INV-1
      statement: "mempalace-code fetch-model without --force continues to prefer cached local model loading before any download path."
      applies_to: ["mempalace_code/cli_commands/model.py", "tests/test_offline.py"]
    - id: INV-2
      statement: "LanceStore search continues to embed query text through _SentenceTransformerEmbedder and must keep its local_files_only-first resolution contract."
      applies_to: ["mempalace_code/storage.py", "tests/test_offline.py"]
    - id: INV-3
      statement: "Existing needs_network offline integration tests remain optional; the new guard must run under the default not-needs_network pytest selection."
      applies_to: ["tests/test_offline.py", "pyproject.toml"]
    - id: INV-4
      statement: "The intentional setup paths for cache miss or --force remain allowed to perform an online-capable load."
      applies_to: ["mempalace_code/cli_commands/model.py", "tests/test_offline.py"]
  risks:
    - id: RISK-1
      risk: "A fake in-process monkeypatch could miss stdout/stderr leakage or import-time network behavior from a real CLI run."
      mitigation: "Run python -m mempalace_code.cli in subprocesses with capture_output=True and a sitecustomize socket blocker loaded before app imports."
    - id: RISK-2
      risk: "A broad output marker such as sentence-transformers could falsely fail because normal fetch output includes the model cache path."
      mitigation: "Assert precise token-warning and metadata/noise markers, and use the event log for online-capable load detection instead of banning normal model identifiers."
    - id: RISK-3
      risk: "A subprocess search test could pass without initializing the embedder if the palace is empty or search exits before query embedding."
      mitigation: "Seed a real Lance palace before spawning the subprocess and assert the fake SentenceTransformer constructor and encode calls were recorded."
    - id: RISK-4
      risk: "Blocking all sockets could create a false positive from unrelated localhost or DNS behavior."
      mitigation: "Keep the subprocess minimal, use fake sentence-transformers/HF modules, and treat any socket attempt as relevant evidence for this no-network contract."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_offline.py::test_cached_fetch_model_subprocess_guard -q"
      proves: "cached fetch-model uses only local model resolution and emits no token-warning output in a subprocess"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_offline.py::test_cached_search_subprocess_guard -q"
      proves: "cached search initializes the query embedder locally and emits no token-warning output in a subprocess"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_offline.py::test_offline_search_subprocess_no_online_retry_on_local_cache_error -q"
      proves: "offline cache-load failure does not fall through to online-capable model resolution or metadata calls"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_offline.py::test_force_fetch_model_subprocess_setup_boundary_allows_online_load -q"
      proves: "the intentional --force setup boundary remains online-capable while keeping third-party warning output suppressed"
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_offline.py -m 'not needs_network' -k 'subprocess or hf_home_selection' -q"
        proves: "new non-network subprocess guards and existing HF_HOME branch-selection coverage run in the default offline test set"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        command: "python -m pytest tests/test_cli_command_modules.py -k 'fetch_model' -q"
        proves: "existing in-process fetch_model call sequencing remains compatible with the subprocess guard"
        acceptance_ids: [AC-1, AC-4]
      - id: REG-3
        command: "python -m pytest tests/test_storage.py -k 'SentenceTransformerEmbedderResolution' -q"
        proves: "existing storage embedder local-first, offline-no-retry, and local-path boundaries remain covered"
        acceptance_ids: [AC-2, AC-3]
      - id: REG-4
        command: "ruff check tests/test_offline.py"
        proves: "the subprocess guard helper code remains lint-clean"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Keep this implementation test-only unless the new guard exposes a current leak. The current source already has local-first seams in `fetch_model()` and `_SentenceTransformerEmbedder`; the missing coverage is a real subprocess that captures fd-level output and import-time side effects.
- Add helper code in `tests/test_offline.py` that creates a temporary fake package root and prepends it to `PYTHONPATH` for subprocesses:
  - `sitecustomize.py` patches `socket.create_connection` and `socket.socket.connect` to append a `socket_attempt` event to a JSONL file and raise.
  - `sentence_transformers/__init__.py` provides a fake `SentenceTransformer` that appends constructor and `encode()` events, writes representative HuggingFace token-warning text directly to stdout/stderr, returns 384-dimensional vectors, and raises on online-capable loads when the test case disallows them.
  - `huggingface_hub/__init__.py` or a meta-path blocker records and raises on metadata helpers such as `model_info`, `hf_hub_download`, or `snapshot_download` if any code reaches them.
- For cached fetch, create `HF_HOME/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/fake` before running `python -m mempalace_code.cli fetch-model` so the subprocess represents a post-setup cache state.
- For cached search, seed a real Lance palace in the parent process before installing the fake subprocess modules. Use the default deterministic test embedder during setup, then run `python -m mempalace_code.cli --palace <palace> search <query>` under `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.
- Parse the JSONL event log after each subprocess. Cached paths should show constructor calls with `local_files_only: true` and no `online_load`, `metadata_attempt`, or `socket_attempt` events. The search happy path should also show an `encode` event so the test proves query embedding really happened.
- Assert precise warning markers such as `The token has not been saved`, `hf.co/settings/tokens`, `huggingface_hub`, and `Token is valid`, rather than broad strings like `sentence-transformers` that can appear in normal cache paths.
- Keep the failure-path test separate from fetch-model setup behavior. In explicit offline search, configure the fake local load to raise and assert the subprocess does not retry without `local_files_only`.
- Keep the setup boundary explicit: a `fetch-model --force` subprocess may record one online-capable constructor call, but the injected warning text must still be absent from captured output because `_quiet_hf_model_output()` owns that suppression.
