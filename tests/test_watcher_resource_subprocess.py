"""Real watcher resource regression coverage for AC-5."""

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path

import pytest

from mempalace_code.backup import managed_backups_dir

MIB = 1024 * 1024
READY_TIMEOUT_SECONDS = 180
CYCLE_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 30
FIRST_CYCLE_ATTEMPT_SECONDS = 6


def _directory_bytes(path: Path) -> int:
    return (
        sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
        if path.exists()
        else 0
    )


def _combined_bytes(palace: Path) -> int:
    return _directory_bytes(palace) + _directory_bytes(Path(managed_backups_dir(str(palace))))


def _rss_bytes(pid: int) -> int:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"required OS RSS metric unavailable: {exc}")
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        pytest.skip("required OS RSS metric unavailable from ps")
    return int(result.stdout.strip()) * 1024


def _fd_count(pid: int) -> int | None:
    proc_fd = Path(f"/proc/{pid}/fd")
    if proc_fd.is_dir():
        try:
            return len(list(proc_fd.iterdir())) or None
        except OSError:
            return None

    if shutil.which("lsof") is None:
        return None
    try:
        result = subprocess.run(
            ["lsof", "-Ff", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    # lsof also emits cwd, txt, and mem records. Only numeric f fields are open
    # descriptors, matching the /proc/<pid>/fd metric used on Linux.
    fields = result.stdout.splitlines()
    if f"p{pid}" not in fields:
        return None
    return sum(1 for line in fields if line.startswith("f") and line[1:].isdigit()) or None


def _fd_growth(samples: list[int | None]) -> int | None:
    observed = [sample for sample in samples if sample is not None]
    if len(observed) != len(samples) or len(observed) < 2:
        return None
    return max(observed) - observed[0]


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected"),
    [
        ("p123\nfcwd\nftxt\nftxt\nfmem\nf0\nf1\nf2\nf17\n", 0, 4),
        ("p123\nfcwd\nftxt\n", 0, None),
        ("", 0, None),
        ("p999\nf0\nf1\nf2\n", 0, None),
        ("p123\nf0\nf1\nf2\n", 1, None),
    ],
)
def test_fd_count_uses_numeric_lsof_descriptors(monkeypatch, stdout, returncode, expected):
    monkeypatch.setattr(Path, "is_dir", lambda self: False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/sbin/lsof")

    def run(args, **kwargs):
        assert args == ["lsof", "-Ff", "-p", "123"]
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert _fd_count(123) == expected


@pytest.mark.parametrize(
    ("samples", "expected"),
    [([], None), ([14], None), ([14, None, 20], None), ([14, 19, 14], 5), ([14, 20, 14], 6)],
)
def test_fd_growth_requires_complete_measurements(samples, expected):
    assert _fd_growth(samples) == expected


def test_fd_count_observes_real_open_files(tmp_path):
    before = _fd_count(os.getpid())
    if before is None:
        pytest.skip("required OS descriptor metric unavailable")
    with ExitStack() as stack:
        for index in range(3):
            stack.enter_context((tmp_path / f"descriptor-{index}").open("w"))
        during = _fd_count(os.getpid())
        assert during is not None
        assert during >= before + 3
    after = _fd_count(os.getpid())
    assert after is not None
    assert after <= during - 3


def _read_output(stream, lines: queue.Queue[str]) -> None:
    for line in iter(stream.readline, ""):
        lines.put(line)
    stream.close()


def _wait_for_output(
    lines: queue.Queue[str], output: list[str], needle: str, timeout_seconds: int
) -> None:
    if _poll_for_output(lines, output, needle, timeout_seconds):
        return
    _drain_output(lines, output)
    joined = "".join(output)
    pytest.fail(
        f"mempalace_reason=watcher_output_timeout\n"
        f"watcher did not emit {needle!r} before timeout; output:\n{joined}"
    )


def _poll_for_output(
    lines: queue.Queue[str], output: list[str], needle: str, timeout_seconds: float
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=min(1, deadline - time.monotonic()))
        except queue.Empty:
            continue
        output.append(line)
        if needle in line:
            return True
    return False


def _drain_output(lines: queue.Queue[str], output: list[str]) -> None:
    while True:
        try:
            output.append(lines.get_nowait())
        except queue.Empty:
            return


def _rewrite_sources(sources: list[Path], cycle: str) -> None:
    for index, source in enumerate(sources, start=1):
        source.write_text(
            f'''def value_{index}():
    """Watcher resource fixture for cycle {cycle}; this source intentionally has
    enough meaningful content to create one changed mined drawer per rewrite."""
    return {cycle!r}
''',
            encoding="utf-8",
        )


def _wait_for_first_cycle(
    lines: queue.Queue[str], output: list[str], project_name: str, sources: list[Path]
) -> None:
    needle = f"[{project_name}: 2 change(s)]"
    deadline = time.monotonic() + CYCLE_TIMEOUT_SECONDS
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        _rewrite_sources(sources, f"ready-{attempt}")
        if _poll_for_output(
            lines,
            output,
            needle,
            min(FIRST_CYCLE_ATTEMPT_SECONDS, deadline - time.monotonic()),
        ):
            _wait_for_output(lines, output, " done (", CYCLE_TIMEOUT_SECONDS)
            return
    _drain_output(lines, output)
    pytest.fail(
        "mempalace_reason=watcher_first_cycle_timeout\n"
        f"watcher did not emit {needle!r} before timeout; output:\n{''.join(output)}"
    )


def _stop_watcher(
    process: subprocess.Popen[str],
    reader: threading.Thread | None,
    lines: queue.Queue[str],
    output: list[str],
) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if reader is not None:
        reader.join(timeout=5)
    _drain_output(lines, output)


def _require_cached_default_model() -> None:
    from mempalace_code.storage import _FastEmbedder, canonical_fastembed_cache_owned

    try:
        assert canonical_fastembed_cache_owned()
        vector = _FastEmbedder(local_files_only=True).compute_source_embeddings(["watcher"])[0]
        assert len(vector) == 384
    except Exception as exc:
        pytest.skip(f"required watcher support unavailable: cached default embedding model: {exc}")


@pytest.mark.slow
def test_watcher_resource_bounds_in_real_subprocess(monkeypatch):
    """Ten real save batches retain bounded process, disk, and backup resources."""
    try:
        import watchfiles  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"required watcher support unavailable: {exc}")
    hf_home = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if not hf_home:
        pytest.skip("required watcher support unavailable: MEMPALACE_TEST_HF_HOME is unset")
    monkeypatch.setenv("HF_HOME", hf_home)
    _require_cached_default_model()

    temp_dir = tempfile.TemporaryDirectory(prefix="mempalace-watcher-resource-")
    process: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None
    lines: queue.Queue[str] | None = None
    output: list[str] = []
    try:
        root = Path(temp_dir.name)
        home = root / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        palace = root / "palace"
        project = root / "project"
        project.mkdir()
        sources = [project / "one.py", project / "two.py"]
        _rewrite_sources(sources, "initial")

        env = os.environ.copy()
        env["HF_HOME"] = hf_home
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        init = subprocess.run(
            [sys.executable, "-m", "mempalace_code", "init", str(project), "--skip-model-download"],
            capture_output=True,
            check=False,
            env=env,
            text=True,
            timeout=30,
        )
        assert init.returncode == 0, (
            "mempalace_reason=watcher_init_failed\n" + init.stdout + init.stderr
        )

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mempalace_code",
                "--palace",
                str(palace),
                "watch",
                str(project),
                "--on-save",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env,
            text=True,
        )
        assert process.stdout is not None, "mempalace_reason=watcher_stdout_unavailable"
        lines = queue.Queue()
        reader = threading.Thread(target=_read_output, args=(process.stdout, lines), daemon=True)
        reader.start()
        _wait_for_output(lines, output, "state=watch-ready", READY_TIMEOUT_SECONDS)

        rss_samples = [_rss_bytes(process.pid)]
        fd_samples = [_fd_count(process.pid)]
        disk_samples = [_combined_bytes(palace)]
        _wait_for_first_cycle(lines, output, project.name, sources)
        rss_samples.append(_rss_bytes(process.pid))
        fd_samples.append(_fd_count(process.pid))
        disk_samples.append(_combined_bytes(palace))
        for cycle in range(2, 11):
            _rewrite_sources(sources, f"cycle-{cycle}")
            _wait_for_output(lines, output, f"[{project.name}: 2 change(s)]", CYCLE_TIMEOUT_SECONDS)
            # The mine summary precedes optimization. Observe the complete batch,
            # after its transient archive and storage descriptors have closed.
            _wait_for_output(lines, output, " done (", CYCLE_TIMEOUT_SECONDS)
            rss_samples.append(_rss_bytes(process.pid))
            fd_samples.append(_fd_count(process.pid))
            disk_samples.append(_combined_bytes(palace))

        _stop_watcher(process, reader, lines, output)
        assert process.returncode == 0, "mempalace_reason=watcher_exit_nonzero\n" + "".join(output)
        summary = "".join(output)
        assert "10 re-mine cycle(s), 20 event(s)" in summary, (
            "mempalace_reason=watcher_summary_mismatch\n" + summary
        )

        peak_rss_growth = max(rss_samples) - rss_samples[0]
        final_rss_growth = rss_samples[-1] - rss_samples[0]
        assert peak_rss_growth <= 100 * MIB, "mempalace_reason=watcher_rss_peak"
        assert final_rss_growth <= 100 * MIB, "mempalace_reason=watcher_rss_final"

        fd_growth = _fd_growth(fd_samples)
        assert fd_growth is not None, "mempalace_reason=watcher_fd_measurement_unavailable"
        assert fd_growth <= 5, "mempalace_reason=watcher_fd_growth"

        backups = Path(managed_backups_dir(str(palace)))
        pre_optimize_count = len(list(backups.glob("pre_optimize_*.tar.gz")))
        assert pre_optimize_count > 0, "mempalace_reason=watcher_backup_missing"
        assert pre_optimize_count <= 5, "mempalace_reason=watcher_backup_count"
        late_disk_growth = disk_samples[10] - disk_samples[5]
        assert late_disk_growth <= 2 * MIB, "mempalace_reason=watcher_disk_growth"

        print(
            json.dumps(
                {
                    "rss_bytes": rss_samples,
                    "fd_counts": fd_samples,
                    "combined_disk_bytes": disk_samples,
                    "pre_optimize_archives": pre_optimize_count,
                    "sigint_exit": process.returncode,
                    "late_disk_growth_bytes": late_disk_growth,
                },
                sort_keys=True,
            )
        )
    finally:
        if process is not None and lines is not None:
            _stop_watcher(process, reader, lines, output)
        temp_dir.cleanup()
