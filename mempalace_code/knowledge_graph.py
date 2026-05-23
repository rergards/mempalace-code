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
    from mempalace_code.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()
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
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

# ── Temporal validation helpers ───────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


def _parse_temporal(value: str | None) -> date | datetime | None:
    """Parse a temporal string to a date or datetime, or return None for blank.

    Accepts: None/empty, YYYY-MM-DD, or explicit UTC ISO datetime (Z or +00:00).
    Raises ValueError for any other format (natural language, naive datetime, etc.).
    """
    if not value:
        return None
    if _DATE_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid temporal value {value!r}: {exc}") from exc
    if _DATETIME_UTC_RE.match(value):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"Invalid temporal value {value!r}: {exc}") from exc
    raise ValueError(
        f"Invalid temporal value {value!r}: expected YYYY-MM-DD or UTC ISO datetime"
        " (e.g. 2026-01-01T12:00:00Z)"
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
    assert cmp_vf is not None
    assert cmp_vt is not None
    if cmp_vt < cmp_vf:
        raise ValueError("Inverted validity window: valid_to precedes valid_from")


def _in_window(
    valid_from_str: str | None, valid_to_str: str | None, as_of: date | datetime
) -> bool:
    """Return True if as_of falls within [valid_from, valid_to] (inclusive).

    NULL bounds are treated as unbounded. Invalid stored temporal strings are
    treated as unbounded (backward-compatible with pre-validation data).
    """
    cmp = _as_comparable(as_of)
    assert cmp is not None

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


DEFAULT_KG_PATH = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")


class KnowledgeGraph:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_KG_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = self._conn()
        conn.executescript("""
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
        """)
        conn.commit()
        conn.close()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _entity_id(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("'", "")

    # ── Write operations ──────────────────────────────────────────────────

    def add_entity(self, name: str, entity_type: str = "unknown", properties: dict | None = None):
        """Add or update an entity node."""
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

        Examples:
            add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
            add_triple("Max", "does", "swimming", valid_from="2025-01-01")
            add_triple("Alice", "attended", "Conference", valid_from="2026-05-10", valid_to="2026-05-10")
        """
        _validate_window(_parse_temporal(valid_from), _parse_temporal(valid_to))

        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")

        # Auto-create entities if they don't exist
        conn = self._conn()
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject))
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, obj))

        # Check for existing identical triple
        existing = conn.execute(
            "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (sub_id, pred, obj_id),
        ).fetchone()

        if existing:
            conn.close()
            return existing[0]  # Already exists and still valid

        triple_id = f"t_{sub_id}_{pred}_{obj_id}_{hashlib.md5(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:8]}"

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
        conn.commit()
        conn.close()
        return triple_id

    def invalidate_by_source_file(
        self, source_file: str, ended: str | None = None, predicates=None
    ):
        """Set valid_to on all active triples (valid_to IS NULL) whose source_file matches.

        When *predicates* is a non-empty list/tuple of predicate strings, only triples
        whose predicate is in that set are expired — other predicates are left untouched.
        Omit *predicates* (or pass ``None``) to expire all active triples for the file,
        which is the original behaviour used by the per-file KG extraction pass.

        Used by the miner before re-parsing a changed or deleted source file and by the
        architecture extraction pass to refresh only architecture predicates without
        expiring type-dependency facts (implements, inherits, depends_on, etc.).
        """
        ended = ended or date.today().isoformat()
        _parse_temporal(ended)  # raises ValueError for invalid temporal strings
        conn = self._conn()
        if predicates:
            placeholders = ",".join("?" * len(predicates))
            conn.execute(
                f"UPDATE triples SET valid_to=? WHERE source_file=? AND valid_to IS NULL"
                f" AND predicate IN ({placeholders})",
                [ended, source_file, *predicates],
            )
        else:
            conn.execute(
                "UPDATE triples SET valid_to=? WHERE source_file=? AND valid_to IS NULL",
                (ended, source_file),
            )
        conn.commit()
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
        ended = ended or date.today().isoformat()
        _parse_temporal(ended)  # raises ValueError for invalid temporal strings
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

        Expires triples whose ``predicate`` is in *predicates* AND whose ``source_file``
        satisfies at least one of:
          - equals ``resolved_root`` exactly (edge case: file at the root itself)
          - starts with ``resolved_root + "/"`` (path-boundary-safe prefix)
          - equals one of the strings in *sentinels* (for virtual sentinel source_file
            values such as ``__arch_ns_project__:<wing>`` that have no real path)

        *project_root* is resolved via ``Path(project_root).resolve()`` before comparison,
        so trailing separators and symlinks are handled transparently.  Stored
        ``source_file`` values are already resolved absolute paths (written by the miner),
        so the comparison is between two canonical paths.

        SQL ``LIKE`` metacharacters (``_`` and ``%``) in the resolved root are escaped
        with an explicit ``ESCAPE`` clause so that paths like ``/tmp/a_b`` only match
        files actually under ``/tmp/a_b/`` and never under sibling ``/tmp/aXb/``.
        """
        if not predicates:
            return
        ended = ended or date.today().isoformat()
        _parse_temporal(ended)  # raises ValueError for invalid temporal strings
        resolved = str(Path(project_root).resolve())
        # Escape SQL LIKE wildcards in the resolved root so that '_' and '%' in
        # project paths match literally rather than as wildcards. Escape the
        # escape char itself first to keep substitution unambiguous.
        escaped_root = resolved.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        prefix_pattern = escaped_root + "/%"

        pred_placeholders = ",".join("?" * len(predicates))
        params: list = [ended, *predicates, resolved, prefix_pattern]

        sentinel_clauses = ""
        if sentinels:
            for s in sentinels:
                sentinel_clauses += " OR source_file = ?"
                params.append(s)

        conn = self._conn()
        conn.execute(
            f"UPDATE triples SET valid_to=? WHERE valid_to IS NULL"
            f" AND predicate IN ({pred_placeholders})"
            f" AND (source_file = ? OR source_file LIKE ? ESCAPE '\\'{sentinel_clauses})",
            params,
        )
        conn.commit()
        conn.close()

    def invalidate_legacy_arch_ns_project_for_wing(
        self,
        legacy_sentinel: str,
        wing_name: str,
        ended: str | None = None,
    ) -> None:
        """Expire pre-WING-SCOPE namespace→project rows for a single wing.

        Pre-WING-SCOPE releases stored namespace→project triples with a single
        shared ``source_file`` sentinel (e.g. ``__arch_ns_project__``) that did
        not include the wing name. Those legacy rows are not matched by
        ``invalidate_arch_by_project_root``'s wing-scoped sentinel
        (``__arch_ns_project__:<wing>``) and so persist forever as orphaned
        current facts after upgrade.

        This helper expires only the legacy rows whose ``object`` resolves to
        *wing_name*, leaving other wings' legacy rows intact until they are
        themselves mined.  After every wing has been mined once on the new
        release, all legacy sentinel rows have been retired.
        """
        ended = ended or date.today().isoformat()
        _parse_temporal(ended)  # raises ValueError for invalid temporal strings
        obj_id = self._entity_id(wing_name)
        conn = self._conn()
        conn.execute(
            "UPDATE triples SET valid_to=? WHERE valid_to IS NULL"
            " AND source_file=? AND predicate='in_project' AND object=?",
            (ended, legacy_sentinel, obj_id),
        )
        conn.commit()
        conn.close()

    def invalidate(self, subject: str, predicate: str, obj: str, ended: str | None = None):
        """Mark a relationship as no longer valid (set valid_to date)."""
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")
        ended_str = ended or date.today().isoformat()

        ended_parsed = _parse_temporal(ended_str)  # raises ValueError if invalid
        cmp_ended = _as_comparable(ended_parsed)

        conn = self._conn()

        # Validate ended against each active row's valid_from before mutating
        active = conn.execute(
            "SELECT valid_from FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (sub_id, pred, obj_id),
        ).fetchall()
        for (vf_str,) in active:
            if vf_str is not None:
                try:
                    cmp_vf = _as_comparable(_parse_temporal(vf_str))
                except ValueError:
                    continue  # skip rows with legacy invalid temporal strings
                if cmp_vf is not None and cmp_ended is not None and cmp_ended < cmp_vf:
                    conn.close()
                    raise ValueError(
                        f"Inverted invalidation: ended ({ended_str!r}) precedes"
                        f" active valid_from ({vf_str!r})"
                    )

        conn.execute(
            "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (ended_str, sub_id, pred, obj_id),
        )
        conn.commit()
        conn.close()

    # ── Query operations ──────────────────────────────────────────────────

    def query_entity(self, name: str, as_of: str | None = None, direction: str = "outgoing"):
        """
        Get all relationships for an entity.

        direction: "outgoing" (entity → ?), "incoming" (? → entity), "both"
        as_of: ISO date or UTC datetime — only return facts valid at that time
        """
        eid = self._entity_id(name)
        as_of_parsed = _parse_temporal(as_of)  # raises ValueError for invalid inputs
        conn = self._conn()

        results = []

        if direction in ("outgoing", "both"):
            for row in conn.execute(
                "SELECT t.*, e.name as obj_name FROM triples t JOIN entities e ON t.object = e.id WHERE t.subject = ?",
                (eid,),
            ).fetchall():
                if as_of_parsed is not None and not _in_window(row[4], row[5], as_of_parsed):
                    continue
                results.append(
                    {
                        "direction": "outgoing",
                        "subject": name,
                        "predicate": row[2],
                        "object": row[10],  # obj_name
                        "valid_from": row[4],
                        "valid_to": row[5],
                        "confidence": row[6],
                        "source_closet": row[7],
                        "current": row[5] is None,
                    }
                )

        if direction in ("incoming", "both"):
            for row in conn.execute(
                "SELECT t.*, e.name as sub_name FROM triples t JOIN entities e ON t.subject = e.id WHERE t.object = ?",
                (eid,),
            ).fetchall():
                if as_of_parsed is not None and not _in_window(row[4], row[5], as_of_parsed):
                    continue
                results.append(
                    {
                        "direction": "incoming",
                        "subject": row[10],  # sub_name
                        "predicate": row[2],
                        "object": name,
                        "valid_from": row[4],
                        "valid_to": row[5],
                        "confidence": row[6],
                        "source_closet": row[7],
                        "current": row[5] is None,
                    }
                )

        conn.close()
        return results

    def query_relationship(self, predicate: str, as_of: str | None = None):
        """Get all triples with a given relationship type."""
        pred = predicate.lower().replace(" ", "_")
        as_of_parsed = _parse_temporal(as_of)  # raises ValueError for invalid inputs
        conn = self._conn()

        results = []
        for row in conn.execute(
            """
            SELECT t.*, s.name as sub_name, o.name as obj_name
            FROM triples t
            JOIN entities s ON t.subject = s.id
            JOIN entities o ON t.object = o.id
            WHERE t.predicate = ?
            """,
            (pred,),
        ).fetchall():
            if as_of_parsed is not None and not _in_window(row[4], row[5], as_of_parsed):
                continue
            results.append(
                {
                    "subject": row[10],
                    "predicate": pred,
                    "object": row[11],
                    "valid_from": row[4],
                    "valid_to": row[5],
                    "current": row[5] is None,
                }
            )
        conn.close()
        return results

    def timeline(self, entity_name: str | None = None):
        """Get all facts in chronological order, optionally filtered by entity."""
        conn = self._conn()
        if entity_name:
            eid = self._entity_id(entity_name)
            rows = conn.execute(
                """
                SELECT t.*, s.name as sub_name, o.name as obj_name
                FROM triples t
                JOIN entities s ON t.subject = s.id
                JOIN entities o ON t.object = o.id
                WHERE (t.subject = ? OR t.object = ?)
                ORDER BY t.valid_from ASC NULLS LAST
                LIMIT 100
            """,
                (eid, eid),
            ).fetchall()
        else:
            rows = conn.execute("""
                SELECT t.*, s.name as sub_name, o.name as obj_name
                FROM triples t
                JOIN entities s ON t.subject = s.id
                JOIN entities o ON t.object = o.id
                ORDER BY t.valid_from ASC NULLS LAST
                LIMIT 100
            """).fetchall()

        conn.close()
        return [
            {
                "subject": r[10],
                "predicate": r[2],
                "object": r[11],
                "valid_from": r[4],
                "valid_to": r[5],
                "current": r[5] is None,
            }
            for r in rows
        ]

    def iter_all_triples(self, batch_size=500):
        """Yield batches of triple dicts without the LIMIT 100 cap.

        Each dict contains: id, subject, predicate, object, valid_from, valid_to,
        confidence, source_closet, source_file.
        """
        conn = self._conn()
        cursor = conn.execute("""
            SELECT t.id, s.name AS subject, t.predicate, o.name AS object,
                   t.valid_from, t.valid_to, t.confidence, t.source_closet, t.source_file
            FROM triples t
            JOIN entities s ON t.subject = s.id
            JOIN entities o ON t.object = o.id
            ORDER BY t.extracted_at ASC
        """)
        cols = [d[0] for d in cursor.description]
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield [dict(zip(cols, r)) for r in rows]
        conn.close()

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self):
        conn = self._conn()
        entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        current = conn.execute("SELECT COUNT(*) FROM triples WHERE valid_to IS NULL").fetchone()[0]
        expired = triples - current
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
            "current_facts": current,
            "expired_facts": expired,
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
