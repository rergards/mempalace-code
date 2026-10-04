"""
Pure rsync command inspection for MemPalace mirror safety.

No subprocess is ever created. All analysis is done on the command string only;
the caller supplies the configured palace paths to compare against.
"""

import fnmatch
import os
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# rsync flags that cause remote deletions of files not in the source.
# "--del" is rsync's alias for --delete-during.
RSYNC_DELETE_FLAGS: frozenset[str] = frozenset(
    {
        "--del",
        "--delete",
        "--delete-after",
        "--delete-before",
        "--delete-delay",
        "--delete-during",
        "--delete-excluded",
        "--delete-missing-args",
    }
)

# rsync flags that delete the transferred files from the (local) source;
# --remove-sent-files is the deprecated alias rsync still accepts.
RSYNC_REMOVE_SOURCE_FLAGS: frozenset[str] = frozenset(
    {"--remove-source-files", "--remove-sent-files"}
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

# Full palace copies that `repair` (<palace>.backup-<UTC>) and the rebuild workflow
# (<palace>.quarantine-<UTC>) leave beside the palace; each family is covered by an exclude
# that matches its sample name (for example 'palace.backup-*/' or 'palace*/').
_COPY_FAMILY_SAMPLES: dict[str, str] = {
    "repair-backups": "palace.backup-20260101T000000Z",
    "quarantines": "palace.quarantine-20260101T000000Z",
}
# Sample state-dir entries for each required family, used when a mirror source is a parent
# of the state directory and excludes are written relative to that parent.
_FAMILY_SAMPLES: dict[str, str] = {
    "palace": "palace",
    "kg": "knowledge_graph.sqlite3",
    "config": "config.json",
    "backups": "backups",
    **_COPY_FAMILY_SAMPLES,
}

# Advisory families: missing members produce a warning, not a blocked verdict.
_ADVISORY_MATCHERS: dict[str, tuple[re.Pattern[str], str]] = {
    # launchd watch jobs log to ~/Library/Logs/<label>.log (before 1.15.0: the shared
    # /tmp/mempalace-watch.log), outside the state dir.
    "logs": (
        re.compile(r"^.*\.log$"),
        "add --exclude='*.log' if you route MemPalace logs into the state directory",
    ),
    # The legacy-KG adoption marker records host-local file state.
    "adopted": (
        re.compile(r"^knowledge_graph\.sqlite3\.adopted$|^\*\.adopted$"),
        "add --exclude=knowledge_graph.sqlite3.adopted; the legacy-KG adoption marker "
        "records host-local state",
    ),
}

# rsync long options that consume the following token when written without '='.
_RSYNC_LONG_WITH_VALUE: frozenset[str] = frozenset(
    {
        "--address",
        "--backup-dir",
        "--block-size",
        "--bwlimit",
        "--checksum-choice",
        "--checksum-seed",
        "--chmod",
        "--chown",
        "--compare-dest",
        "--compress-choice",
        "--compress-level",
        "--contimeout",
        "--copy-dest",
        "--debug",
        "--files-from",
        "--groupmap",
        "--iconv",
        "--info",
        "--link-dest",
        "--log-file",
        "--log-file-format",
        "--max-alloc",
        "--max-delete",
        "--max-size",
        "--min-size",
        "--modify-window",
        "--only-write-batch",
        "--out-format",
        "--outbuf",
        "--partial-dir",
        "--password-file",
        "--port",
        "--protocol",
        "--read-batch",
        "--remote-option",
        "--rsh",
        "--rsync-path",
        "--skip-compress",
        "--sockopts",
        "--stop-after",
        "--stop-at",
        "--suffix",
        "--temp-dir",
        "--timeout",
        "--usermap",
        "--write-batch",
    }
)
# rsync short options that take a value (attached or as the next token).
_RSYNC_SHORT_WITH_VALUE = frozenset("efTBM@")
_RSYNC_RULE_OPTIONS = frozenset(
    {"--exclude", "--include", "--filter", "--exclude-from", "--include-from"}
)
_LONG_RULE_NAMES = {
    "exclude": "-",
    "include": "+",
    "merge": ".",
    "dir-merge": ":",
    "hide": "H",
    "show": "S",
    "protect": "P",
    "risk": "R",
    "clear": "!",
}

# Sudo options that take no argument (flags only).
_SUDO_FLAGS_NO_ARG: frozenset[str] = frozenset(
    {
        "-n",
        "--non-interactive",
        "-S",
        "--stdin",
        "-E",
        "--preserve-env",
        "-H",
        "--set-home",
        "-P",
        "--preserve-groups",
        "-b",
        "--background",
        "-k",
        "--reset-timestamp",
        "-K",
        "--remove-timestamp",
    }
)

# Sudo options that consume one following token as their argument.
_SUDO_FLAGS_ONE_ARG: frozenset[str] = frozenset(
    {
        "-u",
        "--user",
        "-g",
        "--group",
        "-p",
        "--prompt",
        "-C",
        "--close-from",
        "-T",
        "--command-timeout",
        "-D",
        "--chdir",
        "-R",
        "--chroot",
        "-r",
        "--role",
        "-t",
        "--type",
    }
)

# env options that take no argument.
_ENV_FLAGS_NO_ARG: frozenset[str] = frozenset({"-i", "--ignore-environment", "-0", "--null"})

# env options that consume one following token as their argument.
_ENV_FLAGS_ONE_ARG: frozenset[str] = frozenset(
    {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
)

# Shell basenames whose `-c payload` form is supported.
_SHELL_BASENAMES: frozenset[str] = frozenset({"sh", "bash"})

# Process runners that execute their trailing argv unchanged; the rsync argv is
# the tail that starts at the rsync token. Other leading commands (echo, printf)
# only mention rsync and are not flagged.
_TRANSPARENT_RUNNERS: frozenset[str] = frozenset(
    {"caffeinate", "chronic", "command", "exec", "flock", "ionice", "nice", "nohup"}
    | {"setsid", "stdbuf", "taskpolicy", "time", "timeout"}
)

# Shell operators that end one command and start the next.
_COMMAND_SEPARATORS: frozenset[str] = frozenset({"&&", "||", ";", ";;", "|", "|&", "&", "(", ")"})
_REDIRECTIONS: frozenset[str] = frozenset({">", ">>", "<", "<<", "<<<", ">&", "<&", "&>", ">|"})

DANGEROUS_PATTERN_ID = "delete-mode-state-mirror-missing-excludes"
# --delete-excluded is unconditionally dangerous for state-dir mirrors: it removes
# destination files matched by --exclude, so no exclude list can protect palace data.
DELETE_EXCLUDED_PATTERN_ID = "delete-excluded-state-mirror"
REMOVE_SOURCE_PATTERN_ID = "remove-source-files-state-mirror"
PALACE_PATTERN_ID = "delete-mode-palace-mirror"
UNVERIFIABLE_FILTER_PATTERN_ID = "unverifiable-filter-rules"
UNVERIFIABLE_COMPOUND_PATTERN_ID = "unverifiable-compound-command"


@dataclass
class PreflightResult:
    ok: bool
    dangerous: bool = False
    pattern_id: str = ""
    missing_excludes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_error: str = ""
    # Families whose exclusion depends on rules the preflight cannot read or order.
    unverified_excludes: list[str] = field(default_factory=list)


@dataclass
class _RsyncArgs:
    positional: list[str] = field(default_factory=list)
    # Ordered filter rules: (kind, pattern). kind is exclude, include, exclude-file,
    # rules-file (may include), or other (neither protects nor re-includes).
    rules: list[tuple[str, str]] = field(default_factory=list)
    delete: bool = False
    delete_excluded: bool = False
    remove_source: bool = False


def _split(command: str) -> list[str]:
    """Tokenize shell text, keeping control operators as separate tokens."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _segments(tokens: list[str]) -> list[list[str]]:
    """Split tokens into simple commands and drop redirections."""
    segments: list[list[str]] = [[]]
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _COMMAND_SEPARATORS:
            segments.append([])
        elif tok in _REDIRECTIONS:
            current = segments[-1]
            if current and current[-1].isdigit():
                current.pop()  # file-descriptor prefix of "2>&1"
            i += 1  # the redirection target
        else:
            segments[-1].append(tok)
        i += 1
    return [segment for segment in segments if segment]


def _filter_rule(rule: str) -> tuple[str, str]:
    """Classify one rsync filter rule ("- palace/", "exclude,/ x", "merge f", ...).

    Returns (kind, pattern). A rule the preflight cannot interpret is a rules-file:
    it may include or exclude, so it makes coverage unverifiable rather than OK.
    """
    match = re.match(r"^(\S+?)(?:[ _](.*))?$", rule.strip())
    if match is None:
        return "rules-file", rule
    head, argument = match.group(1), match.group(2) or ""
    if head[0] in "-+.:HSPR!":
        name, modifiers = head[0], head[1:]
    else:
        name, _, modifiers = head.partition(",")
    name = _LONG_RULE_NAMES.get(name, name)
    if name == "!":
        return "clear", ""
    if name == "-":
        # A plain (optionally anchored or perishable) exclude protects both sides.
        return ("exclude" if set(modifiers) <= {"/", "p"} else "rules-file"), argument
    if name in {"+", "S", "R"}:
        return "include", argument
    if name in {"H", "P"}:
        # Hide is sender-only and protect keeps receiver files but still overwrites them.
        return "other", argument
    return "rules-file", argument


def _parse_rsync(argv: list[str]) -> _RsyncArgs:
    parsed = _RsyncArgs()
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            parsed.positional.extend(argv[i + 1 :])
            break
        if tok.startswith("--"):
            name, eq, value = tok.partition("=")
            if name in RSYNC_DELETE_FLAGS:
                parsed.delete = True
                parsed.delete_excluded |= name == "--delete-excluded"
            elif name in RSYNC_REMOVE_SOURCE_FLAGS:
                parsed.remove_source = True
            elif name in _RSYNC_RULE_OPTIONS or name in _RSYNC_LONG_WITH_VALUE:
                if not eq and i + 1 < len(argv):
                    i += 1
                    value = argv[i]
                if name == "--exclude":
                    parsed.rules.append(("exclude", value))
                elif name == "--include":
                    parsed.rules.append(("include", value))
                elif name == "--filter":
                    parsed.rules.append(_filter_rule(value))
                elif name == "--exclude-from":
                    parsed.rules.append(("exclude-file", value))
                elif name == "--include-from":
                    parsed.rules.append(("rules-file", value))
        elif tok.startswith("-") and len(tok) > 1:
            chars = tok[1:]
            for j, char in enumerate(chars):
                if char == "F":
                    parsed.rules.append(("rules-file", ".rsync-filter"))
                elif char in _RSYNC_SHORT_WITH_VALUE:
                    value = chars[j + 1 :]
                    if not value and i + 1 < len(argv):
                        i += 1
                        value = argv[i]
                    if char == "f":
                        parsed.rules.append(_filter_rule(value))
                    break
        else:
            parsed.positional.append(tok)
        i += 1
    return parsed


def _active_rules(rules: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Rules after the last clear ('!') rule, which voids everything before it."""
    last_clear = max((i for i, (kind, _) in enumerate(rules) if kind == "clear"), default=-1)
    return rules[last_clear + 1 :]


def _coverage(rules: list[tuple[str, str]], covers) -> str:
    """Return covered, unverified, or missing for one protected family.

    rsync applies the first matching rule, so an include or unread rules file before
    the covering exclude may re-include the family.
    """
    barrier = False
    for kind, pattern in rules:
        if kind in {"include", "rules-file"}:
            barrier = True
        elif kind == "exclude" and covers(pattern):
            return "unverified" if barrier else "covered"
    if any(kind in {"exclude-file", "rules-file"} for kind, _ in rules):
        return "unverified"
    return "missing"


def _exclude_covers_path(pattern: str, relative_parts: tuple[str, ...]) -> bool:
    """Whether an rsync exclude pattern excludes the given transfer-relative path."""
    anchored = pattern.startswith("/")
    normalized = pattern.strip("/")
    for suffix in ("/***", "/**", "/*"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    if not normalized:
        return anchored  # "/" or "/***" excludes the whole transfer
    pattern_parts = tuple(normalized.split("/"))
    for end in range(1, len(relative_parts) + 1):
        prefix = relative_parts[:end]
        if anchored or len(pattern_parts) > 1:
            candidates = [prefix] if anchored else [prefix[-len(pattern_parts) :]]
        else:
            candidates = [prefix[-1:]]
        for candidate in candidates:
            if len(candidate) == len(pattern_parts) and all(
                fnmatch.fnmatchcase(part, glob) for part, glob in zip(candidate, pattern_parts)
            ):
                return True
    return False


def _local_path(argument: str) -> tuple[str, bool] | None:
    """Return (absolute path, trailing slash) for a local or remote-absolute path arg."""
    if argument.startswith("rsync://") or "::" in argument:
        return None
    path = argument
    head, colon, tail = argument.partition(":")
    if colon and "/" not in head:
        # host:path — compare only an absolute remote path with local palace paths.
        if not tail.startswith("/"):
            return None
        path = tail
    else:
        path = os.path.realpath(os.path.expandvars(os.path.expanduser(argument)))
    trailing = argument.endswith("/")
    return os.path.normpath(path), trailing


def _palace_exposure(argument: str, palace: str) -> tuple[str, ...] | None:
    """Transfer-relative parts of the palace inside this path arg; () when uncoverable."""
    resolved = _local_path(argument)
    if resolved is None:
        return None
    path, trailing = resolved
    palace_path = PurePosixPath(os.path.normpath(palace))
    arg_path = PurePosixPath(path)
    if arg_path == palace_path or palace_path in arg_path.parents:
        return () if trailing or arg_path != palace_path else (palace_path.name,)
    if arg_path in palace_path.parents:
        root = arg_path if trailing else arg_path.parent
        return palace_path.relative_to(root).parts
    return None


def _state_dir() -> str:
    return os.path.normpath(os.path.expanduser("~/.mempalace"))


def _classify_rsync(argv: list[str], palace_paths: Sequence[str]) -> PreflightResult:
    parsed = _parse_rsync(argv)
    if not parsed.delete and not parsed.remove_source:
        return PreflightResult(ok=True)

    positional = parsed.positional
    sources = positional[:-1] if len(positional) > 1 else positional
    state_args = [arg for arg in positional if _MEMPALACE_STATE_RE.search(arg)]
    state_dir = _state_dir()
    # A parent of the state directory (for example ~/) mirrors it too; its excludes are
    # written relative to that parent (for example /.mempalace/backups/).
    state_parents: list[tuple[str, tuple[str, ...]]] = []
    for arg in positional:
        if arg in state_args:
            continue
        # Path arguments are resolved, so compare with the resolved state directory too.
        parts = _palace_exposure(arg, state_dir) or _palace_exposure(
            arg, os.path.realpath(state_dir)
        )
        if parts:
            state_parents.append((arg, parts))
    exposures: list[tuple[str, str, tuple[str, ...]]] = []
    palaces = [os.path.normpath(os.path.expanduser(p)) for p in palace_paths if p]
    palaces += [os.path.realpath(p) for p in palaces]
    for palace in dict.fromkeys(palaces):
        if (state_args or state_parents) and PurePosixPath(state_dir) in PurePosixPath(
            palace
        ).parents:
            continue  # the state-dir families already cover a palace inside it
        for arg in positional:
            parts = _palace_exposure(arg, palace)
            if parts is not None:
                exposures.append((arg, palace, parts))
    if not state_args and not state_parents and not exposures:
        return PreflightResult(ok=True)

    if parsed.remove_source and (
        any(arg in sources for arg in state_args)
        or any(arg in sources for arg, _ in state_parents)
        or any(arg in sources for arg, _, _ in exposures)
    ):
        return PreflightResult(
            ok=False,
            dangerous=True,
            pattern_id=REMOVE_SOURCE_PATTERN_ID,
            warnings=[
                "--remove-source-files deletes the local MemPalace files after they are "
                "sent; use `mempalace-code backup create` or export/import instead"
            ],
        )
    if not parsed.delete:
        return PreflightResult(ok=True)

    # --delete-excluded removes destination-side files matched by --exclude, so
    # required excludes cannot protect palace data regardless of coverage.
    if parsed.delete_excluded:
        return PreflightResult(
            ok=False,
            dangerous=True,
            pattern_id=DELETE_EXCLUDED_PATTERN_ID,
            warnings=[
                "--delete-excluded removes destination-side files matched by --exclude; "
                "no exclude list can protect palace data — use --delete and exclude all MemPalace families"
            ],
        )

    rules = _active_rules(parsed.rules)
    missing: list[str] = []
    unverified: list[str] = []
    warnings: list[str] = []

    def note(family: str, status: str) -> None:
        if status == "missing" and family not in missing:
            missing.append(family)
        elif status == "unverified" and family not in unverified:
            unverified.append(family)

    if state_args:
        for family, pattern in _FAMILY_MATCHERS.items():
            note(family, _coverage(rules, pattern.match))
        for family, sample in _COPY_FAMILY_SAMPLES.items():
            note(
                family,
                _coverage(
                    rules,
                    lambda value, sample=sample: (
                        _exclude_covers_path(value, (sample,))
                        or _exclude_covers_path(value, (".mempalace", sample))
                    ),
                ),
            )
    for _arg, parts in state_parents:
        for family, sample in _FAMILY_SAMPLES.items():
            note(
                family,
                _coverage(
                    rules,
                    lambda value, path=(*parts, sample): _exclude_covers_path(value, path),
                ),
            )
    if state_args or state_parents:
        excludes = [value for kind, value in rules if kind == "exclude"]
        for family, (pattern, hint) in _ADVISORY_MATCHERS.items():
            if not any(pattern.match(value) for value in excludes):
                warnings.append(f"advisory: no --exclude for '{family}' ({hint})")

    palace_missing = False
    for arg, palace, parts in exposures:
        status = (
            "missing"
            if not parts
            else _coverage(rules, lambda value, parts=parts: _exclude_covers_path(value, parts))
        )
        if status == "covered":
            continue
        where = "is inside" if not parts else "contains"
        warnings.append(
            f"{arg} {where} the configured palace {palace}; a delete-mode mirror removes "
            "palace content the other side holds"
            + ("" if not parts else f" (exclude it with --exclude='/{'/'.join(parts)}/')")
        )
        if status == "missing":
            palace_missing = True
        elif "palace" not in unverified:
            unverified.append("palace")
    if palace_missing and "palace" not in missing:
        missing.append("palace")
    if unverified:
        warnings.append(
            "rules from --exclude-from/--include-from/merge files, include rules, or "
            "an exclude placed after them cannot be verified; list the exclusions as "
            "plain --exclude options before any include rule"
        )

    if missing:
        return PreflightResult(
            ok=False,
            dangerous=True,
            pattern_id=(DANGEROUS_PATTERN_ID if state_args or state_parents else PALACE_PATTERN_ID),
            missing_excludes=missing,
            unverified_excludes=unverified,
            warnings=warnings,
        )
    if unverified:
        return PreflightResult(
            ok=False,
            pattern_id=UNVERIFIABLE_FILTER_PATTERN_ID,
            unverified_excludes=unverified,
            warnings=warnings,
        )
    return PreflightResult(ok=True, warnings=warnings)


def _is_env_assignment(tok: str) -> bool:
    """Return True if tok is a shell-style NAME=value environment variable assignment."""
    eq = tok.find("=")
    if eq <= 0:
        return False
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", tok[:eq]))


def _skip_wrapper_flags(
    tokens: list[str], i: int, no_arg: frozenset[str], one_arg: frozenset[str]
) -> int:
    """Advance i past known wrapper option flags, stopping at '--' (consumed) or a non-option.

    In addition to canonical separated forms (-n, --non-interactive, --user=root),
    handles compact short-option bundles (-nE) and argument-attached forms (-uroot).
    """
    no_arg_chars: frozenset[str] = frozenset(
        k[1] for k in no_arg if len(k) == 2 and k[0] == "-" and k[1] != "-"
    )
    one_arg_chars: frozenset[str] = frozenset(
        k[1] for k in one_arg if len(k) == 2 and k[0] == "-" and k[1] != "-"
    )

    while i < len(tokens):
        tok = tokens[i]
        if tok == "--":
            return i + 1
        if tok in no_arg:
            i += 1
        elif tok in one_arg:
            i += 2
        elif tok.startswith("--") and "=" in tok:
            i += 1  # --flag=value form
        elif tok.startswith("-") and not tok.startswith("--") and len(tok) > 2:
            # Compact short-option bundle: each char must be a recognised no-arg or
            # one-arg flag; an unrecognised char means the token is not a wrapper option.
            chars = tok[1:]
            j = 0
            valid = True
            consumed_next = False
            while j < len(chars):
                c = chars[j]
                if c in no_arg_chars:
                    j += 1
                elif c in one_arg_chars:
                    # Remaining chars are the attached value; a final char takes the next token.
                    if j == len(chars) - 1:
                        consumed_next = True
                    break
                else:
                    valid = False
                    break
            if valid:
                i += 1
                if consumed_next:
                    i += 1
            else:
                break
        else:
            break
    return i


def _unwrap(tokens: list[str]) -> list[str]:
    """Resolve sudo/env prefixes and transparent runners to the effective argv.

    Returns the tokens unchanged when the first token is neither rsync nor a supported
    wrapper; the caller checks whether the result starts with rsync.
    """
    if not tokens:
        return tokens
    basename = tokens[0].split("/")[-1]
    if basename == "sudo":
        return _unwrap(
            tokens[_skip_wrapper_flags(tokens, 1, _SUDO_FLAGS_NO_ARG, _SUDO_FLAGS_ONE_ARG) :]
        )
    if basename == "env":
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok == "--":
                i += 1
                break
            if tok in _ENV_FLAGS_NO_ARG:
                i += 1
            elif tok in _ENV_FLAGS_ONE_ARG:
                i += 2
            elif (tok.startswith("--") and "=" in tok) or _is_env_assignment(tok):
                i += 1
            else:
                break
        return _unwrap(tokens[i:])
    if basename in _TRANSPARENT_RUNNERS:
        for index, tok in enumerate(tokens[1:], 1):
            if tok.split("/")[-1] == "rsync":
                return tokens[index:]
    return tokens


# Local path prefixes that an earlier command's `cd` cannot redirect.
_ANCHORED_PREFIXES = ("/", "~", "$HOME", "${HOME}")


def _independent_of_earlier_commands(argv: list[str], earlier: list[list[str]]) -> bool:
    """Whether an rsync after other commands is classified correctly by its arguments alone.

    Without delete or source-removal semantics the verdict does not depend on paths.
    Otherwise every local path must be anchored, and no earlier command may assign HOME.
    """
    parsed = _parse_rsync(argv)
    if not parsed.delete and not parsed.remove_source:
        return True
    if any("HOME=" in tok for segment in earlier for tok in segment):
        return False
    for arg in parsed.positional:
        if arg.startswith("rsync://") or "::" in arg:
            continue
        head, colon, _ = arg.partition(":")
        if colon and "/" not in head:
            continue  # host:path resolves on the remote side, not in the local cwd
        if not arg.startswith(_ANCHORED_PREFIXES):
            return False
    return True


def _classify_tokens(
    tokens: list[str],
    palace_paths: Sequence[str],
    depth: int,
    earlier: Sequence[list[str]] = (),
) -> PreflightResult:
    """Classify shell tokens; ``earlier`` holds commands that ran before them."""
    rsync_results: list[tuple[int, PreflightResult]] = []
    unverifiable_later_rsync = False
    segments = _segments(tokens)
    for index, segment in enumerate(segments):
        before = [*earlier, *segments[:index]]
        effective = _unwrap(segment)
        if not effective:
            return PreflightResult(ok=False, parse_error="empty command after wrapper resolution")
        basename = effective[0].split("/")[-1]
        if basename in _SHELL_BASENAMES and len(effective) >= 3 and effective[1] == "-c":
            if depth >= 3:
                return PreflightResult(ok=False, parse_error="shell -c nesting is too deep")
            try:
                inner = _split(effective[2])
            except ValueError as exc:
                return PreflightResult(ok=False, parse_error=str(exc))
            if not inner:
                return PreflightResult(
                    ok=False, parse_error="empty command after wrapper resolution"
                )
            result = _classify_tokens(inner, palace_paths, depth + 1, before)
            if result.parse_error:
                return result
            if result.ok and not result.warnings:
                continue
            rsync_results.append((index, result))
        elif basename == "rsync":
            rsync_results.append((index, _classify_rsync(effective, palace_paths)))
            if before and not _independent_of_earlier_commands(effective, before):
                unverifiable_later_rsync = True
    for _, result in rsync_results:
        if result.dangerous:
            return result
    if unverifiable_later_rsync:
        return PreflightResult(
            ok=False,
            pattern_id=UNVERIFIABLE_COMPOUND_PATTERN_ID,
            warnings=[
                "rsync runs after another command (for example cd) in a compound command, "
                "so its paths and environment cannot be verified; preflight the rsync "
                "command alone with absolute paths"
            ],
        )
    for _, result in rsync_results:
        if not result.ok:
            return result
    warnings = [warning for _, result in rsync_results for warning in result.warnings]
    return PreflightResult(ok=True, warnings=warnings)


def classify_mirror_command(command: str, palace_paths: Sequence[str] = ()) -> PreflightResult:
    """
    Parse and classify an rsync command string without executing it.

    ``palace_paths`` are the configured palace directories (a palace outside
    ``~/.mempalace`` is still palace state). Returns PreflightResult with:
    - ok=True  when the command is safe or not a MemPalace delete-mode mirror.
    - ok=False, dangerous=True when it is a MemPalace delete-mode (or
      --remove-source-files) mirror with missing required excludes; missing_excludes
      lists the absent families.
    - ok=False, dangerous=False when the verdict depends on rules the preflight
      cannot read (exclude files, include ordering) or on a compound shell command;
      unverified_excludes lists the affected families.
    - ok=False, parse_error set when the shell text cannot be tokenized.
    """
    try:
        tokens = _split(command)
    except ValueError as exc:
        return PreflightResult(ok=False, parse_error=str(exc))
    if not tokens:
        return PreflightResult(ok=False, parse_error="empty command")
    return _classify_tokens(tokens, palace_paths, 0)
