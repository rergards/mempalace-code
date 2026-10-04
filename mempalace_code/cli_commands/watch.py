"""Watch command handlers: watch, watch schedule, watch status."""

import os
import re
import shlex
import sys
from pathlib import Path

from ..config import MempalaceConfig


def cmd_watch(args):
    watch_command = getattr(args, "watch_command", None)
    if watch_command == "schedule":
        cmd_watch_schedule(args)
        return
    if watch_command == "status":
        cmd_watch_status(args)
        return

    # Default: run the watcher
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    try:
        from ..watcher import watch_all
    except ImportError as exc:
        print(f"  Error importing watcher: {exc}", file=sys.stderr)
        sys.exit(1)

    watch_all(
        parent_dir=args.dir,
        palace_path=palace_path,
        agent=args.agent,
        respect_gitignore=not args.no_gitignore,
        on_commit=not getattr(args, "on_save", False),
    )


def _schedule_palace(args) -> str | None:
    """Return the explicit --palace to pin in a daemon, or None to use the daemon's default."""
    return (
        os.path.abspath(os.path.expanduser(args.palace)) if getattr(args, "palace", None) else None
    )


def _warn_uncached_model() -> None:
    """Warn when the daemon's offline model load would fail on its first mine."""
    from ..storage import canonical_fastembed_cache_status
    from .alias import recovery_cli_command

    status = canonical_fastembed_cache_status()
    if not status["owned"]:
        print(
            f"  # Warning: the default embedding model is not cached at {status['root']}.\n"
            "  #   The daemon runs offline and never downloads it; before loading the job run:\n"
            f"  #     {shlex.quote(recovery_cli_command())} fetch-model",
            file=sys.stderr,
        )


def cmd_watch_schedule(args):
    from ..watcher import (
        format_watch_command,
        format_watch_flags,
        plan_watch_root,
        render_watch_schedule,
        watch_launchd_label,
    )
    from .alias import resolve_invoked_canonical_cli

    try:
        invoked_launcher = resolve_invoked_canonical_cli()
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)
    selected_launcher = str(invoked_launcher) if invoked_launcher is not None else None
    safe_launcher = shlex.quote(selected_launcher or "mempalace-code")
    watch_root = Path(args.dir).expanduser().resolve()
    palace = _schedule_palace(args)
    on_save = bool(getattr(args, "on_save", False))
    agent = getattr(args, "agent", "mempalace")
    respect_gitignore = not getattr(args, "no_gitignore", False)
    flags = format_watch_flags(on_save=on_save, agent=agent, respect_gitignore=respect_gitignore)
    label = watch_launchd_label(watch_root)
    plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
    safe_plist = shlex.quote(plist_path)
    render_command = format_watch_command(safe_launcher, palace, watch_root, flags, " schedule")

    if getattr(args, "install", False):
        print(
            "  owner action required: --install is not supported.\n"
            f"  Print the snippet with: {render_command}\n"
            f"  Save it with: {render_command} > {safe_plist} (macOS)\n"
            f"  then install it yourself with: launchctl load {safe_plist} (macOS)\n"
            "  or: crontab -e (Linux).",
            file=sys.stderr,
        )
        sys.exit(2)

    platform = sys.platform
    if platform.startswith("darwin"):
        platform = "darwin"
    elif platform.startswith("linux"):
        platform = "linux"
    else:
        print(
            f"  Error: watch scheduling is not supported on {sys.platform}.\n"
            "  'mempalace-code watch schedule' works on macOS (launchd) and Linux (cron) only.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        snippet = render_watch_schedule(
            args.dir,
            platform,
            mempalace_bin=selected_launcher,
            palace_path=palace,
            on_save=on_save,
            agent=agent,
            respect_gitignore=respect_gitignore,
        )
        plan = plan_watch_root(
            args.dir,
            on_commit=not on_save,
            cli=safe_launcher,
            palace_path=palace,
            flags=flags,
            suffix=" schedule",
        )
    except ValueError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(snippet, end="")
    for note in plan.notes:
        print(f"  # {note}", file=sys.stderr)
    _warn_uncached_model()
    if platform == "darwin":
        print(f"\n  # Re-render: {render_command}", file=sys.stderr)
        print(
            f"\n  # Job {label} watches only this root; other roots keep their own jobs.",
            file=sys.stderr,
        )
        print("  # To install:", file=sys.stderr)
        print(f"  #   {render_command} > {safe_plist}", file=sys.stderr)
        print(f"  #   launchctl load {safe_plist}", file=sys.stderr)
        print("  # To stop:", file=sys.stderr)
        print(f"  #   launchctl unload {safe_plist}", file=sys.stderr)
        for other_plist, other_root in _overlapping_watch_jobs(watch_root, palace, label):
            quoted = shlex.quote(str(other_plist))
            print(
                f"\n  # Warning: {other_plist} already watches {other_root} into the same "
                "palace.\n"
                "  #   Both jobs would re-mine the same projects; the second one refuses to "
                "start ('already watched') and launchd restarts it forever.\n"
                f"  #   Unload and remove that job first:  launchctl unload {quoted} && "
                f"rm {quoted}",
                file=sys.stderr,
            )
    else:
        print(
            f"\n  # Re-render: {render_command}\n"
            "  # To install: crontab -e  (paste the line above)",
            file=sys.stderr,
        )


_LEGACY_WATCH_LABEL = "com.mempalace.watch"


def _parse_launchctl_job(output: str) -> dict:
    """Read the top-level service state, counters, log path, and argv from ``launchctl print``."""
    job: dict = {"state": "unknown", "runs": None, "exit_code": None, "log": None, "argv": []}
    depth = 0
    in_arguments = False
    for line in output.splitlines():
        stripped = line.strip()
        if in_arguments:
            if stripped == "}":
                in_arguments = False
            else:
                job["argv"].append(stripped)
            continue
        if depth == 1:
            key, _, value = stripped.partition(" = ")
            value = value.strip()
            if key == "state":
                job["state"] = value
            elif key == "runs":
                job["runs"] = int(value) if value.isdigit() else None
            elif key == "last exit code":
                # Newer launchd appends a name ("78: EX_CONFIG") or prints "(never exited)".
                code = re.match(r"-?\d+", value)
                job["exit_code"] = int(code.group()) if code else None
            elif key == "stdout path":
                job["log"] = value
            elif key == "arguments" and value == "{":
                in_arguments = True
                continue
        depth += stripped.count("{") - stripped.count("}")
    return job


def _job_tokens(argv: list) -> list:
    """Return a job's command tokens, expanding a ``sh -c`` wrapper with shell quoting."""
    tokens = list(argv)
    if len(tokens) == 3 and Path(tokens[0]).name in {"sh", "bash"} and tokens[1] == "-c":
        try:
            tokens = shlex.split(tokens[2])
        except ValueError:
            return []
    return tokens


def _token_after(tokens: list, name: str) -> str | None:
    for index, token in enumerate(tokens[:-1]):
        if token == name:
            return tokens[index + 1]
    return None


def _watched_root_from_argv(argv: list) -> str | None:
    """Return the watch root from a job's arguments, honoring shell quoting."""
    return _token_after(_job_tokens(argv), "watch")


def _job_settings(tokens: list) -> dict | None:
    """Return the palace and watch options a job command carries, or None if unknown."""
    if "watch" not in tokens:
        return None
    from ..watcher import DEFAULT_WATCH_AGENT

    palace = _token_after(tokens, "--palace")
    return {
        "palace": os.path.abspath(os.path.expanduser(palace)) if palace else None,
        "on_save": "--on-save" in tokens,
        "agent": _token_after(tokens, "--agent") or DEFAULT_WATCH_AGENT,
        "respect_gitignore": "--no-gitignore" not in tokens,
    }


def _saved_job_settings(label: str) -> dict | None:
    """Return the settings of this root's saved (not necessarily loaded) plist, if any."""
    import plistlib

    plist = Path(os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist"))
    try:
        argv = plistlib.loads(plist.read_bytes()).get("ProgramArguments") or []
    except (OSError, ValueError, AttributeError, plistlib.InvalidFileException):
        return None
    return _job_settings(_job_tokens([str(arg) for arg in argv]))


def _invoked_launcher() -> str:
    """Return the shell-quoted launcher that re-renders a job, as ``schedule`` does."""
    from .alias import resolve_invoked_canonical_cli

    try:
        invoked = resolve_invoked_canonical_cli()
    except RuntimeError:
        invoked = None
    return shlex.quote(str(invoked) if invoked is not None else "mempalace-code")


def _overlapping_watch_jobs(watch_root: Path, palace: str | None, own_label: str) -> list:
    """Return (plist, root) for saved watch jobs whose root overlaps *watch_root*.

    Two watchers of one project into one palace refuse each other, so such a job would
    make the new one exit 'already watched' on every launchd restart.
    """
    import plistlib

    agents = Path(os.path.expanduser("~/Library/LaunchAgents"))
    try:
        candidates = sorted(agents.glob(f"{_LEGACY_WATCH_LABEL}*.plist"))
    except OSError:
        return []
    overlaps = []
    for plist in candidates:
        if plist.name == f"{own_label}.plist":
            continue
        try:
            argv = plistlib.loads(plist.read_bytes()).get("ProgramArguments") or []
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        tokens = _job_tokens([str(arg) for arg in argv])
        root = _token_after(tokens, "watch")
        if root is None:
            continue
        other_palace = _token_after(tokens, "--palace")
        if (os.path.abspath(os.path.expanduser(other_palace)) if other_palace else None) != palace:
            continue
        other = Path(root).expanduser().resolve()
        if other == watch_root or other in watch_root.parents or watch_root in other.parents:
            overlaps.append((plist, other))
    return overlaps


def _find_launchd_job(watch_root: Path) -> tuple:
    """Return (label, parsed job or None) for this root's LaunchAgent."""
    import subprocess

    from ..watcher import watch_launchd_label

    label = watch_launchd_label(watch_root)
    uid = os.getuid()
    for candidate in (label, _LEGACY_WATCH_LABEL):
        result = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{candidate}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            continue
        parsed = _parse_launchctl_job(result.stdout)
        root = _watched_root_from_argv(parsed["argv"])
        # A job rendered by an older release uses the fixed label; it is this root's
        # job only when its arguments name this root.
        if candidate == label or root == str(watch_root):
            parsed["root"] = root
            return candidate, parsed
    return label, None


def _print_launchd_state(
    watch_root: Path, palace: str | None, label: str, job, render: str = ""
) -> str | None:
    """Print this root's LaunchAgent state; return the next action it implies, if any.

    *render* is the ``schedule`` command that reproduces the job's palace and options.
    It is written to a temporary file first, so a refused render never truncates the
    saved plist.
    """
    from ..watcher import format_watch_command, watch_launchd_log_path

    if job is None:
        plist = shlex.quote(os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist"))
        tmp = shlex.quote(os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist.tmp"))
        print(f"  LaunchAgent: {label}  (not loaded)")
        render = render or format_watch_command(
            "mempalace-code", palace, watch_root, "", " schedule"
        )
        return (
            f"if {plist} already points at the intended root, run launchctl load {plist}; "
            f"otherwise run {render} > {tmp} && mv {tmp} {plist} first."
        )

    log = job["log"] or str(watch_launchd_log_path(label))
    print(f"  LaunchAgent: {label}  state = {job['state']}")
    if job["runs"] is not None:
        print(f"  LaunchAgent: runs = {job['runs']}")
    if job["exit_code"] is not None:
        print(f"  LaunchAgent: last exit code = {job['exit_code']}")
    if job["root"]:
        print(f"  Watched root: {job['root']}")
    print(f"  Log:      {log}")
    print(f"  Stop:     launchctl bootout gui/{os.getuid()}/{label}")
    if job["exit_code"] is not None and job["exit_code"] != 0:
        return f"inspect {log}, fix the last failure, then rerun this status command."
    if job["state"] not in ("running", "waiting"):
        return f"check launchctl state and {log}, then rerun this status command."
    return None


def cmd_watch_status(args):
    """Print disk-budget summary, watch-root validity, and launchd state for the watch daemon."""
    import subprocess

    from ..disk_budget import check_watch_budget, format_bytes
    from ..watcher import (
        DEFAULT_WATCH_AGENT,
        WatchRootError,
        format_watch_command,
        format_watch_flags,
        plan_watch_root,
    )

    cfg = MempalaceConfig()
    min_free, min_free_source = cfg.watch_disk_min_free_setting
    watch_root = Path(args.dir).expanduser().resolve()

    # LaunchAgent lookup (macOS only) comes first: the loaded job's mode decides
    # whether the root must be a git checkout.
    launchd_note = None
    label, job = None, None
    if sys.platform.startswith("darwin"):
        try:
            label, job = _find_launchd_job(watch_root)
        except FileNotFoundError:
            launchd_note = (
                "  LaunchAgent: launchctl not found",
                "run the watcher in the foreground: mempalace-code watch <dir>",
            )
        except subprocess.TimeoutExpired:
            launchd_note = (
                "  LaunchAgent: state unavailable (launchctl timed out)",
                "retry status; if it repeats, inspect launchctl and the job log.",
            )
        except Exception as exc:
            launchd_note = (
                f"  LaunchAgent: state unavailable ({exc})",
                "inspect launchctl and the job log, then rerun status.",
            )
    else:
        launchd_note = ("  LaunchAgent: not available (launchd is macOS-only)", None)

    # The job's own settings decide its palace, mode, and re-render command: the loaded
    # job's arguments, else this root's saved plist, else this invocation's options. A
    # loaded job whose arguments are unknown is not second-guessed.
    settings = None
    source = "arguments"
    if job is not None:
        settings = _job_settings(_job_tokens(job["argv"]))
        source = "loaded" if settings is not None else "unknown"
    elif label is not None:
        settings = _saved_job_settings(label)
        source = "saved" if settings is not None else source
    if settings is None:
        settings = {
            "palace": None,
            "on_save": bool(getattr(args, "on_save", False)),
            "agent": getattr(args, "agent", None) or DEFAULT_WATCH_AGENT,
            "respect_gitignore": not getattr(args, "no_gitignore", False),
        }
    palace = _schedule_palace(args) or settings["palace"]
    palace_path = palace or MempalaceConfig().palace_path
    try:
        status = check_watch_budget(palace_path, min_free)
    except Exception as exc:
        print(f"  Error checking disk budget: {exc}", file=sys.stderr)
        sys.exit(1)

    launcher = _invoked_launcher()
    option_flags = format_watch_flags(
        agent=settings["agent"], respect_gitignore=settings["respect_gitignore"]
    )
    mode_flag = " --on-save" if settings["on_save"] else ""
    render = format_watch_command(
        launcher, palace, watch_root, mode_flag + option_flags, " schedule"
    )
    job_on_commit = source != "unknown" and not settings["on_save"]
    root_error = None
    try:
        plan_watch_root(
            args.dir,
            on_commit=job_on_commit,
            cli=launcher,
            palace_path=palace,
            flags=option_flags,
            suffix=" schedule",
        )
    except WatchRootError as exc:
        root_error = str(exc)
        if job_on_commit and source == "loaded":
            root_error = (
                f"the loaded job runs in commit mode: {root_error.strip()}\n"
                "  Replace the job's plist with that output and reload it."
            )
        elif job_on_commit and source == "saved":
            root_error = (
                f"the saved job runs in commit mode: {root_error.strip()}\n"
                "  Render that command to a temporary file, move it over the job's plist, "
                "and load it."
            )

    print(f"  Palace:   {palace_path}")
    print(f"  Free:     {format_bytes(status.free_bytes)}")
    print(f"  Required: {format_bytes(status.min_free_bytes)} (from {min_free_source})")
    print(f"  Size:     {format_bytes(status.palace_bytes)} (palace)")
    print(f"  Backups:  {format_bytes(status.backups_bytes)}")
    print(f"  Root:     {watch_root}" + ("" if root_error is None else "  (invalid)"))
    if root_error is not None:
        print(f"  Runnable: no  (watch root: {root_error.splitlines()[0]})")
    elif status.allowed:
        print("  Runnable: yes")
    else:
        print("  Runnable: no  (disk budget exceeded)")
    next_action = None
    if root_error is not None:
        next_action = f"fix the watch root — {root_error.strip()}"
    elif not status.allowed:
        next_action = f"free disk space or lower {min_free_source}, then rerun this status command."

    if launchd_note is not None:
        line, action = launchd_note
        print(line)
        if next_action is None:
            next_action = action
    elif label is not None:
        launchd_action = _print_launchd_state(watch_root, palace, label, job, render)
        if next_action is None:
            next_action = launchd_action

    if next_action:
        print(f"  Next: {next_action}")
