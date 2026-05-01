"""
Integration test: offline operation after fetch_model.

Marked @pytest.mark.needs_network because the fetch step downloads ~80 MB from
HuggingFace Hub.  CI should skip these tests by default:

    pytest -m "not needs_network"

Run explicitly when a network connection is available:

    pytest tests/test_offline.py -v
"""

import pytest


@pytest.mark.needs_network
def test_search_works_offline_after_fetch(tmp_path, monkeypatch):
    """After fetch_model, querying the store must succeed with HF offline flags set."""
    import os

    # Use a CI-provided shared cache when available; otherwise isolate to a fresh temp dir.
    # MEMPALACE_TEST_HF_HOME is set by the model-backed CI job so the downloaded model
    # survives across test runs without being re-downloaded into a throwaway directory.
    ci_hf_home = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if ci_hf_home:
        hf_home = ci_hf_home
    else:
        hf_home = str(tmp_path / "hf")
        import pathlib

        pathlib.Path(hf_home).mkdir()
    monkeypatch.setenv("HF_HOME", hf_home)

    # Step 1 — download the model (network allowed here)
    from mempalace.cli import fetch_model
    from mempalace.storage import DEFAULT_EMBED_MODEL

    fetch_model(DEFAULT_EMBED_MODEL)

    # Step 2 — go offline
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    # Step 3 — open a store and query; must not touch the network
    from mempalace.storage import LanceStore

    palace_path = str(tmp_path / "palace")
    store = LanceStore(palace_path=palace_path, create=True)
    results = store.query(["test"], n_results=1)

    # An empty palace returns a dict with list-of-list ids — no error means offline works
    assert isinstance(results, dict)
    assert "ids" in results
