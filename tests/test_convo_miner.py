import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from mempalace_code.convo_miner import (
    _chunk_by_exchange,
    file_already_mined,
    mine_convos,
    scan_convos,
)
from mempalace_code.storage import open_store


def test_chunk_by_exchange_preserves_exact_user_marker_lines():
    marker_lines = [
        "   > indented user marker   ",
        ">no-space user marker\t",
        ">   multi-space user marker  ",
    ]
    lines = [item for marker in marker_lines for item in (marker, "A sufficiently long reply.")]

    chunks = _chunk_by_exchange(lines)

    assert [chunk["content"].split("\n", 1)[0] for chunk in chunks] == marker_lines


def test_scan_convos_rejects_source_symlinks_by_default(tmp_path, capsys):
    regular = tmp_path / "chat.txt"
    regular.write_text(
        "> What happened?\nThe regular conversation was indexed safely.\n",
        encoding="utf-8",
    )
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(regular)
    except OSError as exc:
        import pytest

        pytest.skip(f"symlink creation unavailable: {exc}")

    assert scan_convos(str(tmp_path)) == [regular]
    assert capsys.readouterr().err == f"{link}: not a regular file (symlink)\n"


def test_incremental_skip_query_is_scoped_to_exact_source_and_wing():
    store = MagicMock()
    store.get.return_value = {"ids": ["existing"]}

    assert file_already_mined(store, "/tmp/chat.json", "conversations") is True
    store.get.assert_called_once_with(
        where={
            "$and": [
                {"source_file": "/tmp/chat.json"},
                {"wing": "conversations"},
            ]
        },
        limit=1,
    )


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


def test_full_replaces_changed_source_and_removes_stale_tail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    source_dir = tmp_path / "conversations"
    source_dir.mkdir()
    source = source_dir / "chat.txt"
    palace_path = str(tmp_path / "palace")
    source.write_text(
        "> First old question?\nFirst old answer with enough content.\n\n"
        "> Second old question?\nSecond old answer with enough content.\n\n"
        "> Stale tail question?\nStale tail answer that must disappear.\n",
        encoding="utf-8",
    )

    mine_convos(str(source_dir), palace_path, wing="test_convos", spellcheck=False)
    original = open_store(palace_path, create=False).get(
        where={"$and": [{"source_file": str(source)}, {"wing": "test_convos"}]},
        include=["documents", "metadatas"],
    )
    assert len(original["ids"]) == 3

    mine_convos(str(source_dir), palace_path, wing="test_convos", spellcheck=False)
    assert "Files skipped (already filed): 1" in capsys.readouterr().out
    assert (
        open_store(palace_path, create=False).get(
            where={"$and": [{"source_file": str(source)}, {"wing": "test_convos"}]},
            include=["documents", "metadatas"],
        )
        == original
    )

    source.write_text(
        "> Replacement question?\nReplacement sentinel content is now authoritative.\n",
        encoding="utf-8",
    )
    mine_convos(
        str(source_dir),
        palace_path,
        wing="test_convos",
        spellcheck=False,
        incremental=False,
    )

    replaced = open_store(palace_path, create=False).get(
        where={"$and": [{"source_file": str(source)}, {"wing": "test_convos"}]},
        include=["documents", "metadatas"],
    )
    assert len(replaced["ids"]) == 1
    assert replaced["documents"] == [
        "> Replacement question?\nReplacement sentinel content is now authoritative."
    ]
    assert all(metadata["wing"] == "test_convos" for metadata in replaced["metadatas"])
    summary = capsys.readouterr().out
    assert "Files processed: 1" in summary
    assert "Files skipped (already filed): 0" in summary
    assert "Drawers filed: 1" in summary


def test_full_normalization_failure_preserves_existing_source(tmp_path, monkeypatch, capsys):
    source = tmp_path / "chat.txt"
    source.write_text("input exists", encoding="utf-8")
    store = MagicMock()

    with (
        patch("mempalace_code.convo_miner.get_collection", return_value=store),
        patch("mempalace_code.convo_miner.normalize", side_effect=OSError("read failed")),
        patch("mempalace_code.convo_miner.optimize_store"),
    ):
        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
        mine_convos(
            str(tmp_path),
            str(tmp_path / "palace"),
            wing="test_convos",
            incremental=False,
        )

    store.replace_source.assert_not_called()
    assert "Files processed: 0" in capsys.readouterr().out


def test_full_empty_normalized_source_preserves_existing_source(tmp_path, monkeypatch, capsys):
    source = tmp_path / "chat.txt"
    source.write_text("input exists", encoding="utf-8")
    store = MagicMock()

    with (
        patch("mempalace_code.convo_miner.get_collection", return_value=store),
        patch("mempalace_code.convo_miner.normalize", return_value=""),
        patch("mempalace_code.convo_miner.optimize_store") as mock_optimize,
    ):
        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
        mine_convos(
            str(tmp_path),
            str(tmp_path / "palace"),
            wing="test_convos",
            incremental=False,
        )

    store.replace_source.assert_not_called()
    mock_optimize.assert_not_called()
    assert "Files processed: 1" in capsys.readouterr().out


def test_full_replace_failure_emits_no_success_or_summary_and_does_not_optimize(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "chat.txt"
    source.write_text("input exists", encoding="utf-8")
    store = MagicMock()
    store.replace_source.side_effect = RuntimeError("merge rejected")
    chunk = {"content": "replacement content", "chunk_index": 0}
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

    with (
        patch("mempalace_code.convo_miner.get_collection", return_value=store),
        patch("mempalace_code.convo_miner.normalize", return_value="normalized content" * 3),
        patch("mempalace_code.convo_miner.chunk_exchanges", return_value=[chunk]),
        patch("mempalace_code.convo_miner.optimize_store") as mock_optimize,
    ):
        with pytest.raises(RuntimeError, match="merge rejected"):
            mine_convos(
                str(tmp_path),
                str(tmp_path / "palace"),
                wing="test_convos",
                incremental=False,
            )

    output = capsys.readouterr().out
    assert "✓" not in output
    assert "  Done." not in output
    mock_optimize.assert_not_called()


def test_mine_convos_calls_optimize_once():
    """mine_convos() routes optimization through optimize_store() exactly once after all batches flush."""
    from unittest.mock import MagicMock

    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        with patch("mempalace_code.convo_miner.get_collection") as mock_get_collection:
            mock_store = MagicMock()
            mock_store.add.return_value = None
            mock_get_collection.return_value = mock_store
            with patch("mempalace_code.convo_miner.optimize_store") as mock_adapt:
                from mempalace_code.storage import OptimizeResult

                mock_adapt.return_value = OptimizeResult(ok=True, supported=True)
                mine_convos(tmpdir, palace_path, wing="test_convos")

        mock_adapt.assert_called_once()
    finally:
        shutil.rmtree(tmpdir)


def test_mine_convos_default_calls_safe_optimize_backup_first():
    """mine_convos() with default MempalaceConfig() calls optimize_store(backup_first=True)."""
    from unittest.mock import MagicMock

    from mempalace_code.storage import OptimizeResult

    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        with patch("mempalace_code.convo_miner.get_collection") as mock_get_collection:
            mock_store = MagicMock()
            mock_store.add.return_value = None
            mock_get_collection.return_value = mock_store
            with patch(
                "mempalace_code.convo_miner.optimize_store",
                return_value=OptimizeResult(ok=True, supported=True),
            ) as mock_adapter:
                # No env overrides — default config has backup_before_optimize=True
                mine_convos(tmpdir, palace_path, wing="test_convos")

        mock_adapter.assert_called_once()
        _, call_kwargs = mock_adapter.call_args
        backup_first_val = call_kwargs.get("backup_first")
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
