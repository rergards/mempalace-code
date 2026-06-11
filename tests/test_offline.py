"""
Integration test: offline operation after fetch_model.

This file now contains two sections:

  1. Non-network subprocess guards (run under the default test selection) — prove that
     cached fetch-model and search paths use only local model resolution, make no
     HuggingFace metadata or socket calls, and emit no token-warning output in a real
     subprocess spawned with fake sentence_transformers and socket-blocking modules.

  2. Network-required integration tests (marked @pytest.mark.needs_network) — download
     the real ~80 MB HuggingFace model.  CI skips these by default:

         pytest -m "not needs_network"

     Run explicitly when a connection is available:

         pytest tests/test_offline.py -v
"""

import json
import os
import subprocess
import sys
import textwrap
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


# ── Subprocess guard helpers ───────────────────────────────────────────────────
#
# The four tests below spawn a real `python -m mempalace_code.cli` subprocess and
# inject fake sentence_transformers/huggingface_hub packages plus a sitecustomize
# socket blocker via PYTHONPATH.  A JSONL event log records every constructor,
# encode, online_load, socket_attempt, and metadata_attempt event so the parent
# process can assert the offline contract was honoured.
#
# Precise token-warning markers written by the fake SentenceTransformer constructor
# — production _quiet_hf_model_output() must redirect fd 1/2 to /dev/null during
# construction so these never reach captured output.
_HF_TOKEN_WARNING_MARKERS = [
    "The token has not been saved",
    "hf.co/settings/tokens",
    "Token is valid",
]


def _write_sitecustomize(pkg_root: Path, event_log: Path) -> None:
    """Socket blocker loaded before any app import via PYTHONPATH prepend."""
    (pkg_root / "sitecustomize.py").write_text(
        textwrap.dedent(
            f"""\
            import json, os, socket as _socket

            _log = {str(event_log)!r}

            def _record(event):
                with open(_log, "a") as _f:
                    _f.write(json.dumps(event) + "\\n")

            _orig_create_connection = _socket.create_connection
            def _fake_create_connection(address, *args, **kwargs):
                _record({{"type": "socket_attempt", "via": "create_connection", "address": str(address)}})
                raise OSError("socket blocked by subprocess guard")
            _socket.create_connection = _fake_create_connection

            _OrigSocket = _socket.socket
            _orig_connect = _OrigSocket.connect
            def _fake_connect(self, address):
                _record({{"type": "socket_attempt", "via": "socket.connect", "address": str(address)}})
                raise OSError("socket blocked by subprocess guard")
            _OrigSocket.connect = _fake_connect
            """
        )
    )


def _write_fake_sentence_transformers(pkg_root: Path, event_log: Path) -> None:
    st_dir = pkg_root / "sentence_transformers"
    st_dir.mkdir()
    (st_dir / "__init__.py").write_text(
        textwrap.dedent(
            f"""\
            import json, os, sys

            _log = {str(event_log)!r}

            def _record(event):
                with open(_log, "a") as _f:
                    _f.write(json.dumps(event) + "\\n")

            class SentenceTransformer:
                def __init__(self, model_name_or_path, **kwargs):
                    local_files_only = bool(kwargs.get("local_files_only", False))
                    event_type = "constructor" if local_files_only else "online_load"
                    _record({{"type": event_type, "model_name": model_name_or_path, "local_files_only": local_files_only}})

                    # Write token-warning text that real HF hub emits during construction.
                    # Production _quiet_hf_model_output() redirects fd 1/2 to /dev/null
                    # while the constructor runs, so these must be flushed there — not to
                    # the captured pipe.
                    sys.stdout.write("The token has not been saved to the git credentials helper.\\n")
                    sys.stderr.write(
                        "Token is valid (permission: read). "
                        "Your token has been saved to hf.co/settings/tokens.\\n"
                    )
                    sys.stdout.flush()
                    sys.stderr.flush()

                    if not local_files_only and os.environ.get("MEMPALACE_FAKE_ST_DISALLOW_ONLINE", "0") == "1":
                        raise RuntimeError("online ST load disallowed by subprocess guard")

                    if local_files_only and os.environ.get("MEMPALACE_FAKE_ST_FAIL_LOCAL", "0") == "1":
                        raise OSError("cached model incomplete (fake local-load failure)")

                    self._ndims = 384

                def encode(self, texts, **kwargs):
                    _record({{"type": "encode", "count": len(texts)}})
                    import numpy as _np
                    return _np.zeros((len(texts), self._ndims), dtype=_np.float32)
            """
        )
    )


def _write_fake_huggingface_hub(pkg_root: Path, event_log: Path) -> None:
    hf_dir = pkg_root / "huggingface_hub"
    hf_dir.mkdir()
    (hf_dir / "__init__.py").write_text(
        textwrap.dedent(
            f"""\
            import json, os

            _log = {str(event_log)!r}

            def _record(event):
                with open(_log, "a") as _f:
                    _f.write(json.dumps(event) + "\\n")

            def model_info(*args, **kwargs):
                _record({{"type": "metadata_attempt", "fn": "model_info"}})
                raise OSError("huggingface_hub blocked by subprocess guard")

            def hf_hub_download(*args, **kwargs):
                _record({{"type": "metadata_attempt", "fn": "hf_hub_download"}})
                raise OSError("huggingface_hub blocked by subprocess guard")

            def snapshot_download(*args, **kwargs):
                _record({{"type": "metadata_attempt", "fn": "snapshot_download"}})
                raise OSError("huggingface_hub blocked by subprocess guard")

            def login(*args, **kwargs):
                pass

            def whoami(*args, **kwargs):
                return {{}}
            """
        )
    )


def _build_fake_pkg_root(tmp_path: Path, event_log: Path) -> Path:
    root = tmp_path / "fake_pkgs"
    root.mkdir()
    _write_sitecustomize(root, event_log)
    _write_fake_sentence_transformers(root, event_log)
    _write_fake_huggingface_hub(root, event_log)
    return root


def _make_subprocess_env(
    fake_pkg_root: Path,
    event_log: Path,
    *,
    hf_home: Path | None = None,
    extra: dict[str, str] | None = None,
    unset: list[str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(fake_pkg_root) + (":" + existing_pp if existing_pp else "")
    env["MEMPALACE_TEST_EVENT_LOG"] = str(event_log)
    if hf_home is not None:
        env["HF_HOME"] = str(hf_home)
    if extra:
        env.update(extra)
    for var in unset or []:
        env.pop(var, None)
    return env


def _run_subprocess(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _read_events(event_log: Path) -> list[dict]:  # type: ignore[type-arg]
    if not event_log.exists():
        return []
    events = []
    for line in event_log.read_text().splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _seed_palace(palace_path: Path) -> None:
    from mempalace_code.storage import open_store

    store = open_store(str(palace_path), create=True)
    store.add(
        ids=["offline_guard_d1"],
        documents=["embedding model local search test drawer for offline guard"],
        metadatas=[
            {
                "wing": "test",
                "room": "general",
                "source_file": "guard.py",
                "chunk_index": 0,
                "added_by": "test",
                "filed_at": "2026-01-01T00:00:00",
            }
        ],
    )


# ── AC-1: Cached fetch-model uses only local resolution ───────────────────────

def test_cached_fetch_model_subprocess_guard(tmp_path: Path) -> None:
    """Cached fetch-model: local-only model load, no network calls, no HF token warnings."""
    event_log = tmp_path / "events.jsonl"
    hf_home = tmp_path / "hf_home"
    hf_home.mkdir()

    # Represent a post-setup cache: snapshots dir exists so _model_cache_dir reports it
    model_cache = (
        hf_home / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / "fake"
    )
    model_cache.mkdir(parents=True)

    fake_pkg_root = _build_fake_pkg_root(tmp_path, event_log)
    env = _make_subprocess_env(
        fake_pkg_root,
        event_log,
        hf_home=hf_home,
        extra={"MEMPALACE_FAKE_ST_DISALLOW_ONLINE": "1"},
        # Unset offline env flags to prove the cached path is chosen by code logic,
        # not by environment coercion.
        unset=["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"],
    )

    result = _run_subprocess(
        [sys.executable, "-m", "mempalace_code.cli", "fetch-model"],
        env,
    )

    events = _read_events(event_log)
    event_types = [e["type"] for e in events]

    assert result.returncode == 0, (
        f"fetch-model exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    constructor_events = [e for e in events if e["type"] == "constructor"]
    assert len(constructor_events) == 1, f"Expected 1 constructor event; got {event_types}"
    assert constructor_events[0]["local_files_only"] is True, (
        f"Constructor called without local_files_only=True: {constructor_events[0]}"
    )
    assert "online_load" not in event_types, f"Unexpected online load: {events}"
    assert "socket_attempt" not in event_types, f"Unexpected socket attempt: {events}"
    assert "metadata_attempt" not in event_types, f"Unexpected metadata attempt: {events}"

    combined = result.stdout + result.stderr
    for marker in _HF_TOKEN_WARNING_MARKERS:
        assert marker not in combined, (
            f"HF warning marker {marker!r} leaked to captured output.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ── AC-2: Cached search initialises query embedder locally ────────────────────

def test_cached_search_subprocess_guard(tmp_path: Path) -> None:
    """Cached search: local embedder init, encode called, no network, no HF token warnings."""
    palace_path = tmp_path / "palace"
    palace_path.mkdir()
    _seed_palace(palace_path)

    event_log = tmp_path / "events.jsonl"
    fake_pkg_root = _build_fake_pkg_root(tmp_path, event_log)
    env = _make_subprocess_env(
        fake_pkg_root,
        event_log,
        extra={
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MEMPALACE_FAKE_ST_DISALLOW_ONLINE": "1",
        },
    )

    result = _run_subprocess(
        [
            sys.executable,
            "-m",
            "mempalace_code.cli",
            "--palace",
            str(palace_path),
            "search",
            "embedding model",
        ],
        env,
    )

    events = _read_events(event_log)
    event_types = [e["type"] for e in events]

    assert result.returncode == 0, (
        f"search exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    constructor_events = [e for e in events if e["type"] == "constructor"]
    assert len(constructor_events) == 1, f"Expected 1 constructor event; got {event_types}"
    assert constructor_events[0]["local_files_only"] is True, (
        f"Constructor called without local_files_only=True: {constructor_events[0]}"
    )
    assert "encode" in event_types, f"No encode event — query embedding did not run: {event_types}"
    assert "online_load" not in event_types, f"Unexpected online load: {events}"
    assert "socket_attempt" not in event_types, f"Unexpected socket attempt: {events}"
    assert "metadata_attempt" not in event_types, f"Unexpected metadata attempt: {events}"

    combined = result.stdout + result.stderr
    for marker in _HF_TOKEN_WARNING_MARKERS:
        assert marker not in combined, (
            f"HF warning marker {marker!r} leaked to captured output.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ── AC-3: Offline local-cache failure does not fall through to online retry ───

def test_offline_search_subprocess_no_online_retry_on_local_cache_error(tmp_path: Path) -> None:
    """Offline search with broken local cache: fails without retrying online."""
    palace_path = tmp_path / "palace"
    palace_path.mkdir()
    _seed_palace(palace_path)  # table must exist so _SentenceTransformerEmbedder is invoked

    event_log = tmp_path / "events.jsonl"
    fake_pkg_root = _build_fake_pkg_root(tmp_path, event_log)
    env = _make_subprocess_env(
        fake_pkg_root,
        event_log,
        extra={
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MEMPALACE_FAKE_ST_FAIL_LOCAL": "1",
        },
    )

    result = _run_subprocess(
        [
            sys.executable,
            "-m",
            "mempalace_code.cli",
            "--palace",
            str(palace_path),
            "search",
            "test",
        ],
        env,
    )

    events = _read_events(event_log)
    event_types = [e["type"] for e in events]

    assert result.returncode != 0, (
        f"Expected non-zero exit (local cache failure should not retry); got 0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "online_load" not in event_types, (
        f"online_load event recorded — no-retry contract violated: {events}"
    )
    assert "socket_attempt" not in event_types, f"Unexpected socket attempt: {events}"
    assert "metadata_attempt" not in event_types, f"Unexpected metadata attempt: {events}"


# ── AC-4: --force setup boundary remains online-capable; warnings still quiet ─

def test_force_fetch_model_subprocess_setup_boundary_allows_online_load(tmp_path: Path) -> None:
    """fetch-model --force: one online-capable load allowed; HF warnings still suppressed."""
    event_log = tmp_path / "events.jsonl"
    hf_home = tmp_path / "hf_home"
    hf_home.mkdir()

    fake_pkg_root = _build_fake_pkg_root(tmp_path, event_log)
    env = _make_subprocess_env(
        fake_pkg_root,
        event_log,
        hf_home=hf_home,
        # Unset offline flags so --force path is unambiguously online-capable.
        unset=["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"],
    )

    result = _run_subprocess(
        [sys.executable, "-m", "mempalace_code.cli", "fetch-model", "--force"],
        env,
    )

    events = _read_events(event_log)
    event_types = [e["type"] for e in events]

    assert result.returncode == 0, (
        f"fetch-model --force exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    online_events = [e for e in events if e["type"] == "online_load"]
    assert len(online_events) == 1, (
        f"Expected exactly 1 online_load event for --force; got {event_types}"
    )
    assert "socket_attempt" not in event_types, f"Unexpected socket attempt: {events}"

    combined = result.stdout + result.stderr
    for marker in _HF_TOKEN_WARNING_MARKERS:
        assert marker not in combined, (
            f"HF warning marker {marker!r} leaked in --force path.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
