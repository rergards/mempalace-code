#!/usr/bin/env python3
"""release_readiness_gate.py — Orchestrate the complete release-readiness check.

One command that runs the canonical gate inventory, builds artifacts in a
controlled output directory, runs twine check, artifact member inspection, and
installed smoke, then exits nonzero on any failed row.

Usage:
    python scripts/release_readiness_gate.py --check --json
    python scripts/release_readiness_gate.py --artifact-only --json
    python scripts/release_readiness_gate.py --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE_NAME = "mempalace-code"
DEFAULT_TIMEOUT = 120

# ── Loader helpers ─────────────────────────────────────────────────────────────


def _load_sibling(name: str, script_name: str):
    path = Path(__file__).resolve().parent / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Gate row ──────────────────────────────────────────────────────────────────


def _make_row(gate_id: str, command: str, status: str, detail: str) -> dict:
    return {
        "id": gate_id,
        "command": command,
        "status": status,
        "detail": detail,
    }


# ── Inventory check ───────────────────────────────────────────────────────────


def _run_inventory_check(root: Path) -> list[dict]:
    gate_inventory = _load_sibling("_gate_inventory_readiness", "gate_inventory.py")
    errors = gate_inventory.check_parity(root)
    if errors:
        return [
            _make_row(
                "gate_inventory",
                "python scripts/gate_inventory.py --check",
                "fail",
                "; ".join(errors[:5]),
            )
        ]
    return [
        _make_row(
            "gate_inventory",
            "python scripts/gate_inventory.py --check",
            "pass",
            f"{len(gate_inventory.CANONICAL_GATES)} gates, parity ok",
        )
    ]


# ── Artifact build ────────────────────────────────────────────────────────────


def _build_artifacts(root: Path, out_dir: Path) -> tuple[bool, str]:
    """Build wheel and sdist into out_dir. Returns (ok, detail)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(out_dir), str(root)],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            cwd=str(root),
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout)[:500]
        return True, f"built to {out_dir}"
    except FileNotFoundError:
        return False, "build tool not installed (pip install build)"
    except subprocess.TimeoutExpired:
        return False, "build timed out"


# ── Artifact inspection ───────────────────────────────────────────────────────


def _run_artifact_inspection(dist_dir: Path) -> list[dict]:
    rag = _load_sibling("_release_artifact_gate_readiness", "release_artifact_gate.py")
    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=True)
    rows = []
    for row in result["rows"]:
        rows.append(
            _make_row(
                f"artifact_{row['check'].replace('-', '_')}",
                f"artifact-gate:{row['check']}",
                row["status"],
                row["detail"],
            )
        )
    return rows


# ── Install smoke ─────────────────────────────────────────────────────────────


def _run_install_smoke(dist_dir: Path) -> list[dict]:
    """Run venv and pipx install smokes against the built wheel in dist_dir."""
    smoke = _load_sibling("_release_install_smoke_readiness", "release_install_metadata_smoke.py")

    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        error_detail = "no wheel found in dist dir after build"
        return [
            _make_row(
                "install_smoke_venv",
                "python scripts/release_install_metadata_smoke.py --installer venv --install-spec <wheel> --json",
                "error",
                error_detail,
            ),
            _make_row(
                "install_smoke_pipx",
                "python scripts/release_install_metadata_smoke.py --installer pipx --install-spec <wheel> --json",
                "error",
                error_detail,
            ),
        ]

    wheel_path = wheels[0]
    rows = []

    for installer_name, run_fn in [
        ("venv", smoke.run_venv_smoke),
        ("pipx", smoke.run_pipx_smoke),
    ]:
        gate_id = f"install_smoke_{installer_name}"
        command = (
            f"python scripts/release_install_metadata_smoke.py"
            f" --installer {installer_name} --install-spec {wheel_path.name} --json"
        )
        try:
            result = run_fn(
                install_spec=str(wheel_path),
                package=PACKAGE_NAME,
                run_subprocess=smoke._default_run_subprocess,
            )
            if result.ok:
                rows.append(
                    _make_row(gate_id, command, "pass", f"version={result.expected_version}")
                )
            else:
                diag = "; ".join(result.diagnostics[:3])
                rows.append(_make_row(gate_id, command, "fail", diag))
        except Exception as exc:  # noqa: BLE001  # reason: surface smoke failures as gate rows
            rows.append(_make_row(gate_id, command, "error", str(exc)[:300]))

    return rows


# ── Orchestration ──────────────────────────────────────────────────────────────


def run_readiness(
    root: Path,
    *,
    artifact_only: bool = False,
    skip_smoke: bool = False,
) -> dict:
    """Run the full release-readiness check and return a structured result dict."""
    all_rows: list[dict] = []
    ok = True

    if not artifact_only:
        inventory_rows = _run_inventory_check(root)
        all_rows.extend(inventory_rows)
        if any(r["status"] == "fail" for r in inventory_rows):
            ok = False

    with tempfile.TemporaryDirectory(prefix="mempalace-readiness-") as tmpdir:
        dist_dir = Path(tmpdir) / "dist"
        dist_dir.mkdir()

        build_ok, build_detail = _build_artifacts(root, dist_dir)
        all_rows.append(
            _make_row(
                "artifact_build",
                "python -m build",
                "pass" if build_ok else "fail",
                build_detail,
            )
        )
        if not build_ok:
            ok = False
        else:
            artifact_rows = _run_artifact_inspection(dist_dir)
            all_rows.extend(artifact_rows)
            if any(r["status"] == "fail" for r in artifact_rows):
                ok = False

            if not artifact_only and not skip_smoke:
                smoke_rows = _run_install_smoke(dist_dir)
                all_rows.extend(smoke_rows)
                if any(r["status"] not in ("pass", "skip") for r in smoke_rows):
                    ok = False

    return {
        "ok": ok,
        "rows": all_rows,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orchestrate the complete release-readiness check."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the full release-readiness gate (inventory + build + artifact + smoke).",
    )
    parser.add_argument(
        "--artifact-only",
        action="store_true",
        help="Only build artifacts and run artifact inspection (skip inventory and smoke).",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip install smoke check.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )
    args = parser.parse_args(argv)

    if not args.check and not args.artifact_only:
        parser.error("specify --check or --artifact-only")

    root = Path(__file__).resolve().parent.parent

    result = run_readiness(
        root,
        artifact_only=args.artifact_only,
        skip_smoke=args.skip_smoke,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for row in result["rows"]:
            mark = (
                "PASS"
                if row["status"] == "pass"
                else ("SKIP" if row["status"] == "skip" else "FAIL")
            )
            print(f"  [{mark}] {row['id']}: {row['detail']}")
        if result["ok"]:
            passing = sum(1 for r in result["rows"] if r["status"] == "pass")
            print(f"release-readiness-gate: OK ({passing}/{len(result['rows'])} checks passed)")
        else:
            failing = [r["id"] for r in result["rows"] if r["status"] not in ("pass", "skip")]
            print(f"release-readiness-gate: FAIL ({failing})", file=sys.stderr)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
