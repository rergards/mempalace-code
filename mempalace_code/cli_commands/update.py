"""Explicit MemPalace update command handlers."""

from __future__ import annotations

import json
import shlex
import sys

from .. import updater
from ..updater import UpdateManager, UpdateResult, service_manager_name
from .alias import recovery_cli_command


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
    if data.get("recovery_command"):
        print(f"  Recovery: {data['recovery_command']}")
    if result.stage in ("status", "check"):
        installation = _mapping(data.get("installation"))
        provenance = _mapping(data.get("provenance"))
        watcher = _mapping(data.get("watcher"))
        scheduler = _mapping(data.get("scheduler"))
        extras = installation.get("extras")
        extras_text = ", ".join(str(extra) for extra in extras) if isinstance(extras, list) else ""
        print(f"  Supported install: {installation.get('supported', False)}")
        print(f"  Installer: {installation.get('kind', 'unknown')}")
        if not installation.get("supported", False) and installation.get("reason"):
            print(f"  Installer refusal: {installation['reason']}")
        if data.get("manual_upgrade_command"):
            print(f"  Upgrade this pip install with: {data['manual_upgrade_command']}")
        elif data.get("manual_upgrade_note"):
            print(f"  Pip upgrade: {data['manual_upgrade_note']}")
        print(f"  Retained extras: {extras_text or 'none'}")
        print(f"  Current version: {provenance.get('current_version', 'unknown')}")
        print(f"  Eligible target: {provenance.get('target_version') or 'none'}")
        print(f"  Provenance: {provenance.get('project_url', 'unavailable')}")
        watcher_state = "active" if watcher.get("active", False) else "inactive"
        print(
            f"  Watcher ({watcher.get('unit', 'unknown')}, {watcher_state}): "
            f"{watcher.get('detail', 'unknown')}"
        )
        print(f"  Scheduler enabled: {scheduler.get('enabled', False)}")
        print(f"  Next run: {data.get('next_run') or 'not scheduled'}")
        if data.get("reason"):
            print(f"  Decision: {data['reason']}")
    if result.stage == "scheduler-status":
        print(f"  Scheduler supported: {data.get('supported', False)}")
        print(f"  Scheduler enabled: {data.get('enabled', False)}")
        if data.get("detail"):
            print(f"  Detail: {data['detail']}")
        print(f"  Next run: {data.get('next_run') or 'not scheduled'}")


def _cli_command() -> str:
    """Name the launcher that was invoked, or the bare name when PATH already finds it."""
    return recovery_cli_command()


def _require_yes(args, action: tuple[str, ...]) -> bool:
    if getattr(args, "yes", False):
        return True

    command = [_cli_command()]
    if args.palace:
        command.extend(["--palace", str(args.palace)])
    command.extend(action)
    command.append("--yes")
    if action == ("update", "apply") and getattr(args, "scheduled", False):
        command.append("--scheduled")
    if getattr(args, "json", False):
        command.append("--json")
    result = UpdateResult(
        False,
        "confirmation",
        f"refused: package or {service_manager_name()} mutation requires explicit confirmation",
        2,
        data={"recovery_command": shlex.join(command)},
    )
    _render(result, getattr(args, "json", False))
    return False


def _scheduler_platform_refusal() -> UpdateResult | None:
    """Return the scheduler's platform refusal on hosts without systemd-user support."""
    # Static platform facts: read them from the updater itself, not an injected manager.
    data = updater.UpdateManager._unsupported_platform_data()
    if data is None:
        return None
    return UpdateResult(
        False,
        "unsupported-platform",
        updater.UpdateManager._unsupported_platform_message(),
        2,
        data=data,
    )


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
        if not _require_yes(args, ("update", "apply")):
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
            warning = manager.scheduler_render_warning()
            if warning:
                print(f"  Warning: {warning}", file=sys.stderr)
            if getattr(args, "json", False):
                print(json.dumps(units, indent=2, sort_keys=True))
            else:
                for name, content in units.items():
                    print(f"# {name}\n{content}", end="")
            return
        elif scheduler_command in ("install", "remove"):
            # Offer `--yes` only where the mutation can run; elsewhere report the boundary.
            result = _scheduler_platform_refusal()
            if result is None:
                if not _require_yes(args, ("update", "scheduler", scheduler_command)):
                    raise SystemExit(2)
                if scheduler_command == "install":
                    result = manager.install_scheduler()
                else:
                    result = manager.remove_scheduler()
        else:
            args._scheduler_parser.print_help()
            raise SystemExit(2)
    else:  # pragma: no cover - argparse constrains this branch.
        raise SystemExit(2)

    _render(result, getattr(args, "json", False))
    if not result.ok:
        raise SystemExit(result.exit_code)
