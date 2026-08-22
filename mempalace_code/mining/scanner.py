"""mining.scanner — Project filesystem scan: gitignore, skip rules, file discovery."""

from __future__ import annotations

import fnmatch
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, NamedTuple, TypeAlias, TypedDict

from ..config import MempalaceConfig
from ..language_catalog import known_filenames, readable_extensions
from ..source_io import (
    is_regular_source_path,
    read_regular_bytes,
    read_regular_text,
    regular_source_diagnostic,
)

KNOWN_FILENAMES: set[str] = known_filenames()
READABLE_EXTENSIONS: set[str] = readable_extensions()

SKIP_DIRS: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    "coverage",
    ".mempalace",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".cache",
    ".tox",
    ".nox",
    ".vs",
    "obj",
    "vendor",
    ".idea",
    ".vscode",
    ".ipynb_checkpoints",
    ".eggs",
    "htmlcov",
    "target",
    ".terraform",
}

SKIP_FILENAMES: set[str] = {
    "mempalace.yaml",
    "mempalace.yml",
    "mempal.yaml",
    "mempal.yml",
    ".gitignore",
    "package-lock.json",
    "entities.json",
}


# =============================================================================
# IGNORE MATCHING
# =============================================================================


class GitignoreRule(TypedDict):
    """One parsed .gitignore line."""

    pattern: str
    anchored: bool
    dir_only: bool
    negated: bool


class GitignoreMatcher:
    """Lightweight matcher for one directory's .gitignore patterns."""

    def __init__(self, base_dir: Path, rules: list[GitignoreRule]) -> None:
        self.base_dir = base_dir
        self.rules = rules

    @classmethod
    def from_dir(cls, dir_path: Path) -> GitignoreMatcher | None:
        gitignore_path = dir_path / ".gitignore"
        if not gitignore_path.is_file():
            return None

        try:
            lines = read_regular_text(
                gitignore_path, encoding="utf-8", errors="replace"
            ).splitlines()
        except Exception:
            return None

        rules: list[GitignoreRule] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("\\#") or line.startswith("\\!"):
                line = line[1:]
            elif line.startswith("#"):
                continue

            negated = line.startswith("!")
            if negated:
                line = line[1:]

            anchored = line.startswith("/")
            if anchored:
                line = line.lstrip("/")

            dir_only = line.endswith("/")
            if dir_only:
                line = line.rstrip("/")

            if not line:
                continue

            rules.append(
                {
                    "pattern": line,
                    "anchored": anchored,
                    "dir_only": dir_only,
                    "negated": negated,
                }
            )

        if not rules:
            return None

        return cls(dir_path, rules)

    def matches(self, path: Path, is_dir: bool | None = None) -> bool | None:
        try:
            relative = path.relative_to(self.base_dir).as_posix().strip("/")
        except ValueError:
            return None

        if not relative:
            return None

        if is_dir is None:
            is_dir = path.is_dir()

        ignored: bool | None = None
        for rule in self.rules:
            if self._rule_matches(rule, relative, is_dir):
                ignored = not rule["negated"]
        return ignored

    def _rule_matches(self, rule: GitignoreRule, relative: str, is_dir: bool) -> bool:
        pattern = rule["pattern"]
        parts = relative.split("/")
        pattern_parts = pattern.split("/")

        if rule["dir_only"]:
            target_parts = parts if is_dir else parts[:-1]
            if not target_parts:
                return False
            if rule["anchored"] or len(pattern_parts) > 1:
                return self._match_from_root(target_parts, pattern_parts)
            return any(fnmatch.fnmatch(part, pattern) for part in target_parts)

        if rule["anchored"] or len(pattern_parts) > 1:
            return self._match_from_root(parts, pattern_parts)

        return any(fnmatch.fnmatch(part, pattern) for part in parts)

    def _match_from_root(self, target_parts: list[str], pattern_parts: list[str]) -> bool:
        def matches(path_index: int, pattern_index: int) -> bool:
            if pattern_index == len(pattern_parts):
                return True

            if path_index == len(target_parts):
                return all(part == "**" for part in pattern_parts[pattern_index:])

            pattern_part = pattern_parts[pattern_index]
            if pattern_part == "**":
                return matches(path_index, pattern_index + 1) or matches(
                    path_index + 1, pattern_index
                )

            if not fnmatch.fnmatch(target_parts[path_index], pattern_part):
                return False

            return matches(path_index + 1, pattern_index + 1)

        return matches(0, 0)


GitignoreMatcherCache: TypeAlias = dict[Path, GitignoreMatcher | None]


def load_gitignore_matcher(dir_path: Path, cache: GitignoreMatcherCache) -> GitignoreMatcher | None:
    """Load and cache one directory's .gitignore matcher."""
    if dir_path not in cache:
        cache[dir_path] = GitignoreMatcher.from_dir(dir_path)
    return cache[dir_path]


def is_gitignored(path: Path, matchers: list[GitignoreMatcher], is_dir: bool = False) -> bool:
    """Apply active .gitignore matchers in ancestor order; last match wins."""
    ignored = False
    for matcher in matchers:
        decision = matcher.matches(path, is_dir=is_dir)
        if decision is not None:
            ignored = decision
    return ignored


_DOTNET_MARKERS: tuple[str, ...] = (
    "*.sln",
    "*.csproj",
    "*.fsproj",
    "*.vbproj",
    "*/*.csproj",
    "*/*.fsproj",
    "*/*.vbproj",
)


def _is_dotnet_project(project_path: Path) -> bool:
    """Return True if *project_path* looks like a .NET project.

    Checks for .sln at root level and .csproj/.fsproj/.vbproj at root or one
    level deep (the standard layout: Solution.sln at root, Project/Project.csproj
    in a subdirectory).  Uses early-exit to minimise filesystem round-trips.
    """
    return any(
        any(is_regular_source_path(candidate) for candidate in project_path.glob(pat))
        for pat in _DOTNET_MARKERS
    )


def should_skip_dir(dirname: str) -> bool:
    """Skip known generated/cache directories before gitignore matching."""
    return dirname in SKIP_DIRS or dirname.endswith(".egg-info")


IncludePaths: TypeAlias = Iterable[str]


def normalize_include_paths(include_ignored: IncludePaths | None) -> set[str]:
    """Normalize comma-parsed include paths into project-relative POSIX strings."""
    normalized: set[str] = set()
    for raw_path in include_ignored or []:
        candidate = str(raw_path).strip().strip("/")
        if candidate:
            normalized.add(Path(candidate).as_posix())
    return normalized


def is_exact_force_include(path: Path, project_path: Path, include_paths: set[str]) -> bool:
    """Return True when a path exactly matches an explicit include override."""
    if not include_paths:
        return False

    try:
        relative = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False

    return relative in include_paths


def is_force_included(path: Path, project_path: Path, include_paths: set[str]) -> bool:
    """Return True when a path or one of its ancestors/descendants was explicitly included."""
    if not include_paths:
        return False

    try:
        relative = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False

    if not relative:
        return False

    for include_path in include_paths:
        if relative == include_path:
            return True
        if relative.startswith(f"{include_path}/"):
            return True
        if include_path.startswith(f"{relative}/"):
            return True

    return False


def normalize_hard_exclude_dirs(hard_exclude_dirs: Iterable[str | Path] | None) -> tuple[Path, ...]:
    """Normalize absolute directory paths that must never be scanned."""
    normalized: list[Path] = []
    for raw_path in hard_exclude_dirs or []:
        try:
            normalized.append(Path(raw_path).expanduser().resolve())
        except OSError:
            continue
    return tuple(normalized)


def is_hard_excluded_dir(path: Path, hard_exclude_dirs: tuple[Path, ...]) -> bool:
    """Return True when path is a hard-excluded dir or nested below one."""
    if not hard_exclude_dirs:
        return False
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser().absolute()
    return any(resolved == exclude or exclude in resolved.parents for exclude in hard_exclude_dirs)


# =============================================================================
# APP-LEVEL SCAN FILTER RULES
# =============================================================================


class ScanFilterRules(NamedTuple):
    """Immutable app-level scan exclusion rules loaded from ~/.mempalace/config.json."""

    skip_dirs: frozenset[str]  # directory basenames to exclude
    skip_files: frozenset[str]  # file basenames to exclude
    skip_globs: list[str]  # project-relative POSIX glob patterns to exclude


def get_scan_filter_rules(config: MempalaceConfig | None = None) -> ScanFilterRules:
    """Return ScanFilterRules from app config (or defaults when config is None)."""
    if config is None:
        config = MempalaceConfig()
    return ScanFilterRules(
        skip_dirs=frozenset(config.scan_skip_dirs),
        skip_files=frozenset(config.scan_skip_files),
        skip_globs=list(config.scan_skip_globs),
    )


def _glob_match(rel_posix: str, pattern: str) -> bool:
    """Match a project-relative POSIX path against a glob pattern.

    Supports ** as a zero-or-more-segments wildcard, matching both direct children
    and deeper descendants (e.g. ``generated/**/*.js`` matches ``generated/bundle.js``
    and ``generated/sub/bundle.js``).
    """
    if fnmatch.fnmatch(rel_posix, pattern):
        return True
    if "**" not in pattern:
        return False
    # Also try treating **/ as matching zero segments (direct children)
    alt = pattern.replace("**/", "")
    return bool(alt != pattern and fnmatch.fnmatch(rel_posix, alt))


def is_scan_excluded(
    path: Path, project_path: Path, rules: ScanFilterRules, is_dir: bool = False
) -> bool:
    """Return True when path matches an app-level scan exclusion rule.

    Directories are matched by basename only. Files are matched by basename, then
    by project-relative POSIX glob patterns. Force-include precedence is the
    caller's responsibility.
    """
    name = path.name
    if is_dir:
        if name in rules.skip_dirs:
            return True
    else:
        if name in rules.skip_files:
            return True
    if rules.skip_globs:
        try:
            rel_posix = path.relative_to(project_path).as_posix()
        except ValueError:
            return False
        for pattern in rules.skip_globs:
            if _glob_match(rel_posix, pattern):
                return True
    return False


def _subtree_glob_prefix(pattern: str) -> str | None:
    """Return the literal directory prefix if *pattern* covers an entire subtree, else None.

    A pattern covers a whole subtree when:
      1. Every segment at and after the first ``**`` is either ``**`` or a bare ``*``
         (no extension, no character class, no literal suffix), AND
      2. Every segment **before** the first ``**`` is a literal path segment with no
         glob meta-characters (``*``, ``?``, ``[``).

    Examples that return a prefix: ``build/**`` → ``"build"``, ``generated/**/*`` → ``"generated"``,
    ``src/gen/**`` → ``"src/gen"``, ``**`` → ``""``.
    Examples that return None: ``generated/**/*.js``, ``**/*.py``, ``**/bundle.*``,
    ``*.egg-info/**`` (wildcard in prefix), ``*/build/**`` (wildcard in prefix).
    """
    parts = pattern.split("/")
    if "**" not in parts:
        return None
    star_idx = parts.index("**")
    for part in parts[star_idx:]:
        if part not in ("**", "*"):
            return None
    # Prefix must be entirely literal — startswith() can't match glob wildcards.
    # When wildcards appear in the prefix, fall back to per-file glob matching.
    for part in parts[:star_idx]:
        if any(ch in part for ch in "*?["):
            return None
    return "/".join(parts[:star_idx]).strip("/")


SymlinkSkipReason: TypeAlias = Literal["dangling", "not-a-file", "unreadable", "not a regular file"]


class SymlinkDiagnostic(TypedDict):
    """One dropped source-file symlink, recorded when skip_invalid_source_symlinks is on."""

    path: str
    reason: SymlinkSkipReason


def invalid_source_symlink_reason(path: Path) -> SymlinkSkipReason | None:
    """Return a reason string when *path* is a symlinked source file that fails the guard.

    Returns None for non-symlinks and for symlinks that resolve to a readable file.
    Otherwise returns one of ``"dangling"`` (missing target), ``"not-a-file"``
    (target is a directory or other non-file), or ``"unreadable"`` (target exists
    and is a file but cannot be opened for a small read).
    """
    if not path.is_symlink():
        return None
    try:
        if not path.exists():
            return "dangling"
        if not is_regular_source_path(path):
            return "not-a-file"
        read_regular_bytes(path, max_bytes=1)
    except OSError:
        return "unreadable"
    return None


def _record_non_regular_source(path: Path, diagnostics: list[SymlinkDiagnostic] | None) -> None:
    message = regular_source_diagnostic(path)
    if diagnostics is not None:
        diagnostics.append({"path": str(path), "reason": "not a regular file"})
    else:
        print(message, file=sys.stderr)


def is_dir_subtree_excluded(dir_path: Path, project_path: Path, rules: ScanFilterRules) -> bool:
    """Return True if *dir_path* is fully covered by a subtree skip glob.

    Only unambiguous whole-subtree patterns (e.g. ``build/**``, ``generated/**/*``) are
    eligible. File-specific patterns like ``generated/**/*.js`` are not, and continue to
    be evaluated per-file via ``is_scan_excluded``.
    """
    if not rules.skip_globs:
        return False
    try:
        rel = dir_path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False
    for pattern in rules.skip_globs:
        prefix = _subtree_glob_prefix(pattern)
        if prefix is None:
            continue
        # Empty prefix means the pattern covers the entire project tree.
        if not prefix or rel == prefix or rel.startswith(f"{prefix}/"):
            return True
    return False


# =============================================================================
# SCAN PROJECT
# =============================================================================


def scan_project(
    project_dir: str,
    respect_gitignore: bool = True,
    include_ignored: IncludePaths | None = None,
    scan_rules: ScanFilterRules | None = None,
    hard_exclude_dirs: Iterable[str | Path] | None = None,
    skip_invalid_source_symlinks: bool = False,
    symlink_diagnostics: list[SymlinkDiagnostic] | None = None,
) -> list[Path]:
    """Return list of all readable file paths.

    When *skip_invalid_source_symlinks* is True (opt-in, default disabled), a selected
    source-file symlink is dropped when its target is missing, is not a file, or cannot
    be read through the symlink path. Valid symlinks keep their symlink path (not resolved
    to their target) and regular files are never affected by this guard. When
    *symlink_diagnostics* is provided, each dropped symlink appends a
    ``{"path": str, "reason": str}`` entry.
    """
    project_path = Path(project_dir).expanduser().resolve()
    hard_exclude_paths = normalize_hard_exclude_dirs(hard_exclude_dirs)
    if is_hard_excluded_dir(project_path, hard_exclude_paths):
        return []

    files: list[Path] = []
    active_matchers: list[GitignoreMatcher] = []
    matcher_cache: GitignoreMatcherCache = {}
    include_paths = normalize_include_paths(include_ignored)
    dotnet_project = _is_dotnet_project(project_path)

    if scan_rules is None:
        scan_rules = get_scan_filter_rules()

    for root, dirs, filenames in os.walk(project_path):
        root_path = Path(root)

        if respect_gitignore:
            active_matchers = [
                matcher
                for matcher in active_matchers
                if root_path == matcher.base_dir or matcher.base_dir in root_path.parents
            ]
            current_matcher = load_gitignore_matcher(root_path, matcher_cache)
            if current_matcher is not None:
                active_matchers.append(current_matcher)

        dirs[:] = [
            d
            for d in dirs
            if not is_hard_excluded_dir(root_path / d, hard_exclude_paths)
            and (
                is_force_included(root_path / d, project_path, include_paths)
                or not (
                    should_skip_dir(d)
                    or (dotnet_project and d == "bin")
                    or is_scan_excluded(root_path / d, project_path, scan_rules, is_dir=True)
                    or is_dir_subtree_excluded(root_path / d, project_path, scan_rules)
                )
            )
        ]
        if respect_gitignore and active_matchers:
            dirs[:] = [
                d
                for d in dirs
                if not is_hard_excluded_dir(root_path / d, hard_exclude_paths)
                and (
                    is_force_included(root_path / d, project_path, include_paths)
                    or not is_gitignored(root_path / d, active_matchers, is_dir=True)
                )
            ]

        for filename in filenames:
            filepath = root_path / filename
            if is_hard_excluded_dir(filepath.parent, hard_exclude_paths):
                continue
            force_include = is_force_included(filepath, project_path, include_paths)
            exact_force_include = is_exact_force_include(filepath, project_path, include_paths)

            if not force_include and filename in SKIP_FILENAMES:
                continue
            if not force_include and is_scan_excluded(filepath, project_path, scan_rules):
                continue
            if filepath.suffix.lower() not in READABLE_EXTENSIONS and not exact_force_include:
                if filename not in KNOWN_FILENAMES:
                    continue
            if respect_gitignore and active_matchers and not force_include:
                if is_gitignored(filepath, active_matchers, is_dir=False):
                    continue
            if skip_invalid_source_symlinks:
                reason = invalid_source_symlink_reason(filepath)
                if reason is not None:
                    if symlink_diagnostics is not None:
                        symlink_diagnostics.append({"path": str(filepath), "reason": reason})
                    continue
            if not is_regular_source_path(filepath):
                _record_non_regular_source(filepath, symlink_diagnostics)
                continue
            files.append(filepath)
    return files
