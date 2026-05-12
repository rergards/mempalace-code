"""version-check command handler: --enable, --disable, --status, --check-now."""

import os
import sys

from ..version import __version__
from ..version_check import (
    PYPI_URL,
    fetch_latest_version,
    load_state,
    resolve_config,
    run_check_now,
    save_state,
)


def cmd_version_check(args):
    """Handle 'mempalace-code version-check' subcommand."""
    config_dir = None  # always uses ~/.mempalace for the real CLI

    if getattr(args, "enable", False):
        state = load_state(config_dir)
        state.enabled = True
        save_state(state, config_dir)
        effective = resolve_config(config_dir)
        if effective.source == "env":
            env_raw = os.environ.get("MEMPALACE_VERSION_CHECK", "")
            print("  State saved: enabled.")
            print(
                f"  Note: MEMPALACE_VERSION_CHECK={env_raw!r} (env var) is currently overriding "
                "the persisted state."
            )
        else:
            print("  Version checks enabled.")
            print("  Run 'mempalace-code version-check --status' to view settings.")
        return

    if getattr(args, "disable", False):
        state = load_state(config_dir)
        state.enabled = False
        save_state(state, config_dir)
        effective = resolve_config(config_dir)
        if effective.source == "env":
            env_raw = os.environ.get("MEMPALACE_VERSION_CHECK", "")
            print("  State saved: disabled.")
            print(
                f"  Note: MEMPALACE_VERSION_CHECK={env_raw!r} (env var) is currently overriding "
                "the persisted state."
            )
        else:
            print("  Version checks disabled.")
            print("  Run 'mempalace-code version-check --enable' to opt in.")
        return

    if getattr(args, "check_now", False):
        run_check_now(
            current_version=__version__,
            fetch_fn=lambda: fetch_latest_version(),
        )
        return

    # Default: --status
    _cmd_version_check_status(config_dir)


def _cmd_version_check_status(config_dir) -> None:
    """Print the current version-check status without contacting PyPI."""
    import datetime  # noqa: PLC0415 (deferred import to avoid startup cost)

    config = resolve_config(config_dir)
    state = load_state(config_dir)

    if config.enabled is True:
        enabled_display = "enabled"
    elif config.enabled is False:
        enabled_display = "disabled"
    else:
        enabled_display = "not set (will prompt on next interactive command)"

    print(f"  Version checks:  {enabled_display}")
    print(f"  Source:          {config.source}")
    print(f"  Interval:        {config.interval_hours} hours")
    print(f"  Current version: {__version__}")
    print(f"  PyPI URL:        {PYPI_URL}")

    if state.last_check_ts is not None:
        ts = datetime.datetime.fromtimestamp(state.last_check_ts, tz=datetime.UTC)
        ts_local = ts.astimezone()
        print(f"  Last checked:    {ts_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    else:
        print("  Last checked:    never")

    if config.source == "env":
        env_raw = os.environ.get("MEMPALACE_VERSION_CHECK", "")
        print(f"\n  Note: MEMPALACE_VERSION_CHECK={env_raw!r} overrides persisted state.")
    elif config.enabled is None:
        print(
            "\n  Tip: run 'mempalace-code version-check --enable' to opt in, "
            "or 'mempalace-code version-check --disable' to permanently skip prompting.",
            file=sys.stderr,
        )
