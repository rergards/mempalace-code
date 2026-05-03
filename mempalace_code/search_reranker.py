"""
search_reranker.py — BM25-style hybrid reranker for LanceDB candidate lists.

Reranks an already-retrieved vector candidate pool using token overlap on the
document text plus metadata surface (source_file path parts, symbol_name,
symbol_type, language, room, wing). Vector rank is preserved as a tie-breaker
so candidates with no lexical evidence are not randomly reshuffled.
"""

from __future__ import annotations

import re
from typing import Any


def _tokenize(text: str) -> list[str]:
    """
    Split text into lowercase tokens.

    Handles camelCase/PascalCase boundaries, file path separators,
    extension dots, and all non-alphanumeric delimiters so that
    PackageReference → [package, reference], Infrastructure.csproj →
    [infrastructure, csproj], and src/Main.cs → [src, main, cs].
    """
    if not text:
        return []
    # Split at lowercase→uppercase and UPPER→Upper boundaries
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    # Split on every non-alphanumeric character
    tokens = re.split(r"[^a-zA-Z0-9]+", text)
    return [t.lower() for t in tokens if t]


def _candidate_tokens(candidate: dict[str, Any] | None) -> list[str]:
    """Build the full lexical token surface; None/missing fields are skipped."""
    if not candidate:
        return []

    parts = []

    doc = candidate.get("text")
    if doc:
        parts.append(str(doc))

    for field in ("source_file", "symbol_name", "symbol_type", "language", "room", "wing"):
        val = candidate.get(field)
        if val:
            parts.append(str(val))

    return _tokenize(" ".join(parts))


def _token_overlap(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """
    Fraction of distinct query tokens present in the document token set.
    Returns 0.0 when either set is empty.
    """
    if not query_tokens or not doc_tokens:
        return 0.0
    unique_query = set(query_tokens)
    doc_set = set(doc_tokens)
    return len(unique_query & doc_set) / len(unique_query)


def hybrid_rerank(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    lexical_weight: float = 0.5,
) -> list[dict[str, Any]]:
    """
    Rerank candidates by blending vector rank position with BM25-style token overlap.

    Args:
        query: The search query string.
        candidates: Ordered list of candidate dicts (vector-best first). Each dict
            should include "text"; metadata fields "source_file", "symbol_name",
            "symbol_type", "language", "room", "wing" are included in the lexical
            surface when present. None or missing fields are silently skipped.
        lexical_weight: Blend factor in [0, 1]. 0 = pure vector order; 1 = pure
            lexical. Default 0.5 gives equal weight to lexical and vector evidence.

    Returns:
        A new list with candidates reordered by hybrid score (descending). Original
        vector rank breaks ties so semantically close candidates with equal lexical
        scores keep their LanceDB order. All input candidates are preserved.
    """
    if not candidates:
        return []

    query_tokens = _tokenize(query)
    n = len(candidates)

    scored = []
    for rank, cand in enumerate(candidates):
        doc_tokens = _candidate_tokens(cand)
        lex = _token_overlap(query_tokens, doc_tokens)
        # Normalise vector rank: rank 0 (best) → 1.0, rank n-1 → 1/n
        vec_score = (n - rank) / n
        hybrid = (1.0 - lexical_weight) * vec_score + lexical_weight * lex
        scored.append((hybrid, rank, cand))

    # Descending by hybrid score; ascending original rank breaks ties
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [cand for _, _, cand in scored]
