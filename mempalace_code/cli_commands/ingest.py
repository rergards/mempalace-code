"""Ingest command handlers: init, onboarding, mine, mine-all, split, status."""

import os
import sys
from pathlib import Path

from ..config import MempalaceConfig
from .common import parse_include_ignored


def cmd_init(args):
    import json

    from ..room_detector_local import detect_rooms_local

    config = MempalaceConfig()

    # Validate directory before any side effects — must precede entity scanning
    project_path = Path(args.dir).expanduser().resolve()
    if not project_path.is_dir():
        print(f"  Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    detect_entities_enabled = getattr(args, "detect_entities", False) or config.entity_detection

    if detect_entities_enabled:
        from ..entity_detector import confirm_entities, detect_entities, scan_for_detection

        print(f"\n  Scanning for entities in: {args.dir}")
        files = scan_for_detection(args.dir)
        if files:
            print(f"  Reading {len(files)} files...")
            detected = detect_entities(files)
            total = len(detected["people"]) + len(detected["projects"]) + len(detected["uncertain"])
            if total > 0:
                confirmed = confirm_entities(detected, yes=getattr(args, "yes", False))
                if confirmed["people"] or confirmed["projects"]:
                    entities_path = project_path / "entities.json"
                    with open(entities_path, "w") as f:
                        json.dump(confirmed, f, indent=2)
                    print(f"  Entities saved: {entities_path}")
            else:
                print("  No entities detected — proceeding with directory-based rooms.")

    detect_rooms_local(
        project_dir=args.dir,
        yes=getattr(args, "yes", False),
        interactive=getattr(args, "interactive", False),
    )
    config.init()

    if not getattr(args, "skip_model_download", False):
        from ..storage import DEFAULT_EMBED_MODEL
        from .model import fetch_model

        print("\n  Downloading embedding model (~80 MB)…")
        try:
            fetch_model(DEFAULT_EMBED_MODEL)
        except Exception as exc:
            print(f"  Warning: model download failed: {exc}", file=sys.stderr)
            print(
                "  Run 'mempalace-code fetch-model' manually when network is available.",
                file=sys.stderr,
            )


def cmd_onboarding(args):
    """Guided onboarding: seeds people, projects, and wing taxonomy interactively."""
    from ..onboarding import run_onboarding

    run_onboarding(directory=args.dir)


def _resolve_spellcheck(args, config: MempalaceConfig) -> bool:
    """Resolve spellcheck precedence: CLI flag > config/env > ingest-mode default."""
    flag_value = getattr(args, "spellcheck", None)
    if flag_value is not None:
        return flag_value

    config_value = config.spellcheck_enabled
    if config_value is not None:
        return config_value

    return args.mode == "convos"


def cmd_mine(args):
    config = MempalaceConfig()
    palace_path = os.path.expanduser(args.palace) if args.palace else config.palace_path
    spellcheck = _resolve_spellcheck(args, config)
    include_ignored = parse_include_ignored(args.include_ignored)

    watch = getattr(args, "watch", False)

    if watch:
        # Validate incompatible flag combinations
        if args.dry_run:
            print("  Error: --watch is incompatible with --dry-run.", file=sys.stderr)
            sys.exit(2)
        if args.full:
            print(
                "  Error: --watch is incompatible with --full (watch always uses incremental).",
                file=sys.stderr,
            )
            sys.exit(2)
        if args.limit:
            print(
                "  Error: --watch is incompatible with --limit "
                "(watch must process all files for correct stale-file cleanup).",
                file=sys.stderr,
            )
            sys.exit(2)
        if args.mode == "convos":
            print("  Error: --watch is not supported with --mode convos.", file=sys.stderr)
            sys.exit(2)

        try:
            from ..watcher import watch_and_mine
        except ImportError as exc:
            print(f"  Error importing watcher: {exc}", file=sys.stderr)
            sys.exit(1)

        from ..knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
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
            extract_mode=args.extract,
            spellcheck=spellcheck,
            extract_categories=(
                ["decision", "preference", "milestone", "problem", "emotional"]
                if args.include_emotional
                else None
            ),
        )
    else:
        from ..knowledge_graph import KnowledgeGraph
        from ..mining.orchestrator import mine

        kg = KnowledgeGraph()
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


def cmd_mine_all(args):
    """Mine all detected projects in a parent directory."""
    from ..knowledge_graph import KnowledgeGraph
    from ..mining.orchestrator import mine
    from ..mining.projects import detect_projects, resolve_wing_for_project

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    parent_dir = Path(args.dir).expanduser().resolve()
    if not parent_dir.is_dir():
        print(f"  Error: directory not found: {parent_dir}", file=sys.stderr)
        sys.exit(1)

    projects = detect_projects(str(parent_dir))

    if not projects:
        print(f"  No projects found in {parent_dir}")
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

    print(f"\n  Found {len(project_entries)} project(s) in {parent_dir}\n")

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
    errors: list = []

    new_only = args.new_only

    include_ignored = parse_include_ignored(args.include_ignored)

    for entry in project_entries:
        proj_path = entry["path"]
        proj_name = Path(proj_path).name
        wing_name = entry["wing"]

        if not entry["initialized"]:
            print(f"  SKIP  {proj_name}  (not initialized — run: mempalace-code init {proj_path})")
            skipped += 1
            continue

        if new_only and wing_name in existing_wings:
            print(
                f"  SKIP  {proj_name}  (wing '{wing_name}' already exists — skipped by --new-only)"
            )
            skipped += 1
            continue

        print(f"  MINE  {proj_name}  ->  wing: {wing_name}")
        try:
            kg = KnowledgeGraph()
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


def cmd_split(args):
    """Split concatenated transcript mega-files into per-session files."""
    import sys as _sys

    from ..split_mega_files import main as split_main

    # Rebuild argv for split_mega_files argparse
    argv = ["--source", args.dir]
    if args.output_dir:
        argv += ["--output-dir", args.output_dir]
    if args.dry_run:
        argv.append("--dry-run")
    if args.min_sessions != 2:
        argv += ["--min-sessions", str(args.min_sessions)]

    old_argv = _sys.argv
    _sys.argv = ["mempalace-code split"] + argv
    try:
        split_main()
    finally:
        _sys.argv = old_argv


def cmd_status(args):
    from ..mining.orchestrator import status

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    status(palace_path=palace_path)
