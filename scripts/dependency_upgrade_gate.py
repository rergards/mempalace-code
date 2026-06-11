#!/usr/bin/env python3
"""
dependency_upgrade_gate.py — Audited dependency-upgrade gate.

Subcommands:
  audit          Enumerate direct deps, query advisories for current and target
                 versions, run fresh resolver audits, and write a public report.
  verify-report  Re-check a written report against the current workspace files.
  ci-check       CI enforcement: require a fresh successful report when
                 pyproject.toml or uv.lock changed from a given git base ref;
                 pass cleanly when neither file changed.

Stdlib-only — no project imports, no third-party dependencies.

Report location: docs/dependency-upgrade-reports/<slug>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

REPORT_DIR = "docs/dependency-upgrade-reports"
OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
SCHEMA_VERSION = 1
_ALL_ZEROS_SHA = "0" * 40

# ── Package-name helpers ───────────────────────────────────────────────────────

_DEP_SPEC_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)", re.DOTALL)


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_dep_spec(dep: str) -> tuple[str, str]:
    """Split 'lancedb>=0.20' into ('lancedb', '>=0.20').

    Returns (raw_name, specifier_string).
    """
    m = _DEP_SPEC_RE.match(dep.strip())
    if not m:
        raise ValueError(f"Cannot parse dependency specifier: {dep!r}")
    return m.group(1), m.group(2).strip()


# ── Pyproject parsing ──────────────────────────────────────────────────────────


def _parse_pyproject(pyproject_path: Path) -> dict:
    """Return structured direct-dependency info from pyproject.toml.

    Returned dict:
      {
        "runtime": [(name, specifier), ...],
        "dev": [(name, specifier), ...],   # deduplicated union of dep-groups and optional-deps
        "extras": {extra_name: [(name, specifier), ...], ...},
      }
    """
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)

    project = data.get("project", {})
    dep_groups = data.get("dependency-groups", {})
    optional_deps = project.get("optional-dependencies", {})

    # Runtime: [project].dependencies
    runtime = [_parse_dep_spec(d) for d in project.get("dependencies", [])]

    # Dev: union of [dependency-groups].dev and [project.optional-dependencies].dev
    raw_dev: list[str] = []
    for entry in dep_groups.get("dev", []):
        if isinstance(entry, str):
            raw_dev.append(entry)
    for entry in optional_deps.get("dev", []):
        if isinstance(entry, str):
            raw_dev.append(entry)
    seen_dev: set[str] = set()
    dev: list[tuple[str, str]] = []
    for d in raw_dev:
        name, spec = _parse_dep_spec(d)
        norm = _normalize_name(name)
        if norm not in seen_dev:
            seen_dev.add(norm)
            dev.append((name, spec))

    # Optional extras (excluding dev)
    extras: dict[str, list[tuple[str, str]]] = {}
    for extra_name, entries in optional_deps.items():
        if extra_name == "dev":
            continue
        extras[extra_name] = [_parse_dep_spec(d) for d in entries if isinstance(d, str)]

    return {"runtime": runtime, "dev": dev, "extras": extras}


# ── Lockfile parsing ───────────────────────────────────────────────────────────


def _parse_lockfile(lockfile_path: Path) -> dict[str, str]:
    """Return {normalized_name: version} for every resolved package in uv.lock."""
    with lockfile_path.open("rb") as fh:
        data = tomllib.load(fh)
    return {
        _normalize_name(pkg["name"]): pkg["version"]
        for pkg in data.get("package", [])
        if "version" in pkg
    }


# ── File hashing ───────────────────────────────────────────────────────────────


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


# ── Dependency enumeration ─────────────────────────────────────────────────────


def _enumerate_deps(
    pyproject: dict,
    lock_versions: dict[str, str],
    targets: dict[str, str],
) -> list[dict]:
    """Build a flat list of all direct deps with current/target version info."""
    rows: list[dict] = []

    def _add(group: str, dep_list: list[tuple[str, str]]) -> None:
        for name, specifier in dep_list:
            norm = _normalize_name(name)
            rows.append(
                {
                    "name": name,
                    "normalized_name": norm,
                    "group": group,
                    "specifier": specifier,
                    "current_version": lock_versions.get(norm, "unknown"),
                    "target_version": targets.get(norm),
                }
            )

    _add("runtime", pyproject["runtime"])
    _add("dev", pyproject["dev"])
    for extra_name, dep_list in sorted(pyproject["extras"].items()):
        _add(f"extra:{extra_name}", dep_list)

    return rows


# ── Manifest validation ────────────────────────────────────────────────────────


def _validate_manifest(manifest: dict, pyproject: dict) -> list[str]:
    """Return validation error strings; empty list means the manifest is valid."""
    errors: list[str] = []
    targets: dict = manifest.get("targets", {})
    changed_groups: set[str] = set(manifest.get("changed_groups", []))
    changed_extras: set[str] = set(manifest.get("changed_extras", []))

    # All known direct-dependency normalized names
    all_known: set[str] = {_normalize_name(n) for n, _ in pyproject["runtime"]}
    all_known.update(_normalize_name(n) for n, _ in pyproject["dev"])
    for dep_list in pyproject["extras"].values():
        all_known.update(_normalize_name(n) for n, _ in dep_list)

    target_norms: set[str] = {_normalize_name(k) for k in targets}

    # Reject unknown target packages
    for pkg in targets:
        if _normalize_name(pkg) not in all_known:
            errors.append(f"Unknown direct dependency in targets: {pkg!r}")

    # For every changed group, all deps in that group must have a target
    for group in sorted(changed_groups):
        if group == "runtime":
            dep_list = pyproject["runtime"]
        elif group == "dev":
            dep_list = pyproject["dev"]
        else:
            errors.append(f"Unknown changed group: {group!r}")
            continue
        for name, _ in dep_list:
            if _normalize_name(name) not in target_norms:
                errors.append(f"Missing target for {name!r} in changed group {group!r}")

    # For every changed extra, all deps in that extra must have a target
    for extra in sorted(changed_extras):
        if extra not in pyproject["extras"]:
            errors.append(f"Unknown changed extra: {extra!r}")
            continue
        for name, _ in pyproject["extras"][extra]:
            if _normalize_name(name) not in target_norms:
                errors.append(f"Missing target for {name!r} in changed extra {extra!r}")

    return errors


# ── Advisory querying ──────────────────────────────────────────────────────────


def _default_advisory_querier(queries: list[dict]) -> list[dict]:
    """Query OSV querybatch for advisory hits.

    Each query: {"name": str, "version": str}
    Returns a list of result dicts parallel to queries; each has "vulns" list.
    """
    if not queries:
        return []
    payload = json.dumps(
        {
            "queries": [
                {
                    "package": {"name": q["name"], "ecosystem": "PyPI"},
                    "version": q["version"],
                }
                for q in queries
            ]
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OSV_QUERYBATCH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])
        # Pad with empty results if the API returns fewer than expected
        while len(results) < len(queries):
            results.append({"vulns": []})
        return results
    except urllib.error.URLError as exc:
        print(f"error: OSV query failed: {exc}", file=sys.stderr)
        sys.exit(1)


# ── Resolver audit planning ────────────────────────────────────────────────────


def _plan_resolver_audits(manifest: dict) -> list[list[str]]:
    """Return a list of extras combinations to audit.

    Always includes default install (empty list).
    Includes ["dev"] if "dev" in changed_groups.
    Includes [extra] for each extra in changed_extras.
    """
    plan: list[list[str]] = [[]]  # always audit default install
    changed_groups: set[str] = set(manifest.get("changed_groups", []))
    changed_extras: list[str] = sorted(manifest.get("changed_extras", []))

    if "dev" in changed_groups:
        plan.append(["dev"])

    for extra in changed_extras:
        plan.append([extra])

    return plan


# ── Resolver audit running ─────────────────────────────────────────────────────


def _default_resolver_runner(audit_plan: list[list[str]], root: Path) -> list[dict]:
    """Run a fresh resolver audit in a temp venv for each extras combination.

    Does NOT modify the developer's .venv. Each temp env is discarded after
    the audit regardless of outcome.
    """
    results: list[dict] = []
    for extras in audit_plan:
        extras_label = ",".join(extras) if extras else "(default)"
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_path = Path(tmpdir) / "venv"
            create = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                capture_output=True,
                text=True,
            )
            if create.returncode != 0:
                results.append(
                    {
                        "extras": extras,
                        "status": "failed",
                        "summary": f"venv creation failed for {extras_label}",
                    }
                )
                continue

            pip = venv_path / "bin" / "pip"
            # Install pip-audit inside the temp env (not a project dep)
            subprocess.run(
                [str(pip), "install", "--quiet", "pip-audit"],
                capture_output=True,
            )

            install_spec = f".[{','.join(extras)}]" if extras else "."
            install = subprocess.run(
                [str(pip), "install", "--quiet", install_spec],
                cwd=str(root),
                capture_output=True,
                text=True,
            )
            if install.returncode != 0:
                results.append(
                    {
                        "extras": extras,
                        "status": "failed",
                        "summary": f"install failed for {extras_label}",
                    }
                )
                continue

            pip_audit = venv_path / "bin" / "pip-audit"
            audit_proc = subprocess.run(
                [str(pip_audit), "--format", "json", "--progress-spinner", "off"],
                cwd=str(root),
                capture_output=True,
                text=True,
            )
            status = "success" if audit_proc.returncode == 0 else "failed"
            results.append(
                {
                    "extras": extras,
                    "status": status,
                    "summary": f"resolver audit for {extras_label}: {status}",
                }
            )

    return results


# ── audit command ──────────────────────────────────────────────────────────────


def cmd_audit(
    manifest_path: Path,
    root: Path,
    slug: str | None = None,
    *,
    advisory_querier=None,
    resolver_runner=None,
) -> int:
    """Run the full audit: enumerate deps, query advisories, resolver audits, write report."""
    if advisory_querier is None:
        advisory_querier = _default_advisory_querier
    if resolver_runner is None:
        resolver_runner = _default_resolver_runner

    pyproject_path = root / "pyproject.toml"
    lockfile_path = root / "uv.lock"

    try:
        with manifest_path.open(encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: cannot read manifest: {exc}", file=sys.stderr)
        return 1

    pyproject = _parse_pyproject(pyproject_path)
    lock_versions = _parse_lockfile(lockfile_path)
    targets = {_normalize_name(k): v for k, v in manifest.get("targets", {}).items()}

    # Validate manifest coverage
    errors = _validate_manifest(manifest, pyproject)
    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        return 1

    # Enumerate all direct dependencies
    deps = _enumerate_deps(pyproject, lock_versions, targets)

    # Build advisory queries: current version + target version per dep
    queries: list[dict] = []
    query_meta: list[dict] = []
    for dep in deps:
        norm = dep["normalized_name"]
        if dep["current_version"] != "unknown":
            queries.append({"name": dep["name"], "version": dep["current_version"]})
            query_meta.append({"role": "current", "normalized": norm})
        if dep["target_version"] is not None:
            queries.append({"name": dep["name"], "version": dep["target_version"]})
            query_meta.append({"role": "target", "normalized": norm})

    osv_results = advisory_querier(queries) if queries else []

    # Evaluate advisory results; block on any affected target version
    advisory_blocked = False
    advisory_rows: list[dict] = []
    for i, (q, meta) in enumerate(zip(queries, query_meta, strict=True)):
        result = osv_results[i] if i < len(osv_results) else {"vulns": []}
        advisories = result.get("vulns", [])
        row = {
            "name": q["name"],
            "version": q["version"],
            "role": meta["role"],
            "advisories": [{"id": v["id"]} for v in advisories],
            "status": "affected" if advisories else "clean",
        }
        advisory_rows.append(row)
        if meta["role"] == "target" and advisories:
            for adv in advisories:
                print(
                    f"error: {q['name']}@{q['version']} is affected by advisory {adv['id']}",
                    file=sys.stderr,
                )
            advisory_blocked = True

    if advisory_blocked:
        print(
            "error: target versions blocked by active advisories — no report written",
            file=sys.stderr,
        )
        return 1

    # Plan and run fresh resolver audits
    audit_plan = _plan_resolver_audits(manifest)
    resolver_results = resolver_runner(audit_plan, root)

    resolver_blocked = any(r.get("status") == "failed" for r in resolver_results)

    # Compute report slug from manifest hash when not specified
    if slug is None:
        content = json.dumps(manifest, sort_keys=True).encode("utf-8")
        slug = hashlib.sha256(content).hexdigest()[:16]

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if resolver_blocked else "success",
        "slug": slug,
        "pyproject_hash": _hash_file(pyproject_path),
        "lockfile_hash": _hash_file(lockfile_path),
        "dependencies": deps,
        "advisory_results": advisory_rows,
        "resolver_audits": resolver_results,
    }

    report_dir = root / REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{slug}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if resolver_blocked:
        print(
            f"error: resolver audit failed — report written to {report_path} with status=blocked",
            file=sys.stderr,
        )
        return 1

    print(f"audit passed — report written to {report_path}")
    return 0


# ── verify-report command ──────────────────────────────────────────────────────


def cmd_verify_report(report_path: Path, root: Path) -> int:
    """Re-check a report's schema, file hashes, and audit status."""
    pyproject_path = root / "pyproject.toml"
    lockfile_path = root / "uv.lock"

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: cannot read report {report_path}: {exc}", file=sys.stderr)
        return 1

    errors: list[str] = []

    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unexpected schema_version: {report.get('schema_version')!r}")

    for field in (
        "status",
        "pyproject_hash",
        "lockfile_hash",
        "dependencies",
        "advisory_results",
        "resolver_audits",
    ):
        if field not in report:
            errors.append(f"missing required field: {field!r}")

    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        return 1

    # Hash freshness check
    current_pyproject_hash = _hash_file(pyproject_path)
    current_lockfile_hash = _hash_file(lockfile_path)

    if report["pyproject_hash"] != current_pyproject_hash:
        errors.append(
            f"pyproject.toml hash mismatch: report has {report['pyproject_hash']!r}, "
            f"workspace has {current_pyproject_hash!r}"
        )
    if report["lockfile_hash"] != current_lockfile_hash:
        errors.append(
            f"uv.lock hash mismatch: report has {report['lockfile_hash']!r}, "
            f"workspace has {current_lockfile_hash!r}"
        )

    if report["status"] != "success":
        errors.append(f"report status is {report['status']!r}, expected 'success'")

    # Check no advisory-blocked targets survived
    for row in report.get("advisory_results", []):
        if row.get("role") == "target" and row.get("status") == "affected":
            errors.append(
                f"report contains advisory-blocked target: {row['name']}@{row['version']}"
            )

    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        return 1

    print(f"report verified successfully: {report_path}")
    return 0


# ── Git utilities ──────────────────────────────────────────────────────────────


def _default_git_runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _check_dep_files_changed(
    base_ref: str,
    root: Path,
    git_runner,
) -> bool | None:
    """Return True if pyproject.toml or uv.lock changed from base_ref.

    Returns None when the base ref cannot be resolved (e.g., all-zeros SHA on a
    force-push, or an unresolvable ref), which signals the caller to fail closed.
    """
    if base_ref == _ALL_ZEROS_SHA:
        return None

    resolve = git_runner(["rev-parse", "--verify", base_ref], root)
    if resolve.returncode != 0:
        return None

    result = git_runner(
        ["diff", "--name-only", base_ref, "--", "pyproject.toml", "uv.lock"],
        root,
    )
    if result.returncode != 0:
        return None

    changed = set(result.stdout.strip().splitlines())
    return bool(changed & {"pyproject.toml", "uv.lock"})


# ── ci-check command ───────────────────────────────────────────────────────────


def cmd_ci_check(base_ref: str, root: Path, *, git_runner=None) -> int:
    """Enforce that pyproject.toml/uv.lock changes are covered by a fresh report."""
    if git_runner is None:
        git_runner = _default_git_runner

    changed = _check_dep_files_changed(base_ref, root, git_runner)

    if changed is None:
        # Unresolvable base ref — fail closed so broken refs never bypass the gate
        print(
            f"warning: cannot resolve base ref {base_ref!r} — "
            "treating dependency files as changed (fail-closed)",
            file=sys.stderr,
        )
        changed = True

    if not changed:
        print("ci-check passed: dependency files unchanged from base ref")
        return 0

    # Dependency files changed — require exactly one fresh successful report
    report_dir = root / REPORT_DIR
    if not report_dir.exists():
        print(
            f"error: dependency files changed but no report directory at {REPORT_DIR}",
            file=sys.stderr,
        )
        return 1

    reports = sorted(report_dir.glob("*.json"))
    if not reports:
        print(
            f"error: dependency files changed but no reports found in {REPORT_DIR}",
            file=sys.stderr,
        )
        return 1

    current_pyproject_hash = _hash_file(root / "pyproject.toml")
    current_lockfile_hash = _hash_file(root / "uv.lock")

    matching: list[Path] = []
    for rp in reports:
        try:
            report = json.loads(rp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            report.get("pyproject_hash") == current_pyproject_hash
            and report.get("lockfile_hash") == current_lockfile_hash
        ):
            matching.append(rp)

    if len(matching) == 0:
        print(
            f"error: dependency files changed but no report matches current file hashes "
            f"in {REPORT_DIR}",
            file=sys.stderr,
        )
        return 1

    if len(matching) > 1:
        print(
            f"error: multiple reports match current file hashes in {REPORT_DIR}: "
            f"{[str(p) for p in matching]}",
            file=sys.stderr,
        )
        return 1

    return cmd_verify_report(matching[0], root)


# ── CLI entry point ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None, **injected) -> int:
    parser = argparse.ArgumentParser(
        prog="dependency_upgrade_gate",
        description="Audited dependency-upgrade gate.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Run advisory and resolver audit.")
    p_audit.add_argument("--manifest", required=True, help="Target manifest JSON path.")
    p_audit.add_argument(
        "--slug", default=None, help="Report slug (derived from manifest hash if omitted)."
    )
    p_audit.add_argument("--root", default=".", help="Repository root (default: cwd).")

    p_verify = sub.add_parser("verify-report", help="Verify a written dependency-upgrade report.")
    p_verify.add_argument("report", help="Path to the report JSON file.")
    p_verify.add_argument("--root", default=".", help="Repository root (default: cwd).")

    p_ci = sub.add_parser(
        "ci-check", help="CI enforcement gate: require a fresh report when dep files changed."
    )
    p_ci.add_argument(
        "--base-ref",
        required=True,
        help=(
            "Git ref to diff against. Pass github.event.pull_request.base.sha on "
            "pull_request, github.event.before on push."
        ),
    )
    p_ci.add_argument("--root", default=".", help="Repository root (default: cwd).")

    args = parser.parse_args(argv)

    if args.command == "audit":
        return cmd_audit(
            manifest_path=Path(args.manifest),
            root=Path(args.root).resolve(),
            slug=args.slug,
            advisory_querier=injected.get("advisory_querier"),
            resolver_runner=injected.get("resolver_runner"),
        )
    if args.command == "verify-report":
        return cmd_verify_report(
            report_path=Path(args.report),
            root=Path(args.root).resolve(),
        )
    # ci-check
    return cmd_ci_check(
        base_ref=args.base_ref,
        root=Path(args.root).resolve(),
        git_runner=injected.get("git_runner"),
    )


if __name__ == "__main__":
    sys.exit(main())
