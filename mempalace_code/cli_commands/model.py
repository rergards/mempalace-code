"""Model command handlers: fetch-model."""

import os
import sys
from pathlib import Path


def fetch_model(model_name: str, force: bool = False) -> None:
    """Download *model_name* to the HuggingFace Hub cache.

    Shared by ``cmd_fetch_model`` and ``cmd_init``.  When *force* is True the
    cached model directory is removed before downloading so a fresh copy is
    retrieved.
    """
    import shutil

    from sentence_transformers import SentenceTransformer

    # Compute cache dir at call time so HF_HOME env-var changes (e.g. in tests) are respected.
    # huggingface_hub.constants.HF_HUB_CACHE is a module-level string set at import time and
    # does not update when os.environ changes after Python starts.
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cache_dir = hf_home / "hub"
    # Standard Hub layout: models--{org}--{model}
    model_dir = cache_dir / f"models--sentence-transformers--{model_name}"

    if force and model_dir.exists():
        print(f"  Removing cached model: {model_dir}")
        shutil.rmtree(model_dir)

    print(f"  Downloading model '{model_name}' …")
    SentenceTransformer(model_name)

    # Report cache location and size
    if model_dir.exists():
        size_bytes = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
        size_mb = size_bytes / (1024 * 1024)
        print(f"  Cached at: {model_dir}")
        print(f"  Size on disk: {size_mb:.1f} MB")
    else:
        print(f"  Model ready (cache path not found at expected location: {model_dir})")


def cmd_fetch_model(args):
    from ..storage import DEFAULT_EMBED_MODEL

    model_name = args.model or DEFAULT_EMBED_MODEL
    try:
        fetch_model(model_name, force=args.force)
        print("  Done — embedding model is ready for offline use.")
    except Exception as exc:
        print(f"  Error downloading model: {exc}", file=sys.stderr)
        sys.exit(1)
