"""
retrieval_rerank.py — Deterministic reranker for code retrieval rows.

Promotes .csproj/.fsproj/.vbproj results for project-file intent queries and
symbol-matched results for symbol-intent queries. Non-intent queries return
candidates in the original vector order unchanged.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_PROJECT_FILE_EXTS = frozenset({".csproj", ".fsproj", ".vbproj"})

# Single-token keywords (lowercased) that signal project-file intent
_PROJECT_INTENT_TOKENS = frozenset(
    {
        "packagereference",
        "projectreference",
        "targetframework",
        "nuget",
        "csproj",
        "fsproj",
        "vbproj",
        "sdk",
        "itemgroup",
        "propertygroup",
    }
)

# Two-word compounds that signal project-file intent (substring match on lowercased query)
_PROJECT_INTENT_BIGRAMS = frozenset(
    {
        "package reference",
        "project reference",
        "target framework",
    }
)

# Bonus magnitudes subtracted from L2 distance (larger = stronger promotion)
_PROJECT_FILE_BONUS = 0.50
_SOURCE_STEM_MATCH_BONUS = 0.20
_SYMBOL_MATCH_BONUS = 0.15


def _query_tokens(query: str) -> List[str]:
    """Return lowercased alphanumeric identifier tokens from a query string."""
    return [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", query)]


def _source_stem(source_file: str) -> str:
    """Return the lowercased filename stem (no directory, no extension)."""
    name = source_file.rsplit("/", 1)[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name.lower()


def has_project_file_intent(query: str) -> bool:
    """Return True if the query concerns .NET project file build structure."""
    tokens = set(_query_tokens(query))
    if tokens & _PROJECT_INTENT_TOKENS:
        return True
    q_lower = query.lower()
    return any(bigram in q_lower for bigram in _PROJECT_INTENT_BIGRAMS)


def has_symbol_intent(query: str) -> bool:
    """Return True if the query contains CamelCase identifiers (e.g. TodoItem, IDateTime)."""
    return bool(re.search(r"[A-Z][a-z][A-Za-z0-9]*[A-Z]", query))


def should_overfetch(query: str) -> bool:
    """Return True when overfetching candidates would improve recall for this query."""
    return has_project_file_intent(query) or has_symbol_intent(query)


# Bounds for the overfetch candidate window. The 150 cap bounds rerank cost on
# normal n_results values; the n_results floor guarantees a caller asking for
# more than 150 results still receives the count it requested.
_OVERFETCH_MULTIPLIER = 15
_OVERFETCH_MIN = 50
_OVERFETCH_MAX = 150


def overfetch_limit(n_results: int) -> int:
    """
    Return the LanceDB ``limit()`` value for an intent query asking for n_results.

    Bounded to [n_results, max(_OVERFETCH_MAX, n_results)] so the candidate
    window never falls below what the caller requested.
    """
    bounded = min(max(n_results * _OVERFETCH_MULTIPLIER, _OVERFETCH_MIN), _OVERFETCH_MAX)
    return max(n_results, bounded)


def _score(
    row: Dict[str, Any],
    query_tokens: List[str],
    project_intent: bool,
    symbol_intent: bool,
) -> float:
    """Composite rank score (lower = better). Base is L2 distance; bonuses are subtracted."""
    distance = float(row.get("_distance", 0.0))
    bonus = 0.0

    source_file = str(row.get("source_file") or row.get("source") or "")
    stem = _source_stem(source_file)
    token_set = set(query_tokens)

    if project_intent:
        if any(source_file.lower().endswith(ext) for ext in _PROJECT_FILE_EXTS):
            bonus += _PROJECT_FILE_BONUS
            if stem in token_set:
                bonus += _SOURCE_STEM_MATCH_BONUS

    if symbol_intent:
        symbol_name = str(row.get("symbol_name") or "").lower()
        if stem in token_set:
            bonus += _SOURCE_STEM_MATCH_BONUS
        if symbol_name and symbol_name in token_set:
            bonus += _SYMBOL_MATCH_BONUS

    return distance - bonus


def rerank(
    candidates: List[Dict[str, Any]],
    query: str,
    n_results: int,
) -> List[Dict[str, Any]]:
    """
    Rerank a candidate list for a single query, returning at most n_results rows.

    Non-intent queries: return candidates[:n_results] in original vector order.
    Intent queries: sort by composite score (lower = better), tie-break by original rank.
    """
    if not candidates:
        return []

    is_project = has_project_file_intent(query)
    is_symbol = has_symbol_intent(query)

    if not is_project and not is_symbol:
        return candidates[:n_results]

    tokens = _query_tokens(query)

    scored = [
        (i, _score(row, tokens, is_project, is_symbol), row) for i, row in enumerate(candidates)
    ]
    # Primary sort by composite score; secondary by original vector rank for stability
    scored.sort(key=lambda x: (x[1], x[0]))

    return [row for _, _, row in scored[:n_results]]
