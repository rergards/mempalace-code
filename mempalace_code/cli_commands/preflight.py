import json
import os
import sys


def _configured_palace_paths(args) -> list[str]:
    """Palace directories a mirror must not overwrite: --palace and the configured one."""
    from ..config import MempalaceConfig

    paths = [MempalaceConfig().palace_path]
    if getattr(args, "palace", None):
        paths.append(args.palace)
    return [os.path.expanduser(path) for path in paths]


def cmd_preflight_mirror(args):
    from ..mirror_preflight import classify_mirror_command

    command = args.inspect
    use_json = getattr(args, "json", False)

    result = classify_mirror_command(command, _configured_palace_paths(args))

    if result.parse_error:
        if use_json:
            print(json.dumps({"ok": False, "parse_error": result.parse_error}))
        else:
            print(f"ERROR: {result.parse_error}", file=sys.stderr)
        sys.exit(2)

    if use_json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "dangerous": result.dangerous,
                    "pattern_id": result.pattern_id,
                    "missing_excludes": result.missing_excludes,
                    "unverified_excludes": result.unverified_excludes,
                    "warnings": result.warnings,
                }
            )
        )
    else:
        if result.ok:
            print("OK")
        else:
            # UNVERIFIED: the verdict depends on rules or shell state preflight cannot read.
            print(f"{'BLOCKED' if result.dangerous else 'UNVERIFIED'} [{result.pattern_id}]")
            for family in result.missing_excludes:
                print(f"  missing exclude: {family}")
            for family in result.unverified_excludes:
                print(f"  unverified exclude: {family}")
        for w in result.warnings:
            print(f"  warning: {w}")

    if not result.ok:
        sys.exit(1)


def cmd_preflight(args):
    if args.preflight_command == "mirror":
        cmd_preflight_mirror(args)
    else:
        args._preflight_parser.print_help()
        sys.exit(2)
