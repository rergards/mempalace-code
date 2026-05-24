"""mining.orchestrator — Core mine() loop, batch helpers, storage ops, status."""

import hashlib
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import MempalaceConfig
from ..storage import open_store, optimize_store
from ..version import __version__
from .batching import get_batch_size
from .chunkers import MIN_CHUNK, chunk_file
from .kg_extract import (
    _KG_EXTRACT_EXTENSIONS,
    extract_type_relationships,
    parse_dotnet_project_file,
    parse_sln_file,
    parse_xaml_file,
)
from .languages import detect_language
from .projects import _build_csproj_room_map, _detect_sln_wing, detect_room, load_config
from .scanner import get_scan_filter_rules, normalize_include_paths, scan_project
from .symbols import extract_symbol

# =============================================================================
# INCREMENTAL MINING HELPERS
# =============================================================================


def _file_hash(path: Path) -> str:
    """Return blake2b hex digest (32 chars) of raw file bytes."""
    h = hashlib.blake2b(digest_size=16)
    h.update(path.read_bytes())
    return h.hexdigest()


def _bulk_existing_file_hashes(collection, wing: str) -> dict:
    """Return {source_file: source_hash} for all drawers in wing.

    Delegates to collection.get_source_file_hashes() (LanceDB column projection,
    no vector scan). Returns an empty dict on unsupported backends or empty palace.
    """
    result = collection.get_source_file_hashes(wing)
    return result if result is not None else {}


# =============================================================================
# PALACE — storage operations
# =============================================================================


def get_collection(palace_path: str):
    """Open (or create) the drawer store for a palace."""
    os.makedirs(palace_path, exist_ok=True)
    return open_store(palace_path, create=True)


def file_already_mined(collection, source_file: str) -> bool:
    """Fast check: has this file been filed before?"""
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        return len(results.get("ids", [])) > 0
    except Exception:
        return False


def add_drawer(
    collection,
    wing: str,
    room: str,
    content: str,
    source_file: str,
    chunk_index: int,
    agent: str,
    language: str = "unknown",
    symbol_name: str = "",
    symbol_type: str = "",
    markdown_metadata: Optional[dict] = None,
):
    """Add one drawer to the palace."""
    drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((source_file + str(chunk_index)).encode(), usedforsecurity=False).hexdigest()[:16]}"
    try:
        metadata = {
            "wing": wing,
            "room": room,
            "source_file": source_file,
            "chunk_index": chunk_index,
            "added_by": agent,
            "filed_at": datetime.now().isoformat(),
            "language": language,
            "symbol_name": symbol_name,
            "symbol_type": symbol_type,
        }
        if markdown_metadata:
            metadata.update(markdown_metadata)
        collection.add(
            documents=[content],
            ids=[drawer_id],
            metadatas=[metadata],
        )
        return True
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            return False
        raise


# =============================================================================
# BATCH HELPERS
# =============================================================================


def _find_chunk_in_content(content: str, chunk_text: str, cursor: int) -> tuple[int, int]:
    """Find chunk_text in content starting at cursor, matching newlines flexibly.

    The chunker may join blocks with \\n\\n while the source uses a single \\n.
    Splits chunk_text on runs of newlines and joins the escaped parts with \\n+
    so the regex matches both single and double newlines between lines.

    Returns (start, end) positions in content, or (-1, -1) when not found.
    """
    parts = re.split(r"\n+", chunk_text)
    pattern = r"\n+".join(re.escape(p) for p in parts)
    m = re.search(pattern, content[cursor:])
    if m:
        return cursor + m.start(), cursor + m.end()
    return -1, -1


def _collect_specs_for_file(
    filepath: Path,
    project_path: Path,
    collection,
    wing: str,
    rooms: list,
    agent: str,
    mined_files: Optional[set] = None,
    source_hash: str = "",
    csproj_room_map: Optional[dict] = None,
) -> list:
    """Read, chunk, and prepare drawer specs for one file without writing.

    Returns [] if the file is already mined, unreadable, or below MIN_CHUNK.
    Each spec dict has keys: id, content, metadata.
    IDs and filed_at timestamps are set at spec-creation time.

    If *mined_files* is provided (a set of source_file strings pre-fetched for the
    wing), membership is checked in O(1) instead of issuing a per-file LanceDB query.
    Falls back to file_already_mined() when mined_files is None.

    *source_hash* is the blake2b digest of the file bytes (computed once in mine()).
    Stored verbatim on every drawer for incremental change detection.
    """
    source_file = str(filepath)
    if mined_files is not None:
        if source_file in mined_files:
            return []
    elif file_already_mined(collection, source_file):
        return []

    try:
        raw_content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    content = raw_content.strip()
    if len(content) < MIN_CHUNK:
        return []

    # Compute the line offset caused by stripping leading whitespace/newlines.
    # Lines stripped from the start shift all chunk line numbers forward.
    leading = raw_content[: len(raw_content) - len(raw_content.lstrip())]
    _line_offset = leading.count("\n")

    language = detect_language(filepath, content)
    room = detect_room(filepath, content, rooms, project_path, csproj_room_map=csproj_room_map)
    chunks = chunk_file(content, filepath.suffix.lower(), source_file, language=language)

    # Cursor-based exact-match: advance cursor so repeated chunk text maps to distinct positions.
    _cursor = 0

    specs = []
    for chunk in chunks:
        symbol_name = chunk.get("symbol_name")
        symbol_type = chunk.get("symbol_type")
        if symbol_name is None or symbol_type is None:
            symbol_name, symbol_type = extract_symbol(chunk["content"], language)
        drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((source_file + str(chunk['chunk_index'])).encode(), usedforsecurity=False).hexdigest()[:16]}"
        markdown_metadata = chunk.get("markdown_metadata", {})

        chunk_text = chunk["content"]
        pos_start, pos_end = _find_chunk_in_content(content, chunk_text, _cursor)
        if pos_start != -1:
            line_start = content.count("\n", 0, pos_start) + 1 + _line_offset
            line_end = content.count("\n", 0, pos_end) + 1 + _line_offset
            _cursor = pos_end
        else:
            line_start = 0
            line_end = 0

        specs.append(
            {
                "id": drawer_id,
                "content": chunk_text,
                "metadata": {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file,
                    "chunk_index": chunk["chunk_index"],
                    "added_by": agent,
                    "filed_at": datetime.now().isoformat(),
                    "language": language,
                    "symbol_name": symbol_name,
                    "symbol_type": symbol_type,
                    **markdown_metadata,
                    "source_hash": source_hash,
                    "extractor_version": __version__,
                    "chunker_strategy": chunk.get("chunker_strategy", "regex_structural_v1"),
                    "line_start": line_start,
                    "line_end": line_end,
                },
            }
        )
    return specs


def add_drawers_batch(collection, specs: list) -> int:
    """Embed and upsert a batch of drawer specs. Idempotent: re-mining the same
    file updates existing drawers in place instead of appending duplicates."""
    if not specs:
        return 0
    collection.upsert(
        ids=[s["id"] for s in specs],
        documents=[s["content"] for s in specs],
        metadatas=[s["metadata"] for s in specs],
    )
    return len(specs)


# =============================================================================
# PROCESS ONE FILE
# =============================================================================


def process_file(
    filepath: Path,
    project_path: Path,
    collection,
    wing: str,
    rooms: list,
    agent: str,
    dry_run: bool,
    csproj_room_map: Optional[dict] = None,
) -> int:
    """Read, chunk, route, and file one file. Returns drawer count."""

    if dry_run:
        specs = _collect_specs_for_file(
            filepath,
            project_path,
            None,
            wing,
            rooms,
            agent,
            mined_files=set(),
            csproj_room_map=csproj_room_map,
        )
        if specs:
            room = specs[0]["metadata"]["room"]
            print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(specs)} drawers)")
        return len(specs)

    specs = _collect_specs_for_file(
        filepath, project_path, collection, wing, rooms, agent, csproj_room_map=csproj_room_map
    )
    return add_drawers_batch(collection, specs)


# =============================================================================
# MAIN: MINE
# =============================================================================


def mine(
    project_dir: str,
    palace_path: str,
    wing_override: str | None = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
    respect_gitignore: bool = True,
    include_ignored: list | None = None,
    incremental: bool = True,
    kg=None,
    skip_optimize: bool = False,
    spellcheck: bool = False,
):
    """Mine a project directory into the palace.

    When *incremental* is True (default), only files whose content hash has changed
    since the last mine are re-chunked. Deleted files are swept after a full walk.
    Pass *incremental=False* (or --full from the CLI) to force a clean rebuild.

    *kg* is an optional KnowledgeGraph instance. When provided, .NET project files
    (.csproj, .fsproj, .vbproj) and solution files (.sln) are also parsed for
    structured dependency triples that are written to the knowledge graph.

    *spellcheck* is accepted for shared CLI/config plumbing but ignored: project
    mining stores source files verbatim.

    When *skip_optimize* is True, post-mine storage compaction is skipped.  Callers
    (e.g. the watcher) that run many mine() calls in sequence should skip optimize
    on each call and run a single optimize at the end.
    """

    project_path = Path(project_dir).expanduser().resolve()
    config = load_config(project_dir)

    wing = wing_override or config["wing"]
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])

    dotnet_structure = config.get("dotnet_structure", False)
    csproj_room_map: dict = {}
    if dotnet_structure:
        if not wing_override:
            sln_wing = _detect_sln_wing(project_path)
            if sln_wing:
                wing = sln_wing
        csproj_room_map = _build_csproj_room_map(project_path)

    scan_rules = get_scan_filter_rules(MempalaceConfig())
    files = scan_project(
        project_dir,
        respect_gitignore=respect_gitignore,
        include_ignored=include_ignored,
        scan_rules=scan_rules,
    )
    if limit > 0:
        files = files[:limit]

    mine_start = time.time()

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Rooms:   {', '.join(r['name'] for r in rooms)}")
    print(f"  Files:   {len(files)}")
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    if not incremental:
        print("  Mode:    FULL REBUILD (--full)")
    if not respect_gitignore:
        print("  .gitignore: DISABLED")
    if include_ignored:
        print(f"  Include: {', '.join(sorted(normalize_include_paths(include_ignored)))}")
    print(f"{'─' * 55}\n")

    if not dry_run:
        print("  Loading embedding model...", flush=True)
        collection = get_collection(palace_path)
        collection.warmup()
        print("  Model ready.\n", flush=True)
        existing_hashes = _bulk_existing_file_hashes(collection, wing)
    else:
        collection = None
        existing_hashes = {}

    total_drawers = 0
    files_skipped = 0
    files_tiny = 0
    room_counts = defaultdict(int)
    batch_buffer: list = []
    batch_num = 0
    walked_paths: set = set()

    def flush_batch() -> None:
        nonlocal total_drawers, batch_num
        batch_num += 1
        count = len(batch_buffer)
        print(
            f"  >> Embedding batch {batch_num} ({count} chunks)...",
            end="",
            flush=True,
        )
        t0 = time.time()
        total_drawers += add_drawers_batch(collection, batch_buffer)
        elapsed = time.time() - t0
        print(f" done ({elapsed:.1f}s)", flush=True)
        batch_buffer.clear()

    try:
        for i, filepath in enumerate(files, 1):
            source_file = str(filepath)
            walked_paths.add(source_file)

            if dry_run:
                drawers = process_file(
                    filepath=filepath,
                    project_path=project_path,
                    collection=collection,
                    wing=wing,
                    rooms=rooms,
                    agent=agent,
                    dry_run=True,
                    csproj_room_map=csproj_room_map,
                )
                total_drawers += drawers
                room = detect_room(
                    filepath, "", rooms, project_path, csproj_room_map=csproj_room_map
                )
                room_counts[room] += 1
                continue

            assert collection is not None
            # Print scanning progress every 100 files so large repos aren't silent
            if i % 100 == 0 or i == 1:
                print(
                    f"  Scanning [{i:4}/{len(files)}]...",
                    end="\r",
                    flush=True,
                )

            current_hash = _file_hash(filepath)

            if incremental:
                stored_hash = existing_hashes.get(source_file, "")
                if stored_hash == current_hash and stored_hash != "":
                    # File unchanged — skip
                    files_skipped += 1
                    continue
                # Hash mismatch or new file — delete old drawers then re-mine
                if source_file in existing_hashes:
                    collection.delete_by_source_file(source_file, wing)
                    if kg is not None and filepath.suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                        kg.invalidate_by_source_file(source_file)
            else:
                # --full mode: unconditionally delete existing drawers and re-mine
                collection.delete_by_source_file(source_file, wing)
                if kg is not None and filepath.suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                    kg.invalidate_by_source_file(source_file)

            specs = _collect_specs_for_file(
                filepath,
                project_path,
                collection,
                wing,
                rooms,
                agent,
                mined_files=None,
                source_hash=current_hash,
                csproj_room_map=csproj_room_map,
            )

            # KG triple emission for project/config/XAML/source files
            if kg is not None and filepath.suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                ext = filepath.suffix.lower()
                if ext == ".sln":
                    triples = parse_sln_file(filepath)
                elif ext == ".xaml":
                    triples = parse_xaml_file(filepath)
                elif ext in (".cs", ".fs", ".fsi", ".vb", ".py"):
                    triples = extract_type_relationships(filepath)
                else:
                    triples = parse_dotnet_project_file(filepath)
                for subj, pred, obj in triples:
                    kg.add_triple(subj, pred, obj, source_file=source_file)

            if not specs:
                files_tiny += 1
                continue

            room = specs[0]["metadata"]["room"]
            room_counts[room] += 1
            print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} +{len(specs)}")

            batch_buffer.extend(specs)
            if len(batch_buffer) >= get_batch_size():
                flush_batch()

        if not dry_run:
            assert collection is not None
            if batch_buffer:
                flush_batch()

            # Stale-file sweep: remove drawers for files no longer on disk.
            # Only safe when the full file set was walked (limit == 0).
            if incremental and limit == 0:
                stale_paths = set(existing_hashes.keys()) - walked_paths
                for stale_path in stale_paths:
                    collection.delete_by_source_file(stale_path, wing)
                    if kg is not None and Path(stale_path).suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                        kg.invalidate_by_source_file(stale_path)

            # Architecture extraction pass: derive pattern/layer/namespace/project
            # KG facts from the full walked file set.  Runs after the stale sweep so
            # deleted-file triples are already expired before we re-emit.
            if kg is not None and limit == 0:
                from mempalace_code.architecture import (
                    _NS_PROJECT_SENTINEL,
                    ARCH_PREDICATES,
                    extract_type_inventory,
                    load_arch_config,
                    namespace_project_source_file,
                    run_arch_pass,
                )

                arch_cfg = load_arch_config(config)
                # Expire stale arch triples for the current wing only — other wings'
                # arch facts are preserved so sequential single-wing mines don't wipe
                # each other's KG data.  The namespace→project sentinel is wing-scoped
                # (includes the wing name) so it is also correctly targeted here.
                kg.invalidate_arch_by_project_root(
                    list(ARCH_PREDICATES),
                    project_root=str(project_path),
                    sentinels=[namespace_project_source_file(wing)],
                )
                # Migration: pre-WING-SCOPE releases stored namespace→project rows
                # under a single shared sentinel without the wing suffix.  Expire
                # only this wing's legacy rows (scoped by the in_project object) so
                # other wings' legacy data persists until those wings are mined.
                kg.invalidate_legacy_arch_ns_project_for_wing(_NS_PROJECT_SENTINEL, wing)
                if arch_cfg.get("enabled", True):
                    arch_files = [Path(f) for f in walked_paths]
                    inventory = extract_type_inventory(arch_files, project_path)
                    n_arch = run_arch_pass(inventory, arch_cfg, wing, kg)
                    if n_arch:
                        print(f"  >> Architecture: {n_arch} KG triples emitted", flush=True)

            config = MempalaceConfig()
            if not skip_optimize:
                if config.optimize_after_mine:
                    t0 = time.time()
                    backup_first = config.backup_before_optimize
                    if backup_first:
                        print("  >> Backing up before optimize...", flush=True)
                    print("  >> Optimizing storage...", end="", flush=True)
                    result = optimize_store(collection, palace_path, backup_first=backup_first)
                    if result.ok:
                        print(f" done ({time.time() - t0:.1f}s)", flush=True)
                    else:
                        print(
                            f"\n  !! WARNING: optimize failed or verification error ({time.time() - t0:.1f}s)",
                            flush=True,
                        )
                else:
                    print("  >> Skipping optimize (disabled in config)", flush=True)
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Flushing pending batch...", flush=True)
        if batch_buffer and not dry_run:
            flush_batch()
        print(f"  {total_drawers} drawers filed before interrupt.")

    elapsed = time.time() - mine_start
    mins, secs = divmod(int(elapsed), 60)

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files processed: {len(files) - files_skipped - files_tiny}")
    print(f"  Files skipped (already filed): {files_skipped}")
    if files_tiny:
        print(f"  Files too small to index: {files_tiny}")
    print(f"  Drawers filed: {total_drawers}")
    print(f"  Time: {mins}m {secs}s")
    print("\n  By room:")
    for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    {room:20} {count} files")
    print('\n  Next: mempalace-code search "what you\'re looking for"')
    print(f"{'=' * 55}\n")

    return {
        "files_processed": len(files) - files_skipped - files_tiny,
        "files_skipped": files_skipped,
        "files_tiny": files_tiny,
        "drawers_filed": total_drawers,
        "elapsed_secs": elapsed,
    }


# =============================================================================
# STATUS
# =============================================================================


def _fmt_bytes(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n = n / 1024
    return f"{n:.1f} TB"


def status(palace_path: str):
    """Show what's been filed in the palace."""
    from ..storage import LanceStore

    lance_dir = os.path.join(palace_path, "lance")
    if not os.path.isdir(lance_dir):
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace-code init <dir> then mempalace-code mine <dir>")
        return

    store = open_store(palace_path, create=False, read_only=True)

    if isinstance(store, LanceStore) and store._table is None:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace-code init <dir> then mempalace-code mine <dir>")
        return

    # Count by wing and room
    total = store.count()
    wing_rooms = store.count_by_pair("wing", "room")

    print(f"\n{'=' * 55}")
    print(f"  MemPalace Status — {total} drawers")
    print(f"{'=' * 55}\n")
    for wing, rooms in sorted(wing_rooms.items()):
        print(f"  WING: {wing}")
        for room, count in sorted(rooms.items(), key=lambda x: x[1], reverse=True):
            print(f"    ROOM: {room:20} {count:5} drawers")
        print()

    if isinstance(store, LanceStore):
        try:
            s = store.storage_stats()
            print(
                f"  Storage: logical={_fmt_bytes(s['logical_bytes'])} "
                f"on-disk={_fmt_bytes(s['on_disk_bytes'])} "
                f"reclaimable={_fmt_bytes(s['estimated_reclaimable_bytes'])}"
            )
            print(
                f"  Versions: {s['version_count']}  "
                f"data-files: current={s['current_data_files']} "
                f"on-disk={s['on_disk_data_files']}  "
                f"deletion-files: current={s['current_deletion_files']} "
                f"on-disk={s['on_disk_deletion_files']}"
            )
        except Exception:
            pass

    print(f"{'=' * 55}\n")
