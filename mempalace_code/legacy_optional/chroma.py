"""
legacy_optional/chroma.py — Centralized ChromaDB migration-bridge loading.

Keeps the optional ``[chroma-migration]`` extra import in one place, outside the
ordinary runtime path. ``mempalace_code.storage`` must not reach this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mempalace_code._chroma_store import ChromaStore

CHROMA_MIGRATION_INSTALL_HINT = (
    "chromadb is required only for ChromaDB-to-LanceDB migration. "
    "Install the migration bridge with: pip install 'mempalace-code[chroma-migration]'"
)


def get_chroma_store_class() -> type[ChromaStore]:
    """Return the private migration ``ChromaStore`` adapter.

    Raises:
        ImportError: if the migration extra is not installed. The original
            ``ImportError`` is preserved as ``__cause__``.
    """
    try:
        from mempalace_code._chroma_store import ChromaStore
    except ImportError as exc:
        raise ImportError(CHROMA_MIGRATION_INSTALL_HINT) from exc
    return ChromaStore


def open_chroma_store(
    palace_path: str, collection_name: str = "mempalace_drawers", create: bool = True
) -> Any:
    """Instantiate a ``ChromaStore``.

    Raises:
        ImportError: if the migration extra is not installed. The original
            ``ImportError`` is preserved as ``__cause__``.
    """
    chroma_store_cls = get_chroma_store_class()
    return chroma_store_cls(palace_path, collection_name=collection_name, create=create)
