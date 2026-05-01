---
slug: STORE-CHROMA-IMPORT-ERROR-TESTS
goal: "Add isolated tests for ChromaStore ImportError behavior when the chromadb extra is absent"
risk: low
risk_note: "Test-only change for existing lazy import guards; no production behavior changes planned."
files:
  - path: tests/test_chroma_import_errors.py
    change: "New focused pytest module covering storage.ChromaStore lazy import and open_store(..., backend='chroma') ImportError paths with chromadb mocked absent."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_chroma_import_errors.py -q -k storage_chroma_store_import_error` is run in an environment where chromadb may or may not be installed"
    then: "the test passes and the captured ImportError message contains `mempalace[chroma]` for `from mempalace.storage import ChromaStore`."
  - id: AC-2
    when: "`python -m pytest tests/test_chroma_import_errors.py -q -k open_store_chroma_import_error` is run in an environment where chromadb may or may not be installed"
    then: "the test passes and the captured ImportError message contains `mempalace[chroma]` for `open_store(tmp_path, backend='chroma')`."
  - id: AC-3
    when: "`python -m pytest tests/test_chroma_import_errors.py tests/test_chroma_compat.py -q` is run without chromadb installed"
    then: "the new import-error tests pass and the existing ChromaDB compatibility tests are skipped rather than failing."
  - id: AC-4
    when: "`python -m pytest tests/test_chroma_import_errors.py -q` is run with chromadb installed"
    then: "the new import-error tests still pass by using the mocked-absent chromadb module state instead of the real installed package."
out_of_scope:
  - "Changing storage.py ImportError messages or lazy import implementation."
  - "Removing or rewriting existing chromadb-dependent compatibility tests."
  - "Adding ChromaDB as a required test dependency."
---

## Design Notes

- Put the coverage in a new `tests/test_chroma_import_errors.py` module so optional-backend failure-path tests stay separate from LanceDB storage behavior and ChromaDB compatibility smoke tests.
- Use `unittest.mock.patch.dict(sys.modules, {"chromadb": None})` to force Python's import machinery to behave as though the optional dependency is absent, even if the developer has installed `.[chroma]`.
- Before each assertion, remove `mempalace._chroma_store` from `sys.modules` if present. Without this, a prior successful import can leave the module cached and bypass the mocked missing dependency.
- Import `mempalace.storage` normally, then exercise the public compatibility surfaces:
  - `from mempalace.storage import ChromaStore`
  - `open_store(str(tmp_path), backend="chroma")`
- Assert on the helpful public message substring `mempalace[chroma]`, not on the underlying Python `No module named chromadb` wording.
- Leave `tests/test_chroma_compat.py` guarded by `pytest.importorskip("chromadb")`; these new tests should not require chromadb and should not change the chroma-compat CI job's positive coverage.
