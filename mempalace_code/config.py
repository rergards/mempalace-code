"""
MemPalace configuration system.

Priority: env vars > config file (~/.mempalace/config.json) > defaults
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_T = TypeVar("_T")

# Raw JSON payload boundary: config.json / people_map.json decode to this shape once.
# scan_skip_* properties normalize via _normalize_scan_list, and *_enabled-style
# properties normalize via parse_optional_bool. people_map, topic_wings, and
# hall_keywords instead return this Any-typed payload cast to a
# narrower annotation with no runtime check — a malformed config.json can produce
# a value that mismatches the annotation undetected by strict Pyright.
ConfigPayload: TypeAlias = dict[str, Any]
PeopleMap: TypeAlias = dict[str, str]
HallKeywords: TypeAlias = dict[str, list[str]]
ScanSkipList: TypeAlias = list[str]

DEFAULT_PALACE_PATH = os.path.expanduser("~/.mempalace/palace")

# Storage safety defaults
DEFAULT_OPTIMIZE_AFTER_MINE = True  # Set False to disable auto-compaction
DEFAULT_BACKUP_BEFORE_OPTIMIZE = True  # Auto-backup before risky operations (on by default)
DEFAULT_BACKUP_RETAIN_COUNT = 0  # 0 keeps all backups per-kind (backwards compatible)
DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT = 5  # implicit bound for managed pre-optimize archives
DEFAULT_PRE_WATCH_RETAIN_COUNT = 5  # implicit bound for managed pre-watch archives
DEFAULT_SCHEDULED_RETAIN_COUNT = 14  # implicit bound for managed scheduled archives
DEFAULT_BACKUP_SCHEDULE = "off"  # Scheduled backup frequency: off|daily|weekly|hourly
DEFAULT_BACKUP_MIN_FREE_BYTES = (
    0  # 0 disables the disk-space guard; set e.g. 1_073_741_824 for 1 GiB
)
DEFAULT_BACKUP_WARN_SIZE_BYTES = (
    0  # 0 disables oversized-archive warnings; set e.g. 2_147_483_648 for 2 GiB
)
DEFAULT_SPELLCHECK_ENABLED = None  # compatibility only: unset means off; text stays verbatim
DEFAULT_ENTITY_DETECTION = False

# Version-check defaults
DEFAULT_VERSION_CHECK_ENABLED = None  # None = no choice (will prompt or stay disabled)
DEFAULT_VERSION_CHECK_INTERVAL_HOURS = 168  # 1 week

# Disk-budget safety defaults
DEFAULT_DISK_MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB

# Source label for retention when no explicit backup_retain_count is set.
_IMPLICIT_RETENTION_SOURCE = (
    "the per-kind retention defaults (pre_optimize 5, pre_watch 5, scheduled 14, others all)"
)

DEFAULT_SCAN_SKIP_DIRS: ScanSkipList = [".kotlin-lsp"]
DEFAULT_SCAN_SKIP_FILES: ScanSkipList = []
DEFAULT_SCAN_SKIP_GLOBS: ScanSkipList = []

DEFAULT_TOPIC_WINGS: list[str] = [
    "emotions",
    "consciousness",
    "memory",
    "technical",
    "identity",
    "family",
    "creative",
]

DEFAULT_HALL_KEYWORDS: HallKeywords = {
    "emotions": [
        "scared",
        "afraid",
        "worried",
        "happy",
        "sad",
        "love",
        "hate",
        "feel",
        "cry",
        "tears",
    ],
    "consciousness": [
        "consciousness",
        "conscious",
        "aware",
        "real",
        "genuine",
        "soul",
        "exist",
        "alive",
    ],
    "memory": ["memory", "remember", "forget", "recall", "archive", "palace", "store"],
    "technical": [
        "code",
        "python",
        "script",
        "bug",
        "error",
        "function",
        "api",
        "database",
        "server",
    ],
    "identity": ["identity", "name", "who am i", "persona", "self"],
    "family": ["family", "kids", "children", "daughter", "son", "parent", "mother", "father"],
    "creative": ["game", "gameplay", "player", "app", "design", "art", "music", "story"],
}


def expand_palace_path(path: str | os.PathLike[str]) -> str:
    """Return *path* with ``~`` expanded and made absolute.

    This is the one palace-path normalizer: the CLI ``--palace`` value, the
    ``MEMPALACE_PALACE_PATH`` environment variable, ``palace_path`` in
    config.json, and the public Python entry points all pass through it, so a
    literal ``~`` can never split one palace across two directories.
    """
    return os.path.abspath(os.path.expanduser(os.fspath(path)))


# config.json paths already reported as unreadable, so each process warns once per file.
_WARNED_UNREADABLE_CONFIGS: set[Path] = set()
# (setting, rejected value) pairs already reported, so each process warns once per value.
_WARNED_INVALID_SETTINGS: set[tuple[str, str]] = set()


def _warn_unreadable_config(path: Path, error: Exception | str) -> None:
    """Report an ignored config.json once instead of silently dropping every key in it."""
    if path in _WARNED_UNREADABLE_CONFIGS:
        return
    _WARNED_UNREADABLE_CONFIGS.add(path)
    print(
        f"Warning: ignoring {path} ({error}); using defaults and environment variables. "
        "Fix it as plain JSON without comments, or move it aside.",
        file=sys.stderr,
    )


def _json_type_name(value: object) -> str:
    """Name a decoded JSON value's type the way JSON does (null, array, string, ...)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def warn_invalid_setting(setting: str, value: object, reason: object, action: str) -> None:
    """Report one rejected env/config value on stderr, once per process.

    *setting* names the variable or config key, *reason* says why the value was
    rejected, and *action* says what is used instead.
    """
    shown = repr(value)
    if len(shown) > 80:
        shown = shown[:77] + "..."
    key = (setting, shown)
    if key in _WARNED_INVALID_SETTINGS:
        return
    _WARNED_INVALID_SETTINGS.add(key)
    print(f"Warning: ignoring {shown} for {setting} ({reason}); {action}.", file=sys.stderr)


def _configured_palace_path(value: str, setting: str, noun: str = "palace") -> str:
    """Resolve a configured palace path, warning once when it depends on the cwd.

    An explicit ``--palace`` argument is expected to be relative to the current
    directory; a relative value from the environment or config.json is not, because
    MCP clients and schedulers start commands from arbitrary directories.
    """
    resolved = expand_palace_path(value)
    if not os.path.isabs(os.path.expanduser(value)):
        key = (setting, f"relative:{value}")
        if key not in _WARNED_INVALID_SETTINGS:
            _WARNED_INVALID_SETTINGS.add(key)
            print(
                f"Warning: {setting} is the relative path {value!r}, so it resolves against "
                f"the current directory ({resolved}); commands started from another directory "
                f"select a different {noun}. Set an absolute path.",
                file=sys.stderr,
            )
    return resolved


def _resolve_setting(
    levels: list[tuple[str, object]],
    parse: Callable[[object], _T],
    fallback: Callable[[], tuple[_T, str]],
    describe: Callable[[_T], str] = str,
) -> tuple[_T, str]:
    """Return ``(value, source)`` from the first level whose raw value parses.

    *levels* lists ``(source label, raw value)`` pairs in precedence order; a raw
    value of None means "not set". A value that fails to parse is reported with
    :func:`warn_invalid_setting` and resolution continues with the next level, then
    with *fallback*, so a typo never silently replaces a lower-precedence setting
    with a hard-coded default.
    """
    rejected: list[tuple[str, object, Exception]] = []
    resolved: tuple[_T, str] | None = None
    for label, raw in levels:
        if raw is None:
            continue
        try:
            resolved = (parse(raw), label)
        except (TypeError, ValueError) as exc:
            rejected.append((label, raw, exc))
            continue
        break
    if resolved is None:
        resolved = fallback()
    described = describe(resolved[0])
    action = f"using {described} from {resolved[1]}" if described else f"using {resolved[1]}"
    for label, raw, exc in rejected:
        warn_invalid_setting(label, raw, exc, f"{action} instead")
    return resolved


def _parse_bytes_setting(raw: object) -> int:
    """Parse a byte count; JSON numbers such as ``1e13`` are accepted when integral."""
    from .disk_budget import parse_bytes

    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    return parse_bytes(raw)


def _parse_count_setting(raw: object, minimum: int) -> int:
    """Parse a whole number >= *minimum* from an int, integral float, or digit string."""
    if isinstance(raw, bool):
        raise ValueError("expected a whole number, got a boolean")
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("empty value")
        try:
            raw = int(text)
        except ValueError:
            raise ValueError("expected a whole number") from None
    if not isinstance(raw, int):
        raise ValueError(f"expected a whole number, got {type(raw).__name__}")
    if raw < minimum:
        raise ValueError(f"must be at least {minimum}")
    return raw


def _parse_bool_setting(raw: object) -> bool:
    """Parse a boolean spelling accepted by :func:`parse_optional_bool`, else raise."""
    parsed = parse_optional_bool(raw)
    if parsed is None:
        raise ValueError("expected 1/0, true/false, yes/no, or on/off")
    return parsed


def _format_byte_setting(value: int) -> str:
    from .disk_budget import format_bytes

    return format_bytes(value)


class MempalaceConfig:
    """Configuration manager for MemPalace.

    Load order: env vars > config file > defaults.
    """

    def __init__(self, config_dir: str | Path | None = None) -> None:
        """Initialize config.

        Args:
            config_dir: Override config directory (useful for testing).
                        Defaults to ~/.mempalace.
        """
        self._config_dir = (
            Path(config_dir) if config_dir else Path(os.path.expanduser("~/.mempalace"))
        )
        self._config_file = self._config_dir / "config.json"
        self._people_map_file = self._config_dir / "people_map.json"
        self._file_config: ConfigPayload = {}

        if self._config_file.exists():
            try:
                with open(self._config_file, "r") as f:
                    loaded: object = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                _warn_unreadable_config(self._config_file, exc)
            else:
                if isinstance(loaded, dict):
                    self._file_config = cast("ConfigPayload", loaded)
                else:
                    _warn_unreadable_config(
                        self._config_file,
                        f"top-level value must be a JSON object, got {_json_type_name(loaded)}",
                    )

    def _file_setting(self, key: str) -> tuple[str, object]:
        """Return the ``(source label, raw value)`` level for a config.json key."""
        return (f"{key} in {self._config_file}", self._file_config.get(key))

    @property
    def palace_path(self) -> str:
        """Absolute path to the memory palace data directory (``~`` expanded).

        Priority: MEMPALACE_PALACE_PATH env > legacy MEMPAL_PALACE_PATH env >
        palace_path file key > DEFAULT_PALACE_PATH. An empty env value counts as unset.
        """
        for name in ("MEMPALACE_PALACE_PATH", "MEMPAL_PALACE_PATH"):
            env_val = os.environ.get(name)
            if env_val and env_val.strip():
                return _configured_palace_path(env_val, name)
        raw = self._file_config.get("palace_path")
        if raw is None:
            return DEFAULT_PALACE_PATH
        if isinstance(raw, str) and raw.strip():
            return _configured_palace_path(raw, f"palace_path in {self._config_file}")
        warn_invalid_setting(
            f"palace_path in {self._config_file}",
            raw,
            "expected a non-empty path string",
            f"using the default palace {DEFAULT_PALACE_PATH} instead",
        )
        return DEFAULT_PALACE_PATH

    @property
    def people_map(self) -> PeopleMap:
        """Mapping of name variants to canonical names."""
        if self._people_map_file.exists():
            try:
                with open(self._people_map_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return self._file_config.get("people_map", {})

    @property
    def topic_wings(self) -> list[str]:
        """Legacy upstream topic wing names; no miner or search path reads them."""
        return self._file_config.get("topic_wings", DEFAULT_TOPIC_WINGS)

    @property
    def hall_keywords(self) -> HallKeywords:
        """Legacy upstream hall keyword map; no miner assigns halls from it.

        Kept for API compatibility. Only diary entries carry a ``hall`` value today.
        """
        return self._file_config.get("hall_keywords", DEFAULT_HALL_KEYWORDS)

    @property
    def optimize_after_mine(self) -> bool:
        """Whether to run optimize() after mining. Disable to prevent compaction corruption."""
        env_val = os.environ.get("MEMPALACE_OPTIMIZE_AFTER_MINE")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        return self._file_config.get("optimize_after_mine", DEFAULT_OPTIMIZE_AFTER_MINE)

    @property
    def backup_before_optimize(self) -> bool:
        """Whether to create a backup before optimize(). On by default.

        Priority: MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE env > MEMPALACE_BACKUP_BEFORE_OPTIMIZE env
                  > auto_backup_before_optimize file key > backup_before_optimize file key > default.
        """
        # auto_ env takes highest precedence
        auto_env = os.environ.get("MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE")
        if auto_env is not None:
            return auto_env.lower() in ("1", "true", "yes")
        # legacy env key
        env_val = os.environ.get("MEMPALACE_BACKUP_BEFORE_OPTIMIZE")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        # auto_ file key takes precedence over legacy file key
        if "auto_backup_before_optimize" in self._file_config:
            return bool(self._file_config["auto_backup_before_optimize"])
        return self._file_config.get("backup_before_optimize", DEFAULT_BACKUP_BEFORE_OPTIMIZE)

    @property
    def auto_backup_before_optimize(self) -> bool:
        """Preferred alias for backup_before_optimize. Returns the same value."""
        return self.backup_before_optimize

    @property
    def backup_dir(self) -> str | None:
        """Managed backup root: environment > config file > palace-local default.

        Expand ``~`` and relative paths like palace_path. Invalid explicit values
        raise instead of redirecting archives to another disk. JSON null is unset.
        """
        setting = "MEMPALACE_BACKUP_DIR"
        raw: object = os.environ.get(setting)
        if raw is None:
            setting = f"backup_dir in {self._config_file}"
            raw = self._file_config.get("backup_dir")
        if raw is None:
            return None
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise ValueError(f"Invalid {setting}: expected a non-empty path string without NUL.")
        return _configured_palace_path(raw, setting, noun="backup directory")

    def _env_setting(self, name: str) -> tuple[str, object]:
        """Return the ``(source label, raw value)`` level for an env var; blank means unset."""
        raw = os.environ.get(name)
        if raw is not None and not raw.strip():
            raw = None
        return (name, raw)

    def _backup_retain_count_setting(self) -> tuple[int, str]:
        return _resolve_setting(
            [
                self._env_setting("MEMPALACE_BACKUP_RETAIN_COUNT"),
                self._file_setting("backup_retain_count"),
            ],
            lambda raw: _parse_count_setting(raw, 0),
            lambda: (DEFAULT_BACKUP_RETAIN_COUNT, _IMPLICIT_RETENTION_SOURCE),
            lambda _value: "",
        )

    @property
    def backup_retain_count(self) -> int:
        """Raw explicit/global backup retain count; use retain_count_for_kind() for defaults."""
        return self._backup_retain_count_setting()[0]

    @property
    def _backup_retain_count_explicit(self) -> bool:
        """True when backup_retain_count was set via env var or config file (even if value is 0).

        An empty, unparseable, or negative value from either source is treated as not set
        (with a warning) so that typos and invalid config do not silently suppress implicit
        per-kind defaults; an invalid env value falls through to the config-file key.
        """
        return self._backup_retain_count_setting()[1] != _IMPLICIT_RETENTION_SOURCE

    def retain_count_for_kind(self, kind: str) -> int:
        """Return the applicable retain count for the given backup kind.

        When ``backup_retain_count`` is absent from both env and config file,
        ``scheduled`` maps to ``DEFAULT_SCHEDULED_RETAIN_COUNT`` (14),
        ``pre_optimize`` maps to ``DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT`` (5), and
        ``pre_watch`` maps to ``DEFAULT_PRE_WATCH_RETAIN_COUNT`` (5).
        An explicit ``backup_retain_count: 0`` (or ``MEMPALACE_BACKUP_RETAIN_COUNT=0``)
        is honoured as keep-all for every kind.  All other kinds (e.g. ``manual``)
        use ``backup_retain_count`` unchanged (0 by default).
        """
        if self._backup_retain_count_explicit:
            return self.backup_retain_count
        if kind == "pre_optimize":
            return DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT
        if kind == "pre_watch":
            return DEFAULT_PRE_WATCH_RETAIN_COUNT
        if kind == "scheduled":
            return DEFAULT_SCHEDULED_RETAIN_COUNT
        return self.backup_retain_count

    @property
    def backup_min_free_bytes(self) -> int:
        """Legacy backup floor setting alone; backup_disk_min_free_bytes is what backups use."""
        return _resolve_setting(
            [
                self._env_setting("MEMPALACE_BACKUP_MIN_FREE_BYTES"),
                self._file_setting("backup_min_free_bytes"),
            ],
            _parse_bytes_setting,
            lambda: (DEFAULT_BACKUP_MIN_FREE_BYTES, "the default"),
            _format_byte_setting,
        )[0]

    @property
    def backup_warn_size_bytes(self) -> int:
        """Archive size above which backup list marks the entry as oversized. 0 disables.

        Accepts the same byte values as the disk floors (plain integers or suffixes such
        as ``20KiB`` or ``2GiB``). Priority: MEMPALACE_BACKUP_WARN_SIZE_BYTES env >
        backup_warn_size_bytes file key > 0 (disabled).
        """
        return _resolve_setting(
            [
                self._env_setting("MEMPALACE_BACKUP_WARN_SIZE_BYTES"),
                self._file_setting("backup_warn_size_bytes"),
            ],
            _parse_bytes_setting,
            lambda: (DEFAULT_BACKUP_WARN_SIZE_BYTES, "the default (disabled)"),
            _format_byte_setting,
        )[0]

    @property
    def backup_schedule(self) -> str:
        """Scheduled backup frequency: off | daily | weekly | hourly."""
        env_val = os.environ.get("MEMPALACE_BACKUP_SCHEDULE")
        if env_val is not None:
            return env_val.lower()
        return self._file_config.get("backup_schedule", DEFAULT_BACKUP_SCHEDULE)

    def _optional_bool_setting(self, env_name: str, key: str, default: _T) -> bool | _T:
        """Resolve a boolean env var > config key > *default*, warning on invalid values."""
        return _resolve_setting(
            [self._env_setting(env_name), self._file_setting(key)],
            _parse_bool_setting,
            lambda: (default, "the default"),
            lambda value: "" if value is None else str(value).lower(),
        )[0]

    @property
    def spellcheck_enabled(self) -> bool | None:
        """Compatibility-only spellcheck setting: True, False, or None (unset, off).

        Every ingest mode is off by default, and the setting never changes stored text.
        """
        return self._optional_bool_setting(
            "MEMPALACE_SPELLCHECK_ENABLED", "spellcheck_enabled", DEFAULT_SPELLCHECK_ENABLED
        )

    @property
    def entity_detection(self) -> bool:
        """Whether init should run heuristic people/project detection."""
        return self._optional_bool_setting(
            "MEMPALACE_ENTITY_DETECTION", "entity_detection", DEFAULT_ENTITY_DETECTION
        )

    def _disk_floor_setting(self) -> tuple[int, str]:
        return _resolve_setting(
            [
                self._env_setting("MEMPALACE_DISK_MIN_FREE_BYTES"),
                self._file_setting("disk_min_free_bytes"),
            ],
            _parse_bytes_setting,
            lambda: (DEFAULT_DISK_MIN_FREE_BYTES, "disk_min_free_bytes (1 GiB default)"),
            _format_byte_setting,
        )

    @property
    def disk_min_free_bytes(self) -> int:
        """Global minimum free bytes required before any write-producing palace operation.

        Priority: MEMPALACE_DISK_MIN_FREE_BYTES env > disk_min_free_bytes file key > 1 GiB default.
        An invalid value is reported on stderr and resolution continues with the next level.
        """
        return self._disk_floor_setting()[0]

    @property
    def watch_disk_min_free_setting(self) -> tuple[int, str]:
        """Return ``(floor, source)`` for watch_disk_min_free_bytes.

        *source* names the env var or config key that set the floor, so a status or
        skip message can tell the user which setting to lower.
        """
        return _resolve_setting(
            [
                self._env_setting("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES"),
                self._file_setting("watch_disk_min_free_bytes"),
            ],
            _parse_bytes_setting,
            self._disk_floor_setting,
            _format_byte_setting,
        )

    @property
    def watch_disk_min_free_bytes(self) -> int:
        """Minimum free bytes required before each watcher mine/optimize cycle.

        Priority: MEMPALACE_WATCH_DISK_MIN_FREE_BYTES env > watch_disk_min_free_bytes file key
                  > disk_min_free_bytes (global). Invalid values warn and fall through.
        """
        return self.watch_disk_min_free_setting[0]

    @property
    def backup_disk_min_free_setting(self) -> tuple[int, str]:
        """Return ``(floor, source)`` for backup_disk_min_free_bytes.

        *source* names the env var or config key that set the floor, so a refusal can
        tell the user which setting to lower.
        """
        return _resolve_setting(
            [
                self._env_setting("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES"),
                self._env_setting("MEMPALACE_BACKUP_MIN_FREE_BYTES"),
                self._file_setting("backup_disk_min_free_bytes"),
                self._file_setting("backup_min_free_bytes"),
            ],
            _parse_bytes_setting,
            self._disk_floor_setting,
            _format_byte_setting,
        )

    @property
    def backup_disk_min_free_bytes(self) -> int:
        """Minimum projected free bytes remaining after backup archive creation.

        Priority: MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES env > legacy MEMPALACE_BACKUP_MIN_FREE_BYTES
                  env > backup_disk_min_free_bytes file key > legacy backup_min_free_bytes
                  file key > MEMPALACE_DISK_MIN_FREE_BYTES env > disk_min_free_bytes file key
                  > 1 GiB default. Invalid values warn and fall through to the next level.
        """
        return self.backup_disk_min_free_setting[0]

    @property
    def version_check_enabled(self) -> bool | None:
        """Tri-state version-check setting: True, False, or None (no explicit choice).

        Priority: MEMPALACE_VERSION_CHECK env > version_check_enabled file key > None.
        An invalid env value returns None here; version_check.resolve_config() owns the
        env precedence and fails closed on it. An invalid file value is reported on stderr.
        """
        env_val = os.environ.get("MEMPALACE_VERSION_CHECK")
        if env_val is not None:
            return parse_optional_bool(env_val)
        return _resolve_setting(
            [self._file_setting("version_check_enabled")],
            _parse_bool_setting,
            lambda: (DEFAULT_VERSION_CHECK_ENABLED, "the persisted choice"),
            lambda value: "" if value is None else str(value).lower(),
        )[0]

    @property
    def version_check_interval_hours(self) -> int:
        """Version-check interval in hours (a whole number of at least 1).

        Priority: MEMPALACE_VERSION_CHECK_INTERVAL_HOURS env > version_check_interval_hours
        file key > DEFAULT_VERSION_CHECK_INTERVAL_HOURS (168). An invalid or non-positive
        value is reported on stderr and resolution continues with the next level.
        """
        return _resolve_setting(
            [
                self._env_setting("MEMPALACE_VERSION_CHECK_INTERVAL_HOURS"),
                self._file_setting("version_check_interval_hours"),
            ],
            lambda raw: _parse_count_setting(raw, 1),
            lambda: (DEFAULT_VERSION_CHECK_INTERVAL_HOURS, "the default"),
            lambda value: f"{value} hours",
        )[0]

    @property
    def scan_skip_dirs(self) -> ScanSkipList:
        """Directory basenames excluded from scan_project() and watcher filtering."""
        raw = self._file_config.get("scan_skip_dirs", DEFAULT_SCAN_SKIP_DIRS)
        return _normalize_scan_list(raw, DEFAULT_SCAN_SKIP_DIRS)

    @property
    def scan_skip_files(self) -> ScanSkipList:
        """File basenames excluded from scan_project() and watcher filtering."""
        raw = self._file_config.get("scan_skip_files", DEFAULT_SCAN_SKIP_FILES)
        return _normalize_scan_list(raw, DEFAULT_SCAN_SKIP_FILES)

    @property
    def scan_skip_globs(self) -> ScanSkipList:
        """Project-relative POSIX glob patterns excluded during scanning."""
        raw = self._file_config.get("scan_skip_globs", DEFAULT_SCAN_SKIP_GLOBS)
        return _normalize_scan_list(raw, DEFAULT_SCAN_SKIP_GLOBS)

    def init(self) -> Path:
        """Create config directory and write default config.json if it doesn't exist.

        ``mempalace-code init`` does not call this: every setting already has a default
        when config.json is absent, and init writes only project configuration.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if not self._config_file.exists():
            default_config: ConfigPayload = {
                "palace_path": DEFAULT_PALACE_PATH,
                "entity_detection": DEFAULT_ENTITY_DETECTION,
                "scan_skip_dirs": DEFAULT_SCAN_SKIP_DIRS,
                "scan_skip_files": DEFAULT_SCAN_SKIP_FILES,
                "scan_skip_globs": DEFAULT_SCAN_SKIP_GLOBS,
            }
            with open(self._config_file, "w") as f:
                json.dump(default_config, f, indent=2)
        return self._config_file

    def save_people_map(self, people_map: PeopleMap) -> Path:
        """Write people_map.json to config directory.

        Args:
            people_map: Dict mapping name variants to canonical names.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._people_map_file.lstat()
        except FileNotFoundError:
            pass
        else:
            try:
                if not stat.S_ISREG(self._people_map_file.stat().st_mode):
                    raise OSError("people_map.json is not a regular file")
                with open(self._people_map_file, "r") as f:
                    json.load(f)
            except (json.JSONDecodeError, UnicodeError, OSError) as exc:
                raise RuntimeError(
                    f"Refusing to overwrite {self._people_map_file}: the existing path is the "
                    "recovery source. Repair or move it, then retry save_people_map()."
                ) from exc

        with open(self._people_map_file, "w") as f:
            json.dump(people_map, f, indent=2)
        return self._people_map_file


def _normalize_scan_list(value: object, default: ScanSkipList) -> ScanSkipList:
    """Normalize a scan_skip_* config value to a deduplicated list of non-empty strings.

    Accepts list/tuple; non-string items are dropped (silent coercion would turn
    ``None``/``123`` into bogus exclusion entries). Falls back to default when the
    top-level value has the wrong type.
    """
    if not isinstance(value, (list, tuple)):
        return list(default)
    items = cast("Sequence[object]", value)
    seen: set[str] = set()
    result: ScanSkipList = []
    for item in items:
        if not isinstance(item, str):
            continue
        entry = item.strip()
        if entry and entry not in seen:
            seen.add(entry)
            result.append(entry)
    return result


def parse_optional_bool(value: object) -> bool | None:
    """Parse bool-like config values, returning None for unset/invalid values.

    Accepts a bool or the case-insensitive strings 1/0, true/false, yes/no, on/off.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return None
