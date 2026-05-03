"""
MemPalace configuration system.

Priority: env vars > config file (~/.mempalace/config.json) > defaults
"""

import json
import os
from pathlib import Path

DEFAULT_PALACE_PATH = os.path.expanduser("~/.mempalace/palace")
DEFAULT_COLLECTION_NAME = "mempalace_drawers"

# Storage safety defaults
DEFAULT_OPTIMIZE_AFTER_MINE = True  # Set False to disable auto-compaction
DEFAULT_BACKUP_BEFORE_OPTIMIZE = True  # Auto-backup before risky operations (on by default)
DEFAULT_BACKUP_RETAIN_COUNT = 0  # 0 keeps all backups per-kind (backwards compatible)
DEFAULT_BACKUP_SCHEDULE = "off"  # Scheduled backup frequency: off|daily|weekly|hourly
DEFAULT_BACKUP_MIN_FREE_BYTES = (
    0  # 0 disables the disk-space guard; set e.g. 1_073_741_824 for 1 GiB
)
DEFAULT_BACKUP_WARN_SIZE_BYTES = (
    0  # 0 disables oversized-archive warnings; set e.g. 2_147_483_648 for 2 GiB
)
DEFAULT_SPELLCHECK_ENABLED = None  # None lets each ingest mode choose its own default
DEFAULT_ENTITY_DETECTION = False

# Disk-budget safety defaults
DEFAULT_DISK_MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB

DEFAULT_SCAN_SKIP_DIRS = [".kotlin-lsp"]
DEFAULT_SCAN_SKIP_FILES = []
DEFAULT_SCAN_SKIP_GLOBS = []

DEFAULT_TOPIC_WINGS = [
    "emotions",
    "consciousness",
    "memory",
    "technical",
    "identity",
    "family",
    "creative",
]

DEFAULT_HALL_KEYWORDS = {
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


class MempalaceConfig:
    """Configuration manager for MemPalace.

    Load order: env vars > config file > defaults.
    """

    def __init__(self, config_dir=None):
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
        self._file_config = {}

        if self._config_file.exists():
            try:
                with open(self._config_file, "r") as f:
                    self._file_config = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._file_config = {}

    @property
    def palace_path(self):
        """Path to the memory palace data directory."""
        env_val = os.environ.get("MEMPALACE_PALACE_PATH") or os.environ.get("MEMPAL_PALACE_PATH")
        if env_val:
            return env_val
        return self._file_config.get("palace_path", DEFAULT_PALACE_PATH)

    @property
    def collection_name(self):
        """ChromaDB collection name."""
        return self._file_config.get("collection_name", DEFAULT_COLLECTION_NAME)

    @property
    def people_map(self):
        """Mapping of name variants to canonical names."""
        if self._people_map_file.exists():
            try:
                with open(self._people_map_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return self._file_config.get("people_map", {})

    @property
    def topic_wings(self):
        """List of topic wing names."""
        return self._file_config.get("topic_wings", DEFAULT_TOPIC_WINGS)

    @property
    def hall_keywords(self):
        """Mapping of hall names to keyword lists."""
        return self._file_config.get("hall_keywords", DEFAULT_HALL_KEYWORDS)

    @property
    def optimize_after_mine(self):
        """Whether to run optimize() after mining. Disable to prevent compaction corruption."""
        env_val = os.environ.get("MEMPALACE_OPTIMIZE_AFTER_MINE")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        return self._file_config.get("optimize_after_mine", DEFAULT_OPTIMIZE_AFTER_MINE)

    @property
    def backup_before_optimize(self):
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
    def auto_backup_before_optimize(self):
        """Preferred alias for backup_before_optimize. Returns the same value."""
        return self.backup_before_optimize

    @property
    def backup_retain_count(self):
        """Number of pre-optimize backups to retain. 0 disables pruning."""
        raw_value = os.environ.get("MEMPALACE_BACKUP_RETAIN_COUNT")
        if raw_value is None:
            raw_value = self._file_config.get("backup_retain_count", DEFAULT_BACKUP_RETAIN_COUNT)

        try:
            retain_count = int(raw_value)
        except (TypeError, ValueError):
            return DEFAULT_BACKUP_RETAIN_COUNT

        if retain_count < 0:
            return DEFAULT_BACKUP_RETAIN_COUNT
        return retain_count

    @property
    def backup_min_free_bytes(self):
        """Minimum free bytes required before creating a backup. 0 disables the disk guard."""
        raw_value = os.environ.get("MEMPALACE_BACKUP_MIN_FREE_BYTES")
        if raw_value is None:
            raw_value = self._file_config.get(
                "backup_min_free_bytes", DEFAULT_BACKUP_MIN_FREE_BYTES
            )
        try:
            val = int(raw_value)
        except (TypeError, ValueError):
            return DEFAULT_BACKUP_MIN_FREE_BYTES
        return max(0, val)

    @property
    def backup_warn_size_bytes(self):
        """Archive size above which backup list marks the entry as oversized. 0 disables."""
        raw_value = os.environ.get("MEMPALACE_BACKUP_WARN_SIZE_BYTES")
        if raw_value is None:
            raw_value = self._file_config.get(
                "backup_warn_size_bytes", DEFAULT_BACKUP_WARN_SIZE_BYTES
            )
        try:
            val = int(raw_value)
        except (TypeError, ValueError):
            return DEFAULT_BACKUP_WARN_SIZE_BYTES
        return max(0, val)

    @property
    def backup_schedule(self):
        """Scheduled backup frequency: off | daily | weekly | hourly."""
        env_val = os.environ.get("MEMPALACE_BACKUP_SCHEDULE")
        if env_val is not None:
            return env_val.lower()
        return self._file_config.get("backup_schedule", DEFAULT_BACKUP_SCHEDULE)

    @property
    def spellcheck_enabled(self):
        """Tri-state spellcheck setting: True, False, or None for mode defaults."""
        env_val = os.environ.get("MEMPALACE_SPELLCHECK_ENABLED")
        if env_val is not None:
            parsed = _parse_optional_bool(env_val)
            if parsed is not None:
                return parsed
            return DEFAULT_SPELLCHECK_ENABLED

        if "spellcheck_enabled" in self._file_config:
            parsed = _parse_optional_bool(self._file_config["spellcheck_enabled"])
            if parsed is not None:
                return parsed

        return DEFAULT_SPELLCHECK_ENABLED

    @property
    def entity_detection(self):
        """Whether init should run heuristic people/project detection."""
        env_val = os.environ.get("MEMPALACE_ENTITY_DETECTION")
        if env_val is not None:
            parsed = _parse_optional_bool(env_val)
            if parsed is not None:
                return parsed
            return DEFAULT_ENTITY_DETECTION

        if "entity_detection" in self._file_config:
            parsed = _parse_optional_bool(self._file_config["entity_detection"])
            if parsed is not None:
                return parsed
        return DEFAULT_ENTITY_DETECTION

    def _parse_bytes_config(self, raw) -> int:
        """Parse a bytes value from int/str, falling back to DEFAULT_DISK_MIN_FREE_BYTES on error."""
        from .disk_budget import parse_bytes as _parse_bytes

        if raw is None:
            return DEFAULT_DISK_MIN_FREE_BYTES
        try:
            return _parse_bytes(raw)
        except (ValueError, TypeError):
            return DEFAULT_DISK_MIN_FREE_BYTES

    @property
    def disk_min_free_bytes(self) -> int:
        """Global minimum free bytes required before any write-producing palace operation.

        Priority: MEMPALACE_DISK_MIN_FREE_BYTES env > disk_min_free_bytes file key > 1 GiB default.
        """
        raw = os.environ.get("MEMPALACE_DISK_MIN_FREE_BYTES")
        if raw is None:
            raw = self._file_config.get("disk_min_free_bytes")
        return self._parse_bytes_config(raw)

    @property
    def watch_disk_min_free_bytes(self) -> int:
        """Minimum free bytes required before each watcher mine/optimize cycle.

        Priority: MEMPALACE_WATCH_DISK_MIN_FREE_BYTES env > watch_disk_min_free_bytes file key
                  > disk_min_free_bytes (global).
        """
        raw = os.environ.get("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES")
        if raw is not None:
            return self._parse_bytes_config(raw)
        if "watch_disk_min_free_bytes" in self._file_config:
            return self._parse_bytes_config(self._file_config["watch_disk_min_free_bytes"])
        return self.disk_min_free_bytes

    @property
    def backup_disk_min_free_bytes(self) -> int:
        """Minimum projected free bytes remaining after backup archive creation.

        Priority: MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES env > backup_disk_min_free_bytes file key
                  > legacy MEMPALACE_BACKUP_MIN_FREE_BYTES env > legacy backup_min_free_bytes
                  file key > disk_min_free_bytes (global).
        """
        raw = os.environ.get("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES")
        if raw is not None:
            return self._parse_bytes_config(raw)
        raw = os.environ.get("MEMPALACE_BACKUP_MIN_FREE_BYTES")
        if raw is not None:
            return self._parse_bytes_config(raw)
        if "backup_disk_min_free_bytes" in self._file_config:
            return self._parse_bytes_config(self._file_config["backup_disk_min_free_bytes"])
        if "backup_min_free_bytes" in self._file_config:
            return self._parse_bytes_config(self._file_config["backup_min_free_bytes"])
        return self.disk_min_free_bytes

    @property
    def scan_skip_dirs(self) -> list:
        """Directory basenames excluded from scan_project() and watcher filtering."""
        raw = self._file_config.get("scan_skip_dirs", DEFAULT_SCAN_SKIP_DIRS)
        return _normalize_scan_list(raw, DEFAULT_SCAN_SKIP_DIRS)

    @property
    def scan_skip_files(self) -> list:
        """File basenames excluded from scan_project() and watcher filtering."""
        raw = self._file_config.get("scan_skip_files", DEFAULT_SCAN_SKIP_FILES)
        return _normalize_scan_list(raw, DEFAULT_SCAN_SKIP_FILES)

    @property
    def scan_skip_globs(self) -> list:
        """Project-relative POSIX glob patterns excluded during scanning."""
        raw = self._file_config.get("scan_skip_globs", DEFAULT_SCAN_SKIP_GLOBS)
        return _normalize_scan_list(raw, DEFAULT_SCAN_SKIP_GLOBS)

    def init(self):
        """Create config directory and write default config.json if it doesn't exist."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if not self._config_file.exists():
            default_config = {
                "palace_path": DEFAULT_PALACE_PATH,
                "collection_name": DEFAULT_COLLECTION_NAME,
                "entity_detection": DEFAULT_ENTITY_DETECTION,
                "topic_wings": DEFAULT_TOPIC_WINGS,
                "hall_keywords": DEFAULT_HALL_KEYWORDS,
                "scan_skip_dirs": DEFAULT_SCAN_SKIP_DIRS,
                "scan_skip_files": DEFAULT_SCAN_SKIP_FILES,
                "scan_skip_globs": DEFAULT_SCAN_SKIP_GLOBS,
            }
            with open(self._config_file, "w") as f:
                json.dump(default_config, f, indent=2)
        return self._config_file

    def save_people_map(self, people_map):
        """Write people_map.json to config directory.

        Args:
            people_map: Dict mapping name variants to canonical names.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._people_map_file, "w") as f:
            json.dump(people_map, f, indent=2)
        return self._people_map_file


def _normalize_scan_list(value, default: list) -> list:
    """Normalize a scan_skip_* config value to a deduplicated list of non-empty strings.

    Accepts list/tuple; non-string items are dropped (silent coercion would turn
    ``None``/``123`` into bogus exclusion entries). Falls back to default when the
    top-level value has the wrong type.
    """
    if not isinstance(value, (list, tuple)):
        return list(default)
    seen: set = set()
    result = []
    for item in value:
        if not isinstance(item, str):
            continue
        entry = item.strip()
        if entry and entry not in seen:
            seen.add(entry)
            result.append(entry)
    return result


def _parse_optional_bool(value):
    """Parse bool-like config values, returning None for unset/invalid values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return None
