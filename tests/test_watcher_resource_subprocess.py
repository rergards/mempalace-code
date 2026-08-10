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
from pathlib import Path

import pytest

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
    return _directory_bytes(palace) + _directory_bytes(palace.parent / "backups")


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
            return len(list(proc_fd.iterdir()))
        except OSError:
            return None

    if shutil.which("lsof") is None:
        return None
    try:
        result = subprocess.run(
            ["lsof", "-Fn", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return sum(1 for line in result.stdout.splitlines() if line.startswith("f"))


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
    pytest.fail(f"watcher did not emit {needle!r} before timeout; output:\n{joined}")


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
            return
    _drain_output(lines, output)
    pytest.fail(f"watcher did not emit {needle!r} before timeout; output:\n{''.join(output)}")


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
    from mempalace_code.storage import DEFAULT_EMBED_MODEL

    try:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(
            DEFAULT_EMBED_MODEL,
            device="cpu",
            local_files_only=True,
            trust_remote_code=True,
        )
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
        assert init.returncode == 0, init.stdout + init.stderr

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
        assert process.stdout is not None
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
            rss_samples.append(_rss_bytes(process.pid))
            fd_samples.append(_fd_count(process.pid))
            disk_samples.append(_combined_bytes(palace))

        _stop_watcher(process, reader, lines, output)
        assert process.returncode == 0, "".join(output)
        summary = "".join(output)
        assert "10 re-mine cycle(s), 20 event(s)" in summary, summary

        peak_rss_growth = max(rss_samples) - rss_samples[0]
        final_rss_growth = rss_samples[-1] - rss_samples[0]
        assert peak_rss_growth <= 100 * MIB
        assert final_rss_growth <= 100 * MIB

        observable_fds = [sample for sample in fd_samples if sample is not None]
        if observable_fds:
            assert max(observable_fds) - observable_fds[0] <= 5

        backups = palace.parent / "backups"
        pre_optimize_count = len(list(backups.glob("pre_optimize_*.tar.gz")))
        assert pre_optimize_count <= 5
        late_disk_growth = disk_samples[10] - disk_samples[5]
        assert late_disk_growth <= 2 * MIB

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
