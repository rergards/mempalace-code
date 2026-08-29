#!/usr/bin/env python3
"""Run the repository-pinned Gitleaks CLI with bounded, redacted output."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG_PATH = ".gitleaks.toml"
IGNORE_PATH = ".gitleaksignore"
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*$")
_ZERO_SHA = "0" * 40


def _run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=root, capture_output=True, text=True)


def _require_commit(root: Path, ref: str, role: str) -> None:
    if not ref or ref == _ZERO_SHA or ref.startswith("-") or not _REF_RE.fullmatch(ref):
        raise ValueError(f"unsafe {role} ref: {ref!r}")
    result = _run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], root)
    if result.returncode != 0:
        raise ValueError(f"{role} ref is not a reachable commit: {ref!r}")


def _require_full_history(root: Path) -> None:
    result = _run(["git", "rev-parse", "--is-shallow-repository"], root)
    if result.returncode != 0 or result.stdout.strip() != "false":
        raise ValueError("full-history scan requires a non-shallow checkout")


def scan(
    root: Path,
    *,
    base_ref: str | None = None,
    head_ref: str | None = None,
    artifact_dir: Path,
) -> int:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "gitleaks",
        "git",
        "--config",
        CONFIG_PATH,
        "--gitleaks-ignore-path",
        IGNORE_PATH,
        "--redact=100",
        "--no-banner",
        "--no-color",
        "--report-format",
        "sarif",
        "--report-path",
        str(artifact_dir / "gitleaks.sarif"),
    ]
    mode = "full-history"
    if base_ref is not None or head_ref is not None:
        if base_ref is None or head_ref is None:
            raise ValueError("changed-range requires both --base-ref and --head-ref")
        _require_commit(root, base_ref, "base")
        _require_commit(root, head_ref, "head")
        command.extend(["--log-opts", f"{base_ref}..{head_ref}"])
        mode = "changed-range"
    else:
        _require_full_history(root)
    command.append(".")

    try:
        result = _run(command, root)
    except OSError as exc:
        print(f"gitleaks-scan: FAIL ({mode}; scanner unavailable: {exc})", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(
            f"gitleaks-scan: FAIL ({mode}; scanner exit {result.returncode}; "
            f"report {artifact_dir / 'gitleaks.sarif'})",
            file=sys.stderr,
        )
        return 1
    print(f"gitleaks-scan: OK ({mode})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    changed = subparsers.add_parser("changed-range")
    changed.add_argument("--base-ref", required=True)
    changed.add_argument("--head-ref", required=True)
    changed.add_argument("--artifact-dir", type=Path)
    full = subparsers.add_parser("full-history")
    full.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    try:
        if args.artifact_dir is not None:
            return scan(
                root,
                base_ref=getattr(args, "base_ref", None),
                head_ref=getattr(args, "head_ref", None),
                artifact_dir=args.artifact_dir,
            )
        with tempfile.TemporaryDirectory(prefix="mempalace-gitleaks-") as tmpdir:
            return scan(
                root,
                base_ref=getattr(args, "base_ref", None),
                head_ref=getattr(args, "head_ref", None),
                artifact_dir=Path(tmpdir),
            )
    except ValueError as exc:
        print(f"gitleaks-scan: FAIL ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
