#!/usr/bin/env python3
"""Repository public-safety scan for publishable files.

Checks tracked and staged text for private local paths, secret-like tokens, and
local-only artifact paths. Output is intentionally redacted: failures report the
rule id and file position, not the matched text.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

LOCAL_ONLY_PREFIXES = (
    ".tasks/",
    ".protocols/",
    ".verify-state",
    ".codex-local/",
    "docs/audits/",
)

GENERIC_TEMP_ROOTS = frozenset({"/tmp", "/var/tmp", "/private/var/tmp"})


@dataclass(frozen=True)
class PatternRule:
    rule_id: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class PublicSafetyHit:
    source: str
    rule_id: str
    line: int
    column: int

    def summary(self) -> str:
        return f"{self.source}:{self.line}:{self.column}: {self.rule_id}"


def _join_root(*parts: str) -> str:
    return "".join(parts)


def _token_rules() -> list[PatternRule]:
    return [
        PatternRule("github-token-prefix", re.compile(r"\b[g]hp_[A-Za-z0-9]{20,}")),
        PatternRule("github-pat-prefix", re.compile(r"[g]ithub_pat_")),
        PatternRule("pypi-token-prefix", re.compile(r"\b[p]ypi-[A-Za-z0-9_-]{20,}")),
        PatternRule("openai-token-prefix", re.compile(r"\b[s]k-[A-Za-z0-9]{16,}")),
        PatternRule("anthropic-token-prefix", re.compile(r"\b[s]k-ant-[A-Za-z0-9_-]{16,}")),
    ]


def rendered_rules() -> list[PatternRule]:
    """Rules for generated public artifacts that should contain no absolute roots."""
    roots = [
        ("macos-home-root", _join_root("/", "Users", "/")),
        ("linux-home-root", _join_root("/", "home", "/")),
        ("root-home-root", _join_root("/", "root", "/")),
        ("service-root", _join_root("/", "srv", "/")),
        ("opt-root", _join_root("/", "opt", "/")),
        ("macos-temp-root", _join_root("/", "var", "/", "folders", "/")),
        ("tmp-root", _join_root("/", "tmp", "/")),
        ("windows-user-root", _join_root("C:", "\\", "Users", "\\")),
    ]
    return [PatternRule(rule_id, re.compile(re.escape(value))) for rule_id, value in roots] + (
        _token_rules()
    )


def repository_rules(repo_root: Path) -> list[PatternRule]:
    """Rules for repo source files.

    Public examples can mention generic paths such as /tmp/example. What must not
    land in the repo is this machine's actual home, temp, or checkout path.
    """
    rules = _token_rules()
    candidates: list[tuple[str, str]] = []

    env_home = os.environ.get("HOME")
    if env_home:
        candidates.append(("local-home", env_home))
    for env_name in ("TMPDIR", "TMP", "TEMP", "USERPROFILE"):
        env_val = os.environ.get(env_name)
        if env_val:
            candidates.append((f"local-env-{env_name.lower()}", env_val))
    candidates.extend(
        [
            ("local-home", str(Path.home())),
            ("local-temp", tempfile.gettempdir()),
            ("repo-root", str(repo_root.resolve())),
        ]
    )

    seen: set[str] = set()
    for rule_id, raw_path in candidates:
        normalized = Path(raw_path).expanduser().as_posix().rstrip("/")
        if len(normalized) <= 3 or normalized in GENERIC_TEMP_ROOTS or normalized in seen:
            continue
        seen.add(normalized)
        rules.append(PatternRule(rule_id, re.compile(re.escape(normalized) + r"(?:/|$)")))
    return rules


def scan_text(source: str, text: str, rules: list[PatternRule]) -> list[PublicSafetyHit]:
    hits: list[PublicSafetyHit] = []
    seen_positions: set[tuple[str, int, int]] = set()
    for rule in rules:
        for match in rule.pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            last_newline = text.rfind("\n", 0, match.start())
            column = match.start() + 1 if last_newline < 0 else match.start() - last_newline
            location = (source, line, column)
            if location in seen_positions:
                continue
            seen_positions.add(location)
            hits.append(PublicSafetyHit(source, rule.rule_id, line, column))
    return hits


def scan_bytes(source: str, content: bytes, rules: list[PatternRule]) -> list[PublicSafetyHit]:
    text = content.decode("utf-8", errors="ignore")
    return scan_text(source, text, rules)


def scan_rendered_texts(*texts: str) -> list[str]:
    hits: list[PublicSafetyHit] = []
    for idx, text in enumerate(texts, start=1):
        hits.extend(scan_text(f"rendered:{idx}", text, rendered_rules()))
    return sorted({hit.summary() for hit in hits})


def _git(root: Path, args: list[str]) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def _split_z(output: bytes) -> list[str]:
    return [p.decode("utf-8", errors="surrogateescape") for p in output.split(b"\0") if p]


def tracked_paths(root: Path) -> list[str]:
    return sorted(_split_z(_git(root, ["ls-files", "-z"])))


def staged_paths(root: Path) -> list[str]:
    return sorted(
        _split_z(_git(root, ["diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z"]))
    )


def _read_worktree(root: Path, rel_path: str) -> bytes | None:
    path = root / rel_path
    if not path.is_file():
        return None
    return path.read_bytes()


def _read_staged(root: Path, rel_path: str) -> bytes | None:
    try:
        return _git(root, ["show", f":{rel_path}"])
    except subprocess.CalledProcessError:
        return None


def _path_policy_hit(source: str, rel_path: str) -> PublicSafetyHit | None:
    normalized = rel_path.strip("/")
    for prefix in LOCAL_ONLY_PREFIXES:
        clean_prefix = prefix.strip("/")
        if normalized == clean_prefix or normalized.startswith(prefix):
            return PublicSafetyHit(source, "local-only-artifact-path", 1, 1)
    return None


def scan_git_sources(
    root: Path, *, tracked: bool, staged: bool
) -> tuple[list[PublicSafetyHit], int]:
    rules = repository_rules(root)
    hits: list[PublicSafetyHit] = []
    scanned = 0

    if tracked:
        for rel_path in tracked_paths(root):
            source = f"tracked:{rel_path}"
            content = _read_worktree(root, rel_path)
            if content is None:
                continue
            path_hit = _path_policy_hit(source, rel_path)
            if path_hit:
                hits.append(path_hit)
            scanned += 1
            hits.extend(scan_bytes(source, content, rules))

    if staged:
        for rel_path in staged_paths(root):
            source = f"staged:{rel_path}"
            path_hit = _path_policy_hit(source, rel_path)
            if path_hit:
                hits.append(path_hit)
            content = _read_staged(root, rel_path)
            if content is None:
                continue
            scanned += 1
            hits.extend(scan_bytes(source, content, rules))

    return sorted(set(hits), key=lambda h: h.summary()), scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan tracked/staged files for public-safety leaks."
    )
    parser.add_argument("--repo-root", default=".", help=argparse.SUPPRESS)
    parser.add_argument("--tracked", action="store_true", help="Scan tracked worktree files.")
    parser.add_argument("--staged", action="store_true", help="Scan staged index blobs.")
    args = parser.parse_args(argv)

    if not args.tracked and not args.staged:
        parser.error("choose at least one of --tracked or --staged")

    root = Path(args.repo_root).resolve()
    try:
        hits, scanned = scan_git_sources(root, tracked=args.tracked, staged=args.staged)
    except subprocess.CalledProcessError as exc:
        print(f"public-safety-scan: FAIL - git command failed: {exc.cmd}", file=sys.stderr)
        return 1

    if hits:
        print("public-safety-scan: FAIL", file=sys.stderr)
        for hit in hits:
            print(f"  - {hit.summary()}", file=sys.stderr)
        return 1

    modes = ", ".join(
        mode for mode, enabled in (("tracked", args.tracked), ("staged", args.staged)) if enabled
    )
    print(f"public-safety-scan: OK ({modes}; scanned {scanned} file snapshots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
