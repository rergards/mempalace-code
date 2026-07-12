"""Explicit MemPalace update command handlers."""

from __future__ import annotations

import json
import sys

from ..updater import UpdateManager, UpdateResult


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _render(result: UpdateResult, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return
    print(f"  Update {result.stage}: {result.message}")
    if result.log_path:
        print(f"  Log: {result.log_path}")
    data = result.data
    if result.stage == "status":
        installation = _mapping(data.get("installation"))
        provenance = _mapping(data.get("provenance"))
        watcher = _mapping(data.get("watcher"))
        scheduler = _mapping(data.get("scheduler"))
        extras = installation.get("extras")
        extras_text = ", ".join(str(extra) for extra in extras) if isinstance(extras, list) else ""
        print(f"  Supported install: {installation.get('supported', False)}")
        print(f"  Installer: {installation.get('kind', 'unknown')}")
        print(f"  Retained extras: {extras_text or 'none'}")
        print(f"  Current version: {provenance.get('current_version', 'unknown')}")
        print(f"  Eligible target: {provenance.get('target_version') or 'none'}")
        print(f"  Provenance: {provenance.get('project_url', 'unavailable')}")
        print(
            f"  Watcher ({watcher.get('unit', 'unknown')}): "
            f"{watcher.get('detail', 'unknown')}"
        )
        print(f"  Scheduler enabled: {scheduler.get('enabled', False)}")
        print(f"  Next run: {data.get('next_run') or 'not scheduled'}")
        if data.get("reason"):
            print(f"  Decision: {data['reason']}")


def _require_yes(args) -> bool:
    if getattr(args, "yes", False):
        return True
    print(
        "  Refused: this action changes package or systemd-user state. Re-run with --yes.",
        file=sys.stderr,
    )
    return False


def cmd_update(args) -> None:
    """Handle the opt-in ``mempalace-code update`` command group."""
    if not getattr(args, "update_command", None):
        args._update_parser.print_help()
        raise SystemExit(2)

    manager = UpdateManager(palace_path=args.palace)
    command = args.update_command
    if command == "status":
        result = manager.status()
    elif command == "check":
        result = manager.check()
    elif command == "apply":
        if not _require_yes(args):
            raise SystemExit(2)
        result = manager.apply(scheduled=getattr(args, "scheduled", False))
    elif command == "scheduler":
        scheduler_command = getattr(args, "scheduler_command", None)
        if scheduler_command == "status":
            status = manager.scheduler_status()
            result = UpdateResult(
                True, "scheduler-status", "scheduler status inspected", 0, data=status
            )
        elif scheduler_command == "render":
            units = manager.render_scheduler_units()
            if getattr(args, "json", False):
                print(json.dumps(units, indent=2, sort_keys=True))
            else:
                for name, content in units.items():
                    print(f"# {name}\n{content}", end="")
            return
        elif scheduler_command == "install":
            if not _require_yes(args):
                raise SystemExit(2)
            result = manager.install_scheduler()
        elif scheduler_command == "remove":
            if not _require_yes(args):
                raise SystemExit(2)
            result = manager.remove_scheduler()
        else:
            args._scheduler_parser.print_help()
            raise SystemExit(2)
    else:  # pragma: no cover - argparse constrains this branch.
        raise SystemExit(2)

    _render(result, getattr(args, "json", False))
    if not result.ok:
        raise SystemExit(result.exit_code)
