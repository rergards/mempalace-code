import json
import sys


def cmd_preflight_mirror(args):
    from ..mirror_preflight import classify_mirror_command

    command = args.inspect
    use_json = getattr(args, "json", False)

    result = classify_mirror_command(command)

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
                    "warnings": result.warnings,
                }
            )
        )
    else:
        if result.ok:
            print("OK")
            for w in result.warnings:
                print(f"  warning: {w}")
        else:
            print(f"BLOCKED [{result.pattern_id}]")
            for family in result.missing_excludes:
                print(f"  missing exclude: {family}")
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
