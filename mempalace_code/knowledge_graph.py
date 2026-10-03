"""
knowledge_graph.py — Temporal Entity-Relationship Graph for MemPalace
=====================================================================

Real knowledge graph with:
  - Entity nodes (people, projects, tools, concepts)
  - Typed relationship edges (daughter_of, does, loves, works_on, etc.)
  - Temporal validity (valid_from → valid_to — knows WHEN facts are true)
  - Closet references (links back to the verbatim memory)

Storage: SQLite (local, no dependencies, no subscriptions)
Query: entity-first traversal with time filtering

This is what competes with Zep's temporal knowledge graph.
Zep uses Neo4j in the cloud ($25/mo+). We use SQLite locally (free).

Usage:
    from mempalace_code.knowledge_graph import open_palace_kg

    kg = open_palace_kg(palace_path)  # <palace>/knowledge_graph.sqlite3
    kg.add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
    kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01")
    kg.add_triple("Max", "loves", "chess", valid_from="2025-10-01")

    # Query: everything about Max
    kg.query_entity("Max")

    # Query: what was true about Max in January 2026?
    kg.query_entity("Max", as_of="2026-01-15")

    # Query: who is connected to Alice?
    kg.query_entity("Alice", direction="both")

    # Invalidate: Max's sports injury resolved
    kg.invalidate("Max", "has_issue", "sports_injury", ended="2026-02-15")
"""

import hashlib
import json
import os
import re
import shlex
import sqlite3
import sys
import time
import uuid
import warnings
from datetime import UTC, date, datetime
from pathlib import Path

from .errors import InvalidArgumentError

# ── Temporal validation helpers ───────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


def _parse_temporal(value: str | None) -> date | datetime | None:
    """Parse a temporal string to a date or datetime, or return None for blank.

    Accepts: None/empty, YYYY-MM-DD, or explicit UTC ISO datetime (Z or +00:00).
    Raises InvalidArgumentError (a ValueError) for any other format (natural
    language, naive datetime, etc.), carrying the rejected value.
    """
    if not value:
        return None
    if _DATE_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise InvalidArgumentError(
                f"Invalid temporal value {value!r}: {exc}", value=value
            ) from exc
    if _DATETIME_UTC_RE.match(value):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise InvalidArgumentError(
                f"Invalid temporal value {value!r}: {exc}", value=value
            ) from exc
    raise InvalidArgumentError(
        f"Invalid temporal value {value!r}: expected YYYY-MM-DD or UTC ISO datetime"
        " (e.g. 2026-01-01T12:00:00Z)",
        value=value,
    )


def _as_comparable(t: date | datetime | None) -> datetime | None:
    """Normalize a date or datetime to a UTC-aware datetime for comparison."""
    if t is None:
        return None
    if isinstance(t, datetime):
        return t
    return datetime(t.year, t.month, t.day, tzinfo=UTC)


def _as_comparable_vt(t: date | datetime | None) -> datetime | None:
    """Like _as_comparable but date-only values map to 23:59:59 UTC (end-of-day).

    Used for valid_to comparisons so that a date-only upper bound remains
    inclusive for any datetime as_of within the same calendar day, e.g.
    valid_to="2026-05-10" is still visible at as_of="2026-05-10T12:00:00Z".
    """
    if t is None:
        return None
    if isinstance(t, datetime):
        return t
    return datetime(t.year, t.month, t.day, 23, 59, 59, tzinfo=UTC)


def _validate_window(vf: date | datetime | None, vt: date | datetime | None) -> None:
    """Raise ValueError if valid_to precedes valid_from (equal is allowed)."""
    if vf is None or vt is None:
        return
    cmp_vf = _as_comparable(vf)
    cmp_vt = _as_comparable(vt)
    if cmp_vf is not None and cmp_vt is not None and cmp_vt < cmp_vf:
        raise InvalidArgumentError(
            "Inverted validity window: valid_to precedes valid_from", argument="valid_to"
        )


def _in_window(
    valid_from_str: str | None, valid_to_str: str | None, as_of: date | datetime
) -> bool:
    """Return True if as_of falls within [valid_from, valid_to] (inclusive).

    NULL bounds are treated as unbounded. Invalid stored temporal strings are
    treated as unbounded (backward-compatible with pre-validation data).
    """
    cmp = _as_comparable(as_of)
    if cmp is None:
        return True

    if valid_from_str is not None:
        try:
            vf = _as_comparable(_parse_temporal(valid_from_str))
        except ValueError:
            vf = None
        if vf is not None and cmp < vf:
            return False

    if valid_to_str is not None:
        try:
            vt = _as_comparable_vt(_parse_temporal(valid_to_str))
        except ValueError:
            vt = None
        if vt is not None and cmp > vt:
            return False

    return True


def _temporal_state(
    valid_from_str: str | None,
    valid_to_str: str | None,
    at: date | datetime,
) -> str:
    """Classify one stored interval as current, future, or expired at ``at``."""
    if _in_window(valid_from_str, valid_to_str, at):
        return "current"

    cmp = _as_comparable(at)
    if valid_from_str is not None:
        try:
            valid_from = _as_comparable(_parse_temporal(valid_from_str))
        except ValueError:
            valid_from = None
        if cmp is not None and valid_from is not None and cmp < valid_from:
            return "future"
    return "expired"


def _windows_overlap(
    from_a: str | None, to_a: str | None, from_b: str | None, to_b: str | None
) -> bool:
    """True when two stored validity windows share an instant (None bounds are open)."""

    def bound(value: str | None, end: bool) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = _parse_temporal(value)
        except ValueError:
            return None  # unparseable stored bounds count as unbounded, like _in_window
        return _as_comparable_vt(parsed) if end else _as_comparable(parsed)

    start_a, end_a = bound(from_a, False), bound(to_a, True)
    start_b, end_b = bound(from_b, False), bound(to_b, True)
    if start_a is not None and end_b is not None and start_a > end_b:
        return False
    return not (start_b is not None and end_a is not None and start_b > end_a)


def _default_invalidation_end() -> str:
    """Return the precise UTC instant used by an omitted invalidation bound."""
    return datetime.now(UTC).isoformat()


# Legacy global KG. KnowledgeGraph() without db_path still opens it; CLI, MCP, and
# watcher surfaces open the palace KG and adopt legacy facts through adopt_legacy_kg().
DEFAULT_KG_PATH = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")
_WAL_BUSY_RETRY_DELAYS = (0.01, 0.02, 0.04, 0.08, 0.16)


class KnowledgeGraphUnavailableError(RuntimeError):
    """The knowledge-graph file cannot be used; the message names the recovery step.

    CLI and MCP surfaces report it as one error line instead of a traceback.
    """


class KnowledgeGraphCorruptError(KnowledgeGraphUnavailableError):
    """The knowledge-graph SQLite file is not a database or is malformed.

    Busy or locked databases are never reported as corrupt. The message names the
    file and, for a palace KG, the health and backup commands for that palace.
    """

    def __init__(self, db_path: str, cause: BaseException, palace_path: str | None = None):
        from .cli_invocation import cli_command

        self.db_path = db_path
        self.cause = cause
        self.palace_path = palace_path
        if palace_path is not None:
            next_step = (
                f"{cli_command('health', palace=palace_path)}; restore it from an archive "
                f"listed by {cli_command('backup', 'list', palace=palace_path)}, or, when no "
                "archive holds a healthy one, follow the rebuild steps that health prints"
            )
        else:
            next_step = "keep a copy of the file, then restore it from a backup archive"
        super().__init__(f"knowledge graph {db_path} is corrupt ({cause}). Next: {next_step}")


class KnowledgeGraphReadOnlyError(KnowledgeGraphUnavailableError):
    """The knowledge-graph file, or the directory that holds it, is not writable."""

    def __init__(self, db_path: str, cause: BaseException | str):
        self.db_path = db_path
        self.cause = cause
        folder = os.path.dirname(os.path.abspath(db_path))
        super().__init__(
            f"knowledge graph {db_path} is not writable ({cause}); the palace is read-only. "
            f"Next: give your user write access to {folder} and the files in it "
            f"(for example: chmod -R u+w {shlex.quote(folder)}), then retry."
        )


def _is_corruption(exc: sqlite3.DatabaseError) -> bool:
    """True for a not-a-database or malformed file; False for busy, locked, or I/O errors."""
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int):
        return (code & 0xFF) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
    return not isinstance(exc, sqlite3.OperationalError)


def _is_read_only(exc: sqlite3.OperationalError, db_path: str) -> bool:
    """True when *exc* means the KG file or its directory cannot be written."""
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) == sqlite3.SQLITE_READONLY:
        return True
    return _kg_not_writable(db_path)


def _kg_not_writable(db_path: str) -> bool:
    """True when this user cannot write *db_path* (or create it, and its journal files)."""
    folder = os.path.dirname(os.path.abspath(db_path))
    if os.path.exists(db_path) and not os.access(db_path, os.W_OK):
        return True
    return os.path.isdir(folder) and not os.access(folder, os.W_OK)


def kg_integrity_problem(db_path: str) -> dict | None:
    """Run SQLite's ``quick_check`` on *db_path* read-only; return a problem, or None.

    The problem is ``{"probe": "kg_quick_check", "kind": ..., "message": ...}``: kind
    ``kg_corrupt`` for a malformed or not-a-database file, ``warning`` when the check
    could not run (a locked or read-only file is not proof of corruption). A missing
    file is not a problem. Nothing is written.
    """
    if not os.path.isfile(db_path):
        return None
    # as_uri() percent-encodes '%', '?', '#', and spaces, which a SQLite URI requires.
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        return {"probe": "kg_quick_check", "kind": "warning", "message": f"{db_path}: {exc}"}
    except sqlite3.DatabaseError as exc:
        return {"probe": "kg_quick_check", "kind": "kg_corrupt", "message": f"{db_path}: {exc}"}
    # One problem row can span many lines; report the first two and count the rest.
    problems = [
        line.strip()
        for row in rows
        if row and row[0] != "ok"
        for line in str(row[0]).splitlines()
        if line.strip() and not line.startswith("***")
    ]
    if problems:
        more = f"; and {len(problems) - 2} more problem(s)" if len(problems) > 2 else ""
        return {
            "probe": "kg_quick_check",
            "kind": "kg_corrupt",
            "message": f"{db_path}: {'; '.join(problems[:2])}{more}",
        }
    return None


def ensure_kg_readable(db_path: str, palace_path: str | None = None) -> None:
    """Raise :class:`KnowledgeGraphCorruptError` when *db_path* fails ``quick_check``.

    A missing file, or a check that could not run (locked, read-only), passes.
    """
    problem = kg_integrity_problem(db_path)
    if problem is not None and problem["kind"] == "kg_corrupt":
        detail = problem["message"].removeprefix(f"{db_path}: ")
        raise KnowledgeGraphCorruptError(db_path, sqlite3.DatabaseError(detail), palace_path)


def ensure_kg_writable(db_path: str, palace_path: str | None = None) -> None:
    """Raise before a write when the KG at *db_path* is corrupt or cannot be written.

    Writers (mine, the watcher) call this before their first destructive step, so a
    KG failure never leaves drawers deleted but not re-filed. A missing file is fine
    while its directory is writable. Raises :class:`KnowledgeGraphCorruptError` or
    :class:`KnowledgeGraphReadOnlyError`; creates nothing.
    """
    ensure_kg_readable(db_path, palace_path)
    if _kg_not_writable(db_path):
        raise KnowledgeGraphReadOnlyError(db_path, "permission denied")


_ENTITY_COLUMNS = "id, name, type, properties, created_at"
_TRIPLE_COLUMNS = (
    "id, subject, predicate, object, valid_from, valid_to, confidence, "
    "source_closet, source_file, extracted_at"
)
# idx_triples_spo serves every exact (subject, predicate, object) lookup: predicates have
# few distinct values, so a predicate-index plan scans a large share of the table per fact.
_HAS_FACT = "SELECT 1 FROM triples WHERE subject=? AND predicate=? AND object=? LIMIT 1"
_SCHEMA = """
    CREATE TABLE IF NOT EXISTS entities (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT DEFAULT 'unknown',
        properties TEXT DEFAULT '{}',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS triples (
        id TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        valid_from TEXT,
        valid_to TEXT,
        confidence REAL DEFAULT 1.0,
        source_closet TEXT,
        source_file TEXT,
        extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (subject) REFERENCES entities(id),
        FOREIGN KEY (object) REFERENCES entities(id)
    );

    CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
    CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
    CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
    CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
    CREATE INDEX IF NOT EXISTS idx_triples_spo ON triples(subject, predicate, object);
    CREATE INDEX IF NOT EXISTS idx_triples_source_file ON triples(source_file);
"""
# Named columns for fact reads; entity names are joined for display on both sides.
_FACT_SELECT = (
    "SELECT t.id, COALESCE(s.name, t.subject), t.predicate, COALESCE(o.name, t.object), "
    "t.valid_from, t.valid_to, t.confidence, t.source_closet, t.source_file "
    "FROM triples t LEFT JOIN entities s ON s.id = t.subject "
    "LEFT JOIN entities o ON o.id = t.object"
)
# Releases before this one could not adopt the legacy KG, so their exports cannot hold it.
_FIRST_ADOPTING_RELEASE = (1, 15, 0)


def _normalize_predicate(predicate: str) -> str:
    return predicate.strip().lower().replace(" ", "_")


def _fact_row(row: tuple, current_instant: datetime) -> dict:
    """Map one ``_FACT_SELECT`` row to the public fact dict."""
    return {
        "subject": row[1],
        "predicate": row[2],
        "object": row[3],
        "valid_from": row[4],
        "valid_to": row[5],
        "confidence": row[6],
        "source_closet": row[7],
        "source_file": row[8],
        "current": _temporal_state(row[4], row[5], current_instant) == "current",
    }


def _predates_adoption(version: object) -> bool:
    """Return True when *version* names a release older than the first adopting one."""
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", str(version or "").strip())
    if match is None:
        return False
    return tuple(int(part) for part in match.groups()) < _FIRST_ADOPTING_RELEASE


def kg_file_triple_ids(db_path: str) -> list[str]:
    """Return every triple id stored in the KG file *db_path*, read-only."""
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return [str(row[0]) for row in conn.execute("SELECT id FROM triples")]
    finally:
        conn.close()


def legacy_kg_holds(triple_ids) -> bool:
    """True when the legacy global KG exists and stores every id in *triple_ids*.

    Triple ids are random per insert, so a pre-1.15.0 export or archive whose facts
    all carry legacy ids was written from the legacy file (a command run without
    ``--palace``), not from a palace KG. False for no ids, a missing or unreadable
    legacy file, or any id the legacy file lacks.
    """
    return pre_adoption_kg_origin(triple_ids) == "legacy"


def pre_adoption_kg_origin(triple_ids) -> str:
    """Classify the KG of a pre-1.15.0 export or archive by its triple ids.

    Returns ``"legacy"`` when the legacy global KG stores every id (the command ran
    without ``--palace``), ``"palace"`` when the legacy file is readable and lacks
    at least one id (a palace KG), and ``"unknown"`` when no ids were written or the
    legacy file is missing or unreadable: then either source is possible, and an
    empty legacy KG looks exactly like an empty palace KG.
    """
    ids = {str(triple_id) for triple_id in triple_ids if triple_id}
    if not ids or not os.path.isfile(DEFAULT_KG_PATH):
        return "unknown"
    try:
        legacy_ids = set(kg_file_triple_ids(DEFAULT_KG_PATH))
    except sqlite3.Error:
        return "unknown"
    return "legacy" if ids <= legacy_ids else "palace"


def kg_ids_missing_from(db_path: str, triple_ids) -> int:
    """Count the triples in the KG file *db_path* whose ids are not in *triple_ids*.

    0 when the file is missing or unreadable: callers use this only to decide whether
    replacing or rebuilding from *triple_ids* would lose facts that file holds.
    """
    if not os.path.isfile(db_path):
        return 0
    try:
        stored = kg_file_triple_ids(db_path)
    except sqlite3.Error:
        return 0
    keep = {str(triple_id) for triple_id in triple_ids if triple_id}
    return sum(1 for triple_id in stored if triple_id not in keep)


def palace_kg_path(palace_path: str) -> str:
    """Return the conventional palace-local KG path: <palace>/knowledge_graph.sqlite3.

    ``~`` and relative palace paths are expanded the same way the drawer store does.
    """
    from .config import expand_palace_path

    return os.path.join(expand_palace_path(palace_path), "knowledge_graph.sqlite3")


def open_palace_kg(palace_path: str) -> "KnowledgeGraph":
    """Open the KG owned by *palace_path*; CLI, MCP, and watcher surfaces all use this.

    Raises :class:`KnowledgeGraphCorruptError`, naming this palace's recovery
    commands, when the file is not a database or is malformed.
    """
    adopt_legacy_kg(palace_path)
    try:
        return KnowledgeGraph(db_path=palace_kg_path(palace_path))
    except KnowledgeGraphCorruptError as exc:
        raise KnowledgeGraphCorruptError(exc.db_path, exc.cause, palace_path) from exc.cause


def _real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def _palace_exists(palace_path: str) -> bool:
    """True when *palace_path* holds drawers (``lance/``) or a KG with at least one fact."""
    if os.path.isdir(os.path.join(palace_path, "lance")):
        return True
    kg_file = palace_kg_path(palace_path)
    if not os.path.isfile(kg_file):
        return False
    try:
        conn = sqlite3.connect(f"{Path(kg_file).resolve().as_uri()}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT 1 FROM triples LIMIT 1").fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _is_configured_palace(palace_path: str) -> bool:
    """Return True when *palace_path* is the palace that adopts the legacy KG.

    That is the configured palace (``MEMPALACE_PALACE_PATH``, else ``config.json``, else
    the default). A palace selected only by ``MEMPALACE_PALACE_PATH`` that differs from
    the file-configured one adopts only when it already exists and the file-configured
    palace does not, so a trial or project-scoped selection never consumes adoption.
    """
    from .config import DEFAULT_PALACE_PATH, MempalaceConfig

    config = MempalaceConfig()
    selected = _real(palace_path)
    if selected != _real(config.palace_path):
        return False
    if not (os.environ.get("MEMPALACE_PALACE_PATH") or os.environ.get("MEMPAL_PALACE_PATH")):
        return True
    file_config = getattr(config, "_file_config", None) or {}
    file_configured = _real(str(file_config.get("palace_path", DEFAULT_PALACE_PATH)))
    if selected == file_configured:
        return True
    return not _palace_exists(file_configured) and _palace_exists(selected)


def adopt_legacy_kg(palace_path: str, *, after_import_of_version: str | None = None) -> int:
    """Copy facts held only by the legacy global KG into the configured palace's KG, once.

    Older releases wrote ``DEFAULT_KG_PATH`` from MCP (before 1.13.5) and from CLI
    runs without ``--palace``. For the configured palace only (see
    :func:`_is_configured_palace`), legacy entities and every legacy triple whose
    subject, predicate, and object the palace KG does not hold in any validity state
    are inserted with their original ids and windows; facts the palace KG already knows
    stay authoritative. The legacy database is opened read-only.

    The ``<DEFAULT_KG_PATH>.adopted`` marker records the adopted legacy file state, so
    later opens skip an unchanged legacy file. Without it, a palace rebuilt or restored
    after adoption would receive the legacy facts again, and replaying its JSONL export
    would bring back facts that palace had invalidated. Deleting the marker makes the
    next open adopt again. *after_import_of_version* is the header version of a JSONL
    export just replayed into this palace: an export from a release before adoption
    existed cannot hold the legacy facts, so adoption runs again after that replay even
    when the marker records the legacy state. Returns the number of adopted triples; on
    failure, no facts are copied and a one-line warning with a next step is printed.
    """
    legacy = DEFAULT_KG_PATH
    marker = Path(f"{legacy}.adopted")
    target = palace_kg_path(palace_path)
    replayed_old_export = _predates_adoption(after_import_of_version)
    adopted: list = []
    skipped = 0
    try:
        if not os.path.isfile(legacy):
            return 0
        legacy_stat = os.stat(legacy)
        state = f"{legacy_stat.st_ino} {legacy_stat.st_size} {legacy_stat.st_mtime_ns}"
        marker_current = marker.is_file() and marker.read_text(encoding="utf-8").strip() == state
        if marker_current and not replayed_old_export:
            return 0
        if not _is_configured_palace(palace_path):
            return 0
        if os.path.exists(target) and os.path.samefile(legacy, target):
            return 0
        source = sqlite3.connect(f"{Path(legacy).resolve().as_uri()}?mode=ro", uri=True)
        try:
            entities = source.execute(f"SELECT {_ENTITY_COLUMNS} FROM entities").fetchall()
            triples = source.execute(f"SELECT {_TRIPLE_COLUMNS} FROM triples").fetchall()
        finally:
            source.close()
        if entities or triples:
            conn = KnowledgeGraph(db_path=target)._conn()
            try:
                # Filter before taking the palace write lock; inside it, only the missing
                # combinations are re-checked, in case a concurrent writer added one.
                known = set(conn.execute("SELECT subject, predicate, object FROM triples"))
                missing = {row[1:4] for row in triples} - known
                conn.execute("BEGIN IMMEDIATE")
                missing = {
                    spo for spo in missing if conn.execute(_HAS_FACT, spo).fetchone() is None
                }
                adopted = [row for row in triples if row[1:4] in missing]
                skipped = len(triples) - len(adopted)
                conn.executemany(
                    f"INSERT OR IGNORE INTO entities ({_ENTITY_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                    entities,
                )
                conn.executemany(
                    f"INSERT OR IGNORE INTO triples ({_TRIPLE_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    adopted,
                )
                conn.commit()
            finally:
                conn.close()
    except (OSError, sqlite3.Error, KnowledgeGraphCorruptError) as exc:
        print(
            f"\n  Warning: legacy knowledge graph {legacy} was not adopted into {target} "
            f"({exc}); no facts were copied and it will be retried on the next open.\n"
            f"  Next: if that file is damaged and its facts are not needed, move it aside "
            f'with: mv "{legacy}" "{legacy}.unreadable"',
            file=sys.stderr,
        )
        return 0
    if adopted:
        reason = (
            f" (the imported export was made by {after_import_of_version}, a release that "
            "could not contain them)"
            if replayed_old_export and marker_current
            else ""
        )
        kept = (
            f" {skipped} legacy fact(s) were not copied because this palace KG already "
            "holds the same subject, predicate, and object; its copies stay authoritative."
            if skipped
            else ""
        )
        print(
            f"\n  Adopted {len(adopted)} fact(s) from the legacy knowledge graph {legacy} "
            f"into {target}{reason}; the legacy database was not changed.{kept}",
            file=sys.stderr,
        )
    try:
        marker.write_text(f"{state}\n", encoding="utf-8")
    except OSError as exc:
        print(
            f"\n  Warning: could not record legacy knowledge graph adoption in {marker} "
            f"({exc}); the next open checks {legacy} again.",
            file=sys.stderr,
        )
    return len(adopted)


def _source_scope(source_files, project_root: str | None) -> tuple[str, list]:
    """Return a SQL condition and its parameters matching rows by ``source_file``.

    A row matches when its source is one of *source_files* or lies under
    *project_root*, resolved with ``Path.resolve()`` (the miner stores resolved paths).
    The prefix match is path-boundary safe, and SQL ``LIKE`` wildcards in the root
    match literally, so ``/tmp/a_b`` never matches files under ``/tmp/aXb/``.
    """
    clauses: list[str] = []
    params: list = []
    if source_files:
        clauses.append(f"source_file IN ({','.join('?' * len(source_files))})")
        params.extend(source_files)
    if project_root is not None:
        resolved = str(Path(project_root).resolve())
        escaped = resolved.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("source_file = ? OR source_file LIKE ? ESCAPE '\\'")
        params.extend([resolved, escaped + "/%"])
    if not clauses:
        raise ValueError("a KG source scope needs source files or a project root")
    return " OR ".join(clauses), params


def _entity_key(name: str) -> str:
    """Return the case-insensitive entity id for a display name."""
    return name.strip().lower().replace(" ", "_").replace("'", "")


def _snapshot_connection(db_path: str) -> sqlite3.Connection:
    """Return an in-memory copy of *db_path* (or an empty KG) that a dry run may write."""
    memory = sqlite3.connect(":memory:")
    if os.path.isfile(db_path):
        # With no un-checkpointed WAL content the main file is complete: read it as
        # immutable so a preview does not even touch the -shm read marks.
        wal = f"{db_path}-wal"
        immutable = not os.path.exists(wal) or os.path.getsize(wal) == 0
        mode = "mode=ro&immutable=1" if immutable else "mode=ro"
        source = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?{mode}", uri=True)
        try:
            source.backup(memory)
        finally:
            source.close()
    memory.executescript(_SCHEMA)
    return memory


def _merge_import(conn: sqlite3.Connection, triples, entities) -> dict:
    """Merge exported KG records into the KG behind *conn*; the caller commits.

    Entities: a new entity is inserted with its exported type and properties; an existing
    one only gains a type or properties it lacks, so the palace keeps what it holds.

    Triples, closed records first so the open ones meet the export's whole history,
    otherwise in file order:
      1. A record whose exported id is stored for the same fact: a stored open row takes
         the record's valid_to (the export saw a later invalidation); a stored closed
         row stays closed (conflict: this palace invalidated it after the export);
         anything else is a duplicate.
      2. Otherwise an identical stored fact is a duplicate: any open row for an open
         record, or a row with the same validity window for a closed record.
      3. An open record whose fact the palace itself holds closed with the same
         valid_from is a conflict: the palace invalidated it, so the stale open copy is
         not imported. A closed row the export also holds closed (same id), or that
         this merge inserted, is the export's own history, and a reopened open copy
         after it is imported.
      4. Otherwise the record is inserted with its exported id (unless another fact
         holds it) and its extracted_at.
    """
    summary: dict = {
        "inserted": 0,
        "duplicates": 0,
        "invalidations_applied": 0,
        "conflicts": [],
        "entities": 0,
        "failed": [],
    }
    for record in entities:
        name = str(record.get("name") or "").strip()
        if not name:
            summary["failed"].append("kg_entity record without a name")
            continue
        eid = _entity_key(name)
        etype = str(record.get("entity_type") or "unknown")
        props = record.get("properties") or {}
        props_json = props if isinstance(props, str) else json.dumps(props)
        row = conn.execute("SELECT type, properties FROM entities WHERE id=?", (eid,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO entities (id, name, type, properties, created_at)"
                " VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
                (eid, name, etype, props_json, record.get("created_at")),
            )
            summary["entities"] += 1
            continue
        new_type = row[0] if row[0] not in (None, "", "unknown") else etype
        new_props = row[1] if row[1] not in (None, "", "{}") else props_json
        if (new_type, new_props) != tuple(row):
            conn.execute(
                "UPDATE entities SET type=?, properties=? WHERE id=?", (new_type, new_props, eid)
            )
            summary["entities"] += 1

    # Closed rows that are the export's own history rather than this palace's
    # invalidations: ids the export holds closed, plus every row this merge inserts.
    export_history = {
        record["id"]
        for record in triples
        if isinstance(record.get("id"), str) and record.get("valid_to")
    }
    for record in sorted(triples, key=lambda record: not record.get("valid_to")):
        subject = str(record.get("subject") or "").strip()
        obj = str(record.get("object") or "").strip()
        pred = _normalize_predicate(str(record.get("predicate") or ""))
        valid_from = record.get("valid_from") or None
        valid_to = record.get("valid_to") or None
        fact = f"{subject} → {pred} → {obj}"
        try:
            if not subject or not pred or not obj:
                raise ValueError("subject, predicate, and object are required")
            _validate_window(_parse_temporal(valid_from), _parse_temporal(valid_to))
        except (TypeError, ValueError) as exc:
            summary["failed"].append(f"{fact}: {exc}")
            continue
        sub_id, obj_id = _entity_key(subject), _entity_key(obj)
        spo = (sub_id, pred, obj_id)
        triple_id = record.get("id") if isinstance(record.get("id"), str) else None
        if triple_id:
            stored = conn.execute(
                "SELECT subject, predicate, object, valid_to FROM triples WHERE id=?",
                (triple_id,),
            ).fetchone()
            if stored is not None and tuple(stored[:3]) == spo:
                if stored[3] is None and valid_to is not None:
                    conn.execute(
                        "UPDATE triples SET valid_to=? WHERE id=? AND valid_to IS NULL",
                        (valid_to, triple_id),
                    )
                    summary["invalidations_applied"] += 1
                elif stored[3] is not None and valid_to is None:
                    summary["conflicts"].append(fact)
                else:
                    summary["duplicates"] += 1
                continue
            if stored is not None:
                triple_id = None
        same_fact = "SELECT 1 FROM triples WHERE subject=? AND predicate=? AND object=?"
        if valid_to is None:
            if conn.execute(f"{same_fact} AND valid_to IS NULL LIMIT 1", spo).fetchone():
                summary["duplicates"] += 1
                continue
            closed = conn.execute(
                "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=?"
                " AND valid_from IS ? AND valid_to IS NOT NULL",
                (*spo, valid_from),
            )
            if any(row[0] not in export_history for row in closed):
                summary["conflicts"].append(fact)
                continue
        elif conn.execute(
            f"{same_fact} AND valid_from IS ? AND valid_to=? LIMIT 1", (*spo, valid_from, valid_to)
        ).fetchone():
            summary["duplicates"] += 1
            continue
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject))
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, obj))
        confidence = record.get("confidence")
        triple_id = triple_id or KnowledgeGraph._new_triple_id(sub_id, pred, obj_id, valid_from)
        export_history.add(triple_id)
        conn.execute(
            f"INSERT INTO triples ({_TRIPLE_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
            (
                triple_id,
                sub_id,
                pred,
                obj_id,
                valid_from,
                valid_to,
                1.0 if confidence is None else confidence,
                record.get("source_closet"),
                record.get("source_file"),
                record.get("extracted_at"),
            ),
        )
        summary["inserted"] += 1
    return summary


class LazyKnowledgeGraph:
    """Palace KG proxy that defers :func:`open_palace_kg` until the first method call.

    Use this on incremental mine/watch and dry-run paths so a no-op run cannot
    create a SQLite file or adopt legacy facts by construction.
    """

    def __init__(self, palace_path: str):
        self._palace_path = palace_path
        self._kg: KnowledgeGraph | None = None

    def _get_kg(self) -> "KnowledgeGraph":
        if self._kg is None:
            self._kg = open_palace_kg(self._palace_path)
        return self._kg

    def __getattr__(self, name: str):
        return getattr(self._get_kg(), name)

    def check_writable(self) -> None:
        """Raise when the palace KG is corrupt or read-only, without opening or creating it."""
        if self._kg is not None:
            ensure_kg_writable(self._kg.db_path, self._palace_path)
        else:
            ensure_kg_writable(palace_kg_path(self._palace_path), self._palace_path)

    def import_facts(
        self, triples: list, entities: list | tuple = (), dry_run: bool = False
    ) -> dict:
        """Like :meth:`KnowledgeGraph.import_facts`; a dry run neither opens nor adopts."""
        if dry_run and self._kg is None:
            conn = _snapshot_connection(palace_kg_path(self._palace_path))
            try:
                return _merge_import(conn, triples, entities)
            finally:
                conn.close()
        return self._get_kg().import_facts(triples, entities, dry_run=dry_run)


class KnowledgeGraph:
    def __init__(self, db_path: str | None = None):
        if not db_path:
            warnings.warn(
                "KnowledgeGraph() without db_path opens the legacy global KG "
                f"{DEFAULT_KG_PATH}, which CLI, MCP, and the watcher no longer read; "
                "use open_palace_kg(palace_path) for the palace KG.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.db_path = db_path or DEFAULT_KG_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._init_db()
        except sqlite3.OperationalError as exc:
            if _is_read_only(exc, self.db_path):
                raise KnowledgeGraphReadOnlyError(self.db_path, exc) from exc
            raise
        except sqlite3.DatabaseError as exc:
            if _is_corruption(exc):
                raise KnowledgeGraphCorruptError(self.db_path, exc) from exc
            raise

    def check_writable(self) -> None:
        """Raise when this KG is corrupt or read-only; see :func:`ensure_kg_writable`."""
        ensure_kg_writable(self.db_path)

    def _init_db(self):
        conn = self._conn()
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self):
        busy_retries = 0
        while True:
            conn = sqlite3.connect(self.db_path, timeout=10 if busy_retries == 0 else 0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                if busy_retries:
                    conn.execute("PRAGMA busy_timeout=10000")
                return conn
            except sqlite3.OperationalError as exc:
                conn.close()
                error_code = getattr(exc, "sqlite_errorcode", None)
                is_busy = isinstance(error_code, int) and (error_code & 0xFF) == sqlite3.SQLITE_BUSY
                if not is_busy or busy_retries == len(_WAL_BUSY_RETRY_DELAYS):
                    raise
                time.sleep(_WAL_BUSY_RETRY_DELAYS[busy_retries])
                busy_retries += 1

    def _entity_id(self, name: str) -> str:
        return _entity_key(name)

    # ── Write operations ──────────────────────────────────────────────────

    def add_entity(self, name: str, entity_type: str = "unknown", properties: dict | None = None):
        """Add or update an entity node."""
        name = name.strip()
        eid = self._entity_id(name)
        props = json.dumps(properties or {})
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO entities (id, name, type, properties) VALUES (?, ?, ?, ?)",
            (eid, name, entity_type, props),
        )
        conn.commit()
        conn.close()
        return eid

    @staticmethod
    def _new_triple_id(sub_id: str, pred: str, obj_id: str, valid_from: str | None) -> str:
        digest = hashlib.md5(
            f"{valid_from}{datetime.now().isoformat()}{uuid.uuid4().hex}".encode()
        ).hexdigest()[:8]
        return f"t_{sub_id}_{pred}_{obj_id}_{digest}"

    def _find_or_insert(
        self,
        conn: sqlite3.Connection,
        subject: str,
        pred: str,
        obj: str,
        valid_from: str | None,
        valid_to: str | None,
        confidence: float = 1.0,
        source_closet: str | None = None,
        source_file: str | None = None,
    ) -> tuple[str, bool]:
        """Return ``(triple_id, created)``: an identical stored fact, or a new row.

        An open fact matches any open row for the same subject, predicate, and object.
        A closed fact matches only a row with the same validity window, so replaying
        history (re-import, repeated kg_add) never duplicates it.
        """
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject))
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, obj))
        if valid_to is None:
            existing = conn.execute(
                "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=?"
                " AND valid_to IS NULL LIMIT 1",
                (sub_id, pred, obj_id),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=?"
                " AND valid_from IS ? AND valid_to=? LIMIT 1",
                (sub_id, pred, obj_id, valid_from, valid_to),
            ).fetchone()
        if existing:
            return existing[0], False
        triple_id = self._new_triple_id(sub_id, pred, obj_id, valid_from)
        conn.execute(
            """INSERT INTO triples (id, subject, predicate, object, valid_from, valid_to, confidence, source_closet, source_file)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                triple_id,
                sub_id,
                pred,
                obj_id,
                valid_from,
                valid_to,
                confidence,
                source_closet,
                source_file,
            ),
        )
        return triple_id, True

    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        source_closet: str | None = None,
        source_file: str | None = None,
    ):
        """
        Add a relationship triple: subject → predicate → object.

        Returns the new triple id, or the id of the identical stored fact (an open fact
        for an open request, the same validity window for a closed one).

        Examples:
            add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
            add_triple("Max", "does", "swimming", valid_from="2025-01-01")
            add_triple("Alice", "attended", "Conference", valid_from="2026-05-10", valid_to="2026-05-10")
        """
        return self.add_triple_report(
            subject,
            predicate,
            obj,
            valid_from=valid_from,
            valid_to=valid_to,
            confidence=confidence,
            source_closet=source_closet,
            source_file=source_file,
            with_context=False,
        )["triple_id"]

    def add_triple_report(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        source_closet: str | None = None,
        source_file: str | None = None,
        with_context: bool = True,
    ) -> dict:
        """Add a triple like :meth:`add_triple` and report what the KG now holds.

        Returns ``triple_id``, ``created`` (False when an identical fact already existed
        and nothing changed), the stored ``subject``/``predicate``/``object`` display
        names and validity window, and, with *with_context*, ``other_current``: the other
        facts that are current for the same subject and predicate (always present, empty
        when there are none).

        A request whose window overlaps a current copy of the same subject, predicate,
        and object with a different window adds nothing, so one fact never has two
        current rows: ``created`` is False, ``triple_id`` and the window are that copy's,
        and ``same_fact_current`` lists the current copies whose window differs from the
        request. To end a current fact, use :meth:`invalidate`.
        """
        subject = subject.strip()
        obj = obj.strip()
        _validate_window(_parse_temporal(valid_from), _parse_temporal(valid_to))
        pred = _normalize_predicate(predicate)
        now = datetime.now(UTC)
        conn = self._conn()
        try:
            copies = conn.execute(
                "SELECT id, valid_from, valid_to FROM triples"
                " WHERE subject=? AND predicate=? AND object=? ORDER BY rowid",
                (self._entity_id(subject), pred, self._entity_id(obj)),
            ).fetchall()
            overlapping = [
                copy
                for copy in copies
                if _temporal_state(copy[1], copy[2], now) == "current"
                and _windows_overlap(copy[1], copy[2], valid_from, valid_to)
            ]
            identical = any(
                (copy[1], copy[2]) == (valid_from, valid_to)
                or (valid_to is None and copy[2] is None)
                for copy in overlapping
            )
            if overlapping and not identical:
                triple_id, created = overlapping[0][0], False
            else:
                triple_id, created = self._find_or_insert(
                    conn,
                    subject,
                    pred,
                    obj,
                    valid_from,
                    valid_to,
                    confidence,
                    source_closet,
                    source_file,
                )
                conn.commit()
            report: dict = {"triple_id": triple_id, "created": created}
            # Includes an open copy that an open request matched despite another
            # valid_from, so the caller learns the stored start differs.
            same_fact_current = [
                {"triple_id": copy[0], "valid_from": copy[1], "valid_to": copy[2]}
                for copy in overlapping
                if not created and (copy[1], copy[2]) != (valid_from, valid_to)
            ]
            if same_fact_current:
                report["same_fact_current"] = same_fact_current
            if not with_context:
                return report
            row = conn.execute(f"{_FACT_SELECT} WHERE t.id = ?", (triple_id,)).fetchone()
            report.update(
                {
                    "subject": row[1],
                    "predicate": row[2],
                    "object": row[3],
                    "valid_from": row[4],
                    "valid_to": row[5],
                }
            )
            others = conn.execute(
                f"{_FACT_SELECT} WHERE t.subject = ? AND t.predicate = ? AND t.object != ?"
                " ORDER BY t.object, t.rowid",
                (self._entity_id(subject), pred, self._entity_id(obj)),
            ).fetchall()
            report["other_current"] = [
                {"object": other[3], "valid_from": other[4], "valid_to": other[5]}
                for other in others
                if _temporal_state(other[4], other[5], now) == "current"
            ]
            return report
        finally:
            conn.close()

    def invalidate_by_source_file(
        self, source_file: str, ended: str | None = None, predicates=None
    ) -> int:
        """Set valid_to on all active triples (valid_to IS NULL) whose source_file matches.

        When *predicates* is a non-empty list/tuple of predicate strings, only triples
        whose predicate is in that set are expired — other predicates are left untouched.
        Omit *predicates* (or pass ``None``) to expire all active triples for the file,
        which is the original behaviour used by the per-file KG extraction pass.

        Used by the miner before re-parsing a changed or deleted source file and by the
        architecture extraction pass to refresh only architecture predicates without
        expiring type-dependency facts (implements, inherits, depends_on, etc.).
        Returns the number of facts expired.
        """
        ended = ended or _default_invalidation_end()
        _parse_temporal(ended)
        conn = self._conn()
        try:
            if predicates:
                placeholders = ",".join("?" * len(predicates))
                cursor = conn.execute(
                    f"UPDATE triples SET valid_to=? WHERE source_file=? AND valid_to IS NULL"
                    f" AND predicate IN ({placeholders})",
                    [ended, source_file, *predicates],
                )
            else:
                cursor = conn.execute(
                    "UPDATE triples SET valid_to=? WHERE source_file=? AND valid_to IS NULL",
                    (ended, source_file),
                )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def invalidate_by_predicates(self, predicates: list, ended: str | None = None) -> None:
        """Expire all active triples (valid_to IS NULL) whose predicate is in *predicates*.

        Used by the architecture extraction pass to globally reset arch facts (is_pattern,
        is_layer, in_namespace, in_project) before re-emitting a fresh picture from the
        current walked file set.  Works correctly across both incremental and full-rebuild
        mine modes without needing to track which files were deleted.
        """
        if not predicates:
            return
        ended = ended or _default_invalidation_end()
        _parse_temporal(ended)
        conn = self._conn()
        placeholders = ",".join("?" * len(predicates))
        conn.execute(
            f"UPDATE triples SET valid_to=? WHERE valid_to IS NULL"
            f" AND predicate IN ({placeholders})",
            [ended, *predicates],
        )
        conn.commit()
        conn.close()

    def invalidate_arch_by_project_root(
        self,
        predicates: list,
        project_root: str,
        sentinels: list | None = None,
        ended: str | None = None,
    ) -> None:
        """Expire active arch triples scoped to one project root, preserving other wings.

        Expires open triples whose ``predicate`` is in *predicates* and whose
        ``source_file`` lies under *project_root* or equals one of *sentinels* (virtual
        sources such as ``__arch_ns_project__:<wing>``); see :func:`_source_scope`.
        Mining uses :meth:`sync_facts`, which expires only the facts a fresh
        extraction no longer yields; this method is kept for API compatibility.
        """
        if not predicates:
            return
        ended = ended or _default_invalidation_end()
        _parse_temporal(ended)
        scope, scope_params = _source_scope(sentinels or (), project_root)
        conn = self._conn()
        conn.execute(
            "UPDATE triples SET valid_to=? WHERE valid_to IS NULL"
            f" AND predicate IN ({','.join('?' * len(predicates))}) AND ({scope})",
            [ended, *predicates, *scope_params],
        )
        conn.commit()
        conn.close()

    def invalidate_legacy_arch_ns_project_for_wing(
        self,
        legacy_sentinel: str,
        wing_name: str,
        ended: str | None = None,
    ) -> int:
        """Expire pre-WING-SCOPE namespace→project rows for a single wing; return the count.

        Pre-WING-SCOPE releases stored namespace→project triples with a single
        shared ``source_file`` sentinel (e.g. ``__arch_ns_project__``) that did
        not include the wing name. Those legacy rows are not matched by the
        architecture pass's wing-scoped sentinel (``__arch_ns_project__:<wing>``) and
        so persist forever as orphaned current facts after upgrade.

        This helper expires only the legacy rows whose ``object`` resolves to
        *wing_name*, leaving other wings' legacy rows intact until they are
        themselves mined.  After every wing has been mined once on the new
        release, all legacy sentinel rows have been retired.
        """
        ended = ended or _default_invalidation_end()
        _parse_temporal(ended)
        obj_id = self._entity_id(wing_name)
        conn = self._conn()
        try:
            cursor = conn.execute(
                "UPDATE triples SET valid_to=? WHERE valid_to IS NULL"
                " AND source_file=? AND predicate='in_project' AND object=?",
                (ended, legacy_sentinel, obj_id),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def invalidate(self, subject: str, predicate: str, obj: str, ended: str | None = None):
        """Mark a relationship as no longer valid (set valid_to date).

        Only open rows (no valid_to) change. Returns a report: ``invalidated`` (rows
        changed), ``ended`` (the valid_to actually stored, including the precise instant
        used when *ended* is omitted), the stored display names, and, when nothing
        matched, ``already_ended`` (closed rows for this exact fact) and
        ``current_objects`` (objects that are current for the same subject and predicate).
        """
        subject = subject.strip()
        obj = obj.strip()
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = _normalize_predicate(predicate)
        ended_str = ended or _default_invalidation_end()

        ended_parsed = _parse_temporal(ended_str)
        cmp_ended = _as_comparable(ended_parsed)

        conn = self._conn()
        try:
            # Validate ended against each active row's valid_from before mutating
            active = conn.execute(
                "SELECT valid_from FROM triples WHERE subject=? AND predicate=? AND object=?"
                " AND valid_to IS NULL",
                (sub_id, pred, obj_id),
            ).fetchall()
            for (vf_str,) in active:
                if vf_str is not None:
                    try:
                        cmp_vf = _as_comparable(_parse_temporal(vf_str))
                    except ValueError:
                        continue  # skip rows with legacy invalid temporal strings
                    if cmp_vf is not None and cmp_ended is not None and cmp_ended < cmp_vf:
                        raise InvalidArgumentError(
                            f"Inverted invalidation: ended ({ended_str!r}) precedes"
                            f" active valid_from ({vf_str!r})",
                            argument="ended",
                        )

            changed = conn.execute(
                "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=?"
                " AND valid_to IS NULL",
                (ended_str, sub_id, pred, obj_id),
            ).rowcount
            conn.commit()
            names = dict(
                conn.execute("SELECT id, name FROM entities WHERE id IN (?, ?)", (sub_id, obj_id))
            )
            report: dict = {
                "invalidated": changed,
                "ended": ended_str if changed else None,
                "subject": names.get(sub_id, subject),
                "predicate": pred,
                "object": names.get(obj_id, obj),
            }
            if changed:
                return report
            now = datetime.now(UTC)
            report["already_ended"] = [
                {"valid_from": row[4], "valid_to": row[5]}
                for row in conn.execute(
                    f"{_FACT_SELECT} WHERE t.subject=? AND t.predicate=? AND t.object=?"
                    " AND t.valid_to IS NOT NULL ORDER BY t.rowid",
                    (sub_id, pred, obj_id),
                )
            ]
            report["current_objects"] = [
                row[3]
                for row in conn.execute(
                    f"{_FACT_SELECT} WHERE t.subject=? AND t.predicate=?"
                    " ORDER BY t.object, t.rowid",
                    (sub_id, pred),
                )
                if _temporal_state(row[4], row[5], now) == "current"
            ]
            return report
        finally:
            conn.close()

    def sync_facts(
        self,
        facts: list,
        *,
        source_files: list | tuple = (),
        project_root: str | None = None,
        predicates: list | tuple | None = None,
        exclude_predicates: list | tuple = (),
        ended: str | None = None,
    ) -> dict:
        """Make the open facts of one extraction scope equal *facts*, in one transaction.

        *facts* holds ``(subject, predicate, object, source_file)`` tuples. The scope is
        every open row whose ``source_file`` is one of *source_files* or lies under
        *project_root* (path-boundary safe), restricted to *predicates* when given and
        excluding *exclude_predicates*. Open rows in scope that are still extracted stay
        unchanged (their ids and history are kept); rows no longer extracted, and
        duplicate open copies, get ``valid_to``; new facts are inserted, reusing an open
        copy outside the scope as :meth:`add_triple` does.

        Returns counts: ``facts`` (distinct desired facts), ``unchanged``, ``inserted``,
        and ``expired``.
        """
        ended = ended or _default_invalidation_end()
        _parse_temporal(ended)
        scope, params = _source_scope(source_files, project_root)
        where = f"valid_to IS NULL AND ({scope})"
        if predicates is not None:
            if not predicates:
                return {"facts": 0, "unchanged": 0, "inserted": 0, "expired": 0}
            where += f" AND predicate IN ({','.join('?' * len(predicates))})"
            params.extend(predicates)
        if exclude_predicates:
            where += f" AND predicate NOT IN ({','.join('?' * len(exclude_predicates))})"
            params.extend(exclude_predicates)

        desired: dict = {}
        for subject, predicate, obj, source_file in facts:
            subject = str(subject).strip()
            obj = str(obj).strip()
            pred = _normalize_predicate(str(predicate))
            key = (self._entity_id(subject), pred, self._entity_id(obj))
            desired.setdefault(key, (subject, pred, obj, source_file))

        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            kept: set = set()
            stale: list = []
            for row_id, sub_id, pred, obj_id in conn.execute(
                f"SELECT id, subject, predicate, object FROM triples WHERE {where} ORDER BY rowid",
                params,
            ).fetchall():
                key = (sub_id, pred, obj_id)
                if key in desired and key not in kept:
                    kept.add(key)
                else:
                    stale.append((ended, row_id))
            conn.executemany("UPDATE triples SET valid_to=? WHERE id=?", stale)
            inserted = 0
            for key, (subject, pred, obj, source_file) in desired.items():
                if key in kept:
                    continue
                _, created = self._find_or_insert(
                    conn, subject, pred, obj, None, None, source_file=source_file
                )
                inserted += int(created)
            conn.commit()
        finally:
            conn.close()
        return {
            "facts": len(desired),
            "unchanged": len(kept),
            "inserted": inserted,
            "expired": len(stale),
        }

    # ── Query operations ──────────────────────────────────────────────────

    def query_entity(self, name: str, as_of: str | None = None, direction: str = "outgoing"):
        """
        Get all relationships for an entity.

        direction: "outgoing" (entity → ?), "incoming" (? → entity), "both"
        as_of: ISO date or UTC datetime — only return facts valid at that time

        Subjects and objects are the stored entity display names; the lookup is
        case-insensitive and ignores surrounding whitespace in *name*.
        """
        supported_directions = ("outgoing", "incoming", "both")
        if direction not in supported_directions:
            raise ValueError(
                f"Invalid direction: supported directions are {', '.join(supported_directions)}"
            )

        eid = self._entity_id(name)
        as_of_parsed = _parse_temporal(as_of)
        current_instant = datetime.now(UTC)
        conn = self._conn()

        results = []
        sides = [("outgoing", "t.subject"), ("incoming", "t.object")]
        for side, column in sides:
            if direction not in (side, "both"):
                continue
            for row in conn.execute(
                f"{_FACT_SELECT} WHERE {column} = ? ORDER BY t.rowid", (eid,)
            ).fetchall():
                if as_of_parsed is not None and not _in_window(row[4], row[5], as_of_parsed):
                    continue
                results.append({"direction": side, **_fact_row(row, current_instant)})

        conn.close()
        return results

    def query_relationship(self, predicate: str, as_of: str | None = None):
        """Get all triples with a given relationship type."""
        pred = _normalize_predicate(predicate)
        as_of_parsed = _parse_temporal(as_of)
        current_instant = datetime.now(UTC)
        conn = self._conn()

        results = []
        for row in conn.execute(
            f"{_FACT_SELECT} WHERE t.predicate = ? ORDER BY t.rowid", (pred,)
        ).fetchall():
            if as_of_parsed is not None and not _in_window(row[4], row[5], as_of_parsed):
                continue
            fact = _fact_row(row, current_instant)
            del fact["confidence"]
            results.append(fact)
        conn.close()
        return results

    def timeline(self, entity_name: str | None = None, limit: int | None = 100, offset: int = 0):
        """Get facts in chronological order, optionally filtered by entity.

        Returns at most *limit* facts (None for all) starting at *offset*, ordered by
        valid_from with undated facts last, then by recording order. Use
        :meth:`timeline_total` for the number of facts available to page through.
        """
        current_instant = datetime.now(UTC)
        where, params = self._timeline_filter(entity_name)
        conn = self._conn()
        rows = conn.execute(
            f"{_FACT_SELECT}{where} ORDER BY t.valid_from ASC NULLS LAST, t.extracted_at ASC,"
            " t.rowid ASC LIMIT ? OFFSET ?",
            [*params, -1 if limit is None else limit, max(0, offset)],
        ).fetchall()
        conn.close()
        facts = []
        for row in rows:
            fact = _fact_row(row, current_instant)
            del fact["confidence"]
            facts.append(fact)
        return facts

    def timeline_total(self, entity_name: str | None = None) -> int:
        """Return how many facts :meth:`timeline` pages through for *entity_name*."""
        where, params = self._timeline_filter(entity_name)
        conn = self._conn()
        total = conn.execute(f"SELECT COUNT(*) FROM triples t{where}", params).fetchone()[0]
        conn.close()
        return total

    def _timeline_filter(self, entity_name: str | None) -> tuple[str, list]:
        if not entity_name or not entity_name.strip():
            return "", []
        eid = self._entity_id(entity_name)
        return " WHERE (t.subject = ? OR t.object = ?)", [eid, eid]

    def iter_all_triples(self, batch_size=500):
        """Yield batches of triple dicts without the LIMIT 100 cap.

        Each dict contains: id, subject, predicate, object, valid_from, valid_to,
        confidence, source_closet, source_file, extracted_at.
        """
        conn = self._conn()
        cursor = conn.execute("""
            SELECT t.id, COALESCE(s.name, t.subject) AS subject, t.predicate,
                   COALESCE(o.name, t.object) AS object,
                   t.valid_from, t.valid_to, t.confidence, t.source_closet, t.source_file,
                   t.extracted_at
            FROM triples t
            LEFT JOIN entities s ON t.subject = s.id
            LEFT JOIN entities o ON t.object = o.id
            ORDER BY t.extracted_at ASC, t.rowid ASC
        """)
        cols = [d[0] for d in cursor.description]
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield [dict(zip(cols, r)) for r in rows]
        conn.close()

    def iter_entities(self, ids: set | None = None, metadata_only: bool = True):
        """Yield entity dicts (id, name, entity_type, properties, created_at).

        With *metadata_only*, only entities carrying a type or properties are yielded;
        the others are recreated from triple names on import. *ids* restricts output.
        """
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, name, type, properties, created_at FROM entities ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        for eid, name, etype, props, created_at in rows:
            if ids is not None and eid not in ids:
                continue
            etype = etype or "unknown"
            try:
                properties = json.loads(props) if props else {}
            except ValueError:
                properties = props
            if metadata_only and etype == "unknown" and not properties:
                continue
            yield {
                "id": eid,
                "name": name,
                "entity_type": etype,
                "properties": properties,
                "created_at": created_at,
            }

    def import_facts(
        self, triples: list, entities: list | tuple = (), dry_run: bool = False
    ) -> dict:
        """Merge exported ``kg_triple``/``kg_entity`` records into this KG in one transaction.

        See :func:`_merge_import` for the rules. With *dry_run*, the merge runs against an
        in-memory snapshot, so the counts are exact and nothing is written.
        """
        if dry_run:
            conn = _snapshot_connection(self.db_path)
        else:
            conn = self._conn()
            conn.execute("BEGIN IMMEDIATE")
        try:
            summary = _merge_import(conn, triples, entities)
            if not dry_run:
                conn.commit()
            return summary
        finally:
            conn.close()

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self):
        current_instant = datetime.now(UTC)
        conn = self._conn()
        entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        temporal_counts = {"current": 0, "expired": 0, "future": 0}
        for valid_from, valid_to in conn.execute("SELECT valid_from, valid_to FROM triples"):
            temporal_counts[_temporal_state(valid_from, valid_to, current_instant)] += 1
        predicates = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT predicate FROM triples ORDER BY predicate"
            ).fetchall()
        ]
        conn.close()
        return {
            "entities": entities,
            "triples": triples,
            "current_facts": temporal_counts["current"],
            "expired_facts": temporal_counts["expired"],
            "future_facts": temporal_counts["future"],
            "relationship_types": predicates,
        }

    # ── Architecture queries ──────────────────────────────────────────────

    def type_dependency_chain(self, type_name: str, max_depth: int = 3) -> dict:
        """
        Recursive graph walk: find ancestors and descendants of a type via
        inherits / implements / extends predicates.

        Walk up: follow outgoing inherits/implements/extends to find ancestors.
        Walk down: follow incoming inherits/implements/extends to find descendants.
        Cycle detection via separate visited sets for each direction.
        max_depth caps traversal per direction (default 3).

        Returns:
            {
                "type": type_name,
                "ancestors": [{"type": ..., "relationship": ..., "depth": ...}, ...],
                "descendants": [{"type": ..., "relationship": ..., "depth": ...}, ...],
            }
        """
        TYPE_PREDICATES = {"inherits", "implements", "extends"}

        # Walk UP: outgoing edges (type → predicate → parent)
        ancestors: list = []
        visited_up: set = {self._entity_id(type_name)}
        queue: list = [(type_name, 0)]
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            facts = self.query_entity(current, direction="outgoing")
            for fact in facts:
                if not fact["current"]:
                    continue
                if fact["predicate"] not in TYPE_PREDICATES:
                    continue
                target = fact["object"]
                target_id = self._entity_id(target)
                if target_id in visited_up:
                    continue
                visited_up.add(target_id)
                ancestors.append(
                    {"type": target, "relationship": fact["predicate"], "depth": depth + 1}
                )
                queue.append((target, depth + 1))

        # Walk DOWN: incoming edges (child → predicate → type)
        descendants: list = []
        visited_down: set = {self._entity_id(type_name)}
        queue = [(type_name, 0)]
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            facts = self.query_entity(current, direction="incoming")
            for fact in facts:
                if not fact["current"]:
                    continue
                if fact["predicate"] not in TYPE_PREDICATES:
                    continue
                target = fact["subject"]
                target_id = self._entity_id(target)
                if target_id in visited_down:
                    continue
                visited_down.add(target_id)
                descendants.append(
                    {"type": target, "relationship": fact["predicate"], "depth": depth + 1}
                )
                queue.append((target, depth + 1))

        return {
            "type": type_name,
            "ancestors": ancestors,
            "descendants": descendants,
        }

    # ── Seed from known facts ─────────────────────────────────────────────

    def seed_from_entity_facts(self, entity_facts: dict):
        """
        Seed the knowledge graph from fact_checker.py ENTITY_FACTS.
        This bootstraps the graph with known ground truth.
        """
        for key, facts in entity_facts.items():
            name = facts.get("full_name", key.capitalize())
            etype = facts.get("type", "person")
            self.add_entity(
                name,
                etype,
                {
                    "gender": facts.get("gender", ""),
                    "birthday": facts.get("birthday", ""),
                },
            )

            # Relationships
            parent = facts.get("parent")
            if parent:
                self.add_triple(
                    name, "child_of", parent.capitalize(), valid_from=facts.get("birthday")
                )

            partner = facts.get("partner")
            if partner:
                self.add_triple(name, "married_to", partner.capitalize())

            relationship = facts.get("relationship", "")
            if relationship == "daughter":
                self.add_triple(
                    name,
                    "is_child_of",
                    facts.get("parent", "").capitalize() or name,
                    valid_from=facts.get("birthday"),
                )
            elif relationship == "husband":
                self.add_triple(name, "is_partner_of", facts.get("partner", name).capitalize())
            elif relationship == "brother":
                self.add_triple(name, "is_sibling_of", facts.get("sibling", name).capitalize())
            elif relationship == "dog":
                self.add_triple(name, "is_pet_of", facts.get("owner", name).capitalize())
                self.add_entity(name, "animal")

            # Interests
            for interest in facts.get("interests", []):
                self.add_triple(name, "loves", interest.capitalize(), valid_from="2025-01-01")
