"""Ingest command handlers: init, onboarding, mine, mine-all, split, status."""

import os
import shlex
import sys
from pathlib import Path
from typing import NoReturn

from ..cli_invocation import cli_command
from ..config import MempalaceConfig
from .common import exit_writer_busy, palace_command, parse_include_ignored


def _stdin_is_interactive() -> bool:
    """True when prompts can be answered: stdin is an open terminal."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, OSError, ValueError):
        return False


def _print_init_next_steps(
    project_path: Path, palace: str | None, model_ready: bool, rooms_regenerated: bool
) -> None:
    """Print the commands that complete setup, starting with fetch-model when needed.

    After ``--force`` regenerated the rooms, ``mine --full`` re-files drawers of
    unchanged files into the new rooms (an incremental mine skips them).
    """
    steps = []
    if not model_ready:
        try:
            from ..storage import canonical_fastembed_cache_owned

            model_ready = canonical_fastembed_cache_owned()
        except Exception:
            model_ready = False
    if not model_ready:
        steps.append("mempalace-code fetch-model")
    palace_arg = f"--palace {shlex.quote(palace)} " if palace else ""
    full = " --full" if rooms_regenerated else ""
    steps.append(f"mempalace-code {palace_arg}mine {shlex.quote(str(project_path))}{full}")
    print("\n  Next steps:" if len(steps) > 1 else "\n  Next step:")
    for step in steps:
        print(f"    {step}")
    print()


def cmd_init(args):
    import json

    from ..room_detector_local import (
        detect_rooms_local,
        existing_project_config,
        restore_regular_destinations,
        snapshot_regular_destinations,
        validate_init_destinations,
        write_regular_destination,
    )

    # Validate directory before any side effects — must precede entity scanning
    project_path = Path(args.dir).expanduser().resolve()
    if not project_path.is_dir():
        problem = "not a directory" if project_path.exists() else "directory not found"
        print(f"  Error: {problem}: {args.dir}", file=sys.stderr)
        sys.exit(1)

    def exit_destination_error(exc: OSError) -> NoReturn:
        print(f"  Error: {exc}", file=sys.stderr)
        print(
            f"  Next: fix the destination, then rerun: mempalace-code init {project_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    yes = getattr(args, "yes", False)
    force = getattr(args, "force", False)
    rerun = f"mempalace-code init {shlex.quote(str(project_path))}" + (" --force" if force else "")

    def exit_input_closed() -> NoReturn:
        print("\n  Init aborted: input closed before a choice was made.", file=sys.stderr)
        print("  No changes were saved.", file=sys.stderr)
        print(f"  Next: accept the detected values without prompts: {rerun} --yes", file=sys.stderr)
        sys.exit(1)

    interactive = getattr(args, "interactive", False) and not yes
    will_write_rooms = force or existing_project_config(project_path) is None
    if interactive and will_write_rooms and not _stdin_is_interactive():
        print(
            "  Error: --interactive needs a terminal to answer prompts, but stdin is not a TTY. "
            "No changes were saved.",
            file=sys.stderr,
        )
        print(f"  Next: accept the detected rooms without prompts: {rerun}", file=sys.stderr)
        sys.exit(2)

    config = MempalaceConfig()
    detect_entities_enabled = getattr(args, "detect_entities", False) or config.entity_detection
    try:
        destinations = validate_init_destinations(project_path, detect_entities_enabled)
        snapshots = snapshot_regular_destinations(
            [project_path / "mempalace.yaml", *destinations.values()]
        )
    except OSError as exc:
        exit_destination_error(exc)

    entities_content: str | None = None
    if detect_entities_enabled:
        from ..entity_detector import confirm_entities, detect_entities, scan_for_detection

        print(f"\n  Scanning for entities in: {args.dir}")
        files = scan_for_detection(args.dir)
        if files:
            print(f"  Reading {len(files)} files...")
            detected = detect_entities(files)
            total = len(detected["people"]) + len(detected["projects"]) + len(detected["uncertain"])
            if total > 0:
                auto_accept = yes or not _stdin_is_interactive()
                if auto_accept and not yes:
                    print(
                        "  stdin is not a terminal: accepting detected people and projects "
                        "as with --yes (uncertain names are skipped)."
                    )
                try:
                    confirmed = confirm_entities(detected, yes=auto_accept)
                except EOFError:
                    exit_input_closed()
                if confirmed["people"] or confirmed["projects"]:
                    entities_content = json.dumps(confirmed, indent=2)
            else:
                print("  No entities detected — proceeding with directory-based rooms.")

    try:
        rooms_result = detect_rooms_local(
            project_dir=args.dir,
            yes=yes,
            interactive=interactive,
            force=force,
        )
        if entities_content is not None:
            entities_path = destinations["entities.json"]
            if rooms_result == "kept" and entities_path.exists():
                print(f"  Kept existing {entities_path} (rerun with --force to replace it).")
            else:
                write_regular_destination(entities_path, entities_content)
                print(f"  Entities saved: {entities_path}")
    except EOFError:
        try:
            restore_regular_destinations(snapshots)
        except OSError:
            pass
        exit_input_closed()
    except OSError as exc:
        try:
            restore_regular_destinations(snapshots)
        except OSError as rollback_exc:
            print(f"  Error: init rollback failed: {rollback_exc}", file=sys.stderr)
            print(
                f"  Next: inspect {project_path}, restore its prior files, then rerun init.",
                file=sys.stderr,
            )
            sys.exit(1)
        exit_destination_error(exc)

    model_ready = False
    if not getattr(args, "skip_model_download", False):
        from ..storage import DEFAULT_EMBED_MODEL
        from .model import fetch_model

        print("\n  Caching/verifying embedding model (~80 MB)…")
        try:
            fetch_model(DEFAULT_EMBED_MODEL)
            model_ready = True
        except Exception as exc:
            # The error names the exact recovery; the next steps below list fetch-model.
            print(f"  Warning: model cache/verify failed: {exc}", file=sys.stderr)

    _print_init_next_steps(
        project_path,
        getattr(args, "palace", None),
        model_ready,
        rooms_regenerated=rooms_result == "regenerated",
    )


def cmd_onboarding(args):
    """Guided onboarding: seeds people, projects, and wing taxonomy interactively."""
    import sys

    from ..onboarding import run_onboarding

    result = run_onboarding(directory=args.dir)
    if result is None:
        sys.exit(1)


def _resolve_spellcheck(args, config: MempalaceConfig) -> bool:
    """Resolve spellcheck precedence: CLI flag > config/env > off.

    Mining keeps drawer text verbatim, so the resolved value never rewrites what is
    stored; an explicit request prints a notice instead of silently doing nothing.
    """
    flag_value = getattr(args, "spellcheck", None)
    enabled = flag_value if flag_value is not None else config.spellcheck_enabled
    if enabled:
        print(
            "  Note: spellcheck no longer rewrites mined text; drawers are stored verbatim. "
            "--spellcheck and spellcheck_enabled are accepted for compatibility only.",
            file=sys.stderr,
        )
    return bool(enabled)


def _exit_invalid_mine_argument(exc: Exception) -> NoReturn:
    """Report a refused --wing/--agent value (exit 2); the message names the fix."""
    print(f"  Error: {exc}.", file=sys.stderr)
    sys.exit(2)


def cmd_mine(args):
    from ..errors import InvalidArgumentError
    from ..operation_lock import OperationLockedError

    try:
        _cmd_mine(args)
    except OperationLockedError as exc:
        exit_writer_busy(exc)
    except InvalidArgumentError as exc:
        _exit_invalid_mine_argument(exc)


def _cmd_mine(args):
    from ..mining.projects import validate_mine_arguments

    # A blank or unsafe --wing and a blank --agent exit 2 before the palace is touched.
    if args.wing is not None:
        from ..errors import InvalidArgumentError
        from ..taxonomy_filters import clean_write_name

        try:
            clean_write_name(args.wing, "--wing")
        except InvalidArgumentError as exc:
            print(f"  Error: {exc}.", file=sys.stderr)
            print(
                "  Next: pass --wing a name without '/', '\\' or control characters, or omit "
                "--wing to use the wing from mempalace.yaml.",
                file=sys.stderr,
            )
            sys.exit(2)
    validate_mine_arguments(args.wing, args.agent)
    config = MempalaceConfig()
    palace_path = os.path.expanduser(args.palace) if args.palace else config.palace_path
    spellcheck = _resolve_spellcheck(args, config)
    include_ignored = parse_include_ignored(args.include_ignored)

    watch = getattr(args, "watch", False)

    if watch:
        # Validate incompatible flag combinations
        if args.dry_run:
            print("  Error: --watch is incompatible with --dry-run.", file=sys.stderr)
            print(
                "  Next: run the dry run without --watch, then start watch separately.",
                file=sys.stderr,
            )
            sys.exit(2)
        if args.full:
            print(
                "  Error: --watch is incompatible with --full (watch always uses incremental).",
                file=sys.stderr,
            )
            print(
                "  Next: run --full once without --watch, then start watch separately.",
                file=sys.stderr,
            )
            sys.exit(2)
        if args.limit:
            print(
                "  Error: --watch is incompatible with --limit "
                "(watch must process all files for correct stale-file cleanup).",
                file=sys.stderr,
            )
            print("  Next: remove --limit before starting watch.", file=sys.stderr)
            sys.exit(2)
        if args.mode == "convos":
            print("  Error: --watch is not supported with --mode convos.", file=sys.stderr)
            print(
                "  Next: mine conversation exports once without --watch, or watch a project-source directory.",
                file=sys.stderr,
            )
            sys.exit(2)

        try:
            from ..watcher import watch_and_mine
        except ImportError as exc:
            print(f"  Error importing watcher: {exc}", file=sys.stderr)
            sys.exit(1)

        from ..knowledge_graph import LazyKnowledgeGraph

        kg = LazyKnowledgeGraph(palace_path)
        watch_and_mine(
            project_dir=args.dir,
            palace_path=palace_path,
            wing_override=args.wing,
            agent=args.agent,
            respect_gitignore=not args.no_gitignore,
            include_ignored=include_ignored,
            kg=kg,
        )
        return

    if args.mode == "convos":
        from ..convo_miner import mine_convos

        mine_convos(
            convo_dir=args.dir,
            palace_path=palace_path,
            wing=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            incremental=not args.full,
            extract_mode=args.extract,
            spellcheck=spellcheck,
            extract_categories=(
                ["decision", "preference", "milestone", "problem", "emotional"]
                if args.include_emotional
                else None
            ),
        )
    else:
        from ..knowledge_graph import LazyKnowledgeGraph
        from ..mining.orchestrator import mine

        kg = LazyKnowledgeGraph(palace_path)
        mine(
            project_dir=args.dir,
            palace_path=palace_path,
            wing_override=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            respect_gitignore=not args.no_gitignore,
            include_ignored=include_ignored,
            incremental=not args.full,
            kg=kg,
            spellcheck=spellcheck,
        )


def _report_unmarked_subdirs(parent_dir: Path, projects: list) -> None:
    """Name visible subdirectories that mine-all skips because they are not projects."""
    project_paths = {Path(proj["path"]) for proj in projects}
    try:
        children = sorted(parent_dir.iterdir(), key=lambda child: child.name)
    except OSError:
        return
    skipped = [
        child.name
        for child in children
        if not child.name.startswith(".")
        and child.is_dir()
        and not child.is_symlink()
        and child not in project_paths
    ]
    if not skipped:
        return
    shown = ", ".join(skipped[:10]) + (
        f", and {len(skipped) - 10} more" if len(skipped) > 10 else ""
    )
    print(
        f"  Skipped {len(skipped)} subdirector{'y' if len(skipped) == 1 else 'ies'} "
        f"without project markers or mempalace.yaml: {shown}"
    )
    print(f"  To include one, run: mempalace-code init {shlex.quote(str(parent_dir / skipped[0]))}")


def cmd_mine_all(args):
    """Mine all detected projects in a parent directory."""
    from ..errors import InvalidArgumentError
    from ..knowledge_graph import LazyKnowledgeGraph
    from ..mining.orchestrator import mine
    from ..mining.projects import (
        detect_projects,
        resolve_wing_for_project,
        validate_mine_arguments,
    )
    from ..operation_lock import OperationLockedError

    try:
        validate_mine_arguments(None, args.agent)
    except InvalidArgumentError as exc:
        _exit_invalid_mine_argument(exc)
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if getattr(args, "force", False):
        print(
            "  Note: --force is deprecated and has no effect; mine-all always syncs every "
            "initialized project incrementally.",
            file=sys.stderr,
        )

    parent_dir = Path(args.dir).expanduser().resolve()
    if not parent_dir.is_dir():
        problem = "not a directory" if parent_dir.exists() else "directory not found"
        print(f"  Error: {problem}: {parent_dir}", file=sys.stderr)
        sys.exit(1)

    projects = detect_projects(str(parent_dir))

    if not projects:
        print(f"  No projects found in {parent_dir}")
        _report_unmarked_subdirs(parent_dir, projects)
        print(
            "  Next: run mempalace-code init <project-dir>, or point mine-all at a "
            "parent directory with initialized project subdirectories."
        )
        return

    # Resolve wing names; config parse errors are fatal before any mining starts.
    project_entries = []
    config_error_count = 0
    for proj in projects:
        try:
            wing_name = resolve_wing_for_project(proj["path"])
            project_entries.append({**proj, "wing": wing_name})
        except ValueError as exc:
            config_error_count += 1
            print(f"  ERROR  {Path(proj['path']).name}: {exc}", file=sys.stderr)

    if config_error_count:
        print(
            f"  {config_error_count} project(s) had config parse errors — fix them and retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n  Found {len(project_entries)} project(s) in {parent_dir}")
    _report_unmarked_subdirs(parent_dir, projects)
    print()

    # Detect duplicate wings among projects that will actually be mined.
    # Uninitialized projects are skipped later, so a uninit/init wing collision is
    # not a corruption risk and must not block the batch.
    wing_to_paths: dict = {}
    for entry in project_entries:
        if entry["initialized"]:
            wing_to_paths.setdefault(entry["wing"], []).append(entry["path"])

    duplicate_wings = {w: paths for w, paths in wing_to_paths.items() if len(paths) > 1}
    if duplicate_wings:
        for w, paths in sorted(duplicate_wings.items()):
            path_list = ", ".join(str(p) for p in paths)
            print(
                f"  ERROR  duplicate wing '{w}': {path_list}\n"
                f"         Configure a unique 'wing:' in each project's mempalace.yaml.",
                file=sys.stderr,
            )
        sys.exit(1)

    if args.dry_run:
        # Dry-run: only show detected projects, never open the store
        for entry in project_entries:
            name = Path(entry["path"]).name
            status = "initialized" if entry["initialized"] else "not initialized"
            print(f"  [{status}]  {name}  ->  wing: {entry['wing']}")
        print("\n  Dry run — no mining performed.")
        return

    # Load existing wings from the store once (not per-project)
    try:
        from ..storage import open_store

        store = open_store(palace_path, create=True)
        existing_wings = set(store.count_by("wing").keys())
    except Exception as e:
        print(f"  Error opening palace at {palace_path}: {e}", file=sys.stderr)
        sys.exit(1)

    mined = 0
    skipped = 0
    uninitialized: list = []
    errors: list = []

    new_only = args.new_only

    include_ignored = parse_include_ignored(args.include_ignored)

    for entry in project_entries:
        proj_path = entry["path"]
        proj_name = Path(proj_path).name
        wing_name = entry["wing"]

        if not entry["initialized"]:
            print(f"  SKIP  {proj_name}  (not initialized — run: {cli_command('init', proj_path)})")
            skipped += 1
            uninitialized.append(proj_path)
            continue

        if new_only and wing_name in existing_wings:
            print(
                f"  SKIP  {proj_name}  (wing '{wing_name}' already exists — skipped by --new-only)"
            )
            skipped += 1
            continue

        print(f"  MINE  {proj_name}  ->  wing: {wing_name}")
        try:
            kg = LazyKnowledgeGraph(palace_path)
            mine(
                project_dir=proj_path,
                palace_path=palace_path,
                wing_override=wing_name,
                agent=args.agent,
                limit=0,
                dry_run=False,
                respect_gitignore=not args.no_gitignore,
                include_ignored=include_ignored,
                incremental=True,
                kg=kg,
            )
            existing_wings.add(wing_name)
            mined += 1
        except KeyboardInterrupt:
            print("\n  Interrupted.", file=sys.stderr)
            raise
        except OperationLockedError as exc:
            # Every later project would wait on the same writer: stop the batch.
            print(f"  Stopped after {mined} of {len(project_entries)} project(s).", file=sys.stderr)
            exit_writer_busy(exc)
        except BaseException as exc:
            errors.append((proj_name, str(exc)))
            print(f"  ERROR {proj_name}: {exc}", file=sys.stderr)

    # Print error details then summary
    print(f"\n  {'=' * 50}")
    print(
        f"  Summary: found {len(project_entries)}, mined {mined}, "
        f"skipped {skipped}, errors {len(errors)}"
    )
    if errors:
        print("  Errors:")
        for proj_name, msg in errors:
            print(f"    {proj_name}: {msg}")
    print(f"  {'=' * 50}\n")

    if errors:
        sys.exit(1)
    if uninitialized and len(uninitialized) == len(project_entries):
        print(
            f"  Error: nothing mined: no project under {parent_dir} is initialized.\n"
            f"  Next: run {cli_command('init', str(uninitialized[0]))} "
            "(and each other project above), then run "
            f"{palace_command(palace_path, 'mine-all', str(parent_dir))}",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_split(args):
    """Split concatenated transcript mega-files into per-session files."""
    from ..split_mega_files import main as split_main

    # Rebuild argv for split_mega_files argparse; a file path splits just that file.
    # A missing path with an extension is reported as a missing file.
    source = Path(args.dir).expanduser()
    as_file = source.is_file() or (not source.exists() and bool(source.suffix))
    argv = ["--file", str(source)] if as_file else ["--source", str(source)]
    if args.output_dir:
        argv += ["--output-dir", args.output_dir]
    if args.dry_run:
        argv.append("--dry-run")
    if args.min_sessions != 2:
        argv += ["--min-sessions", str(args.min_sessions)]

    old_argv = sys.argv
    sys.argv = ["mempalace-code split"] + argv
    try:
        split_main()
    finally:
        sys.argv = old_argv


def cmd_status(args):
    from ..mining.orchestrator import status

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    if not status(palace_path=palace_path, summary=getattr(args, "summary", False)):
        sys.exit(1)
