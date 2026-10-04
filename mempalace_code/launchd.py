"""launchd.py — Per-path launchd job labels, logs, and environment shared by schedules."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# Settings a scheduled job must share with the shell that rendered it: model location and
# offline policy, plus every documented MEMPALACE_* floor, retention, and path setting.
_DAEMON_ENV_NAMES = frozenset(
    {"HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "SENTENCE_TRANSFORMERS_HOME"}
)
_DAEMON_ENV_PREFIXES = ("MEMPALACE_", "MEMPAL_")
_SECRET_ENV_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|CREDENTIAL|API_?KEY")


def launchd_label(prefix: str, path: str | Path) -> str:
    """Return ``<prefix>.<dir-name-slug>-<hash>`` for one directory.

    The hash is the first 8 hex digits of the SHA-256 of the resolved path, so each
    directory gets its own job: scheduling a second one never replaces the first, and
    re-rendering the same one replaces only its own job.
    """
    root = Path(path).expanduser().resolve()
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-")[:40].strip("-")
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}.{slug}-{digest}" if slug else f"{prefix}.{digest}"


def launchd_log_path(label: str) -> Path:
    """Return the per-user, per-job log (never a shared world-writable path)."""
    return Path.home() / "Library" / "Logs" / f"{label}.log"


def daemon_environment(environ: Mapping[str, str]) -> dict:
    """Select the settings a scheduled job inherits from the rendering shell.

    The job always runs offline unless the operator set ``HF_HUB_OFFLINE``
    explicitly: a background job must never download a model without consent, so a
    missing model fails with the ``fetch-model`` recovery instead.
    """
    selected = {}
    for name, value in environ.items():
        if name not in _DAEMON_ENV_NAMES and not name.startswith(_DAEMON_ENV_PREFIXES):
            continue
        if _SECRET_ENV_NAME.search(name) or any(ord(ch) < 32 for ch in value):
            continue
        selected[name] = value
    selected.setdefault("HF_HUB_OFFLINE", "1")
    return dict(sorted(selected.items()))
