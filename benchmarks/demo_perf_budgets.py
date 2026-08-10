#!/usr/bin/env python3
"""
demo_perf_budgets.py — Deterministic synthetic performance budgets.

Measures mine (full + incremental no-op), search, read, and maintenance
(optimize/cleanup) timings against a small, fixed, in-repo fixture project —
never an external repository, never real HuggingFace model weights, never the
network. All work happens inside a disposable temp directory that is removed
before the process exits.

Determinism and offline guarantees:
  - The embedder is a deterministic token-hash function (same scheme as
    tests/conftest.py's ``_DeterministicTestEmbedder``), monkeypatched onto
    ``LanceStore._get_embedder`` before any store is opened.
  - HOME/XDG paths are redirected to a temp tree so a developer's real
    ``~/.mempalace`` config never perturbs scan rules or timings.
  - A socket guard turns any accidental network attempt into an immediate,
    loud failure instead of a hang or a real download.

Usage:
    python benchmarks/demo_perf_budgets.py                 # informational report (text)
    python benchmarks/demo_perf_budgets.py --json           # informational report (JSON)
    python benchmarks/demo_perf_budgets.py --check --ci     # hard budget gate (CI)
    python benchmarks/demo_perf_budgets.py --update-baseline --reason "..."
                                                              # regenerate the committed artifact

Only ``--check --ci`` together enforce the committed hard budgets and return a
non-zero exit code on breach, missing metrics, or a malformed artifact. Every
other invocation is informational only and always exits 0 on a successful
measurement run.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import re
import socket
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "benchmarks" / "demo_perf_budgets.json"
SCHEMA_VERSION = 1

_EMBED_DIM = 384


# ─── Deterministic embedder (no network, no model download) ──────────────────


class _DeterministicBenchEmbedder:
    """Token-hash embedder — same scheme as tests/conftest.py's test embedder."""

    def ndims(self) -> int:
        return _EMBED_DIM

    def compute_source_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * _EMBED_DIM
        for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
            idx = int.from_bytes(digest[:2], "little") % _EMBED_DIM
            vec[idx] += 1.0 if digest[2] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


@contextlib.contextmanager
def _deterministic_embedder():
    from mempalace_code.storage import LanceStore

    orig = LanceStore._get_embedder
    LanceStore._get_embedder = lambda _self: _DeterministicBenchEmbedder()
    try:
        yield
    finally:
        LanceStore._get_embedder = orig


# ─── Socket guard — any accidental network attempt fails loudly ──────────────


class NetworkBlockedError(OSError):
    """Raised when the benchmark's socket guard intercepts an outbound connection."""


@contextlib.contextmanager
def _socket_guard():
    orig_create_connection = socket.create_connection
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex

    def _blocked_create_connection(address, *_a, **_k):
        raise NetworkBlockedError(
            f"demo_perf_budgets guard: network blocked (connect to {address})"
        )

    def _blocked_connect(_self, address):
        raise NetworkBlockedError(
            f"demo_perf_budgets guard: network blocked (connect to {address})"
        )

    def _blocked_connect_ex(_self, address):
        raise NetworkBlockedError(
            f"demo_perf_budgets guard: network blocked (connect_ex to {address})"
        )

    socket.create_connection = _blocked_create_connection
    socket.socket.connect = _blocked_connect
    socket.socket.connect_ex = _blocked_connect_ex
    try:
        yield
    finally:
        socket.create_connection = orig_create_connection
        socket.socket.connect = orig_connect
        socket.socket.connect_ex = orig_connect_ex


# ─── Isolated HOME/XDG env — a real ~/.mempalace config must never leak in ────


@contextlib.contextmanager
def _isolated_env(tmp_root: Path):
    home = tmp_root / "home"
    xdg_cache = tmp_root / "xdg_cache"
    xdg_config = tmp_root / "xdg_config"
    xdg_data = tmp_root / "xdg_data"
    for d in (home, xdg_cache, xdg_config, xdg_data):
        d.mkdir(parents=True, exist_ok=True)

    overrides = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(xdg_data),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "MEMPALACE_VERSION_CHECK": "0",
        "MEMPALACE_DISK_MIN_FREE_BYTES": "1",
    }
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ─── Fixture — fixed, in-repo content only; no external repository path ──────

_APP_PY_LINES = [
    '"""Deterministic perf-budget fixture module."""',
    "",
    "",
    "def compute_budget_marker_alpha(value):",
    '    """Doubles value; unique marker budget_marker_alpha anchors this chunk '
    'for search/read proof."""',
    "    return value * 2",
    "",
    "",
    "def helper_budget_offset(value):",
    '    """Adds one; keeps the module above the chunker\'s minimum-size threshold."""',
    "    return value + 1",
    "",
]

_NOTES_MD = (
    "# Performance Budget Fixture Notes\n"
    "\n"
    "This fixture proves mine, search, read, and maintenance operate on real,\n"
    "deterministic content rather than mocked internals. Marker: budget_marker_beta.\n"
)

_SETTINGS_TOML = (
    "[fixture]\n"
    'name = "perf-budget-fixture"\n'
    'purpose = "prove deterministic mine, search, read, and maintenance timings"\n'
    'marker = "budget_marker_gamma"\n'
)

_SERVICE_GO = (
    "package main\n"
    "\n"
    'import "fmt"\n'
    "\n"
    "// budgetMarkerDelta identifies this file inside the perf-budget fixture.\n"
    "func budgetMarkerDelta() string {\n"
    '\treturn "go-fixture-marker"\n'
    "}\n"
    "\n"
    "func main() {\n"
    "\tfmt.Println(budgetMarkerDelta())\n"
    "}\n"
)

FIXTURE_FILES: dict[str, str] = {
    "app.py": "\n".join(_APP_PY_LINES),
    "NOTES.md": _NOTES_MD,
    "settings.toml": _SETTINGS_TOML,
    "service.go": _SERVICE_GO,
}

_MEMPALACE_YAML = "wing: perf_budget_fixture\nrooms:\n  - name: general\n    description: All perf-budget fixture files\n"

SEARCH_QUERIES = (
    "budget_marker_alpha",
    "budget_marker_beta",
    "budget_marker_gamma",
    "budget_marker_delta",
)
SEARCH_REPEATS_PER_QUERY = 5
READ_REPEATS_PER_TARGET = 5


def build_fixture(project_dir: Path) -> dict[str, Any]:
    """Write the fixed, in-repo fixture project. No external path is ever accepted."""
    project_dir.mkdir(parents=True, exist_ok=True)
    for name, content in FIXTURE_FILES.items():
        (project_dir / name).write_text(content, encoding="utf-8")
    (project_dir / "mempalace.yaml").write_text(_MEMPALACE_YAML, encoding="utf-8")
    total_bytes = sum(len(c.encode("utf-8")) for c in FIXTURE_FILES.values())
    return {
        "files": sorted(FIXTURE_FILES),
        "file_count": len(FIXTURE_FILES),
        "total_bytes": total_bytes,
    }


def _read_targets() -> tuple[tuple[str, int, int], ...]:
    return tuple((name, 1, len(content.splitlines())) for name, content in FIXTURE_FILES.items())


# ─── Latency stats ─────────────────────────────────────────────────────────


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * pct
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)


def _latency_stats(samples_secs: list[float]) -> dict[str, Any]:
    ms = sorted(s * 1000.0 for s in samples_secs)
    return {
        "samples": len(ms),
        "median_ms": statistics.median(ms),
        "p95_ms": _percentile(ms, 0.95),
        "max_ms": max(ms),
    }


# ─── Measured surfaces ──────────────────────────────────────────────────────


def measure_mine_full(project_dir: Path, palace_dir: Path) -> dict[str, Any]:
    from mempalace_code.mining.orchestrator import mine

    t0 = time.perf_counter()
    result = mine(str(project_dir), str(palace_dir), incremental=False, skip_optimize=True)
    elapsed = time.perf_counter() - t0
    return {
        "elapsed_secs": elapsed,
        "drawers_filed": result["drawers_filed"],
        "files_processed": result["files_processed"],
    }


def measure_mine_incremental_noop(project_dir: Path, palace_dir: Path) -> dict[str, Any]:
    from mempalace_code.mining.orchestrator import mine

    t0 = time.perf_counter()
    result = mine(str(project_dir), str(palace_dir), incremental=True, skip_optimize=True)
    elapsed = time.perf_counter() - t0
    if result["drawers_filed"] != 0:
        raise RuntimeError(
            f"incremental no-op mine expected drawers_filed == 0, got {result['drawers_filed']}"
        )
    return {
        "elapsed_secs": elapsed,
        "drawers_filed": result["drawers_filed"],
        "files_skipped": result["files_skipped"],
    }


def measure_search(palace_dir: Path) -> dict[str, Any]:
    from mempalace_code.searcher import search_memories

    samples: list[float] = []
    for query in SEARCH_QUERIES:
        for _ in range(SEARCH_REPEATS_PER_QUERY):
            t0 = time.perf_counter()
            result = search_memories(query, str(palace_dir), n_results=5)
            samples.append(time.perf_counter() - t0)
            if "error" in result:
                raise RuntimeError(f"search_memories error for {query!r}: {result['error']}")
            if not result.get("results"):
                raise RuntimeError(f"search_memories returned no results for {query!r}")
    return _latency_stats(samples)


def measure_read(palace_dir: Path) -> dict[str, Any]:
    from mempalace_code.reader import read_slice
    from mempalace_code.storage import open_store

    store = open_store(str(palace_dir), create=False, read_only=True)
    samples: list[float] = []
    for name, start, end in _read_targets():
        for _ in range(READ_REPEATS_PER_TARGET):
            t0 = time.perf_counter()
            result = read_slice(store, name, start, end)
            samples.append(time.perf_counter() - t0)
            if "error" in result:
                raise RuntimeError(f"read_slice error for {name}: {result['error']}")
    return _latency_stats(samples)


def measure_maintenance(palace_dir: Path) -> dict[str, Any]:
    from mempalace_code.storage import open_store, optimize_store

    store = open_store(str(palace_dir), create=False)
    t0 = time.perf_counter()
    result = optimize_store(store, str(palace_dir), backup_first=False)
    elapsed = time.perf_counter() - t0
    if not result.ok:
        raise RuntimeError("optimize_store reported ok=False")
    return {"elapsed_secs": elapsed, "ok": result.ok, "supported": result.supported}


def run_measurements() -> dict[str, Any]:
    """Run the full disposable-palace measurement pass. No repo files are touched."""
    with tempfile.TemporaryDirectory(prefix="mempalace_perf_budget_") as tmp:
        tmp_path = Path(tmp)
        project_dir = tmp_path / "project"
        palace_dir = tmp_path / "palace"
        sink = io.StringIO()
        with (
            _isolated_env(tmp_path),
            _socket_guard(),
            _deterministic_embedder(),
            contextlib.redirect_stdout(sink),
        ):
            fixture = build_fixture(project_dir)
            mine_full = measure_mine_full(project_dir, palace_dir)
            mine_incremental_noop = measure_mine_incremental_noop(project_dir, palace_dir)
            search = measure_search(palace_dir)
            read = measure_read(palace_dir)
            maintenance = measure_maintenance(palace_dir)
    return {
        "fixture": fixture,
        "mine_full": mine_full,
        "mine_incremental_noop": mine_incremental_noop,
        "search": search,
        "read": read,
        "maintenance": maintenance,
    }


def _actual_values(measurements: dict[str, Any]) -> dict[str, float]:
    return {
        "mine_full": measurements["mine_full"]["elapsed_secs"],
        "mine_incremental_noop": measurements["mine_incremental_noop"]["elapsed_secs"],
        "search_p95": measurements["search"]["p95_ms"],
        "read_p95": measurements["read"]["p95_ms"],
        "maintenance": measurements["maintenance"]["elapsed_secs"],
    }


# ─── Budget comparison rules ────────────────────────────────────────────────

# actual <= max(floor, baseline * ratio) — a generous floor keeps a near-zero
# baseline from producing an impossible-to-pass budget (ratio * 0 == 0), and
# the ratio absorbs ordinary hosted-runner variance around a real baseline.
DEFAULT_RULES: dict[str, dict[str, Any]] = {
    "mine_full": {
        "unit": "secs",
        "floor": 20.0,
        "ratio": 3.0,
        "comparison": "actual_secs <= max(floor_secs, baseline_secs * ratio)",
    },
    "mine_incremental_noop": {
        "unit": "secs",
        "floor": 2.0,
        "ratio": 4.0,
        "comparison": "actual_secs <= max(floor_secs, baseline_secs * ratio)",
    },
    "search_p95": {
        "unit": "ms",
        "floor": 200.0,
        "ratio": 5.0,
        "comparison": "actual_p95_ms <= max(floor_ms, baseline_p95_ms * ratio)",
    },
    "read_p95": {
        "unit": "ms",
        "floor": 100.0,
        "ratio": 5.0,
        "comparison": "actual_p95_ms <= max(floor_ms, baseline_p95_ms * ratio)",
    },
    "maintenance": {
        "unit": "secs",
        "floor": 5.0,
        "ratio": 5.0,
        "comparison": "actual_secs <= max(floor_secs, baseline_secs * ratio)",
    },
}
METRIC_NAMES: tuple[str, ...] = tuple(DEFAULT_RULES)


def budget_for(baseline: float, floor: float, ratio: float) -> float:
    return max(floor, baseline * ratio)


def evaluate_metric(name: str, actual: float, baseline: float, floor: float, ratio: float) -> dict:
    budget = budget_for(baseline, floor, ratio)
    return {
        "name": name,
        "actual": actual,
        "baseline": baseline,
        "floor": floor,
        "ratio": ratio,
        "budget": budget,
        "passed": actual <= budget,
    }


def _budget_rows(measurements: dict[str, Any], artifact: dict[str, Any]) -> list[dict]:
    actuals = _actual_values(measurements)
    return [
        evaluate_metric(
            name,
            actuals[name],
            artifact["metrics"][name]["baseline"],
            artifact["metrics"][name]["floor"],
            artifact["metrics"][name]["ratio"],
        )
        for name in METRIC_NAMES
    ]


# ─── Artifact schema + validation ───────────────────────────────────────────


def validate_artifact(data: Any) -> list[str]:
    """Return a list of shape errors; empty means the artifact is well-formed."""
    errors: list[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    require(isinstance(data, dict), "artifact root must be a JSON object")
    if not isinstance(data, dict):
        return errors

    require(
        data.get("schema_version") == SCHEMA_VERSION, f"schema_version must equal {SCHEMA_VERSION}"
    )

    bcb = data.get("budget_changed_because")
    require(
        isinstance(bcb, str) and bcb.strip() != "",
        "budget_changed_because must be a non-empty string",
    )

    fixture = data.get("fixture")
    require(isinstance(fixture, dict), "fixture must be an object")
    if isinstance(fixture, dict):
        require(
            isinstance(fixture.get("files"), list) and len(fixture["files"]) > 0,
            "fixture.files must be a non-empty list",
        )
        require(
            isinstance(fixture.get("file_count"), int) and fixture.get("file_count", -1) > 0,
            "fixture.file_count must be a positive int",
        )
        require(
            isinstance(fixture.get("total_bytes"), int) and fixture.get("total_bytes", -1) >= 0,
            "fixture.total_bytes must be a non-negative int",
        )

    metrics = data.get("metrics")
    require(isinstance(metrics, dict), "metrics must be an object")
    if isinstance(metrics, dict):
        for name in METRIC_NAMES:
            m = metrics.get(name)
            if m is None:
                errors.append(f"metrics.{name} is required")
                continue
            if not isinstance(m, dict):
                errors.append(f"metrics.{name} must be an object")
                continue
            require(m.get("unit") in ("secs", "ms"), f"metrics.{name}.unit must be 'secs' or 'ms'")
            baseline = m.get("baseline")
            require(
                isinstance(baseline, (int, float))
                and not isinstance(baseline, bool)
                and baseline >= 0,
                f"metrics.{name}.baseline must be a non-negative number",
            )
            before = m.get("before")
            require(
                before is None
                or (isinstance(before, (int, float)) and not isinstance(before, bool)),
                f"metrics.{name}.before must be null or a number",
            )
            floor = m.get("floor")
            require(
                isinstance(floor, (int, float)) and not isinstance(floor, bool) and floor >= 0,
                f"metrics.{name}.floor must be a non-negative number",
            )
            ratio = m.get("ratio")
            require(
                isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and ratio >= 1,
                f"metrics.{name}.ratio must be a number >= 1",
            )
            require(
                isinstance(m.get("comparison"), str) and m.get("comparison", "").strip() != "",
                f"metrics.{name}.comparison must be a non-empty string",
            )

    return errors


def load_and_validate_artifact(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and validate the committed budget artifact. Fails closed on any problem."""
    if not path.exists():
        return None, [f"budget artifact missing: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"budget artifact malformed JSON: {exc}"]
    errors = validate_artifact(data)
    if errors:
        return None, errors
    return data, []


# ─── Reporting ───────────────────────────────────────────────────────────────


def render_text_report(measurements: dict[str, Any], budget_rows: list[dict] | None) -> str:
    fixture = measurements["fixture"]
    mine_full = measurements["mine_full"]
    mine_inc = measurements["mine_incremental_noop"]
    search = measurements["search"]
    read = measurements["read"]
    maint = measurements["maintenance"]

    lines = [
        "MemPalace Demo Performance Budgets",
        "=" * 55,
        f"Fixture files: {fixture['file_count']} ({fixture['total_bytes']} bytes)",
        "",
        f"mine (full):        {mine_full['elapsed_secs']:.4f}s ({mine_full['drawers_filed']} drawers)",
        f"mine (incremental): {mine_inc['elapsed_secs']:.4f}s (files_skipped={mine_inc['files_skipped']})",
        f"search:             median={search['median_ms']:.2f}ms p95={search['p95_ms']:.2f}ms "
        f"max={search['max_ms']:.2f}ms (n={search['samples']})",
        f"read:               median={read['median_ms']:.2f}ms p95={read['p95_ms']:.2f}ms "
        f"max={read['max_ms']:.2f}ms (n={read['samples']})",
        f"maintenance:        {maint['elapsed_secs']:.4f}s (ok={maint['ok']})",
    ]

    if budget_rows is not None:
        lines.append("")
        lines.append("Budget comparison (informational unless --check --ci):")
        for row in budget_rows:
            status = "PASS" if row["passed"] else "FAIL"
            lines.append(
                f"  [{status}] {row['name']}: actual={row['actual']:.4f} budget={row['budget']:.4f} "
                f"(baseline={row['baseline']:.4f} floor={row['floor']} ratio={row['ratio']})"
            )

    return "\n".join(lines)


# ─── CLI entry points ────────────────────────────────────────────────────────


def _run_informational(as_json: bool) -> int:
    measurements = run_measurements()
    rows: list[dict] | None = None
    if ARTIFACT_PATH.exists():
        try:
            artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            artifact = None
        if isinstance(artifact, dict) and not validate_artifact(artifact):
            rows = _budget_rows(measurements, artifact)

    if as_json:
        payload: dict[str, Any] = {"measurements": measurements}
        if rows is not None:
            payload["budget_rows"] = rows
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_text_report(measurements, rows))
    return 0


def _run_check() -> int:
    artifact, errors = load_and_validate_artifact(ARTIFACT_PATH)
    if errors:
        print("demo-perf-budgets: FAIL — budget artifact invalid", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    assert artifact is not None

    measurements = run_measurements()
    rows = _budget_rows(measurements, artifact)
    print(render_text_report(measurements, rows))

    failed = [r for r in rows if not r["passed"]]
    if failed:
        print("", file=sys.stderr)
        print("demo-perf-budgets: FAIL", file=sys.stderr)
        for r in failed:
            print(
                f"  - {r['name']}: actual {r['actual']:.4f} exceeds budget {r['budget']:.4f}",
                file=sys.stderr,
            )
        return 1

    print("")
    print("demo-perf-budgets: OK")
    return 0


def _run_update_baseline(reason: str) -> int:
    measurements = run_measurements()
    actuals = _actual_values(measurements)

    prev: dict[str, Any] | None = None
    if ARTIFACT_PATH.exists():
        try:
            loaded = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
            prev = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            prev = None

    metrics: dict[str, Any] = {}
    for name in METRIC_NAMES:
        prev_metric = prev.get("metrics", {}).get(name) if isinstance(prev, dict) else None
        floor = (prev_metric or {}).get("floor", DEFAULT_RULES[name]["floor"])
        ratio = (prev_metric or {}).get("ratio", DEFAULT_RULES[name]["ratio"])
        before = (prev_metric or {}).get("baseline")
        metrics[name] = {
            "unit": DEFAULT_RULES[name]["unit"],
            "baseline": actuals[name],
            "before": before,
            "floor": floor,
            "ratio": ratio,
            "comparison": DEFAULT_RULES[name]["comparison"],
        }

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "budget_changed_because": reason.strip(),
        "fixture": measurements["fixture"],
        "metrics": metrics,
    }
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {ARTIFACT_PATH.relative_to(ROOT).as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic synthetic performance budgets for mine/search/read/maintenance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the informational report as JSON."
    )
    parser.add_argument(
        "--check", action="store_true", help="Enforce the committed hard budgets (requires --ci)."
    )
    parser.add_argument(
        "--ci", action="store_true", help="Required alongside --check to run the hard CI gate."
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Measure and rewrite the committed artifact's baseline (requires --reason).",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Rationale for --update-baseline (becomes budget_changed_because).",
    )
    args = parser.parse_args(argv)

    if args.check and not args.ci:
        parser.error(
            "--check requires --ci (run: python benchmarks/demo_perf_budgets.py --check --ci)"
        )
    if args.update_baseline and not args.reason.strip():
        parser.error('--update-baseline requires --reason "..."')

    if args.update_baseline:
        return _run_update_baseline(args.reason)
    if args.check:
        return _run_check()
    return _run_informational(as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
