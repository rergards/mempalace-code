---
slug: CI-CACHING-TEST-ENV-BRANCH
goal: "Add focused non-network coverage for HF_HOME selection in offline test helpers"
risk: low
risk_note: "Test-only change in one module; no production code, downloads, or fixture-wide behavior changes"
files:
  - path: tests/test_offline.py
    change: "Extract the MEMPALACE_TEST_HF_HOME/HF_HOME selection block into a private helper and add a parametrized non-network unit test covering CI-cache and tmp-cache branches"
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_offline.py -k 'hf_home_selection and ci_cache' -vv is run"
    then: "pytest reports the CI-cache parameter passed after asserting HF_HOME equals the MEMPALACE_TEST_HF_HOME value and tmp_path/hf was not created"
  - id: AC-2
    when: "python -m pytest tests/test_offline.py -k 'hf_home_selection and tmp_cache' -vv is run with MEMPALACE_TEST_HF_HOME unset"
    then: "pytest reports the tmp-cache parameter passed after asserting HF_HOME equals tmp_path/hf and that directory exists"
  - id: AC-3
    when: "python -m pytest tests/test_offline.py -m 'not needs_network' -k hf_home_selection -q is run"
    then: "the branch-selection unit test is selected and completes without invoking fetch_model, SentenceTransformer, or HuggingFace download output"
out_of_scope:
  - "Changing production cache or embedding behavior"
  - "Downloading or prewarming embedding models"
  - "Adding new helper files"
  - "Refactoring the e2e offline gate beyond what is needed for this focused unit coverage"
---

## Design Notes

- Keep the implementation test-only and local to `tests/test_offline.py`; no new fixture/helper file is needed.
- Move the duplicated setup block from `test_search_works_offline_after_fetch()` into a small private helper, for example `_configure_hf_home(tmp_path, monkeypatch)`.
- The existing network-marked offline integration test should call the helper so the new unit test covers the same branch-selection code used before `fetch_model()`.
- Add a parametrized test with explicit IDs such as `ci_cache` and `tmp_cache`; keep it unmarked so it runs under the default `not needs_network` filter.
- For the CI-cache branch, set `MEMPALACE_TEST_HF_HOME` to a path under `tmp_path`, call the helper, and assert `HF_HOME` is exactly that string while `tmp_path / "hf"` does not exist.
- For the tmp-cache fallback branch, delete `MEMPALACE_TEST_HF_HOME`, call the helper, and assert `HF_HOME` is `str(tmp_path / "hf")` and the directory exists.
- The unit test should not import or patch `fetch_model`; it should stop before any `SentenceTransformer` path is reachable. The existing `needs_network` integration test remains the only model-download test.
- Targeted verification after implementation:
  - `python -m pytest tests/test_offline.py -m "not needs_network" -k hf_home_selection -q`
  - `ruff check tests/test_offline.py`
