#!/usr/bin/env python3
"""Gitleaks gate wrapper with redacted reports and reviewed baselines.

Modes: ``changed-range`` (PR/push delta), ``full-history`` (scheduled/release),
``fixture-smoke`` (synthetic non-live credential classes) and
``validate-baseline``. Every mode fails closed: an unusable range, a shallow
checkout, a missing scanner binary, an ungoverned suppression surface, or
malformed baseline metadata all exit 1 with a one-line reason instead of a
traceback.

The Gitleaks CLI itself is installed from the checksum-locked tool module in
``tools/gitleaks`` (see ``.github/actions/gitleaks-gate``), never from a mutable
``@tag`` typed into a workflow.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import string
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(".gitleaks.toml")
BASELINE_PATH = Path("security/gitleaks-baseline.yml")
SCANNER_IGNORE_NAME = ".gitleaksignore"
REDACTED = "[REDACTED]"
REQUIRED_SYNTHETIC_CLASSES = (
    "pypi-token",
    "github-token",
    "aws-access-key",
    "private-key",
    "high-entropy",
)
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*$")
_ALL_ZERO_RE = re.compile(r"^0{40}$")
# Character classes keep these literals from matching themselves, the same
# self-evading style scripts/public_safety_scan.py uses for its token rules.
_TOKEN_REDACTIONS = (
    re.compile(r"\b[g]hp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b[g]ithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b[p]ypi-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b[A]KIA[0-9A-Z]{16}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ArtifactResult:
    """One scan's settled verdict plus the redacted files that record it."""

    ok: bool
    scanner_failed: bool
    findings: list[dict[str, Any]]
    report_path: Path
    sarif_path: Path
    summary_path: Path
    diagnostic: str


@dataclass(frozen=True)
class ScanOutcome:
    returncode: int
    findings: int
    command: list[str]
    summary_path: Path
    sarif_path: Path
    report_path: Path


Runner = Callable[[Sequence[str], Path], RunResult]
# Maps the redacted findings of one scan to ``(passed, headline)``. Scan modes
# disagree on what a finding means: for the repository scans any finding fails,
# while the fixture smoke fails when a required class is *not* reported.
Verdict = Callable[[Sequence[dict[str, Any]]], tuple[bool, str]]


class GitleaksScanError(RuntimeError):
    """Fail-closed wrapper validation error."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run(command: Sequence[str], cwd: Path) -> RunResult:
    """Run ``command``; a missing executable is a bounded error, not a traceback."""
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        raise GitleaksScanError(f"could not execute {command[0]!r}: {exc}") from exc
    return RunResult(completed.returncode, completed.stdout, completed.stderr)


def _git(command: Sequence[str], cwd: Path) -> RunResult:
    return _run(["git", *command], cwd)


def _validate_ref_arg(value: str, role: str) -> None:
    if not value or value.startswith("-") or not _REF_RE.match(value):
        raise GitleaksScanError(f"{role} ref is empty or unsafe: {value!r}")
    if _ALL_ZERO_RE.match(value):
        raise GitleaksScanError(f"{role} ref is the all-zero GitHub sentinel")


def _require_commit(root: Path, ref: str, role: str, git_runner: Runner) -> None:
    _validate_ref_arg(ref, role)
    result = git_runner(["rev-parse", "--verify", f"{ref}^{{commit}}"], root)
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr or result.stdout).strip() or "no output"
        raise GitleaksScanError(f"{role} ref {ref!r} is not a reachable commit: {detail}")


def ensure_changed_range(
    root: Path, base_ref: str, head_ref: str, git_runner: Runner = _git
) -> None:
    _require_commit(root, base_ref, "base", git_runner)
    _require_commit(root, head_ref, "head", git_runner)


def ensure_full_history(root: Path, git_runner: Runner = _git) -> None:
    inside = git_runner(["rev-parse", "--is-inside-work-tree"], root)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        detail = (inside.stderr or inside.stdout).strip() or "not a Git worktree"
        raise GitleaksScanError(f"full-history scan requires a Git worktree: {detail}")

    shallow = git_runner(["rev-parse", "--is-shallow-repository"], root)
    if shallow.returncode != 0:
        detail = (shallow.stderr or shallow.stdout).strip() or "git shallow check failed"
        raise GitleaksScanError(f"full-history scan could not verify checkout depth: {detail}")
    if shallow.stdout.strip() != "false":
        raise GitleaksScanError("full-history scan requires fetch-depth 0 / non-shallow history")

    count = git_runner(["rev-list", "--count", "--all"], root)
    if count.returncode != 0:
        detail = (count.stderr or count.stdout).strip() or "git rev-list failed"
        raise GitleaksScanError(f"full-history scan could not count reachable history: {detail}")
    try:
        commits = int(count.stdout.strip())
    except ValueError as exc:
        raise GitleaksScanError(
            f"full-history scan got a non-integer reachable commit count: {count.stdout!r}"
        ) from exc
    if commits < 1:
        raise GitleaksScanError("full-history scan found no reachable commits")


# ── Reviewed baseline metadata ─────────────────────────────────────────────────


def load_baseline_metadata(path: Path) -> dict[str, Any]:
    """Parse the reviewed baseline file; every I/O or syntax failure is bounded."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise GitleaksScanError(f"baseline metadata file is missing: {path}") from exc
    except OSError as exc:
        raise GitleaksScanError(f"baseline metadata file is unreadable: {path}: {exc}") from exc
    if not text.strip():
        raise GitleaksScanError(f"baseline metadata file is empty: {path}")
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GitleaksScanError(f"baseline metadata file is not valid YAML: {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GitleaksScanError("baseline metadata must be a mapping")
    return parsed


def baseline_validation_errors(path: Path) -> list[str]:
    try:
        data = load_baseline_metadata(path)
    except GitleaksScanError as exc:
        return [str(exc)]

    errors: list[str] = []
    if data.get("version") != 1:
        errors.append("version must be 1")
    entries = data.get("entries")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        errors.append("entries must be a list")
        return errors

    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"entries[{index}] must be a mapping")
            continue
        for key in ("fingerprint", "rationale", "owner"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"entries[{index}].{key} must be a non-empty string")
        # An unquoted YAML date (expires: 2027-01-01) parses as datetime.date, so
        # accept both that and a quoted string rather than rejecting the natural
        # spelling of a date.
        review = entry.get("review_condition")
        expiry = entry.get("expires")
        has_review = isinstance(review, str) and bool(review.strip())
        has_expiry = isinstance(expiry, datetime.date) or (
            isinstance(expiry, str) and bool(expiry.strip())
        )
        if not (has_review or has_expiry):
            errors.append(
                f"entries[{index}] must include review_condition or a dated expires value"
            )
        fingerprint = entry.get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint.strip():
            if fingerprint in seen:
                errors.append(f"entries[{index}].fingerprint duplicates {fingerprint!r}")
            seen.add(fingerprint)
    return errors


def baseline_fingerprints(path: Path) -> list[str]:
    errors = baseline_validation_errors(path)
    if errors:
        raise GitleaksScanError("; ".join(errors))
    entries = load_baseline_metadata(path).get("entries") or []
    return [entry["fingerprint"] for entry in entries]


def _write_scanner_ignore(fingerprints: Sequence[str], temp_dir: Path) -> list[str]:
    """Derive the scanner ignore file from reviewed fingerprints only.

    Gitleaks' ``--baseline-path`` compares whole findings and explicitly ignores
    the fingerprint, so it cannot express "this reviewed fingerprint is allowed".
    ``.gitleaksignore`` is the fingerprint-keyed mechanism, so the file is always
    passed — even when empty — and it is written into a temporary directory
    outside the scanned tree.

    Passing it does **not** displace an in-tree ``.gitleaksignore``: Gitleaks
    loads ``<source>/.gitleaksignore`` unconditionally, in addition to this path.
    ``ensure_no_scanner_ignore_file`` is what keeps a stray unreviewed file from
    silencing a finding.
    """
    ignore_path = temp_dir / SCANNER_IGNORE_NAME
    body = "".join(f"{fingerprint}\n" for fingerprint in fingerprints)
    ignore_path.write_text(body, encoding="utf-8")
    return ["--gitleaks-ignore-path", str(ignore_path)]


def ensure_no_scanner_ignore_file(source: Path) -> None:
    """Fail closed when the scanned tree carries its own ``.gitleaksignore``.

    Gitleaks reads ``<source>/.gitleaksignore`` in addition to the explicit
    ``--gitleaks-ignore-path`` derived from reviewed metadata, so a two-line file
    dropped into the worktree suppresses findings that ``validate-baseline``
    never sees. Its presence is therefore an error, not an input.
    """
    stray = source / SCANNER_IGNORE_NAME
    if stray.exists():
        raise GitleaksScanError(
            f"ungoverned {SCANNER_IGNORE_NAME} in the scanned tree: {stray}; "
            f"{BASELINE_PATH.as_posix()} is the only governed suppression path"
        )


# ── Governed suppression surfaces in the scanner configuration ─────────────────

# A pattern that matches every probe below silences whole rules — or the whole
# scan — with no fingerprint, owner, or review condition behind it.
_ALLOWLIST_PROBES = (
    "a",
    "mempalace_code/storage.py",
    "docs/quality/scorecard.md",
    "tools/gitleaks/go.sum",
)


def _is_catch_all(pattern: str) -> bool:
    try:
        compiled = re.compile(pattern)
    except re.error:
        # Gitleaks compiles these with Go's RE2. Anything Python cannot parse is
        # left to the scanner rather than guessed at here.
        return False
    return all(compiled.search(probe) for probe in _ALLOWLIST_PROBES)


def _allowlist_blocks(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Both the singular and plural spellings Gitleaks accepts."""
    blocks: list[dict[str, Any]] = []
    single = table.get("allowlist")
    if isinstance(single, dict):
        blocks.append(single)
    plural = table.get("allowlists")
    if isinstance(plural, list):
        blocks.extend(item for item in plural if isinstance(item, dict))
    return blocks


def config_validation_errors(path: Path) -> list[str]:
    """Reject config-level suppressions, which carry no reviewed metadata.

    ``security/gitleaks-baseline.yml`` suppresses one fingerprint at a time and is
    validated entry by entry. A ``[allowlist]`` in the scanner config is the
    competing mechanism: it silences findings by path or regex with no
    fingerprint, owner, or review condition, and nothing else in the gate notices.
    Narrow per-rule allowlists stay legal — only catch-all patterns are rejected.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"Gitleaks config is missing: {path}"]
    except (OSError, UnicodeDecodeError) as exc:
        return [f"Gitleaks config is unreadable: {path}: {exc}"]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [f"Gitleaks config is not valid TOML: {path}: {exc}"]

    errors: list[str] = []
    if _allowlist_blocks(data):
        errors.append(
            "top-level allowlist suppresses findings repository-wide without reviewed "
            f"metadata; use {BASELINE_PATH.as_posix()} instead"
        )
    rules = data.get("rules")
    if not isinstance(rules, list):
        return errors
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            continue
        rule_id = rule["id"] if isinstance(rule.get("id"), str) else f"rules[{index}]"
        for block in _allowlist_blocks(rule):
            for key in ("paths", "regexes"):
                patterns = block.get(key)
                if isinstance(patterns, str):
                    patterns = [patterns]
                if not isinstance(patterns, list):
                    continue
                errors.extend(
                    f"rule {rule_id!r} allowlist {key} entry {pattern!r} matches everything, "
                    f"which disables the rule without review; use {BASELINE_PATH.as_posix()}"
                    for pattern in patterns
                    if isinstance(pattern, str) and _is_catch_all(pattern)
                )
    return errors


# ── Report loading, redaction and artifacts ────────────────────────────────────


def _finding_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        findings = payload.get("findings") or payload.get("Findings") or payload.get("results")
        if isinstance(findings, list):
            return [item for item in findings if isinstance(item, dict)]
    return []


def load_report(path: Path) -> Any:
    """Return the raw Gitleaks report payload; an unwritten report reads as empty."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GitleaksScanError(f"Gitleaks report is not valid JSON: {path}: {exc}") from exc


def load_findings(path: Path) -> list[dict[str, Any]]:
    return _finding_list(load_report(path))


def _secret_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"secret", "match"} and isinstance(item, str) and len(item) >= 6:
                values.append(item)
            values.extend(_secret_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_secret_values(item))
    return values


def redact_text(text: str, extra_values: Sequence[str] = ()) -> str:
    redacted = text
    for value in sorted({v for v in extra_values if len(v) >= 6}, key=len, reverse=True):
        redacted = redacted.replace(value, REDACTED)
    for pattern in _TOKEN_REDACTIONS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def _sanitize_payload(value: Any, extra_values: Sequence[str]) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"secret", "match"}:
                clean[key] = REDACTED
            else:
                clean[key] = _sanitize_payload(item, extra_values)
        return clean
    if isinstance(value, list):
        return [_sanitize_payload(item, extra_values) for item in value]
    if isinstance(value, str):
        return redact_text(value, extra_values)
    return value


def _finding_value(finding: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = finding.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return default


def _finding_line(finding: dict[str, Any]) -> int:
    value = finding.get("StartLine", finding.get("Line", finding.get("line", 1)))
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def _finding_facts(finding: dict[str, Any]) -> tuple[str, str, str]:
    rule = _finding_value(finding, "RuleID", "RuleId", "rule_id", default="unknown-rule")
    file_name = _finding_value(finding, "File", "file", "filename", default="unknown-file")
    fingerprint = _finding_value(
        finding, "Fingerprint", "fingerprint", default="missing-fingerprint"
    )
    return rule, file_name, fingerprint


def _summary_lines(findings: Sequence[dict[str, Any]], headline: str) -> list[str]:
    lines = [headline]
    for finding in findings:
        rule, file_name, fingerprint = _finding_facts(finding)
        commit = _finding_value(finding, "Commit", "commit")
        suffix = f" commit={commit}" if commit else ""
        lines.append(
            f"  - {rule} {file_name}:{_finding_line(finding)} fingerprint={fingerprint}{suffix}"
        )
    return lines


def _write_sarif(
    findings: Sequence[dict[str, Any]],
    path: Path,
    *,
    headline: str,
    scanner_failed: bool,
    returncode: int,
) -> None:
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for finding in findings:
        rule, file_name, fingerprint = _finding_facts(finding)
        rules.setdefault(rule, {"id": rule, "shortDescription": {"text": rule}})
        results.append(
            {
                "ruleId": rule,
                "message": {"text": f"Gitleaks finding fingerprint={fingerprint}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": file_name},
                            "region": {"startLine": _finding_line(finding)},
                        }
                    }
                ],
                "partialFingerprints": {"gitleaksFingerprint": fingerprint},
            }
        )
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "Gitleaks", "rules": list(rules.values())}},
                # A scan that never ran must not read as a clean one. SARIF's own
                # success flag carries the same verdict as the summary headline,
                # so a downstream consumer cannot mistake "0 findings" for "clean".
                "invocations": [
                    {
                        "executionSuccessful": not scanner_failed,
                        "exitCode": returncode,
                        "exitCodeDescription": headline,
                    }
                ],
                "results": results,
            }
        ],
    }
    path.write_text(json.dumps(sarif, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_redacted_artifacts(
    *,
    raw_report: Path,
    artifact_dir: Path,
    mode: str,
    verdict: Verdict,
    returncode: int,
    stdout: str,
    stderr: str,
) -> ArtifactResult:
    raw_payload = load_report(raw_report)
    secret_values = _secret_values(raw_payload)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report_path = artifact_dir / f"{mode}.report.json"
    sarif_path = artifact_dir / f"{mode}.sarif"
    summary_path = artifact_dir / f"{mode}.summary.txt"

    clean_payload = _sanitize_payload(raw_payload, secret_values)
    findings = _finding_list(clean_payload)

    # A nonzero exit that parsed into no findings means Gitleaks or its config
    # failed, not that the tree is clean. The verdict is settled here, before any
    # artifact is written, so stdout, the summary and the SARIF cannot attest a
    # clean scan that never happened.
    scanner_failed = returncode not in (0, 1) or (returncode == 1 and not findings)
    ok, headline = verdict(findings)
    if scanner_failed:
        ok = False
        headline = (
            f"gitleaks-scan: FAIL ({mode}; scanner error, exit {returncode}; "
            f"{len(findings)} finding(s))"
        )

    report_path.write_text(
        json.dumps(clean_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_sarif(
        findings,
        sarif_path,
        headline=headline,
        scanner_failed=scanner_failed,
        returncode=returncode,
    )
    summary = redact_text("\n".join(_summary_lines(findings, headline)) + "\n", secret_values)
    summary_path.write_text(summary, encoding="utf-8")
    return ArtifactResult(
        ok=ok,
        scanner_failed=scanner_failed,
        findings=findings,
        report_path=report_path,
        sarif_path=sarif_path,
        summary_path=summary_path,
        diagnostic=redact_text("\n".join(part for part in (stdout, stderr) if part), secret_values),
    )


def _base_command(subcommand: str, config: Path, report_path: Path) -> list[str]:
    return [
        "gitleaks",
        subcommand,
        "--config",
        str(config),
        "--redact=100",
        "--exit-code=1",
        "--no-banner",
        "--report-format=json",
        "--report-path",
        str(report_path),
    ]


# ── Scan modes ─────────────────────────────────────────────────────────────────


def _repository_verdict(mode: str) -> Verdict:
    """Any reported finding fails a repository scan."""

    def verdict(findings: Sequence[dict[str, Any]]) -> tuple[bool, str]:
        if not findings:
            return True, f"gitleaks-scan: OK ({mode}; 0 findings)"
        return False, f"gitleaks-scan: FAIL ({mode}; {len(findings)} finding(s))"

    return verdict


def _scan(
    *,
    root: Path,
    mode: str,
    subcommand: str,
    scan_args: Sequence[str],
    target: str,
    config_path: Path,
    fingerprints: Sequence[str],
    verdict: Verdict,
    artifact_dir: Path,
    runner: Runner,
) -> ScanOutcome:
    """Run one Gitleaks invocation and write only redacted artifacts.

    The raw report stays inside a ``TemporaryDirectory`` that is removed on exit;
    nothing unredacted reaches ``artifact_dir``, stdout, or stderr. A nonzero exit
    with no parsed findings means the scanner itself failed, so its (redacted)
    diagnostics are surfaced rather than reported as a clean scan.
    """
    ensure_no_scanner_ignore_file(root / target)
    with tempfile.TemporaryDirectory(prefix="gitleaks-raw-") as raw_dir:
        raw_report = Path(raw_dir) / f"{mode}.raw.json"
        command = [
            *_base_command(subcommand, config_path, raw_report),
            *_write_scanner_ignore(fingerprints, Path(raw_dir)),
            *scan_args,
            target,
        ]
        result = runner(command, root)
        artifacts = _write_redacted_artifacts(
            raw_report=raw_report,
            artifact_dir=artifact_dir,
            mode=mode,
            verdict=verdict,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        print(artifacts.summary_path.read_text(encoding="utf-8"), end="")
        if artifacts.scanner_failed and artifacts.diagnostic:
            print(artifacts.diagnostic, file=sys.stderr)
        return ScanOutcome(
            returncode=0 if artifacts.ok else 1,
            findings=len(artifacts.findings),
            command=command,
            summary_path=artifacts.summary_path,
            sarif_path=artifacts.sarif_path,
            report_path=artifacts.report_path,
        )


def run_changed_range(
    *,
    root: Path,
    base_ref: str,
    head_ref: str,
    config_path: Path,
    baseline_path: Path,
    artifact_dir: Path,
    runner: Runner = _run,
    git_runner: Runner = _git,
) -> ScanOutcome:
    ensure_changed_range(root, base_ref, head_ref, git_runner)
    return _scan(
        root=root,
        mode="changed-range",
        subcommand="git",
        scan_args=[f"--log-opts={base_ref}..{head_ref}"],
        target=".",
        config_path=config_path,
        fingerprints=baseline_fingerprints(baseline_path),
        verdict=_repository_verdict("changed-range"),
        artifact_dir=artifact_dir,
        runner=runner,
    )


def run_full_history(
    *,
    root: Path,
    config_path: Path,
    baseline_path: Path,
    artifact_dir: Path,
    runner: Runner = _run,
    git_runner: Runner = _git,
) -> ScanOutcome:
    ensure_full_history(root, git_runner)
    return _scan(
        root=root,
        mode="full-history",
        subcommand="git",
        scan_args=["--log-opts=--all"],
        target=".",
        config_path=config_path,
        fingerprints=baseline_fingerprints(baseline_path),
        verdict=_repository_verdict("full-history"),
        artifact_dir=artifact_dir,
        runner=runner,
    )


# ── Synthetic fixture smoke ────────────────────────────────────────────────────

_ALNUM = string.ascii_letters + string.digits
# aws-access-token requires [A-Z2-7]{16}; pypi-upload-token requires [\w-]{50,}.
_BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_WORD = _ALNUM + "_-"
_BASE64 = _ALNUM + "+/"


def _synthetic_body(seed: str, alphabet: str, length: int) -> str:
    """Deterministic high-entropy filler.

    Fixtures must clear each rule's entropy threshold, so repeated-character
    filler is not usable. The value is derived here at runtime, which also keeps
    every complete credential-shaped string out of tracked source (INV-4).
    """
    chars: list[str] = []
    counter = 0
    while len(chars) < length:
        block = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        chars.extend(alphabet[byte % len(alphabet)] for byte in block)
        counter += 1
    return "".join(chars[:length])


def build_synthetic_fixture(root: Path) -> dict[str, Path]:
    """Write one non-live file per required secret class into ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    values = {
        "pypi-token": "pypi-" + "AgEIcHlwaS5vcmc" + _synthetic_body("pypi", _WORD, 64),
        "github-token": "gh" + "p_" + _synthetic_body("github", _ALNUM, 36),
        "aws-access-key": "AK" + "IA" + _synthetic_body("aws", _BASE32, 16),
        "private-key": (
            "-----BEGIN "
            + "RSA PRIVATE KEY-----\n"
            + _synthetic_body("private-key", _BASE64, 128)
            + "\n-----END "
            + "RSA PRIVATE KEY-----"
        ),
        "high-entropy": "repo_token = '" + _synthetic_body("entropy", _ALNUM, 44) + "'",
    }
    paths: dict[str, Path] = {}
    for secret_class, value in values.items():
        path = root / f"{secret_class}.txt"
        path.write_text(value + "\n", encoding="utf-8")
        paths[secret_class] = path
    return paths


def run_fixture_smoke(
    *,
    root: Path,
    config_path: Path,
    artifact_dir: Path,
    runner: Runner = _run,
) -> ScanOutcome:
    """Assert the configured rule corpus still detects every required class.

    Findings are the expected result here — the smoke fails when a class is
    *missing*, which is what a silently narrowed rule set would look like.
    """
    with tempfile.TemporaryDirectory(prefix="gitleaks-fixtures-") as fixture_dir:
        fixture_paths = build_synthetic_fixture(Path(fixture_dir))

        def verdict(findings: Sequence[dict[str, Any]]) -> tuple[bool, str]:
            reported = {_finding_value(finding, "File", "file", "filename") for finding in findings}
            missing = sorted(
                secret_class
                for secret_class, path in fixture_paths.items()
                if not any(path.name in file_name for file_name in reported)
            )
            total = len(fixture_paths)
            if missing:
                return False, (
                    f"gitleaks-scan: FAIL (fixture-smoke; {total - len(missing)}/{total} required "
                    f"classes detected; undetected: {', '.join(missing)})"
                )
            return True, f"gitleaks-scan: OK (fixture-smoke; {total}/{total} required classes)"

        return _scan(
            root=root,
            mode="fixture-smoke",
            subcommand="dir",
            scan_args=[],
            target=fixture_dir,
            config_path=config_path,
            # No suppressions: the smoke must see the corpus exactly as configured.
            fingerprints=[],
            verdict=verdict,
            artifact_dir=artifact_dir,
            runner=runner,
        )


# ── CLI ────────────────────────────────────────────────────────────────────────


def _artifact_dir(root: Path, value: str | None, temp_parent: Path) -> Path:
    if value:
        path = Path(value)
        return path if path.is_absolute() else root / path
    return temp_parent / "artifacts"


def _display_path(path: Path, root: Path) -> str:
    """Repository-relative when possible; ``--baseline`` may point anywhere."""
    return Path(os.path.relpath(path, root)).as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run redacted Gitleaks security gates.")
    parser.add_argument("--repo-root", type=Path, default=repo_root(), help=argparse.SUPPRESS)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline_parser = subparsers.add_parser("validate-baseline")
    baseline_parser.add_argument("--artifact-dir", help=argparse.SUPPRESS)

    changed = subparsers.add_parser("changed-range")
    changed.add_argument("--base-ref", required=True)
    changed.add_argument("--head-ref", required=True)
    changed.add_argument("--artifact-dir")

    full = subparsers.add_parser("full-history")
    full.add_argument("--artifact-dir")

    fixture = subparsers.add_parser("fixture-smoke")
    fixture.add_argument("--artifact-dir")

    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    config_path = args.config if args.config.is_absolute() else root / args.config
    baseline_path = args.baseline if args.baseline.is_absolute() else root / args.baseline

    try:
        if args.command == "validate-baseline":
            # Both governed suppression surfaces are validated together: reviewed
            # per-fingerprint metadata, and the scanner config that could silence
            # the same finding without any metadata at all.
            errors = [
                *baseline_validation_errors(baseline_path),
                *config_validation_errors(config_path),
            ]
            if errors:
                print("gitleaks-baseline: FAIL", file=sys.stderr)
                for error in errors:
                    print(f"  - {error}", file=sys.stderr)
                return 1
            print(
                f"gitleaks-baseline: OK ({_display_path(baseline_path, root)}, "
                f"{_display_path(config_path, root)})"
            )
            return 0

        with tempfile.TemporaryDirectory(prefix="gitleaks-artifacts-") as temp_artifacts:
            artifacts = _artifact_dir(root, args.artifact_dir, Path(temp_artifacts))
            if args.command == "changed-range":
                outcome = run_changed_range(
                    root=root,
                    base_ref=args.base_ref,
                    head_ref=args.head_ref,
                    config_path=config_path,
                    baseline_path=baseline_path,
                    artifact_dir=artifacts,
                )
            elif args.command == "full-history":
                outcome = run_full_history(
                    root=root,
                    config_path=config_path,
                    baseline_path=baseline_path,
                    artifact_dir=artifacts,
                )
            elif args.command == "fixture-smoke":
                outcome = run_fixture_smoke(
                    root=root, config_path=config_path, artifact_dir=artifacts
                )
            else:  # pragma: no cover - argparse rejects unknown subcommands first
                parser.error("unknown command")
            return outcome.returncode
    except GitleaksScanError as exc:
        print(f"gitleaks-scan: FAIL - {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"gitleaks-scan: FAIL - {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
