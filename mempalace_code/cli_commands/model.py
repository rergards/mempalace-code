"""Model command handlers: fetch-model."""

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _quiet_hf_model_output():
    """Suppress third-party model-loader noise while preserving exceptions."""
    loggers = [logging.getLogger("huggingface_hub")]
    previous = [logger.level for logger in loggers]
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stdout = os.dup(1)
    old_stderr = os.dup(2)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        for logger in loggers:
            logger.setLevel(logging.ERROR)
        active_error = None
        cleanup_error = None
        try:
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            try:
                yield
            except BaseException as exc:
                active_error = exc
                raise
        finally:
            try:
                try:
                    sys.stdout.flush()
                except BaseException as exc:
                    cleanup_error = exc
                try:
                    sys.stderr.flush()
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
            finally:
                try:
                    os.dup2(old_stdout, 1)
                finally:
                    os.dup2(old_stderr, 2)
            if active_error is None and cleanup_error is not None:
                raise cleanup_error
    finally:
        try:
            os.close(devnull)
        finally:
            try:
                os.close(old_stdout)
            finally:
                try:
                    os.close(old_stderr)
                finally:
                    for logger, level in zip(loggers, previous):
                        logger.setLevel(level)


def _hf_model_id(model_name: str) -> str:
    return model_name if "/" in model_name else f"sentence-transformers/{model_name}"


def _is_existing_model_path(model_name: str) -> bool:
    try:
        return Path(model_name).expanduser().exists()
    except OSError:
        return False


def _model_cache_dir(model_name: str) -> Path | None:
    if _is_existing_model_path(model_name):
        return None
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return hf_home / "hub" / f"models--{'--'.join(_hf_model_id(model_name).split('/'))}"


def _load_model(model_name: str, *, local_files_only: bool):
    from sentence_transformers import SentenceTransformer

    with _quiet_hf_model_output():
        return SentenceTransformer(model_name, local_files_only=local_files_only)


def fetch_model(model_name: str, force: bool = False) -> None:
    """Ensure *model_name* is available for offline embedding.

    Shared by ``cmd_fetch_model`` and ``cmd_init``.  When *force* is True the
    cached model directory is removed before downloading so a fresh copy is
    retrieved.
    """
    import shutil

    model_dir = _model_cache_dir(model_name)

    if force and model_dir and model_dir.exists():
        print(f"  Removing cached model: {model_dir}")
        shutil.rmtree(model_dir)

    if not force:
        try:
            _load_model(model_name, local_files_only=True)
            print(f"  Model '{model_name}' is already available locally.")
        except Exception:
            if _is_existing_model_path(model_name):
                raise
            print(f"  Downloading model '{model_name}' …")
            print("  Waiting for model download; no input is needed.")
            _load_model(model_name, local_files_only=False)
    else:
        print(f"  Downloading model '{model_name}' …")
        print("  Waiting for model download; no input is needed.")
        _load_model(model_name, local_files_only=False)

    # Report cache location and size
    if model_dir and model_dir.exists():
        size_bytes = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
        size_mb = size_bytes / (1024 * 1024)
        print(f"  Cached at: {model_dir}")
        print(f"  Size on disk: {size_mb:.1f} MB")
    elif _is_existing_model_path(model_name):
        print(f"  Local model path: {Path(model_name).expanduser()}")
    else:
        print("  Model loaded successfully.")
        print(f"  Cache path could not be reported (expected: {model_dir}).")
        print("  No action needed unless offline search or mining fails later.")


def cmd_fetch_model(args):
    from ..storage import DEFAULT_EMBED_MODEL

    model_name = args.model or DEFAULT_EMBED_MODEL
    try:
        fetch_model(model_name, force=args.force)
        print("  Done — embedding model is ready for offline use.")
    except Exception as exc:
        print(f"  Error preparing model: {exc}", file=sys.stderr)
        sys.exit(1)
