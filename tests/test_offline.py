"""
Integration test: offline operation after fetch_model.

Marked @pytest.mark.needs_network because the fetch step downloads ~80 MB from
HuggingFace Hub.  CI should skip these tests by default:

    pytest -m "not needs_network"

Run explicitly when a network connection is available:

    pytest tests/test_offline.py -v
"""

import os
from pathlib import Path

import pytest


def _configure_hf_home(tmp_path: Path, monkeypatch) -> str:
    """Select and configure HF_HOME, mirroring the CI-cache/tmp-cache branch logic.

    Returns the resolved HF_HOME string after setting it via monkeypatch.
    """
    ci_hf_home = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if ci_hf_home:
        hf_home = ci_hf_home
    else:
        hf_home = str(tmp_path / "hf")
        Path(hf_home).mkdir()
    monkeypatch.setenv("HF_HOME", hf_home)
    return hf_home


@pytest.mark.parametrize(
    "use_ci_cache",
    [True, False],
    ids=["ci_cache", "tmp_cache"],
)
def test_hf_home_selection(tmp_path, monkeypatch, use_ci_cache):
    """Branch-selection unit test: no model download, runs without needs_network."""
    if use_ci_cache:
        ci_path = str(tmp_path / "shared_hf")
        monkeypatch.setenv("MEMPALACE_TEST_HF_HOME", ci_path)
    else:
        monkeypatch.delenv("MEMPALACE_TEST_HF_HOME", raising=False)

    result = _configure_hf_home(tmp_path, monkeypatch)

    if use_ci_cache:
        assert result == str(tmp_path / "shared_hf")
        assert os.environ["HF_HOME"] == str(tmp_path / "shared_hf")
        assert not (tmp_path / "hf").exists()
    else:
        assert result == str(tmp_path / "hf")
        assert os.environ["HF_HOME"] == str(tmp_path / "hf")
        assert (tmp_path / "hf").is_dir()


@pytest.mark.needs_network
def test_search_works_offline_after_fetch(tmp_path, monkeypatch):
    """After fetch_model, querying the store must succeed with HF offline flags set."""
    # Use a CI-provided shared cache when available; otherwise isolate to a fresh temp dir.
    # MEMPALACE_TEST_HF_HOME is set by the model-backed CI job so the downloaded model
    # survives across test runs without being re-downloaded into a throwaway directory.
    _configure_hf_home(tmp_path, monkeypatch)

    # Step 1 — download the model (network allowed here)
    from mempalace_code.cli import fetch_model
    from mempalace_code.storage import DEFAULT_EMBED_MODEL

    fetch_model(DEFAULT_EMBED_MODEL)

    # Step 2 — go offline
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    # Step 3 — open a store and query; must not touch the network
    from mempalace_code.storage import LanceStore

    palace_path = str(tmp_path / "palace")
    store = LanceStore(palace_path=palace_path, create=True)
    results = store.query(["test"], n_results=1)

    # An empty palace returns a dict with list-of-list ids — no error means offline works
    assert isinstance(results, dict)
    assert "ids" in results
