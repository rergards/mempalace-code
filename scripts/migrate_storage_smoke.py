#!/usr/bin/env python3
"""
migrate_storage_smoke.py — Disposable release-check smoke for migrate-storage.

Requires the [chroma] extra:
    pip install 'mempalace-code[chroma]'

Usage:
    python scripts/migrate_storage_smoke.py --rows 3
    python scripts/migrate_storage_smoke.py --rows 1
    python scripts/migrate_storage_smoke.py --exercise-dst-guard

All temporary artifacts live inside a TemporaryDirectory and are removed on exit.
No repository files are written.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import subprocess
import sys
import tempfile

MARKER_PREFIX = "smoke_migrate_marker"
_EMBED_DIM = 384


def _det_embed(text: str) -> list[float]:
    """Deterministic embedding from token hashing — no model download required."""
    vec = [0.0] * _EMBED_DIM
    for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        idx = int.from_bytes(digest[:2], "little") % _EMBED_DIM
        vec[idx] += 1.0 if digest[2] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _check_chroma() -> None:
    """Exit with install hint if the [chroma] extra is not present."""
    try:
        import chromadb  # noqa: F401
    except ImportError:
        print(
            "Error: chromadb is not installed. Install with: pip install 'mempalace-code[chroma]'",
            file=sys.stderr,
        )
        sys.exit(1)


def _seed_chroma_source(path: str, n_rows: int) -> None:
    """Create a tiny ChromaDB source palace with deterministic fixture content.

    Supplies explicit embeddings so Chroma's default embedding function is never
    called — the source fixture is created without any model download.
    """
    import chromadb

    os.makedirs(path, exist_ok=True)
    client = chromadb.PersistentClient(path=path)
    col = client.get_or_create_collection(
        "mempalace_drawers",
        embedding_function=None,  # BYO embeddings — avoids Chroma model download
    )
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    embeddings: list[list[float]] = []
    for i in range(n_rows):
        ids.append(f"smoke_row_{i}")
        doc = f"{MARKER_PREFIX} row {i}: unique fixture content for smoke migration test"
        docs.append(doc)
        metas.append({"wing": "smoke", "room": "general", "source_file": f"smoke_{i}.md"})
        embeddings.append(_det_embed(doc))
    col.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    """Run the mempalace_code CLI as a subprocess with version checks disabled."""
    env = os.environ.copy()
    env["MEMPALACE_VERSION_CHECK"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "mempalace_code.cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


def _parse_counts(output: str) -> tuple[int, int] | None:
    """Parse 'Source drawers: N  Destination drawers: M' from CLI output."""
    m = re.search(r"Source drawers:\s*(\d+)\s+Destination drawers:\s*(\d+)", output)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def smoke_happy_path(n_rows: int, work_dir: str) -> None:
    """Seed Chroma source → run migrate-storage CLI → verify counts and search."""
    src = os.path.join(work_dir, "chroma_src")
    dst = os.path.join(work_dir, "lance_dst")
    backup_dir = os.path.join(work_dir, "backups")

    print(f"[smoke] seeding {n_rows} row(s) into Chroma source ...")
    _seed_chroma_source(src, n_rows)

    print("[smoke] running migrate-storage CLI ...")
    result = _run_cli(
        [
            "migrate-storage",
            src,
            dst,
            "--backup-dir",
            backup_dir,
            "--verify",
        ]
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        print(f"[smoke] FAIL: migrate-storage exited {result.returncode}", file=sys.stderr)
        print(output, file=sys.stderr)
        sys.exit(1)

    print(f"[smoke] CLI output: {output.strip()}")

    counts = _parse_counts(output)
    if counts is None:
        print(
            f"[smoke] FAIL: count line not found in CLI output: {output!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    src_count, dst_count = counts
    print(f"[smoke] counts: source={src_count} destination={dst_count}")

    if src_count != n_rows:
        print(f"[smoke] FAIL: source={src_count} expected {n_rows}", file=sys.stderr)
        sys.exit(1)
    if dst_count != n_rows:
        print(f"[smoke] FAIL: destination={dst_count} expected {n_rows}", file=sys.stderr)
        sys.exit(1)

    print("[smoke] searching migrated palace for unique marker ...")
    search_result = _run_cli(["--palace", dst, "search", MARKER_PREFIX])
    search_output = search_result.stdout + search_result.stderr
    if MARKER_PREFIX not in search_output:
        print(
            f"[smoke] FAIL: marker not found in search output: {search_output!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    print("[smoke] search: marker found in migrated palace")
    print(f"[smoke] PASS: source={src_count} destination={dst_count} search=ok")


def smoke_dst_guard(work_dir: str) -> None:
    """Verify migrate-storage refuses a non-empty destination without --force."""
    src_a = os.path.join(work_dir, "chroma_src_a")
    src_b = os.path.join(work_dir, "chroma_src_b")
    dst = os.path.join(work_dir, "lance_dst")
    backup_dir = os.path.join(work_dir, "backups")

    # Pre-populate the Lance destination via a migration with --force so the guard
    # test has a non-empty target to refuse. Using the CLI (not LanceStore.add)
    # keeps the guard test free of direct embedding model calls.
    print("[smoke] seeding Chroma source A (1 row) to pre-populate destination ...")
    _seed_chroma_source(src_a, 1)

    result_a = _run_cli(["migrate-storage", src_a, dst, "--backup-dir", backup_dir, "--force"])
    if result_a.returncode != 0:
        output_a = result_a.stdout + result_a.stderr
        print(f"[smoke] FAIL: pre-population migration failed: {output_a}", file=sys.stderr)
        sys.exit(1)

    # LanceStore.count() only reads the row-count metadata — no embedder needed.
    from mempalace_code.storage import LanceStore

    pre_count = LanceStore(dst, create=False).count()
    print(f"[smoke] Lance destination pre-populated: {pre_count} row(s)")

    print("[smoke] seeding Chroma source B (2 rows) for guard test ...")
    _seed_chroma_source(src_b, 2)

    print("[smoke] running migrate-storage without --force (expect failure) ...")
    result_b = _run_cli(["migrate-storage", src_b, dst, "--backup-dir", backup_dir])
    output_b = result_b.stdout + result_b.stderr
    print(f"[smoke] CLI exit={result_b.returncode} output: {output_b.strip()}")

    if result_b.returncode == 0:
        print("[smoke] FAIL: expected non-zero exit for non-empty dst", file=sys.stderr)
        sys.exit(1)
    if "already contains rows" not in output_b:
        print(
            f"[smoke] FAIL: 'already contains rows' not in output: {output_b!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    after_count = LanceStore(dst, create=False).count()
    if after_count != pre_count:
        print(
            f"[smoke] FAIL: dst count changed from {pre_count} to {after_count}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[smoke] guard-ok: dst count unchanged at {after_count}")
    print("[smoke] PASS: destination guard verified")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Disposable release-check smoke for migrate-storage CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/migrate_storage_smoke.py --rows 3
  python scripts/migrate_storage_smoke.py --rows 1
  python scripts/migrate_storage_smoke.py --exercise-dst-guard

All artifacts are removed from a temporary directory on exit.
""",
    )

    def _positive_int(v: str) -> int:
        i = int(v)
        if i < 1:
            raise argparse.ArgumentTypeError(f"{v!r} is not a positive integer (must be >= 1)")
        return i

    parser.add_argument(
        "--rows",
        type=_positive_int,
        default=3,
        help="Number of rows to seed in the Chroma source palace (default: 3, minimum: 1)",
    )
    parser.add_argument(
        "--exercise-dst-guard",
        action="store_true",
        help="Run the non-empty destination refusal check instead of the happy-path smoke",
    )
    args = parser.parse_args()

    _check_chroma()

    with tempfile.TemporaryDirectory(prefix="mempalace_smoke_migrate_") as work_dir:
        print(f"[smoke] work dir: {work_dir}")
        if args.exercise_dst_guard:
            smoke_dst_guard(work_dir)
        else:
            smoke_happy_path(args.rows, work_dir)
    print("[smoke] temporary artifacts removed")


if __name__ == "__main__":
    main()
