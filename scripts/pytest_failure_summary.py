#!/usr/bin/env python3
"""Emit one bounded, public-safe GitHub annotation from a pytest JUnit report."""

from __future__ import annotations

import argparse
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_REPORT_BYTES = 16 * 1024 * 1024
PUBLIC_CLASSNAME = re.compile(r"tests(?:\.[A-Za-z0-9_]+)+")
PUBLIC_TEST_NAME = re.compile(r"[A-Za-z0-9_.-]+")
FAILURE_REASON = re.compile(r"mempalace_reason=([a-z0-9_]+)")
PUBLIC_FAILURE_REASONS = frozenset(
    {
        "watcher_backup_count",
        "watcher_disk_growth",
        "watcher_exit_nonzero",
        "watcher_fd_growth",
        "watcher_first_cycle_timeout",
        "watcher_init_failed",
        "watcher_output_timeout",
        "watcher_rss_final",
        "watcher_rss_peak",
        "watcher_stdout_unavailable",
        "watcher_summary_mismatch",
    }
)


def _public_identifier(value: object, pattern: re.Pattern[str], limit: int) -> str:
    base = str(value).split("[", 1)[0]
    return base[:limit] if pattern.fullmatch(base) else "unavailable"


def _public_reason(outcome: ET.Element) -> str:
    private_failure = f"{outcome.get('message', '')}\n{outcome.text or ''}"
    match = FAILURE_REASON.search(private_failure)
    if match and match.group(1) in PUBLIC_FAILURE_REASONS:
        return match.group(1)
    return "unavailable"


def first_failure(report_path: Path) -> tuple[str, str, str, str]:
    try:
        metadata = report_path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_REPORT_BYTES:
            return "unavailable", "unavailable", "session", "unavailable"
        root = ET.parse(report_path).getroot()
    except (OSError, ET.ParseError):
        return "unavailable", "unavailable", "session", "unavailable"

    for testcase in root.iter("testcase"):
        outcome_element = next(
            (child for child in testcase if child.tag.rsplit("}", 1)[-1] in {"failure", "error"}),
            None,
        )
        if outcome_element is None:
            continue
        classname = _public_identifier(testcase.get("classname", ""), PUBLIC_CLASSNAME, 240)
        name = _public_identifier(testcase.get("name", ""), PUBLIC_TEST_NAME, 120)
        phase = outcome_element.tag.rsplit("}", 1)[-1]
        return classname, name, phase, _public_reason(outcome_element)
    return "unavailable", "unavailable", "session", "unavailable"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    classname, name, phase, reason = first_failure(args.report)
    print(
        f"::error title=pytest failure::classname={classname} name={name} "
        f"phase={phase} reason={reason}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
