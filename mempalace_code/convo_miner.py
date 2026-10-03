#!/usr/bin/env python3
"""
convo_miner.py — Mine conversations into the palace.

Ingests chat exports (Claude Code, Codex, Gemini, ChatGPT, Claude.ai, Slack, plain text
transcripts). Normalizes format, chunks by exchange (user turn + answer = one unit),
files to palace.

Verbatim-first: every non-blank transcript line is stored, with its line breaks, in
exactly one exchange drawer. Long exchanges are split at paragraph boundaries into
several drawers; units too short to stand alone are merged into a neighbour.

Same palace as project mining. Different ingest strategy.
"""

import hashlib
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, NoReturn, Optional

from .cli_invocation import cli_command
from .config import MempalaceConfig, expand_palace_path
from .mining.batching import get_batch_size
from .mining.orchestrator import add_drawers_batch
from .normalize import NotAConversationError, normalize
from .operation_lock import holds_palace_write_lease
from .source_io import is_regular_source_path, read_regular_bytes, regular_source_diagnostic
from .storage import is_legacy_compressed, open_store, optimize_store, prune_settled_versions
from .version import __version__

# File types that might contain conversations
CONVO_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
}

# Directory names the scan does not enter. Skipped directories are reported, and a
# skipped directory can still be mined by passing it to `mine` directly.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    ".mempalace",
    "tool-results",
    "memory",
}

# Inside a transcript, a unit shorter than this is merged into a neighbour, never
# dropped. A whole transcript is filed however short it is; only one with no text left
# after normalization is skipped, and named.
MIN_CHUNK_SIZE = 30
# Soft drawer size: longer exchanges are split at paragraph or line boundaries.
MAX_CHUNK_CHARS = 1500

# Bump a strategy whenever its chunking changes: rows stamped with another strategy
# are rebuilt by the next mine, incremental or not.
# v3: only a user turn's first line carries the "> " marker, and Claude Code interrupt
# notices, shell-mode wrappers, block/part boundaries, and byte-order marks are
# normalized as documented.
EXCHANGE_CHUNKER_STRATEGY = "convo_turn_v3"
GENERAL_CHUNKER_STRATEGY = "convo_general_v2"
_STRATEGY_BY_MODE = {
    "exchange": EXCHANGE_CHUNKER_STRATEGY,
    "general": GENERAL_CHUNKER_STRATEGY,
}

# General-extraction memory types, named like the exchange-mode rooms.
GENERAL_ROOMS = {
    "decision": "decisions",
    "preference": "preferences",
    "milestone": "milestones",
    "problem": "problems",
    "emotional": "emotional",
}

_DELETE_BATCH = 500


# =============================================================================
# CHUNKING — exchange pairs for conversations
# =============================================================================

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_USER_SPEAKER_RE = re.compile(r"^\s*(?:user|human|you|me)\s*:", re.IGNORECASE)
_ASSISTANT_SPEAKER_RE = re.compile(
    r"^\s*(?:assistant|ai|claude|chatgpt|gpt|gemini|codex|copilot|bot)\s*:", re.IGNORECASE
)
# Claude Code terminal session banner, e.g. "▐▛███▜▌   Claude Code v2.0.14".
_SESSION_BANNER_RE = re.compile(r"^\s*[^\w\s>].*\bClaude Code v\d")

# A segment is a half-open line range [start, end) with a kind: "turn" (a user turn
# and the answer that follows) or "lead" (text before a turn: preamble or banner).
_Segment = tuple[int, int, str]


def chunk_exchanges(content: str) -> list:
    """Chunk a conversation into drawer-sized units without dropping text.

    One user turn plus the answer that follows is one unit. Text before the first
    turn is kept and merged into the first exchange when it fits. A unit longer than
    MAX_CHUNK_CHARS is split at paragraph (else line) boundaries, keeping fenced code
    together where possible; a unit shorter than MIN_CHUNK_SIZE is merged into a
    neighbour. Every line keeps its line breaks.

    A transcript normalized from a structured export carries its ``(role, text)``
    turns, so multi-line user messages and answer lines starting with ``>`` keep
    their roles. Plain text uses ``>`` user turns, else ``User:``/``Assistant:``
    speaker prefixes, else packs paragraphs.
    """
    messages = getattr(content, "messages", None)
    if messages:
        lines, segments = _segments_from_messages(messages)
    else:
        lines = content.split("\n")
        segments = _segments_from_text(lines)
    return _chunks_from_segments(lines, segments)


def _is_marker_line(line: str) -> bool:
    return line.strip().startswith(">")


def _segments_from_messages(messages) -> tuple[list[str], list[_Segment]]:
    """Render structured turns: a user turn's first line marked with '> ', the rest verbatim.

    The message list already says where each turn starts, so lines after the first
    keep their text exactly as written (pasted code or configs stay copyable).
    """
    lines: list[str] = []
    segments: list[_Segment] = []
    start, kind = 0, "lead"
    previous_role = ""
    for role, text in messages:
        text_lines = str(text).split("\n")
        if role == "user":
            if len(lines) > start:
                segments.append((start, len(lines), kind))
            if lines:
                lines.append("")
            start, kind = len(lines), "turn"
            lines.append(f"> {text_lines[0]}")
            lines.extend(text_lines[1:])
        else:
            if previous_role and previous_role != "user":
                lines.append("")
            lines.extend(text_lines)
        previous_role = role
    if len(lines) > start:
        segments.append((start, len(lines), kind))
    return lines, segments


def _segments_from_text(lines: list[str]) -> list[_Segment]:
    """Find exchange boundaries in a plain-text transcript."""
    if any(_is_marker_line(line) for line in lines):

        def is_turn_start(i: int) -> bool:
            return _is_marker_line(lines[i]) and not (i > 0 and _is_marker_line(lines[i - 1]))

    elif any(_USER_SPEAKER_RE.match(line) for line in lines) and any(
        _ASSISTANT_SPEAKER_RE.match(line) for line in lines
    ):

        def is_turn_start(i: int) -> bool:
            return bool(_USER_SPEAKER_RE.match(lines[i]))

    else:
        # No turn markers: one unit, packed into paragraph-bounded drawers.
        return [(0, len(lines), "lead")]

    segments: list[_Segment] = []
    start, kind = 0, "lead"
    for i, line in enumerate(lines):
        if is_turn_start(i):
            new_kind = "turn"
        elif _SESSION_BANNER_RE.match(line):
            new_kind = "lead"
        else:
            continue
        if i > start:
            segments.append((start, i, kind))
        start, kind = i, new_kind
    segments.append((start, len(lines), kind))
    return segments


def _chunks_from_segments(lines: list[str], segments: list[_Segment]) -> list:
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)

    def size(start: int, end: int) -> int:
        return offsets[end] - offsets[start] - 1

    # Blank lines outside fenced code are paragraph breaks; a line that starts
    # outside a fence is a safe place to cut when no paragraph break fits.
    breakable: list[bool] = []
    outside: list[bool] = []
    in_fence = False
    for line in lines:
        outside.append(not in_fence)
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            breakable.append(False)
        else:
            breakable.append(not in_fence and not line.strip())
    outside.append(True)

    min_piece = MAX_CHUNK_CHARS // 3

    def best_cut(start: int, i: int) -> tuple[int, int]:
        for j in range(i - 1, start, -1):
            if breakable[j] and size(start, j) >= min_piece:
                return j, j + 1
        for j in range(i, start, -1):
            if outside[j] and size(start, j) >= min_piece:
                return j, j
        return i, i

    def trim(start: int, end: int) -> tuple[int, int]:
        while start < end and not lines[start].strip():
            start += 1
        while end > start and not lines[end - 1].strip():
            end -= 1
        return start, end

    pieces: list[list] = []
    for seg_start, seg_end, kind in segments:
        start = seg_start
        for i in range(seg_start, seg_end):
            while i > start and size(start, i + 1) > MAX_CHUNK_CHARS:
                cut, resume = best_cut(start, i)
                s, e = trim(start, cut)
                if s < e:
                    pieces.append([s, e, kind])
                start = resume
        s, e = trim(start, seg_end)
        if s < e:
            pieces.append([s, e, kind])

    # Text before a turn (preamble, session banner) joins that turn when it fits.
    merged: list[list] = []
    for piece in pieces:
        if merged and merged[-1][2] == "lead" and piece[2] == "turn":
            if size(merged[-1][0], piece[1]) <= MAX_CHUNK_CHARS:
                merged[-1] = [merged[-1][0], piece[1], "turn"]
                continue
        merged.append(piece)

    # Units too short to stand alone join the previous drawer (or the next one).
    result: list[list] = []
    carry: Optional[list] = None
    for piece in merged:
        if carry is not None:
            piece = [carry[0], piece[1], piece[2]]
            carry = None
        if len("\n".join(lines[piece[0] : piece[1]]).strip()) < MIN_CHUNK_SIZE:
            if result:
                result[-1][1] = piece[1]
            else:
                carry = piece
            continue
        result.append(piece)
    if carry is not None:
        result.append(carry)

    return [
        {"content": "\n".join(lines[start:end]), "chunk_index": index}
        for index, (start, end, _kind) in enumerate(result)
    ]


# =============================================================================
# ROOM DETECTION — topic-based for conversations
# =============================================================================

TOPIC_KEYWORDS = {
    "technical": [
        "code",
        "python",
        "function",
        "bug",
        "error",
        "api",
        "database",
        "server",
        "deploy",
        "git",
        "test",
        "debug",
        "refactor",
    ],
    "architecture": [
        "architecture",
        "design",
        "pattern",
        "structure",
        "schema",
        "interface",
        "module",
        "component",
        "service",
        "layer",
    ],
    "planning": [
        "plan",
        "roadmap",
        "milestone",
        "deadline",
        "priority",
        "sprint",
        "backlog",
        "scope",
        "requirement",
        "spec",
    ],
    "decisions": [
        "decided",
        "chose",
        "picked",
        "switched",
        "migrated",
        "replaced",
        "trade-off",
        "alternative",
        "option",
        "approach",
    ],
    "problems": [
        "problem",
        "issue",
        "broken",
        "failed",
        "crash",
        "stuck",
        "workaround",
        "fix",
        "solved",
        "resolved",
    ],
}


def detect_convo_room(content: str) -> str:
    """Score conversation content against topic keywords."""
    content_lower = content[:3000].lower()
    scores = {}
    for room, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scores[room] = score
    if scores:
        return max(scores, key=lambda k: scores[k])
    return "general"


# =============================================================================
# PALACE OPERATIONS
# =============================================================================


def get_collection(palace_path: str):
    """Open (or create) the drawer store for a palace."""
    os.makedirs(palace_path, mode=0o700, exist_ok=True)
    return open_store(palace_path, create=True)


@dataclass
class _StoredSource:
    """The conversation drawers already stored for one source and extract mode."""

    ids: list = field(default_factory=list)
    hashes: set = field(default_factory=set)
    strategies: set = field(default_factory=set)
    # A pre-1.15.0 compress replaced some drawer's text with AAAK: re-file the source.
    legacy_compressed: bool = False

    def is_current(self, source_hash: str, strategy: str) -> bool:
        return (
            bool(self.ids)
            and not self.legacy_compressed
            and self.hashes == {source_hash}
            and self.strategies == {strategy}
        )


_STATE_COLUMNS = [
    "id",
    "source_file",
    "ingest_mode",
    "extract_mode",
    "source_hash",
    "chunker_strategy",
    "original_tokens",
    "compression_ratio",
]


def _load_convo_state(store, wing: str) -> dict:
    """Return {source_file: {extract_mode: _StoredSource}} for conversation drawers in *wing*.

    Manual drawers, diary entries, and project drawers are never part of this state,
    so conversation mining never replaces or sweeps them.
    """
    rows = store.scan_wing_metadata(wing, _STATE_COLUMNS) if store is not None else None
    state: dict = {}
    if not isinstance(rows, list):
        return state
    for row in rows:
        if row.get("ingest_mode") != "convos":
            continue
        source_file = row.get("source_file")
        if not isinstance(source_file, str) or not source_file:
            continue
        mode = row.get("extract_mode") or "exchange"
        stored = state.setdefault(source_file, {}).setdefault(mode, _StoredSource())
        stored.ids.append(row.get("id"))
        stored.hashes.add(row.get("source_hash") or "")
        stored.strategies.add(row.get("chunker_strategy") or "")
        stored.legacy_compressed = stored.legacy_compressed or is_legacy_compressed(row)
    return state


def _general_excerpts(content: str, categories: Optional[Iterable[str]]) -> list:
    """Classified excerpts taken from within one exchange drawer at a time.

    An excerpt never spans two exchanges and is never longer than the exchange drawer
    it came from, so a long answer cannot absorb the next exchange's decision.
    """
    from .general_extractor import extract_memories

    excerpts = []
    for chunk in chunk_exchanges(content):
        for memory in extract_memories(chunk["content"], categories=categories):
            excerpts.append({**memory, "chunk_index": len(excerpts)})
    return excerpts


def _stored_convo_wing(store, source_file: str) -> Optional[str]:
    """The wing holding most conversation drawers of *source_file*, else None."""
    if store is None:
        return None
    found = store.get(
        where={"$and": [{"source_file": source_file}, {"ingest_mode": "convos"}]},
        include=["metadatas"],
    )
    wings = Counter(meta.get("wing") for meta in found.get("metadatas") or [] if meta.get("wing"))
    return wings.most_common(1)[0][0] if wings else None


def _delete_ids(store, ids: list) -> int:
    unique = list(dict.fromkeys(drawer_id for drawer_id in ids if drawer_id))
    for start in range(0, len(unique), _DELETE_BATCH):
        store.delete(unique[start : start + _DELETE_BATCH])
    return len(unique)


def _undecodable_reason(raw: bytes) -> Optional[str]:
    """Return why *raw* cannot be mined as text, or None when it is UTF-8 text."""
    if b"\x00" in raw:
        return (
            "binary or UTF-16 content (NUL bytes); convert it to UTF-8 text, "
            "e.g. iconv -f <encoding> -t UTF-8"
        )
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return (
            f"not valid UTF-8 (byte offset {exc.start}); convert it to UTF-8, "
            "e.g. iconv -f <encoding> -t UTF-8"
        )
    return None


# =============================================================================
# SCAN FOR CONVERSATION FILES
# =============================================================================


def scan_convos(convo_dir: str, skipped: Optional[list] = None) -> list:
    """Find all potential conversation files.

    Directories named in SKIP_DIRS and ``*.meta.json`` sidecars are not mined. When
    *skipped* is a list, their paths are appended to it so callers can report them.
    """
    convo_path = Path(convo_dir).expanduser().resolve()
    files = []
    for root, dirs, filenames in os.walk(convo_path):
        accepted_dirs = []
        for dirname in sorted(dirs):
            dirpath = Path(root) / dirname
            if dirname in SKIP_DIRS:
                if skipped is not None:
                    skipped.append(dirpath)
            elif dirpath.suffix.lower() in CONVO_EXTENSIONS:
                print(regular_source_diagnostic(dirpath), file=sys.stderr)
            else:
                accepted_dirs.append(dirname)
        dirs[:] = accepted_dirs
        for filename in sorted(filenames):
            filepath = Path(root) / filename
            if filename.endswith(".meta.json"):
                if skipped is not None:
                    skipped.append(filepath)
                continue
            if filepath.suffix.lower() in CONVO_EXTENSIONS:
                if not is_regular_source_path(filepath):
                    print(regular_source_diagnostic(filepath), file=sys.stderr)
                    continue
                files.append(filepath)
    return files


# =============================================================================
# MINE CONVERSATIONS
# =============================================================================


def _exit_source_error(message: str, palace_path: str) -> NoReturn:
    print(f"  Error: {message}", file=sys.stderr)
    print(
        "  Next: check the path, then rerun: "
        f"{cli_command('mine', '<conversations-dir-or-file>', '--mode', 'convos', palace=palace_path)}",
        file=sys.stderr,
    )
    sys.exit(1)


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _fit(text: str, width: int = 50) -> str:
    return text if len(text) <= width else "…" + text[-(width - 1) :]


def _drawer_id(wing: str, room: str, source_file: str, chunk_index: int, extract_mode: str) -> str:
    key = source_file + str(chunk_index)
    if extract_mode != "exchange":
        # Keep extract modes apart: their drawers coexist for the same source.
        key = f"{source_file}\x00{extract_mode}\x00{chunk_index}"
    digest = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:16]
    return f"drawer_{wing}_{room}_{digest}"


@holds_palace_write_lease("mine-convos", on_acquire=prune_settled_versions)
def mine_convos(
    convo_dir: str,
    palace_path: str,
    wing: str | None = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
    incremental: bool = True,
    extract_mode: str = "exchange",
    spellcheck: bool = False,
    extract_categories: Optional[Iterable[str]] = None,
) -> dict:
    """Mine a directory of conversation files (or one file) into the palace.

    extract_mode:
        "exchange" — default verbatim exchange chunking (user turn + answer = one unit)
        "general"  — general extractor: decisions, preferences, milestones, problems,
                     plus emotional memories when explicitly enabled. These classified
                     excerpts are stored next to, never instead of, exchange drawers.

    Incremental mining re-chunks a file when its content hash or the mode's chunker
    strategy differs from its stored drawers, or when a pre-1.15.0 ``compress``
    replaced their text, then removes the file's leftover drawers. Drawers of transcripts that are no longer on disk are kept by an
    incremental mine, which only counts them: tools prune old transcripts (Claude
    Code deletes sessions after ``cleanupPeriodDays``), and the palace may hold the
    only copy. A full mine (``incremental=False``) that walks a whole directory (no
    *limit*) removes them. Storage is optimized only when drawers were written or
    removed.
    """
    strategy = _STRATEGY_BY_MODE.get(extract_mode)
    if strategy is None:
        raise ValueError(f"unknown extract_mode {extract_mode!r}; use 'exchange' or 'general'")

    palace_path = expand_palace_path(palace_path)
    convo_path = Path(convo_dir).expanduser().resolve()
    skipped: list = []
    if convo_path.is_dir():
        walk_root: Optional[Path] = convo_path
        display_root = convo_path
        files = scan_convos(str(convo_path), skipped=skipped)
    elif convo_path.exists():
        if not is_regular_source_path(convo_path):
            _exit_source_error(regular_source_diagnostic(convo_path), palace_path)
        if convo_path.suffix.lower() not in CONVO_EXTENSIONS:
            _exit_source_error(
                f"not a conversation file: {convo_dir} "
                f"(expected {', '.join(sorted(CONVO_EXTENSIONS))})",
                palace_path,
            )
        walk_root = None
        display_root = convo_path.parent
        files = [convo_path]
    else:
        _exit_source_error(f"directory or file not found: {convo_dir}", palace_path)

    # A dry run reads existing drawers without creating a palace.
    collection = None if dry_run else get_collection(palace_path)
    reader = open_store(palace_path, create=False, read_only=True) if dry_run else collection

    wing_note = ""
    if not wing and walk_root is None:
        # One transcript mined again on its own keeps the wing that already holds it
        # (for example the wing of the directory it was first mined with).
        wing = _stored_convo_wing(reader, str(convo_path))
        if wing:
            wing_note = " (the wing that already holds this transcript)"
    if not wing:
        wing = display_root.name.lower().replace(" ", "_").replace("-", "_")

    if limit > 0:
        files = files[:limit]

    skipped_dirs = [path for path in skipped if not path.name.endswith(".meta.json")]
    skipped_sidecars = len(skipped) - len(skipped_dirs)

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine — Conversations")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}{wing_note}")
    print(f"  Source:  {convo_path}")
    print(f"  Files:   {len(files)}")
    print(f"  Palace:  {palace_path}")
    if skipped_dirs:
        shown = ", ".join(_display_path(path, display_root) + "/" for path in skipped_dirs[:5])
        more = f" and {len(skipped_dirs) - 5} more" if len(skipped_dirs) > 5 else ""
        print(f"  Skipped: {shown}{more} (excluded names; mine one directly to include it)")
    if skipped_sidecars:
        print(f"  Skipped: {skipped_sidecars} .meta.json sidecar file(s)")
    if extract_mode == "general":
        print("  Extract: general (classified excerpts, kept apart from verbatim exchanges)")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    if not incremental:
        print("  Mode:    FULL REBUILD (--full)")
    print(f"{'-' * 55}\n")

    state = _load_convo_state(reader, wing)

    files_processed = 0
    files_skipped = 0
    files_tiny = 0
    files_not_convo = 0
    files_failed = 0
    drawers_filed = 0
    drawers_removed = 0
    room_counts: Counter = Counter()
    batch_specs: list = []
    batch_deletes: list = []
    batch_lines: list = []

    def flush_batch() -> None:
        nonlocal drawers_filed, drawers_removed
        if batch_specs:
            drawers_filed += add_drawers_batch(collection, batch_specs)
        if batch_deletes:
            drawers_removed += _delete_ids(collection, batch_deletes)
        for line in batch_lines:
            print(line)
        batch_specs.clear()
        batch_deletes.clear()
        batch_lines.clear()

    removing = "would remove" if dry_run else "removing"

    def announce(line: str) -> None:
        if dry_run:
            print(line)
        else:
            batch_lines.append(line)  # reported once its batch is written

    def remove(ids: list, shown: str = "", why: str = "") -> None:
        nonlocal drawers_removed
        if dry_run:
            drawers_removed += len(set(ids))
        else:
            batch_deletes.extend(ids)
        if shown:
            announce(f"  - {removing} {len(set(ids))} drawers of {shown} ({why})")

    def report_skip(shown: str, reason: str) -> None:
        nonlocal files_failed
        files_failed += 1
        print(f"  ! skipped {shown}: {reason}", file=sys.stderr)

    for i, filepath in enumerate(files, 1):
        source_file = str(filepath)
        shown = _display_path(filepath, display_root)
        stored = state.get(source_file, {}).get(extract_mode)

        try:
            raw = read_regular_bytes(filepath)
        except OSError as exc:
            report_skip(shown, f"could not read: {exc}")
            continue
        reason = _undecodable_reason(raw)
        if reason is not None:
            report_skip(shown, reason)
            continue
        source_hash = hashlib.blake2b(raw, digest_size=16).hexdigest()

        if incremental and stored is not None and stored.is_current(source_hash, strategy):
            files_skipped += 1
            continue

        previous_ids = list(stored.ids) if stored is not None else []
        try:
            content = normalize(source_file, spellcheck=spellcheck)
        except NotAConversationError as exc:
            # Skipped on purpose (e.g. Slack users.json): not a failure, never retried.
            files_not_convo += 1
            print(f"  - skipped {shown}: {exc}")
            if previous_ids:
                remove(previous_ids, shown, "not a conversation")
            continue
        except (OSError, ValueError) as exc:
            report_skip(shown, f"{exc} (retried on the next mine)")
            continue

        if not content or not content.strip():
            files_tiny += 1
            print(f"  - skipped {shown}: no conversation text")
            if previous_ids:
                remove(previous_ids, shown, "no conversation text left")
            continue

        if extract_mode == "general":
            chunks = _general_excerpts(content, extract_categories)
        else:
            chunks = chunk_exchanges(content)

        file_specs = []
        for chunk in chunks:
            if extract_mode == "general":
                memory_type = str(chunk.get("memory_type") or "general")
                room = GENERAL_ROOMS.get(memory_type, memory_type)
            else:
                room = detect_convo_room(chunk["content"])
            file_specs.append(
                {
                    "id": _drawer_id(wing, room, source_file, chunk["chunk_index"], extract_mode),
                    "content": chunk["content"],
                    "metadata": {
                        "wing": wing,
                        "room": room,
                        "source_file": source_file,
                        "chunk_index": chunk["chunk_index"],
                        "added_by": agent,
                        "filed_at": datetime.now().isoformat(),
                        "ingest_mode": "convos",
                        "extract_mode": extract_mode,
                        "extractor_version": __version__,
                        "chunker_strategy": strategy,
                        "source_hash": source_hash,
                    },
                }
            )

        files_processed += 1
        rooms = Counter(spec["metadata"]["room"] for spec in file_specs)
        room_counts.update(rooms)
        new_ids = {spec["id"] for spec in file_specs}
        remove([drawer_id for drawer_id in previous_ids if drawer_id not in new_ids])
        note = "" if file_specs else "  (no memories found)"

        if dry_run:
            rooms_text = ", ".join(f"{room}:{count}" for room, count in rooms.most_common())
            print(f"    [DRY RUN] {shown} → {len(file_specs)} drawers ({rooms_text}){note}")
            drawers_filed += len(file_specs)
            continue

        batch_specs.extend(file_specs)
        batch_lines.append(f"  ✓ [{i:4}/{len(files)}] {_fit(shown):50} +{len(file_specs)}{note}")
        if len(batch_specs) >= get_batch_size():
            flush_batch()

    if not dry_run:
        flush_batch()

    # Conversation drawers whose source is gone. Only a whole-directory walk can prove
    # absence, and drawers under skipped directories are left alone. Only an explicit
    # --full walk removes them: tools prune old transcripts (Claude Code deletes
    # sessions after cleanupPeriodDays), and the palace may hold the only copy.
    sources_missing = 0
    if walk_root is not None and limit == 0:
        discovered = {str(path) for path in files}
        root_prefix = os.path.join(str(walk_root), "")
        skipped_prefixes = tuple(os.path.join(str(path), "") for path in skipped_dirs)
        gone = sorted(
            source_file
            for source_file in state
            if source_file.startswith(root_prefix)
            and source_file not in discovered
            and not source_file.startswith(skipped_prefixes)
        )
        if incremental:
            sources_missing = len(gone)
        else:
            for n, source_file in enumerate(gone):
                ids = [
                    drawer_id for stored in state[source_file].values() for drawer_id in stored.ids
                ]
                shown = _display_path(Path(source_file), display_root) if n < 10 else ""
                remove(ids, shown, "source no longer present")
            if len(gone) > 10:
                announce(f"  - ... {removing} the drawers of {len(gone) - 10} more missing sources")

    if collection is not None:
        flush_batch()
        if drawers_filed or drawers_removed:
            config = MempalaceConfig()
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

    would = "that would be " if dry_run else ""
    print(f"\n{'=' * 55}")
    print("  Dry run complete — nothing was filed." if dry_run else "  Done.")
    print(f"  Files {would}processed: {files_processed}")
    print(f"  Files skipped (already filed): {files_skipped}")
    if files_tiny:
        print(f"  Files with no text to index: {files_tiny}")
    if files_not_convo:
        print(f"  Files skipped (not a conversation): {files_not_convo}")
    if files_failed:
        print(f"  Files failed: {files_failed} (see messages above; retried on the next mine)")
    print(f"  Drawers {would}filed: {drawers_filed}")
    if drawers_removed:
        print(f"  Drawers {would}removed: {drawers_removed}")
    if sources_missing:
        print(
            f"  Transcripts no longer present: {sources_missing} "
            "(drawers kept; the palace may hold the only copy)"
        )
    if room_counts:
        print("\n  By room:")
        for room, count in room_counts.most_common():
            print(f"    {room:20} {count} drawers")
    print(f"\n  Next: {cli_command('search', 'what you are looking for', palace=palace_path)}")
    if sources_missing:
        full_argv = ["mine", str(convo_path), "--mode", "convos", "--wing", wing]
        if extract_mode != "exchange":
            full_argv += ["--extract", extract_mode]
        full_argv.append("--full")
        print(f"  To remove those drawers: {cli_command(*full_argv, palace=palace_path)}")
    print(f"{'=' * 55}\n")

    return {
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "files_tiny": files_tiny,
        "files_not_conversation": files_not_convo,
        "files_failed": files_failed,
        "drawers_filed": drawers_filed,
        "drawers_removed": drawers_removed,
        "sources_missing": sources_missing,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convo_miner.py <convo_dir> [--palace PATH] [--limit N] [--dry-run]")
        sys.exit(1)
    from .config import MempalaceConfig

    mine_convos(sys.argv[1], palace_path=MempalaceConfig().palace_path)
