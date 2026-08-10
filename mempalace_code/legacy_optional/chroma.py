"""
legacy_optional/chroma.py — Centralized ChromaDB legacy-backend loading.

Keeps the optional ``[chroma]`` extra import in one place, outside the
protected ``storage`` layer. ``mempalace_code.storage`` reaches this module
through ``importlib.import_module()`` rather than a static import — the
architecture guard (``scripts/architecture_guard.py``) treats ``storage`` as a
protected layer that must not statically import ``legacy_optional``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mempalace_code._chroma_store import ChromaStore


def get_chroma_store_class() -> type[ChromaStore]:
    """Return the ``ChromaStore`` class.

    Raises:
        ImportError: if the ``[chroma]`` extra is not installed. The original
            ``ImportError`` is preserved as ``__cause__``.
    """
    try:
        from mempalace_code._chroma_store import ChromaStore
    except ImportError as exc:
        raise ImportError(
            "ChromaStore requires the [chroma] extra: pip install 'mempalace-code[chroma]'"
        ) from exc
    return ChromaStore


def open_chroma_store(
    palace_path: str, collection_name: str = "mempalace_drawers", create: bool = True
) -> Any:
    """Instantiate a ``ChromaStore``.

    Raises:
        ImportError: if the ``[chroma]`` extra is not installed. The original
            ``ImportError`` is preserved as ``__cause__``.
    """
    chroma_store_cls = get_chroma_store_class()
    return chroma_store_cls(palace_path, collection_name=collection_name, create=create)
