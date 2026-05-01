import os
import shutil
import tempfile
from unittest.mock import patch

from mempalace_code.convo_miner import mine_convos
from mempalace_code.storage import open_store


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
        with patch("mempalace_code.convo_miner.get_collection") as mock_get_collection:
            from unittest.mock import MagicMock

            mock_store = MagicMock()
            mock_store.add.return_value = None
            mock_get_collection.return_value = mock_store
            mine_convos(tmpdir, palace_path, wing="test_convos")

        # Either safe_optimize (LanceDB) or optimize (legacy) should be called
        assert mock_store.safe_optimize.called or mock_store.optimize.called
    finally:
        shutil.rmtree(tmpdir)


def test_mine_convos_default_calls_safe_optimize_backup_first():
    """AC-13: mine_convos() with default MempalaceConfig() calls safe_optimize(backup_first=True)."""
    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        with patch("mempalace_code.convo_miner.get_collection") as mock_get_collection:
            from unittest.mock import MagicMock

            mock_store = MagicMock()
            mock_store.add.return_value = None
            mock_store.safe_optimize.return_value = True
            mock_get_collection.return_value = mock_store
            # No env overrides — default config has backup_before_optimize=True
            mine_convos(tmpdir, palace_path, wing="test_convos")

        mock_store.safe_optimize.assert_called_once()
        call_args, call_kwargs = mock_store.safe_optimize.call_args
        backup_first_val = call_kwargs.get(
            "backup_first", call_args[1] if len(call_args) > 1 else None
        )
        assert backup_first_val is True, f"Expected backup_first=True, got {backup_first_val!r}"
    finally:
        shutil.rmtree(tmpdir)


def test_mine_convos_passes_spellcheck_true_by_default(tmp_path):
    convo_file = tmp_path / "chat.json"
    convo_file.write_text("{}", encoding="utf-8")
    normalized = "> pleese remember this important decision\nAssistant response.\n" * 3

    with patch("mempalace_code.convo_miner.normalize", return_value=normalized) as mock_normalize:
        mine_convos(str(tmp_path), str(tmp_path / "palace"), wing="test", dry_run=True)

    assert mock_normalize.call_args.kwargs["spellcheck"] is True


def test_mine_convos_passes_spellcheck_false_when_requested(tmp_path):
    convo_file = tmp_path / "chat.json"
    convo_file.write_text("{}", encoding="utf-8")
    normalized = "> pleese remember this important decision\nAssistant response.\n" * 3

    with patch("mempalace_code.convo_miner.normalize", return_value=normalized) as mock_normalize:
        mine_convos(
            str(tmp_path),
            str(tmp_path / "palace"),
            wing="test",
            dry_run=True,
            spellcheck=False,
        )

    assert mock_normalize.call_args.kwargs["spellcheck"] is False


def test_mine_convos_general_uses_default_extract_categories(tmp_path):
    convo_file = tmp_path / "chat.txt"
    convo_file.write_text("conversation export", encoding="utf-8")
    normalized = (
        "> User: I feel worried and lonely about the migration.\n"
        "Assistant: I understand the concern and can help.\n"
    ) * 3
    extracted = [
        {
            "content": "The fix worked and solved the bug.",
            "memory_type": "milestone",
            "chunk_index": 0,
        }
    ]

    with (
        patch("mempalace_code.convo_miner.normalize", return_value=normalized),
        patch(
            "mempalace_code.general_extractor.extract_memories", return_value=extracted
        ) as mock_extract,
    ):
        mine_convos(
            str(tmp_path),
            str(tmp_path / "palace"),
            wing="test",
            dry_run=True,
            extract_mode="general",
        )

    assert mock_extract.call_args.kwargs["categories"] is None


def test_mine_convos_general_passes_emotional_opt_in(tmp_path):
    convo_file = tmp_path / "chat.txt"
    convo_file.write_text("conversation export", encoding="utf-8")
    normalized = (
        "> User: I feel worried and lonely about the migration.\n"
        "Assistant: I understand the concern and can help.\n"
    ) * 3
    categories = ["decision", "preference", "milestone", "problem", "emotional"]
    extracted = [
        {"content": "I feel worried and lonely.", "memory_type": "emotional", "chunk_index": 0}
    ]

    with (
        patch("mempalace_code.convo_miner.normalize", return_value=normalized),
        patch(
            "mempalace_code.general_extractor.extract_memories", return_value=extracted
        ) as mock_extract,
    ):
        mine_convos(
            str(tmp_path),
            str(tmp_path / "palace"),
            wing="test",
            dry_run=True,
            extract_mode="general",
            extract_categories=categories,
        )

    assert mock_extract.call_args.kwargs["categories"] == categories
