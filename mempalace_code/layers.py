#!/usr/bin/env python3
"""
layers.py — 4-Layer Memory Stack for mempalace
===================================================

Load only what you need, when you need it.

    Layer 0: Identity       (~100 tokens)   — Always loaded. "Who am I?" (capped at 800 chars)
    Layer 1: Essential Story (~500-800)      — Always loaded. Recent diary/manual notes and
                                               decisions first, then conversations and code.
    Layer 2: On-Demand      (~200-500 each)  — Loaded when a topic/wing comes up.
    Layer 3: Deep Search    (unlimited)      — Full semantic search.

Wake-up cost: ~600-900 tokens (L0+L1). Leaves 95%+ of context free.

Reads from the LanceDB palace drawer store
and ~/.mempalace/identity.txt.
"""

import os
import sys
from pathlib import Path

from .config import MempalaceConfig
from .storage import PalaceReadError, distance_to_similarity, open_store

# ---------------------------------------------------------------------------
# Layer 0 — Identity
# ---------------------------------------------------------------------------


class Layer0:
    """
    ~100 tokens. Always loaded.
    Reads from ~/.mempalace/identity.txt — a plain-text file the user writes.
    Text beyond MAX_CHARS is cut (at a line or word boundary) and ``truncated`` is set.

    Example identity.txt:
        I am Atlas, a personal AI assistant for Alice.
        Traits: warm, direct, remembers everything.
        People: Alice (creator), Bob (Alice's partner).
        Project: A journaling app that helps people process emotions.
    """

    MAX_CHARS = 800  # hard cap (~200 tokens); aim for ~100 tokens

    def __init__(self, identity_path: str | None = None):
        if identity_path is None:
            identity_path = os.path.expanduser("~/.mempalace/identity.txt")
        self.path = identity_path
        self._text = None
        self.truncated = False

    def render(self) -> str:
        """Return the identity text (capped at MAX_CHARS), or a sensible default."""
        if self._text is not None:
            return self._text

        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read().strip()
            except OSError as exc:
                text = f"## L0 — IDENTITY\nCannot read {self.path}: {exc.strerror or exc}"
            if len(text) > self.MAX_CHARS:
                cut = text[: self.MAX_CHARS]
                boundary = max(cut.rfind("\n"), cut.rfind(" "))
                if boundary > self.MAX_CHARS // 2:
                    cut = cut[:boundary]
                text = cut.rstrip() + " ..."
                self.truncated = True
            self._text = text
        else:
            self._text = (
                "## L0 — IDENTITY\nNo identity configured. Create ~/.mempalace/identity.txt"
            )

        return self._text

    def token_estimate(self) -> int:
        return len(self.render()) // 4


# ---------------------------------------------------------------------------
# Layer 1 — Essential Story (auto-generated from palace)
# ---------------------------------------------------------------------------

# Drawers written by an agent or a person (diary entries, manual notes) cannot be
# regenerated from any source and carry the most deliberate memory.
_NOTE_STRATEGIES = frozenset({"diary_v1", "manual_v1"})
_DECISION_NAMES = frozenset({"decision", "decisions"})
_RANK_COLUMNS = ("id", "wing", "room", "topic", "chunker_strategy", "ingest_mode", "filed_at")


def _l1_tier(row: dict) -> int:
    """Return the L1 priority tier of a drawer: lower is shown first."""
    if row.get("chunker_strategy") in _NOTE_STRATEGIES:
        return 0
    if {str(row.get("room") or "").lower(), str(row.get("topic") or "").lower()} & _DECISION_NAMES:
        return 1
    if row.get("ingest_mode") == "convos":
        return 2
    return 3


def _is_noise(text: str) -> bool:
    """Return whether a drawer looks like raw JSON/XML/punctuation rather than prose."""
    stripped = text.strip()
    if len(stripped) < 12:
        return True
    head = stripped[:1]
    after = stripped[1:].lstrip()[:1]
    if head in "[{" and after in ("{", "[", '"', "]", "}"):
        return True
    if head == "<" and (after.isalpha() or after in "?!/"):
        return True
    visible = [c for c in stripped if not c.isspace()]
    letters = sum(1 for c in visible if c.isalpha())
    return letters < 0.4 * len(visible)


class Layer1:
    """
    ~500-800 tokens. Always loaded.

    Picks at most MAX_DRAWERS drawers, in this order, most recently filed first within
    each tier:

      1. diary entries and manually filed drawers (``diary_v1`` / ``manual_v1``)
      2. decision drawers (room or topic ``decision``/``decisions``)
      3. other conversation drawers
      4. project-file drawers

    Drawers that look like raw JSON/XML fragments are skipped. Ranking reads only
    metadata columns; text is fetched for the top-ranked drawers alone. Snippets are
    the verbatim drawer text, whitespace-collapsed and truncated. Knowledge-graph facts
    are not part of L1.
    """

    MAX_DRAWERS = 15  # at most 15 moments in wake-up
    MAX_CHARS = 3200  # hard cap on total L1 text (~800 tokens)
    MAX_CANDIDATES = 150  # ranked drawers whose text may be fetched
    SNIPPET_CHARS = 200
    _FETCH_BATCH = 30

    def __init__(self, palace_path: str | None = None, wing: str | None = None):
        cfg = MempalaceConfig()
        self.palace_path = palace_path or cfg.palace_path
        self.wing = wing

    @staticmethod
    def _rank(store, wing: str | None) -> list:
        """Return drawer ids in L1 priority order, reading metadata columns only."""
        table = store._table
        if table is None:
            return []
        names = set(table.schema.names)
        columns = [column for column in _RANK_COLUMNS if column in names]
        with store._reading():
            rows = store._scan_columns(table, columns).to_pylist()
        if wing:
            rows = [row for row in rows if row.get("wing") == wing]
        rows.sort(key=lambda row: str(row.get("id") or ""))
        rows.sort(key=lambda row: str(row.get("filed_at") or ""), reverse=True)
        rows.sort(key=_l1_tier)
        return [row["id"] for row in rows]

    def generate(self, wing: str | None = None) -> str:
        """Pull the top-ranked drawers from the palace and format them as compact L1 text."""
        wing = wing or self.wing
        if not os.path.isdir(self.palace_path):
            return f"## L1 — No palace found at {self.palace_path}. Run: mempalace-code mine <dir>"
        try:
            store = open_store(self.palace_path, create=False, read_only=True)
            ranked = self._rank(store, wing)
        except PalaceReadError:
            raise  # a damaged palace is not an empty one
        except Exception as exc:
            return f"## L1 — Cannot read palace at {self.palace_path}: {exc}"
        if not ranked:
            return "## L1 — No memories yet."

        picked = []
        seen = set()
        fetched = 0
        candidates = ranked[: self.MAX_CANDIDATES]
        for start in range(0, len(candidates), self._FETCH_BATCH):
            batch = candidates[start : start + self._FETCH_BATCH]
            found = store.get(ids=batch, include=["documents", "metadatas"])
            by_id = {
                doc_id: (doc, meta)
                for doc_id, doc, meta in zip(found["ids"], found["documents"], found["metadatas"])
            }
            for doc_id in batch:
                if doc_id not in by_id:
                    continue
                doc, meta = by_id[doc_id]
                fetched += 1
                snippet = " ".join(doc.split())
                if _is_noise(snippet) or snippet in seen:
                    continue
                seen.add(snippet)
                picked.append((meta, snippet))
                if len(picked) >= self.MAX_DRAWERS:
                    break
            if len(picked) >= self.MAX_DRAWERS:
                break
        if not picked:
            if fetched:
                return "## L1 — No memories yet (only raw data fragments were found)."
            return "## L1 — No memories yet."

        # Group by wing/room in priority order of each group's first drawer.
        groups: dict = {}
        for meta, snippet in picked:
            label = meta.get("room") or "general"
            if not wing:
                label = f"{meta.get('wing') or '?'}/{label}"
            groups.setdefault(label, []).append((meta, snippet))

        lines = ["## L1 — ESSENTIAL STORY"]
        total_len = 0
        for label, entries in groups.items():
            room_line = f"\n[{label}]"
            lines.append(room_line)
            total_len += len(room_line)

            for meta, snippet in entries:
                if len(snippet) > self.SNIPPET_CHARS:
                    snippet = snippet[: self.SNIPPET_CHARS - 3] + "..."
                source = meta.get("source_file")
                hint = Path(source).name if source else (meta.get("date") or "")
                entry_line = f"  - {snippet}"
                if hint:
                    entry_line += f"  ({hint})"

                if total_len + len(entry_line) > self.MAX_CHARS:
                    lines.append("  ... (more in L3 search)")
                    return "\n".join(lines)

                lines.append(entry_line)
                total_len += len(entry_line)

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Layer 2 — On-Demand (wing/room filtered retrieval)
# ---------------------------------------------------------------------------


class Layer2:
    """
    ~200-500 tokens per retrieval.
    Loaded when a specific topic or wing comes up in conversation.
    Queries the palace drawer store with a wing/room filter.
    """

    def __init__(self, palace_path: str | None = None):
        cfg = MempalaceConfig()
        self.palace_path = palace_path or cfg.palace_path

    def retrieve(
        self, wing: str | None = None, room: str | None = None, n_results: int = 10
    ) -> str:
        """Retrieve drawers filtered by wing and/or room."""
        try:
            store = open_store(self.palace_path, create=False, read_only=True)
            col = store
        except Exception:
            return "No palace found."

        where = {}
        if wing and room:
            where = {"$and": [{"wing": wing}, {"room": room}]}
        elif wing:
            where = {"wing": wing}
        elif room:
            where = {"room": room}

        kwargs = {"include": ["documents", "metadatas"], "limit": n_results}
        if where:
            kwargs["where"] = where

        try:
            results = col.get(**kwargs)
        except Exception as e:
            return f"Retrieval error: {e}"

        docs = results.get("documents", [])
        metas = results.get("metadatas", [])

        if not docs:
            label = f"wing={wing}" if wing else ""
            if room:
                label += f" room={room}" if label else f"room={room}"
            return f"No drawers found for {label}."

        lines = [f"## L2 — ON-DEMAND ({len(docs)} drawers)"]
        for doc, meta in zip(docs[:n_results], metas[:n_results]):
            room_name = meta.get("room", "?")
            source = Path(meta.get("source_file", "")).name if meta.get("source_file") else ""
            snippet = doc.strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            entry = f"  [{room_name}] {snippet}"
            if source:
                entry += f"  ({source})"
            lines.append(entry)

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Layer 3 — Deep Search (full semantic search via the palace drawer store)
# ---------------------------------------------------------------------------


class Layer3:
    """
    Unlimited depth. Semantic search against the full palace.
    Reuses searcher.py logic against mempalace_drawers.
    """

    def __init__(self, palace_path: str | None = None):
        cfg = MempalaceConfig()
        self.palace_path = palace_path or cfg.palace_path

    def search(
        self, query: str, wing: str | None = None, room: str | None = None, n_results: int = 5
    ) -> str:
        """Semantic search, returns compact result text."""
        try:
            store = open_store(self.palace_path, create=False)
            col = store
        except Exception:
            return "No palace found."

        where = {}
        if wing and room:
            where = {"$and": [{"wing": wing}, {"room": room}]}
        elif wing:
            where = {"wing": wing}
        elif room:
            where = {"room": room}

        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
            # Plain cosine order: L3 reports similarity, not the code-intent rerank.
            "intent_rerank": False,
        }
        if where:
            kwargs["where"] = where

        try:
            results = col.query(**kwargs)
        except Exception as e:
            return f"Search error: {e}"

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]

        if not docs:
            return "No results found."

        lines = [f'## L3 — SEARCH RESULTS for "{query}"']
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
            similarity = distance_to_similarity(dist)
            wing_name = meta.get("wing", "?")
            room_name = meta.get("room", "?")
            source = Path(meta.get("source_file", "")).name if meta.get("source_file") else ""

            snippet = doc.strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."

            lines.append(f"  [{i}] {wing_name}/{room_name} (sim={similarity})")
            lines.append(f"      {snippet}")
            if source:
                lines.append(f"      src: {source}")

        return "\n".join(lines)

    def search_raw(
        self, query: str, wing: str | None = None, room: str | None = None, n_results: int = 5
    ) -> list:
        """Return raw dicts instead of formatted text."""
        try:
            store = open_store(self.palace_path, create=False)
            col = store
        except Exception:
            return []

        where = {}
        if wing and room:
            where = {"$and": [{"wing": wing}, {"room": room}]}
        elif wing:
            where = {"wing": wing}
        elif room:
            where = {"room": room}

        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
            # Plain cosine order: L3 reports similarity, not the code-intent rerank.
            "intent_rerank": False,
        }
        if where:
            kwargs["where"] = where

        try:
            results = col.query(**kwargs)
        except Exception:
            return []

        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            hits.append(
                {
                    "text": doc,
                    "wing": meta.get("wing", "unknown"),
                    "room": meta.get("room", "unknown"),
                    "source_file": Path(meta.get("source_file", "?")).name,
                    "similarity": distance_to_similarity(dist),
                    "metadata": meta,
                }
            )
        return hits


# ---------------------------------------------------------------------------
# MemoryStack — unified interface
# ---------------------------------------------------------------------------


class MemoryStack:
    """
    The full 4-layer stack. One class, one palace, everything works.

        stack = MemoryStack()
        print(stack.wake_up())                # L0 + L1 (~600-900 tokens)
        print(stack.recall(wing="my_app"))     # L2 on-demand
        print(stack.search("pricing change"))  # L3 deep search
    """

    def __init__(self, palace_path: str | None = None, identity_path: str | None = None):
        cfg = MempalaceConfig()
        self.palace_path = palace_path or cfg.palace_path
        self.identity_path = identity_path or os.path.expanduser("~/.mempalace/identity.txt")

        self.l0 = Layer0(self.identity_path)
        self.l1 = Layer1(self.palace_path)
        self.l2 = Layer2(self.palace_path)
        self.l3 = Layer3(self.palace_path)

    def wake_up(self, wing: str | None = None) -> str:
        """
        Generate wake-up text: L0 (identity) + L1 (essential story).
        Typically ~600-900 tokens. Inject into system prompt or first message.

        Args:
            wing: Optional wing filter for L1 (project-specific wake-up).
        """
        parts = []

        # L0: Identity
        parts.append(self.l0.render())
        parts.append("")

        # L1: Essential Story (the wing applies to this call only)
        parts.append(self.l1.generate(wing=wing))

        return "\n".join(parts)

    def recall(self, wing: str | None = None, room: str | None = None, n_results: int = 10) -> str:
        """On-demand L2 retrieval filtered by wing/room."""
        return self.l2.retrieve(wing=wing, room=room, n_results=n_results)

    def search(
        self, query: str, wing: str | None = None, room: str | None = None, n_results: int = 5
    ) -> str:
        """Deep L3 semantic search."""
        return self.l3.search(query, wing=wing, room=room, n_results=n_results)

    def status(self) -> dict:
        """Status of all layers."""
        result = {
            "palace_path": self.palace_path,
            "L0_identity": {
                "path": self.identity_path,
                "exists": os.path.exists(self.identity_path),
                "tokens": self.l0.token_estimate(),
            },
            "L1_essential": {
                "description": (
                    "Recent diary entries and manual notes first, then decisions, "
                    "conversations, and project drawers"
                ),
            },
            "L2_on_demand": {
                "description": "Wing/room filtered retrieval",
            },
            "L3_deep_search": {
                "description": "Full semantic search via the palace drawer store",
            },
        }

        # Count drawers
        try:
            store = open_store(self.palace_path, create=False, read_only=True)
            col = store
            count = col.count()
            result["total_drawers"] = count
        except Exception:
            result["total_drawers"] = 0

        return result


# ---------------------------------------------------------------------------
# CLI (standalone)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    def usage():
        print("layers.py — 4-Layer Memory Stack")
        print()
        print("Usage:")
        print("  python layers.py wake-up              Show L0 + L1")
        print("  python layers.py wake-up --wing=NAME  Wake-up for a specific project")
        print("  python layers.py recall --wing=NAME   On-demand L2 retrieval")
        print("  python layers.py search <query>       Deep L3 search")
        print("  python layers.py status               Show layer status")
        sys.exit(0)

    if len(sys.argv) < 2:
        usage()

    cmd = sys.argv[1]

    # Parse flags
    flags = {}
    positional = []
    for arg in sys.argv[2:]:
        if arg.startswith("--") and "=" in arg:
            key, val = arg.split("=", 1)
            flags[key.lstrip("-")] = val
        elif not arg.startswith("--"):
            positional.append(arg)

    palace_path = flags.get("palace")
    stack = MemoryStack(palace_path=palace_path)

    if cmd in ("wake-up", "wakeup"):
        wing = flags.get("wing")
        text = stack.wake_up(wing=wing)
        print(f"Wake-up text (~{len(text) // 4} tokens):", file=sys.stderr)
        print(text)

    elif cmd == "recall":
        wing = flags.get("wing")
        room = flags.get("room")
        text = stack.recall(wing=wing, room=room)
        print(text)

    elif cmd == "search":
        query = " ".join(positional) if positional else ""
        if not query:
            print("Usage: python layers.py search <query>")
            sys.exit(1)
        wing = flags.get("wing")
        room = flags.get("room")
        text = stack.search(query, wing=wing, room=room)
        print(text)

    elif cmd == "status":
        s = stack.status()
        print(json.dumps(s, indent=2))

    else:
        usage()
