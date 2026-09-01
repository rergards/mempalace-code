#!/usr/bin/env python3
"""Run the repository-pinned Gitleaks CLI with bounded, redacted output."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import unquote

CONFIG_PATH = ".gitleaks.toml"
IGNORE_PATH = ".gitleaksignore"
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*$")
_FINGERPRINT_RE = re.compile(
    r"^(?P<commit>[0-9a-f]{40}):(?P<path>[^:\r\n]+):"
    r"(?P<rule>[A-Za-z0-9][A-Za-z0-9._-]*):(?P<line>[1-9][0-9]*)$"
)
_METADATA_PREFIX = "# gitleaks-ignore-metadata: "
_GLOB_CHARS = frozenset("*?[]{}")
_SUPPRESSION_KEYS = frozenset({"allowlist", "allowlists", "disabledrules"})
_ZERO_SHA = "0" * 40
_MAX_FIXTURE_REPORT_BYTES = 1_000_000
_FIXTURE_EXPECTATIONS = {
    "pypi-token.txt": "pypi-upload-token",
    "github-token.txt": "github-pat",
    "aws-access-key.txt": "aws-access-token",
    "private-key.pem": "private-key",
    "entropy-assignment.txt": "mempalace-high-entropy-assignment",
}


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


def _load_unique_json_object(raw: str, line_number: int) -> dict[str, object]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate suppression metadata field at line {line_number}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed suppression metadata at line {line_number}") from exc
    except ValueError as exc:
        if str(exc).startswith("duplicate suppression metadata field"):
            raise
        raise ValueError(f"malformed suppression metadata at line {line_number}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"suppression metadata must be an object at line {line_number}")
    return value


def _validate_metadata(metadata: dict[str, object], line_number: int, today: date) -> None:
    allowed = {"owner", "rationale", "review_condition", "expiry"}
    unknown = sorted(set(metadata) - allowed)
    if unknown:
        raise ValueError(
            f"unknown suppression metadata field at line {line_number}: {', '.join(unknown)}"
        )
    for field in ("owner", "rationale"):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"suppression metadata requires nonempty {field} at line {line_number}"
            )

    review_condition = metadata.get("review_condition")
    expiry = metadata.get("expiry")
    if review_condition is not None and (
        not isinstance(review_condition, str) or not review_condition.strip()
    ):
        raise ValueError(
            f"suppression metadata review_condition must be nonempty at line {line_number}"
        )
    if expiry is not None:
        if not isinstance(expiry, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry):
            raise ValueError(
                f"suppression metadata expiry must be ISO YYYY-MM-DD at line {line_number}"
            )
        try:
            expiry_date = date.fromisoformat(expiry)
        except ValueError as exc:
            raise ValueError(
                f"suppression metadata expiry must be ISO YYYY-MM-DD at line {line_number}"
            ) from exc
        if expiry_date < today:
            raise ValueError(f"suppression metadata expired at line {line_number}")
    if review_condition is None and expiry is None:
        raise ValueError(
            "suppression metadata requires nonempty review_condition or nonexpired expiry "
            f"at line {line_number}"
        )


def _validate_config_suppressions(root: Path) -> None:
    config_path = root / CONFIG_PATH
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot parse {CONFIG_PATH}: {exc}") from exc

    for top_level_key, top_level_value in config.items():
        normalized_top_level = re.sub(r"[-_]", "", top_level_key).lower()
        if normalized_top_level == "extend" and isinstance(top_level_value, dict):
            for source_key in top_level_value:
                normalized_source = re.sub(r"[-_]", "", source_key).lower()
                if normalized_source not in {"path", "url"}:
                    continue
                raise ValueError(
                    f"unvalidated Gitleaks config import is forbidden: {top_level_key}.{source_key}"
                )

    def visit(value: object, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = re.sub(r"[-_]", "", key).lower()
                child_path = (*path, key)
                if normalized in _SUPPRESSION_KEYS:
                    raise ValueError(
                        f"suppression-capable Gitleaks config is forbidden: {'.'.join(child_path)}"
                    )
                if normalized == "disabled" and child is True:
                    raise ValueError(
                        f"Gitleaks rule disablement is forbidden: {'.'.join(child_path)}"
                    )
                if normalized == "enabled" and child is False:
                    raise ValueError(
                        f"Gitleaks rule disablement is forbidden: {'.'.join(child_path)}"
                    )
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, str(index)))

    visit(config)


def validate_baseline(root: Path, *, today: date | None = None) -> None:
    """Validate governed native exact fingerprints and forbid broader suppression."""
    _validate_config_suppressions(root)
    ignore_path = root / IGNORE_PATH
    try:
        lines = ignore_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read {IGNORE_PATH}: {exc}") from exc

    fingerprints: set[str] = set()
    pending_metadata: tuple[dict[str, object], int] | None = None
    current_date = today or datetime.now(UTC).date()
    for line_number, raw_line in enumerate(lines, start=1):
        if raw_line.startswith(_METADATA_PREFIX):
            if pending_metadata is not None:
                raise ValueError(f"orphan suppression metadata at line {pending_metadata[1]}")
            metadata = _load_unique_json_object(raw_line[len(_METADATA_PREFIX) :], line_number)
            _validate_metadata(metadata, line_number, current_date)
            pending_metadata = (metadata, line_number)
            continue

        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            if pending_metadata is not None:
                raise ValueError(f"orphan suppression metadata at line {pending_metadata[1]}")
            continue
        if pending_metadata is None:
            raise ValueError(
                f"fingerprint lacks immediately preceding metadata at line {line_number}"
            )
        if raw_line != stripped:
            raise ValueError(f"malformed exact fingerprint at line {line_number}")

        match = _FINGERPRINT_RE.fullmatch(stripped)
        if match is None:
            raise ValueError(f"malformed exact fingerprint at line {line_number}")
        path = match.group("path")
        path_parts = path.split("/")
        if (
            path.startswith("/")
            or "\\" in path
            or any(character in path for character in _GLOB_CHARS)
            or any(part in {"", ".", ".."} for part in path_parts)
        ):
            raise ValueError(f"fingerprint path must be exact at line {line_number}")
        if stripped in fingerprints:
            raise ValueError(f"duplicate fingerprint at line {line_number}")
        fingerprints.add(stripped)
        pending_metadata = None

    if pending_metadata is not None:
        raise ValueError(f"orphan suppression metadata at line {pending_metadata[1]}")


def _fixture_values() -> dict[str, str]:
    def urlsafe(size: int) -> str:
        return base64.urlsafe_b64encode(os.urandom(size)).decode("ascii").rstrip("=")

    def random_from(alphabet: str, size: int) -> str:
        return "".join(secrets.choice(alphabet) for _ in range(size))

    private_body = base64.b64encode(os.urandom(96)).decode("ascii")
    private_lines = [private_body[index : index + 64] for index in range(0, len(private_body), 64)]
    private_marker = "-----{} PRIVATE KEY-----"
    return {
        "pypi-token.txt": "pypi-" + "AgEIcHlwaS5vcmcC" + urlsafe(40),
        "github-token.txt": "ghp_"
        + random_from("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", 36),
        "aws-access-key.txt": (
            'aws_access_key_id = "'
            + "AKIA"
            + random_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", 16)
            + '"\n'
        ),
        "private-key.pem": "\n".join(
            [private_marker.format("BEGIN"), *private_lines, private_marker.format("END"), ""]
        ),
        "entropy-assignment.txt": 'api_key = "' + urlsafe(36) + '"\n',
    }


def _sarif_result_identity(result: object) -> tuple[str, str] | None:
    if not isinstance(result, dict) or not isinstance(result.get("ruleId"), str):
        return None
    try:
        uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(uri, str):
        return None
    return Path(unquote(uri)).name, result["ruleId"]


def _fixture_secret_values(values: dict[str, str]) -> list[str]:
    aws = re.search(r"AKIA[A-Z2-7]{16}", values["aws-access-key.txt"])
    entropy = re.search(r'api_key = "([^"]+)"', values["entropy-assignment.txt"])
    if aws is None or entropy is None:
        raise ValueError("generated fixture has an invalid secret shape")
    private_lines = values["private-key.pem"].splitlines()[1:-1]
    return [
        values["pypi-token.txt"].strip(),
        values["github-token.txt"].strip(),
        aws.group(0),
        *private_lines,
        entropy.group(1),
    ]


def fixture_smoke(root: Path) -> int:
    """Prove five detector classes with the installed real binary and disposable data."""
    validate_baseline(root)
    temp_base = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    if not temp_base.is_dir():
        raise ValueError("fixture temporary base does not exist")
    if temp_base == root.resolve() or root.resolve() in temp_base.parents:
        raise ValueError("system temporary directory must be outside the checkout")

    with tempfile.TemporaryDirectory(prefix="mempalace-gitleaks-fixture-", dir=temp_base) as tmpdir:
        fixture_root = Path(tmpdir)
        report_path = fixture_root / "report" / "fixture.sarif"
        worktree = fixture_root / "work"
        worktree.mkdir()
        values = _fixture_values()
        for filename, value in values.items():
            (worktree / filename).write_text(value, encoding="utf-8")

        setup_commands = [
            ["git", "init", "--quiet"],
            ["git", "config", "user.name", "Gitleaks Fixture"],
            ["git", "config", "user.email", "fixture.invalid@example.invalid"],
            ["git", "add", "."],
            ["git", "commit", "--quiet", "-m", "synthetic detector fixture"],
        ]
        for step, command in enumerate(setup_commands, start=1):
            result = _run(command, worktree)
            if result.returncode != 0:
                print(f"gitleaks-fixture: FAIL (fixture setup step {step})", file=sys.stderr)
                return 1

        report_path.parent.mkdir()
        command = [
            "gitleaks",
            "git",
            "--config",
            str((root / CONFIG_PATH).resolve()),
            "--gitleaks-ignore-path",
            str((root / IGNORE_PATH).resolve()),
            "--redact=100",
            "--no-banner",
            "--no-color",
            "--report-format",
            "sarif",
            "--report-path",
            str(report_path),
            ".",
        ]
        try:
            result = _run(command, worktree)
        except OSError as exc:
            print(f"gitleaks-fixture: FAIL (scanner unavailable: {exc})", file=sys.stderr)
            return 1
        if result.returncode != 1:
            print(f"gitleaks-fixture: FAIL (scanner exit {result.returncode})", file=sys.stderr)
            return 1
        try:
            if report_path.stat().st_size > _MAX_FIXTURE_REPORT_BYTES:
                raise ValueError("report exceeds size limit")
            report_text = report_path.read_text(encoding="utf-8")
            report = json.loads(report_text)
            results = report["runs"][0]["results"]
            if not isinstance(results, list):
                raise ValueError("results is not a list")
        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            print(f"gitleaks-fixture: FAIL (invalid bounded SARIF: {exc})", file=sys.stderr)
            return 1

        if any(secret in report_text for secret in _fixture_secret_values(values)):
            print(
                "gitleaks-fixture: FAIL (SARIF contains complete fixture material)", file=sys.stderr
            )
            return 1
        identities = {identity for item in results if (identity := _sarif_result_identity(item))}
        missing = [
            filename
            for filename, rule_id in _FIXTURE_EXPECTATIONS.items()
            if (filename, rule_id) not in identities
        ]
        if missing:
            print(
                "gitleaks-fixture: FAIL (missing classes: " + ", ".join(sorted(missing)) + ")",
                file=sys.stderr,
            )
            return 1

    print("gitleaks-fixture: OK (5 detector classes; redacted SARIF; temporary data removed)")
    return 0


def scan(
    root: Path,
    *,
    base_ref: str | None = None,
    head_ref: str | None = None,
    artifact_dir: Path,
) -> int:
    validate_baseline(root)
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
    subparsers.add_parser("validate-baseline")
    subparsers.add_parser("fixture-smoke")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    try:
        if args.mode == "validate-baseline":
            validate_baseline(root)
            print("gitleaks-baseline: OK (governed exact fingerprints; no broad suppressions)")
            return 0
        if args.mode == "fixture-smoke":
            return fixture_smoke(root)
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
