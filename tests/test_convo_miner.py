import os
import tempfile
import shutil
from unittest.mock import patch

from mempalace.convo_miner import mine_convos
from mempalace.storage import open_store


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    palace_path = os.path.join(tmpdir, "palace")
    mine_convos(tmpdir, palace_path, wing="test_convos")

    store = open_store(palace_path, create=False)
    assert store.count() >= 2

    # Verify search works
    results = store.query(query_texts=["memory persistence"], n_results=1, include=["documents"])
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir)


def test_mine_convos_calls_optimize_once():
    """mine_convos() calls collection.optimize() exactly once after all batches flush."""
    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        with patch("mempalace.convo_miner.get_collection") as mock_get_collection:
            from unittest.mock import MagicMock

            mock_store = MagicMock()
            mock_store.add.return_value = None
            mock_get_collection.return_value = mock_store
            mine_convos(tmpdir, palace_path, wing="test_convos")

        mock_store.optimize.assert_called_once()
    finally:
        shutil.rmtree(tmpdir)
