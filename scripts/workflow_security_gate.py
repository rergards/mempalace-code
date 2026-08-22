#!/usr/bin/env python3
"""workflow_security_gate.py — immutable Action pins and the publish permission boundary.

actionlint owns workflow syntax and zizmor owns expression-injection and permission
analysis; this gate adds only the two invariants they do not enforce for us: every
external ``uses:`` under .github/workflows/ is a full 40-hex commit SHA with an adjacent
version comment, and publish.yml keeps exactly the job set and the permissions Trusted
Publishing and the GitHub Release step need. ``uses:`` values come from the parsed YAML
node tree — quoted scalars, flow-style steps and job-level reusable-workflow calls all
included — the source line is read only to recover the trailing ``# <version>`` comment,
and anything the parser cannot resolve is reported rather than skipped.

Usage: python scripts/workflow_security_gate.py --root . [--format json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

import yaml

# Trailing ``# <version>`` comment following a ``uses:`` scalar on the same source line.
TRAILING_COMMENT_RE = re.compile(r"^\s*#\s*(?P<comment>\S.*?)\s*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

PUBLISH_PATH = ".github/workflows/publish.yml"
# Exact job set and permissions of the release workflow. "" is workflow level; {} means
# "declares nothing, inherits the workflow default".
# Exact per-job publish permissions. The workflow default stays read-only so a
# new job inherits nothing; every widening below is reviewed and read-only.
# `build` reads the release-required check-run (checks) and the Dependency Audit
# run history (actions) for release admission before any artifact is built.
# `github-release` rechecks the exact run/admission evidence and reconciles
# GitHub Release assets.
PUBLISH_PERMISSIONS: dict[str, dict[str, str]] = {
    "": {"contents": "read"},
    "build": {"contents": "read", "checks": "read", "actions": "read"},
    "publish": {"id-token": "write"},
    "github-release": {"contents": "write", "checks": "read", "actions": "read"},
}

RECOVERY = (
    "Recovery: pin every reported reference to the reviewed release commit SHA keeping its "
    "' # <version>' comment, restore the publish.yml job set and permissions, then re-run "
    "`python scripts/workflow_security_gate.py --root . --format json` and confirm exit 0."
)


def _fields(node: yaml.Node | None) -> dict[str, yaml.Node]:
    """Return the ``key -> value node`` fields of a YAML mapping node."""
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {key.value: value for key, value in node.value if isinstance(key, yaml.ScalarNode)}


def _line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


def _collect_uses(document: yaml.Node, relative: str, errors: list[str]) -> list[yaml.Node]:
    """Return every ``uses:`` scalar node GitHub Actions would execute in this workflow."""
    found: list[yaml.Node] = []

    def _record(owner: str, node: yaml.Node | None) -> None:
        if node is None:
            return
        if isinstance(node, yaml.ScalarNode) and node.value.strip():
            found.append(node)
        else:
            errors.append(
                f"UNPARSED-USES: {relative}:{_line(node)}: {owner} 'uses:' is not a string"
            )

    jobs = _fields(document).get("jobs")
    if jobs is not None and not isinstance(jobs, yaml.MappingNode):
        errors.append(f"UNPARSED-JOBS: {relative}:{_line(jobs)}: 'jobs:' is not a mapping")
        return found

    for job_id, job in _fields(jobs).items():
        # A job-level ``uses:`` is a reusable-workflow call and needs the same pin.
        _record(f"job {job_id!r}", _fields(job).get("uses"))
        steps = _fields(job).get("steps")
        if steps is None:
            continue
        if not isinstance(steps, yaml.SequenceNode):
            errors.append(
                f"UNPARSED-STEPS: {relative}:{_line(steps)}: job {job_id!r} steps are not a list"
            )
            continue
        for index, step in enumerate(steps.value):
            if isinstance(step, yaml.MappingNode):
                _record(f"job {job_id!r} step {index}", _fields(step).get("uses"))
            else:
                errors.append(
                    f"UNPARSED-STEPS: {relative}:{_line(step)}: job {job_id!r} step {index} "
                    "is not a mapping"
                )
    return found


def _trailing_comment(lines: list[str], node: yaml.Node) -> str:
    """Recover the ``# <version>`` comment that trails a scalar on its own source line."""
    start, end = node.start_mark.line, node.end_mark.line
    if start != end or end >= len(lines):
        return ""
    match = TRAILING_COMMENT_RE.match(lines[end][node.end_mark.column :])
    return match.group("comment") if match else ""


def _check_action_pins(root: Path, errors: list[str]) -> list[dict[str, object]]:
    """Require a full commit SHA plus a version comment on every external ``uses:``."""
    reports: list[dict[str, object]] = []
    workflows = root / ".github" / "workflows"
    paths = sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")])
    if not paths:
        errors.append("NO-WORKFLOWS: .github/workflows/ contains no .yml or .yaml workflow")
        return reports

    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            document = yaml.compose(text)
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            errors.append(f"UNPARSABLE-WORKFLOW: {relative}: {exc}")
            continue

        lines = text.splitlines()
        external: list[dict[str, object]] = []
        for node in _collect_uses(document, relative, errors) if document else []:
            ref = node.value.strip()
            if ref.startswith("."):  # repository-local composite action, nothing to pin
                continue
            action, separator, revision = ref.partition("@")
            if not separator or not SHA_RE.match(revision):
                errors.append(
                    f"MUTABLE-REF: {relative}:{_line(node)}: {ref} is not pinned to a "
                    "full 40-hex commit SHA"
                )
                continue
            comment = _trailing_comment(lines, node)
            if not comment:
                errors.append(
                    f"MISSING-VERSION-COMMENT: {relative}:{_line(node)}: {action}@{revision} "
                    "has no adjacent ' # <version>' comment"
                )
                continue
            external.append(
                {"action": action, "line": _line(node), "sha": revision, "version": comment}
            )
        reports.append({"path": relative, "external_uses": external})
    return reports


def _permissions(node: object) -> dict[str, str]:
    """Return a declared ``permissions:`` mapping; anything else reads as undeclared."""
    declared = node.get("permissions") if isinstance(node, dict) else None
    if not isinstance(declared, dict):
        return {}
    return {str(key): str(value) for key, value in declared.items()}


def _check_publish_permissions(root: Path, errors: list[str]) -> dict[str, dict[str, str]]:
    """Require publish.yml to keep exactly the documented job set and permissions."""
    path = root / PUBLISH_PATH
    if not path.exists():
        errors.append(f"MISSING-PUBLISH-WORKFLOW: {PUBLISH_PATH} is required")
        return {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        errors.append(f"UNPARSABLE-PUBLISH-WORKFLOW: {PUBLISH_PATH}: {exc}")
        return {}

    document = document if isinstance(document, dict) else {}
    jobs = document.get("jobs") if isinstance(document.get("jobs"), dict) else {}

    # A renamed or added release job must be reviewed here, never inherit silently.
    expected_jobs = set(PUBLISH_PERMISSIONS) - {""}
    for job_id in sorted(expected_jobs.symmetric_difference(jobs)):
        code = "UNEXPECTED-PUBLISH-JOB" if job_id in jobs else "MISSING-PUBLISH-JOB"
        errors.append(
            f"{code}: {PUBLISH_PATH}: job {job_id!r}; the release job set must be exactly "
            f"{sorted(expected_jobs)}"
        )

    observed: dict[str, dict[str, str]] = {}
    for job_id, expected in PUBLISH_PERMISSIONS.items():
        if job_id and job_id not in jobs:
            continue
        observed[job_id] = _permissions(document if not job_id else jobs[job_id])
        if observed[job_id] != expected:
            errors.append(
                f"PUBLISH-PERMISSIONS: {PUBLISH_PATH}: {f'job {job_id!r}' if job_id else 'workflow'}"
                f" permissions must be exactly {expected or 'inherited (none declared)'}; "
                f"found {observed[job_id] or 'none'}"
            )
    return observed


class SecurityReport(TypedDict):
    errors: list[str]
    ok: bool
    publish_permissions: dict[str, dict[str, str]]
    workflows: list[dict[str, object]]


def check_workflow_security(root: Path) -> SecurityReport:
    """Return a machine-readable report for both workflow security invariants."""
    errors: list[str] = []
    flows = _check_action_pins(root, errors)
    perms = _check_publish_permissions(root, errors)
    return {"errors": errors, "ok": not errors, "publish_permissions": perms, "workflows": flows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Action pins and publish permissions.")
    parser.add_argument("--root", default=".", help="Repository root to inspect (default: .).")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Format.")
    args = parser.parse_args(argv)

    report = check_workflow_security(Path(args.root).resolve())
    errors = report["errors"]

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif not errors:
        print("workflow-security-gate: OK")

    if errors:
        print("workflow-security-gate: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(RECOVERY, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
