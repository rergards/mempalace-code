"""FastEmbed-native subprocess coverage for cached and recovery behavior."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mempalace_code.storage import (
    CANONICAL_EMBED_MODEL,
    CANONICAL_EMBED_MODEL_REVISION,
    canonical_fastembed_provenance,
)

ROOT = Path(__file__).resolve().parent.parent


def _write_sitecustomize(pkg_root: Path, event_log: Path) -> None:
    (pkg_root / "sitecustomize.py").write_text(
        textwrap.dedent(
            f"""\
            import json, socket as _socket
            _log = {str(event_log)!r}
            def _record(event):
                with open(_log, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event) + "\\n")
            def _blocked(address, *args, **kwargs):
                _record({{"type": "socket_attempt", "address": str(address)}})
                raise OSError("socket blocked by FastEmbed offline guard")
            _socket.create_connection = _blocked
            _OrigSocket = _socket.socket
            def _blocked_connect(self, address):
                return _blocked(address)
            _OrigSocket.connect = _blocked_connect
            """
        ),
        encoding="utf-8",
    )


def _write_fake_fastembed(pkg_root: Path, event_log: Path) -> None:
    package = pkg_root / "fastembed"
    package.mkdir()
    (package / "__init__.py").write_text(
        textwrap.dedent(
            f"""\
            import hashlib, json, math, os
            from pathlib import Path
            _log = {str(event_log)!r}
            _revision = {CANONICAL_EMBED_MODEL_REVISION!r}
            def _record(event):
                with open(_log, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event) + "\\n")
            def _download(cache):
                repository = cache / "models--qdrant--all-MiniLM-L6-v2-onnx"
                refs = repository / "refs"
                refs.mkdir(parents=True, exist_ok=True)
                (refs / "main").write_text(_revision, encoding="utf-8")
                snapshot = repository / "snapshots" / _revision
                snapshot.mkdir(parents=True, exist_ok=True)
                for name in ("config.json", "model.onnx", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"):
                    (snapshot / name).write_bytes(b"fixture")
                (snapshot / "tokenizer_config.json").write_text(json.dumps({{"max_length": 128, "model_max_length": 512}}), encoding="utf-8")
            class TextEmbedding:
                def __init__(self, **kwargs):
                    _record({{"type": "init", "local_files_only": bool(kwargs.get("local_files_only")), "providers": kwargs.get("providers")}})
                    if not kwargs.get("local_files_only"):
                        cache = Path(kwargs["cache_dir"])
                        if os.environ.get("MEMPALACE_FAKE_FASTEMBED_FAIL_DOWNLOAD") == "1":
                            cache.mkdir(parents=True, exist_ok=True)
                            (cache / "interrupted.bin").write_bytes(b"partial")
                            raise RuntimeError("fake interrupted download")
                        _download(cache)
                def embed(self, texts):
                    texts = list(texts)
                    _record({{"type": "embed", "count": len(texts)}})
                    for text in texts:
                        digest = hashlib.sha256(text.encode("utf-8")).digest()
                        vector = [0.0] * 384
                        for index, value in enumerate(digest):
                            vector[index] = (value - 127.5) / 127.5
                        norm = math.sqrt(sum(value * value for value in vector))
                        yield [value / norm for value in vector]
            """
        ),
        encoding="utf-8",
    )


def _write_owned_cache(hf_home: Path) -> Path:
    root = hf_home / "mempalace-fastembed" / "all-MiniLM-L6-v2-v1"
    repository = root / "models--qdrant--all-MiniLM-L6-v2-onnx"
    refs = repository / "refs"
    refs.mkdir(parents=True)
    (refs / "main").write_text(CANONICAL_EMBED_MODEL_REVISION, encoding="utf-8")
    snapshot = repository / "snapshots" / CANONICAL_EMBED_MODEL_REVISION
    snapshot.mkdir(parents=True)
    for name in (
        "config.json",
        "model.onnx",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ):
        (snapshot / name).write_bytes(b"fixture")
    (snapshot / "tokenizer_config.json").write_text(
        json.dumps({"max_length": 256, "model_max_length": 512}), encoding="utf-8"
    )
    (root / ".mempalace-model.json").write_text(
        json.dumps(canonical_fastembed_provenance()), encoding="utf-8"
    )
    return root


def _fake_runtime(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    event_log = tmp_path / "events.jsonl"
    packages = tmp_path / "packages"
    packages.mkdir()
    _write_sitecustomize(packages, event_log)
    _write_fake_fastembed(packages, event_log)
    hf_home = tmp_path / "hf-home"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(packages), str(ROOT)])
    env["HF_HOME"] = str(hf_home)
    env["MEMPALACE_VERSION_CHECK"] = "0"
    return env, hf_home, event_log


def _run(arguments: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments], capture_output=True, text=True, env=env, timeout=30
    )


def _events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _seed_palace(palace: Path, env: dict[str, str]) -> None:
    code = (
        "from mempalace_code.storage import LanceStore; import sys; "
        "store=LanceStore(sys.argv[1]); "
        "store.add(['d1'], ['offline cached search drawer'], "
        "[{'wing':'test','room':'general','source_file':'fixture.py'}])"
    )
    result = _run(["-c", code, str(palace)], env)
    assert result.returncode == 0, result.stderr


def test_cached_fetch_uses_fastembed_local_only_without_network(tmp_path: Path) -> None:
    env, hf_home, event_log = _fake_runtime(tmp_path)
    _write_owned_cache(hf_home)
    env.pop("HF_HUB_OFFLINE", None)
    env.pop("TRANSFORMERS_OFFLINE", None)

    result = _run(["-m", "mempalace_code.cli", "fetch-model"], env)

    assert result.returncode == 0, result.stderr
    assert "already available locally" in result.stdout
    events = _events(event_log)
    assert [event["local_files_only"] for event in events if event["type"] == "init"] == [True]
    assert not any(event["type"] == "socket_attempt" for event in events)


def test_cached_search_uses_fastembed_local_only_without_network(tmp_path: Path) -> None:
    env, hf_home, event_log = _fake_runtime(tmp_path)
    _write_owned_cache(hf_home)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    palace = tmp_path / "palace"
    _seed_palace(palace, env)
    before = len(_events(event_log))

    result = _run(
        ["-m", "mempalace_code.cli", "--palace", str(palace), "search", "cached search"],
        env,
    )

    assert result.returncode == 0, result.stderr
    events = _events(event_log)[before:]
    assert any(event["type"] == "embed" for event in events)
    assert all(event.get("local_files_only") is True for event in events if event["type"] == "init")
    assert not any(event["type"] == "socket_attempt" for event in events)


def test_corrupt_offline_cache_fails_before_fastembed_or_online_retry(tmp_path: Path) -> None:
    env, hf_home, event_log = _fake_runtime(tmp_path)
    root = _write_owned_cache(hf_home)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    palace = tmp_path / "palace"
    _seed_palace(palace, env)
    (root / ".mempalace-model.json").unlink()
    before = len(_events(event_log))

    result = _run(["-m", "mempalace_code.cli", "--palace", str(palace), "search", "offline"], env)

    assert result.returncode != 0
    assert "not owned" in result.stderr
    events = _events(event_log)[before:]
    assert not any(event["type"] in {"init", "socket_attempt"} for event in events)
    assert root.is_dir()


def test_force_partial_failure_and_retry_preserve_each_interruption(tmp_path: Path) -> None:
    env, hf_home, event_log = _fake_runtime(tmp_path)
    root = hf_home / "mempalace-fastembed" / "all-MiniLM-L6-v2-v1"
    root.mkdir(parents=True)
    (root / "original.bin").write_bytes(b"original")
    env["MEMPALACE_FAKE_FASTEMBED_FAIL_DOWNLOAD"] = "1"

    failed = _run(["-m", "mempalace_code.cli", "fetch-model", "--force"], env)

    assert failed.returncode == 1
    assert "Preserved partial cache at:" in failed.stdout
    assert "Retry exactly: `mempalace-code fetch-model --model all-MiniLM-L6-v2`" in failed.stderr
    env.pop("MEMPALACE_FAKE_FASTEMBED_FAIL_DOWNLOAD")
    recovered = _run(["-m", "mempalace_code.cli", "fetch-model"], env)
    assert recovered.returncode == 0, recovered.stderr
    assert "Preserved partial cache at:" in recovered.stdout
    quarantines = sorted(root.parent.glob(f"{root.name}.quarantine-*"))
    assert len(quarantines) == 2
    assert any((path / "original.bin").exists() for path in quarantines)
    assert any((path / "interrupted.bin").exists() for path in quarantines)
    cached = _run(["-m", "mempalace_code.cli", "fetch-model"], env)
    assert cached.returncode == 0
    assert "already available locally" in cached.stdout
    assert not any(event["type"] == "socket_attempt" for event in _events(event_log))


def test_real_fastembed_cached_search_subprocess_guard(tmp_path: Path) -> None:
    """Direct real-runtime evidence when the qualification cache is supplied."""
    shared = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if not shared:
        pytest.skip("MEMPALACE_TEST_HF_HOME is required for real FastEmbed qualification")
    source = Path(shared) / "mempalace-fastembed" / "all-MiniLM-L6-v2-v1"
    if not source.is_dir():
        pytest.fail("MEMPALACE_TEST_HF_HOME lacks the canonical FastEmbed cache")
    event_log = tmp_path / "events.jsonl"
    guard = tmp_path / "guard"
    guard.mkdir()
    _write_sitecustomize(guard, event_log)
    hf_home = tmp_path / "hf-home"
    shutil.copytree(source, hf_home / "mempalace-fastembed" / source.name, symlinks=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(guard), str(ROOT)])
    env["HF_HOME"] = str(hf_home)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["MEMPALACE_VERSION_CHECK"] = "0"
    palace = tmp_path / "real-palace"
    _seed_palace(palace, env)

    result = _run(["-m", "mempalace_code.cli", "--palace", str(palace), "search", "offline"], env)

    assert result.returncode == 0, result.stderr
    assert not any(event["type"] == "socket_attempt" for event in _events(event_log))
    assert CANONICAL_EMBED_MODEL == "sentence-transformers/all-MiniLM-L6-v2"
