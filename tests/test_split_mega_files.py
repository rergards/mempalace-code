import json
import multiprocessing as mp
import os
import queue
import sys

import pytest

from mempalace_code import split_mega_files as smf
from mempalace_code.source_io import RegularSourceError


def _require_fifo() -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available on this platform")


def _try_symlink(link, target) -> bool:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        return False
    return True


def _mp_context():
    if sys.platform != "win32" and "fork" in mp.get_all_start_methods():
        return mp.get_context("fork")
    return mp.get_context("spawn")


def _run_child(worker, *args, timeout: float = 10.0) -> dict:
    ctx = _mp_context()
    result_queue = ctx.Queue()
    proc = ctx.Process(target=worker, args=(*args, result_queue))
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        pytest.fail(f"{worker.__name__} exceeded {timeout}s hard timeout")
    assert proc.exitcode == 0, f"{worker.__name__} exited {proc.exitcode}"
    try:
        return result_queue.get_nowait()
    except queue.Empty:
        pytest.fail(f"{worker.__name__} returned no result")


def _split_worker(mega: str, out_dir: str, bypass_precheck: bool, result_queue) -> None:
    """Child: run a real split so a blocking output open fails the hard timeout."""
    from mempalace_code import split_mega_files as child_smf

    if bypass_precheck:
        child_smf._reject_non_regular_output_entry = lambda _out_path, **_kwargs: None

    try:
        written = child_smf.split_file(mega, out_dir)
        result_queue.put({"status": "ok", "value": [str(path) for path in written]})
    except Exception as exc:
        result_queue.put({"status": "error", "type": type(exc).__name__, "message": str(exc)})


def _session(prompt: str) -> str:
    return "Claude Code v1\n" + "\n".join([f"> {prompt}"] + ["answer"] * 12)


def _write_mega(tmp_path):
    mega = tmp_path / "mega.txt"
    mega.write_text(_session("prompt") + "\n" + _session("prompt two"), encoding="utf-8")
    return mega


def _planned_outputs(mega, out_dir):
    """Resolve the filenames split_file will synthesize, without writing anything."""
    return smf.split_file(mega, out_dir, dry_run=True)


def test_split_file_writes_regular_chunks(tmp_path):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = smf.split_file(mega, out_dir)

    assert len(written) == 2
    assert [path.parent for path in written] == [out_dir, out_dir]
    assert written[0].name.startswith("mega_part01_")
    assert written[0].name.endswith("_prompt.txt")
    assert written[1].name.startswith("mega_part02_")
    assert written[1].name.endswith("_prompt-two.txt")
    assert written[0].read_text(encoding="utf-8") == _session("prompt") + "\n"
    assert written[1].read_text(encoding="utf-8") == _session("prompt two")
    assert sorted(path.name for path in out_dir.iterdir()) == sorted(p.name for p in written)


def test_split_file_dry_run_creates_no_output_files(tmp_path):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"

    planned = smf.split_file(mega, out_dir, dry_run=True)

    assert len(planned) == 2
    assert not out_dir.exists()
    assert mega.exists()


def test_split_file_with_only_tiny_fragments_leaves_output_dir_absent(tmp_path):
    mega = tmp_path / "mega.txt"
    mega.write_text("Claude Code v1\nshort\nClaude Code v1\nshort", encoding="utf-8")
    out_dir = tmp_path / "out"

    written = smf.split_file(mega, out_dir)

    assert written == []
    assert not out_dir.exists()
    assert mega.read_text(encoding="utf-8") == "Claude Code v1\nshort\nClaude Code v1\nshort"


def test_split_file_refuses_a_fifo_at_a_synthesized_output_name(tmp_path):
    _require_fifo()
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    blocked = _planned_outputs(mega, out_dir)[0]
    os.mkfifo(blocked)

    result = _run_child(_split_worker, str(mega), str(out_dir), False)

    assert result["status"] == "error", result
    assert result["type"] == "RegularSourceError"
    assert "not a regular output target" in result["message"]
    assert str(blocked) in result["message"]
    # The hostile entry is left untouched for operator inspection.
    assert os.path.exists(blocked)
    assert not os.path.isfile(blocked)


def test_split_output_descriptor_refuses_a_reader_less_fifo_without_the_precheck(tmp_path):
    """O_NONBLOCK, not the lstat pre-check, is what keeps the open from hanging."""
    _require_fifo()
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    blocked = _planned_outputs(mega, out_dir)[0]
    os.mkfifo(blocked)

    result = _run_child(_split_worker, str(mega), str(out_dir), True)

    assert result["status"] == "error", result
    assert result["type"] == "RegularSourceError"
    assert "not a regular output target" in result["message"]


def test_split_output_descriptor_refuses_a_fifo_with_a_live_reader(tmp_path, monkeypatch):
    """A live reader lets the open succeed, so fstat must reject the descriptor."""
    _require_fifo()
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    blocked = _planned_outputs(mega, out_dir)[0]
    os.mkfifo(blocked)
    monkeypatch.setattr(
        smf,
        "_reject_non_regular_output_entry",
        lambda _out_path, **_kwargs: None,
    )

    reader_fd = os.open(blocked, os.O_RDWR | getattr(os, "O_NONBLOCK", 0))
    try:
        with pytest.raises(RegularSourceError, match="not a regular output target"):
            smf.split_file(mega, out_dir)
    finally:
        os.close(reader_fd)

    assert not os.path.isfile(blocked)


def test_split_file_refuses_a_dangling_symlink_output_target(tmp_path):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = outside / "escaped.txt"
    blocked = _planned_outputs(mega, out_dir)[0]
    if not _try_symlink(blocked, escaped):
        pytest.skip("symlink creation is not available for this user/platform")

    with pytest.raises(RegularSourceError, match="not a regular output target"):
        smf.split_file(mega, out_dir)

    # Path.exists() answers False for a dangling link, so a bare existence probe
    # would have created this file outside the requested output directory.
    assert not escaped.exists()
    assert list(outside.iterdir()) == []
    assert blocked.is_symlink()


def test_split_file_refuses_a_redirecting_symlink_output_target(tmp_path):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("pre-existing content", encoding="utf-8")
    blocked = _planned_outputs(mega, out_dir)[0]
    if not _try_symlink(blocked, victim):
        pytest.skip("symlink creation is not available for this user/platform")

    with pytest.raises(RegularSourceError, match="not a regular output target"):
        smf.split_file(mega, out_dir)

    assert victim.read_text(encoding="utf-8") == "pre-existing content"


def test_main_refuses_a_symlink_explicit_output_directory(tmp_path, monkeypatch, capsys):
    mega = _write_mega(tmp_path)
    original = mega.read_text(encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    out_dir = tmp_path / "out"
    if not _try_symlink(out_dir, outside):
        pytest.skip("symlink creation is not available for this user/platform")
    monkeypatch.setattr(sys, "argv", ["split", "--file", str(mega), "--output-dir", str(out_dir)])

    with pytest.raises(SystemExit) as raised:
        smf.main()

    assert raised.value.code == 1
    assert mega.read_text(encoding="utf-8") == original
    assert not mega.with_suffix(".mega_backup").exists()
    assert list(outside.iterdir()) == []
    combined = capsys.readouterr()
    assert "not a safe output directory" in combined.err
    assert combined.err.count("retry with a new empty --output-dir") == 1


def test_main_fails_closed_when_explicit_output_directory_is_replaced(
    tmp_path, monkeypatch, capsys
):
    mega = _write_mega(tmp_path)
    original = mega.read_text(encoding="utf-8")
    out_dir = tmp_path / "out"
    anchored_dir = tmp_path / "anchored-output"
    original_write = smf._write_regular_output
    write_count = 0

    def replace_after_first_write(out_path, text, *, dir_fd=None):
        nonlocal write_count
        original_write(out_path, text, dir_fd=dir_fd)
        write_count += 1
        if write_count == 1:
            out_dir.rename(anchored_dir)
            out_dir.mkdir()

    monkeypatch.setattr(smf, "_write_regular_output", replace_after_first_write)
    monkeypatch.setattr(sys, "argv", ["split", "--file", str(mega), "--output-dir", str(out_dir)])

    with pytest.raises(SystemExit) as raised:
        smf.main()

    assert raised.value.code == 1
    assert mega.read_text(encoding="utf-8") == original
    assert not mega.with_suffix(".mega_backup").exists()
    assert len(list(anchored_dir.iterdir())) == 1
    assert list(out_dir.iterdir()) == []
    captured = capsys.readouterr()
    assert "not a safe output directory" in captured.err
    assert captured.err.count("retry with a new empty --output-dir") == 1
    assert "created 1 files; failed 1 of 1 mega-files" in captured.out


def test_split_file_refuses_a_hardlinked_output_target(tmp_path):
    if not hasattr(os, "link"):
        pytest.skip("hardlink creation is not available on this platform")
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("pre-existing content", encoding="utf-8")
    blocked = _planned_outputs(mega, out_dir)[0]
    try:
        os.link(victim, blocked)
    except OSError:
        pytest.skip("hardlink creation is not available for this user/filesystem")

    with pytest.raises(RegularSourceError, match="not a regular output target"):
        smf.split_file(mega, out_dir)

    assert victim.read_text(encoding="utf-8") == "pre-existing content"


def test_split_file_fallback_refuses_to_replace_an_existing_regular_output(tmp_path, monkeypatch):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    blocked = _planned_outputs(mega, out_dir)[0]
    blocked.write_text("pre-existing content", encoding="utf-8")
    monkeypatch.setattr(smf, "_HAS_O_NOFOLLOW", False)
    monkeypatch.setattr(smf, "_HAS_O_NONBLOCK", False)

    with pytest.raises(RegularSourceError, match="retry with a new empty --output-dir"):
        smf.split_file(mega, out_dir)

    assert blocked.read_text(encoding="utf-8") == "pre-existing content"


def test_split_file_fallback_creates_new_regular_outputs(tmp_path, monkeypatch):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(smf, "_HAS_O_NOFOLLOW", False)
    monkeypatch.setattr(smf, "_HAS_O_NONBLOCK", False)

    written = smf.split_file(mega, out_dir)

    assert len(written) == 2
    assert all(path.is_file() for path in written)


def test_split_file_refuses_a_directory_output_target(tmp_path):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    blocked = _planned_outputs(mega, out_dir)[0]
    blocked.mkdir()

    with pytest.raises(RegularSourceError, match="not a regular output target"):
        smf.split_file(mega, out_dir)

    assert blocked.is_dir()
    assert list(blocked.iterdir()) == []


def test_main_renames_the_source_only_after_a_successful_split(tmp_path, monkeypatch, capsys):
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["split", "--file", str(mega), "--output-dir", str(out_dir)])

    smf.main()

    assert not mega.exists()
    assert (tmp_path / "mega.mega_backup").read_text(encoding="utf-8") == _session(
        "prompt"
    ) + "\n" + _session("prompt two")
    assert len(list(out_dir.iterdir())) == 2
    assert "renamed to mega.mega_backup" in capsys.readouterr().out


def test_main_repeated_apply_preserves_existing_outputs_and_source(tmp_path, monkeypatch, capsys):
    mega = _write_mega(tmp_path)
    original = mega.read_text(encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["split", "--file", str(mega), "--output-dir", str(out_dir)])

    smf.main()
    output_bytes = {path.name: path.read_bytes() for path in out_dir.iterdir()}
    mega.write_text(original, encoding="utf-8")
    capsys.readouterr()

    with pytest.raises(SystemExit) as raised:
        smf.main()

    assert raised.value.code == 1
    assert mega.read_text(encoding="utf-8") == original
    assert {path.name: path.read_bytes() for path in out_dir.iterdir()} == output_bytes
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert combined.count("retry with a new empty --output-dir") == 1
    assert "created 0 files; failed 1 of 1 mega-files" in captured.out


def test_main_missing_output_parent_preserves_source(tmp_path, monkeypatch, capsys):
    mega = _write_mega(tmp_path)
    original = mega.read_text(encoding="utf-8")
    out_dir = tmp_path / "missing-parent" / "out"
    monkeypatch.setattr(sys, "argv", ["split", "--file", str(mega), "--output-dir", str(out_dir)])

    with pytest.raises(SystemExit) as raised:
        smf.main()

    assert raised.value.code == 1
    assert mega.read_text(encoding="utf-8") == original
    assert not out_dir.parent.exists()
    assert not mega.with_suffix(".mega_backup").exists()
    captured = capsys.readouterr()
    assert "original left in place as mega.txt" in captured.out
    assert str(out_dir) in captured.err


def test_main_keeps_the_source_when_an_output_target_is_refused(tmp_path, monkeypatch, capsys):
    _require_fifo()
    mega = _write_mega(tmp_path)
    original = mega.read_text(encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    blocked = _planned_outputs(mega, out_dir)[0]
    os.mkfifo(blocked)
    monkeypatch.setattr(sys, "argv", ["split", "--file", str(mega), "--output-dir", str(out_dir)])

    with pytest.raises(SystemExit) as raised:
        smf.main()

    assert raised.value.code == 1
    assert mega.read_text(encoding="utf-8") == original
    assert not (tmp_path / "mega.mega_backup").exists()
    captured = capsys.readouterr()
    assert "not a regular output target" in captured.err
    assert "original left in place as mega.txt" in captured.out
    assert "created 0 files; failed 1 of 1 mega-files" in captured.out


def test_main_reports_partial_outputs_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    _require_fifo()
    mega = _write_mega(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    planned = _planned_outputs(mega, out_dir)
    os.mkfifo(planned[1])
    monkeypatch.setattr(sys, "argv", ["split", "--file", str(mega), "--output-dir", str(out_dir)])

    with pytest.raises(SystemExit) as raised:
        smf.main()

    assert raised.value.code == 1
    assert mega.exists()
    assert planned[0].is_file()
    assert not os.path.isfile(planned[1])
    captured = capsys.readouterr()
    assert "created 1 files; failed 1 of 1 mega-files" in captured.out


def test_load_known_people_requires_explicit_config(monkeypatch, tmp_path):
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", tmp_path / "missing.json")
    smf._KNOWN_NAMES_CACHE = None

    known_people = smf._load_known_people()
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", known_people)

    assert known_people == []
    assert smf._load_username_map() == {}
    assert smf.extract_people(["> Alice reviewed Ben's change with Jordan\n"]) == []


def test_load_known_people_from_list_config(monkeypatch, tmp_path):
    config_path = tmp_path / "known_names.json"
    config_path.write_text(json.dumps(["Alice", "Ben"]))
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", config_path)
    smf._KNOWN_NAMES_CACHE = None

    known_people = smf._load_known_people()
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", known_people)

    assert known_people == ["Alice", "Ben"]
    assert smf._load_username_map() == {}
    assert smf.extract_people(["> Alice reviewed the change with Ben\n"]) == ["Alice", "Ben"]


def test_load_known_people_from_dict_config(monkeypatch, tmp_path):
    config_path = tmp_path / "known_names.json"
    config_path.write_text(json.dumps({"names": ["Alice"], "username_map": {"jdoe": "John"}}))
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", config_path)
    smf._KNOWN_NAMES_CACHE = None

    assert smf._load_known_people() == ["Alice"]
    assert smf._load_username_map() == {"jdoe": "John"}


def test_extract_people_uses_username_map(monkeypatch, tmp_path):
    config_path = tmp_path / "known_names.json"
    config_path.write_text(json.dumps({"names": ["Alice"], "username_map": {"jdoe": "John"}}))
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", config_path)
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", ["Alice"])
    smf._KNOWN_NAMES_CACHE = None

    people = smf.extract_people(["Working in /Users/jdoe/project\n"])
    assert people == ["John"]


def test_extract_people_detects_names_from_content(monkeypatch):
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", ["Alice", "Ben"])
    people = smf.extract_people(["> Alice reviewed the change with Ben\n"])
    assert people == ["Alice", "Ben"]


def test_extract_people_treats_regex_metacharacters_as_literal(monkeypatch):
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", ["OBrien (Jr.)"])

    assert smf.extract_people(["> obrien (jr.) reviewed the change\n"]) == ["OBrien (Jr.)"]
    assert smf.extract_people(["> OBrien Jr reviewed the change\n"]) == []
    assert smf.extract_people(["> xOBrien (Jr.) and OBrien (Jr.)x reviewed it\n"]) == []


def test_extract_people_handles_invalid_raw_regex_with_nonword_edge(monkeypatch):
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", ["[Admin"])

    assert smf.extract_people(["> [admin joined the review\n"]) == ["[Admin"]
    assert smf.extract_people(["> x[Admin and [Adminx joined the review\n"]) == []
