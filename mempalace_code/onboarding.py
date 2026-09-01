#!/usr/bin/env python3
"""
onboarding.py — MemPalace guided onboarding (opt-in).

Asks the user:
  1. How they're using MemPalace (work / personal / combo)
  2. Who the people in their life are (names, nicknames, relationships)
  3. What their projects are
  4. What they want their wings called

Seeds the entity_registry with confirmed data so MemPalace knows your world
from minute one — before a single session is indexed.

This is an opt-in path for personal/notes-heavy setups.
For code projects, `mempalace-code init <dir>` generates mempalace.yaml
from folder structure without any prompts.

Usage:
    mempalace-code onboarding <dir>       (guided, interactive)
    mempalace-code init <dir>             (config-file-first, non-interactive)
"""

from pathlib import Path

from mempalace_code.entity_detector import detect_entities, scan_for_detection
from mempalace_code.entity_registry import EntityRegistry

# ─────────────────────────────────────────────────────────────────────────────
# Default wing taxonomies by mode
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_WINGS = {
    "work": [
        "projects",
        "clients",
        "team",
        "decisions",
        "research",
    ],
    "personal": [
        "family",
        "health",
        "creative",
        "reflections",
        "relationships",
    ],
    "combo": [
        "family",
        "work",
        "health",
        "creative",
        "projects",
        "reflections",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Safety constants
# ─────────────────────────────────────────────────────────────────────────────

_MAX_RETRIES = 3
_YN_VALID = frozenset({"y", "yes", "n", "no"})


# ─────────────────────────────────────────────────────────────────────────────
# Abort signal
# ─────────────────────────────────────────────────────────────────────────────


class _AbortOnboarding(Exception):
    """Raised on EOF, Ctrl-C, or retry exhaustion to abort cleanly without traceback."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _safe_input(prompt: str) -> str | None:
    """Read one line from stdin. Returns stripped value, or None on EOF/interrupt."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _hr():
    print(f"\n{'─' * 58}")


def _header(text):
    print(f"\n{'=' * 58}")
    print(f"  {text}")
    print(f"{'=' * 58}")


def _ask(prompt: str, default: str | None = None) -> str:
    """Prompt for free-form text. Raises _AbortOnboarding on EOF or interrupt."""
    if default:
        val = _safe_input(f"  {prompt} [{default}]: ")
        if val is None:
            raise _AbortOnboarding
        return val if val else default
    val = _safe_input(f"  {prompt}: ")
    if val is None:
        raise _AbortOnboarding
    return val


def _yn(prompt: str, default: str = "y") -> bool:
    """
    Yes/no prompt with bounded retries and safe default.

    Accepted values: y, yes, n, no (case-insensitive) or empty (uses default).
    Raises _AbortOnboarding on EOF, interrupt, or retry exhaustion.
    """
    indicator = "Y/n" if default == "y" else "y/N"
    for _ in range(_MAX_RETRIES):
        val = _safe_input(f"  {prompt} [{indicator}]: ")
        if val is None:
            raise _AbortOnboarding
        if val == "":
            return default == "y"
        if val.lower() in _YN_VALID:
            return val.lower() in ("y", "yes")
        print("  Please enter y or n.")
    raise _AbortOnboarding


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Mode selection
# ─────────────────────────────────────────────────────────────────────────────


def _ask_mode() -> str:
    _header("Welcome to MemPalace")
    print("""
  MemPalace is a personal memory system. To work well, it needs to know
  a little about your world — who the people are, what the projects
  are, and how you want your memory organized.

  This takes about 2 minutes. You can always update it later.
""")
    print("  How are you using MemPalace?")
    print()
    print("    [1]  Work     — notes, projects, clients, colleagues, decisions")
    print("    [2]  Personal — diary, family, health, relationships, reflections")
    print("    [3]  Both     — personal and professional mixed")
    print()

    for _ in range(_MAX_RETRIES):
        choice = _safe_input("  Your choice [1/2/3]: ")
        if choice is None:
            raise _AbortOnboarding
        if choice == "1":
            return "work"
        elif choice == "2":
            return "personal"
        elif choice == "3":
            return "combo"
        print("  Please enter 1, 2, or 3.")
    raise _AbortOnboarding


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: People
# ─────────────────────────────────────────────────────────────────────────────


def _ask_people(mode: str) -> tuple[list, dict]:
    """Returns (people_list, aliases_dict)."""
    people = []
    aliases = {}  # nickname → full name

    if mode in ("personal", "combo"):
        _hr()
        print("""
  Personal world — who are the important people in your life?

  Format: name, relationship (e.g. "Riley, daughter" or just "Devon")
  For nicknames, you'll be asked separately.
  Type 'done' when finished.
""")
        while True:
            entry = _safe_input("  Person: ")
            if entry is None:
                raise _AbortOnboarding
            if entry.lower() in ("done", ""):
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            relationship = parts[1] if len(parts) > 1 else ""
            if name:
                nick = _safe_input(f"  Nickname for {name}? (or enter to skip): ")
                if nick is None:
                    raise _AbortOnboarding
                if nick:
                    aliases[nick] = name
                people.append({"name": name, "relationship": relationship, "context": "personal"})

    if mode in ("work", "combo"):
        _hr()
        print("""
  Work world — who are the colleagues, clients, or collaborators
  you'd want to find in your notes?

  Format: name, role (e.g. "Ben, co-founder" or just "Sarah")
  Type 'done' when finished.
""")
        while True:
            entry = _safe_input("  Person: ")
            if entry is None:
                raise _AbortOnboarding
            if entry.lower() in ("done", ""):
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            role = parts[1] if len(parts) > 1 else ""
            if name:
                people.append({"name": name, "relationship": role, "context": "work"})

    return people, aliases


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Projects
# ─────────────────────────────────────────────────────────────────────────────


def _ask_projects(mode: str) -> list:
    if mode == "personal":
        return []

    _hr()
    print("""
  What are your main projects? (These help MemPalace distinguish project
  names from person names — e.g. "Lantern" the project vs. "Lantern" the word.)

  Type 'done' when finished.
""")
    projects = []
    while True:
        proj = _safe_input("  Project: ")
        if proj is None:
            raise _AbortOnboarding
        if proj.lower() in ("done", ""):
            break
        if proj:
            projects.append(proj)
    return projects


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Wings
# ─────────────────────────────────────────────────────────────────────────────


def _ask_wings(mode: str) -> list:
    defaults = DEFAULT_WINGS[mode]
    _hr()
    print(f"""
  Wings are the top-level categories in your memory palace.

  Suggested wings for {mode} mode:
    {", ".join(defaults)}

  Press enter to keep these, or type your own comma-separated list.
""")
    custom = _safe_input("  Wings: ")
    if custom is None:
        raise _AbortOnboarding
    if custom:
        return [w.strip() for w in custom.split(",") if w.strip()]
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Auto-detect from files
# ─────────────────────────────────────────────────────────────────────────────


def _auto_detect(directory: str, known_people: list) -> list:
    """Scan directory for additional entity candidates."""
    known_names = {p["name"].lower() for p in known_people}

    try:
        files = scan_for_detection(directory)
        if not files:
            return []
        detected = detect_entities(files)
        new_people = [
            e
            for e in detected["people"]
            if e["name"].lower() not in known_names and e["confidence"] >= 0.7
        ]
        return new_people
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Ambiguity warnings
# ─────────────────────────────────────────────────────────────────────────────


def _warn_ambiguous(people: list) -> list:
    """
    Flag names that are also common English words.
    Returns list of ambiguous names for user awareness.
    """
    from mempalace_code.entity_registry import COMMON_ENGLISH_WORDS

    ambiguous = []
    for p in people:
        if p["name"].lower() in COMMON_ENGLISH_WORDS:
            ambiguous.append(p["name"])
    return ambiguous


# ─────────────────────────────────────────────────────────────────────────────
# Main onboarding flow
# ─────────────────────────────────────────────────────────────────────────────


def _generate_aaak_bootstrap(
    people: list, projects: list, wings: list, mode: str, config_dir: Path | None = None
):
    """
    Generate AAAK entity registry + critical facts bootstrap from onboarding data.
    These files teach the AI about the user's world from session one.
    """
    from .room_detector_local import write_regular_destination

    mempalace_dir = Path(config_dir) if config_dir else Path.home() / ".mempalace"
    mempalace_dir.mkdir(parents=True, exist_ok=True)

    # Build AAAK entity codes (first 3 letters of name, uppercase)
    entity_codes = {}
    for p in people:
        name = p["name"]
        code = name[:3].upper()
        # Handle collisions
        while code in entity_codes.values():
            code = name[:4].upper()
        entity_codes[name] = code

    # AAAK entity registry
    registry_lines = [
        "# AAAK Entity Registry",
        "# Auto-generated by mempalace-code init. Update as needed.",
        "",
        "## People",
    ]
    for p in people:
        name = p["name"]
        code = entity_codes[name]
        rel = p.get("relationship", "")
        registry_lines.append(f"  {code}={name} ({rel})" if rel else f"  {code}={name}")

    if projects:
        registry_lines.extend(["", "## Projects"])
        for proj in projects:
            code = proj[:4].upper()
            registry_lines.append(f"  {code}={proj}")

    registry_lines.extend(
        [
            "",
            "## AAAK Quick Reference",
            "  Symbols: ♡=love ★=importance ⚠=warning →=relationship |=separator",
            "  Structure: KEY:value | GROUP(details) | entity.attribute",
            "  Read naturally — expand codes, treat *markers* as emotional context.",
        ]
    )

    write_regular_destination(mempalace_dir / "aaak_entities.md", "\n".join(registry_lines))

    # Critical facts bootstrap (pre-palace — before any mining)
    facts_lines = [
        "# Critical Facts (bootstrap — will be enriched after mining)",
        "",
    ]

    personal_people = [p for p in people if p.get("context") == "personal"]
    work_people = [p for p in people if p.get("context") == "work"]

    if personal_people:
        facts_lines.append("## People (personal)")
        for p in personal_people:
            code = entity_codes[p["name"]]
            rel = p.get("relationship", "")
            facts_lines.append(
                f"- **{p['name']}** ({code}) — {rel}" if rel else f"- **{p['name']}** ({code})"
            )
        facts_lines.append("")

    if work_people:
        facts_lines.append("## People (work)")
        for p in work_people:
            code = entity_codes[p["name"]]
            rel = p.get("relationship", "")
            facts_lines.append(
                f"- **{p['name']}** ({code}) — {rel}" if rel else f"- **{p['name']}** ({code})"
            )
        facts_lines.append("")

    if projects:
        facts_lines.append("## Projects")
        for proj in projects:
            facts_lines.append(f"- **{proj}**")
        facts_lines.append("")

    facts_lines.extend(
        [
            "## Palace",
            f"Wings: {', '.join(wings)}",
            f"Mode: {mode}",
            "",
            "*This file will be enriched by palace_facts.py after mining.*",
        ]
    )

    write_regular_destination(mempalace_dir / "critical_facts.md", "\n".join(facts_lines))


def run_onboarding(
    directory: str = ".",
    config_dir: Path | None = None,
    auto_detect: bool = True,
) -> EntityRegistry | None:
    """
    Run the full onboarding flow.
    Returns the seeded EntityRegistry, or None if the user aborted.

    All mutations (registry, AAAK files) are staged until all prompts
    complete successfully. EOF or Ctrl-C at any prompt aborts cleanly
    without partial writes.
    """
    try:
        return _run_onboarding_inner(directory, config_dir, auto_detect)
    except _AbortOnboarding:
        print("\n  Onboarding aborted. No changes were saved.")
        return None


def _run_onboarding_inner(
    directory: str,
    config_dir: Path | None,
    auto_detect: bool,
) -> EntityRegistry:
    # ── Collect all data from prompts (no writes until completion) ────────────

    # Step 1: Mode
    mode = _ask_mode()

    # Step 2: People
    people, aliases = _ask_people(mode)

    # Step 3: Projects
    projects = _ask_projects(mode)

    # Step 4: Wings (stored in config, not registry — just show user)
    wings = _ask_wings(mode)

    # Step 5: Auto-detect additional people from files
    # Privacy-sensitive: defaults to No — explicit Yes required to scan.
    if auto_detect and _yn(
        "Scan local files for additional names we might have missed?", default="n"
    ):
        directory = _ask("Directory to scan", default=directory)
        detected = _auto_detect(directory, people)
        if detected:
            _hr()
            print(f"\n  Found {len(detected)} additional name candidates:\n")
            for e in detected:
                print(
                    f"    {e['name']:20} confidence={e['confidence']:.0%}  "
                    f"({', '.join(e['signals'][:1])})"
                )
            print()
            if _yn("Add any of these to your registry?", default="n"):
                for e in detected:
                    ans = _safe_input(f"    {e['name']} — (p)erson, (s)kip? ")
                    if ans is None:
                        raise _AbortOnboarding
                    if ans == "p":
                        rel = _ask(f"Relationship/role for {e['name']}?")
                        if mode == "personal":
                            ctx = "personal"
                        elif mode == "work":
                            ctx = "work"
                        else:
                            ctx_raw = _safe_input("    Context — (p)ersonal or (w)ork? ")
                            if ctx_raw is None:
                                raise _AbortOnboarding
                            ctx = "work" if ctx_raw.lower().startswith("w") else "personal"
                        people.append({"name": e["name"], "relationship": rel, "context": ctx})

    # Step 6: Warn about ambiguous names
    ambiguous = _warn_ambiguous(people)
    if ambiguous:
        _hr()
        print(f"""
  Heads up — these names are also common English words:
    {", ".join(ambiguous)}

  MemPalace will check the context before treating them as person names.
  For example: "I picked up Riley" → person.
               "Have you ever tried" → adverb.
""")

    # ── All prompts complete — now write (staged commit) ──────────────────────

    from .room_detector_local import restore_regular_destinations, snapshot_regular_destinations

    mempalace_dir = Path(config_dir) if config_dir else Path.home() / ".mempalace"
    output_paths = [
        mempalace_dir / "entity_registry.json",
        mempalace_dir / "aaak_entities.md",
        mempalace_dir / "critical_facts.md",
    ]
    directory_was_absent = not mempalace_dir.exists()
    snapshots = snapshot_regular_destinations(output_paths)

    # Build and save registry with rerun reconciliation.
    registry = EntityRegistry.load(config_dir)
    try:
        registry.seed(mode=mode, people=people, projects=projects, aliases=aliases)
        _generate_aaak_bootstrap(people, projects, wings, mode, config_dir)
    except BaseException:
        restore_regular_destinations(snapshots)
        if directory_was_absent and mempalace_dir.is_dir() and not any(mempalace_dir.iterdir()):
            mempalace_dir.rmdir()
        raise

    # Summary
    _header("Setup Complete")
    print()
    print(f"  {registry.summary()}")
    print(f"\n  Wings: {', '.join(wings)}")
    print(f"\n  Registry saved to: {registry._path}")
    print("\n  AAAK entity registry: ~/.mempalace/aaak_entities.md")
    print("  Critical facts bootstrap: ~/.mempalace/critical_facts.md")
    print("\n  Your AI will know your world from the first session.")
    print()

    return registry


# ─────────────────────────────────────────────────────────────────────────────
# Quick setup (non-interactive, for testing)
# ─────────────────────────────────────────────────────────────────────────────


def quick_setup(
    mode: str,
    people: list,
    projects: list | None = None,
    aliases: dict | None = None,
    config_dir: Path | None = None,
) -> EntityRegistry:
    """
    Programmatic setup without interactive prompts.
    Used in tests and benchmark scripts.

    people: list of dicts {"name": str, "relationship": str, "context": str}
    """
    registry = EntityRegistry.load(config_dir)
    registry.seed(
        mode=mode,
        people=people,
        projects=projects or [],
        aliases=aliases or {},
    )
    return registry


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    run_onboarding(directory=directory)
