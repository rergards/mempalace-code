#!/usr/bin/env python3
"""
split_mega_files.py — Split concatenated transcript files into per-session files
=================================================================================

Scans the top level of a directory for .txt files (or splits one file of any
extension) that contain multiple Claude Code terminal sessions, identified by
their "Claude Code v<version>" banner line. Splits each into individual files
named with: date, time, people detected, and subject from first prompt.

Distinguishes true session starts from mid-session context restores
(which show "Ctrl+E to show X previous messages"). A mention of "Claude Code v2"
inside a prompt or answer is not a banner and never starts a session.

Every line of the source lands in exactly one output file: text before the first
banner goes with the first session, and short sessions are written too.
Output files are written to --output-dir (default: same dir as source).
The original is then renamed with the .mega_backup extension next to the source
(kept, not deleted, and not mined); an existing backup is never replaced, the next
one is <stem>.1.mega_backup. A split that fails midway removes the outputs it wrote.

Usage:
    python3 split_mega_files.py                          # scan ~/Desktop/transcripts
    python3 split_mega_files.py --source ~/Desktop/transcripts  # explicit source
    python3 split_mega_files.py --file ~/transcripts/sub/mega.md  # one file
    python3 split_mega_files.py --dry-run                # show what would happen
    python3 split_mega_files.py --min-sessions 2         # only files with 2+ sessions

By: Ben, 2026-03-30
"""

import argparse
import errno
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import NoReturn

from .source_io import (
    RegularSourceError,
    is_regular_source_path,
    read_regular_text,
    regular_source_diagnostic,
    stat_regular_source,
)

HOME = Path.home()

_HAS_O_NONBLOCK = bool(getattr(os, "O_NONBLOCK", 0))
_HAS_O_NOFOLLOW = bool(getattr(os, "O_NOFOLLOW", 0))
_O_BINARY = getattr(os, "O_BINARY", 0)
_OUTPUT_MODE = 0o644
_OUTPUT_TARGET_REASON = "not a regular output target"
_OUTPUT_REPLACE_REASON = "output target already exists; retry with a new empty --output-dir"
_OUTPUT_DIR_REASON = "not a safe output directory; retry with a new empty --output-dir"
LUMI_DIR = Path(os.environ.get("MEMPALACE_SOURCE_DIR", str(HOME / "Desktop/transcripts")))

# People explicitly configured for name detection in content.
_KNOWN_NAMES_PATH = HOME / ".mempalace" / "known_names.json"
_KNOWN_NAMES_CACHE = None


def _load_known_names_config(force_reload: bool = False):
    """Load and cache the optional known-names config file."""
    global _KNOWN_NAMES_CACHE

    if force_reload:
        _KNOWN_NAMES_CACHE = None

    if _KNOWN_NAMES_CACHE is not None:
        return _KNOWN_NAMES_CACHE

    if _KNOWN_NAMES_PATH.exists():
        try:
            _KNOWN_NAMES_CACHE = json.loads(read_regular_text(_KNOWN_NAMES_PATH))
            return _KNOWN_NAMES_CACHE
        except (json.JSONDecodeError, OSError):
            pass

    _KNOWN_NAMES_CACHE = None
    return None


def _load_known_people() -> list:
    """Load explicitly configured known names."""
    data = _load_known_names_config()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("names", [])
    return []


KNOWN_PEOPLE = _load_known_people()


def _load_username_map() -> dict:
    """Load username-to-name mapping from config file."""
    data = _load_known_names_config()
    if isinstance(data, dict):
        return data.get("username_map", {})
    return {}


def is_true_session_start(lines, idx):
    """
    True session start: 'Claude Code v' header NOT followed by 'Ctrl+E'/'previous messages'
    within the next 6 lines (those are context restores, not new sessions).
    """
    nearby = "".join(lines[idx : idx + 6])
    return "Ctrl+E" not in nearby and "previous messages" not in nearby


# A banner line holds "Claude Code v<version>" with only box-drawing or logo glyphs
# around it, e.g. "╭─── Claude Code v2.0.14 ───╮" or " ▐▛███▜▌   Claude Code v2.0.37".
_SESSION_BANNER_RE = re.compile(r"^[\s\u2500-\u259f✻*]*Claude Code v\d[\w.+-]*[\s\u2500-\u259f]*$")


def find_session_boundaries(lines):
    """Return list of line indices where true new sessions begin."""
    boundaries = []
    for i, line in enumerate(lines):
        if _SESSION_BANNER_RE.match(line) and is_true_session_start(lines, i):
            boundaries.append(i)
    return boundaries


def _read_session_lines(path: Path) -> list[str]:
    return read_regular_text(path, errors="replace").splitlines(keepends=True)


def discover_text_sources(src_dir: Path) -> list[Path]:
    """Return regular .txt sources for split scanning."""
    files = []
    for path in sorted(src_dir.glob("*.txt")):
        if not is_regular_source_path(path):
            print(regular_source_diagnostic(path), file=sys.stderr)
            continue
        files.append(path)
    return files


def extract_timestamp(lines):
    """
    Find the first timestamp line: ⏺ H:MM AM/PM Weekday, Month DD, YYYY
    Returns (datetime_str, iso_str) or (None, None).
    """
    ts_pattern = re.compile(r"⏺\s+(\d{1,2}:\d{2}\s+[AP]M)\s+\w+,\s+(\w+)\s+(\d{1,2}),\s+(\d{4})")
    months = {
        "January": "01",
        "February": "02",
        "March": "03",
        "April": "04",
        "May": "05",
        "June": "06",
        "July": "07",
        "August": "08",
        "September": "09",
        "October": "10",
        "November": "11",
        "December": "12",
    }
    for line in lines[:50]:
        m = ts_pattern.search(line)
        if m:
            time_str, month, day, year = m.groups()
            mon = months.get(month, "00")
            day_z = day.zfill(2)
            time_safe = time_str.replace(":", "").replace(" ", "")
            iso = f"{year}-{mon}-{day_z}"
            human = f"{year}-{mon}-{day_z}_{time_safe}"
            return human, iso
    return None, None


def extract_people(lines):
    """
    Detect people mentioned as speakers or by name in first 100 lines.
    Returns sorted list of detected names.
    """
    found = set()
    text = "".join(lines[:100])

    # Speaker tags: "Alice:", "Ben:", etc.
    for person in KNOWN_PEOPLE:
        if re.search(rf"(?<!\w){re.escape(person)}(?!\w)", text, re.IGNORECASE):
            found.add(person)

    # Working directory username hint — map to known people if configured
    dir_match = re.search(r"/Users/(\w+)/", text)
    if dir_match:
        username = dir_match.group(1)
        # User can map usernames to names in ~/.mempalace/known_names.json
        # under a "username_map" key, e.g. {"username_map": {"jdoe": "John"}}
        username_map = _load_username_map()
        if username in username_map:
            found.add(username_map[username])

    return sorted(found)


def extract_subject(lines):
    """
    Find the first meaningful user prompt (> line that isn't a shell command).
    Returns cleaned, filename-safe subject string.
    """
    skip_patterns = re.compile(
        r"^(\.\/|cd |ls |python|bash|git |cat |source |export |claude|./activate)"
    )
    for line in lines:
        if line.startswith("> "):
            prompt = line[2:].strip()
            if prompt and not skip_patterns.match(prompt) and len(prompt) > 5:
                # Clean for filename
                subject = re.sub(r"[^\w\s-]", "", prompt)
                subject = re.sub(r"\s+", "-", subject.strip())
                return subject[:60]
    return "session"


def _reject_non_regular_output_entry(out_path: Path, *, dir_fd: int | None = None) -> None:
    """Refuse a synthesized output name that already exists as a non-regular entry.

    ``os.lstat`` is deliberate: ``Path.exists`` follows links and answers False for a
    dangling symlink, so an existence probe would let the write create the link target
    outside the requested output directory.
    """
    try:
        if dir_fd is None:
            st = os.lstat(out_path)
        else:
            st = os.stat(out_path.name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise RegularSourceError(out_path, _OUTPUT_TARGET_REASON)


def _open_regular_output_descriptor(out_path: Path, *, dir_fd: int | None = None) -> int:
    """Open a validated regular-file descriptor for a generated split chunk.

    O_NOFOLLOW refuses a symlink at the synthesized name and O_NONBLOCK keeps a
    reader-less FIFO from blocking the open forever; ``fstat`` re-validates the
    descriptor that will actually be written.
    """
    _reject_non_regular_output_entry(out_path, dir_fd=dir_fd)

    # Every synthesized chunk is new. Exclusive creation prevents a repeated or
    # raced apply from truncating an operator-owned regular file.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY
    if _HAS_O_NOFOLLOW:
        flags |= os.O_NOFOLLOW
    if _HAS_O_NONBLOCK:
        flags |= os.O_NONBLOCK

    try:
        if dir_fd is None:
            fd = os.open(out_path, flags, _OUTPUT_MODE)
        else:
            fd = os.open(out_path.name, flags, _OUTPUT_MODE, dir_fd=dir_fd)
    except OSError as exc:
        if _output_entry_is_unsafe(out_path, dir_fd=dir_fd):
            raise RegularSourceError(out_path, _OUTPUT_TARGET_REASON) from exc
        if exc.errno == errno.EEXIST:
            raise RegularSourceError(out_path, _OUTPUT_REPLACE_REASON) from exc
        raise

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise RegularSourceError(out_path, _OUTPUT_TARGET_REASON)
        os.ftruncate(fd, 0)
        _clear_nonblocking(fd)
    except Exception:
        os.close(fd)
        raise

    return fd


def _output_entry_is_unsafe(out_path: Path, *, dir_fd: int | None = None) -> bool:
    """Report whether a failed open was caused by a hostile entry rather than plain I/O."""
    try:
        if dir_fd is None:
            st = os.lstat(out_path)
        else:
            st = os.stat(out_path.name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return False
    return not stat.S_ISREG(st.st_mode) or st.st_nlink != 1


def _clear_nonblocking(fd: int) -> None:
    """Drop O_NONBLOCK once the descriptor is known to be a regular file."""
    if not _HAS_O_NONBLOCK:
        return

    import fcntl

    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)


def _write_regular_output(out_path: Path, text: str, *, dir_fd: int | None = None) -> None:
    """Write a generated chunk through a descriptor validated as a regular file.

    The file was created exclusively by this call, so a failed write removes it.
    """
    payload = memoryview(text.encode("utf-8"))
    fd = _open_regular_output_descriptor(out_path, dir_fd=dir_fd)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written == 0:
                raise OSError("regular output write made no progress")
            offset += written
    except BaseException:
        os.close(fd)
        _remove_outputs([out_path], dir_fd=dir_fd)
        raise
    os.close(fd)


def _remove_outputs(paths: list, *, dir_fd: int | None = None) -> None:
    """Remove split outputs this run created; paths that could not be removed stay listed."""
    for out_path in list(paths):
        try:
            if dir_fd is None:
                os.unlink(out_path)
            else:
                os.unlink(out_path.name, dir_fd=dir_fd)
        except FileNotFoundError:
            pass
        except OSError:
            continue
        paths.remove(out_path)


def _acquire_explicit_output_directory(out_dir: Path):
    """Return an anchored directory descriptor when the platform can provide one.

    The fallback validates or creates only the requested leaf, then relies on the
    universal O_EXCL file writer. It does not close parent-path TOCTOU races.
    """
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", set())
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    can_anchor = (
        _HAS_O_NOFOLLOW
        and directory_flag
        and os.open in supports_dir_fd
        and os.mkdir in supports_dir_fd
        and os.stat in supports_dir_fd
        and os.stat in supports_follow_symlinks
    )
    if not can_anchor:
        try:
            output_stat = os.lstat(out_dir)
        except FileNotFoundError:
            try:
                out_dir.mkdir()
            except FileExistsError:
                output_stat = os.lstat(out_dir)
            else:
                output_stat = os.lstat(out_dir)
        if not stat.S_ISDIR(output_stat.st_mode):
            raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON)
        return None, None

    explicit_dir = Path(os.path.abspath(out_dir))
    output_dir_fd = None
    parent_fd = None
    try:
        try:
            expected_parent = os.stat(explicit_dir.parent, follow_symlinks=False)
        except OSError as exc:
            raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON) from exc
        if not stat.S_ISDIR(expected_parent.st_mode):
            raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON)
        parent_fd = os.open(
            explicit_dir.parent,
            os.O_RDONLY | directory_flag | os.O_NOFOLLOW,
        )
        opened_parent = os.fstat(parent_fd)
        if not stat.S_ISDIR(opened_parent.st_mode) or (
            opened_parent.st_dev,
            opened_parent.st_ino,
        ) != (expected_parent.st_dev, expected_parent.st_ino):
            raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON)

        try:
            expected_output = os.stat(
                explicit_dir.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            os.mkdir(explicit_dir.name, dir_fd=parent_fd)
            expected_output = os.stat(
                explicit_dir.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        if not stat.S_ISDIR(expected_output.st_mode):
            raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON)

        output_dir_fd = os.open(
            explicit_dir.name,
            os.O_RDONLY | directory_flag | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        output_dir_stat = os.fstat(output_dir_fd)
        current_output = os.stat(
            explicit_dir.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        expected_identity = (expected_output.st_dev, expected_output.st_ino)
        if (
            not stat.S_ISDIR(output_dir_stat.st_mode)
            or (output_dir_stat.st_dev, output_dir_stat.st_ino) != expected_identity
            or (current_output.st_dev, current_output.st_ino) != expected_identity
        ):
            raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON)
        return output_dir_fd, output_dir_stat
    except Exception:
        if output_dir_fd is not None:
            os.close(output_dir_fd)
        raise
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


def split_file(filepath, output_dir, dry_run=False, *, _progress=None):
    """
    Split a single mega-file into per-session files.

    Every line is written: text before the first session banner is kept with the
    first session, so the outputs concatenate back to the source text.
    Returns list of output paths written (or would be written if dry_run).
    """
    path = Path(filepath)
    lines = _read_session_lines(path)

    boundaries = find_session_boundaries(lines)
    if len(boundaries) < 2:
        return []  # Not a mega-file

    # Add sentinel at end
    boundaries.append(len(lines))

    out_dir = Path(output_dir) if output_dir else path.parent
    written = _progress if _progress is not None else []
    output_dir_fd = None
    output_dir_stat = None
    output_dir_acquired = False

    try:
        for i, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            session = lines[start:end]
            # Text before the first banner (an export note, a stray line) stays with
            # the first session instead of being dropped.
            chunk = lines[:end] if i == 0 else session
            preamble = f", {start} before the first session" if i == 0 and start else ""

            ts_human, ts_iso = extract_timestamp(session)
            people = extract_people(session)
            subject = extract_subject(session)

            # Build filename: SOURCESTEM__DATE_TIME_People_subject.txt
            # Source stem prefix prevents collisions when multiple mega-files
            # produce sessions with the same timestamp/people/subject.
            ts_part = ts_human or f"part{i + 1:02d}"
            people_part = "-".join(people[:3]) if people else "unknown"
            src_stem = re.sub(r"[^\w-]", "_", path.stem)[:40]
            name = f"{src_stem}__{ts_part}_{people_part}_{subject}.txt"
            # Sanitize
            name = re.sub(r"[^\w\.\-]", "_", name)
            name = re.sub(r"_+", "_", name)

            out_path = out_dir / name

            if dry_run:
                print(f"  [{i + 1}/{len(boundaries) - 1}] {name}  ({len(chunk)} lines{preamble})")
            else:
                if output_dir and not output_dir_acquired:
                    output_dir_fd, output_dir_stat = _acquire_explicit_output_directory(out_dir)
                    output_dir_acquired = True

                if output_dir_fd is not None:
                    assert output_dir_stat is not None
                    try:
                        current_output = os.stat(out_dir, follow_symlinks=False)
                    except OSError as exc:
                        raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON) from exc
                    if (current_output.st_dev, current_output.st_ino) != (
                        output_dir_stat.st_dev,
                        output_dir_stat.st_ino,
                    ):
                        raise RegularSourceError(out_dir, _OUTPUT_DIR_REASON)

                _write_regular_output(out_path, "".join(chunk), dir_fd=output_dir_fd)
                print(f"  ✓ {name}  ({len(chunk)} lines{preamble})")

            written.append(out_path)
    except BaseException:
        # A split that stops midway removes the outputs it already wrote, so the next
        # mine does not file them next to the original that stays in place.
        if not dry_run:
            _remove_outputs(written, dir_fd=output_dir_fd)
        raise
    finally:
        if output_dir_fd is not None:
            os.close(output_dir_fd)

    return written


def _backup_candidates(source: Path):
    """``<stem>.mega_backup``, then ``<stem>.<n>.mega_backup`` for n = 1, 2, ..."""
    yield source.with_suffix(".mega_backup")
    n = 1
    while True:
        yield source.with_name(f"{source.stem}.{n}.mega_backup")
        n += 1


def _move_to_unused_backup(source: Path) -> Path:
    """Rename *source* to the first unused backup name; an existing backup is never replaced.

    A hard link claims the name atomically (it fails when the name exists, even if a
    concurrent split took it after the check); where hard links are unsupported, the
    rename happens only after an existence check.
    """
    for backup in _backup_candidates(source):
        if backup.exists() or backup.is_symlink():
            continue
        try:
            os.link(source, backup)
        except FileExistsError:
            continue
        except OSError:
            source.rename(backup)
            return backup
        source.unlink()
        return backup
    raise AssertionError("unreachable")  # pragma: no cover


def _exit_missing_source(path: Path, kind: str) -> NoReturn:
    """Fail loudly: a mistyped source is an error, not an empty split."""
    parent = path.absolute().parent
    while not parent.is_dir() and parent != parent.parent:
        parent = parent.parent
    print(f"Error: source {kind} not found: {path}", file=sys.stderr)
    print(
        f"  Next: ls {shlex.quote(str(parent))}  (then rerun mempalace-code split "
        "with the correct path from that listing)",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Split concatenated Claude Code transcript mega-files into per-session files. "
            "Each split original is renamed to <name>.mega_backup next to the source "
            "(kept, not mined; an existing backup is never replaced: <name>.1.mega_backup). "
            "A split that fails midway removes the files it wrote."
        )
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help=(
            "Source directory; its top-level .txt files are scanned "
            "(default: MEMPALACE_SOURCE_DIR or ~/Desktop/transcripts)"
        ),
    )
    parser.add_argument(
        "--output-dir", type=str, default=None, help="Output directory (default: same as source)"
    )
    parser.add_argument(
        "--min-sessions",
        type=int,
        default=2,
        help="Only split files with at least N sessions (default: 2)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would happen without writing files"
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Split a single specific file (any extension) instead of scanning dir",
    )
    args = parser.parse_args()

    src_dir = Path(args.source).expanduser() if args.source else LUMI_DIR
    output_dir = args.output_dir or None  # None = same dir as file

    if args.file:
        source = Path(args.file).expanduser()
        if not source.is_file():
            _exit_missing_source(source, "file")
        files = [source]
    else:
        if not src_dir.is_dir():
            _exit_missing_source(src_dir, "directory")
        files = discover_text_sources(src_dir)

    mega_files = []
    unreadable = 0
    for f in files:
        try:
            lines = _read_session_lines(f)
        except OSError as exc:
            print(f"{f}: {exc}", file=sys.stderr)
            unreadable += 1
            continue
        boundaries = find_session_boundaries(lines)
        if len(boundaries) >= args.min_sessions:
            mega_files.append((f, len(boundaries)))

    if not mega_files:
        if unreadable:
            print(
                f"Error: {unreadable} source file(s) could not be read (see above); nothing split.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if args.file:
            print(f"No mega-file: {files[0]} has fewer than {args.min_sessions} sessions.")
        else:
            print(
                f"No mega-files found in {src_dir} (min {args.min_sessions} sessions; "
                f"scanned {len(files)} top-level .txt files)."
            )
            print(
                "  Subdirectories and other extensions are not scanned; "
                "pass a file path to split one file."
            )
        return

    print(f"\n{'=' * 60}")
    print(f"  Mega-file splitter — {'DRY RUN' if args.dry_run else 'SPLITTING'}")
    print(f"{'=' * 60}")
    print(f"  Source:      {Path(args.file).expanduser() if args.file else src_dir}")
    print(f"  Output:      {output_dir or 'same dir as source'}")
    print(f"  Mega-files:  {len(mega_files)}")
    print(f"{'─' * 60}\n")

    total_written = 0
    failed_files = 0
    for f, n_sessions in mega_files:
        try:
            size_kb = stat_regular_source(f).st_size // 1024
        except OSError as exc:
            print(f"{f}: {exc}", file=sys.stderr)
            failed_files += 1
            continue
        print(f"  {f.name}  ({n_sessions} sessions, {size_kb}KB)")
        progress = []
        try:
            written = split_file(f, output_dir, dry_run=args.dry_run, _progress=progress)
        except OSError as exc:
            # A refused output target must not cost the operator the source mega-file.
            # split_file removed the outputs it wrote; any it could not remove are named.
            failed_files += 1
            print(f"{f}: {exc}", file=sys.stderr)
            for leftover in progress:
                print(f"  ! could not remove partial output {leftover}", file=sys.stderr)
            if progress:
                print(
                    f"  Next: delete the {len(progress)} partial output file(s) above before "
                    "mining, or they are filed next to the original",
                    file=sys.stderr,
                )
            print(f"  → Split aborted; no split files kept; original left in place as {f.name}\n")
            continue
        total_written += len(written)

        if not args.dry_run and written:
            backup = _move_to_unused_backup(f)
            print(f"  → Original renamed to {backup.name} (kept, not mined)\n")
        else:
            print()

    print(f"{'─' * 60}")
    if args.dry_run:
        print(f"  DRY RUN — would create {total_written} files from {len(mega_files)} mega-files")
    elif failed_files:
        print(
            f"  Done with errors — created {total_written} files; "
            f"failed {failed_files} of {len(mega_files)} mega-files"
        )
    else:
        print(f"  Done — created {total_written} files from {len(mega_files)} mega-files")
    if unreadable:
        print(f"  {unreadable} source file(s) could not be read (see errors above)")
    print()
    if failed_files or unreadable:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
