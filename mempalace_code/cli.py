#!/usr/bin/env python3
"""
MemPalace — Give your AI a memory. No API key required.

Two ways to ingest:
  Projects:      mempalace-code mine ~/projects/my_app          (code, docs, notes)
  Conversations: mempalace-code mine ~/chats/ --mode convos     (Claude, ChatGPT, Slack)

Same palace. Same search. Different ingest strategies.

Commands:
    mempalace-code init <dir>                  Detect rooms from folder structure
    mempalace-code split <dir>                 Split concatenated mega-files into per-session files
    mempalace-code mine <dir>                  Mine project files (default)
    mempalace-code mine <dir> --mode convos    Mine conversation exports
    mempalace-code mine-all <parent-dir>       Mine all projects in a directory
    mempalace-code watch <parent-dir>          Watch all projects for changes, re-mine automatically
    mempalace-code watch <parent-dir> schedule Print launchd/cron snippet for watch daemon
    mempalace-code search "query"              Find anything, exact words
    mempalace-code wake-up                     Show L0 + L1 wake-up context
    mempalace-code wake-up --wing my_app       Wake-up for a specific project
    mempalace-code status                      Show what's been filed
    mempalace-code health [--json]             Probe palace for fragment corruption
    mempalace-code cleanup [--older-than-days N] [--unsafe-now] [--json]  Reclaim stale Lance versions
    mempalace-code repair [--rollback] [--dry-run]  Repair palace (rollback or full rebuild)
    mempalace-code backup [--out FILE]         Snapshot palace to a .tar.gz archive
    mempalace-code restore FILE [--force]      Restore palace from a .tar.gz archive
    mempalace-code diary write --agent <name> --entry "<text>"  Write a diary entry

Examples:
    mempalace-code init ~/projects/my_app
    mempalace-code mine ~/projects/my_app
    mempalace-code mine ~/chats/claude-sessions --mode convos
    mempalace-code search "why did we switch to GraphQL"
    mempalace-code search "pricing discussion" --wing my_app --room costs
    mempalace-code diary write --agent claude-code --entry "Finished feature X" --topic dev
"""

import argparse
import sys

from .cli_commands.alias import cmd_install_alias, install_legacy_alias, main_alias
from .cli_commands.backup_restore import cmd_backup, cmd_restore
from .cli_commands.diary import cmd_diary
from .cli_commands.export_import import cmd_export, cmd_import
from .cli_commands.ingest import (
    cmd_init,
    cmd_mine,
    cmd_mine_all,
    cmd_onboarding,
    cmd_split,
    cmd_status,
)
from .cli_commands.maintenance import cmd_cleanup, cmd_health, cmd_migrate_storage, cmd_repair
from .cli_commands.model import cmd_fetch_model, fetch_model
from .cli_commands.query import cmd_compress, cmd_read, cmd_search, cmd_wakeup
from .cli_commands.version_check import cmd_version_check
from .cli_commands.watch import cmd_watch

# Re-export for backward compatibility (tests and downstream direct imports).
__all__ = [
    "main",
    "main_alias",
    "install_legacy_alias",
    "fetch_model",
]


def main():
    from ._stdio import configure_windows_stdio

    configure_windows_stdio()

    parser = argparse.ArgumentParser(
        description="MemPalace — Give your AI a memory. No API key required.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Where the palace lives (default: from ~/.mempalace/config.json or ~/.mempalace/palace)",
    )

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Detect rooms from your folder structure")
    p_init.add_argument("dir", help="Project directory to set up")
    p_init.add_argument(
        "--yes",
        action="store_true",
        help="Backward-compatible flag: accepted but no longer required (init is non-interactive by default)",
    )
    p_init.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt to review, edit, or add rooms before saving mempalace.yaml",
    )
    p_init.add_argument(
        "--detect-entities",
        action="store_true",
        help="Opt in to heuristic people/project detection during init",
    )
    p_init.add_argument(
        "--skip-model-download",
        action="store_true",
        dest="skip_model_download",
        help="Skip automatic embedding model download (run 'fetch-model' later)",
    )

    # onboarding
    p_onboarding = sub.add_parser(
        "onboarding",
        help="Guided onboarding: set up people, projects, and wing taxonomy interactively",
    )
    p_onboarding.add_argument("dir", help="Project directory to configure")

    # mine
    p_mine = sub.add_parser("mine", help="Mine files into the palace")
    p_mine.add_argument("dir", help="Directory to mine")
    p_mine.add_argument(
        "--mode",
        choices=["projects", "convos"],
        default="projects",
        help="Ingest mode: 'projects' for code/docs (default), 'convos' for chat exports",
    )
    p_mine.add_argument("--wing", default=None, help="Wing name (default: directory name)")
    p_mine.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Don't respect .gitignore files when scanning project files",
    )
    p_mine.add_argument(
        "--include-ignored",
        action="append",
        default=[],
        help="Always scan these project-relative paths even if ignored; repeat or pass comma-separated paths",
    )
    p_mine.add_argument(
        "--agent",
        default="mempalace",
        help="Your name — recorded on every drawer (default: mempalace)",
    )
    p_mine.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    p_mine.add_argument(
        "--dry-run", action="store_true", help="Show what would be filed without filing"
    )
    p_mine.add_argument(
        "--full",
        action="store_true",
        help="Force full rebuild — re-mine all files even if content is unchanged",
    )
    p_mine.add_argument(
        "--extract",
        choices=["exchange", "general"],
        default="exchange",
        help=(
            "Extraction strategy for convos mode: 'exchange' (default) or 'general' "
            "(decision, preference, milestone, problem by default)"
        ),
    )
    p_mine.add_argument(
        "--include-emotional",
        action="store_true",
        help="Opt in to emotional memories for --mode convos --extract general",
    )
    spellcheck_group = p_mine.add_mutually_exclusive_group()
    spellcheck_group.add_argument(
        "--spellcheck",
        dest="spellcheck",
        action="store_true",
        default=None,
        help="Enable spellcheck for conversation normalization",
    )
    spellcheck_group.add_argument(
        "--no-spellcheck",
        dest="spellcheck",
        action="store_false",
        help="Disable spellcheck for conversation normalization",
    )
    p_mine.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Watch for file changes and re-mine automatically (requires mempalace-code[watch]). "
            "Incompatible with --dry-run, --full, --limit, and --mode convos."
        ),
    )

    # mine-all
    p_mine_all = sub.add_parser(
        "mine-all", help="Mine all projects in a parent directory (one wing per project)"
    )
    p_mine_all.add_argument("dir", help="Parent directory containing project subdirectories")
    p_mine_all.add_argument(
        "--dry-run",
        action="store_true",
        help="List detected projects and derived wing names without mining",
    )
    p_mine_all.add_argument(
        "--force",
        action="store_true",
        help="Deprecated — mine-all now syncs all wings incrementally by default; accepted for compatibility",
    )
    p_mine_all.add_argument(
        "--new-only",
        dest="new_only",
        action="store_true",
        help="Skip projects whose wing already exists in the palace (old default behavior)",
    )
    p_mine_all.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Don't respect .gitignore files when scanning project files",
    )
    p_mine_all.add_argument(
        "--include-ignored",
        action="append",
        default=[],
        help="Always scan these project-relative paths even if ignored",
    )
    p_mine_all.add_argument(
        "--agent",
        default="mempalace",
        help="Name recorded on every drawer (default: mempalace)",
    )

    # search
    p_search = sub.add_parser("search", help="Find anything, exact words")
    p_search.add_argument("query", help="What to search for")
    p_search.add_argument("--wing", default=None, help="Limit to one project")
    p_search.add_argument("--room", default=None, help="Limit to one room")
    p_search.add_argument("--results", type=int, default=5, help="Number of results")

    # read
    p_read = sub.add_parser(
        "read",
        help="Print stored source lines for a file and line range (requires freshly mined chunks with line metadata)",
    )
    p_read.add_argument("source_file", help="Exact source file path as stored in the palace")
    p_read.add_argument("--start", type=int, required=True, help="First line to include (1-indexed)")
    p_read.add_argument("--end", type=int, required=True, help="Last line to include (1-indexed)")
    p_read.add_argument("--wing", default=None, help="Filter to a specific wing (optional)")

    # compress
    p_compress = sub.add_parser(
        "compress", help="Compress drawers using AAAK Dialect (~30x reduction)"
    )
    p_compress.add_argument("--wing", default=None, help="Wing to compress (default: all wings)")
    p_compress.add_argument(
        "--dry-run", action="store_true", help="Preview compression without storing"
    )
    p_compress.add_argument(
        "--config", default=None, help="Entity config JSON (e.g. entities.json)"
    )

    # wake-up
    p_wakeup = sub.add_parser("wake-up", help="Show L0 + L1 wake-up context (~600-900 tokens)")
    p_wakeup.add_argument("--wing", default=None, help="Wake-up for a specific project/wing")

    # split
    p_split = sub.add_parser(
        "split",
        help="Split concatenated transcript mega-files into per-session files (run before mine)",
    )
    p_split.add_argument("dir", help="Directory containing transcript files")
    p_split.add_argument(
        "--output-dir",
        default=None,
        help="Write split files here (default: same directory as source files)",
    )
    p_split.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be split without writing files",
    )
    p_split.add_argument(
        "--min-sessions",
        type=int,
        default=2,
        help="Only split files containing at least N sessions (default: 2)",
    )

    # diary
    p_diary = sub.add_parser("diary", help="Diary commands")
    diary_sub = p_diary.add_subparsers(dest="diary_command")

    p_diary_write = diary_sub.add_parser("write", help="Write a diary entry")
    p_diary_write.add_argument("--agent", required=True, help="Agent name (e.g. claude-code)")
    p_diary_write.add_argument(
        "--entry", required=True, help="Diary entry content (stored verbatim)"
    )
    p_diary_write.add_argument("--topic", default="general", help="Topic tag (default: general)")
    p_diary_write.add_argument(
        "--wing", default=None, help="Override target wing (default: wing_<agent>)"
    )

    # migrate-storage
    p_migrate = sub.add_parser(
        "migrate-storage",
        help="Migrate a ChromaDB palace to LanceDB (requires mempalace-code[chroma])",
    )
    p_migrate.add_argument("src_palace", help="Source ChromaDB palace path")
    p_migrate.add_argument("dst_palace", help="Destination LanceDB palace path")
    p_migrate.add_argument(
        "--backup-dir",
        default=None,
        help="Directory for the source backup tar.gz (default: parent of src_palace)",
    )
    p_migrate.add_argument(
        "--force",
        action="store_true",
        help="Allow appending to a non-empty destination palace",
    )
    p_migrate.add_argument(
        "--embed-model",
        default=None,
        help="Embedding model for the destination (default: all-MiniLM-L6-v2)",
    )
    p_migrate.add_argument(
        "--verify",
        action="store_true",
        help="Verify per-wing counts after migration; exit non-zero on mismatch",
    )

    # health
    p_health = sub.add_parser(
        "health",
        help="Probe palace for fragment-missing or read errors",
    )
    p_health.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON report instead of human-readable output",
    )

    # cleanup
    p_cleanup = sub.add_parser(
        "cleanup",
        help="Reclaim disk space from stale Lance versions (LanceDB palaces only)",
    )
    p_cleanup.add_argument(
        "--older-than-days",
        type=int,
        default=7,
        dest="older_than_days",
        metavar="DAYS",
        help="Remove versions older than this many days (default: 7)",
    )
    p_cleanup.add_argument(
        "--unsafe-now",
        action="store_true",
        dest="unsafe_now",
        help=(
            "Remove ALL stale versions immediately (cleanup_older_than=0, delete_unverified=True). "
            "Only safe when no other writer process is active."
        ),
    )
    p_cleanup.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON result instead of human-readable output",
    )

    # repair
    p_repair = sub.add_parser(
        "repair",
        help="Rebuild palace vector index from stored data (fixes segfaults after corruption)",
    )
    p_repair.add_argument(
        "--rollback",
        action="store_true",
        help="Attempt version rollback to last healthy version before falling back to full rebuild",
    )
    p_repair.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="With --rollback: show candidate version without restoring",
    )

    # status
    sub.add_parser("status", help="Show what's been filed")

    # install-alias
    p_alias = sub.add_parser(
        "install-alias",
        help="Create optional `mempalace` alias when that command name is unused",
    )
    p_alias.add_argument(
        "--target-dir",
        default=None,
        help="Directory where the alias should be created (default: next to mempalace-code)",
    )

    # fetch-model
    p_fetch = sub.add_parser("fetch-model", help="Download the embedding model (~80 MB)")
    p_fetch.add_argument(
        "--model",
        default=None,
        help="Model name (default: all-MiniLM-L6-v2)",
    )
    p_fetch.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )

    # watch
    p_watch = sub.add_parser(
        "watch",
        help="Watch all initialized projects for changes and re-mine automatically",
    )
    p_watch.add_argument(
        "dir",
        help="Parent directory containing project subdirectories",
    )
    p_watch.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Don't respect .gitignore files when scanning project files",
    )
    p_watch.add_argument(
        "--agent",
        default="mempalace",
        help="Name recorded on every drawer (default: mempalace)",
    )
    p_watch.add_argument(
        "--on-save",
        action="store_true",
        help="Re-mine on every file save instead of only on git commits (noisier)",
    )
    watch_sub = p_watch.add_subparsers(dest="watch_command")

    # watch status
    watch_sub.add_parser(
        "status",
        help="Print disk-budget summary and launchd state for the watch daemon",
    )

    # watch schedule
    p_watch_schedule = watch_sub.add_parser(
        "schedule",
        help="Print a scheduler snippet (launchd plist or cron line) for the watch daemon",
    )
    p_watch_schedule.add_argument(
        "--install",
        action="store_true",
        help="(Accepted but rejected with an explanation — owner action required)",
    )

    # backup
    p_backup = sub.add_parser(
        "backup",
        help="Palace backup commands: create, list, schedule",
    )
    # Top-level --out for back-compat: 'mempalace-code backup --out X' still works
    p_backup.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="Output .tar.gz path (default: <palace_parent>/backups/mempalace_backup_<ts>.tar.gz)",
    )
    backup_sub = p_backup.add_subparsers(dest="backup_command")

    # backup create
    p_backup_create = backup_sub.add_parser(
        "create",
        help="Create a .tar.gz snapshot of the palace (lance data + KG + metadata)",
    )
    p_backup_create.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="Output .tar.gz path (default: <palace_parent>/backups/<kind_prefix><ts>.tar.gz)",
    )
    p_backup_create.add_argument(
        "--kind",
        choices=["manual", "scheduled", "pre_optimize"],
        default="manual",
        help="Backup kind — affects filename prefix and retention bucket (default: manual)",
    )

    # backup list
    p_backup_list = backup_sub.add_parser(
        "list",
        help="List existing backup archives",
    )
    p_backup_list.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Include an extra directory in backup discovery (e.g. a legacy CWD backup location)",
    )

    # backup schedule
    p_backup_schedule = backup_sub.add_parser(
        "schedule",
        help="Print a scheduler snippet (launchd plist or cron line) for scheduled backups",
    )
    p_backup_schedule.add_argument(
        "--freq",
        required=True,
        choices=["daily", "weekly", "hourly"],
        help="Backup frequency",
    )
    p_backup_schedule.add_argument(
        "--install",
        action="store_true",
        help="(Accepted but rejected with an explanation — owner action required)",
    )

    # restore
    p_restore = sub.add_parser(
        "restore",
        help="Restore a palace from a .tar.gz backup archive",
    )
    p_restore.add_argument("archive", help="Path to the .tar.gz backup archive")
    p_restore.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing non-empty palace",
    )

    # export
    p_export = sub.add_parser("export", help="Export drawers (and KG) to a JSONL file for backup")
    p_export.add_argument(
        "--out",
        required=True,
        metavar="FILE",
        help="Output JSONL file path (use '-' for stdout)",
    )
    p_export.add_argument(
        "--only-manual",
        action="store_true",
        help="Export only manually-added drawers (chunker_strategy in manual_v1, diary_v1)",
    )
    p_export.add_argument("--wing", default=None, help="Limit export to one wing")
    p_export.add_argument("--room", default=None, help="Limit export to one room")
    p_export.add_argument(
        "--since",
        default=None,
        metavar="DATE",
        help="Export only drawers filed on or after this ISO date (e.g. 2026-01-01)",
    )
    p_export.add_argument("--with-kg", action="store_true", help="Include KG triples in export")
    p_export.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Include raw embedding vectors (larger file)",
    )
    p_export.add_argument("--pretty", action="store_true", help="Pretty-print JSON (larger file)")

    # import
    p_import = sub.add_parser("import", help="Import drawers (and KG) from a JSONL export file")
    p_import.add_argument("jsonl_file", help="JSONL export file to import (use '-' for stdin)")
    p_import.add_argument(
        "--skip-dedup",
        action="store_true",
        help="Skip duplicate detection (import all records regardless of similarity)",
    )
    p_import.add_argument("--skip-kg", action="store_true", help="Skip KG triple import")
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be imported without writing anything",
    )
    p_import.add_argument(
        "--wing-override",
        default=None,
        metavar="WING",
        help="Override the wing for all imported drawers",
    )

    # version-check
    p_vc = sub.add_parser(
        "version-check",
        help="Manage opt-in periodic new-version checks (contacts PyPI for package metadata only)",
    )
    vc_group = p_vc.add_mutually_exclusive_group()
    vc_group.add_argument(
        "--enable",
        action="store_true",
        help="Enable periodic version checks",
    )
    vc_group.add_argument(
        "--disable",
        action="store_true",
        help="Disable periodic version checks (suppress future prompts)",
    )
    vc_group.add_argument(
        "--check-now",
        dest="check_now",
        action="store_true",
        help="Check for a newer version right now (contacts PyPI; ignores interval)",
    )
    vc_group.add_argument(
        "--status",
        action="store_true",
        help="Show current version-check settings without contacting PyPI (default action)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "diary" and not args.diary_command:
        p_diary.print_help()
        sys.exit(2)

    if args.command == "diary":
        args._diary_parser = p_diary

    if args.command == "mine" and args.include_emotional:
        if args.mode != "convos" or args.extract != "general":
            p_mine.error("--include-emotional requires --mode convos --extract general")

    dispatch = {
        "init": cmd_init,
        "onboarding": cmd_onboarding,
        "mine": cmd_mine,
        "mine-all": cmd_mine_all,
        "watch": cmd_watch,
        "split": cmd_split,
        "search": cmd_search,
        "read": cmd_read,
        "compress": cmd_compress,
        "wake-up": cmd_wakeup,
        "migrate-storage": cmd_migrate_storage,
        "health": cmd_health,
        "cleanup": cmd_cleanup,
        "repair": cmd_repair,
        "status": cmd_status,
        "diary": cmd_diary,
        "fetch-model": cmd_fetch_model,
        "install-alias": cmd_install_alias,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "export": cmd_export,
        "import": cmd_import,
        "version-check": cmd_version_check,
    }

    # --- opt-in version-check hook ---
    # version-check command handles itself; all others may get a first-run prompt.
    if args.command != "version-check":
        from .version import __version__ as _current_version
        from .version_check import (
            load_state,
            resolve_config,
            run_automatic_check,
            run_first_run_prompt,
            should_prompt_first_run,
        )

        _vc_config = resolve_config()
        _vc_state = load_state()

        if should_prompt_first_run(args.command, _vc_config):
            run_first_run_prompt(_vc_state)
            _vc_config = resolve_config()

    dispatch[args.command](args)

    # Automatic check runs after the command succeeds; skipped on SystemExit.
    if args.command != "version-check" and _vc_config.enabled:  # type: ignore[possibly-undefined]  # reason: assigned conditionally via opt-in path; always set when enabled
        run_automatic_check(  # type: ignore[possibly-undefined]  # reason: assigned conditionally via opt-in path; always set when enabled
            _current_version,  # type: ignore[possibly-undefined]  # reason: assigned conditionally via opt-in path; always set when enabled
            _vc_config,
            _vc_state,  # type: ignore[possibly-undefined]  # reason: assigned conditionally via opt-in path; always set when enabled
        )


if __name__ == "__main__":
    main()
