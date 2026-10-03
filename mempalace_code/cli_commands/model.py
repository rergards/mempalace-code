"""Model command handlers: fetch-model."""

import importlib
import logging
import os
import shlex
import stat
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


@contextmanager
def _quiet_fastembed_logs():
    """Silence FastEmbed's loguru ERROR lines; failures are reported once by fetch-model."""
    try:
        from loguru import logger as loguru_logger
    except ImportError:
        yield
        return
    loguru_logger.disable("fastembed")
    try:
        yield
    finally:
        loguru_logger.enable("fastembed")


def _say(message: str) -> None:
    """Print progress immediately so captured stdout stays ordered with stderr errors."""
    print(message, flush=True)


class ModelFetchError(RuntimeError):
    """A fetch-model failure whose message already names its one recovery."""


def _hf_model_id(model_name: str) -> str:
    return model_name if "/" in model_name else f"sentence-transformers/{model_name}"


def _is_existing_model_path(model_name: str) -> bool:
    try:
        return Path(model_name).expanduser().exists()
    except OSError:
        return False


def _model_cache_dir(model_name: str) -> Path | None:
    from ..storage import canonical_fastembed_cache_root, is_canonical_embed_model

    if is_canonical_embed_model(model_name):
        return canonical_fastembed_cache_root()
    if _is_existing_model_path(model_name):
        return None
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return hf_home / "hub" / f"models--{'--'.join(_hf_model_id(model_name).split('/'))}"


def _load_model(model_name: str, *, local_files_only: bool):
    from ..storage import _FastEmbedder, is_canonical_embed_model, preflight_embed_model

    if is_canonical_embed_model(model_name):
        with _quiet_fastembed_logs():
            return _FastEmbedder(local_files_only=local_files_only)

    preflight_embed_model(model_name)
    SentenceTransformer = importlib.import_module("sentence_transformers").SentenceTransformer

    with _quiet_hf_model_output():
        return SentenceTransformer(model_name, local_files_only=local_files_only)


def _fetch_command(model_name: str, *, force: bool = False) -> str:
    return f"mempalace-code fetch-model --model {model_name}" + (" --force" if force else "")


def _offline_refusal(what: str, command: str) -> ModelFetchError:
    """Explain that no download can run while a Hugging Face offline switch is set."""
    from ..storage import offline_mode_variables

    variables = offline_mode_variables()
    unset = " ".join(f"-u {name}" for name in variables)
    return ModelFetchError(
        f"{what} Offline mode is on ({', '.join(variables)}), so no download can run. "
        f"With network access, run exactly: `env {unset} {command}`; or copy a prepared "
        "cache from a connected machine (docs/OFFLINE_USAGE.md, Option A)."
    )


def _fetch_canonical_model(model_name: str, force: bool) -> None:
    """Make the canonical cache usable without ever deleting a working cache first."""
    from ..storage import (
        CanonicalModelDownloadError,
        _canonical_fastembed_cache_error,
        _first_line,
        canonical_fastembed_cache_root,
        discard_failed_canonical_fastembed_download,
        discard_set_aside_canonical_fastembed_cache,
        offline_mode_variables,
        quarantine_unowned_canonical_fastembed_cache,
        remove_empty_canonical_fastembed_cache_root,
        restore_orphaned_canonical_fastembed_cache,
        restore_set_aside_canonical_fastembed_cache,
        set_aside_owned_canonical_fastembed_cache,
    )

    root = canonical_fastembed_cache_root()
    # An interrupted --force run may have left the working cache set aside; putting it
    # back is a local rename, so it also runs offline.
    restored, kept = restore_orphaned_canonical_fastembed_cache()
    if restored is not None:
        _say(f"  Restored the cache an interrupted fetch-model set aside: {restored} -> {root}")
    for orphan in kept:
        _say(f"  Kept a set-aside cache that does not validate: {orphan}")
    command = _fetch_command(model_name)
    present = root.exists() or root.is_symlink()
    problem = _canonical_fastembed_cache_error(root) if present else None
    owned = present and problem is None
    if owned and not force:
        try:
            _load_model(model_name, local_files_only=True)
        except Exception as exc:
            problem = f"it failed to load: {_first_line(exc.__cause__ or exc)}"
        else:
            _say(f"  Model '{model_name}' is already available locally.")
            return

    if offline_mode_variables():
        if owned and problem is None:
            what = (
                "Refusing to replace the cached embedding model: its replacement must be "
                f"downloaded first. The cache at {root} is unchanged."
            )
            raise _offline_refusal(what, _fetch_command(model_name, force=True))
        if not present or remove_empty_canonical_fastembed_cache_root():
            what = f"The embedding model is not cached at {root}."
        else:
            what = (
                f"The cached embedding model at {root} is not usable ({problem}); "
                "it was left unchanged."
            )
        raise _offline_refusal(what, command)

    set_aside: Path | None = None
    preserved: Path | None = None
    if owned:
        # Replace a working (--force) or unloadable cache only after its replacement
        # validates; until then it waits in a hidden sibling and is restored on failure.
        if problem is None:
            _say(f"  Replacing cached model after the new download validates: {root}")
        else:
            _say(f"  Cached model is not usable ({problem}); replacing it.")
        set_aside = set_aside_owned_canonical_fastembed_cache()
    elif present:
        preserved = quarantine_unowned_canonical_fastembed_cache()
        if preserved is not None:
            _say(f"  Preserved partial cache at: {preserved}")

    _say(f"  Downloading model '{model_name}' …")
    _say("  Waiting for model download; no input is needed.")
    try:
        _load_model(model_name, local_files_only=False)
    except BaseException as exc:
        # BaseException too: Ctrl-C during a stalled download must also put the
        # set-aside cache back before the interrupt propagates. What the failed
        # download left behind was made by this run, so it is deleted, not preserved.
        notes = []
        try:
            if set_aside is not None:
                restore_set_aside_canonical_fastembed_cache(set_aside)
                notes.append(f"The previous cache was restored at {root}.")
                if force:
                    command = _fetch_command(model_name, force=True)
            else:
                discard_failed_canonical_fastembed_download()
        except (OSError, RuntimeError) as cleanup_exc:
            kept = (
                f"The previous cache is kept at {set_aside}; move it back with exactly: "
                f"`mv {shlex.quote(str(set_aside))} {shlex.quote(str(root))}`."
                if set_aside is not None
                else f"Move {root} aside manually, then retry: `{command}`."
            )
            raise ModelFetchError(
                f"Model download did not complete ({_first_line(exc)}), and cleaning up "
                f"failed ({_first_line(cleanup_exc)}). {kept}"
            ) from exc
        if preserved is not None:
            notes.append(f"Preserved cache: {preserved}.")
        if not isinstance(exc, Exception):
            for note in notes:
                print(f"  {note}", file=sys.stderr, flush=True)
            raise
        if isinstance(exc, CanonicalModelDownloadError) and not exc.retryable:
            raise ModelFetchError(
                f"Model download failed: {exc.reason}. "
                + "".join(f"{note} " for note in notes)
                + "Copy a prepared cache from a machine that has one "
                "(docs/OFFLINE_USAGE.md, Option A), or upgrade to a mempalace-code release "
                "that pins an available revision."
            ) from exc
        reason = (
            exc.reason
            if isinstance(exc, CanonicalModelDownloadError)
            else f"did not complete ({_first_line(exc)}); check network access to Hugging Face"
        )
        raise ModelFetchError(
            f"Model download failed: {reason}. "
            + "".join(f"{note} " for note in notes)
            + f"Retry exactly: `{command}`"
        ) from exc

    if set_aside is not None and not discard_set_aside_canonical_fastembed_cache(set_aside):
        _say(f"  Previous cache kept at: {set_aside}")


def _fetch_custom_model(model_name: str, force: bool) -> None:
    from ..storage import offline_mode_variables, preflight_embed_model

    # Report a missing [custom-models] extra before any progress output.
    preflight_embed_model(model_name)
    model_dir = _model_cache_dir(model_name)
    if force and model_dir is not None and (model_dir.exists() or model_dir.is_symlink()):
        raise ModelFetchError(
            f"Refusing to delete a custom-model cache automatically: {model_dir}. "
            "Move it aside manually, then retry without --force."
        )
    if not force:
        try:
            _load_model(model_name, local_files_only=True)
        except Exception:
            if _is_existing_model_path(model_name):
                raise
        else:
            _say(f"  Model '{model_name}' is already available locally.")
            return
    if offline_mode_variables():
        raise _offline_refusal(
            f"The embedding model '{model_name}' is not cached.", _fetch_command(model_name)
        )
    _say(f"  Downloading model '{model_name}' …")
    _say("  Waiting for model download; no input is needed.")
    _load_model(model_name, local_files_only=False)


def _cache_footprint(model_dir: Path) -> tuple[int, int]:
    """Return (bytes, bytes stored outside *model_dir*), counting each stored file once.

    Snapshot entries are links into a blob store; with recent huggingface_hub versions
    that store can be shared and live outside the model directory.
    """
    inside_root = Path(os.path.realpath(model_dir))
    seen: set[tuple[int, int]] = set()
    total = outside = 0
    for entry in model_dir.rglob("*"):
        try:
            target = Path(os.path.realpath(entry)) if entry.is_symlink() else entry
            info = target.stat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) in seen:
            continue
        seen.add((info.st_dev, info.st_ino))
        total += info.st_size
        if not target.is_relative_to(inside_root):
            outside += info.st_size
    return total, outside


def fetch_model(model_name: str, force: bool = False) -> None:
    """Ensure *model_name* is available for offline embedding.

    Shared by ``cmd_fetch_model`` and ``cmd_init``. With *force* the canonical cache is
    downloaded again; the working copy is set aside and deleted only after the new copy
    validates, and it is restored when the download fails. While ``HF_HUB_OFFLINE`` or
    ``TRANSFORMERS_OFFLINE`` is set, no cache is moved or removed.
    """
    from ..storage import is_canonical_embed_model

    sys.stdout.flush()
    if is_canonical_embed_model(model_name):
        _fetch_canonical_model(model_name, force)
    else:
        _fetch_custom_model(model_name, force)

    model_dir = _model_cache_dir(model_name)
    if model_dir and model_dir.exists():
        size_bytes, outside_bytes = _cache_footprint(model_dir)
        _say(f"  Cached at: {model_dir}")
        _say(f"  Size on disk: {size_bytes / (1024 * 1024):.1f} MB")
        if outside_bytes:
            _say(
                f"  Includes {outside_bytes / (1024 * 1024):.1f} MB in the shared Hugging Face "
                f"blob store; to move this model, copy all of {model_dir.parent}."
            )
    elif _is_existing_model_path(model_name):
        _say(f"  Local model path: {Path(model_name).expanduser()}")
    else:
        _say("  Model loaded successfully.")
        _say(f"  Cache path could not be reported (expected: {model_dir}).")
        _say("  No action needed unless offline search or mining fails later.")


def cmd_fetch_model(args):
    from ..storage import DEFAULT_EMBED_MODEL

    model_name = args.model or DEFAULT_EMBED_MODEL
    try:
        fetch_model(model_name, force=args.force)
        _say("  Done — embedding model is ready for offline use.")
    except Exception as exc:
        sys.stdout.flush()
        print(f"  Error preparing model: {exc}", file=sys.stderr)
        sys.exit(1)
