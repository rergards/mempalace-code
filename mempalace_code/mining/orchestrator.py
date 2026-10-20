"""mining.orchestrator — Core mine() loop, batch helpers, storage ops, status."""

import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..architecture import ARCH_PREDICATES
from ..cli_invocation import cli_command, cli_prefix, no_palace_next_step
from ..config import MempalaceConfig, expand_palace_path
from ..operation_lock import holds_palace_write_lease
from ..source_io import (
    RegularSourceError,
    hash_regular_bytes,
    is_regular_source_path,
    read_regular_bytes,
)
from ..storage import (
    _FILE_MINING_CHUNKER_STRATEGIES,
    CHROMA_RUNTIME_RETIRED_MESSAGE,
    ChromaRuntimeRetiredError,
    _copy_reconcile_record_path,
    is_canonical_project_source,
    is_legacy_chroma_palace,
    is_legacy_compressed,
    is_valid_file_hash,
    open_store,
    optimize_store,
    prune_settled_versions,
)
from ..version import __version__
from .batching import get_batch_size
from .chunkers import FILE_CHUNKER_STRATEGIES, STRATEGY_REGEX_STRUCTURAL, chunk_file
from .kg_extract import (
    _KG_EXTRACT_EXTENSIONS,
    FILE_KG_PREDICATES,
    extract_type_relationships,
    parse_dotnet_project_file,
    parse_sln_file,
    parse_xaml_file,
)
from .languages import detect_language
from .projects import (
    _build_csproj_room_map,
    detect_room,
    load_config,
    mine_wing,
    settle_mine_wing,
    validate_mine_arguments,
)
from .scanner import (
    NESTED_GIT_ROOT,
    TECHNICAL_ROOTS,
    get_scan_filter_rules,
    is_exact_force_include,
    is_force_included,
    is_technical_root_path,
    resolve_include_paths,
    scan_project,
)
from .source_text import (
    DEFAULT_MAX_FILE_BYTES,
    SKIP_EMPTY,
    SKIP_MINIFIED,
    SKIP_REASON_LABELS,
    SKIP_SECRET,
    SKIP_TOO_LARGE,
    SourceText,
    decode_source,
)
from .symbols import extract_symbol

# =============================================================================
# INCREMENTAL MINING HELPERS
# =============================================================================


def _expired_count(value: object) -> int:
    """A fact count a KG write returned; 0 for KG doubles that return nothing."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _file_hash(path: Path) -> str:
    """Return blake2b hex digest (32 chars) of raw file bytes."""
    return hash_regular_bytes(path, digest_size=16)


def _warn_source_read_error(path: Path, exc: OSError) -> None:
    detail = str(exc) if isinstance(exc, RegularSourceError) else f"{path}: {exc}"
    print(detail, file=sys.stderr)


def _bulk_existing_file_hashes(
    collection, wing: str, *, project_root=None, protected_source_files: Optional[set] = None
) -> Optional[dict]:
    """Return {source_file: source_hash} for all drawers in wing.

    Delegates to collection.get_source_file_hashes() (LanceDB column projection,
    no vector scan). Scoped calls preserve None so callers cannot confuse an
    unavailable provenance assessment with a successful empty scan.
    """
    try:
        if project_root is None:
            result = collection.get_source_file_hashes(wing)
        else:
            result = collection.get_source_file_hashes(
                wing,
                project_root=project_root,
                protected_source_files=protected_source_files,
            )
    except Exception:
        if project_root is not None:
            return None
        raise
    if project_root is None:
        return result if result is not None else {}
    return result if isinstance(result, dict) else None


def _owned_tiny_sources(
    tiny_hashes: object, project_root: Path, protected_source_files: set[str]
) -> set[str]:
    """Return original sidecar keys with proven safe path and digest provenance."""
    if not isinstance(tiny_hashes, dict):
        return set()
    return {
        source_file
        for source_file, source_hash in tiny_hashes.items()
        if isinstance(source_file, str)
        and is_valid_file_hash(source_hash)
        and is_canonical_project_source(source_file, project_root)
        and source_file not in protected_source_files
    }


def _tiny_hashes_path(palace_path: str) -> Path:
    """Return the path to the tiny-hashes sidecar.

    Stored under palace/.mempalace/ so the scanner skips it when the palace
    directory lives inside the project being mined (.mempalace is in SKIP_DIRS).
    """
    return Path(palace_path) / ".mempalace" / "tiny_hashes.json"


def _load_tiny_hashes(palace_path: str, wing: str) -> dict:
    """Return {source_file: source_hash} for files that produced no chunks on the last mine.

    Files with nothing indexable (empty, binary, too large, minified) have no drawer
    rows, so their hashes are stored in a sidecar JSON file rather than in the
    palace. Callers re-validate a matching entry under the current read rules before
    skipping the file. Returns an empty dict when the sidecar is absent or unreadable.
    """
    p = _tiny_hashes_path(palace_path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            return {}
        hashes = data.get(wing, {})
        return hashes if isinstance(hashes, dict) else {}
    except Exception:
        return {}


def _save_tiny_hashes(palace_path: str, wing: str, hashes: dict) -> None:
    """Persist {source_file: source_hash} for zero-chunk files to the sidecar JSON."""
    p = _tiny_hashes_path(palace_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[wing] = hashes
    p.write_text(json.dumps(data))


def _mine_config_path(palace_path: str) -> Path:
    """Sidecar with the routing fingerprint of the last completed mine per wing/project."""
    return Path(palace_path) / ".mempalace" / "mine_config.json"


# Bump when detect_room's rules change so the next mine re-routes unchanged files.
ROOM_ROUTING_RULES = 2


def _routing_fingerprint(config: dict, rooms: list, dotnet_structure: object) -> str:
    """Hash of the settings and room-routing rules that decide rooms, skips, and facts."""
    payload = {
        "routing_rules": ROOM_ROUTING_RULES,
        "rooms": rooms,
        "dotnet_structure": bool(dotnet_structure),
        "architecture": config.get("architecture"),
        "max_file_bytes": config.get("max_file_bytes"),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _existing_wings(collection) -> set:
    """Return the palace's wing names; empty when the taxonomy cannot be read."""
    try:
        return set(collection.count_by("wing"))
    except Exception:
        return set()  # degraded read: the mine itself reports real storage failures


def _load_config_fingerprint(palace_path: str, wing: str, project_path: Path) -> Optional[str]:
    """Return the stored routing fingerprint, or None when unknown."""
    try:
        data = json.loads(_mine_config_path(palace_path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get(wing), dict):
        return None
    value = data[wing].get(str(project_path))
    return value if isinstance(value, str) else None


def _earlier_project_wings(
    palace_path: str, wing: str, project_path: Path, palace_wings: set
) -> list[str]:
    """Other wings a full mine of *project_path* filed into that still exist in the palace."""
    try:
        data = json.loads(_mine_config_path(palace_path).read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    project = str(project_path)
    return sorted(
        name
        for name, entry in data.items()
        if name != wing and name in palace_wings and isinstance(entry, dict) and project in entry
    )


def _save_config_fingerprint(
    palace_path: str, wing: str, project_path: Path, fingerprint: str
) -> None:
    path = _mine_config_path(palace_path)
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    entry = data.get(wing)
    if not isinstance(entry, dict):
        entry = {}
    entry[str(project_path)] = fingerprint
    data[wing] = entry
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True))
    except OSError as exc:
        print(f"  WARNING: could not record mine configuration: {exc}", file=sys.stderr)


def _stale_strategies(entry: dict) -> set:
    """Chunker strategies of a source's drawers that the current chunkers no longer write."""
    return {
        strategy
        for strategy in entry.get("strategies", set())
        if strategy and strategy not in FILE_CHUNKER_STRATEGIES
    }


def _needs_rechunk(entry: dict) -> bool:
    """True when an unchanged source's drawers must be rebuilt anyway.

    That is when an older chunker wrote them, or a pre-1.15.0 ``compress`` replaced
    their text with AAAK (the source hash is unchanged, the verbatim text is gone).
    """
    return bool(_stale_strategies(entry)) or bool(entry.get("legacy_compressed"))


def _source_file_layout(collection, wing: str) -> dict:
    """Return {source_file: {"strategies", "rooms"}} for mined rows, or {} if unsupported."""
    getter = getattr(collection, "get_source_file_layout", None)
    if getter is None:
        return {}
    try:
        layout = getter(wing)
    except Exception:
        return {}
    return layout if isinstance(layout, dict) else {}


def _open_existing_store_read_only(palace_path: str):
    """Open an existing palace read-only for dry-run comparisons; None when absent."""
    if not os.path.isdir(os.path.join(palace_path, "lance")):
        return None
    try:
        return open_store(palace_path, create=False, read_only=True)
    except Exception as exc:
        print(f"  Dry run: palace not readable ({exc}); comparing against an empty palace.")
        return None


def _scan_hard_exclude_dirs(project_path: Path, palace_path: str) -> list[Path]:
    """Return storage dirs that must not be mined as source files."""
    try:
        palace_dir = Path(palace_path).expanduser().resolve()
    except OSError:
        return []
    if palace_dir == project_path or project_path in palace_dir.parents:
        return [palace_dir]
    return []


# =============================================================================
# GENERATED COPIES — nested checkouts and technical copies of project files
# =============================================================================

# The scanner's project-root technical directories, where agents and tools keep technical
# copies of the project (task checkouts, writer workspaces). Default scans do not walk
# them. Stored sources below them are only candidates: deletion still needs identical
# current bytes and identical stored chunks of a canonical project file.
_TECHNICAL_COPY_ROOTS = tuple(sorted(TECHNICAL_ROOTS))
# Copy sources assessed, then re-assessed and deleted, per exact-id batch.
_COPY_RECONCILE_BATCH = 200
# Row fields that say where or when a chunk was filed, not what it holds.
_COPY_LOCATION_FIELDS = frozenset(
    {"id", "text", "vector", "source_file", "filed_at", "added_by", "room", "extractor_version"}
)
# Canonical-assessment reasons that leave a copy free to repeat another stored copy.
_COPY_PEER_REASONS = frozenset({"chunks-differ", "content-differs"})
# Copy record events whose counterparts are alias targets of removed rows.
_COPY_ALIAS_EVENTS = frozenset({"remove", "removed"})


def _no_copy_reconcile() -> dict:
    return {
        "copy_sources_removed": 0,
        "copy_rows_removed": 0,
        "copy_sources_retained_by_reason": {},
        "copy_reconcile_refusal": None,
        "copy_disk": None,
    }


def _under_prefixes(source_file: str, prefixes: tuple) -> bool:
    return any(source_file.startswith(prefix + os.sep) for prefix in prefixes)


def _is_technical_copy_path(path_text: str, project_path: Path) -> bool:
    return is_technical_root_path(path_text, project_path)


def _technical_copy_counterparts(
    files: list, project_path: Path, stored_sources: Optional[dict] = None
) -> dict:
    """Map each technical copy candidate to its canonical counterpart.

    Candidates are walked files below a technical copy root (explicitly included)
    and stored sources below one, which default scans no longer walk. The
    counterpart is the walked file outside every technical root whose complete
    project-relative path is the longest strict suffix of the copy's relative path.
    A candidate only selects a pair; the copy proof is assessed separately.
    """
    canonical: dict = {}
    copies: dict = {}
    for path in files:
        try:
            parts = path.relative_to(project_path).parts
        except ValueError:
            continue
        if parts and parts[0] in _TECHNICAL_COPY_ROOTS:
            copies[str(path)] = parts
        else:
            canonical[parts] = path
    prefixes = tuple(str(project_path / root) + os.sep for root in _TECHNICAL_COPY_ROOTS)
    for source_file in stored_sources or ():
        if not isinstance(source_file, str) or not source_file.startswith(prefixes):
            continue
        if source_file not in copies and _is_technical_copy_path(source_file, project_path):
            copies[source_file] = Path(source_file).relative_to(project_path).parts
    result: dict = {}
    for copy_file, parts in copies.items():
        for start in range(1, len(parts)):
            match = canonical.get(parts[start:])
            if match is not None:
                result[copy_file] = str(match)
                break
    return result


def _generated_copy_pairs(
    existing_hashes: dict,
    nested_roots: list,
    copy_counterparts: dict,
    project_path: Path,
    walked: set,
) -> list:
    """Pair stored copy sources with the canonical source they may repeat.

    Covers walked technical copies and stored sources below a skipped nested Git
    checkout, whose counterpart is the same path relative to that checkout. Equal
    stored digests only select a candidate; they never prove a deletion. Copies
    whose stored digest differs from their counterpart's are candidates too when at
    least two share that counterpart and one valid digest, since they may repeat one
    legacy snapshot. A lone changed copy is not selected.
    """
    roots = [str(root) for root, kind in nested_roots if kind == NESTED_GIT_ROOT]
    pairs: dict = {}
    peers: dict = defaultdict(list)
    for source_file, source_hash in existing_hashes.items():
        if not is_valid_file_hash(source_hash):
            continue
        counterpart = copy_counterparts.get(source_file)
        if counterpart is None:
            root = next((r for r in roots if source_file.startswith(r + os.sep)), None)
            if root is None:
                continue
            candidate = str(project_path / os.path.relpath(source_file, root))
            if candidate not in walked or _is_technical_copy_path(candidate, project_path):
                continue
            counterpart = candidate
        if counterpart == source_file:
            continue
        counterpart_hash = existing_hashes.get(counterpart)
        if counterpart_hash == source_hash:
            pairs[source_file] = counterpart
        elif is_valid_file_hash(counterpart_hash):
            peers[(counterpart, source_hash)].append(source_file)
    for (counterpart, _), sources in peers.items():
        if len(sources) > 1:
            pairs.update((source_file, counterpart) for source_file in sources)
    return sorted(pairs.items())


def _rows_by_source(collection, wing: str, sources: list) -> Optional[dict]:
    """Return {source_file: [row, ...]} for *sources* in *wing*; None when unreadable."""
    iter_all = getattr(collection, "iter_all", None)
    if iter_all is None:
        return None
    rows: dict = defaultdict(list)
    try:
        for batch in iter_all(
            where={"$and": [{"wing": wing}, {"source_file": {"$in": sources}}]},
            batch_size=1000,
        ):
            for row in batch:
                rows[row.get("source_file")].append(row)
    except Exception:
        return None
    return rows


def _is_current_generated_row(row: dict, source_hash: str) -> bool:
    return (
        row.get("ingest_mode") == "file"
        and row.get("chunker_strategy") in _FILE_MINING_CHUNKER_STRATEGIES
        and row.get("type") == ""
        and is_valid_file_hash(source_hash)
        and row.get("source_hash") == source_hash
        and not is_legacy_compressed(row)
    )


def _chunk_order(row: dict) -> tuple:
    value = row.get("chunk_index")
    if isinstance(value, int) and not isinstance(value, bool):
        return (0, value, "")
    return (1, 0, str(value))


def _chunk_group(rows: list) -> list:
    """Ordered chunk text plus every metadata field except filing location and time."""
    group = []
    for row in sorted(rows, key=_chunk_order):
        fields = sorted((k, v) for k, v in row.items() if k not in _COPY_LOCATION_FIELDS)
        group.append((row.get("text"), fields))
    return group


def _assess_generated_copy(rows_by_source: dict, copy_file: str, counterpart: str) -> tuple:
    """Return (copy row ids, digest, None) when *copy_file* exactly repeats *counterpart*.

    Otherwise the ids are empty and the last item names why the copy is kept. Proof
    needs both files to be current regular files without symlink components and with
    identical bytes, every stored copy row to be a current generated row of that
    digest, and the ordered chunk groups to match in text and all other metadata.
    """
    digests = []
    for path_text in (copy_file, counterpart):
        try:
            if os.path.realpath(path_text) != path_text:
                return [], "", "source-missing-or-not-regular"
            if not is_regular_source_path(Path(path_text)):
                return [], "", "source-missing-or-not-regular"
            digests.append(_file_hash(Path(path_text)))
        except OSError:
            return [], "", "source-missing-or-not-regular"
    digest = digests[0]
    if digest != digests[1]:
        return [], digest, "content-differs"
    copy_rows = rows_by_source.get(copy_file, [])
    if not copy_rows:
        return [], digest, "no-stored-rows"
    if not all(_is_current_generated_row(row, digest) for row in copy_rows):
        return [], digest, "protected-or-legacy-row"
    canonical_rows = rows_by_source.get(counterpart, [])
    canonical_rows = [row for row in canonical_rows if _is_current_generated_row(row, digest)]
    if _chunk_group(copy_rows) != _chunk_group(canonical_rows):
        return [], digest, "chunks-differ"
    return [row["id"] for row in copy_rows], digest, None


def _assess_copy_batch(
    collection,
    wing: str,
    batch: list,
    retained,
    prefix: str = "",
    rejected: Optional[list] = None,
) -> list:
    """Assess *batch* of (copy, counterpart) pairs; count each kept copy in *retained*.

    With *rejected*, each kept copy is appended there as (copy, counterpart, reason,
    digest) instead, and the caller decides how it is counted.
    """
    sources = sorted({path for pair in batch for path in pair})
    rows_by_source = _rows_by_source(collection, wing, sources)
    qualified = []
    for copy_file, counterpart in batch:
        if rows_by_source is None:
            if rejected is not None:
                rejected.append((copy_file, counterpart, "rows-unreadable", ""))
            else:
                retained[prefix + "rows-unreadable"] += 1
            continue
        ids, digest, reason = _assess_generated_copy(rows_by_source, copy_file, counterpart)
        if reason is None:
            qualified.append((copy_file, counterpart, ids, digest))
        elif rejected is not None:
            rejected.append((copy_file, counterpart, reason, digest))
        else:
            retained[prefix + reason] += 1
    return qualified


def _append_copy_record(record_path: Path, entry: dict) -> bool:
    try:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        with record_path.open("a+b") as handle:
            if handle.tell():
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    handle.write(b"\n")
            handle.write((json.dumps(entry, sort_keys=True, default=str) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        # Publish both the record entry and its directory before deleting rows.
        for directory in (record_path.parent, record_path.parent.parent):
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except OSError as exc:
        print(f"  WARNING: could not record copy reconciliation: {exc}", file=sys.stderr)
        return False
    return True


def _on_disk_bytes(collection) -> Optional[int]:
    stats = getattr(collection, "storage_stats", None)
    if not callable(stats):
        return None
    try:
        snapshot = stats()
        if not isinstance(snapshot, dict):
            return None
        value = snapshot.get("on_disk_bytes")
    except Exception:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _snapshot_key(rows: list, digest: str) -> Optional[str]:
    """Digest of one copy's complete chunk group; None unless every row is current."""
    if not rows or not all(_is_current_generated_row(row, digest) for row in rows):
        return None
    group = json.dumps(_chunk_group(rows), sort_keys=True, default=str)
    return hashlib.sha256(group.encode("utf-8")).hexdigest()


def _copy_snapshot_classes(collection, wing: str, peers: dict, retained) -> list:
    """Group peer candidates into classes of one exact stored snapshot.

    *peers* maps (counterpart, current digest) to [(copy, reason), ...]. A class is a
    sorted list of at least two copies whose rows are all current generated rows of
    that digest with one complete chunk group. The key only groups candidates: each
    peer is still proven by the unchanged assessor. Sources are read in bounded
    batches; every copy outside a class is counted under its canonical reason.
    """
    classes: list = []
    for (_, digest), candidates in sorted(peers.items()):
        if len(candidates) < 2:
            retained[candidates[0][1]] += 1
            continue
        snapshots: dict = defaultdict(list)
        ordered = sorted(candidates)
        for start in range(0, len(ordered), _COPY_RECONCILE_BATCH):
            batch = ordered[start : start + _COPY_RECONCILE_BATCH]
            sources = [copy_file for copy_file, _ in batch]
            rows_by_source = _rows_by_source(collection, wing, sources) or {}
            for copy_file, reason in batch:
                key = _snapshot_key(rows_by_source.get(copy_file, []), digest)
                if key is None:
                    retained[reason] += 1
                else:
                    snapshots[key].append((copy_file, reason))
        for members in snapshots.values():
            if len(members) > 1:
                classes.append(members)
            else:
                retained[members[0][1]] += 1
    return classes


def _qualify_copy_peers(collection, wing: str, classes: list, targets: set, retained) -> list:
    """Prove each snapshot peer against the one representative its class keeps.

    The representative is the lowest-sorted member an existing record already names
    as an alias target, else the lowest-sorted member, so a retry keeps the same one.
    Representatives and recorded targets are kept; every other member must pass the
    unchanged assessor against the representative, in bounded batches that re-read
    it. Kept members are counted under their canonical-assessment reason.
    """
    peer_pairs: list = []
    reasons: dict = {}
    for members in classes:
        named = [copy_file for copy_file, _ in members if copy_file in targets]
        keeper = named[0] if named else members[0][0]
        for copy_file, reason in members:
            reasons[copy_file] = reason
            if copy_file == keeper or copy_file in targets:
                retained[reason] += 1
            else:
                peer_pairs.append((copy_file, keeper))
    qualified: list = []
    for start in range(0, len(peer_pairs), _COPY_RECONCILE_BATCH):
        batch = peer_pairs[start : start + _COPY_RECONCILE_BATCH]
        failed: list = []
        qualified.extend(
            (copy_file, representative)
            for copy_file, representative, _, _ in _assess_copy_batch(
                collection, wing, batch, retained, rejected=failed
            )
        )
        for copy_file, _, _, _ in failed:
            retained[reasons[copy_file]] += 1
    return qualified


def _without_alias_targets(qualified: list, targets: set, retained) -> list:
    """Drop every pair whose copy is an alias target of this run or an earlier one.

    No representative can be deleted, and no alias can name a deleted source.
    """
    counterparts = {counterpart for _, counterpart in qualified}
    kept: list = []
    for copy_file, counterpart in qualified:
        if copy_file in targets:
            retained["historical-alias-target"] += 1
        elif copy_file in counterparts:
            retained["alias-target"] += 1
        else:
            kept.append((copy_file, counterpart))
    return kept


def _copy_history_object(pairs: list) -> dict:
    """Reject ambiguous JSON objects, including objects nested in alias sources."""
    entry: dict = {}
    for key, value in pairs:
        if key in entry:
            raise ValueError("duplicate JSON object key in copy history")
        entry[key] = value
    return entry


def _copy_history_line(line: bytes, wing: str) -> tuple:
    """Return (alias targets one copy-record line names for *wing*, problem or None)."""
    try:
        entry = json.loads(line, object_pairs_hook=_copy_history_object)
    except ValueError:
        return [], "not valid JSON"
    if not isinstance(entry, dict) or not isinstance(entry.get("event"), str):
        return [], "missing its event"
    if entry["event"] not in _COPY_ALIAS_EVENTS:
        if entry["event"] not in {"refused", "summary"} or "sources" in entry:
            return [], "an unknown or ambiguous event"
        return [], None
    sources = entry.get("sources")
    if not isinstance(entry.get("wing"), str) or not entry["wing"].strip():
        return [], "an alias record without a wing"
    if not isinstance(sources, list) or not sources:
        return [], "an alias record without sources"
    if not all(
        isinstance(source, dict)
        and isinstance(source.get("source_file"), str)
        and isinstance(source.get("counterpart"), str)
        and source["counterpart"]
        for source in sources
    ):
        return [], "an alias record with an invalid source"
    if entry["wing"] != wing:
        return [], None
    return [source["counterpart"] for source in sources], None


def _historical_copy_targets(record_path: Path, wing: str) -> tuple:
    """Return (counterparts earlier remove/removed records of *wing* name, refusal).

    Recorded alias targets must outlive the aliases that name them. A record that was
    never created is empty history. Any line that cannot be read, parsed or attributed,
    and any remove/removed record whose sources cannot be validated, returns a refusal
    instead: write-before-delete ordering does not prove that a damaged line never
    preceded a deletion. The record is streamed and never changed here.
    """
    targets: set = set()
    try:
        if record_path.is_symlink():
            return set(), "copy reconciliation history is a symlink; no copy is removed"
        with record_path.open("rb") as handle:
            for number, line in enumerate(handle, 1):
                named, problem = _copy_history_line(line, wing)
                if problem is not None:
                    reason = f"copy reconciliation history line {number} is {problem}"
                    return set(), f"{reason}; no copy is removed while alias targets are unknown"
                targets.update(named)
    except FileNotFoundError:
        return set(), None
    except OSError as exc:
        return set(), f"copy reconciliation history is unreadable ({exc}); no copy is removed"
    return targets, None


def _reconcile_generated_copies(
    collection, wing: str, pairs: list, palace_path: str, kg_path, optimize_enabled: bool
) -> dict:
    """Delete stored rows that exactly repeat a canonical source; keep everything else.

    Knowledge-graph facts are never read or changed. Copies the canonical source does
    not prove may still exactly repeat each other: one representative per stored
    snapshot is kept and the other copies are proven against it. Representatives and
    every alias target named in this run or in the existing record are never deleted,
    and a record that cannot be read or validated refuses all deletions. A healthy
    pre_optimize backup gates the first deletion; a failed or degraded one refuses all
    of them and keeps the forensic archive. Each exact-id batch is re-assessed
    immediately before it is deleted and recorded before and after, so an
    interruption leaves the remaining candidates for the next run to reassess.
    """
    outcome = _no_copy_reconcile()
    retained: dict = defaultdict(int)
    qualified: list = []
    rejected: list = []
    for start in range(0, len(pairs), _COPY_RECONCILE_BATCH):
        batch = pairs[start : start + _COPY_RECONCILE_BATCH]
        qualified.extend(
            (copy_file, counterpart)
            for copy_file, counterpart, _, _ in _assess_copy_batch(
                collection, wing, batch, retained, rejected=rejected
            )
        )
    peers: dict = defaultdict(list)
    for copy_file, counterpart, reason, digest in rejected:
        if reason in _COPY_PEER_REASONS:
            peers[(counterpart, digest)].append((copy_file, reason))
        else:
            retained[reason] += 1
    classes = _copy_snapshot_classes(collection, wing, peers, retained)
    if not qualified and not classes:
        outcome["copy_sources_retained_by_reason"] = dict(retained)
        return outcome

    record_path = _copy_reconcile_record_path(palace_path)
    # Before any deletion: earlier alias targets stay, and damaged history refuses.
    targets, history_refusal = _historical_copy_targets(record_path, wing)
    if history_refusal is not None:
        retained["history-refused"] += len(qualified) + sum(len(c) for c in classes)
        outcome["copy_reconcile_refusal"] = history_refusal
        outcome["copy_sources_retained_by_reason"] = dict(retained)
        return outcome
    qualified.extend(_qualify_copy_peers(collection, wing, classes, targets, retained))
    qualified = _without_alias_targets(qualified, targets, retained)
    if not qualified:
        outcome["copy_sources_retained_by_reason"] = dict(retained)
        return outcome
    archive = None
    refusal: Optional[str] = None
    try:
        from ..backup import create_backup

        metadata, archive = create_backup(palace_path, kind="pre_optimize", kg_path=kg_path)
    except Exception as exc:
        refusal = f"pre_optimize backup failed: {exc}"
    else:
        if not isinstance(metadata, dict) or metadata.get("degraded"):
            refusal = (
                f"pre_optimize backup is degraded; the forensic archive {archive} is kept "
                "but is not a recovery point"
            )
    if refusal is not None:
        retained["backup-refused"] += len(qualified)
        outcome["copy_reconcile_refusal"] = refusal
        outcome["copy_sources_retained_by_reason"] = dict(retained)
        _append_copy_record(
            record_path,
            {
                "event": "refused",
                "timestamp": datetime.now().isoformat(),
                "wing": wing,
                "reason": refusal,
                "candidates": len(qualified),
            },
        )
        return outcome

    on_disk_before = _on_disk_bytes(collection)
    for start in range(0, len(qualified), _COPY_RECONCILE_BATCH):
        chunk = qualified[start : start + _COPY_RECONCILE_BATCH]
        batch = chunk
        # Drift since the first assessment keeps the source.
        confirmed = _assess_copy_batch(
            collection, wing, batch, retained, prefix="changed-before-delete:"
        )
        if not confirmed:
            continue
        alias_rows = _rows_by_source(collection, wing, [item[0] for item in confirmed])
        if alias_rows is None:
            retained["alias-metadata-unreadable"] += len(confirmed)
            continue
        sources = [
            {
                "source_file": copy_file,
                "counterpart": counterpart,
                "source_hash": digest,
                "rows": len(ids),
                "aliases": [
                    {
                        k: row.get(k)
                        for k in (
                            "id",
                            "source_file",
                            "room",
                            "filed_at",
                            "added_by",
                            "extractor_version",
                            "chunker_strategy",
                            "source_hash",
                        )
                    }
                    for row in alias_rows.get(copy_file, [])
                ],
            }
            for copy_file, counterpart, ids, digest in confirmed
        ]
        entry = {"timestamp": datetime.now().isoformat(), "wing": wing, "backup": archive}
        if not _append_copy_record(record_path, {**entry, "event": "remove", "sources": sources}):
            outcome["copy_reconcile_refusal"] = "copy reconciliation record could not be written"
            retained["record-unwritable"] += len(qualified) - start
            break
        deleted = collection.delete([row_id for _, _, ids, _ in confirmed for row_id in ids])
        outcome["copy_sources_removed"] += len(confirmed)
        outcome["copy_rows_removed"] += deleted
        _append_copy_record(
            record_path,
            {
                **entry,
                "event": "removed",
                "alias_record_timestamp": entry["timestamp"],
                "sources": [
                    {k: v for k, v in source.items() if k != "aliases"} for source in sources
                ],
                "deleted_rows": deleted,
            },
        )

    maintenance = None
    if optimize_enabled and outcome["copy_rows_removed"]:
        optimized = optimize_store(collection, palace_path, backup_first=False, kg_path=kg_path)
        if optimized.ok:
            from ..storage import READER_VERSION_GRACE

            # Keep normal readers available during the one settling interval.
            time.sleep(READER_VERSION_GRACE.total_seconds() + 0.1)
            maintenance = collection.cleanup_stale_fragments(older_than_days=0, unsafe_now=False)
        else:
            maintenance = {"ok": False, "error": "healthy-backed optimize failed"}
    on_disk_after = _on_disk_bytes(collection)
    reason = (
        "Row deletion commits a new Lance version; earlier versions keep these bytes until "
        "supported maintenance prunes them"
    )
    if not optimize_enabled:
        reason += " (post-mine optimize is disabled or skipped, so this run prunes nothing)"
    outcome["copy_disk"] = {
        "measurement_scope": "Lance table files; excludes backups and the provenance record",
        "on_disk_bytes_before": on_disk_before,
        "on_disk_bytes_after": on_disk_after,
        "disk_reclaimed": bool(
            maintenance
            and maintenance.get("ok")
            and on_disk_before is not None
            and on_disk_after is not None
            and on_disk_after < on_disk_before
        ),
        "maintenance": maintenance,
        "reason": (
            f"Supported maintenance: {maintenance}; measured bytes {on_disk_before} -> {on_disk_after}"
            if maintenance is not None
            else reason
        ),
    }
    outcome["copy_sources_retained_by_reason"] = dict(retained)
    _append_copy_record(
        record_path,
        {
            "event": "summary",
            "timestamp": datetime.now().isoformat(),
            "wing": wing,
            "sources_removed": outcome["copy_sources_removed"],
            "rows_removed": outcome["copy_rows_removed"],
            "retained_by_reason": outcome["copy_sources_retained_by_reason"],
            **outcome["copy_disk"],
        },
    )
    return outcome


def _copy_maintenance_pending(record_path: Path) -> bool:
    """A bounded diagnostic hint; current Lance state and recovery gates still decide."""
    try:
        with record_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 65536))
            last = json.loads(handle.read().splitlines()[-1])
        maintenance = last.get("maintenance") if isinstance(last, dict) else None
        return not (
            isinstance(last, dict)
            and last.get("event") == "summary"
            and isinstance(maintenance, dict)
            and maintenance.get("ok") is True
            # A safe prune may retain every old version for readers.
            and type(maintenance.get("version_count_after")) is int
            and maintenance["version_count_after"] == 1
            and maintenance.get("versions_kept_for_readers", 0) == 0
        )
    except (OSError, ValueError, IndexError):
        # An interrupted/oversized final entry cannot prove completed maintenance.
        return True


def _run_copy_reconcile(
    collection,
    wing: str,
    pairs: list,
    palace_path: str,
    kg_path,
    skip_optimize: bool,
    *,
    retry_maintenance: bool = True,
) -> dict:
    optimize_enabled = not skip_optimize and MempalaceConfig().optimize_after_mine
    outcome = (
        _reconcile_generated_copies(collection, wing, pairs, palace_path, kg_path, optimize_enabled)
        if pairs
        else _no_copy_reconcile()
    )
    if (
        not retry_maintenance
        or not optimize_enabled
        or outcome["copy_rows_removed"]
        or outcome["copy_reconcile_refusal"]
        or not _copy_maintenance_due(palace_path)
    ):
        return outcome
    return _retry_copy_maintenance(collection, wing, palace_path, kg_path, outcome)


def _copy_maintenance_due(palace_path: str) -> bool:
    """True when the local copy record hints that physical maintenance is pending.

    Only a hint for when to look: current Lance state and the recovery gates in
    _retry_copy_maintenance decide, and it never authorizes deletion.
    """
    record_path = _copy_reconcile_record_path(palace_path)
    return record_path.is_file() and _copy_maintenance_pending(record_path)


def _retry_copy_maintenance(
    collection, wing: str, palace_path: str, kg_path, outcome: dict
) -> dict:
    """Retry pending physical maintenance after an earlier exact-copy removal.

    Shared by mine() and the watcher's once-per-batch maintenance decision. Callers
    hold the palace write lease, so the record is assessed and updated under it.
    """
    # The existing local record is only a retry hint, never deletion authority.
    # Lance versions are the existing retry state. No journal marker or new store:
    # after a deferred prune or post-delete interruption, an unchanged mine can
    # safely retry with a fresh healthy recovery point and the same reader fence.
    stats_method = getattr(collection, "storage_stats", None)
    if not callable(stats_method):
        return outcome
    before = None
    try:
        before = stats_method()
        if not isinstance(before, dict):
            return outcome
        state = before.get("latest_version_compact")
        if state is True and before.get("version_count", 0) <= 1:
            _append_copy_record(
                _copy_reconcile_record_path(palace_path),
                {
                    "event": "summary",
                    "wing": wing,
                    "maintenance": {"ok": True, "version_count_after": before["version_count"]},
                },
            )
            return outcome
        if state is None:
            maintenance = {
                "ok": False,
                "deferred": True,
                "error": "Current compaction metadata unavailable",
            }
        elif state is True:
            # Reuse the existing prune-only predicate and reader fence. No new
            # recovery archive is needed when no fragment is rewritten.
            maintenance = collection.cleanup_stale_fragments(
                older_than_days=0, unsafe_now=False, compact=False
            )
        else:
            optimized = optimize_store(collection, palace_path, backup_first=True, kg_path=kg_path)
            if optimized.ok:
                maintenance = collection.cleanup_stale_fragments(
                    older_than_days=0, unsafe_now=False
                )
            else:
                maintenance = {"ok": False, "error": "healthy-backed optimize failed"}
    except Exception as exc:
        maintenance = {"ok": False, "error": str(exc)}
    after_bytes = _on_disk_bytes(collection)
    before_bytes = before.get("on_disk_bytes") if isinstance(before, dict) else None
    outcome["copy_disk"] = {
        "measurement_scope": "Lance table files; excludes backups and the provenance record",
        "on_disk_bytes_before": before_bytes,
        "on_disk_bytes_after": after_bytes,
        "disk_reclaimed": bool(
            maintenance.get("ok")
            and isinstance(before_bytes, int)
            and after_bytes is not None
            and after_bytes < before_bytes
        ),
        "maintenance": maintenance,
        "reason": f"Retry supported maintenance: {maintenance}; bytes {before_bytes} -> {after_bytes}",
    }
    _append_copy_record(
        _copy_reconcile_record_path(palace_path),
        {"event": "summary", "wing": wing, **outcome["copy_disk"]},
    )
    return outcome


def _print_copy_summary(copies_skipped: int, outcome: dict) -> None:
    if copies_skipped:
        print(f"  Files skipped (identical copy of a filed project file): {copies_skipped}")
    if outcome.get("copy_reconcile_refusal"):
        print(f"  Copy reconciliation refused: {outcome['copy_reconcile_refusal']}")
    if outcome.get("copy_sources_removed"):
        print(
            f"  Copy drawers removed: {outcome['copy_rows_removed']} "
            f"({outcome['copy_sources_removed']} exact copies of filed project files)"
        )
    retained = outcome.get("copy_sources_retained_by_reason") or {}
    if retained:
        detail = ", ".join(f"{reason} {count}" for reason, count in sorted(retained.items()))
        print(f"  Copies kept (not proven exact): {detail}")
    disk = outcome.get("copy_disk")
    if disk:
        print(f"  Disk: {disk['reason']}")


# =============================================================================
# PALACE — storage operations
# =============================================================================


def get_collection(palace_path: str):
    """Open (or create) the drawer store for a palace."""
    os.makedirs(palace_path, mode=0o700, exist_ok=True)
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


def _read_source(
    filepath: Path, *, max_file_bytes: Optional[int], force_include: bool
) -> SourceText:
    """Read and decode one source file under the mining read policy.

    Under a byte cap only ``max_file_bytes + 1`` bytes are read, which is enough to
    tell that a file is too large without loading all of it.
    """
    cap = None if force_include or not max_file_bytes else max_file_bytes + 1
    return decode_source(
        read_regular_bytes(filepath, max_bytes=cap),
        filepath.name,
        max_bytes=max_file_bytes,
        force_include=force_include,
    )


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
    *,
    diagnostics: Optional[dict] = None,
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
    force_include: bool = False,
) -> list:
    """Read, chunk, and prepare drawer specs for one file without writing.

    Returns [] if the file is already mined or has nothing indexable (empty,
    binary, too large, or minified). When *diagnostics* is a dict it receives
    ``skip_reason`` (None when indexed), ``encoding``, and ``replaced_bytes``.
    Each spec dict has keys: id, content, metadata; ``content`` is an exact slice
    of the decoded source and ``line_start``/``line_end`` locate it.

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

    source = _read_source(filepath, max_file_bytes=max_file_bytes, force_include=force_include)
    if diagnostics is not None:
        diagnostics["skip_reason"] = source.skip_reason
        diagnostics["encoding"] = source.encoding
        diagnostics["replaced_bytes"] = source.replaced_bytes
    if source.skip_reason is not None:
        return []
    content = source.text

    language = detect_language(filepath, content)
    room = detect_room(filepath, content, rooms, project_path, csproj_room_map=csproj_room_map)
    chunks = chunk_file(content, filepath.suffix.lower(), source_file, language=language)

    specs = []
    previous_symbol = ("", "")
    for chunk in chunks:
        symbol_name = chunk.get("symbol_name")
        symbol_type = chunk.get("symbol_type")
        if symbol_name is None or symbol_type is None:
            symbol_name, symbol_type = extract_symbol(chunk["content"], language)
            if not symbol_name and chunk.get("continuation") and previous_symbol[0]:
                # A piece of an oversized declaration keeps its declaration's symbol.
                symbol_name, symbol_type = previous_symbol
        previous_symbol = (symbol_name, symbol_type)
        drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((source_file + str(chunk['chunk_index'])).encode(), usedforsecurity=False).hexdigest()[:16]}"
        markdown_metadata = chunk.get("markdown_metadata", {})

        specs.append(
            {
                "id": drawer_id,
                "content": chunk["content"],
                "metadata": {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file,
                    "chunk_index": chunk["chunk_index"],
                    "added_by": agent,
                    "ingest_mode": "file",
                    "filed_at": datetime.now().isoformat(),
                    "language": language,
                    "symbol_name": symbol_name,
                    "symbol_type": symbol_type,
                    **markdown_metadata,
                    "source_hash": source_hash,
                    "extractor_version": __version__,
                    "chunker_strategy": chunk.get("chunker_strategy", STRATEGY_REGEX_STRUCTURAL),
                    "line_start": chunk["line_start"],
                    "line_end": chunk["line_end"],
                },
            }
        )
    return specs


def add_drawers_batch(collection, specs: list, replace_sources=(), wing: str = "") -> int:
    """Embed and upsert a batch of drawer specs. Idempotent: re-mining the same
    file updates existing drawers in place instead of appending duplicates.

    Mined rows of *replace_sources* in *wing* that the batch does not rewrite are
    dropped in the same commit, so a reader never sees such a file without drawers.
    """
    if not specs:
        return 0
    ids = [s["id"] for s in specs]
    documents = [s["content"] for s in specs]
    metadatas = [s["metadata"] for s in specs]
    if replace_sources:
        collection.replace_mined_sources(
            replace_sources, wing, ids=ids, documents=documents, metadatas=metadatas
        )
    else:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
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


_MAX_LISTED_FILES = 10
# Sidecar hit reported without re-reading the file: it had nothing to index last time.
SKIP_UNCHANGED = "unchanged"


def _project_max_file_bytes(config: dict) -> Optional[int]:
    """Return the per-file byte cap from mempalace.yaml ``max_file_bytes`` (0 = no cap)."""
    value = config.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        print(
            f"  WARNING: ignoring invalid max_file_bytes {value!r} in mempalace.yaml "
            f"(expected an integer >= 0); using {DEFAULT_MAX_FILE_BYTES}.",
            file=sys.stderr,
        )
        return DEFAULT_MAX_FILE_BYTES
    return value or None


def _relative_label(path: Path, project_path: Path) -> str:
    try:
        return path.relative_to(project_path).as_posix()
    except ValueError:
        return str(path)


def _print_file_list(label: str, paths: list, project_path: Path) -> None:
    print(f"  {label}: {len(paths)}")
    for path in sorted(paths)[:_MAX_LISTED_FILES]:
        print(f"    - {_relative_label(Path(path), project_path)}")
    if len(paths) > _MAX_LISTED_FILES:
        print(f"    … and {len(paths) - _MAX_LISTED_FILES} more")


def _unsupported_summary(paths: list) -> str:
    counts: dict = defaultdict(int)
    for path in paths:
        counts[Path(path).suffix.lower() or "no extension"] += 1
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    return ", ".join(f"{suffix} {count}" for suffix, count in top)


def _shell_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def _mine_command(
    palace_path: str,
    project_path: Path,
    *,
    wing_override: str | None,
    agent: str,
    respect_gitignore: bool,
    include_paths: set,
    extra_include: str | None = None,
) -> str:
    """Return the shell command that repeats this mine with the caller's options."""
    parts = [*cli_prefix(), "--palace", os.path.abspath(palace_path), "mine", str(project_path)]
    if wing_override:
        parts += ["--wing", wing_override]
    if agent != "mempalace":
        parts += ["--agent", agent]
    if not respect_gitignore:
        parts.append("--no-gitignore")
    includes = set(include_paths)
    if extra_include:
        includes.add(extra_include)
    for include in sorted(includes):
        parts += ["--include-ignored", include]
    return " ".join(_shell_quote(part) for part in parts)


@holds_palace_write_lease("mine", on_acquire=prune_settled_versions)
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
    skip_invalid_source_symlinks: bool = False,
    symlink_diagnostics: Optional[list] = None,
    kg_path: Optional[str] = None,
    collection=None,
    warmup: bool = True,
):
    """Mine a project directory into the palace.

    When *incremental* is True (default), only files whose content hash has changed
    since the last mine are re-chunked. Files whose drawers were written by an older
    chunker strategy or whose text a pre-1.15.0 ``compress`` replaced, and files
    whose room changed because mempalace.yaml changed, are re-chunked too. Pass
    *incremental=False* (or --full from the CLI) to force a clean rebuild that
    re-chunks every file. Either mode sweeps drawers of files no
    longer discovered (deleted or newly excluded) after a full walk (limit == 0).
    Mining replaces only drawers it produced; manual and diary drawers that cite a
    mined file are never deleted.

    *kg* is an optional KnowledgeGraph instance. When provided, .NET project files
    (.csproj, .fsproj, .vbproj) and solution files (.sln) are also parsed for
    structured dependency triples that are written to the knowledge graph.

    *spellcheck* is accepted for shared CLI/config plumbing but ignored: project
    mining stores source files verbatim.

    When *skip_optimize* is True, post-mine storage compaction is skipped.  Callers
    (e.g. the watcher) that run many mine() calls in sequence should skip optimize
    on each call and run a single optimize at the end.

    *skip_invalid_source_symlinks* remains for call compatibility; source rejection is
    unconditional. *symlink_diagnostics* collects rejected paths and actual source kinds.

    *kg_path* is passed to ``optimize_store()`` for pre-optimize backups.  When None
    the backup module default, the palace's own ``<palace>/knowledge_graph.sqlite3``,
    is used.

    *collection* optionally injects an already-open drawer store.  Watchers use
    this to keep one store (and its lazy embedder) for their full lifecycle.
    Standalone callers retain the existing behavior when it is omitted.

    When *warmup* is False, mining uses the injected store without explicitly
    warming its embedding model.  This is for callers that have already warmed
    the same lifecycle-owned store.

    A KeyboardInterrupt saves the pending batch (a second one skips that save; one that
    arrives while a batch is embedding does not embed it again), prints what was filed, and is re-raised so callers can report the interruption (the CLI
    exits 130).
    """
    if limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")
    # One rule for every write surface: a blank or path-like wing is refused, never stored.
    validate_mine_arguments(wing_override, agent)

    palace_path = expand_palace_path(palace_path)
    project_path = Path(project_dir).expanduser().resolve()
    config = load_config(project_dir)

    wing = mine_wing(config, wing_override)
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])

    dotnet_structure = config.get("dotnet_structure", False)
    csproj_room_map: dict = {}
    if dotnet_structure:
        csproj_room_map = _build_csproj_room_map(project_path)

    max_file_bytes = _project_max_file_bytes(config)
    include_paths, include_warnings = resolve_include_paths(include_ignored, project_path)
    for warning in include_warnings:
        print(f"  WARNING: {warning}", file=sys.stderr)

    scan_rules = get_scan_filter_rules(MempalaceConfig())
    unsupported_files: list = []
    nested_roots: list = []
    files = scan_project(
        project_dir,
        respect_gitignore=respect_gitignore,
        include_ignored=sorted(include_paths),
        scan_rules=scan_rules,
        hard_exclude_dirs=_scan_hard_exclude_dirs(project_path, palace_path),
        skip_invalid_source_symlinks=skip_invalid_source_symlinks,
        symlink_diagnostics=symlink_diagnostics,
        unsupported_files=unsupported_files,
        nested_roots=nested_roots,
    )
    if limit > 0:
        files = files[:limit]
    # Stored drawers below a skipped nested checkout or unclassifiable .git marker are
    # never stale-swept by this run, even when the marker error clears meanwhile.
    skipped_prefixes = tuple(str(root) for root, _ in nested_roots)
    for root, kind in nested_roots:
        if kind != NESTED_GIT_ROOT:
            print(
                f"  WARNING: {root}: its .git marker could not be classified; the directory "
                "was not mined and its stored drawers are kept.",
                file=sys.stderr,
            )

    def force_included(path: Path) -> bool:
        return is_exact_force_include(path, project_path, include_paths)

    if dry_run:
        collection = _open_existing_store_read_only(palace_path)
    elif collection is None:
        collection = get_collection(palace_path)
    palace_wings = _existing_wings(collection) if collection is not None else set()
    if collection is not None:
        wing = settle_mine_wing(
            palace_wings,
            wing,
            wing_override,
            retry_command=lambda existing: _mine_command(
                palace_path,
                project_path,
                wing_override=existing,
                agent=agent,
                respect_gitignore=respect_gitignore,
                include_paths=include_paths,
            ),
        )

    fingerprint = _routing_fingerprint(config, rooms, dotnet_structure)
    stored_fingerprint = _load_config_fingerprint(palace_path, wing, project_path)
    config_changed = stored_fingerprint is not None and stored_fingerprint != fingerprint
    reroute_check = stored_fingerprint != fingerprint

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
    if include_paths:
        print(f"  Include: {', '.join(sorted(include_paths))}")
    if nested_roots:
        print(
            f"  Nested:  {len(nested_roots)} nested Git checkout(s) not mined "
            "(--include-ignored <path> mines one)"
        )
    if config_changed:
        print(
            "  Config:  room routing changed since the last mine (mempalace.yaml or "
            "routing rules) — re-applying rooms"
        )
    earlier_wings = _earlier_project_wings(palace_path, wing, project_path, palace_wings)
    if earlier_wings:
        names = ", ".join(repr(name) for name in earlier_wings)
        print(
            f"  Note:    this project was mined before into wing {names}; those drawers are "
            "not moved. Mine with that --wing to keep one copy, or delete the old wing "
            "(MCP mempalace_delete_wing) after checking what it holds."
        )
    print(f"{'─' * 55}\n")

    if not dry_run:
        from ..backup import reconcile_managed_backups

        reconcile_managed_backups(palace_path)

    # Pre-compute file hashes and the stale-sweep inventory for every full walk.
    # Incremental mode also uses them for no-op detection; running before warmup
    # lets a true no-op skip the embedding model entirely.
    _precomputed_hashes: dict = {}  # {source_file_str: hash} — populated below when useful
    existing_hashes: dict = {}
    stale_hashes: dict = {}
    stale_assessment_available = False
    protected_stale_sources: set[str] = set()
    tiny_hashes: dict = {}
    tiny_reasons: dict = {}  # {source_file: skip reason} for validated sidecar entries
    owned_tiny_sources: set[str] = set()
    needs_remine: set[str] = set()  # unchanged files that must be re-chunked anyway
    layout: dict = {}
    _hashes_loaded = False  # True when hashes were already fetched for the main loop
    files_failed = 0
    _hash_failed_paths: set[str] = set()
    # Technical copies identical to their filed canonical file, and stored copy or
    # nested-checkout sources paired with the canonical source they may repeat.
    copy_counterparts: dict = {}
    skipped_copies: set[str] = set()
    reconcile_pairs: list = []

    embedder_warmed = False

    def classify(path: Path) -> Optional[str]:
        """Return the current skip reason for a file, or None when it is indexable."""
        return _read_source(
            path, max_file_bytes=max_file_bytes, force_include=force_included(path)
        ).skip_reason

    def unchanged_needs_reroute(path: Path) -> bool:
        stored_rooms = layout.get(str(path), {}).get("rooms")
        if not stored_rooms:
            return False
        source = _read_source(path, max_file_bytes=max_file_bytes, force_include=True)
        room = detect_room(path, source.text, rooms, project_path, csproj_room_map=csproj_room_map)
        return stored_rooms != {room}

    if collection is not None and limit == 0:
        existing_hashes = _bulk_existing_file_hashes(collection, wing) or {}
        scoped_hashes = _bulk_existing_file_hashes(
            collection,
            wing,
            project_root=project_path,
            protected_source_files=protected_stale_sources,
        )
        stale_assessment_available = scoped_hashes is not None
        stale_hashes = {
            source_file: source_hash
            for source_file, source_hash in (scoped_hashes or {}).items()
            if not _under_prefixes(source_file, skipped_prefixes)
            and not _is_technical_copy_path(source_file, project_path)
        }
        if not stale_assessment_available:
            print(
                "  Stale-file sweep skipped: project provenance assessment unavailable; "
                "rerun this mine after resolving storage metadata access.",
                file=sys.stderr,
            )
        layout = _source_file_layout(collection, wing)
        # Re-validate the nothing-to-index sidecar whenever the rules that filled it may
        # differ: a changed or missing routing fingerprint (palaces from older releases
        # have none) or drawers from an older chunker.
        rules_changed = reroute_check or any(_stale_strategies(e) for e in layout.values())
        # A full rebuild starts a fresh tiny sidecar but still sweeps what the old one owned.
        stored_tiny_hashes = _load_tiny_hashes(palace_path, wing)
        tiny_hashes = dict(stored_tiny_hashes) if incremental else {}
        _hashes_loaded = True
        for _f in files:
            sf = str(_f)
            try:
                current = _file_hash(_f)
                _precomputed_hashes[sf] = current
                if not incremental:
                    continue
                if tiny_hashes.get(sf, "") == current and current:
                    if rules_changed or force_included(_f):
                        # Re-validate "nothing to index" under the current rules (an
                        # older chunker skipped small files; the byte cap may have moved).
                        reason = classify(_f)
                        if reason is None:
                            tiny_hashes.pop(sf, None)
                        else:
                            tiny_reasons[sf] = reason
                elif existing_hashes.get(sf, "") == current and current:
                    if _needs_rechunk(layout.get(sf, {})):
                        needs_remine.add(sf)
                    elif reroute_check and unchanged_needs_reroute(_f):
                        needs_remine.add(sf)
            except OSError as exc:
                _warn_source_read_error(_f, exc)
                files_failed += 1
                _hash_failed_paths.add(sf)
                _precomputed_hashes.pop(sf, None)
                continue
        _walked_set = {str(path) for path in files}
        # Stored technical sources stay candidates when default scans prune their roots.
        copy_counterparts = _technical_copy_counterparts(files, project_path, existing_hashes)
        # Commit primary files before considering their technical copies, including
        # the first mine of an empty palace. Unique reports keep their normal order.
        files.sort(key=lambda path: str(path) in copy_counterparts)
        skipped_copies = {
            copy_file
            for copy_file, counterpart in copy_counterparts.items()
            if not is_force_included(Path(copy_file), project_path, include_paths)
            and _precomputed_hashes.get(copy_file) is not None
            and _precomputed_hashes.get(copy_file) == _precomputed_hashes.get(counterpart)
            and existing_hashes.get(counterpart) == _precomputed_hashes.get(copy_file)
        }
        needs_remine.difference_update(skipped_copies)
        reconcile_pairs = [
            pair
            for pair in _generated_copy_pairs(
                existing_hashes, nested_roots, copy_counterparts, project_path, _walked_set
            )
            if not is_force_included(Path(pair[0]), project_path, include_paths)
        ]
        _any_changed = bool(needs_remine) or any(
            not (
                (existing_hashes.get(sf, "") == h and existing_hashes.get(sf, "") != "")
                or (tiny_hashes.get(sf, "") == h and tiny_hashes.get(sf, "") != "")
            )
            for sf, h in _precomputed_hashes.items()
            if sf not in skipped_copies
        )
        owned_tiny_sources = {
            source_file
            for source_file in _owned_tiny_sources(
                stored_tiny_hashes, project_path, protected_stale_sources
            )
            if not _under_prefixes(source_file, skipped_prefixes)
            and not _is_technical_copy_path(source_file, project_path)
        }
        _any_deleted = stale_assessment_available and bool(
            (set(stale_hashes) | owned_tiny_sources) - _walked_set
        )
        if (
            not dry_run
            and incremental
            and stale_assessment_available
            and not _any_changed
            and not _any_deleted
            and not config_changed
        ):
            copy_reconcile = _run_copy_reconcile(
                collection, wing, reconcile_pairs, palace_path, kg_path, skip_optimize
            )
            elapsed = time.time() - mine_start
            mins, secs = divmod(int(elapsed), 60)
            _tiny_count = sum(
                1
                for sf, h in _precomputed_hashes.items()
                if tiny_hashes.get(sf, "") == h and tiny_hashes.get(sf, "") != ""
            )
            _skip_count = len(_precomputed_hashes) - _tiny_count
            print(f"\n{'=' * 55}")
            print("  Done. (incremental — no changes detected)")
            print(f"  Files skipped (already filed): {_skip_count}")
            if _tiny_count:
                print(f"  Files skipped (nothing to index, unchanged): {_tiny_count}")
            if unsupported_files:
                print(
                    f"  Files not scanned (unsupported type): {len(unsupported_files)} "
                    f"({_unsupported_summary(unsupported_files)})"
                )
            if files_failed:
                print(f"  Files failed to read: {files_failed}")
            _print_copy_summary(len(skipped_copies), copy_reconcile)
            print("  Drawers filed: 0")
            print(f"  Time: {mins}m {secs}s")
            print(f"{'=' * 55}\n")
            _save_config_fingerprint(palace_path, wing, project_path, fingerprint)
            skipped_reasons: dict = defaultdict(int)
            for sf, h in _precomputed_hashes.items():
                if tiny_hashes.get(sf, "") == h and h:
                    skipped_reasons[tiny_reasons.get(sf, SKIP_UNCHANGED)] += 1
            return {
                "files_processed": 0,
                "files_skipped": _skip_count,
                "files_tiny": _tiny_count,
                "files_skipped_by_reason": dict(skipped_reasons),
                "files_lossy_decoded": 0,
                "files_failed": files_failed,
                "files_unsupported": len(unsupported_files),
                "drawers_filed": 0,
                "stale_files_removed": 0,
                "stale_drawers_removed": 0,
                "stale_sources_removed": [],
                "nested_roots_skipped": len(nested_roots),
                "copy_files_skipped": len(skipped_copies),
                **copy_reconcile,
                "elapsed_secs": elapsed,
                "embedder_warmed": False,
            }

    if not dry_run:
        assert collection is not None
        # A corrupt or read-only KG must stop the run before the first drawer delete;
        # a failure inside the file loop would leave that file's drawers deleted.
        check_kg = getattr(kg, "check_writable", None)
        if check_kg is not None:
            check_kg()
        if warmup:
            print("  Loading embedding model...", flush=True)
            collection.warmup()
            embedder_warmed = True
            print("  Model ready.\n", flush=True)
        if not _hashes_loaded:
            existing_hashes = _bulk_existing_file_hashes(collection, wing) or {}
            layout = _source_file_layout(collection, wing)
            # Tiny files produce no drawers so their hashes live in a sidecar. Load it
            # for incremental runs; start fresh for full rebuilds so the sidecar is
            # rebuilt from scratch.
            tiny_hashes = _load_tiny_hashes(palace_path, wing) if incremental else {}

    total_drawers = 0
    files_processed = 0
    files_skipped = 0
    skipped_by_reason: dict = defaultdict(list)  # {reason: [source_file, ...]}
    lossy_files: list = []
    stale_files_removed = 0
    stale_drawers_removed = 0
    stale_sources_removed: list = []
    room_counts = defaultdict(int)
    copies_skipped = 0
    copy_reconcile = _no_copy_reconcile()
    batch_buffer: list = []
    # Files whose old mined drawers are replaced when their batch is written.
    pending_replace: set = set()
    # Empty replacements have no batch to commit; remove them only after all writes succeed.
    pending_empty_sources: dict = {}
    batch_num = 0
    walked_paths: set = set()
    completed = False
    kg_file_facts = 0
    kg_facts_inserted = 0
    kg_facts_expired = 0

    embedding_in_flight = False

    def flush_batch() -> None:
        nonlocal total_drawers, batch_num, embedding_in_flight
        batch_num += 1
        count = len(batch_buffer)
        print(
            f"  >> Embedding batch {batch_num} ({count} chunks)...",
            end="",
            flush=True,
        )
        t0 = time.time()
        batch_sources = {spec["metadata"]["source_file"] for spec in batch_buffer}
        replacing = sorted(batch_sources & pending_replace)
        embedding_in_flight = True
        total_drawers += add_drawers_batch(
            collection, batch_buffer, replace_sources=replacing, wing=wing
        )
        for spec in batch_buffer:
            metadata = spec["metadata"]
            existing_hashes[metadata["source_file"]] = metadata["source_hash"]
        embedding_in_flight = False
        pending_replace.difference_update(replacing)
        elapsed = time.time() - t0
        print(f" done ({elapsed:.1f}s)", flush=True)
        batch_buffer.clear()

    try:
        for i, filepath in enumerate(files, 1):
            source_file = str(filepath)
            walked_paths.add(source_file)

            if source_file in _hash_failed_paths:
                continue

            counterpart = copy_counterparts.get(source_file)
            if counterpart is not None and not is_force_included(
                filepath, project_path, include_paths
            ):
                expected = _precomputed_hashes.get(source_file)
                if batch_buffer and existing_hashes.get(counterpart) != expected:
                    flush_batch()
                if (
                    expected
                    and counterpart not in pending_empty_sources
                    and existing_hashes.get(counterpart) == expected
                ):
                    try:
                        same_current_bytes = (
                            _file_hash(filepath) == expected
                            and _file_hash(Path(counterpart)) == expected
                        )
                    except OSError:
                        same_current_bytes = False
                    if same_current_bytes:
                        copies_skipped += 1
                        continue

            # Print scanning progress every 100 files so large repos aren't silent
            if not dry_run and (i % 100 == 0 or i == 1):
                print(
                    f"  Scanning [{i:4}/{len(files)}]...",
                    end="\r",
                    flush=True,
                )

            try:
                current_hash = _precomputed_hashes.get(source_file) or _file_hash(filepath)
            except OSError as exc:
                _warn_source_read_error(filepath, exc)
                files_failed += 1
                continue

            if incremental and source_file not in needs_remine:
                stored_hash = existing_hashes.get(source_file, "")
                if stored_hash == current_hash and stored_hash != "":
                    if not _needs_rechunk(layout.get(source_file, {})):
                        # File unchanged (has current drawers) — skip
                        files_skipped += 1
                        continue
                # Check the tiny-file sidecar before paying for a full chunk pass.
                tiny_stored_hash = tiny_hashes.get(source_file, "")
                if tiny_stored_hash == current_hash and tiny_stored_hash != "":
                    reason = tiny_reasons.get(source_file)
                    if reason is None and not _hashes_loaded and force_included(filepath):
                        try:
                            reason = classify(filepath)
                        except OSError as exc:
                            _warn_source_read_error(filepath, exc)
                            files_failed += 1
                            continue
                        if reason is None:
                            tiny_hashes.pop(source_file, None)
                    if source_file in tiny_hashes:
                        # Unchanged and still has nothing indexable — skip re-processing.
                        skipped_by_reason[reason or SKIP_UNCHANGED].append(source_file)
                        continue

            diagnostics: dict = {}
            try:
                specs = _collect_specs_for_file(
                    filepath,
                    project_path,
                    collection,
                    wing,
                    rooms,
                    agent,
                    mined_files=set(),
                    source_hash=current_hash,
                    csproj_room_map=csproj_room_map,
                    diagnostics=diagnostics,
                    max_file_bytes=max_file_bytes,
                    force_include=force_included(filepath),
                )
            except OSError as exc:
                _warn_source_read_error(filepath, exc)
                files_failed += 1
                continue

            if diagnostics.get("replaced_bytes") and diagnostics.get("skip_reason") is None:
                lossy_files.append(source_file)
                print(
                    f"  WARNING: {filepath}: not valid UTF-8 and no usable coding declaration; "
                    f"{diagnostics['replaced_bytes']} undecodable byte(s) stored as U+FFFD",
                    file=sys.stderr,
                )

            if dry_run:
                if not specs:
                    skipped_by_reason[diagnostics.get("skip_reason") or "empty"].append(source_file)
                    continue
                files_processed += 1
                total_drawers += len(specs)
                room = specs[0]["metadata"]["room"]
                room_counts[room] += 1
                print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(specs)} drawers)")
                continue

            assert collection is not None
            replaces_rows = (
                not incremental or source_file in existing_hashes or source_file in needs_remine
            )
            if replaces_rows and not specs:
                pending_empty_sources[source_file] = current_hash
            elif replaces_rows:
                # The old drawers stay readable until the batch that holds the new ones
                # replaces them in one commit (see add_drawers_batch).
                pending_replace.add(source_file)

            # KG facts for project/config/XAML/source files: unchanged facts keep their
            # rows and facts no longer extracted expire. Architecture facts are refreshed
            # by the architecture pass below.
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
                synced = kg.sync_facts(
                    [(subj, pred, obj, source_file) for subj, pred, obj in triples],
                    source_files=[source_file],
                    exclude_predicates=ARCH_PREDICATES,
                )
                if isinstance(synced, dict):
                    kg_facts_inserted += _expired_count(synced.get("inserted"))
                    kg_facts_expired += _expired_count(synced.get("expired"))
                kg_file_facts += len(set(triples))

            if not specs:
                # A pending deletion must stay retryable if an interrupt saves the sidecar.
                if replaces_rows:
                    tiny_hashes.pop(source_file, None)
                else:
                    tiny_hashes[source_file] = current_hash
                skipped_by_reason[diagnostics.get("skip_reason") or "empty"].append(source_file)
                continue

            # File produced chunks — remove any stale tiny-hash entry.
            tiny_hashes.pop(source_file, None)
            files_processed += 1
            room = specs[0]["metadata"]["room"]
            room_counts[room] += 1
            print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} +{len(specs)}")

            batch_buffer.extend(specs)
            if len(batch_buffer) >= get_batch_size():
                flush_batch()

        if dry_run and limit == 0 and stale_assessment_available:
            stale_files_removed = len(
                (set(stale_hashes) | owned_tiny_sources) - walked_paths - protected_stale_sources
            )

        if not dry_run:
            assert collection is not None
            if batch_buffer:
                flush_batch()

            for source_file in sorted(pending_empty_sources):
                removed = collection.delete_by_source_file(source_file, wing, mined_rows_only=True)
                if removed:
                    stale_drawers_removed += removed
                    stale_files_removed += 1
                tiny_hashes[source_file] = pending_empty_sources[source_file]

            # Stale-file sweep: remove drawers for files no longer on disk.
            # Only safe when the full file set was walked (limit == 0).
            if limit == 0 and stale_assessment_available:
                stale_paths = set(stale_hashes) - walked_paths
                stale_tiny_paths = owned_tiny_sources - walked_paths
                sweep_succeeded = True
                if stale_paths:
                    try:
                        deleted = collection.delete_by_source_files(
                            stale_paths, wing, project_root=project_path
                        )
                    except Exception as exc:
                        sweep_succeeded = False
                        print(f"  Stale-file sweep failed: {exc}", file=sys.stderr)
                    else:
                        stale_drawers_removed += deleted
                        stale_files_removed += len(stale_paths)
                        # Only the swept (deleted or excluded) sources; now-skipped files
                        # counted above still exist on disk.
                        stale_sources_removed = sorted(stale_paths)
                        if deleted < len(stale_paths):
                            sweep_succeeded = False
                            print(
                                "  Stale-file sweep incomplete: scoped bulk deletion was not "
                                "supported or did not remove every assessed source.",
                                file=sys.stderr,
                            )
                if sweep_succeeded:
                    for stale_path in stale_paths | stale_tiny_paths:
                        if (
                            kg is not None
                            and Path(stale_path).suffix.lower() in _KG_EXTRACT_EXTENSIONS
                        ):
                            # A manual drawer can still name a vanished file: keep the facts
                            # it protects, but always expire what mining extracted from it.
                            kg_facts_expired += _expired_count(
                                kg.invalidate_by_source_file(
                                    stale_path,
                                    predicates=sorted(FILE_KG_PREDICATES)
                                    if stale_path in protected_stale_sources
                                    else None,
                                )
                            )
                    for stale_tiny in stale_tiny_paths:
                        tiny_hashes.pop(stale_tiny, None)

            # Exact generated copies of filed project files: drawer rows only, never KG.
            if limit == 0:
                copy_reconcile = _run_copy_reconcile(
                    collection,
                    wing,
                    reconcile_pairs,
                    palace_path,
                    kg_path,
                    skip_optimize,
                    retry_maintenance=False,
                )

            # Architecture extraction pass: derive pattern/layer/namespace/project
            # KG facts from the full walked file set.  Runs after the stale sweep so
            # deleted-file triples are already expired before we re-emit.
            if kg is not None and limit == 0:
                from mempalace_code.architecture import (
                    _NS_PROJECT_SENTINEL,
                    arch_facts,
                    extract_type_inventory,
                    load_arch_config,
                    namespace_project_source_file,
                    refresh_arch_facts,
                )

                arch_cfg = load_arch_config(config)
                # Migration: pre-WING-SCOPE releases stored namespace→project rows
                # under a single shared sentinel without the wing suffix.  Expire
                # only this wing's legacy rows (scoped by the in_project object) so
                # other wings' legacy data persists until those wings are mined.
                kg_facts_expired += _expired_count(
                    kg.invalidate_legacy_arch_ns_project_for_wing(_NS_PROJECT_SENTINEL, wing)
                )
                inventory = (
                    extract_type_inventory([Path(f) for f in walked_paths], project_path)
                    if arch_cfg.get("enabled", True)
                    else []
                )
                # Diff against this wing's current architecture facts only: other wings'
                # facts survive, unchanged facts keep their rows, removed ones expire.
                if skipped_prefixes or any(
                    _is_technical_copy_path(source, project_path) for source in existing_hashes
                ):
                    desired = arch_facts(inventory, arch_cfg, wing)
                    # Closed facts stay closed. Existing unique support under newly
                    # excluded/unreadable prefixes must survive this full-root sync.
                    protected_namespaces = set()
                    for predicate in ARCH_PREDICATES:
                        for fact in kg.query_relationship(predicate):
                            source = fact.get("source_file") or ""
                            protected = _under_prefixes(source, skipped_prefixes) or (
                                _is_technical_copy_path(source, project_path)
                                and source not in walked_paths
                            )
                            if fact.get("valid_to") is None and protected:
                                if predicate == "in_namespace":
                                    protected_namespaces.add(fact["object"])
                                desired.append(
                                    (
                                        fact["subject"],
                                        predicate,
                                        fact["object"],
                                        fact["source_file"],
                                    )
                                )
                    for fact in kg.query_relationship("in_project"):
                        if (
                            fact.get("valid_to") is None
                            and fact.get("source_file") == namespace_project_source_file(wing)
                            and fact["subject"] in protected_namespaces
                            and fact["object"] == wing
                        ):
                            desired.append(
                                (fact["subject"], "in_project", wing, fact["source_file"])
                            )
                    arch = kg.sync_facts(
                        desired,
                        source_files=[namespace_project_source_file(wing)],
                        project_root=str(project_path),
                        predicates=list(ARCH_PREDICATES),
                    )
                else:
                    arch = refresh_arch_facts(inventory, arch_cfg, wing, project_path, kg)
                # New and expired count every KG change of this run: file facts, facts of
                # deleted files, legacy rows, and architecture facts.
                inserted = arch["inserted"] + kg_facts_inserted
                expired = arch["expired"] + kg_facts_expired
                if kg_file_facts or arch["facts"] or inserted or expired:
                    print(
                        f"  >> Knowledge graph: {kg_file_facts} file facts extracted, "
                        f"{arch['facts']} architecture facts ({inserted} new, "
                        f"{expired} expired)",
                        flush=True,
                    )

            app_config = MempalaceConfig()
            if not skip_optimize and copy_reconcile.get("copy_disk") is None:
                if app_config.optimize_after_mine:
                    t0 = time.time()
                    backup_first = app_config.backup_before_optimize
                    if backup_first:
                        print("  >> Backing up before optimize...", flush=True)
                    print("  >> Optimizing storage...", end="", flush=True)
                    result = optimize_store(
                        collection, palace_path, backup_first=backup_first, kg_path=kg_path
                    )
                    if result.ok:
                        print(f" done ({time.time() - t0:.1f}s)", flush=True)
                    else:
                        print(
                            f"\n  !! WARNING: optimize failed or verification error ({time.time() - t0:.1f}s)",
                            flush=True,
                        )
                else:
                    print("  >> Skipping optimize (disabled in config)", flush=True)
        completed = True
    except KeyboardInterrupt:
        if embedding_in_flight:
            # Embedding that batch again would keep Ctrl-C waiting for a second full
            # pass; the rerun below files those chunks instead.
            print(
                f"\n\n  Interrupted while embedding batch {batch_num}; its "
                f"{len(batch_buffer)} chunks may not have been filed (their files stay "
                "out of search until the next mine embeds them again).",
                flush=True,
            )
        else:
            print("\n\n  Interrupted.", flush=True)
            if batch_buffer and not dry_run:
                print(
                    f"  Saving the {len(batch_buffer)} pending chunks; press Ctrl-C again to "
                    "stop now (their files stay out of search until the next mine embeds "
                    "them again).",
                    flush=True,
                )
                try:
                    flush_batch()
                except KeyboardInterrupt:
                    # Batches hold whole files and writes are upserts, so an incremental
                    # rerun re-mines exactly the files whose chunks were not saved.
                    print(
                        f"\n  Stopped without saving {len(batch_buffer)} pending chunks.",
                        flush=True,
                    )
        print(f"  {total_drawers} drawers filed before interrupt.")
        if not dry_run:
            _save_tiny_hashes(palace_path, wing, tiny_hashes)
        rerun = _mine_command(
            palace_path,
            project_path,
            wing_override=wing_override,
            agent=agent,
            respect_gitignore=respect_gitignore,
            include_paths=include_paths,
        )
        print(f"  Mine interrupted; rerun to finish (incremental resumes): {rerun}", flush=True)
        raise

    elapsed = time.time() - mine_start
    mins, secs = divmod(int(elapsed), 60)

    print(f"\n{'=' * 55}")
    print("  Done. (dry run — nothing filed)" if dry_run else "  Done.")
    print(f"  Files processed: {files_processed}")
    print(f"  Files skipped (already filed): {files_skipped}")
    unchanged = skipped_by_reason.get(SKIP_UNCHANGED, [])
    if unchanged:
        print(f"  Files skipped (nothing to index, unchanged): {len(unchanged)}")
    for reason, label in SKIP_REASON_LABELS.items():
        paths = skipped_by_reason.get(reason, [])
        if not paths:
            continue
        if reason == SKIP_EMPTY:
            print(f"  Files skipped ({label}): {len(paths)}")
        elif reason == SKIP_TOO_LARGE:
            _print_file_list(
                f"Files skipped ({label}, over {max_file_bytes or 0:,} bytes)", paths, project_path
            )
        else:
            _print_file_list(f"Files skipped ({label})", paths, project_path)
    too_large = sorted(skipped_by_reason.get(SKIP_TOO_LARGE, []))
    oversized = too_large or sorted(
        skipped_by_reason.get(SKIP_MINIFIED, []) + skipped_by_reason.get(SKIP_SECRET, [])
    )
    if oversized:
        example = _relative_label(Path(oversized[0]), project_path)
        command = _mine_command(
            palace_path,
            project_path,
            wing_override=wing_override,
            agent=agent,
            respect_gitignore=respect_gitignore,
            include_paths=include_paths,
            extra_include=example,
        )
        byte_cap = " (or raise max_file_bytes in mempalace.yaml)" if too_large else ""
        print(f"    To index one anyway: {command}{byte_cap}")
    if lossy_files:
        _print_file_list(
            "Files decoded lossily (not valid UTF-8; bytes replaced with U+FFFD)",
            lossy_files,
            project_path,
        )
    if unsupported_files:
        print(
            f"  Files not scanned (unsupported type): {len(unsupported_files)} "
            f"({_unsupported_summary(unsupported_files)})"
        )
    if stale_files_removed:
        if dry_run:
            print(f"  Stale files a real run would sweep: {stale_files_removed}")
        else:
            print(
                f"  Stale drawers removed: {stale_drawers_removed} "
                f"({stale_files_removed} deleted, excluded or now-skipped file(s))"
            )
    if files_failed:
        print(f"  Files failed to read: {files_failed}")
    _print_copy_summary(copies_skipped, copy_reconcile)
    print(f"  Drawers {'that would be filed' if dry_run else 'filed'}: {total_drawers}")
    print(f"  Time: {mins}m {secs}s")
    if room_counts:
        print("\n  By room:")
        for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"    {room:20} {count} files")
    print(f"\n  Next: {cli_command('search', 'what you are looking for', palace=palace_path)}")
    print(f"{'=' * 55}\n")

    if not dry_run:
        _save_tiny_hashes(palace_path, wing, tiny_hashes)
        if completed and limit == 0:
            _save_config_fingerprint(palace_path, wing, project_path, fingerprint)

    files_tiny = sum(len(paths) for paths in skipped_by_reason.values())
    return {
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "files_tiny": files_tiny,
        "files_skipped_by_reason": {
            reason: len(paths) for reason, paths in skipped_by_reason.items() if paths
        },
        "files_lossy_decoded": len(lossy_files),
        "files_unsupported": len(unsupported_files),
        "files_failed": files_failed,
        "drawers_filed": total_drawers,
        "stale_files_removed": stale_files_removed,
        "stale_drawers_removed": stale_drawers_removed,
        "stale_sources_removed": stale_sources_removed,
        "nested_roots_skipped": len(nested_roots),
        "copy_files_skipped": copies_skipped,
        **copy_reconcile,
        "elapsed_secs": elapsed,
        "embedder_warmed": embedder_warmed,
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


def status(palace_path: str, summary: bool = False) -> bool:
    """Show what's been filed in the palace; return False when there is no palace.

    When *summary* is True, print only a fixed set of bounded metrics
    (drawer count, wing count, room-pair count, plus storage/version
    metrics) instead of enumerating every wing/room pair. Output size then
    stays constant regardless of taxonomy cardinality, unlike the default
    detailed report below.
    """
    from ..storage import LanceStore

    lance_dir = os.path.join(palace_path, "lance")
    if is_legacy_chroma_palace(palace_path):
        raise ChromaRuntimeRetiredError(CHROMA_RUNTIME_RETIRED_MESSAGE)
    if not os.path.isdir(lance_dir):
        print(f"\n  No palace found at {palace_path}")
        print(f"  Next: {no_palace_next_step(palace_path)}.")
        return False

    store = open_store(palace_path, create=False, read_only=True)

    if isinstance(store, LanceStore) and store._table is None:
        print(f"\n  No palace found at {palace_path}")
        print(f"  Next: {no_palace_next_step(palace_path)}.")
        return False

    # Count by wing and room
    total = store.count()
    wing_rooms = store.count_by_pair("wing", "room")

    if summary:
        wing_count = len(wing_rooms)
        room_pair_count = sum(len(rooms) for rooms in wing_rooms.values())
        print(f"\n{'=' * 55}")
        print("  MemPalace Status Summary")
        print(f"{'=' * 55}\n")
        print(f"  Drawers: {total}")
        print(f"  Wings: {wing_count}")
        print(f"  Room pairs: {room_pair_count}")
    else:
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
    return True
