"""
Pure rsync command inspection for MemPalace mirror safety.

No subprocess is ever created. All analysis is done on the command string only.
"""

import re
import shlex
from dataclasses import dataclass, field

# rsync flags that cause remote deletions of files not in the source
RSYNC_DELETE_FLAGS: frozenset[str] = frozenset(
    {
        "--delete",
        "--delete-after",
        "--delete-before",
        "--delete-delay",
        "--delete-during",
        "--delete-excluded",
        "--delete-missing-args",
    }
)

# Matches any path arg that references a MemPalace state directory.
# Handles ~/.mempalace/, $HOME/.mempalace/, /abs/path/.mempalace/, host:.mempalace/
# and bare .mempalace/ (relative path from home dir).
_MEMPALACE_STATE_RE = re.compile(r"(?:[/:]|^)\.mempalace(?:/|$)")

# Required exclude families: a delete-mode state mirror must exclude each of
# these families to receive an ok=True verdict.
_FAMILY_MATCHERS: dict[str, re.Pattern[str]] = {
    "palace": re.compile(r"^palace(?:/|$|\*)"),
    "kg": re.compile(r"^knowledge_graph\.sqlite3$|^\*\.sqlite3$"),
    "config": re.compile(r"^config\.json$"),
    "backups": re.compile(r"^backups(?:/|$|\*)"),
}

# Advisory families: missing members produce a warning, not a blocked verdict.
# Logs default to /tmp/mempalace-watch.log (outside the state dir) so they are
# advisory only; operators who route logs into the state dir should add an exclude.
_ADVISORY_MATCHERS: dict[str, re.Pattern[str]] = {
    "logs": re.compile(r"^.*\.log$"),
}

DANGEROUS_PATTERN_ID = "delete-mode-state-mirror-missing-excludes"
# --delete-excluded is unconditionally dangerous for state-dir mirrors: it removes
# destination files matched by --exclude, so no exclude list can protect palace data.
DELETE_EXCLUDED_PATTERN_ID = "delete-excluded-state-mirror"


@dataclass
class PreflightResult:
    ok: bool
    dangerous: bool = False
    pattern_id: str = ""
    missing_excludes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_error: str = ""


def _extract_excludes(tokens: list[str]) -> list[str]:
    excludes: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--exclude="):
            excludes.append(tok[len("--exclude=") :])
        elif tok == "--exclude" and i + 1 < len(tokens):
            i += 1
            excludes.append(tokens[i])
        i += 1
    return excludes


def _has_delete_semantics(tokens: list[str]) -> bool:
    return any(tok in RSYNC_DELETE_FLAGS for tok in tokens)


def _targets_state_dir(tokens: list[str]) -> bool:
    for tok in tokens[1:]:  # skip command name
        if not tok.startswith("-") and _MEMPALACE_STATE_RE.search(tok):
            return True
    return False


def _family_covered(pattern: re.Pattern[str], excludes: list[str]) -> bool:
    return any(pattern.match(e) for e in excludes)


def classify_mirror_command(command: str) -> PreflightResult:
    """
    Parse and classify an rsync command string without executing it.

    Returns PreflightResult with:
    - ok=True  when the command is safe or not a MemPalace delete-mode mirror.
    - ok=False, dangerous=True when it is a MemPalace delete-mode mirror with
      missing required excludes; missing_excludes lists the absent families.
    - ok=False, parse_error set when the shell text cannot be tokenized.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return PreflightResult(ok=False, parse_error=str(exc))

    if not tokens:
        return PreflightResult(ok=False, parse_error="empty command")

    cmd_basename = tokens[0].split("/")[-1]
    if cmd_basename != "rsync":
        return PreflightResult(ok=True)

    if not _has_delete_semantics(tokens):
        return PreflightResult(ok=True)

    if not _targets_state_dir(tokens):
        return PreflightResult(ok=True)

    # --delete-excluded removes destination-side files matched by --exclude, so
    # required excludes cannot protect palace data regardless of coverage.
    if "--delete-excluded" in tokens:
        return PreflightResult(
            ok=False,
            dangerous=True,
            pattern_id=DELETE_EXCLUDED_PATTERN_ID,
            warnings=[
                "--delete-excluded removes destination-side files matched by --exclude; "
                "no exclude list can protect palace data — use --delete and exclude all MemPalace families"
            ],
        )

    excludes = _extract_excludes(tokens)

    missing = [
        family
        for family, pattern in _FAMILY_MATCHERS.items()
        if not _family_covered(pattern, excludes)
    ]

    warnings: list[str] = []
    for family, pattern in _ADVISORY_MATCHERS.items():
        if not _family_covered(pattern, excludes):
            warnings.append(
                f"advisory: no --exclude for '{family}' "
                f"(add --exclude='*.log' if you route MemPalace logs into the state directory)"
            )

    if missing:
        return PreflightResult(
            ok=False,
            dangerous=True,
            pattern_id=DANGEROUS_PATTERN_ID,
            missing_excludes=missing,
            warnings=warnings,
        )

    return PreflightResult(ok=True, warnings=warnings)
