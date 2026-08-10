#!/usr/bin/env python3
"""Workflow summary guard — validates publishable workflow review summaries.

Checks that every surviving finding in a sanitized summary has concrete evidence
and an explicit action or deferral branch. Rejects private paths and secret-like
tokens without echoing the matched content in diagnostics.

Usage:
    python scripts/workflow_summary_guard.py --file summary.md
    cat pr-body-snippet.md | python scripts/workflow_summary_guard.py
    python scripts/workflow_summary_guard.py --file a.md --file b.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Public-safety rules — mirrors rendered_rules() in scripts/public_safety_scan.py
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PatternRule:
    rule_id: str
    pattern: re.Pattern[str]


def _join(*parts: str) -> str:
    return "".join(parts)


def _token_rules() -> list[_PatternRule]:
    return [
        _PatternRule("github-token-prefix", re.compile(r"\b[g]hp_[A-Za-z0-9]{20,}")),
        _PatternRule("github-pat-prefix", re.compile(r"[g]ithub_pat_")),
        _PatternRule("pypi-token-prefix", re.compile(r"\b[p]ypi-[A-Za-z0-9_-]{20,}")),
        _PatternRule("openai-token-prefix", re.compile(r"\b[s]k-[A-Za-z0-9]{16,}")),
        _PatternRule("anthropic-token-prefix", re.compile(r"\b[s]k-ant-[A-Za-z0-9_-]{16,}")),
    ]


def _local_only_artifact_rules() -> list[_PatternRule]:
    prefixes = [
        ".tasks/",
        ".protocols/",
        ".verify-state",
        ".codex-local/",
        "docs/audits/",
    ]
    return [_PatternRule("local-only-artifact", re.compile(re.escape(p))) for p in prefixes]


def _public_safety_rules() -> list[_PatternRule]:
    roots = [
        ("macos-home-root", _join("/", "Users", "/")),
        ("linux-home-root", _join("/", "home", "/")),
        ("root-home-root", _join("/", "root", "/")),
        ("service-root", _join("/", "srv", "/")),
        ("opt-root", _join("/", "opt", "/")),
        ("macos-temp-root", _join("/", "var", "/", "folders", "/")),
        ("tmp-root", _join("/", "tmp", "/")),
        ("windows-user-root", _join("C:", "\\", "Users", "\\")),
    ]
    return [_PatternRule(rid, re.compile(re.escape(v))) for rid, v in roots] + _token_rules()


# ---------------------------------------------------------------------------
# Schema & validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = frozenset(
    {
        "review lens",
        "finding",
        "evidence",
        "action taken",
        "verification",
        "deferral reason",
    }
)

_FIELD_RE = re.compile(r"\*\*([^*]+)\*\*\s*:\s*(.*)", re.IGNORECASE)
_BACKLOG_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9-]*\b")
_PATH_FRAG_RE = re.compile(r"\b[A-Za-z0-9_.][A-Za-z0-9_.-]*/[A-Za-z0-9_./:-]+")
_FILE_EXT_RE = re.compile(
    r"\b[A-Za-z0-9_][A-Za-z0-9_.-]*"
    r"\.(?:py|md|json|yaml|yml|toml|txt|rst|cfg|ini|sh|js|ts|go|rs|rb|lock|csv|html|css)"
    r"(?::\d+)?\b"
)

_TRIVIAL = frozenset({"", "none", "n/a", "na", "n.a.", "-", "tbd", "todo"})


@dataclass(frozen=True)
class Diagnostic:
    source: str
    rule_id: str
    line: int
    col: int = 1

    def summary(self) -> str:
        return f"{self.source}:{self.line}:{self.col}: {self.rule_id}"


@dataclass
class _FindingBlock:
    fields: dict[str, tuple[str, int]] = field(default_factory=dict)

    @property
    def first_line(self) -> int:
        if not self.fields:
            return 1
        return min(ln for _, ln in self.fields.values())


def _is_trivial(value: str) -> bool:
    return value.strip().lower() in _TRIVIAL


def _has_path_fragment(value: str) -> bool:
    """Return True when value contains a concrete file reference (nested path or top-level file)."""
    return bool(_PATH_FRAG_RE.search(value)) or bool(_FILE_EXT_RE.search(value))


def _parse_blocks(text: str) -> list[_FindingBlock]:
    """Split text into heading-delimited sections and extract field lines.

    Each section that contains at least one required field becomes a finding block.
    """
    current: _FindingBlock = _FindingBlock()
    blocks: list[_FindingBlock] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        if re.match(r"^#{1,6}\s", line):
            if current.fields:
                blocks.append(current)
            current = _FindingBlock()
            continue
        m = _FIELD_RE.search(line)
        if m:
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            if key in REQUIRED_FIELDS:
                current.fields[key] = (value, lineno)

    if current.fields:
        blocks.append(current)

    return blocks


def _validate_block(block: _FindingBlock, source: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    def _get(key: str) -> tuple[str, int]:
        return block.fields.get(key, ("", block.first_line))

    evidence, ev_line = _get("evidence")
    action, ac_line = _get("action taken")
    verification, _ = _get("verification")
    deferral, df_line = _get("deferral reason")

    if _is_trivial(evidence) or not _has_path_fragment(evidence):
        diagnostics.append(Diagnostic(source, "missing-evidence", ev_line))

    fixed_ok = (
        not _is_trivial(action) and _has_path_fragment(action) and not _is_trivial(verification)
    )
    deferred_ok = (
        not _is_trivial(deferral)
        and bool(_BACKLOG_ID_RE.search(deferral))
        and "acceptance" in deferral.lower()
    )

    if not fixed_ok and not deferred_ok:
        ref_line = ac_line if action else df_line
        diagnostics.append(Diagnostic(source, "missing-action-or-deferral", ref_line))

    return diagnostics


def _scan_public_safety(source: str, text: str) -> list[Diagnostic]:
    hits: list[Diagnostic] = []
    all_rules = _public_safety_rules() + _local_only_artifact_rules()
    for rule in all_rules:
        for match in rule.pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            last_nl = text.rfind("\n", 0, match.start())
            col = match.start() + 1 if last_nl < 0 else match.start() - last_nl
            hits.append(Diagnostic(source, rule.rule_id, line, col))
    return hits


def check_text(source: str, text: str) -> list[Diagnostic]:
    """Validate a workflow summary and return all diagnostics.

    Runs finding-block validation (evidence + actionability) and public-safety
    scanning. Returns an empty list when the summary is clean.
    """
    diagnostics: list[Diagnostic] = []
    for block in _parse_blocks(text):
        diagnostics.extend(_validate_block(block, source))
    diagnostics.extend(_scan_public_safety(source, text))
    return diagnostics


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate publishable workflow review summaries for actionability and public safety. "
            "Reads from stdin when --file is not provided."
        )
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        metavar="PATH",
        help="Summary file to check (may be given multiple times).",
    )
    args = parser.parse_args(argv)

    all_diagnostics: list[Diagnostic] = []

    if args.files:
        for path_str in args.files:
            path = Path(path_str)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                print(
                    f"workflow-summary-guard: ERROR reading {path_str}: {exc}",
                    file=sys.stderr,
                )
                return 1
            all_diagnostics.extend(check_text(str(path), text))
    else:
        text = sys.stdin.read()
        all_diagnostics.extend(check_text("<stdin>", text))

    if all_diagnostics:
        print("workflow-summary-guard: FAIL", file=sys.stderr)
        for d in sorted(all_diagnostics, key=lambda x: (x.source, x.line, x.col, x.rule_id)):
            print(f"  - {d.summary()}", file=sys.stderr)
        return 1

    sources = ", ".join(args.files) if args.files else "<stdin>"
    print(f"workflow-summary-guard: OK ({sources})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
