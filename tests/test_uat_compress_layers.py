"""UAT regressions for `compress` (AAAK) and `wake-up` (memory layers).

compress is read-only: drawers keep their verbatim text. Drawers that a pre-1.15.0
compress overwrote can be restored from a backup archive with --recover-from.
wake-up ranks L1 drawers, caps L0, and prints only the context on stdout.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from mempalace_code.cli import main
from mempalace_code.dialect import Dialect
from mempalace_code.layers import Layer0, Layer1, MemoryStack
from mempalace_code.storage import LanceStore, open_store

ROOT = Path(__file__).resolve().parent.parent

BILLING_TEXT = (
    '"""Billing helpers."""\n'
    "\n"
    "# We decided to round half-even because accountants asked for bankers rounding.\n"
    'TAX_RATE = Decimal("0.19")\n'
    "\n"
    "def tax_for(amount):\n"
    '    """Return VAT for an amount, rounded half-even to cents."""\n'
    "    return (amount * TAX_RATE).quantize(CENT, rounding=ROUND_HALF_EVEN)\n"
)
DIARY_TEXT = (
    "Diary entry number 3 about the refund gateway timeout investigation. "
    "We decided to raise the timeout to 30s."
)
MANUAL_TEXT = "The license is Apache-2.0 because of the patent grant, and Dana owns the registry."


def _seed_palace(palace: Path) -> LanceStore:
    store = open_store(str(palace), create=True)
    store.add(
        ids=["drawer_tproj_src_billing", "diary_wing_orin_1", "drawer_notes_manual_1"],
        documents=[BILLING_TEXT, DIARY_TEXT, MANUAL_TEXT],
        metadatas=[
            {
                "wing": "tproj",
                "room": "src",
                "source_file": "/work/tproj/src/billing.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-09-01T10:00:00",
                "ingest_mode": "file",
                "source_hash": "0" * 32,
                "chunker_strategy": "regex_structural_v1",
                "line_start": 1,
                "line_end": 8,
            },
            {
                "wing": "wing_orin",
                "room": "diary",
                "hall": "hall_diary",
                "topic": "decisions",
                "type": "diary_entry",
                "agent": "orin",
                "filed_at": "2026-09-02T10:00:00",
                "date": "2026-09-02",
                "chunker_strategy": "diary_v1",
            },
            {
                "wing": "notes",
                "room": "legal",
                "filed_at": "2026-09-03T10:00:00",
                "chunker_strategy": "manual_v1",
            },
        ],
    )
    return store


def _run_cli(capsys, *argv):
    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _all_rows(palace: Path) -> dict:
    store = open_store(str(palace), create=False, read_only=True)
    got = store.get(include=["documents", "metadatas"], limit=10000)
    return {
        doc_id: (text, meta)
        for doc_id, text, meta in zip(got["ids"], got["documents"], got["metadatas"])
    }


def _legacy_compress(palace: Path, ids) -> None:
    """Rewrite drawers the way `compress` did before 1.15.0 (AAAK text in place)."""
    store = open_store(str(palace), create=False)
    dialect = Dialect()
    got = store.get(ids=list(ids), include=["documents", "metadatas"])
    for doc_id, text, meta in zip(got["ids"], got["documents"], got["metadatas"]):
        summary = dialect.compress(text, metadata=meta)
        stats = dialect.compression_stats(text, summary)
        legacy_meta = dict(meta)
        legacy_meta["compression_ratio"] = round(stats["size_ratio"], 1)
        legacy_meta["original_tokens"] = stats["original_tokens_est"]
        store.upsert(ids=[doc_id], documents=[summary], metadatas=[legacy_meta])


# ── compress keeps drawers verbatim (convos-7, ops-6, convos-19) ─────────────


class TestCompressKeepsDrawersVerbatim:
    def test_compress_all_wings_leaves_every_drawer_and_version_unchanged(
        self, tmp_path, capsys, monkeypatch
    ):
        palace = tmp_path / "palace"
        _seed_palace(palace)
        before = _all_rows(palace)
        versions_before = len(
            open_store(str(palace), create=False, read_only=True)._require_table().list_versions()
        )

        def no_embedder(_store):
            raise AssertionError("compress must not load the embedder")

        monkeypatch.setattr(LanceStore, "_get_embedder", no_embedder)
        code, out, err = _run_cli(capsys, "--palace", str(palace), "compress")

        assert code == 0, err
        assert "drawers keep their verbatim text and nothing is stored" in out
        # The diary drawer is summarized in the output only.
        assert "diary_wing_orin_1" in out
        assert _all_rows(palace) == before
        after_store = open_store(str(palace), create=False, read_only=True)
        assert len(after_store._require_table().list_versions()) == versions_before
        assert not (tmp_path / "backups").exists()

    def test_read_slice_still_returns_source_lines_after_compress(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        _seed_palace(palace)

        assert _run_cli(capsys, "--palace", str(palace), "compress", "--wing", "tproj")[0] == 0
        code, out, err = _run_cli(
            capsys,
            "--palace",
            str(palace),
            "read",
            "billing.py",
            "--start",
            "3",
            "--end",
            "4",
            "--wing",
            "tproj",
        )

        assert code == 0, err
        assert "3: # We decided to round half-even because accountants" in out
        assert '4: TAX_RATE = Decimal("0.19")' in out


# ── --config handling (convos-23) ────────────────────────────────────────────


class TestCompressEntityConfig:
    def test_missing_config_exits_2_with_guidance(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        _seed_palace(palace)
        missing = tmp_path / "nope" / "entities.json"

        code, out, err = _run_cli(
            capsys, "--palace", str(palace), "compress", "--dry-run", "--config", str(missing)
        )

        assert code == 2
        assert f"cannot use entity config {missing}" in err
        assert "No such file or directory" in err
        assert "--detect-entities" in err
        assert "Selected" not in out

    def test_invalid_json_config_exits_2_without_traceback(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        _seed_palace(palace)
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")

        code, _out, err = _run_cli(
            capsys, "--palace", str(palace), "compress", "--config", str(bad)
        )

        assert code == 2
        assert "not valid JSON" in err
        assert "line 1, column 2" in err
        assert "Traceback" not in err

    def test_entities_json_in_cwd_is_not_loaded_implicitly(self, tmp_path, capsys, monkeypatch):
        palace = tmp_path / "palace"
        _seed_palace(palace)
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        (cwd / "entities.json").write_text("{not json", encoding="utf-8")
        monkeypatch.chdir(cwd)

        code, out, err = _run_cli(capsys, "--palace", str(palace), "compress")

        assert code == 0, err
        assert "Loaded entity config" not in out


# ── statistics and key quotes (convos-24, ops-7) ─────────────────────────────


class TestCompressStatistics:
    def test_total_ratio_matches_token_totals(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        _seed_palace(palace)

        code, out, _err = _run_cli(capsys, "--palace", str(palace), "compress")

        assert code == 0
        rows = [(int(a), int(b)) for a, b in re.findall(r"(?m)^    (\d+)t -> (\d+)t \(", out)]
        total = re.search(r"(?m)^  Total: (\d+)t -> (\d+)t \((\d+\.\d)x compression\)", out)
        assert rows
        assert total is not None
        original, summary = sum(r[0] for r in rows), sum(r[1] for r in rows)
        assert (int(total.group(1)), int(total.group(2))) == (original, summary)
        assert total.group(3) == f"{original / summary:.1f}"
        assert all(after < before for before, after in rows)


# ── recovery of palaces compressed before 1.15.0 ─────────────────────────────


class TestCompressRecoverFromArchive:
    def _legacy_palace(self, tmp_path):
        from mempalace_code.backup import create_backup

        palace = tmp_path / "palace"
        _seed_palace(palace)
        verbatim = _all_rows(palace)
        _meta, archive = create_backup(str(palace), kind="manual")
        _legacy_compress(palace, ["drawer_tproj_src_billing", "diary_wing_orin_1"])
        later = open_store(str(palace), create=False)
        later.add(
            ids=["diary_wing_orin_2"],
            documents=["A later diary entry written after compress."],
            metadatas=[
                {"wing": "wing_orin", "room": "diary", "chunker_strategy": "diary_v1"},
            ],
        )
        return palace, str(archive), verbatim

    def test_compress_reports_legacy_drawers_instead_of_summarizing_them(self, tmp_path, capsys):
        palace, _archive, _verbatim = self._legacy_palace(tmp_path)

        code, out, err = _run_cli(capsys, "--palace", str(palace), "compress")

        assert code == 0
        assert "Warning: 2 drawers already hold AAAK text" in err
        assert "compress --recover-from <archive> --dry-run" in err
        assert "drawer_tproj_src_billing" not in out

    def test_dry_run_then_recovery_restores_exact_text_and_keeps_later_writes(
        self, tmp_path, capsys
    ):
        palace, archive, verbatim = self._legacy_palace(tmp_path)
        compressed = _all_rows(palace)

        code, out, err = _run_cli(
            capsys, "--palace", str(palace), "compress", "--recover-from", archive, "--dry-run"
        )
        assert code == 0, err
        assert "holding AAAK text from an earlier compress: 2" in out
        assert f"Recoverable from {archive}: 2" in out
        assert _all_rows(palace) == compressed

        code, out, err = _run_cli(
            capsys, "--palace", str(palace), "compress", "--recover-from", archive
        )
        assert code == 0, err
        assert "Restored verbatim text for 2 drawers." in out
        restored = _all_rows(palace)
        for doc_id in ("drawer_tproj_src_billing", "diary_wing_orin_1", "drawer_notes_manual_1"):
            assert restored[doc_id] == verbatim[doc_id]
        assert restored["diary_wing_orin_2"][0] == "A later diary entry written after compress."

        code, out, _err = _run_cli(
            capsys, "--palace", str(palace), "compress", "--recover-from", archive
        )
        assert code == 0
        assert "nothing to do" in out

    def test_drawer_missing_from_archive_is_listed_and_exits_1(self, tmp_path, capsys):
        from mempalace_code.backup import create_backup

        palace = tmp_path / "palace"
        _seed_palace(palace)
        _meta, archive = create_backup(str(palace), kind="manual")
        extra = open_store(str(palace), create=False)
        extra.add(
            ids=["drawer_notes_manual_2"],
            documents=["A manual note filed after the archive was created, long enough."],
            metadatas=[{"wing": "notes", "room": "legal", "chunker_strategy": "manual_v1"}],
        )
        _legacy_compress(palace, ["diary_wing_orin_1", "drawer_notes_manual_2"])

        code, out, err = _run_cli(
            capsys, "--palace", str(palace), "compress", "--recover-from", str(archive)
        )

        assert code == 1
        assert "Restored verbatim text for 1 drawers." in out
        assert "Not recoverable from this archive: 1" in err
        assert "drawer_notes_manual_2" in err
        assert "rerun with an older archive" in err
        assert _all_rows(palace)["diary_wing_orin_1"][0] == DIARY_TEXT

    def test_missing_archive_exits_2_before_touching_the_palace(self, tmp_path, capsys):
        palace, _archive, _verbatim = self._legacy_palace(tmp_path)
        before = _all_rows(palace)

        code, _out, err = _run_cli(
            capsys,
            "--palace",
            str(palace),
            "compress",
            "--recover-from",
            str(tmp_path / "missing.tar.gz"),
        )

        assert code == 2
        assert "backup archive not found" in err
        assert "backup list" in err
        assert _all_rows(palace) == before

    def test_recovery_refuses_while_maintenance_holds_the_exclusive_lease(
        self, tmp_path, capsys, exclusive_install_lease_elsewhere
    ):
        palace, archive, _verbatim = self._legacy_palace(tmp_path)
        before = _all_rows(palace)

        with exclusive_install_lease_elsewhere():
            code, _out, err = _run_cli(
                capsys, "--palace", str(palace), "compress", "--recover-from", archive
            )

        assert code == 1
        assert "recovery did not start: MemPalace operation is already running" in err
        assert "compress --recover-from" in err
        assert _all_rows(palace) == before

    def test_recovery_refuses_while_another_writer_holds_the_palace(
        self, tmp_path, capsys, monkeypatch
    ):
        import threading

        from mempalace_code import operation_lock

        palace, archive, _verbatim = self._legacy_palace(tmp_path)
        before = _all_rows(palace)
        monkeypatch.setattr(operation_lock, "DEFAULT_PALACE_WRITE_WAIT_SECONDS", 0.2)
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with operation_lock.palace_write_lease(str(palace), "mine", wait=0):
                held.set()
                release.wait(10)

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            assert held.wait(10)
            code, _out, err = _run_cli(
                capsys, "--palace", str(palace), "compress", "--recover-from", archive
            )
        finally:
            release.set()
            holder.join(10)

        assert code == 1
        assert "recovery did not start: Another MemPalace writer" in err
        assert "compress --recover-from" in err
        assert "Traceback" not in err
        assert _all_rows(palace) == before


# ── wake-up L1 selection (convos-16, layers-1) ───────────────────────────────


def _seed_wakeup_palace(palace: Path) -> None:
    store = open_store(str(palace), create=True)
    ids, docs, metas = [], [], []
    for index in range(20):
        ids.append(f"code_{index:02d}")
        docs.append(f"def handler_{index}(request):\n    return request.value * {index}\n")
        metas.append(
            {
                "wing": "proj",
                "room": "src",
                "source_file": f"/proj/src/mod_{index}.py",
                "ingest_mode": "file",
                "filed_at": f"2026-09-10T10:00:{index:02d}",
            }
        )
    ids += ["convo_chat", "convo_decision", "json_noise", "diary_old", "note_manual"]
    docs += [
        "We talked about the Heron sprint retro and what went well.",
        "We decided to ship Atlas on pgvector instead of a separate vector store.",
        '[\n  {\n    "uuid": "d1", "name": "Borealis telemetry"\n  }\n]',
        "DECISION_DIARY_1: remember that the gateway timeout is now 30s.",
        "Manual note: the on-call rotation changes every Monday.",
    ]
    metas += [
        {"wing": "convos", "room": "general", "ingest_mode": "convos", "filed_at": "2026-09-11"},
        {"wing": "convos", "room": "decision", "ingest_mode": "convos", "filed_at": "2026-09-01"},
        {"wing": "convos", "room": "general", "ingest_mode": "convos", "filed_at": "2026-09-12"},
        {
            "wing": "wing_orin",
            "room": "diary",
            "chunker_strategy": "diary_v1",
            "filed_at": "2026-08-01T09:00:00",
            "date": "2026-08-01",
        },
        {
            "wing": "notes",
            "room": "ops",
            "chunker_strategy": "manual_v1",
            "filed_at": "2026-08-02T09:00:00",
        },
    ]
    store.add(ids=ids, documents=docs, metadatas=metas)


class TestWakeUpEssentialStory:
    def test_notes_and_decisions_come_before_newer_project_drawers(self, tmp_path):
        palace = tmp_path / "palace"
        _seed_wakeup_palace(palace)

        text = Layer1(str(palace)).generate()

        order = [
            text.index("Manual note: the on-call rotation"),
            text.index("DECISION_DIARY_1"),
            text.index("We decided to ship Atlas on pgvector"),
            text.index("Heron sprint retro"),
            text.index("def handler_19(request)"),
        ]
        assert order == sorted(order)
        assert "Borealis" not in text
        assert "[wing_orin/diary]" in text
        # Whitespace is collapsed so code snippets read as one line.
        assert "def handler_19(request): return request.value * 19" in text
        assert text.count("\n  - ") <= Layer1.MAX_DRAWERS

    def test_wing_scope_applies_to_one_call_only(self, tmp_path):
        palace = tmp_path / "palace"
        _seed_wakeup_palace(palace)
        stack = MemoryStack(palace_path=str(palace), identity_path=str(tmp_path / "none.txt"))

        scoped = stack.wake_up(wing="convos")
        unscoped = stack.wake_up()

        assert "DECISION_DIARY_1" not in scoped
        assert "[decision]" in scoped
        assert "DECISION_DIARY_1" in unscoped

    def test_ranking_reads_metadata_and_fetches_text_only_for_candidates(
        self, tmp_path, monkeypatch
    ):
        palace = tmp_path / "palace"
        _seed_wakeup_palace(palace)
        calls = []
        real_get = LanceStore.get

        def tracking_get(self, ids=None, where=None, include=None, limit=10000, offset=0):
            calls.append(ids)
            return real_get(self, ids=ids, where=where, include=include, limit=limit, offset=offset)

        monkeypatch.setattr(LanceStore, "get", tracking_get)
        Layer1(str(palace)).generate()

        assert calls, "L1 must fetch text for its candidates"
        assert all(ids is not None for ids in calls), "L1 must not page through every drawer"
        assert sum(len(ids) for ids in calls) <= Layer1.MAX_CANDIDATES


# ── wake-up edge cases (convos-29) ───────────────────────────────────────────


class TestWakeUpEdgeCases:
    def test_identity_is_capped_and_cli_warns_on_stderr(self, tmp_path, capsys, monkeypatch):
        palace = tmp_path / "palace"
        _seed_wakeup_palace(palace)
        home = tmp_path / "home"
        identity = home / ".mempalace" / "identity.txt"
        identity.parent.mkdir(parents=True)
        identity.write_text("I am Orin. " * 2000, encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))

        layer = Layer0(str(identity))
        rendered = layer.render()
        assert layer.truncated
        assert len(rendered) <= Layer0.MAX_CHARS + 4

        code, out, err = _run_cli(capsys, "--palace", str(palace), "wake-up")
        assert code == 0
        assert out.startswith("I am Orin.")
        assert len(out) < 4000
        assert "Wake-up text (~" in err
        assert "is longer than 800 characters" in err

    def test_stdout_carries_only_the_context(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        _seed_wakeup_palace(palace)

        code, out, err = _run_cli(capsys, "--palace", str(palace), "wake-up")

        assert code == 0
        assert out.startswith("## L0 — IDENTITY")
        assert "Wake-up text" not in out
        assert "=====" not in out
        assert err.startswith("Wake-up text (~")

    def test_missing_palace_exits_1_without_creating_it(self, tmp_path, capsys):
        palace = tmp_path / "nonexistent_palace"

        code, out, err = _run_cli(capsys, "--palace", str(palace), "wake-up")

        assert code == 1
        assert out == ""
        assert f"No palace found at {palace}" in err
        assert f"--palace {palace} mine <dir>" in err
        assert not palace.exists()

    def test_blank_wing_is_rejected(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        _seed_wakeup_palace(palace)

        code, out, err = _run_cli(capsys, "--palace", str(palace), "wake-up", "--wing", "")

        assert code == 2
        assert out == ""
        assert "--wing must not be blank" in err

    def test_closed_stdout_pipe_exits_quietly(self, tmp_path):
        palace = tmp_path / "palace"
        _seed_wakeup_palace(palace)
        read_end, write_end = os.pipe()
        os.close(read_end)
        env = dict(os.environ, PYTHONPATH=str(ROOT), HOME=str(tmp_path / "home"))
        try:
            result = subprocess.run(
                [sys.executable, "-m", "mempalace_code.cli", "--palace", str(palace), "wake-up"],
                stdout=write_end,
                stderr=subprocess.PIPE,
                env=env,
                timeout=120,
                check=False,
            )
        finally:
            os.close(write_end)

        stderr = result.stderr.decode()
        assert result.returncode == 0, stderr
        assert "BrokenPipeError" not in stderr
        assert "Traceback" not in stderr
